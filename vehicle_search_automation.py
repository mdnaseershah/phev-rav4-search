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
        "max_mileage": 70000,
        "aliases": ["outlander phev", "outlander plug-in", "outlander plug in", "outlander hybrid"],
        "urls": {
            "autotrader": "https://www.autotrader.ca/cars/mitsubishi/outlander/va_outlander-phev/reg_qc/cit_gatineau/pr_32000?offer=N%2CU&modelyearfrom=2022&modelyearto=2023&cy=CA&damaged_listing=exclude&desc=0&sort=standard&ustate=N%2CU&zip=Gatineau&zipr=500&lat=45.47723&lon=-75.70164&atype=C&mcat=ma50gr201018va1568&size=20",
            "cargurus": "https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&zip=J8T&distance=500&makeModelTrimPaths=m46%2Fd2652%2Cm46&nonShippableBaseline=127&sortDirection=ASC&sortType=DEAL_SCORE&maxMileage=70000&startYear=2022&endYear=2023&maxPrice=32000",
            "kijiji": "https://www.kijiji.ca/b-cars-trucks/canada/mitsubishi-outlander-phev/mitsubishi-outlander-2022__2023/k0c174l0a54a1000054a68?kilometers=0__70000&price=0__32000&view=list",
            "clutch": "https://www.clutch.ca/cars/mitsubishi-outlander-phev-under-32000?yearLow=2022&yearHigh=2023&mileageHigh=70000",
            "facebook": "https://www.facebook.com/marketplace/search/?query=Mitsubishi%20Outlander%20PHEV&maxPrice=32000",
            "kijiji_rss": "https://www.kijiji.ca/rss-srp-cars-trucks/gatineau/k0c174l1700312?price=0__32000&maxKilometers=70000&minYear=2022&maxYear=2023&radius=400&ad=offering&vehicleType=cars",
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
                if k <= vehicle_config.get("max_mileage", 120000) and k >= 500:
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

def _listing_value_score(listing):
    """Rank listings by best price-to-value. Lower score = better value."""
    price = _parse_money(listing.get("price"))
    km = _parse_km(listing.get("mileage"))
    
    vehicle_name = listing.get("vehicle", "")
    over_cap = 0
    for v in WANTED_VEHICLES:
        if v["vehicle"] == vehicle_name:
            max_km = v.get("max_mileage", 120000)
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
        ("/cars/",), make, model, year_min, year_max, aliases, vehicle_name, max_price, max_km
    )

def parse_kijiji_listings(html_text, make, model, year_min, year_max, aliases, vehicle_name, max_price, max_km):
    """Parse Kijiji search results."""
    if not html_text:
        return []
    
    soup = BeautifulSoup(html_text, "lxml")
    results = []
    seen_urls = set()
    
    for a in soup.select("a[href*='/v-cars-trucks/'], a[href*='/v-view-details/']"):
        href = a.get("href", "")
        full = urllib.parse.urljoin("https://www.kijiji.ca", href)
        if full in seen_urls:
            continue
        
        text = a.get_text(" ", strip=True) or ""
        if not _matches_model(text, make, _model_tokens(model, aliases)):
            continue
        
        year = _extract_year(text)
        if year:
            try:
                if not (year_min <= int(year) <= year_max): continue
            except ValueError: pass
        
        card = _card_text(a)
        price = _find_price(card)
        km = _find_mileage(card)
        trim = _extract_trim(text, make, model)
        sunroof = _extract_sunroof(card)
        
        if price is not None and price > max_price: continue
        if km is not None and km > max_km: continue
        
        seen_urls.add(full)
        results.append({
            "url": full, "title": text[:100], "year": year, "trim": trim,
            "price": ("$" + format(price, ",")) if price else None,
            "mileage": ("{:,} km".format(km)) if km else None,
            "sunroof": sunroof, "vehicle": vehicle_name,
        })
    
    # Fallback
    if not results:
        results = _collect_listings_from_html(
            html_text, "https://www.kijiji.ca",
            ("/v-cars-trucks", "/v-autos", "/v-view-details"),
            make, model, year_min, year_max, aliases, vehicle_name, max_price, max_km
        )
    
    return results


# -------------------------
# API-based parsers (primary, replace fragile Playwright rendering)
# -------------------------
def _parse_autotrader_ads_html(ads_html, make, model, y_min, y_max, aliases, vehicle_name, max_price, max_km):
    """Extract listings from the AdsHtml fragment returned by AutoTrader's search API."""
    soup = BeautifulSoup(ads_html, "lxml")
    token_groups = _model_tokens(model, aliases)
    results = []
    seen = set()
    # AutoTrader detail links look like /a/<make>/<model>/<city>/<province>/<id>/
    for a in soup.select("a[href*='/a/']"):
        href = a.get("href", "")
        full = urllib.parse.urljoin("https://www.autotrader.ca", href)
        if full in seen:
            continue
        card = _card_text(a)
        # Match on card text OR the href path (href always carries make/model).
        if not _matches_model(card + " " + href, make, token_groups):
            continue
        year = _extract_year(card)
        if year:
            try:
                if not (y_min <= int(year) <= y_max):
                    continue
            except ValueError:
                pass
        price = _find_price(card)
        km = _find_mileage(card)
        if price is not None and price > max_price:
            continue
        if km is not None and km > max_km:
            continue
        seen.add(full)
        title = a.get_text(" ", strip=True) or card[:100]
        results.append({
            "url": full, "title": title, "year": year,
            "trim": _extract_trim(title, make, model),
            "price": ("$" + format(price, ",")) if price is not None else None,
            "mileage": ("{:,} km".format(km)) if km is not None else None,
            "sunroof": _extract_sunroof(card), "vehicle": vehicle_name,
        })
    return results


