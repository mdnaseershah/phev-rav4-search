#!/usr/bin/env python3
"""
vehicle_search_automation.py

Enhanced scraper that uses Playwright for JS-rendered marketplaces (AutoTrader, CarGurus)
and requests for simpler sites (Kijiji, Clutch). 
Collects ALL listings from all sources, ranks them by price-to-value,
and sends an email with clickable links to actual listings (not search pages).
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

# Try to import Playwright (gracefully fall back if not installed)
try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Playwright not installed. JS-rendered sites (AutoTrader, CarGurus) will not return listings.")

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
            "facebook": "https://www.facebook.com/marketplace/search/?query=Mitsubishi%20Outlander%20PHEV&maxPrice=32000"
        }
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
            "facebook": "https://www.facebook.com/marketplace/search/?query=Toyota%20RAV4%20Prime&maxPrice=42000"
        }
    },
]

# -------------------------
# Global list of ALL found listings (populated by scrape_and_populate_listings)
# -------------------------
ALL_LISTINGS = []

# -------------------------
# HTTP & Playwright Helpers
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

def fetch_rendered_html(url, timeout=30000):
    """Fetch a page with full JS rendering using Playwright (for AutoTrader, CarGurus, etc.)"""
    if not PLAYWRIGHT_AVAILABLE:
        print(f"Playwright not available, cannot render JS for: {url}")
        return None
    try:
        with _sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"Playwright render failed for {url}: {e}")
        return None

def fetch_url(task):
    """Worker function for threading (requests only)"""
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
    """Rank listings by best price-to-value. Lower score = better value."""
    price = _parse_money(listing.get("price"))
    km = _parse_km(listing.get("mileage"))
    
    # Determine over-cap based on vehicle type
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

def _collect_listings_from_html(html_text, base_url, path_markers, make, model, year_min, year_max, aliases, vehicle_name):
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
        
        # Filter by mileage cap for this vehicle
        vehicle_config = next((v for v in WANTED_VEHICLES if v["vehicle"] == vehicle_name), None)
        max_km = vehicle_config.get("max_mileage", 120000) if vehicle_config else 120000
        km = _parse_km(details.get("mileage"))
        if km is not None and km > max_km:
            continue
        
        # Filter by price cap
        max_price = vehicle_config.get("max_price", 100000) if vehicle_config else 100000
        price = _parse_money(details.get("price"))
        if price is not None and price > max_price:
            continue
        
        # Check year is in range
        yr = _extract_year(details.get("title"))
        if yr:
            try:
                if not (year_min <= int(yr) <= year_max):
                    continue
            except ValueError:
                pass
        
        # Add the vehicle name to the details
        details["vehicle"] = vehicle_name
        
        results.append(details)
    
    return results

# -------------------------
# Marketplace-specific parsers
# -------------------------
def parse_autotrader_listings(html_text, make, model, year_min, year_max, aliases, vehicle_name):
    """Parse AutoTrader search results page for ALL listings."""
    if not html_text:
        return []
    
    soup = BeautifulSoup(html_text, "lxml")
    token_groups = _model_tokens(model, aliases)
    results = []
    seen_urls = set()
    
    # Try multiple strategies to find listing cards
    
    # Strategy 1: Find all article/card elements with listing data
    for selector in [".listing-card", ".result-item", "article[data-listing-id]", "div[data-listing-id]", 
                     ".listing", ".vehicle-card", ".search-item", ".card-body"]:
        cards = soup.select(selector)
        if cards:
            for card in cards:
                links = card.select("a[href]")
                for a in links:
                    href = a.get("href", "")
                    full = urllib.parse.urljoin("https://www.autotrader.ca", href)
                    if full in seen_urls:
                        continue
                    text = card.get_text(" ", strip=True) or ""
                    if not _matches_model(text, make, token_groups) and not _year_in_range(text, year_min, year_max):
                        continue
                    
                    # Extract details from the card
                    price = _find_price(text)
                    km = _find_mileage(text)
                    year = _extract_year(text)
                    trim = _extract_trim(text, make, model)
                    sunroof = _extract_sunroof(text)
                    
                    # Get title from the link itself
                    title = a.get_text(" ", strip=True) or text[:100]
                    
                    # Filter by caps
                    vehicle_config = next((v for v in WANTED_VEHICLES if v["vehicle"] == vehicle_name), None)
                    max_km = vehicle_config.get("max_mileage", 120000) if vehicle_config else 120000
                    max_price = vehicle_config.get("max_price", 100000) if vehicle_config else 100000
                    if price is not None and price > max_price:
                        continue
                    if km is not None and km > max_km:
                        continue
                    if year:
                        try:
                            if not (year_min <= int(year) <= year_max):
                                continue
                        except ValueError:
                            pass
                    
                    seen_urls.add(full)
                    results.append({
                        "url": full,
                        "title": title,
                        "year": year,
                        "trim": trim,
                        "price": ("$" + format(price, ",")) if price is not None else None,
                        "mileage": ("{:,} km".format(km)) if km is not None else None,
                        "sunroof": sunroof,
                        "vehicle": vehicle_name,
                    })
            if results:
                break
    
    # Strategy 2: Fall back to generic anchor scanning
    if not results:
        results = _collect_listings_from_html(
            html_text, "https://www.autotrader.ca", 
            ("/cars/",), make, model, year_min, year_max, aliases, vehicle_name
        )
    
    return results

def parse_cargurus_listings(html_text, make, model, year_min, year_max, aliases, vehicle_name):
    """Parse CarGurus search results for ALL listings."""
    return _collect_listings_from_html(
        html_text, "https://www.cargurus.ca",
        ("/cars/", "inventorylisting"), make, model, year_min, year_max, aliases, vehicle_name
    )

def parse_kijiji_listings(html_text, make, model, year_min, year_max, aliases, vehicle_name):
    """Parse Kijiji search results for ALL listings."""
    if not html_text:
        return []
    
    soup = BeautifulSoup(html_text, "lxml")
    token_groups = _model_tokens(model, aliases)
    results = []
    seen_urls = set()
    
    # Kijiji listings are typically in <a> tags with specific classes
    for a in soup.select("a[href*='/v-cars-trucks/'], a[href*='/v-view-details/']"):
        href = a.get("href", "")
        full = urllib.parse.urljoin("https://www.kijiji.ca", href)
        if full in seen_urls:
            continue
        
        text = a.get_text(" ", strip=True) or ""
        if not _matches_model(text, make, token_groups):
            continue
        
        year = _extract_year(text)
        if year:
            try:
                if not (year_min <= int(year) <= year_max):
                    continue
            except ValueError:
                pass
        
        # Find the price in the card context
        card = _card_text(a)
        price = _find_price(card)
        km = _find_mileage(card)
        trim = _extract_trim(text, make, model)
        sunroof = _extract_sunroof(card)
        
        # Filter by price/mileage caps
        vehicle_config = next((v for v in WANTED_VEHICLES if v["vehicle"] == vehicle_name), None)
        max_km = vehicle_config.get("max_mileage", 120000) if vehicle_config else 120000
        max_price = vehicle_config.get("max_price", 100000) if vehicle_config else 100000
        
        if price is not None and price > max_price:
            continue
        if km is not None and km > max_km:
            continue
        
        seen_urls.add(full)
        results.append({
            "url": full,
            "title": text[:100],
            "year": year,
            "trim": trim,
            "price": ("$" + format(price, ",")) if price is not None else None,
            "mileage": ("{:,} km".format(km)) if km is not None else None,
            "sunroof": sunroof,
            "vehicle": vehicle_name,
        })
    
    # Fall back to generic scanning if Kijiji-specific selectors didn't work
    if not results:
        results = _collect_listings_from_html(
            html_text, "https://www.kijiji.ca",
            ("/v-cars-trucks", "/v-autos", "/v-view-details"), 
            make, model, year_min, year_max, aliases, vehicle_name
        )
    
    return results

def parse_clutch_listings(html_text, make, model, year_min, year_max, aliases, vehicle_name):
    """Parse Clutch.ca search results for ALL listings."""
    return _collect_listings_from_html(
        html_text, "https://clutch.ca",
        ("/cars/",), make, model, year_min, year_max, aliases, vehicle_name
    )

# -------------------------
# Dealer & Local Probing
# -------------------------
def load_dealers_from_file():
    if os.path.exists(DEALERS_JSON):
        try:
            with open(DEALERS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data: return data
        except Exception as e: print(f"Failed to load {DEALERS_JSON}: {e}")
    return []

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

# -------------------------
# Main Scrape Orchestration
# -------------------------
def scrape_and_populate_listings():
    global ALL_LISTINGS
    ALL_LISTINGS = []  # Reset each run
    
    dealer_sites = list(set(d.get("website") for d in load_dealers_from_file() if d.get("website")))
    
    for wanted in WANTED_VEHICLES:
        vehicle_name = wanted["vehicle"]
        make = wanted["make"]
        model = wanted["model"]
        y_min, y_max = wanted["year_min"], wanted["year_max"]
        aliases = wanted.get("aliases", [])
        urls = wanted["urls"]
        
        print(f"\nSearching for: {vehicle_name}")
        vehicle_listings = []
        
        # --- AutoTrader (JS-rendered, use Playwright if available) ---
        if PLAYWRIGHT_AVAILABLE:
            print(f"  Fetching AutoTrader (with JS rendering)...")
            at_html = fetch_rendered_html(urls["autotrader"])
            if at_html:
                at_listings = parse_autotrader_listings(at_html, make, model, y_min, y_max, aliases, vehicle_name)
                print(f"    Found {len(at_listings)} listing(s) on AutoTrader")
                vehicle_listings.extend(at_listings)
        else:
            print(f"  Skipping AutoTrader (Playwright not available for JS rendering)")
        
        # --- CarGurus (JS-rendered, use Playwright if available) ---
        if PLAYWRIGHT_AVAILABLE:
            print(f"  Fetching CarGurus (with JS rendering)...")
            cg_html = fetch_rendered_html(urls["cargurus"])
            if cg_html:
                cg_listings = parse_cargurus_listings(cg_html, make, model, y_min, y_max, aliases, vehicle_name)
                print(f"    Found {len(cg_listings)} listing(s) on CarGurus")
                vehicle_listings.extend(cg_listings)
        else:
            print(f"  Skipping CarGurus (Playwright not available for JS rendering)")
        
        # --- Kijiji (server-rendered, use requests) ---
        print(f"  Fetching Kijiji...")
        kj_html = http_get(urls["kijiji"])
        if kj_html:
            kj_listings = parse_kijiji_listings(kj_html, make, model, y_min, y_max, aliases, vehicle_name)
            print(f"    Found {len(kj_listings)} listing(s) on Kijiji")
            vehicle_listings.extend(kj_listings)
        
        # --- Clutch (server-rendered, use requests) ---
        print(f"  Fetching Clutch.ca...")
        cl_html = http_get(urls["clutch"])
        if cl_html:
            cl_listings = parse_clutch_listings(cl_html, make, model, y_min, y_max, aliases, vehicle_name)
            print(f"    Found {len(cl_listings)} listing(s) on Clutch")
            vehicle_listings.extend(cl_listings)
        
        # --- Local dealer probing ---
        print(f"  Probing {len(dealer_sites)} local dealer websites...")
        dealer_tasks = []
        for site in dealer_sites:
            for path in ["/used-inventory", "/inventory", "/used", "/search"]:
                dealer_tasks.append((site.rstrip("/") + path, site))
        
        dealer_found_urls = []
        if dealer_tasks:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_task = {executor.submit(fetch_url, task): task for task in dealer_tasks}
                for future in concurrent.futures.as_completed(future_to_task):
                    task = future_to_task[future]
                    site, html = future.result()
                    found = find_listing_in_dealer_html(html, site, make, model)
                    if found and found not in dealer_found_urls:
                        dealer_found_urls.append(found)
        
        if dealer_found_urls:
            print(f"    Found {len(dealer_found_urls)} listing(s) on dealer sites")
            for url in dealer_found_urls:
                vehicle_listings.append({
                    "url": url,
                    "title": f"{vehicle_name} (Dealer)",
                    "year": None, "trim": None,
                    "price": None, "mileage": None, "sunroof": None,
                    "vehicle": vehicle_name,
                })
        
        # Deduplicate by URL
        seen = set()
        unique_listings = []
        for lst in vehicle_listings:
            u = lst.get("url", "")
            if u and u not in seen:
                seen.add(u)
                unique_listings.append(lst)
        
        if unique_listings:
            print(f"  Total unique listings for {vehicle_name}: {len(unique_listings)}")
            ALL_LISTINGS.extend(unique_listings)
        else:
            print(f"  No listings found for {vehicle_name}. Using fallback search URL.")
            ALL_LISTINGS.append({
                "url": urls["autotrader"],
                "title": f"{vehicle_name} (Click to search)",
                "year": None, "trim": None,
                "price": None, "mileage": None, "sunroof": None,
                "vehicle": vehicle_name,
                "is_fallback": True,
            })
    
    print(f"\nTotal listings collected across all vehicles: {len(ALL_LISTINGS)}")

# -------------------------
# HTML Generation
# -------------------------
def generate_dealers_html():
    dealers = load_dealers_from_file()
    if not dealers:
        return "<html><body><p>No dealers found.</p></body></html>"
    rows = "".join([f"<tr><td><a href='{d.get('website','#')}'>{d.get('name','')}</a></td><td>{d.get('brand','')}</td><td>{d.get('city','')}</td><td>{d.get('distance_km','')} km</td></tr>" for d in dealers])
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Dealers</title><style>body{{font-family:Arial;margin:20px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border:1px solid #ddd;text-align:left}}th{{background:#f0f0f0}}</style></head><body><h2>Dealers ({len(dealers)})</h2><table><thead><tr><th>Dealer</th><th>Brand</th><th>City</th><th>Distance</th></tr></thead><tbody>{rows}</tbody></table></body></html>"

def generate_email_html(est_now):
    # Build the marketplace quick links HTML
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
    
    # Rank ALL listings by value score
    ranked = sorted(ALL_LISTINGS, key=_listing_value_score)
    
    em_dash = "\u2014"
    
    def listing_row(rank, listing):
        """Generate an HTML table row for a single listing."""
        url = listing.get("url", "#")
        title = listing.get("title") or listing.get("vehicle", "Vehicle")
        
        # If it's a fallback (no real listing found), mark it
        is_fallback = listing.get("is_fallback", False)
        if is_fallback or not url or "example.com" in url:
            # Use the vehicle's search URL instead
            vehicle_name = listing.get("vehicle", "")
            wanted = next((v for v in WANTED_VEHICLES if v["vehicle"] == vehicle_name), None)
            url = wanted["urls"]["autotrader"] if wanted else "#"
            link_label = "View Search Results \u2192"
        else:
            link_label = title
        
        price_disp = listing.get("price") or em_dash
        mileage_disp = listing.get("mileage") or em_dash
        sunroof_disp = listing.get("sunroof") or em_dash
        
        # Determine source for display
        if is_fallback:
            source = "Search"
        elif "autotrader" in url.lower():
            source = "AutoTrader"
        elif "cargurus" in url.lower():
            source = "CarGurus"
        elif "kijiji" in url.lower():
            source = "Kijiji"
        elif "clutch" in url.lower():
            source = "Clutch"
        elif "facebook" in url.lower():
            source = "Facebook"
        else:
            source = "Dealer"
        
        year_disp = listing.get("year") or ""
        trim_disp = listing.get("trim") or ""
        
        # Build the display title
        base_name = listing.get("vehicle", "")
        display_parts = [year_disp, base_name, trim_disp]
        display_title = " ".join(p for p in display_parts if p).strip()
        if len(display_title) < 5:
            display_title = title
        
        return f"""<tr>
