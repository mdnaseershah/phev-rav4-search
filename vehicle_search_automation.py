#!/usr/bin/env python3
"""
vehicle_search_automation.py

Full replacement: conservative scraper + HTML/email generator.
- Populates LISTINGS[*]['url'] with real listing URLs when available (AutoTrader, Kijiji, CarGurus, Clutch.ca, Facebook Marketplace, dealer sites).
- Stricter link selection to avoid landing on unrelated listings (e.g. editorial/review articles, wrong vehicle trims).
- Preserves email layout, fonts, colors, and behavior (marketplace buttons moved to bottom, with pre-filled filters and year ranges).
- Generates gatineau_phev_rav4_search_results.html and dealers.html and sends email if credentials provided.
- Scheduled to run at 7 AM Gatineau (US/Eastern) time year-round; see main() for the DST-safe guard.

Usage:
- Place dealers.json in repo root (optional but recommended).
- Install requirements: requests, beautifulsoup4, lxml, tqdm, pytz
- To test locally: set ENABLE_SCRAPE=1 and run the script.
"""

from __future__ import annotations
import os
import time
import json
import re
import urllib.parse
import requests
import pytz
from datetime import datetime
from bs4 import BeautifulSoup
from tqdm import tqdm
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.encoders import encode_base64
import smtplib

# -------------------------
# Configuration / Env
# -------------------------
GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS')
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
EST = pytz.timezone('US/Eastern')

# Set by the GitHub Actions workflow (github.event_name). Empty when run locally.
GITHUB_EVENT_NAME = os.getenv('GITHUB_EVENT_NAME', '')

ENABLE_SCRAPE = os.getenv('ENABLE_SCRAPE', '0') == '1'
REQUEST_DELAY = float(os.getenv('REQUEST_DELAY', '1.0'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '2'))

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
}

DEALERS_JSON = "dealers.json"  # optional: full dealers list

# -------------------------
# Vehicles to find (you can extend)
# -------------------------
WANTED_VEHICLES = [
    {
        "vehicle": "Mitsubishi Outlander PHEV",
        "make": "Mitsubishi",
        "model": "Outlander PHEV",
        "year_min": 2022,
        "year_max": 2023,
        "aliases": ["outlander phev", "outlander plug-in", "outlander plug in", "outlander hybrid"],
        "cargurus_entity": "d2652",
    },
    {
        "vehicle": "Toyota RAV4 Prime",
        "make": "Toyota",
        "model": "RAV4 Prime",
        "year_min": 2022,
        "year_max": 2023,
        "aliases": ["rav4 prime", "rav 4 prime", "rav4 plug-in", "rav4 plug in", "rav4 phev", "rav4 plug-in hybrid"],
        "cargurus_entity": "d2992",
    },
]

# -------------------------
# Placeholder LISTINGS (kept for backward compatibility)
# These will be updated by the scraper when ENABLE_SCRAPE=1
# -------------------------
LISTINGS = [
    {
        "vehicle": "Mitsubishi Outlander PHEV",
        "price": "$39,900",
        "mileage": "12,000 km",
        "sunroof": "No",
        "city": "Gatineau, QC",
        "distance_km": 6.5,
        "dealer_name": "Rallye Mitsubishi",
        "dealer_rating": "4.2",
        "url": "https://example.com/listing/outlander-1"
    },
    {
        "vehicle": "Toyota RAV4 Prime",
        "price": "$49,500",
        "mileage": "5,000 km",
        "sunroof": "Yes",
        "city": "Ottawa, ON",
        "distance_km": 11.9,
        "dealer_name": "Bel-Air Toyota",
        "dealer_rating": "4.6",
        "url": "https://example.com/listing/rav4-1"
    },
]

# -------------------------
# Dealers (fallback if dealers.json missing)
# -------------------------
DEALERS = [
    {"name": "Toyota Gatineau", "brand": "Toyota", "city": "Gatineau, QC", "distance_km": 2.1, "website": "https://www.toyotagatineau.ca"},
    {"name": "Rallye Mitsubishi", "brand": "Mitsubishi", "city": "Gatineau, QC", "distance_km": 6.5, "website": "https://www.rallyemitsubishi.ca"},
]