def parse_autotrader_api(vehicle_name, vehicle_config):
    """Fetch AutoTrader listings via its internal Refinement/Search JSON API.

    The API returns an ``AdsHtml`` fragment containing the rendered listing cards,
    which is far more reliable than headlessly rendering the full search page.
    """
    make = vehicle_config["make"]
    model = vehicle_config["model"]
    at_model = vehicle_config.get("autotrader_model", model)
    y_min, y_max = vehicle_config["year_min"], vehicle_config["year_max"]
    aliases = vehicle_config.get("aliases", [])
    max_price = vehicle_config["max_price"]
    max_km = vehicle_config["max_mileage"]
    search_url = vehicle_config["urls"]["autotrader"]

    # Warm the session first so we carry the cookies the API expects.
    try:
        session.get(search_url, timeout=25)
    except Exception as e:
        print(f"    AutoTrader warm-up failed (continuing): {e}")

    payload = {
        "Address": "Gatineau, QC",
        "Proximity": 500,
        "Make": make,
        "Model": at_model,
        "IsNew": True,
        "IsUsed": True,
        "WithPhotos": True,
        "PriceMin": 0,
        "PriceMax": max_price,
        "YearMin": str(y_min),
        "YearMax": str(y_max),
        "OdometerMax": max_km,
        "Skip": 0,
        "Top": 30,
        "micrositeType": 1,
    }
    data = http_post_json(
        "https://www.autotrader.ca/Refinement/Search", payload,
        referer=search_url, origin="https://www.autotrader.ca",
    )
    if not data:
        return []
    ads_html = ""
    if isinstance(data, dict):
        ads_html = data.get("AdsHtml") or data.get("adsHtml") or data.get("_raw") or ""
    if not ads_html:
        print("    AutoTrader API returned no AdsHtml (payload/format may need tuning)")
        return []
    listings = _parse_autotrader_ads_html(
        ads_html, make, model, y_min, y_max, aliases, vehicle_name, max_price, max_km
    )
    print(f"    AutoTrader API: {len(listings)} listing(s)")
    return listings


def parse_cargurus_api(vehicle_name, vehicle_config):
    """Fetch CarGurus listings via its searchResults JSON endpoint."""
    make = vehicle_config["make"]
    model = vehicle_config["model"]
    y_min, y_max = vehicle_config["year_min"], vehicle_config["year_max"]
    max_price = vehicle_config["max_price"]
    max_km = vehicle_config["max_mileage"]
    entity = vehicle_config.get("cargurus_entity")
    zip_code = vehicle_config.get("cargurus_zip", "J8T")
    if not entity:
        print("    CarGurus: no entity id configured, skipping API")
        return []

    api = (
        "https://www.cargurus.ca/Cars/searchResults.action"
        f"?zip={zip_code}&distance=500&entitySelectingHelper.selectedEntity={entity}"
        f"&maxPrice={max_price}&startYear={y_min}&endYear={y_max}&maxMileage={max_km}"
        "&sortDir=ASC&sortType=DEAL_SCORE&offset=0&maxResults=30&filtersModified=true"
    )
    data = http_get_json(api, referer=vehicle_config["urls"]["cargurus"])
    if data is None:
        return []

    # Response is either a bare list or a dict wrapping the list.
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("listings", "tiles", "results", "searchResults"):
            if isinstance(data.get(key), list):
                items = data[key]
                break

    results = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        lid = it.get("id") or it.get("listingId")
        if not lid:
            continue
        url = f"https://www.cargurus.ca/Cars/inventorylisting/vdp.action?listingId={lid}"
        if url in seen:
            continue

        price = it.get("price") or it.get("expectedPrice")
        if price is None:
            price = _parse_money(it.get("expectedPriceString") or it.get("priceString"))
        km = it.get("mileage")
        if km is None:
            km = _parse_km(it.get("mileageString"))
        year = it.get("carYear") or it.get("year")
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None

        try:
            if price is not None and float(price) > max_price:
                continue
        except (TypeError, ValueError):
            pass
        try:
            if km is not None and float(km) > max_km:
                continue
        except (TypeError, ValueError):
            pass
        if year is not None and not (y_min <= year <= y_max):
            continue

        trim = it.get("trimName") or it.get("trim")
        seen.add(url)
        title = " ".join(str(x) for x in [year, make, model, trim] if x)
        results.append({
            "url": url, "title": title,
            "year": str(year) if year else None, "trim": trim,
            "price": ("$" + format(int(float(price)), ",")) if price not in (None, "") else None,
            "mileage": ("{:,} km".format(int(float(km)))) if km not in (None, "") else None,
            "sunroof": None, "vehicle": vehicle_name,
        })
    print(f"    CarGurus API: {len(results)} listing(s)")
    return results


