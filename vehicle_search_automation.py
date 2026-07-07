#!/usr/bin/env python3
"""
vehicle_search_automation.py

V3 - Robust scraper using Playwright with domcontentloaded strategy.
Fixes: networkidle timeout, missing --no-sandbox, cookie popups, Clutch.js.
Collects ALL listings from all sources, ranks them, and emails clickable links.
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
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

# Try to import Playwright
try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠ Playwright not installed. Only Kijiji will work.")

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

session = requests.Session()
session.headers.update(DEFAULT_HEADERS)

DEALERS_JSON = "dealers.json"

# Popular dealer sites always probed for inventory (in addition to dealers.json).
# Each entry mirrors the dealers.json shape ({"name", "website"}); the name is shown
# as the listing's Source. These run on standard Canadian dealer platforms (D2C Media
# / EDealer / Convertus / Sincro) that embed schema.org JSON-LD on inventory pages, so
# _extract_jsonld_vehicles can read them with plain requests — no headless browser.
# Add more dealers here.
POPULAR_DEALER_SITES = [
    {"name": "Rallye Mitsubishi", "website": "https://www.rallyemitsubishi.ca"},
]

# -------------------------
# Vehicles & Search Config
# -------------------------
WANTED_VEHICLES = [
    {
        "vehicle": "Mitsubishi Outlander PHEV",
        "make": "Mitsubishi",
        "model": "Outlander PHEV",
        "year_min": 2022,
        "year_max": 2023,
        "max_price": 32000,
        "max_mileage": {2022: 70000, 2023: 100000},   # <-- CHANGED: year-specific caps
        "aliases": ["outlander phev", "outlander plug-in", "outlander plug in", "outlander hybrid"],
        "urls": {
            "autotrader": "https://www.autotrader.ca/cars/mitsubishi/outlander/va_outlander-phev/reg_qc/cit_gatineau/pr_32000?offer=N%2CU&modelyearfrom=2022&modelyearto=2023&cy=CA&damaged_listing=exclude&desc=0&sort=standard&ustate=N%2CU&zip=Gatineau&zipr=500&lat=45.47723&lon=-75.70164&atype=C&mcat=ma50gr201018va1568&size=20",
            "cargurus": "https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&zip=J8T&distance=500&makeModelTrimPaths=m46%2Fd2652%2Cm46&nonShippableBaseline=127&sortDirection=ASC&sortType=DEAL_SCORE&maxMileage=100000&startYear=2022&endYear=2023&maxPrice=32000",  # <-- CHANGED
            "kijiji": "https://www.kijiji.ca/b-cars-trucks/canada/mitsubishi-outlander-phev/mitsubishi-outlander-2022__2023/k0c174l0a54a1000054a68?kilometers=0__100000&price=0__32000&view=list",  # <-- CHANGED
            "clutch": "https://www.clutch.ca/cars/mitsubishi-outlander-phev-under-32000?yearLow=2022&yearHigh=2023&mileageHigh=100000",  # <-- CHANGED
            "facebook": "https://www.facebook.com/marketplace/search/?query=Mitsubishi%20Outlander%20PHEV&maxPrice=32000",
            "kijiji_rss": "https://www.kijiji.ca/rss-srp-cars-trucks/gatineau/k0c174l1700312?price=0__32000&maxKilometers=100000&minYear=2022&maxYear=2023&radius=400&ad=offering&vehicleType=cars",  # <-- CHANGED
        },
        # --- API identifiers (used by parse_*_api functions) ---
        "autotrader_model": "Outlander PHEV",  # AutoTrader taxonomy model name
        "cargurus_entity": "d2652",            # CarGurus model entity id (Outlander PHEV)
        "cargurus_zip": "J8T",
        # Known trims, most-specific first — used to build a clean Vehicle label.
        "trims": ["GT S-AWC", "GT Premium", "SE S-AWC", "LE S-AWC", "ES S-AWC",
                   "Black Edition", "GT", "SEL", "SE", "ES", "LE"],
    },
    {
        "vehicle": "Toyota RAV4 Prime",
        "make": "Toyota",
        "model": "RAV4 Prime",
        "year_min": 2021,
        "year_max": 2023,
        "max_price": 42000,
        "max_mileage": 120000,
        "aliases": ["rav4 prime", "rav 4 prime", "rav4 plug-in", "rav4 plug in", "rav4 phev", "rav4 plug-in hybrid"],
        "urls": {
            "autotrader": "https://www.autotrader.ca/cars/reg_qc/cit_gatineau/pr_42000?cat=ma70gr201439va2400%2Cma70gr201439va3942&offer=N%2CU&modelyearfrom=2021&modelyearto=2023&cy=CA&damaged_listing=exclude&desc=0&sort=standard&ustate=N%2CU&zip=Gatineau&zipr=500&lat=45.47723&lon=-75.70164&atype=C&mcat=ma70gr201439&size=20",
            "cargurus": "https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&zip=J8T&distance=500&entitySelectingHelper.selectedEntity=d2992&nonShippableBaseline=127&sortDirection=ASC&sortType=DEAL_SCORE&maxMileage=120000&startYear=2021&endYear=2023&maxPrice=42000",
            "kijiji": "https://www.kijiji.ca/b-cars-trucks/canada/toyota-rav4/toyota-rav4-2021__2023/k0c174l0a54a1000054a68?kilometers=0__120000&price=0__42000&view=list",
            "clutch": "https://www.clutch.ca/cars/under-40000?yearLow=2021&yearHigh=2023&models=toyota;rav4-plug-in-hybrid,toyota;rav4-prime&mileageHigh=120000",
            "facebook": "https://www.facebook.com/marketplace/search/?query=Toyota%20RAV4%20Prime&maxPrice=42000",
            "kijiji_rss": "https://www.kijiji.ca/rss-srp-cars-trucks/gatineau/k0c174l1700312?price=0__42000&maxKilometers=120000&minYear=2021&maxYear=2023&radius=400&ad=offering&vehicleType=cars",
        },
        # --- API identifiers (used by parse_*_api functions) ---
        # AutoTrader lists RAV4 Prime as a *variant* of model "RAV4"; query the model
        # broadly and let alias matching keep only Prime/PHEV/plug-in results.
        "autotrader_model": "RAV4",
        "cargurus_entity": "d2992",            # CarGurus model entity id (RAV4 Prime)
        "cargurus_zip": "J8T",
        # Known trims, most-specific first — used to build a clean Vehicle label.
        "trims": ["XSE", "SE"],
    },
]

# -------------------------
# Global list of ALL found listings
# -------------------------
ALL_LISTINGS = []

# -------------------------
# HTTP & Playwright Helpers
# -------------------------
def http_get(url, timeout=20):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            print(f"    HTTP {resp.status_code} ({len(resp.text)} bytes)")
            return resp.text
        except Exception as e:
            print(f"    HTTP attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                return None
            time.sleep(REQUEST_DELAY * attempt)
    return None

def fetch_rendered_html(url, timeout=40000):
    """
    Fetch a page with full JS rendering using Playwright.
    Uses 'domcontentloaded' + explicit waits (NOT 'networkidle') for reliability.
    """
    if not PLAYWRIGHT_AVAILABLE:
        print(f"    Skipping (Playwright not available)")
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with _sync_playwright() as p:
                # Launch browser with proper flags for GitHub Actions
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                    ]
                )
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()

                # Step 1: Navigate — wait for DOM only (fast, ~2s)
                print(f"    Navigating...")
                page.goto(url, wait_until='domcontentloaded', timeout=timeout)
                print(f"    DOM loaded, waiting for JS rendering...")

                # Step 2: Wait a few seconds for JS to execute
                page.wait_for_timeout(5000)

                # Step 3: Try to dismiss cookie / consent banners
                try:
                    cookie_selectors = [
                        'button:has-text("Accept")', 'button:has-text("Reject All")',
                        'button:has-text("Close")', 'button:has-text("OK")',
                        'button:has-text("Continue")', '[aria-label*="Close"]',
                        '.cookie-banner button', '#cookie-banner button',
                        '.cookie-consent button', '.consent button',
                        '.ot-sdk-container button', '#onetrust-accept-btn-handler',
                        '.fc-button-label', 'button[id*="accept"]',
                    ]
                    for sel in cookie_selectors:
                        btns = page.query_selector_all(sel)
                        for btn in btns:
                            try:
                                btn.click()
                                page.wait_for_timeout(500)
                                print(f"    Clicked cookie button: {sel}")
                            except:
                                pass
                except Exception as e:
                    print(f"    Cookie handling note: {e}")

                # Step 4: Wait for listing-related selectors to appear
                listing_selectors = [
                    '.listing-card', '.result-item', 'article[data-listing-id]',
                    '.vehicle-card', '.search-item', '.card',
                    '[class*="listing"]', '[class*="vehicle"]', '[class*="result"]',
                    'a[href*="/cars/"]', 'a[href*="/listing/"]',
                    'div[data-testid*="listing"]', 'div[data-testid*="vehicle"]',
                    'div[class*="card"]', 'li[class*="listing"]',
                ]
                found_selector = None
                for sel in listing_selectors:
                    try:
                        page.wait_for_selector(sel, timeout=3000)
                        found_selector = sel
                        print(f"    Found listing element: {sel}")
                        page.wait_for_timeout(1000)  # Let more load
                        break
                    except:
                        continue

                if not found_selector:
                    print(f"    No listing elements found (page may still have data)")

                # Step 5: Get the fully rendered HTML
                html = page.content()
                print(f"    Rendered HTML: {len(html)} bytes")
                
                # Log how many links are on the page
                soup = BeautifulSoup(html, 'lxml')
                links = soup.select('a[href]')
                listing_links = [l for l in links if '/cars/' in l.get('href', '').lower() or '/listing/' in l.get('href', '').lower()]
                print(f"    Total links: {len(links)}, car-related links: {len(listing_links)}")

                browser.close()
                return html

        except Exception as e:
            print(f"    ⚠ Playwright attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                return None
            time.sleep(REQUEST_DELAY * attempt)

    return None

def fetch_url(task):
    """Worker function for threading (requests only)"""
    url, label = task
    print(f"  Fetching {label} via requests...")
    return label, http_get(url)

def http_get_json(url, referer=None, timeout=25):
    """GET a URL expecting a JSON response. Returns parsed JSON or None."""
    headers = {"Accept": "application/json, text/plain, */*", "X-Requested-With": "XMLHttpRequest"}
    if referer:
        headers["Referer"] = referer
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            print(f"    JSON GET {resp.status_code} ({len(resp.text)} bytes)")
            return resp.json()
        except Exception as e:
            print(f"    JSON GET attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                return None
            time.sleep(REQUEST_DELAY * attempt)
    return None

def http_post_json(url, payload, referer=None, origin=None, timeout=30):
    """POST a JSON payload expecting a JSON response.

    Returns parsed JSON, or {"_raw": <text>} when the body is not valid JSON,
    or None on failure.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            print(f"    JSON POST {resp.status_code} ({len(resp.text)} bytes)")
            try:
                return resp.json()
            except Exception:
                return {"_raw": resp.text}
        except Exception as e:
            print(f"    JSON POST attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                return None
            time.sleep(REQUEST_DELAY * attempt)
    return None

# -------------------------
# RSS Parsing (NEW — most reliable source)
# -------------------------
def parse_kijiji_rss(vehicle_name, vehicle_config):
    """Parse Kijiji RSS feed for structured listing data."""
    rss_url = vehicle_config.get("urls", {}).get("kijiji_rss")
    if not rss_url:
        return []
    
    print(f"  Fetching Kijiji RSS...")
    xml_text = http_get(rss_url)
    if not xml_text:
        return []
    
    results = []
    seen_guids = set()
    
    soup = BeautifulSoup(xml_text, "lxml-xml")  # Use XML parser for RSS
    
    for item in soup.select("item"):
        # Get GUID (unique ID) and link
        guid = item.find("guid")
        link = item.find("link")
        url = link.get_text(strip=True) if link else None
        guid_text = guid.get_text(strip=True) if guid else url
        
        if not url or guid_text in seen_guids:
            continue
        seen_guids.add(guid_text)
        
        title = item.find("title")
        title_text = title.get_text(strip=True) if title else ""
        
        description = item.find("description")
        desc_text = description.get_text(" ", strip=True) if description else ""
        
        # Extract price from description
        price = None
        price_match = re.search(r'\$\s?(\d{1,3}(?:,\d{3})+|\d{4,6})', desc_text)
        if price_match:
            try:
                p = int(price_match.group(1).replace(",", ""))
                if p <= vehicle_config.get("max_price", 100000):
                    price = p
            except:
                pass
        
        # Extract year from title
        year = re.search(r'\b(20[0-3]\d)\b', title_text)
        year_val = year.group(0) if year else None
        
        # Extract mileage from description
        km = None
        km_match = re.search(r'(\d{1,3}(?:,\d{3})+|\d{4,6})\s*km', desc_text, re.I)
        if km_match:
            try:
                k = int(km_match.group(1).replace(",", ""))
                if k <= _get_mileage_cap(vehicle_config, int(year_val) if year_val else None) and k >= 500:  # <-- CHANGED
                    km = k
            except:
                pass
        
        # Extract trim
        trim = _extract_trim(title_text + " " + desc_text, vehicle_config["make"], vehicle_config["model"])
        
        # Check sunroof
        sunroof = "Yes" if re.search(r'(?i)\b(sun ?roof|moon ?roof|panoramic)\b', title_text + " " + desc_text) else None
        
        results.append({
            "url": url,
            "title": title_text,
            "year": year_val,
            "trim": trim,
            "price": ("$" + format(price, ",")) if price else None,
            "mileage": ("{:,} km".format(km)) if km else None,
            "sunroof": sunroof,
            "desc": desc_text,
            "vehicle": vehicle_name,
        })
    
    print(f"    Found {len(results)} Kijiji RSS listings")
    return results

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

def _parse_money(text):
    if not text: return None
    digits = re.sub(r"[^0-9.]", "", str(text))
    return float(digits) if digits else None

def _parse_km(text):
    if not text: return None
    digits = re.sub(r"[^0-9.]", "", str(text))
    return float(digits) if digits else None

# -------------------------
# NEW: Helper for year-specific mileage caps
# -------------------------
def _get_mileage_cap(vehicle_config, year=None):
    """Get the max mileage for a vehicle config, optionally year-specific.
    
    If ``max_mileage`` is a dict (year -> cap), returns the cap for the given year,
    or the highest cap if year is None/unknown.
    If it's a plain int, returns that value directly.
    """
    mm = vehicle_config.get("max_mileage", 120000)
    if isinstance(mm, dict):
        if year is not None and int(year) in mm:
            return mm[int(year)]
        return max(mm.values()) if mm else 120000
    return mm

def _listing_value_score(listing):
    """Rank listings by best price-to-value. Lower score = better value."""
    price = _parse_money(listing.get("price"))
    km = _parse_km(listing.get("mileage"))
    
    vehicle_name = listing.get("vehicle", "")
    over_cap = 0
    for v in WANTED_VEHICLES:
        if v["vehicle"] == vehicle_name:
            max_km = _get_mileage_cap(v, int(listing.get("year")) if listing.get("year") else None)  # <-- CHANGED
            if km is not None and km > max_km:
                over_cap = 1
            break
    
    if price is None:
        return (over_cap, float("inf"), float("inf"))
    
    km_penalty = (km or 0) * 0.05
    sunroof = str(listing.get("sunroof", "")).strip().lower() in ("yes", "y", "true")
    sunroof_bonus = -500 if sunroof else 0
    
    return (over_cap, price + km_penalty + sunroof_bonus, km if km is not None else float("inf"))

def _norm_url(u):
    """Normalize a URL for dedup: drop scheme, query, fragment, trailing slash, case."""
    u = (u or "").split("#")[0].split("?")[0].rstrip("/").lower()
    return re.sub(r"^https?://(www\.)?", "", u)

def _dedup_signature(listing, vehicle_config):
    """Identity key for the *same physical car* seen across paths/sources.

    The same unit surfaces from multiple dealer probe paths (index vs
    model-filtered vs certified) and from multiple marketplaces (AutoTrader +
    Kijiji), each with a slightly different URL — so URL-only dedup leaves
    duplicate rows. We key on the car's own attributes instead:
      - exact mileage is a near-unique fingerprint -> (vehicle, year, trim, km)
      - if mileage is unknown (typical for dealer JSON-LD), fall back to price
      - if neither is known, we can only trust the normalized URL
    """
    vehicle = (listing.get("vehicle") or "").strip().lower()
    year = str(listing.get("year") or "").strip()
    src = " ".join(str(listing.get(k) or "") for k in ("title", "trim", "desc"))
    trim = (_clean_trim(src, vehicle_config) or (listing.get("trim") or "")).strip().lower()
    km = _parse_km(listing.get("mileage"))
    price = _parse_money(listing.get("price"))
    if km:
        return ("m", vehicle, year, trim, km)
    if price:
        return ("p", vehicle, year, trim, price)
    return ("u", _norm_url(listing.get("url", "")))

def _better_listing(a, b):
    """Pick the representative to keep when two listings are the same car.

    Prefer the lower real price; carry over a sunroof flag, mileage, or a
    richer description from the discarded twin so no info is lost.
    """
    pa, pb = _parse_money(a.get("price")), _parse_money(b.get("price"))
    keep, drop = (a, b) if (pa if pa is not None else float("inf")) <= (pb if pb is not None else float("inf")) else (b, a)
    if str(drop.get("sunroof", "")).strip().lower() in ("yes", "y", "true"):
        keep["sunroof"] = keep.get("sunroof") or drop.get("sunroof")
    if not _parse_km(keep.get("mileage")) and _parse_km(drop.get("mileage")):
        keep["mileage"] = drop.get("mileage")
    if len(str(drop.get("desc") or "")) > len(str(keep.get("desc") or "")):
        keep["desc"] = drop.get("desc")
    return keep

def _dedup_listings(listings, vehicle_config):
    """Collapse duplicate listings (same car via different paths/sources)."""
    by_url, ordered = {}, []
    for lst in listings:  # first pass: exact normalized-URL dedup
        nu = _norm_url(lst.get("url", ""))
        if nu and nu in by_url:
            by_url[nu] = _better_listing(by_url[nu], lst)
            continue
        by_url[nu] = lst
        ordered.append(nu)
    stage1 = [by_url[nu] for nu in ordered]

    by_sig, out = {}, []
    for lst in stage1:  # second pass: content-signature dedup
        sig = _dedup_signature(lst, vehicle_config)
        if sig in by_sig:
            idx = by_sig[sig]
            out[idx] = _better_listing(out[idx], lst)
            continue
        by_sig[sig] = len(out)
        out.append(lst)
    return out

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

def _collect_listings_from_html(html_text, base_url, path_markers, make, model, year_min, year_max, aliases, vehicle_name, max_price=100000, max_km=120000):
    """Return ALL matching listings from parsed HTML."""
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "lxml")
    token_groups = _model_tokens(model, aliases)
    results = []
    seen_urls = set()
    
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
        if full in seen_urls:
            continue
        seen_urls.add(full)
        
        details = _listing_from_anchor(a, full, make, model, token_groups)
        
        # Filter by mileage cap
        km = _parse_km(details.get("mileage"))
        if km is not None and km > max_km:
            continue
        
        # Filter by price cap
        price = _parse_money(details.get("price"))
        if price is not None and price > max_price:
            continue
        
        # Check year
        yr = _extract_year(details.get("title"))
        if yr:
            try:
                if not (year_min <= int(yr) <= year_max):
                    continue
            except ValueError:
                pass
        
        details["vehicle"] = vehicle_name
        results.append(details)
    
    return results