# -------------------------
# HTTP helpers
# -------------------------
def http_get(url, headers=None, timeout=15):
    headers = headers or DEFAULT_HEADERS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return resp.text
        except Exception as e:
            print(f"HTTP GET attempt {attempt} failed for {url}: {e}")
            time.sleep(REQUEST_DELAY * attempt)
    return None

# -------------------------
# Shared filter: pages that are never real listings
# -------------------------
NON_LISTING_HREF_MARKERS = (
    "/editorial/", "/expert-reviews/", "/research/", "/news/",
    "/reviews/", "/help", "/about", "/blog/",
)

def _is_listing_candidate(href: str) -> bool:
    if not href:
        return False
    low = href.lower()
    return not any(marker in low for marker in NON_LISTING_HREF_MARKERS)


def _extract_year(text):
    """Return the first plausible 4-digit model year found in text, or None."""
    if not text:
        return None
    match = re.search(r"\b(19[9]\d|20[0-3]\d)\b", str(text))
    return match.group(0) if match else None


def _year_ok(candidate_text, year):
    """True unless the candidate clearly shows a different model year than wanted.
    Accepts when no year is present (can't tell); rejects only on a clear mismatch."""
    if not year:
        return True
    found = _extract_year(candidate_text or "")
    if found is None:
        return True
    return found == str(year)


def _year_in_range(candidate_text, year_min, year_max):
    """True unless the candidate clearly shows a year outside [year_min, year_max].
    Accepts when no year is present (can't tell)."""
    found = _extract_year(candidate_text or "")
    if found is None:
        return True
    try:
        y = int(found)
    except (TypeError, ValueError):
        return True
    return year_min <= y <= year_max


LOCAL_MARKERS = (
    "gatineau", "ottawa", "quebec", "-qc", " qc", "/qc", "outaouais",
    "hull", "aylmer", "chelsea", "cantley", "buckingham",
)


def _looks_local(candidate_text):
    """True if the listing text/href suggests the Gatineau-Ottawa area (best-effort)."""
    low = (candidate_text or "").lower()
    return any(marker in low for marker in LOCAL_MARKERS)


def _parse_money(text):
    """Parse a price like '$39,900' into a float, or None."""
    if not text:
        return None
    digits = re.sub(r"[^0-9.]", "", str(text))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def _parse_km(text):
    """Parse a mileage like '12,000 km' into a float, or None."""
    if not text:
        return None
    digits = re.sub(r"[^0-9.]", "", str(text))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


MAX_MILEAGE_KM = 80000  # hard requirement: mileage must be under 80,000 km

def _mileage_ok(listing):
    """True unless the listing clearly exceeds MAX_MILEAGE_KM. Unknown mileage is allowed."""
    km = _parse_km(listing.get("mileage"))
    if km is None:
        return True
    return km < MAX_MILEAGE_KM

def _listing_value_score(listing):
    """Best price-to-value sort key (lower ranks higher / is better).

    Ordering priority:
      1. Listings within the mileage cap rank ahead of those over it.
      2. Lower price-plus-mileage cost ranks higher.
      3. A sunroof is preferred, so it lowers the effective cost slightly (tie-breaker).
    Missing price sorts to the end."""
    price = _parse_money(listing.get("price"))
    km = _parse_km(listing.get("mileage"))
    over_cap = 0 if (km is None or km < MAX_MILEAGE_KM) else 1
    if price is None:
        return (over_cap, float("inf"), float("inf"))
    km_penalty = (km or 0) * 0.05
    sunroof = str(listing.get("sunroof", "")).strip().lower() in ("yes", "y", "true")
    sunroof_bonus = -500 if sunroof else 0  # sunroof preferred: nudge it ahead of an equal car without one
    return (over_cap, price + km_penalty + sunroof_bonus, km if km is not None else float("inf"))

# -------------------------
# Marketplace-specific builders/parsers (STRICTER)
# -------------------------
def build_autotrader_search_url(make: str, model: str, location="Gatineau, QC"):
    make_slug = urllib.parse.quote(make.lower())
    model_slug = urllib.parse.quote(model.lower().replace(" ", "-"))
    loc_q = urllib.parse.quote(location)
    return f"https://www.autotrader.ca/cars/{make_slug}/{model_slug}/?loc={loc_q}&prx=400"