def parse_clutch_api(vehicle_name, vehicle_config):
    """Fetch Clutch.ca listings from the __NEXT_DATA__ JSON embedded in the page.

    Clutch is a Next.js site: its search results are serialized into a
    <script id="__NEXT_DATA__"> tag on the initial HTML, so a plain request
    (no headless browser) is enough. We recursively scan for listing-like dicts.
    """
    make = vehicle_config["make"]
    model = vehicle_config["model"]
    y_min, y_max = vehicle_config["year_min"], vehicle_config["year_max"]
    aliases = vehicle_config.get("aliases", [])
    max_price = vehicle_config["max_price"]
    max_km = vehicle_config["max_mileage"]

    html = http_get(vehicle_config["urls"]["clutch"])
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        print("    Clutch: no __NEXT_DATA__ block found")
        return []
    try:
        blob = json.loads(tag.string)
    except Exception as e:
        print(f"    Clutch: __NEXT_DATA__ JSON parse failed: {e}")
        return []

    token_groups = _model_tokens(model, aliases)
    results = []
    seen = set()

    def _emit(obj):
        yr = obj.get("year") or obj.get("modelYear")
        mk = obj.get("make") or obj.get("makeName") or ""
        md = obj.get("model") or obj.get("modelName") or ""
        trim = obj.get("trim") or obj.get("trimName") or ""
        price = obj.get("price") or obj.get("listPrice") or obj.get("sellingPrice")
        km = obj.get("mileage") or obj.get("odometer") or obj.get("kilometres") or obj.get("kilometers")
        slug = obj.get("slug") or obj.get("url") or obj.get("vin") or obj.get("id")
        if not yr or not slug:
            return
        blob_text = f"{yr} {mk} {md} {trim}"
        if not _matches_model(blob_text, make, token_groups):
            return
        try:
            yri = int(yr)
        except (TypeError, ValueError):
            yri = None
        if yri is not None and not (y_min <= yri <= y_max):
            return
        try:
            if price is not None and float(price) > max_price:
                return
        except (TypeError, ValueError):
            pass
        try:
            if km is not None and float(km) > max_km:
                return
        except (TypeError, ValueError):
            pass
        s = str(slug)
        if s.startswith("http"):
            url = s
        elif "/" in s:
            url = urllib.parse.urljoin("https://www.clutch.ca", s)
        else:
            url = f"https://www.clutch.ca/cars/{s}"
        if url in seen:
            return
        seen.add(url)
        results.append({
            "url": url, "title": blob_text.strip(),
            "year": str(yri) if yri else None, "trim": trim or None,
            "price": ("$" + format(int(float(price)), ",")) if price not in (None, "") else None,
            "mileage": ("{:,} km".format(int(float(km)))) if km not in (None, "") else None,
            "sunroof": None, "vehicle": vehicle_name,
        })

    def walk(obj):
        if isinstance(obj, dict):
            try:
                _emit(obj)
            except Exception:
                pass
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(blob)
    print(f"    Clutch: {len(results)} listing(s)")
    return results


