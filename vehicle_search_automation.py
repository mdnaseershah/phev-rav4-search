#!/usr/bin/env python3
"""
vehicle_search_automation.py

Fast, optimized scraper + HTML/email generator.
- Uses exact, pre-filtered marketplace URLs (price caps, mileage caps, exact trims).
- Uses requests.Session() and ThreadPoolExecutor for concurrent, high-speed scraping.
- Generates gatineau_phev_rav4_search_results.html and dealers.html and sends email.
"""

from __future__ import annotations
import os
import time
import json
import re
import urllib.parse
import requests
import pytz
import concurrent.futures
from datetime import datetime
from bs4 import BeautifulSoup
from tqdm import tqdm
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

# -------------------------
# Configuration / Env
# -------------------------
GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS')
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
EST = pytz.timezone('US/Eastern')

ENABLE_SCRAPE = os.getenv('ENABLE_SCRAPE', '0') == '1'
REQUEST_DELAY = float(os.getenv('REQUEST_DELAY', '1.0'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '2'))

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
}

# Global persistent session for connection pooling (massive speed boost)
session = requests.Session()
session.headers.update(DEFAULT_HEADERS)

DEALERS_JSON = "dealers.json"

# -------------------------
# Vehicles & Exact URLs Config
# -------------------------
WANTED_VEHICLES = [
    {
        "vehicle": "Mitsubishi Outlander PHEV",
        "make": "Mitsubishi",
        "model": "Outlander PHEV",
        "year_min": 2022,
        "year_max": 2023,
        "aliases": ["outlander phev", "outlander plug-in", "outlander plug in", "outlander hybrid"],
        "urls": {
            "autotrader": "https://www.autotrader.ca/cars/mitsubishi/outlander/va_outlander-phev/reg_qc/cit_gatineau/pr_32000?offer=N%2CU&modelyearfrom=2022&modelyearto=2023&cy=CA&damaged_listing=exclude&desc=0&sort=standard&ustate=N%2CU&zip=Gatineau&zipr=500&lat=45.47723&lon=-75.70164&atype=C&mcat=ma50gr201018va1568&size=20",
            "cargurus": "https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&zip=J8T&distance=500&makeModelTrimPaths=m46%2Fd2652%2Cm46&nonShippableBaseline=127&sortDirection=ASC&sortType=DEAL_SCORE&maxMileage=70000&startYear=2022&endYear=2023&maxPrice=32000",
            "kijiji": "https://www.kijiji.ca/b-cars-trucks/canada/mitsubishi-outlander-phev/mitsubishi-outlander-2022__2023/k0c174l0a54a1000054a68?kilometers=0__70000&price=0__32000&view=list",
            "clutch": "https://www.clutch.ca/cars/mitsubishi-outlander-phev-under-32000?yearLow=2022&yearHigh=2023&mileageHigh=70000",
            "facebook": "https://www.facebook.com/marketplace/search/?query=Mitsubishi%20Outlander%20PHEV&maxPrice=32000"
        }
    },
    {
        "vehicle": "Toyota RAV4 Prime",
        "make": "Toyota",
        "model": "RAV4 Prime",
        "year_min": 2021,
        "year_max": 2023,
        "aliases": ["rav4 prime", "rav 4 prime", "rav4 plug-in", "rav4 plug in", "rav4 phev", "rav4 plug-in hybrid"],
        "urls": {
            "autotrader": "https://www.autotrader.ca/cars/reg_qc/cit_gatineau/pr_42000?cat=ma70gr201439va2400%2Cma70gr201439va3942&offer=N%2CU&modelyearfrom=2021&modelyearto=2023&cy=CA&damaged_listing=exclude&desc=0&sort=standard&ustate=N%2CU&zip=Gatineau&zipr=500&lat=45.47723&lon=-75.70164&atype=C&mcat=ma70gr201439&size=20",
            "cargurus": "https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&zip=J8T&distance=500&entitySelectingHelper.selectedEntity=d2992&nonShippableBaseline=127&sortDirection=ASC&sortType=DEAL_SCORE&maxMileage=120000&startYear=2021&endYear=2023&maxPrice=42000",
            "kijiji": "https://www.kijiji.ca/b-cars-trucks/canada/toyota-rav4/toyota-rav4-2021__2023/k0c174l0a54a1000054a68?kilometers=0__120000&price=0__42000&view=list",
            "clutch": "https://www.clutch.ca/cars/under-40000?yearLow=2021&yearHigh=2023&models=toyota;rav4-plug-in-hybrid,toyota;rav4-prime&mileageHigh=120000",
            "facebook": "https://www.facebook.com/marketplace/search/?query=Toyota%20RAV4%20Prime&maxPrice=42000"
        }
    },
]