def build_kijiji_search_url(query: str):
    kw = urllib.parse.quote(query.strip().lower().replace(" ", "-"))
    return f"https://www.kijiji.ca/b-cars-trucks/gatineau-quebec/{kw}/k0c174l1700184?rb=true"


def build_cargurus_search_url(make: str, model: str, entity: str = ""):
    if entity:
        return (f"https://www.cargurus.ca/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action"
                f"?sourceContext=carGurusHomePageModel&entitySelectingHelper.selectedEntity={entity}"
                f"&zip=J8T&distance=400")
    kw = urllib.parse.quote(f"{make} {model}")
    return f"https://www.cargurus.ca/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action?zip=J8T&distance=400&keywords={kw}"


def build_clutch_search_url(make: str, model: str):
    kw = urllib.parse.quote(f"{make} {model}".strip())
    return f"https://clutch.ca/cars?keyword={kw}"


def build_facebook_marketplace_search_url(query: str):
    kw = urllib.parse.quote(f"{query.strip()} Gatineau")
    return f"https://www.facebook.com/marketplace/search/?query={kw}"


# --- STRICTER: build_marketplace_search_url ---
def build_marketplace_search_url(vehicle_name: str, prefer: str = "autotrader") -> str:
    s = vehicle_name.strip()
    year_match = re.match(r'^(19|20)\d{2}', s)
    year = year_match.group(0) if year_match else ""
    tokens = s.split()
    if year:
        tokens = tokens[1:]
    make = tokens[0] if len(tokens) >= 1 else ""
    model = " ".join(tokens[1:3]) if len(tokens) >= 3 else " ".join(tokens[1:]) if len(tokens) >= 2 else ""
    trim = " ".join(tokens[2:]) if len(tokens) >= 3 else ""
    keyword_parts = []
    if year:
        keyword_parts.append(year)
    if make:
        keyword_parts.append(make)
    if model:
        keyword_parts.append(model)
    if trim:
        keyword_parts.append(trim)
    keyword = " ".join([p for p in keyword_parts if p]).strip()
    q = urllib.parse.quote_plus(keyword)

    if prefer == "autotrader":
        make_q = urllib.parse.quote_plus(make)
        model_q = urllib.parse.quote_plus(model)
        if model_q:
            return f"https://www.autotrader.ca/cars/{make_q}/{model_q}/?loc=Gatineau%2C+QC&prx=400"
        return f"https://www.autotrader.ca/cars/?kw={q}&loc=Gatineau%2C+QC&prx=400"
    elif prefer == "kijiji":
        return f"https://www.kijiji.ca/b-cars-trucks/canada/{q}/k0c174l1700199?address=Gatineau%2C+QC&radius=400.0"
    else:
        return f"https://www.google.com/search?q={q}+Gatineau+cars"

# --- FIXED: parse_autotrader_first_listing ---
def _model_tokens(model, aliases):
    """Token groups identifying the wanted model; match if ALL tokens in ANY group are present."""
    groups = [model.lower().split()]
    for a in (aliases or []):
        groups.append(a.lower().split())
    return groups


def _matches_model(text, make, token_groups):
    """True if text contains the make and all tokens of at least one alias group."""
    low = (text or "").lower()
    if make and make.lower() not in low:
        return False
    return any(all(tok in low for tok in grp) for grp in token_groups if grp)


def _pick_listing(html_text, base_url, path_markers, make, model, year_min, year_max, aliases):
    """Shared listing picker: first real listing anchor matching make+model(or alias)
    within the year range whose path looks like a listing. Prefers local (Gatineau/Ottawa) matches."""
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "lxml")
    token_groups = _model_tokens(model, aliases)
    fallback = None
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        if not _is_listing_candidate(href):
            continue
        low_href = href.lower()
        if path_markers and not any(pm in low_href for pm in path_markers):
            continue
        text = a.get_text(" ", strip=True) or ""
        blob = text + " " + href
        if not _matches_model(blob, make, token_groups):
            continue
        if not _year_in_range(blob, year_min, year_max):
            continue
        full = urllib.parse.urljoin(base_url, href)
        if _looks_local(blob):
            return full
        if fallback is None:
            fallback = full
    return fallback


def parse_autotrader_first_listing(html_text, make, model, year_min, year_max, aliases=None):
    return _pick_listing(html_text, "https://www.autotrader.ca", ("/a/", "/cars/"),
                         make, model, year_min, year_max, aliases)