# -------------------------
# Dealer Probing
# -------------------------
def load_dealers_from_file():
    if os.path.exists(DEALERS_JSON):
        try:
            with open(DEALERS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data: return data
        except Exception as e: print(f"Failed to load {DEALERS_JSON}: {e}")
    return []


def _dealer_name_from_site(site):
    """Fallback friendly name derived from a dealer domain (e.g. 'Bank Street Toyota')."""
    parsed = urllib.parse.urlparse(site if "//" in site else "http://" + site)
    host = re.sub(r"^www\.", "", parsed.netloc or site, flags=re.I).split(".")[0]
    return re.sub(r"[-_]+", " ", host).strip().title() or "Dealer"

def _looks_like_vehicle_detail(href: str) -> bool:
    """True only for links that point at a *specific* vehicle detail page.

    Rejects generic inventory/category/nav links (the old bug returned the first
    of those, since it matched the make anywhere in the URL).
    """
    low = (href or "").lower()
    if not low or low.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    if not _is_listing_candidate(low):
        return False
    stripped = low.split("?")[0].split("#")[0].rstrip("/")
    # A bare category/index page is not a specific listing.
    if stripped.endswith((
        "/inventory", "/used-inventory", "/used", "/vehicles", "/cars",
        "/search", "/new-inventory", "/pre-owned", "/preowned", "/used-cars",
    )):
        return False
    detail_seg = any(seg in low for seg in (
        "/vehicle", "/vdp", "/inventory/", "/used/", "/detail", "/listing",
        "/cars/", "/vehicles/", "/pre-owned/", "/preowned/", "/auto/", "/stock",
    ))
    has_id = bool(re.search(r"\d{4,}", stripped))  # stock #, VIN fragment, or id
    return detail_seg and has_id


def _extract_jsonld_vehicles(html_text, base_url, make, model, aliases, vehicle_name,
                             y_min, y_max, max_price, max_km):
    """Parse schema.org JSON-LD vehicle listings from a dealer page.

    Canadian dealer platforms (D2C Media / EDealer / Convertus / Sincro) embed
    Car/Vehicle/Product structured data in <script type="application/ld+json">
    blocks on their inventory pages. This yields clean make/model/year/trim/price/
    mileage without a headless browser and is the most reliable dealer source.
    """
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "lxml")
    token_groups = _model_tokens(model, aliases)
    results = []
    seen = set()

    def _num(v):
        if isinstance(v, dict):
            v = v.get("value") or v.get("@value")
        return _parse_money(v) if v is not None else None

    def _handle(obj):
        if not isinstance(obj, dict):
            return
        t = obj.get("@type", "")
        types = [str(x).lower() for x in (t if isinstance(t, list) else [t])]
        if not any(x in ("car", "vehicle", "product", "individualproduct",
                          "motorizedvehicle") for x in types):
            return
        name = obj.get("name") or ""
        brand = obj.get("brand")
        brand_name = brand.get("name") if isinstance(brand, dict) else (brand or "")
        mdl = obj.get("model")
        if isinstance(mdl, dict):
            mdl = mdl.get("name", "")
        blob = f"{name} {brand_name} {mdl}"
        if not _matches_model(blob, make, token_groups):
            return
        offers = obj.get("offers")
        if isinstance(offers, list) and offers:
            offers = offers[0]
        offers = offers if isinstance(offers, dict) else {}
        # Detail URL: dealer feeds often put it on the Offer, not the Vehicle.
        url = obj.get("url") or obj.get("@id") or offers.get("url") or ""
        if url:
            url = urllib.parse.urljoin(base_url, url)
        if not url or url in seen:
            return
        year = None
        for k in ("vehicleModelDate", "modelDate", "productionDate",
                  "releaseDate", "dateVehicleFirstRegistered"):
            y = _extract_year(str(obj.get(k, "")))
            if y:
                year = y
                break
        if not year:
            year = _extract_year(name)  # year is commonly embedded in the name
        if year:
            try:
                if not (y_min <= int(year) <= y_max):
                    return
            except ValueError:
                pass
        price = _parse_money(offers.get("price") or offers.get("lowPrice"))
        if price is None:
            price = _parse_money(obj.get("price"))
        if price is not None and price > max_price:
            return
        km = _num(obj.get("mileageFromOdometer"))
        if km is not None and km > max_km:
            return
        trim = obj.get("vehicleConfiguration") or obj.get("trim")
        desc = obj.get("description") or ""
        seen.add(url)
        results.append({
            "url": url, "title": name or blob.strip(), "year": year, "trim": trim,
            "price": ("$" + format(int(price), ",")) if price is not None else None,
            "mileage": ("{:,} km".format(int(km))) if km is not None else None,
            "sunroof": _extract_sunroof(f"{name} {desc}"),
            "desc": desc, "vehicle": vehicle_name,
        })

    def walk(obj):
        if isinstance(obj, dict):
            _handle(obj)
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            walk(json.loads(raw))
        except Exception:
            continue  # some sites emit invalid/concatenated JSON-LD; skip those
    return results


def _extract_odometer(html_text):
    """Pull an odometer reading (km, int) from a dealer *detail* page.

    Standard Canadian dealer platforms (D2C Media / Sincro / Convertus, e.g.
    Rallye Mitsubishi) do NOT put mileage in their JSON-LD — it lives in a
    hidden form field on the vehicle detail page, e.g.
    `<input type="hidden" name="vehicle_odometer" value="43356" />`. We read
    that (in either attribute order), then fall back to a JSON-LD
    `mileageFromOdometer` if some platform provides it.
    """
    if not html_text:
        return None
    # Hidden form field named (vehicle_)odometer/mileage/kilometers, name/value
    # in either order. The `trade_vehicle_odometer` trade-in field is empty and
    # is excluded because its name has a `trade_` prefix the anchor rejects.
    name_alt = r'(?:vehicle_)?(?:odometer|mileage|kil(?:o)?met(?:er|re)s?)'
    for pat in (
        r'name=["\']' + name_alt + r'["\'][^>]*?value=["\']\s*([\d.,]+)\s*["\']',
        r'value=["\']\s*([\d.,]+)\s*["\'][^>]*?name=["\']' + name_alt + r'["\']',
    ):
        m = re.search(pat, html_text, re.I)
        if m:
            km = _parse_km(m.group(1))
            if km:
                return int(km)
    m = re.search(r'"mileageFromOdometer"[^0-9]{0,40}?([\d.,]+)', html_text, re.I)
    if m:
        km = _parse_km(m.group(1))
        if km:
            return int(km)
    return None


def _enrich_dealer_mileage(listings):
    """Fill in missing mileage by fetching each listing's detail page.

    Dealer inventory pages carry the JSON-LD listing but not the odometer, so
    for any listing still lacking mileage we fetch its detail URL and parse the
    hidden odometer field (see `_extract_odometer`). Runs concurrently.
    """
    need = [l for l in listings if not _parse_km(l.get("mileage")) and l.get("url")]
    if not need:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        fut = {ex.submit(http_get, l["url"]): l for l in need}
        for f in concurrent.futures.as_completed(fut):
            lst = fut[f]
            try:
                km = _extract_odometer(f.result())
            except Exception:
                km = None
            if km is not None:
                lst["mileage"] = "{:,} km".format(km)