# -------------------------
# Marketplace-specific parsers
# -------------------------
def parse_autotrader_listings(html_text, make, model, year_min, year_max, aliases, vehicle_name, max_price, max_km):
    """Parse AutoTrader search results page for ALL listings."""
    if not html_text:
        return []
    
    soup = BeautifulSoup(html_text, "lxml")
    results = []
    seen_urls = set()
    
    # Strategy 1: Find listing cards by common selectors
    for selector in [".listing-card", ".result-item", "article[data-listing-id]", "div[data-listing-id]", 
                     ".listing", ".vehicle-card", ".search-item", ".card-body",
                     "[class*='listing']", "[class*='vehicle']", "[class*='result']",
                     "div[class*='card']"]:
        cards = soup.select(selector)
        if cards:
            print(f"    AutoTrader: found {len(cards)} elements with selector '{selector}'")
            for card in cards:
                links = card.select("a[href]")
                for a in links:
                    href = a.get("href", "")
                    full = urllib.parse.urljoin("https://www.autotrader.ca", href)
                    if full in seen_urls:
                        continue
                    text = card.get_text(" ", strip=True) or ""
                    if not _matches_model(text, make, _model_tokens(model, aliases)):
                        continue
                    
                    price = _find_price(text)
                    km = _find_mileage(text)
                    year = _extract_year(text)
                    trim = _extract_trim(text, make, model)
                    sunroof = _extract_sunroof(text)
                    title = a.get_text(" ", strip=True) or text[:100]
                    
                    if price is not None and price > max_price: continue
                    if km is not None and km > max_km: continue
                    if year:
                        try:
                            if not (year_min <= int(year) <= year_max): continue
                        except ValueError: pass
                    
                    seen_urls.add(full)
                    results.append({
                        "url": full, "title": title, "year": year, "trim": trim,
                        "price": ("$" + format(price, ",")) if price else None,
                        "mileage": ("{:,} km".format(km)) if km else None,
                        "sunroof": sunroof, "vehicle": vehicle_name,
                    })
            if results:
                print(f"      Extracted {len(results)} listings")
                return results
    
    # Strategy 2: Find all car-related links in the page
    print(f"    AutoTrader: scanning all links for car listings...")
    for a in soup.select("a[href*='/cars/'], a[href*='/listing/']"):
        href = a.get("href", "")
        full = urllib.parse.urljoin("https://www.autotrader.ca", href)
        if full in seen_urls:
            continue
        seen_urls.add(full)
        
        text = a.get_text(" ", strip=True) or ""
        if not _matches_model(text, make, _model_tokens(model, aliases)):
            continue
        
        price = _find_price(text)
        km = _find_mileage(text)
        year = _extract_year(text)
        
        if price is not None and price > max_price: continue
        if km is not None and km > max_km: continue
        if year:
            try:
                if not (year_min <= int(year) <= year_max): continue
            except ValueError: pass
        
        trim = _extract_trim(text, make, model)
        sunroof = _extract_sunroof(text)
        
        results.append({
            "url": full, "title": text[:100], "year": year, "trim": trim,
            "price": ("$" + format(price, ",")) if price else None,
            "mileage": ("{:,} km".format(km)) if km else None,
            "sunroof": sunroof, "vehicle": vehicle_name,
        })
    
    if results:
        print(f"      Found {len(results)} listings via link scanning")
    else:
        print(f"      No listings found on AutoTrader page")
    
    return results

def parse_cargurus_listings(html_text, make, model, year_min, year_max, aliases, vehicle_name, max_price, max_km):
    """Parse CarGurus search results."""
    return _collect_listings_from_html(
        html_text, "https://www.cargurus.ca",
        ("/cars/", "inventorylisting"), make, model, year_min, year_max, aliases, vehicle_name, max_price, max_km
    )

def parse_clutch_listings(html_text, make, model, year_min, year_max, aliases, vehicle_name, max_price, max_km):
    """Parse Clutch.ca search results."""
    return _collect_listings_from_html(
        html_text, "https://clutch.ca",
       