# -------------------------
# Placeholder LISTINGS
# -------------------------
LISTINGS = [
    {"vehicle": "Mitsubishi Outlander PHEV", "price": "$29,900", "mileage": "45,000 km", "sunroof": "No", "city": "Gatineau, QC", "distance_km": 6.5, "dealer_name": "Rallye Mitsubishi", "url": "https://example.com/listing/outlander-1"},
    {"vehicle": "Toyota RAV4 Prime", "price": "$39,500", "mileage": "65,000 km", "sunroof": "Yes", "city": "Ottawa, ON", "distance_km": 11.9, "dealer_name": "Bel-Air Toyota", "url": "https://example.com/listing/rav4-1"},
]

DEALERS = [
    {"name": "Toyota Gatineau", "brand": "Toyota", "city": "Gatineau, QC", "distance_km": 2.1, "website": "https://www.toyotagatineau.ca"},
    {"name": "Rallye Mitsubishi", "brand": "Mitsubishi", "city": "Gatineau, QC", "distance_km": 6.5, "website": "https://www.rallyemitsubishi.ca"},
]

# -------------------------
# HTTP Helpers
# -------------------------
def http_get(url, timeout=15):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"HTTP GET failed for {url}: {e}")
            time.sleep(REQUEST_DELAY * attempt)
    return None

def fetch_url(task):
    """Worker function for threading"""
    url, label = task
    return label, http_get(url)

# -------------------------
# Parsing Logic
# -------------------------
NON_LISTING_HREF_MARKERS = ("/editorial/", "/expert-reviews/", "/research/", "/news/", "/reviews/", "/help", "/about", "/blog/")

def _is_listing_candidate(href: str) -> bool:
    if not href: return False
    return not any(marker in href.lower() for marker in NON_LISTING_HREF_MARKERS)

def _extract_year(text):
    if not text: return None
    match = re.search(r"\b(19[9]\d|20[0-3]\d)\b", str(text))
    return match.group(0) if match else None

def _year_in_range(candidate_text, year_min, year_max):
    found = _extract_year(candidate_text or "")
    if found is None: return True
    try:
        return year_min <= int(found) <= year_max
    except ValueError:
        return True

def _looks_local(candidate_text):
    low = (candidate_text or "").lower()
    return any(marker in low for marker in ("gatineau", "ottawa", "quebec", "-qc", " qc", "/qc", "outaouais", "hull", "aylmer", "chelsea", "cantley", "buckingham"))

def _parse_money(text):
    if not text: return None
    digits = re.sub(r"[^0-9.]", "", str(text))
    return float(digits) if digits else None

def _parse_km(text):
    if not text: return None
    digits = re.sub(r"[^0-9.]", "", str(text))
    return float(digits) if digits else None

def _listing_value_score(listing):
    price = _parse_money(listing.get("price"))
    km = _parse_km(listing.get("mileage"))
    over_cap = 0 if (km is None or km < 120000) else 1
    if price is None:
        return (over_cap, float("inf"), float("inf"))
    km_penalty = (km or 0) * 0.05
    sunroof = str(listing.get("sunroof", "")).strip().lower() in ("yes", "y", "true")
    sunroof_bonus = -500 if sunroof else 0
    return (over_cap, price + km_penalty + sunroof_bonus, km if km is not None else float("inf"))

def _model_tokens(model, aliases):
    groups = [model.lower().split()]
    for a in (aliases or []): groups.append(a.lower().split())
    return groups

def _matches_model(text, make, token_groups):
    low = (text or "").lower()
    if make and make.lower() not in low: return False
    return any(all(tok in low for tok in grp) for grp in token_groups if grp)

def _card_text(anchor):
    node = anchor
    for _ in range(4):
        if node.parent is None: break
        node = node.parent
    return node.get_text(" ", strip=True) if node else (anchor.get_text(" ", strip=True) or "")