def find_dealer_listings(html_text, base_url, make, model, aliases, vehicle_name,
                         y_min, y_max, max_price, max_km):
    """Return ALL genuine vehicle-detail listings on a dealer page.

    Tries schema.org JSON-LD first (clean, structured); falls back to anchor
    scanning that requires the visible text to name make + model AND the href to
    look like a real detail page (not just the make appearing in the domain).
    """
    if not html_text:
        return []
    # 1) Structured data — most reliable on standard dealer platforms.
    jsonld = _extract_jsonld_vehicles(html_text, base_url, make, model, aliases,
                                      vehicle_name, y_min, y_max, max_price, max_km)
    if jsonld:
        return jsonld
    # 2) Fallback: strict anchor scanning.
    soup = BeautifulSoup(html_text, "lxml")
    token_groups = _model_tokens(model, aliases)
    results = []
    seen = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not _looks_like_vehicle_detail(href):
            continue
        text = a.get_text(" ", strip=True) or ""
        card = _card_text(a)
        blob = (text + " " + card).strip()
        # Strict: make must be present AND a full model/alias token group present.
        if not _matches_model(blob, make, token_groups):
            continue
        year = _extract_year(text) or _extract_year(card)
        if year:
            try:
                if not (y_min <= int(year) <= y_max):
                    continue
            except ValueError:
                pass
        full = urllib.parse.urljoin(base_url, href)
        if full in seen:
            continue
        price = _find_price(card)
        km = _find_mileage(card)
        if price is not None and price > max_price:
            continue
        if km is not None and km > max_km:
            continue
        seen.add(full)
        title = text or f"{year or ''} {vehicle_name}".strip()
        results.append({
            "url": full, "title": title, "year": year,
            "trim": _extract_trim(text, make, model),
            "price": ("$" + format(price, ",")) if price is not None else None,
            "mileage": ("{:,} km".format(km)) if km is not None else None,
            "sunroof": _extract_sunroof(card), "vehicle": vehicle_name,
        })
    return results


# -------------------------
# Main Scrape Orchestration
# -------------------------
def scrape_and_populate_listings():
    global ALL_LISTINGS
    ALL_LISTINGS = []
    
    # Map each dealer website -> display name (used as the listing Source).
    dealer_name_by_site = {}
    for d in [*load_dealers_from_file(), *POPULAR_DEALER_SITES]:
        w = d.get("website")
        if w:
            dealer_name_by_site.setdefault(w, d.get("name") or _dealer_name_from_site(w))
    dealer_sites = list(dealer_name_by_site)
    
    for wanted in WANTED_VEHICLES:
        vehicle_name = wanted["vehicle"]
        make = wanted["make"]
        model = wanted["model"]
        y_min, y_max = wanted["year_min"], wanted["year_max"]
        max_price = wanted["max_price"]
        max_km = wanted["max_mileage"]
        aliases = wanted.get("aliases", [])
        urls = wanted["urls"]
        
        print(f"\n{'='*60}")
        print(f"Searching: {vehicle_name}")
        print(f"{'='*60}")
        vehicle_listings = []
        
        # ---- 1. Kijiji RSS (most reliable) ----
        try:
            rss_results = parse_kijiji_rss(vehicle_name, wanted)
            vehicle_listings.extend(rss_results)
        except Exception as e:
            print(f"    Kijiji RSS error: {e}")
        
        # ---- 2. AutoTrader (internal search API) ----
        print(f"\n  --- AutoTrader ---")
        try:
            at_listings = parse_autotrader_api(vehicle_name, wanted)
            vehicle_listings.extend(at_listings)
            # Fallback: if the API yields nothing, try headless rendering.
            if not at_listings and PLAYWRIGHT_AVAILABLE:
                print(f"    AutoTrader API empty; trying Playwright fallback...")
                at_html = fetch_rendered_html(urls["autotrader"])
                if at_html:
                    fb = parse_autotrader_listings(at_html, make, model, y_min, y_max, aliases, vehicle_name, max_price, max_km)
                    print(f"    AutoTrader Playwright fallback: {len(fb)} listing(s)")
                    vehicle_listings.extend(fb)
        except Exception as e:
            print(f"    AutoTrader error: {e}")

        # ---- 3. CarGurus (internal search API) ----
        print(f"\n  --- CarGurus ---")
        try:
            vehicle_listings.extend(parse_cargurus_api(vehicle_name, wanted))
        except Exception as e:
            print(f"    CarGurus error: {e}")

        # ---- 4. Kijiji Web (requests fallback) ----
        print(f"\n  --- Kijiji Web ---")
        kj_html = http_get(urls["kijiji"])
        if kj_html:
            kj_listings = parse_kijiji_listings(kj_html, make, model, y_min, y_max, aliases, vehicle_name, max_price, max_km)
            print(f"    Kijiji Web result: {len(kj_listings)} listing(s)")
            vehicle_listings.extend(kj_listings)

        # ---- 5. Clutch.ca (__NEXT_DATA__ JSON, no browser needed) ----
        print(f"\n  --- Clutch.ca ---")
        try:
            vehicle_listings.extend(parse_clutch_api(vehicle_name, wanted))
        except Exception as e:
            print(f"    Clutch error: {e}")

        # ---- 6. Local dealer probing ----
        print(f"\n  --- Local Dealers ({len(dealer_sites)} sites) ---")
        dealer_tasks = []
        make_q = urllib.parse.quote_plus(make)
        model_q = urllib.parse.quote_plus(model)
        # Model-filtered inventory URLs surface deep inventory directly — the bare
        # index only shows page 1 (e.g. Rallye's used 2022 Outlander PHEV only
        # appears under /en/pre-owned?make=Mitsubishi&model=Outlander+PHEV).
        # Cover BOTH the Used/Pre-Owned and Certified Pre-Owned (CPO) sections;
        # a CPO unit isn't always cross-listed under plain pre-owned.
        filtered_paths = [
            f"/en/pre-owned?make={make_q}&model={model_q}",
            f"/en/certified-inventory?make={make_q}&model={model_q}",
            f"/en/certified?make={make_q}&model={model_q}",
            f"/en/inventory?make={make_q}&model={model_q}",
            f"/pre-owned?make={make_q}&model={model_q}",
            f"/certified-inventory?make={make_q}&model={model_q}",
            f"/inventory?make={make_q}&model={model_q}",
        ]
        # Plain inventory index paths (dealers that list everything on one page, or
        # that 301 to the right place, e.g. /en/used-inventory -> /en/pre-owned).
        index_paths = [
            "/en/pre-owned", "/en/certified-inventory", "/en/certified",
            "/en/inventory?type=used", "/en/inventory", "/en/used-inventory",
            "/used-inventory", "/certified-inventory", "/inventory?type=used",
            "/inventory", "/used", "/vehicles",
        ]
        for site in dealer_sites:
            base = site.rstrip("/")
            for path in filtered_paths + index_paths:
                dealer_tasks.append((base + path, site))

        dealer_found = []
        seen_dealer_urls = set()
        if dealer_tasks:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_task = {executor.submit(fetch_url, task): task for task in dealer_tasks}
                for future in concurrent.futures.as_completed(future_to_task):
                    task = future_to_task[future]
                    site_label, html = future.result()
                    for lst in find_dealer_listings(html, site_label, make, model, aliases,
                                                     vehicle_name, y_min, y_max, max_price, max_km):
                        if lst["url"] not in seen_dealer_urls:
                            seen_dealer_urls.add(lst["url"])
                            lst["source"] = (dealer_name_by_site.get(site_label)
                                             or _dealer_name_from_site(site_label))
                            dealer_found.append(lst)

        if dealer_found:
            # Collapse the same car found under multiple probe-path URLs BEFORE
            # enrichment so each detail page is fetched once, not per path.
            dealer_found = _dedup_listings(dealer_found, wanted)
            # Dealer inventory pages omit the odometer — fetch each detail page
            # to fill in mileage, then drop anything now shown to be over the cap.
            _enrich_dealer_mileage(dealer_found)
            dealer_found = [l for l in dealer_found
                            if not ((_parse_km(l.get("mileage")) or 0) > max_km)]
            print(f"    Found {len(dealer_found)} real listing(s) on dealer sites")
            vehicle_listings.extend(dealer_found)

        # ---- Deduplicate (same car across probe paths + marketplaces) ----
        unique = _dedup_listings(vehicle_listings, wanted)

        if unique:
            print(f"\n  ✅ Total unique listings for {vehicle_name}: {len(unique)}")
            ALL_LISTINGS.extend(unique)
        else:
            print(f"\n  ⚠ No listings found for {vehicle_name}. Using fallback search link.")
            ALL_LISTINGS.append({
                "url": urls["autotrader"], "title": f"{vehicle_name} (Click to search)",
                "year": None, "trim": None, "price": None,
                "mileage": None, "sunroof": None, "vehicle": vehicle_name,
                "is_fallback": True,
            })
    
    print(f"\n{'='*60}")
    print(f"Total listings across all vehicles: {len(ALL_LISTINGS)}")
    print(f"{'='*60}")