<td style="padding:10px;border:1px solid #ddd;text-align:center;"><strong>#{rank}</strong></td>
<td style="padding:10px;border:1px solid #ddd;"><a href="{url}" target="_blank" style="color:#2563eb;font-weight:bold;text-decoration:none;">{display_title}</a></td>
<td style="padding:10px;border:1px solid #ddd;">{price_disp}</td>
<td style="padding:10px;border:1px solid #ddd;">{mileage_disp}</td>
<td style="padding:10px;border:1px solid #ddd;">{sunroof_disp}</td>
<td style="padding:10px;border:1px solid #ddd;">{source}</td>
</tr>"""
    
    # Generate all table rows
    if ranked:
        all_rows = [listing_row(rank, listing) for rank, listing in enumerate(ranked, start=1)]
        table_rows = "".join(all_rows)
    else:
        table_rows = f"""<tr><td colspan="6" style="padding:20px;text-align:center;color:#888;">No listings found. Use the quick links below to search manually.</td></tr>"""
    
    # Count real vs fallback listings
    real_count = sum(1 for l in ALL_LISTINGS if not l.get("is_fallback") and l.get("url") and "example.com" not in l.get("url", ""))
    
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;margin:0;padding:20px;color:#333;line-height:1.6;">
    <h2 style="color:#2563eb;margin-top:0;">Daily Vehicle Search Results</h2>
    <p style="color:#555;font-size:14px;">Generated on: {est_now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}</p>
    <p style="color:#555;font-size:13px;">{real_count} real listing(s) found. <span style="color:#999;">Click a title to open the actual listing page.</span></p>
    
    <h3 style="border-bottom:2px solid #eee;padding-bottom:5px;margin-top:30px;">Ranked Listings (Best Value First)</h3>
    <table style="width:100%;border-collapse:collapse;margin-top:10px;font-size:14px;">
        <tr style="background:#f8f9fa;">
            <th style="padding:10px;border:1px solid #ddd;text-align:center;">Rank</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Vehicle</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Price</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Mileage</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Sunroof</th>
            <th style="padding:10px;border:1px solid #ddd;text-align:left;">Source</th>
        </tr>
        {table_rows}
    </table>

    <h3 style="border-bottom:2px solid #eee;padding-bottom:5px;margin-top:40px;">Marketplace Quick Links</h3>
    <p style="font-size:13px;color:#555;">One-click searches using exact strict filters for maximum price, mileage, and models.</p>
    {buttons_html}
    
    <hr style="margin-top:30px;border:none;border-top:1px solid #eee;">
    <p style="font-size:11px;color:#aaa;text-align:center;">
        Vehicle Search Automation &mdash; Ran on {est_now.strftime('%B %d, %Y at %I:%M %p %Z')}
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
        print(f"Success: Email sent to {RECIPIENT_EMAIL}")
    except Exception as e:
        print(f"Error sending email: {e}")

# -------------------------
# Main
# -------------------------
def main():
    est_now = datetime.now(EST)
    print(f"--- Starting vehicle search at {est_now.strftime('%Y-%m-%d %H:%M:%S %Z')} ---")
    print(f"Playwright available: {PLAYWRIGHT_AVAILABLE}")
    
    if ENABLE_SCRAPE:
        scrape_and_populate_listings()
    
    email_html = generate_email_html(est_now)
    with open("gatineau_phev_rav4_search_results.html", "w", encoding="utf-8") as f:
        f.write(email_html)
    with open("dealers.html", "w", encoding="utf-8") as f:
        f.write(generate_dealers_html())
    
    send_email(
        f"Vehicle Search Update: {est_now.strftime('%b %d')} (Gatineau PHEV/RAV4)",
        email_html
    )
    print("--- Done ---")

if __name__ == "__main__":
    main()