def parse_kijiji_first_listing(html_text, make, model, year_min, year_max, aliases=None):
    return _pick_listing(html_text, "https://www.kijiji.ca",
                         ("/v-cars-trucks", "/v-autos", "/v-view-details.html"),
                         make, model, year_min, year_max, aliases)


def parse_cargurus_first_listing(html_text, make, model, year_min, year_max, aliases=None):
    return _pick_listing(html_text, "https://www.cargurus.ca", ("/cars/", "inventorylisting"),
                         make, model, year_min, year_max, aliases)


def parse_clutch_first_listing(html_text, make, model, year_min, year_max, aliases=None):
    return _pick_listing(html_text, "https://clutch.ca", ("/cars/",),
                         make, model, year_min, year_max, aliases)


def parse_facebook_first_listing(html_text):
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "lxml")
    for a in soup.select("a[href*='/marketplace/item/']"):
        href = a.get("href", "")
        if href:
            return urllib.parse.urljoin("https://www.facebook.com", href)
    return None

# -------------------------
# Dealer site probing heuristics
# -------------------------
COMMON_INVENTORY_PATHS = [
    "/inventory", "/used-inventory", "/used-cars", "/new-inventory", "/vehicles", "/cars", "/search", "/inventory/used", "/used"
]

def probe_dealer_for_listing(dealer_website: str, make: str, model: str):
    if not dealer_website:
        return None
    base = dealer_website.rstrip("/")
    for path in COMMON_INVENTORY_PATHS:
        url = base + path
        html = http_get(url)
        if not html:
            continue
        found = find_listing_in_html(html, base, make, model)
        if found:
            return found
    search_patterns = ["/search?q=", "/search?query=", "/inventory?search=", "/vehicles?search="]
    q = urllib.parse.quote_plus(f"{make} {model}")
    for p in search_patterns:
        url = f"{base}{p}{q}"
        html = http_get(url)
        if not html:
            continue
        found = find_listing_in_html(html, base, make, model)
        if found:
            return found
    html = http_get(base)
    if html:
        found = find_listing_in_html(html, base, make, model)
        if found:
            return found
    return None

def find_listing_in_html(html_text: str, base_url: str, make: str, model: str):
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "lxml")
    tokens = [make.lower(), model.lower()]
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        text = (a.get_text(" ", strip=True) or "").lower()
        if not href or not _is_listing_candidate(href):
            continue
        if all(tok in text for tok in tokens if tok):
            return urllib.parse.urljoin(base_url, href)
        if any(tok in href.lower() for tok in tokens):
            return urllib.parse.urljoin(base_url, href)
    for card in soup.select("[data-vin], [data-listing-id], .inventory-item, .vehicle-card"):
        a = card.find("a", href=True)
        if a:
            href = a["href"]
            text = (a.get_text(" ", strip=True) or "").lower()
            if not _is_listing_candidate(href):
                continue
            if all(tok in text for tok in tokens) or any(tok in href.lower() for tok in tokens):
                return urllib.parse.urljoin(base_url, href)
    return None