# -------------------------
# HTML Generation
# -------------------------
def generate_dealers_html():
    dealers = load_dealers_from_file()
    if not dealers:
        return "<html><body><p>No dealers found.</p></body></html>"
    rows = "".join([f"<tr><td><a href='{d.get('website','#')}'>{d.get('name','')}</a></td><td>{d.get('brand','')}</td><td>{d.get('city','')}</td><td>{d.get('distance_km','')} km</td></tr>" for d in dealers])
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Dealers</title><style>body{{font-family:Arial;margin:20px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border:1px solid #ddd;text-align:left}}th{{background:#f0f0f0}}</style></head><body><h2>Dealers ({len(dealers)})</h2><table><thead><tr><th>Dealer</th><th>Brand</th><th>City</th><th>Distance</th></tr></thead><tbody>{rows}</tbody></table></body></html>"

# Short, human-readable feature tags for the Description column, matched against
# a listing's title/description text (label, regex).
FEATURE_PATTERNS = [
    ("Sunroof", r"(?i)\b(sun ?roof|moon ?roof|panoramic)\b"),
    ("Leather", r"(?i)\bleather\b"),
    ("Heated Seats", r"(?i)\bheated (front |rear )?seats?\b"),
    ("CarPlay", r"(?i)\b(apple )?car ?play\b"),
    ("Android Auto", r"(?i)\bandroid auto\b"),
    ("Navigation", r"(?i)\b(navigation|nav system|gps nav)\b"),
    ("AWD", r"(?i)\b(s-awc|awd|all[- ]wheel)\b"),
    ("Backup Cam", r"(?i)\b(back(-| )?up cam|rear(view)? cam|reverse cam)\w*"),
    ("Remote Start", r"(?i)\bremote start\b"),
    ("Certified", r"(?i)\bcertified\b"),
    ("Warranty", r"(?i)\bwarranty\b"),
]


def _clean_trim(text, vehicle_config):
    """Return one clean trim token (e.g. 'SEL', 'SE S-AWC') from text, or None."""
    if not text or not vehicle_config:
        return None
    for tr in sorted(vehicle_config.get("trims", []), key=len, reverse=True):
        if re.search(r"(?i)\b" + re.escape(tr) + r"\b", text):
            return tr
    return None


# Sunroof presence inferred from trim, per vehicle. Lets us state sunroof
# confidently in the Description even when a listing/dealer feed omits it.
#   True  = sunroof standard on that trim   False = no sunroof on that trim
# Only trims we are confident about are listed; anything absent -> unknown,
# and we fall back to whatever the listing text says.
#
# Validated (2026) for the Canadian Mitsubishi Outlander PHEV, both the 2022
# (3rd-gen) and all-new 2023 lineups: the base **ES has no sunroof**, and the
# **panoramic sunroof is standard from the LE trim up** (LE / SEL / GT /
# GT Premium / Black Edition). Confirmed against Mitsubishi Canada trim data and
# a live Rallye 2022 "LE" listing (lists "panoramic sunroof").
#   - "SE" is deliberately omitted: it's inconsistent across model years.
#   - RAV4 Prime is omitted entirely: its moonroof is an option package on both
#     SE and XSE, so it can't be implied from the trim — we trust listing text.
SUNROOF_BY_TRIM = {
    "Mitsubishi Outlander PHEV": {
        "ES": False, "ES S-AWC": False,
        "LE": True, "LE S-AWC": True,
        "SEL": True,
        "GT": True, "GT S-AWC": True, "GT Premium": True,
        "Black Edition": True,
    },
}


def _sunroof_status(listing, vehicle_config):
    """Return 'yes' / 'no' / None for a listing's sunroof.

    Trusts an explicit mention in the listing first, then falls back to the
    confident trim -> sunroof map (SUNROOF_BY_TRIM) so we can state sunroof even
    when a dealer feed doesn't. None = genuinely unknown (don't claim either way).
    """
    text = " ".join(str(listing.get(k) or "") for k in ("title", "desc"))
    if re.search(r"(?i)\b(sun ?roof|moon ?roof|panoramic)\b", text) \
       or str(listing.get("sunroof", "")).strip().lower() in ("yes", "y", "true"):
        return "yes"
    trim = _clean_trim(
        " ".join(str(listing.get(k) or "") for k in ("title", "trim", "desc")),
        vehicle_config)
    table = SUNROOF_BY_TRIM.get((vehicle_config or {}).get("vehicle", ""), {})
    if trim in table:
        return "yes" if table[trim] else "no"
    return None


def _vehicle_label(listing, vehicle_config):
    """Compose a clean 'YEAR Make Model Trim' label — no marketing/description text."""
    year = str(listing.get("year") or "").strip()
    base = (listing.get("vehicle") or "").strip()
    src = " ".join(str(listing.get(k) or "") for k in ("title", "trim", "desc"))
    trim = _clean_trim(src, vehicle_config)
    if not trim:
        raw = (listing.get("trim") or "").strip()
        # Accept a raw trim only if it's short and not a marketing blob.
        if raw and len(raw) <= 18 and not re.search(r"\d{3,}", raw):
            trim = raw
    label = " ".join(p for p in [year, base, trim] if p).strip()
    return label or (listing.get("title") or base or "Vehicle")


def _short_description(listing, vehicle_config=None):
    """A short, clear feature summary (e.g. 'Sunroof, Leather, AWD'), or '' if none.

    Sunroof leads the summary and is trim-aware: 'Sunroof' when we're confident
    it's present (listing text or trim), 'No Sunroof' when the trim confirms it
    has none, and silence when genuinely unknown.
    """
    text = " ".join(str(listing.get(k) or "") for k in ("title", "desc"))
    found = []
    status = _sunroof_status(listing, vehicle_config)
    if status == "yes":
        found.append("Sunroof")
    elif status == "no":
        found.append("No Sunroof")
    for label, pat in FEATURE_PATTERNS:
        if label == "Sunroof":
            continue  # handled above (trim-aware)
        if re.search(pat, text) and label not in found:
            found.append(label)
        if len(found) >= 5:
            break
    return ", ".join(found)


def generate_email_html(est_now):
    # Marketplace quick links
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
    
    ranked = sorted(ALL_LISTINGS, key=_listing_value_score)
    em_dash = "\u2014"
    
    def listing_row(rank, listing):
        url = listing.get("url", "#")
        is_fallback = listing.get("is_fallback", False)
        vname = listing.get("vehicle", "")
        w = next((v for v in WANTED_VEHICLES if v["vehicle"] == vname), None)

        if is_fallback or not url or "example.com" in url:
            url = w["urls"]["autotrader"] if w else "#"

        price_disp = listing.get("price") or em_dash
        mileage_disp = listing.get("mileage") or em_dash

        if listing.get("source"):  # dealer listings carry the dealership name
            source = listing["source"]
        elif is_fallback:
            source = "Search"
        elif "autotrader" in url.lower(): source = "AutoTrader"
        elif "cargurus" in url.lower(): source = "CarGurus"
        elif "kijiji" in url.lower(): source = "Kijiji"
        elif "clutch" in url.lower(): source = "Clutch"
        elif "facebook" in url.lower(): source = "Facebook"
        else: source = "Dealer"

        # Vehicle column: clean 'YEAR Make Model Trim' only.
        vehicle_disp = _vehicle_label(listing, w)
        # Description column: short feature summary incl. trim-aware sunroof.
        desc_disp = _short_description(listing, w) or em_dash

        td = "padding:9px 10px;border-bottom:1px solid #eee;vertical-align:top;"
        return f"""<tr>
<td style="{td}text-align:center;color:#888;font-weight:bold;">{rank}</td>
<td style="{td}"><a href="{url}" target="_blank" style="color:#2563eb;font-weight:600;text-decoration:none;">{vehicle_disp}</a></td>
<td style="{td}white-space:nowrap;font-weight:600;">{price_disp}</td>
<td style="{td}white-space:nowrap;color:#555;">{mileage_disp}</td>
<td style="{td}color:#555;font-size:13px;">{desc_disp}</td>
<td style="{td}color:#555;font-size:13px;">{source}</td>
</tr>"""

    if ranked:
        all_rows = [listing_row(rank, lst) for rank, lst in enumerate(ranked, start=1)]
        table_rows = "".join(all_rows)
    else:
        table_rows = '<tr><td colspan="6" style="padding:20px;text-align:center;color:#888;">No listings found. Use quick links below.</td></tr>'
    
    real_count = sum(1 for l in ALL_LISTINGS if not l.get("is_fallback") and l.get("url") and "example.com" not in l.get("url", ""))
    
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;margin:0;padding:20px;color:#333;line-height:1.6;">
    <h2 style="color:#2563eb;margin-top:0;">Daily Vehicle Search Results</h2>
    <p style="color:#555;font-size:14px;">Generated on: {est_now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}</p>
    <p style="color:#555;font-size:13px;">{real_count} real listing(s) found. <span style="color:#999;">Click a title to open the actual listing page.</span></p>
    
    <h3 style="border-bottom:2px solid #eee;padding-bottom:5px;margin-top:30px;">Ranked Listings (Best Value First)</h3>
    <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;margin-top:10px;">
    <table style="width:100%;min-width:640px;border-collapse:collapse;table-layout:fixed;font-size:14px;border:1px solid #eee;">
        <colgroup>
            <col style="width:44px;">
            <col style="width:24%;">
            <col style="width:82px;">
            <col style="width:92px;">
            <col style="width:auto;">
            <col style="width:16%;">
        </colgroup>
        <thead>
        <tr style="background:#f8f9fa;text-align:left;">
            <th style="padding:9px 10px;border-bottom:2px solid #e5e7eb;text-align:center;">#</th>
            <th style="padding:9px 10px;border-bottom:2px solid #e5e7eb;">Vehicle</th>
            <th style="padding:9px 10px;border-bottom:2px solid #e5e7eb;">Price</th>
            <th style="padding:9px 10px;border-bottom:2px solid #e5e7eb;">Mileage</th>
            <th style="padding:9px 10px;border-bottom:2px solid #e5e7eb;">Description</th>
            <th style="padding:9px 10px;border-bottom:2px solid #e5e7eb;">Source</th>
        </tr>
        </thead>
        <tbody>
        {table_rows}
        </tbody>
    </table>
    </div>

    <h3 style="border-bottom:2px solid #eee;padding-bottom:5px;margin-top:40px;">Marketplace Quick Links</h3>
    <p style="font-size:13px;color:#555;">One-click searches using exact strict filters.</p>
    {buttons_html}
    
    <hr style="margin-top:30px;border:none;border-top:1px solid #eee;">
    <p style="font-size:11px;color:#aaa;text-align:center;">
        Vehicle Search Automation &mdash; {est_now.strftime('%B %d, %Y at %I:%M %p %Z')}
    </p>
</body>
</html>"""

# -------------------------
# Email Sending
# -------------------------
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
        print(f"✅ Email sent to {RECIPIENT_EMAIL}")
    except Exception as e:
        print(f"❌ Error sending email: {e}")

# -------------------------
# Main
# -------------------------
def main():
    est_now = datetime.now(EST)
    
    # DST-safe schedule guard
    github_event = os.getenv('GITHUB_EVENT_NAME', '')
    if github_event not in ('', 'workflow_dispatch'):
        eastern_hour = est_now.hour
        if eastern_hour != 7:
            print(f"Skipping: Eastern hour is {eastern_hour}, not 7. "
                  f"Triggered by '{github_event}'.")
            return
    
    print(f"{'='*60}")
    print(f"  Vehicle Search Automation V3")
    print(f"  Started: {est_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Playwright available: {PLAYWRIGHT_AVAILABLE}")
    print(f"{'='*60}")
    
    if ENABLE_SCRAPE:
        scrape_and_populate_listings()
    
    print(f"\nGenerating HTML files...")
    email_html = generate_email_html(est_now)
    with open("gatineau_phev_rav4_search_results.html", "w", encoding="utf-8") as f:
        f.write(email_html)
    with open("dealers.html", "w", encoding="utf-8") as f:
        f.write(generate_dealers_html())
    
    print(f"Sending email...")
    send_email(
        f"Vehicle Search Update: {est_now.strftime('%b %d')} (Gatineau PHEV/RAV4)",
        email_html
    )
    print(f"\n{'='*60}")
    print(f"  Done!")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