def _extract_trim(title, make, model):
    if not title: return None
    t = re.sub(r"\b(19[9]\d|20[0-3]\d)\b", " ", title)
    drop = [make or ""] + (model or "").split() + ["plug-in", "plug", "in", "hybrid", "phev", "prime", "phev)", "(phev"]
    low = t
    for w in drop:
        if w: low = re.sub(r"(?i)\b" + re.escape(w) + r"\b", " ", low)
    low = re.sub(r"[^A-Za-z0-9\- ]", " ", low)
    low = re.sub(r"\s+", " ", low).strip()
    return low or None

def _extract_sunroof(card_text):
    return "Yes" if card_text and re.search(r"(?i)\b(sun ?roof|moon ?roof|panoramic roof)\b", card_text) else None

def _find_price(card_text):
    if not card_text: return None
    best = None
    for m in re.findall(r"\$\s?(\d{1,3}(?:,\d{3})+|\d{4,6})(?:\.\d{2})?", card_text):
        try: val = int(m.replace(",", ""))
        except ValueError: continue
        if 3000 <= val <= 100000:
            if best is None or val > best: best = val
    return best

def _find_mileage(card_text):
    if not card_text: return None
    for m in re.findall(r"(\d{1,3}(?:,\d{3})+|\d{4,6})\s?(?:km|kms|kilometres|kilometers)\b", card_text, flags=re.I):
        try: val = int(m.replace(",", ""))
        except ValueError: continue
        if 500 <= val <= 400000: return val
    return None

def _title_is_listing(title, make, token_groups):
    if not title or len(title) < 6 or not _extract_year(title): return False
    low = title.lower()
    return (bool(make) and make.lower() in low) or any(all(tok in low for tok in grp) for grp in token_groups if grp)

def _listing_from_anchor(anchor, full_url, make, model, token_groups):
    title = anchor.get_text(" ", strip=True) or ""
    base = {"url": full_url, "title": None, "year": None, "trim": None, "price": None, "mileage": None, "sunroof": None}
    if not _title_is_listing(title, make, token_groups): return base
    card = _card_text(anchor)
    price = _find_price(card)
    km = _find_mileage(card)
    base.update({
        "title": title,
        "year": _extract_year(title),
        "trim": _extract_trim(title, make, model),
        "price": ("$" + format(price, ",")) if price is not None else None,
        "mileage": ("{:,} km".format(km)) if km is not None else None,
        "sunroof": _extract_sunroof(card),
    })
    return base

def _pick_listing(html_text, base_url, path_markers, make, model, year_min, year_max, aliases):
    if not html_text: return None
    soup = BeautifulSoup(html_text, "lxml")
    token_groups = _model_tokens(model, aliases)
    fallback = None
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript:") or not _is_listing_candidate(href):
            continue
        if path_markers and not any(pm in href.lower() for pm in path_markers):
            continue
        text = a.get_text(" ", strip=True) or ""
        blob = text + " " + href
        if not _matches_model(blob, make, token_groups) or not _year_in_range(blob, year_min, year_max):
            continue
        full = urllib.parse.urljoin(base_url, href)
        details = _listing_from_anchor(a, full, make, model, token_groups)
        
        # Simple cap logic just for initial fetch phase filtering
        km = _parse_km(details.get("mileage"))
        if km is not None and km > 120000: continue
        
        if _looks_local(blob): return details
        if fallback is None: fallback = details
    return fallback