# -------------------------
# Orchestration: find real listing URLs
# -------------------------
def load_dealers_from_file():
    if os.path.exists(DEALERS_JSON):
        try:
            with open(DEALERS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                print(f"Loaded {len(data)} dealers from {DEALERS_JSON}")
                return data
        except Exception as e:
            print(f"Failed to load {DEALERS_JSON}: {e}")
    return DEALERS

def generate_marketplace_search_url(vehicle_name: str):
    return build_marketplace_search_url(vehicle_name, prefer="autotrader")

def scrape_and_populate_listings():
    dealers = load_dealers_from_file()
    dealer_sites = []
    for d in dealers:
        site = d.get("website")
        if site and site not in dealer_sites:
            dealer_sites.append(site)

    found_map = {}
    for wanted in WANTED_VEHICLES:
        vehicle_name = wanted.get("vehicle")
        make = wanted.get("make", "")
        model = wanted.get("model", "")
        year_min = wanted.get("year_min", datetime.now().year - 1)
        year_max = wanted.get("year_max", datetime.now().year)
        aliases = wanted.get("aliases", [])
        print(f"Searching marketplaces for: {vehicle_name}")

        at_url = build_autotrader_search_url(make, model)
        at_html = http_get(at_url)
        at_listing = parse_autotrader_first_listing(at_html, make, model, year_min, year_max, aliases)
        if at_listing:
            print(f"  AutoTrader -> {at_listing}")
            found_map[vehicle_name] = at_listing
            continue

        cg_url = build_cargurus_search_url(make, model)
        cg_html = http_get(cg_url)
        cg_listing = parse_cargurus_first_listing(cg_html, make, model, year_min, year_max, aliases)
        if cg_listing:
            print(f"  CarGurus -> {cg_listing}")
            found_map[vehicle_name] = cg_listing
            continue

        kj_url = build_kijiji_search_url(f"{make} {model}")
        kj_html = http_get(kj_url)
        kj_listing = parse_kijiji_first_listing(kj_html, make, model, year_min, year_max, aliases)
        if kj_listing:
            print(f"  Kijiji -> {kj_listing}")
            found_map[vehicle_name] = kj_listing
            continue

        clutch_url = build_clutch_search_url(make, model)
        clutch_html = http_get(clutch_url)
        clutch_listing = parse_clutch_first_listing(clutch_html, make, model, year_min, year_max, aliases)
        if clutch_listing:
            print(f"  Clutch.ca -> {clutch_listing}")
            found_map[vehicle_name] = clutch_listing
            continue

        fb_url = build_facebook_marketplace_search_url(f"{make} {model}")
        fb_html = http_get(fb_url)
        fb_listing = parse_facebook_first_listing(fb_html)
        if fb_listing:
            print(f"  Facebook Marketplace -> {fb_listing}")
            found_map[vehicle_name] = fb_listing
            continue

        print("  Probing local dealer websites for direct listings (this may take a while)...")
        for site in tqdm(dealer_sites, desc="Probing dealers", unit="site"):
            try:
                found = probe_dealer_for_listing(site, make, model)
                if found:
                    print(f"  Found on dealer site {site} -> {found}")
                    found_map[vehicle_name] = found
                    break
            except Exception as e:
                print(f"  Probe failed for {site}: {e}")
        if vehicle_name not in found_map:
            fallback = generate_marketplace_search_url(vehicle_name)
            print(f"  No direct listing found; using fallback search URL: {fallback}")
            found_map[vehicle_name] = fallback

    for entry in LISTINGS:
        name = entry.get("vehicle", "")
        if name in found_map:
            entry["url"] = found_map[name]
            print(f"Updated LISTINGS url for '{name}' -> {entry['url']}")
        else:
            raw = entry.get("url", "") or ""
            if not raw or "example.com" in raw:
                entry["url"] = generate_marketplace_search_url(name)
                print(f"Set fallback search URL for '{name}' -> {entry['url']}")

# -------------------------
# HTML generation
# -------------------------
def generate_dealers_html():
    rows = []
    dealers = load_dealers_from_file()
    for d in dealers:
        rows.append(f"""
        <tr>
            <td><a href="{d.get('website','#')}" target="_blank" rel="noopener">{d.get('name','')}</a></td>
            <td>{d.get('brand','')}</td>
            <td>{d.get('city','')}</td>
            <td>{d.get('distance_km','')} km</td>
        </tr>
        """)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>All Dealers</title>
<style>
body{{font-family:Arial,sans-serif;margin:20px;color:#333}}
h2{{color:#2563eb}}
table{{width:100%;border-collapse:collapse;margin-top:20px}}
th,td{{padding:10px;border:1px solid #ddd;text-align:left}}
th{{background:#f0f0f0;font-weight:bold}}
a{{color:#2563eb;text-decoration:none}}
a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<h2>All Dealers ({len(dealers)} total)</h2>
<p>Click any dealer name to open their website.</p>
<table>
<thead><tr><th>Dealer</th><th>Brand</th><th>City</th><th>Distance</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</body>
</html>
"""
    return html

def generate_email_html(est_now):
    buttons_html = ""
    for wanted in WANTED_VEHICLES:
        v_name = wanted["vehicle"]
        make = wanted["make"]
        model = wanted["model"]
        yr1 = wanted.get("year_min", datetime.now().year - 1)
        yr2 = wanted.get("year_max", datetime.now().year)
        cg_entity = wanted.get("cargurus_entity", "")

        make_slug = urllib.parse.quote(make.lower())
        model_slug = urllib.parse.quote(model.lower().replace(" ", "-"))
        kw = f"{make} {model}"
        kw_q = urllib.parse.quote(kw)
        kw_hyphen = urllib.parse.quote(kw.lower().replace(" ", "-"))
        loc_q = urllib.parse.quote("Gatineau, QC")

        at_url = f"https://www.autotrader.ca/cars/{make_slug}/{model_slug}/?loc={loc_q}&prx=400&yr1={yr1}&yr2={yr2}"
        if cg_entity:
            cg_url = f"https://www.cargurus.ca/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action?sourceContext=carGurusHomePageModel&entitySelectingHelper.selectedEntity={cg_entity}&zip=J8T&distance=400&minYear={yr1}&maxYear={yr2}"
        else:
            cg_url = f"https://www.cargurus.ca/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action?zip=J8T&distance=400&keywords={kw_q}"
        kj_url = f"https://www.kijiji.ca/b-cars-trucks/gatineau-quebec/{kw_hyphen}/k0c174l1700184?rb=true"
        cl_url = f"https://clutch.ca/cars?keyword={kw_q}"
        fb_url = f"https://www.facebook.com/marketplace/search/?query={kw_q}%20Gatineau"

        btn = "display:inline-block;margin:4px 6px 4px 0;padding:8px 14px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;font-size:13px;"
        buttons_html += f"""
        <div style="margin-top: 14px; margin-bottom: 6px;"><strong>{v_name} ({yr1}-{yr2}):</strong></div>
        <a href="{at_url}" target="_blank" rel="noopener" style="{btn}">AutoTrader.ca</a>
        <a href="{cg_url}" target="_blank" rel="noopener" style="{btn}">CarGurus.ca</a>
        <a href="{kj_url}" target="_blank" rel="noopener" style="{btn}">Kijiji</a>
        <a href="{cl_url}" target="_blank" rel="noopener" style="{btn}">Clutch.ca</a>
        <a href="{fb_url}" target="_blank" rel="noopener" style="{btn}">Facebook</a>
        """

    outlander_rows = []
    rav4_rows = []

    # Enforce the mileage cap (< 80,000 km), then rank by best price-to-value.
    # A sunroof is preferred and acts as a tie-breaker in _listing_value_score.
    eligible_listings = [l for l in LISTINGS if _mileage_ok(l)]
    ranked_listings = sorted(eligible_listings, key=_listing_value_score)

    for listing in ranked_listings:
        raw_url = listing.get('url') or ""
        if not raw_url or "example.com" in raw_url.lower():
            vehicle_href = generate_marketplace_search_url(listing.get('vehicle',''))
        else:
            vehicle_href = raw_url
        row = f"""<tr>
<td style="padding:10px;border-bottom:1px solid #e5e7eb;"><a href="{vehicle_href}" target="_blank" rel="noopener" style="color:#2563eb;text-decoration:none;">{listing['vehicle']}</a></td>
<td style="padding:10px;border-bottom:1px solid #e5e7eb;">{listing['price']} &middot; {listing['mileage']} &middot; Sunroof: {listing['sunroof']}</td>
<td style="padding:10px;border-bottom:1px solid #e5e7eb;">{listing['city']} ({listing['distance_km']} km)</td>
<td style="padding:10px;border-bottom:1px solid #e5e7eb;">{listing['dealer_name']}</td>
</tr>"""
        if "Outlander" in listing['vehicle']:
            outlander_rows.append(row)
        else:
            rav4_rows.append(row)

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vehicle Search Results</title>
<style>
body{{font-family:Arial,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#333;background:#f9f9f9}}
.container{{background:#fff;padding:20px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1)}}
.header{{border-bottom:2px solid #2563eb;padding-bottom:12px;margin-bottom:20px}}
h1{{margin:0;color:#2563eb;font-size:22px}}
.meta{{color:#666;font-size:13px;margin:6px 0 0}}
h3{{color:#1f2937;margin:18px 0 10px;font-size:16px}}
table{{width:100%;border-collapse:collapse}}
th{{background:#f0f0f0;padding:10px;text-align:left;font-weight:bold;border-bottom:2px solid #ddd}}
td{{padding:10px;border-bottom:1px solid #e5e7eb}}
a{{color:#2563eb;text-decoration:none}}
a:hover{{text-decoration:underline}}
.buttons{{margin:20px 0;padding:16px;background:#f9f9f9;border-radius:6px}}
.footer{{margin-top:20px;padding-top:12px;border-top:1px solid #e5e7eb;font-size:12px;color:#666}}
.note{{background:#fef3c7;padding:10px;border-left:4px solid #f59e0b;margin:12px 0;border-radius:4px;font-size:13px}}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1>&#128663; Vehicle Search Results</h1>
<div class="meta">Generated: {est_now.strftime('%B %d, %Y at %I:%M %p %Z')}</div>
</div>

<h3>Mitsubishi Outlander PHEV</h3>
<table>
<thead><tr><th>Vehicle</th><th>Details</th><th>Location</th><th>Dealer</th></tr></thead>
<tbody>
{''.join(outlander_rows) if outlander_rows else '<tr><td colspan="4">No results found</td></tr>'}
</tbody>
</table>

<h3>Toyota RAV4 Prime</h3>
<table>
<thead><tr><th>Vehicle</th><th>Details</th><th>Location</th><th>Dealer</th></tr></thead>
<tbody>
{''.join(rav4_rows) if rav4_rows else '<tr><td colspan="4">No results found</td></tr>'}
</tbody>
</table>

<h3 style="margin-top:18px;">Search Popular Marketplaces</h3>
<div class="buttons">
{buttons_html}
</div>

<div class="note">
<strong>&#128206; Dealers List:</strong> The attached <strong>dealers.html</strong> file contains all {len(load_dealers_from_file())} dealers in your area.
Download it and open in your browser to see the full list with clickable links.
</div>

<div class="footer">
Next update: Every 3 days at 7 AM Gatineau time (Eastern, DST-adjusted)<br>
Generated: {est_now.strftime('%Y-%m-%d %I:%M %p %Z')}
</div>
</div>
</body>
</html>
"""
    return html

# -------------------------
# Email send (unchanged)
# -------------------------
def send_email(subject, html_body, files_to_attach):
    if not (GMAIL_ADDRESS and GMAIL_PASSWORD and RECIPIENT_EMAIL):
        print("Email credentials not set. Skipping send.")
        return
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = RECIPIENT_EMAIL
    plain = MIMEText("Please open as HTML to view the email properly.", 'plain')
    msg.attach(plain)
    html_part = MIMEText(html_body, 'html')
    msg.attach(html_part)
    for filepath in files_to_attach:
        try:
            with open(filepath, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(filepath)}"')
            msg.attach(part)
            print(f"Attached {filepath}")
        except Exception as e:
            print(f"Failed to attach {filepath}: {e}")
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30)
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Email failed: {e}")

# -------------------------
# Main
# -------------------------
def main():
    est_now = datetime.now(EST)

    is_manual_or_local = GITHUB_EVENT_NAME in ('workflow_dispatch', '')
    if not is_manual_or_local and est_now.hour != 7:
        print(f"Skipping this run: current Gatineau time is {est_now.strftime('%I:%M %p %Z')}, "
              f"not 7:00 AM. This trigger corresponds to the other DST offset.")
        return

    if ENABLE_SCRAPE:
        print("ENABLE_SCRAPE=1: attempting to scrape marketplaces, Facebook Marketplace and dealer sites for real listing URLs...")
        try:
            scrape_and_populate_listings()
        except Exception as e:
            print("Scraping step failed:", e)
    else:
        for entry in LISTINGS:
            raw = entry.get("url", "") or ""
            if not raw or "example.com" in raw.lower():
                entry["url"] = generate_marketplace_search_url(entry.get("vehicle",""))

    dealers_html = generate_dealers_html()
    email_html = generate_email_html(est_now)

    with open('dealers.html', 'w', encoding='utf-8') as f:
        f.write(dealers_html)
    print("Generated dealers.html")

    with open('gatineau_phev_rav4_search_results.html', 'w', encoding='utf-8') as f:
        f.write(email_html)
    print("Generated gatineau_phev_rav4_search_results.html")

    subject = f"Vehicle Search Results - {est_now.strftime('%B %d, %Y')}"
    send_email(subject, email_html, ['gatineau_phev_rav4_search_results.html', 'dealers.html'])

if __name__ == '__main__':
    main()