# -------------------------
# Orchestration
# -------------------------
def load_dealers_from_file():
    if os.path.exists(DEALERS_JSON):
        try:
            with open(DEALERS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data: return data
        except Exception as e: print(f"Failed to load {DEALERS_JSON}: {e}")
    return DEALERS

def find_listing_in_dealer_html(html_text: str, base_url: str, make: str, model: str):
    if not html_text: return None
    soup = BeautifulSoup(html_text, "lxml")
    tokens = [make.lower(), model.lower()]
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        text = (a.get_text(" ", strip=True) or "").lower()
        if not href or not _is_listing_candidate(href): continue
        if all(tok in text for tok in tokens if tok) or any(tok in href.lower() for tok in tokens):
            return urllib.parse.urljoin(base_url, href)
    return None

def scrape_and_populate_listings():
    dealer_sites = list(set(d.get("website") for d in load_dealers_from_file() if d.get("website")))
    found_map = {}

    for wanted in WANTED_VEHICLES:
        vehicle_name = wanted["vehicle"]
        make = wanted["make"]
        model = wanted["model"]
        y_min, y_max = wanted["year_min"], wanted["year_max"]
        aliases = wanted.get("aliases", [])
        urls = wanted["urls"]
        print(f"\nSearching for: {vehicle_name}")

        # 1. Concurrently fetch marketplace URLs
        tasks = [
            (urls["autotrader"], "autotrader"),
            (urls["cargurus"], "cargurus"),
            (urls["kijiji"], "kijiji"),
            (urls["clutch"], "clutch")
        ]
        
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_url = {executor.submit(fetch_url, task): task for task in tasks}
            for future in concurrent.futures.as_completed(future_to_url):
                label, html = future.result()
                results[label] = html

        # Parse results
        at_listing = _pick_listing(results.get("autotrader"), "https://www.autotrader.ca", ("/a/", "/cars/"), make, model, y_min, y_max, aliases)
        if at_listing: found_map[vehicle_name] = at_listing; print(f"  AutoTrader -> {at_listing['url']}"); continue

        cg_listing = _pick_listing(results.get("cargurus"), "https://www.cargurus.ca", ("/cars/", "inventorylisting"), make, model, y_min, y_max, aliases)
        if cg_listing: found_map[vehicle_name] = cg_listing; print(f"  CarGurus -> {cg_listing['url']}"); continue

        kj_listing = _pick_listing(results.get("kijiji"), "https://www.kijiji.ca", ("/v-cars-trucks", "/v-autos", "/v-view-details"), make, model, y_min, y_max, aliases)
        if kj_listing: found_map[vehicle_name] = kj_listing; print(f"  Kijiji -> {kj_listing['url']}"); continue

        cl_listing = _pick_listing(results.get("clutch"), "https://clutch.ca", ("/cars/",), make, model, y_min, y_max, aliases)
        if cl_listing: found_map[vehicle_name] = cl_listing; print(f"  Clutch -> {cl_listing['url']}"); continue

        # 2. Concurrently probe dealers if not found
        print(f"  Probing {len(dealer_sites)} local dealer websites...")
        dealer_tasks = [(site.rstrip("/") + "/used-inventory", site) for site in dealer_sites] + \
                       [(site.rstrip("/") + "/inventory", site) for site in dealer_sites]

        dealer_found = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_site = {executor.submit(fetch_url, task): task for task in dealer_tasks}
            for future in concurrent.futures.as_completed(future_to_site):
                site, html = future.result()
                found = find_listing_in_dealer_html(html, site, make, model)
                if found:
                    dealer_found = {"url": found}
                    break
        
        if dealer_found:
            found_map[vehicle_name] = dealer_found
            print(f"  Found on dealer site -> {dealer_found['url']}")
        else:
            fallback = urls["autotrader"]
            print(f"  No direct listing found; using fallback: {fallback}")
            found_map[vehicle_name] = {"url": fallback}

    # Update global LISTINGS
    for entry in LISTINGS:
        name = entry.get("vehicle", "")
        found = found_map.get(name)
        if found:
            entry["url"] = found.get("url") or entry.get("url")
            for key in ("year", "trim", "title", "price", "mileage", "sunroof"):
                if key in found and found[key]: entry[key] = found[key]

# -------------------------
# HTML Generation
# -------------------------
def generate_dealers_html():
    dealers = load_dealers_from_file()
    rows = "".join([f"<tr><td><a href='{d.get('website','#')}'>{d.get('name','')}</a></td><td>{d.get('brand','')}</td><td>{d.get('city','')}</td><td>{d.get('distance_km','')} km</td></tr>" for d in dealers])
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Dealers</title><style>body{{font-family:Arial;margin:20px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border:1px solid #ddd;text-align:left}}th{{background:#f0f0f0}}</style></head><body><h2>Dealers ({len(dealers)})</h2><table><thead><tr><th>Dealer</th><th>Brand</th><th>City</th><th>Distance</th></tr></thead><tbody>{rows}</tbody></table></body></html>"

def generate_email_html(est_now):
    buttons_html = ""
    for wanted in WANTED_VEHICLES:
        urls = wanted["urls"]
        btn = "display:inline-block;margin:4px 6px 4px 0;padding:8px 14px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;font-size:13px;"
        buttons_html += f"""
        <div style="margin-top: 14px; margin-bottom: 6px;"><strong>{wanted['vehicle']} ({wanted['year_min']}-{wanted['year_max']}):</strong></div>
        <a href="{urls['autotrader']}" target="_blank" style="{btn}">AutoTrader.ca</a>
        <a href="{urls['cargurus']}" target="_blank" style="{btn}">CarGurus.ca</a>
        <a href="{urls['kijiji']}" target="_blank" style="{btn}">Kijiji</a>
        <a href="{urls['clutch']}" target="_blank" style="{btn}">Clutch.ca</a>
        <a href="{urls['facebook']}" target="_blank" style="{btn}">Facebook</a>
        """

    ranked_listings = sorted(LISTINGS, key=_listing_value_score)
    
    outlander_rows = []
    rav4_rows = []

    for rank, listing in enumerate(ranked_listings, start=1):
        wanted_vehicle = next((v for v in WANTED_VEHICLES if v['vehicle'] == listing.get('vehicle')), None)
        vehicle_href = wanted_vehicle['urls']['autotrader'] if wanted_vehicle else listing.get('url', '#')

        base_name = listing.get('vehicle', '')
        desc_parts = [str(listing.get('year') or ''), base_name, listing.get('trim') or '']
        description = listing.get('title') or " ".join([p for p in desc_parts if p])

        # Pre-assign variables to avoid backslashes in f-string expression (fixes SyntaxError on Python < 3.12)
        em_dash = "\u2014"
        price_disp = listing.get('price') or em_dash
        mileage_disp = listing.get('mileage') or em_dash
        sunroof_disp = listing.get('sunroof') or em_dash
        city_disp = listing.get('city') or em_dash
        dealer_disp = listing.get('dealer_name') or em_dash

        row = f"""<tr>
<td style="padding:10px;border:1px solid #ddd;text-align:center;"><strong>#{rank}</strong></td>
<td style="padding:10px;border:1px solid #ddd;"><a href="{vehicle_href}" style="color:#2563eb;font-weight:bold;text-decoration:none;">{description}</a></td>
<td style="padding:10px;border:1px solid #ddd;">{price_disp}</td>
<td style="padding:10px;border:1px solid #ddd;">{mileage_disp}</td>
<td style="padding:10px;border:1px solid #ddd;">{sunroof_disp}</td>
<td style="padding:10px;border:1px solid #ddd;">{city_disp}</td>
<td style="padding:10px;border:1px solid #ddd;">{dealer_disp}</td>
</tr>"""
        if "outlander" in base_name.lower(): outlander_rows.append(row)
        else: rav4_rows.append(row)

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;margin:0;padding:20px;color:#333;line-height:1.6;">
    <h2 style="color:#2563eb;margin-top:0;">Daily Vehicle Search Results</h2>
    <p style="color:#555;font-size:14px;">Generated on: {est_now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}</p>
    
    <h3 style="border-bottom:2px solid #eee;padding-bottom:5px;margin-top:30px;">Top Ranked Listings</h3>
    <table style="width:100%;border-collapse:collapse;margin-top:10px;font-size:14px;">
        <tr style="background:#f8f9fa;">
            <th style="padding:10px;border:1px solid #ddd;text-align:center;">Rank</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Vehicle</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Price</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Mileage</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Sunroof</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Location</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Dealer</th>
        </tr>
        {''.join(outlander_rows + rav4_rows)}
    </table>

    <h3 style="border-bottom:2px solid #eee;padding-bottom:5px;margin-top:40px;">Marketplace Quick Links</h3>
    <p style="font-size:13px;color:#555;">One-click searches using exact strict filters for maximum price, mileage, and models.</p>
    {buttons_html}
</body>
</html>"""

def send_email(subject: str, html_content: str):
    if not all([GMAIL_ADDRESS, GMAIL_PASSWORD, RECIPIENT_EMAIL]):
        print("Missing email credentials. Skipping email.")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_content, "html"))
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        server.quit()
        print(f"Success: Email sent to {RECIPIENT_EMAIL}")
    except Exception as e:
        print(f"Error sending email: {e}")

def main():
    est_now = datetime.now(EST)
    print(f"--- Starting vehicle search at {est_now.strftime('%Y-%m-%d %H:%M:%S %Z')} ---")
    if ENABLE_SCRAPE: scrape_and_populate_listings()
    
    email_html = generate_email_html(est_now)
    with open("gatineau_phev_rav4_search_results.html", "w", encoding="utf-8") as f: f.write(email_html)
    with open("dealers.html", "w", encoding="utf-8") as f: f.write(generate_dealers_html())
    
    send_email(f"Vehicle Search Update: {est_now.strftime('%b %d')} (Gatineau PHEV/RAV4)", email_html)
    print("--- Done ---")

if __name__ == "__main__":
    main()
