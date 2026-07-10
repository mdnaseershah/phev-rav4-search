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

# Dealer-probe politeness knobs (the dealer list is large, ~140 sites). Defaults are
# deliberately gentle so we don't hammer any single site or trip GitHub-Actions IP
# rate limits: requests to one host are made SEQUENTIALLY (never in parallel), only a
# handful of hosts are probed at once, and there's a short pause between a host's
# requests. All free — plain requests, no paid APIs.
DEALER_MAX_WORKERS = int(os.getenv('DEALER_MAX_WORKERS', '6'))   # hosts probed concurrently
DEALER_REQUEST_DELAY = float(os.getenv('DEALER_REQUEST_DELAY', '0.6'))  # pause between a host's requests
DEALER_MAX_SITES = int(os.getenv('DEALER_MAX_SITES', '0'))      # 0 = no cap (probe all); >0 caps for testing

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(DEFAULT_HEADERS)

DEALERS_JSON = "dealers.json"
# Large probe-only dealer list (not shown on dealers.html). Same shape as dealers.json
# ({"name", "website", optional "brand"/"province"}). Loaded by load_dealer_sites_from_file()
# and merged into the inventory-probe set. Kept separate so the curated dealers.html page
# stays small while we still scrape the full list.
DEALER_SITES_JSON = "dealer_sites.json"

# Persistent "already seen" store (committed back by the workflow). Holds the normalized
# URLs of listings shown in previous runs so each run can flag which listings are NEW.
# Missing file → treated as a baseline (nothing flagged new on the very first run).
SEEN_LISTINGS_JSON = "seen_listings.json"

# Popular dealer sites always probed for inventory (in addition to dealers.json).
# Each entry mirrors the dealers.json shape ({"name", "website"}); the name is shown
# as the listing's Source. These run on standard Canadian dealer platforms (D2C Media
# / EDealer / Convertus / Sincro) that embed schema.org JSON-LD on inventory pages, so
# _extract_jsonld_vehicles can read them with plain requests — no headless browser.
# Add more dealers here.
POPULAR_DEALER_SITES = [
    {"name": "Rallye Mitsubishi", "website": "https://www.rallyemitsubishi.ca", "province": "QC"},
]

# -------------------------
# Vehicles & Search Config
# -------------------------
WANTED_VEHICLES = [
    {
        "vehicle": "Mitsubishi Outlander PHEV",
        "make": "Mitsubishi",
        "model": "Outlander PHEV",
        "year_min": 2023,   # range is 2023–2024 (2022 dropped per user request)
        "year_max": 2024,
        # Year-specific price caps: 2023/2024 → $32.5k.
        # _get_price_cap() applies the per-year cap after each listing's year is known.
        "max_price": {2023: 32500, 2024: 32500},
        # Mileage cap is a flat 70k for every year (2023/2024).
        "max_mileage": {2023: 70000, 2024: 70000},
        "aliases": ["outlander phev", "outlander plug-in", "outlander plug in", "outlander hybrid"],
        "urls": {
            # Broad search uses the caps ($32.5k / 70k km); the per-year cap is
            # re-applied after each listing's year is known.
            "autotrader": "https://www.autotrader.ca/cars/mitsubishi/outlander/va_outlander-phev/pr_32500?offer=N%2CU&modelyearfrom=2023&modelyearto=2024&cy=CA&damaged_listing=exclude&desc=0&sort=standard&ustate=N%2CU&zip=Gatineau&zipr=100000&lat=45.47723&lon=-75.70164&atype=C&mcat=ma50gr201018va1568&size=20",  # nationwide + 2023–2024
            # Nationwide (distance=50000) using the modern makeModelTrimPaths=m46,m46/d2652 filter (Mitsubishi=m46, Outlander PHEV=d2652).
            "cargurus": "https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&zip=J8Z+3H5&distance=50000&nonShippableBaseline=75&sortDirection=ASC&sortType=DEAL_SCORE&makeModelTrimPaths=m46%2Cm46%2Fd2652&maxMileage=70000&startYear=2023&endYear=2024&maxPrice=32500",  # nationwide + 2023–2024 + makeModelTrimPaths
            "kijiji": "https://www.kijiji.ca/b-cars-trucks/canada/mitsubishi-outlander-phev/mitsubishi-outlander-2023__2024/k0c174l0a54a1000054a68?kilometers=0__70000&price=0__32500&view=list",  # 2023–2024
            "clutch": "https://www.clutch.ca/cars/mitsubishi-outlander-phev-under-32500?yearLow=2023&yearHigh=2024&mileageHigh=70000",  # 2023–2024
            "facebook": "https://www.facebook.com/marketplace/search/?query=Mitsubishi%20Outlander%20PHEV&maxPrice=32500",
            # Myers Auto Group used inventory (Dealer.com SPA — manual quick-link only, not scrapable for free).
            "myers": "https://www.myers.ca/vehicles/used/?sc=used&mk=Mitsubishi&md=Outlander&yr=2023,2024",
            # LeaseBusters lease-transfer marketplace (SCRAPED — see parse_leasebusters).
            # SUVs/Crossovers category (7) + Mitsubishi make (31), Gatineau postal.
            "leasebusters": "https://leasebusters.com/vehicle-search-result?gallery=1&categories=SUVs%20/%20Crossovers-7&makes=Mitsubishi-31&postalcode=J8Z%203H5",
            "kijiji_rss": "https://www.kijiji.ca/rss-srp-cars-trucks/canada/k0c174l0?price=0__32500&maxKilometers=70000&minYear=2023&maxYear=2024&ad=offering&vehicleType=cars",  # nationwide l0 + 2023–2024
        },
        # LeaseBusters scrape config (category = SUVs/Crossovers, make = Mitsubishi).
        # Verified working Jul 2026. See parse_leasebusters().
        "leasebusters": {"category_id": 7, "make_id": 31},
        # --- API identifiers (used by parse_*_api functions) ---
        "autotrader_model": "Outlander PHEV",  # AutoTrader taxonomy model name
        "cargurus_make": "m46",                # CarGurus make id (Mitsubishi)
        "cargurus_entity": "d2652",            # CarGurus model entity id (Outlander PHEV)
        # Known trims, most-specific first — used to build a clean Vehicle label.
        "trims": ["GT S-AWC", "GT Premium", "SE S-AWC", "LE S-AWC", "ES S-AWC",
                   "Black Edition", "GT", "SEL", "SE", "ES", "LE"],
    },
    {
        "vehicle": "Toyota RAV4 Prime",
        "make": "Toyota",
        "model": "RAV4 Prime",
        "year_min": 2023,   # range is 2023 only (2022 dropped per user request; 2024 excluded)
        "year_max": 2023,
        "max_price": 35000,
        "max_mileage": 120000,
        "aliases": ["rav4 prime", "rav 4 prime", "rav4 plug-in", "rav4 plug in", "rav4 phev", "rav4 plug-in hybrid"],
        "urls": {
            # Nationwide (no reg/city path; zipr widened to national radius). 2023
            # models are badged "RAV4 Plug-in Hybrid"; aliases cover both names.
            "autotrader": "https://www.autotrader.ca/cars/pr_35000?cat=ma70gr201439va2400%2Cma70gr201439va3942&offer=N%2CU&modelyearfrom=2023&modelyearto=2023&cy=CA&damaged_listing=exclude&desc=0&sort=standard&ustate=N%2CU&zip=Gatineau&zipr=100000&lat=45.47723&lon=-75.70164&atype=C&mcat=ma70gr201439&size=20",  # nationwide + 2023
            # Nationwide (distance=50000) using the modern makeModelTrimPaths=m7,m7/d2992 filter (Toyota=m7, RAV4 Prime=d2992).
            "cargurus": "https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&zip=J8Z+3H5&distance=50000&nonShippableBaseline=75&sortDirection=ASC&sortType=DEAL_SCORE&makeModelTrimPaths=m7%2Cm7%2Fd2992&maxMileage=120000&startYear=2023&endYear=2023&maxPrice=35000",  # nationwide + 2023 + makeModelTrimPaths
            "kijiji": "https://www.kijiji.ca/b-cars-trucks/canada/toyota-rav4/toyota-rav4-2023__2023/k0c174l0a54a1000054a68?kilometers=0__120000&price=0__35000&view=list",  # 2023
            "clutch": "https://www.clutch.ca/cars/under-40000?yearLow=2023&yearHigh=2023&models=toyota;rav4-plug-in-hybrid,toyota;rav4-prime&mileageHigh=120000",  # 2023
            "facebook": "https://www.facebook.com/marketplace/search/?query=Toyota%20RAV4%20Prime&maxPrice=35000",
            # Myers Auto Group used inventory (Dealer.com SPA — manual quick-link only, not scrapable for free).
            "myers": "https://www.myers.ca/vehicles/used/?sc=used&mk=Toyota&md=RAV4%20Prime&yr=2023,2023",
            "kijiji_rss": "https://www.kijiji.ca/rss-srp-cars-trucks/canada/k0c174l0?price=0__35000&maxKilometers=120000&minYear=2023&maxYear=2023&ad=offering&vehicleType=cars",  # nationwide l0 + 2023
        },
        # No LeaseBusters config: the Toyota make id on LeaseBusters is served by a
        # JS-only typeahead we could not verify without guessing, so RAV4 Prime is
        # intentionally not scraped there. Add {"category_id": 7, "make_id": <id>}
        # here once the id is confirmed to enable it (parse_leasebusters is generic).
        # --- API identifiers (used by parse_*_api functions) ---
        # AutoTrader lists RAV4 Prime as a *variant* of model "RAV4"; query the model
        # broadly and let alias matching keep only Prime/PHEV/plug-in results.
        "autotrader_model": "RAV4",
        "cargurus_make": "m7",                 # CarGurus make id (Toyota)
        "cargurus_entity": "d2992",            # CarGurus model entity id (RAV4 Prime)
        # Known trims, most-specific first — used to build a clean Vehicle label.
        "trims": ["XSE", "SE"],
    },
]

# -------------------------
# Global list of ALL found listings
# -------------------------
ALL_LISTINGS = []

# LeaseBusters lease-TRANSFER listings are kept SEPARATE from ALL_LISTINGS: their
# dollar figure is a monthly lease payment (not a purchase price), so mixing them
# into the value-ranked purchase tables would corrupt the ranking. They get their
# own dedicated section in the email. Populated by scrape_and_populate_listings().
LEASEBUSTERS_LISTINGS = []

# Per-source result counts for the current run (source name -> number of listings it
# contributed, summed across both vehicles). Powers the email's "source health" footer
# so a silently blocked/broken source (0 results) is visible rather than invisible.
SOURCE_COUNTS = {}

def _record_source(name, listings):
    """Add this source's contribution to SOURCE_COUNTS and return the listings unchanged."""
    try:
        SOURCE_COUNTS[name] = SOURCE_COUNTS.get(name, 0) + len(listings or [])
    except Exception:
        pass
    return listings or []

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
                if p <= _get_price_cap(vehicle_config):  # highest cap; year cap re-applied later
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
            "province": _normalize_province(title_text, desc_text, url),
            "vehicle": vehicle_name,
        })
    
    print(f"    Found {len(results)} Kijiji RSS listings")
    return results


# -------------------------
# LeaseBusters (lease-TRANSFER marketplace) — scraped server-side, free (no browser)
# -------------------------
# LeaseBusters is an ASP.NET Razor Pages site. The search grid is AJAX: a GET on the
# search page yields an antiforgery token + cookie, then each result page is a POST to
# /vehicle-search-result with the MVC-model form fields (SearchResult.*) and the token.
# Each page returns 10 rendered listing cards. The per-vehicle detail page carries a
# feature grid that lists ONLY features the car HAS, so a sunroof can be *confirmed*
# per listing (not merely inferred from trim). Verified working Jul 2026.
#
# IMPORTANT: these are lease *takeovers* — the price is a MONTHLY payment, not a
# purchase price — so they are kept out of the value-ranked purchase tables and shown
# in their own email section. Only enabled for vehicles with a "leasebusters" config.
LEASEBUSTERS_BASE = "https://leasebusters.com"
LEASEBUSTERS_POSTAL = "J8Z 3H5"   # Gatineau (distance-to-seller is computed from this)
LEASEBUSTERS_MAX_PAGES = 8        # safety cap (10 cards/page → up to 80 candidates)


def _leasebusters_detail_has_sunroof(html_text):
    """True/False/None for a LeaseBusters *detail* page's sunroof.

    The detail page renders a feature grid (`<div class="col-6 col-sm-4">Feature</div>`)
    that lists only the features the car actually has. Return True if any lists a
    sun/moon/panoramic roof, False if the grid is present but names none, None if we
    can't find a feature grid at all (so the caller can fall back to trim inference).
    """
    if not html_text:
        return None
    feats = re.findall(r'<div[^>]*class="[^"]*col-6 col-sm-4[^"]*"[^>]*>\s*([^<]+?)\s*</div>',
                       html_text, re.I)
    if not feats:
        return None
    for f in feats:
        if re.search(r'(?i)(sun ?roof|moon ?roof|panoramic)', f):
            return True
    return False


def _parse_leasebusters_cards(grid_html, vehicle_name, vehicle_config):
    """Parse rendered LeaseBusters grid cards into listing dicts (lease-transfer shape)."""
    y_min, y_max = vehicle_config["year_min"], vehicle_config["year_max"]
    aliases = [a.lower() for a in vehicle_config.get("aliases", [])]
    model_lc = vehicle_config["model"].lower()
    out = []
    soup = BeautifulSoup(grid_html, "lxml")
    for h3 in soup.select("h3.bordered-bottom"):
        title = h3.get_text(" ", strip=True)
        tl = title.lower()
        # Keep only the exact model (e.g. "Outlander PHEV"), not a plain Outlander/RVR.
        if not (model_lc in tl or any(a in tl for a in aliases)):
            continue
        ym = re.search(r"\b(20[2-3]\d)\b", title)
        if not ym:
            continue
        year = int(ym.group(1))
        if not (y_min <= year <= y_max):
            continue
        # Smallest ancestor that also contains this card's /details/ link.
        card = h3.find_parent(lambda t: t.name == "div"
                              and t.find("a", href=re.compile(r"/details/\d+")) is not None)
        if not card:
            continue
        a = card.find("a", href=re.compile(r"/details/\d+"))
        did = re.search(r"/details/(\d+)", a.get("href", ""))
        if not did:
            continue
        # Use the bare /details/<id> URL (the title-slug suffix contains an
        # unencoded space that can trip requests); this form serves the same page.
        detail_url = f"{LEASEBUSTERS_BASE}/details/{did.group(1)}"
        # Label -> value from every table row in the card (City/Distance/Odometer/
        # Colour/Months Remaining/Lease Payment/Effective Payment/Cash Incentive).
        info = {}
        for tr in card.select("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2:
                info[tds[0].get_text(" ", strip=True).rstrip(":")] = tds[-1].get_text(" ", strip=True)
        price_span = card.select_one(".price-text span") or card.select_one(".price-text")
        headline = price_span.get_text(" ", strip=True) if price_span else ""
        monthly = info.get("Effective Payment") or info.get("Lease Payment") or headline
        out.append({
            "vehicle": vehicle_name,
            "url": detail_url,
            "title": title,
            "year": str(year),
            "trim": _clean_trim(title, vehicle_config),
            "monthly": monthly or None,
            "months_remaining": info.get("Months Remaining"),
            "mileage": info.get("Odometer (kms)") or info.get("Odometer"),
            "city": info.get("City"),
            "distance": info.get("Distance To Seller"),
            "colour": info.get("Exterior Colour"),
            "sunroof": None,   # filled from the detail page below
        })
    return out


def parse_leasebusters(vehicle_name, vehicle_config):
    """Scrape LeaseBusters lease-transfer listings for one vehicle, filtered to
    the year range AND to a confirmed sunroof. Returns [] if the vehicle has no
    "leasebusters" config or on any failure (so a bad run just contributes nothing).
    """
    cfg = vehicle_config.get("leasebusters")
    if not cfg:
        return []
    print(f"  Fetching LeaseBusters (lease transfers)...")
    lb_session = requests.Session()
    lb_session.headers.update(DEFAULT_HEADERS)
    search_url = vehicle_config["urls"]["leasebusters"]
    try:
        r = lb_session.get(search_url, timeout=25)
        r.raise_for_status()
    except Exception as e:
        print(f"    LeaseBusters GET failed: {e}")
        return []
    m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r.text)
    if not m:
        print(f"    LeaseBusters: no antiforgery token found; skipping.")
        return []
    token = m.group(1)

    def _post_page(page):
        data = [
            ("SearchResult.CurrentPage", str(page)),
            ("SearchResult.SelectedCategories[0].Id", str(cfg["category_id"])),
            ("SearchResult.SelectedCategories[0].IsSelected", "true"),
            ("SearchResult.SelectedMakes[0].Id", str(cfg["make_id"])),
            ("SearchResult.SelectedMakes[0].IsSelected", "true"),
            ("SearchResult.VehicleSearchResultsEr.PostalCode", LEASEBUSTERS_POSTAL),
            ("SearchResult.VehicleSearchResultsEr.SelectedGallery", "Leasing"),
            ("SearchResult.VehicleSearchResultsEr.Top", "10"),
            ("SearchResult.VehicleSearchResultsEr.Skip", "0"),
            ("SearchResult.VehicleSearchResultsEr.MaximumDistanceToSeller", "500"),
            ("SearchResult.VehicleSearchResultsEr.OrderBy", "3"),
            ("SearchResult.VehicleSearchResultsEr.ReverseOrderBy", "False"),
        ]
        headers = {"RequestVerificationToken": token,
                   "Content-Type": "application/x-www-form-urlencoded"}
        resp = lb_session.post(LEASEBUSTERS_BASE + "/vehicle-search-result",
                               data=data, headers=headers, timeout=25)
        resp.raise_for_status()
        return resp.text

    candidates, seen_urls = [], set()
    for page in range(LEASEBUSTERS_MAX_PAGES):
        try:
            grid = _post_page(page)
        except Exception as e:
            print(f"    LeaseBusters page {page} POST failed: {e}")
            break
        if "/details/" not in grid:   # empty page → past the end
            break
        page_cards = _parse_leasebusters_cards(grid, vehicle_name, vehicle_config)
        # Also stop if this page's raw ids repeat what we've seen (no new results).
        page_ids = set(re.findall(r"/details/(\d+)", grid))
        new_ids = page_ids - seen_urls
        seen_urls |= page_ids
        for c in page_cards:
            candidates.append(c)
        if not new_ids:
            break
        time.sleep(REQUEST_DELAY)   # polite pause between page POSTs

    # De-dupe candidates by detail URL (image + title anchors can both surface a card).
    uniq = {}
    for c in candidates:
        uniq.setdefault(c["url"], c)
    candidates = list(uniq.values())
    print(f"    LeaseBusters: {len(candidates)} {vehicle_config['model']} candidate(s) in range")

    # Confirm sunroof per listing from the detail-page feature grid (fall back to
    # the trim-based map when the grid can't be read). Fetch detail pages concurrently.
    def _confirm(listing):
        html = None
        try:
            dr = lb_session.get(listing["url"], timeout=25)
            if dr.ok:
                html = dr.text
        except Exception:
            html = None
        # Two independent signals: the detail-page feature grid (authoritative when
        # readable) and the trim→sunroof map. Treat EITHER positive as a Yes, so a
        # GT/SEL (sunroof standard) isn't dropped if the seller forgot to tick it.
        grid = _leasebusters_detail_has_sunroof(html)          # True / False / None
        status = _sunroof_status(listing, vehicle_config)      # "yes" / "no" / None
        if grid is True or status == "yes":
            sun = True
        elif grid is False or status == "no":
            sun = False
        else:
            sun = None
        listing["sunroof"] = "Yes" if sun is True else ("No" if sun is False else None)
        return listing

    if candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(_confirm, candidates))

    # User criteria: "with a sunroof" → keep only confirmed-sunroof listings.
    kept = [c for c in candidates if c.get("sunroof") == "Yes"]
    print(f"    LeaseBusters: {len(kept)} with confirmed sunroof (of {len(candidates)})")
    return kept


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
# Helpers for year-specific mileage / price caps
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


def _get_price_cap(vehicle_config, year=None):
    """Get the max price for a vehicle config, optionally year-specific.

    Mirrors ``_get_mileage_cap``: ``max_price`` may be a dict (year -> cap) — e.g.
    the Outlander (2023/2024 -> $32.5k) — or a plain int. Returns the year-specific
    cap, or the highest cap when the year is None/unknown (used to build the broad
    search query before per-listing years are known).
    """
    mp = vehicle_config.get("max_price", 100000)
    if isinstance(mp, dict):
        if year is not None and int(year) in mp:
            return mp[int(year)]
        return max(mp.values()) if mp else 100000
    return mp


def _env_int(name):
    """Read an int from an env var; None if unset/blank/non-numeric (so an empty
    workflow input leaves the hardcoded default untouched)."""
    v = os.getenv(name)
    if v is None or not str(v).strip():
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _rewrite_url_caps(url, price=None, mileage=None, y_min=None, y_max=None):
    """Rewrite the common cap query params in a marketplace URL so a changed budget
    actually widens/narrows what we fetch. Only unambiguous params are touched (validated
    not to collide with distance/category digits); year slugs baked into path segments are
    left alone — the post-fetch year filter still enforces the real range either way."""
    if price is not None:
        p = str(int(price))
        for pat in (r'(pr_)\d+', r'(maxPrice=)\d+', r'(price=0__)\d+', r'(-under-)\d+'):
            url = re.sub(pat, r'\g<1>' + p, url)
    if mileage is not None:
        m = str(int(mileage))
        for pat in (r'(maxMileage=)\d+', r'(maxKilometers=)\d+', r'(kilometers=0__)\d+', r'(mileageHigh=)\d+'):
            url = re.sub(pat, r'\g<1>' + m, url)
    if y_min is not None:
        s = str(int(y_min))
        for pat in (r'(modelyearfrom=)\d+', r'(startYear=)\d+', r'(minYear=)\d+', r'(yearLow=)\d+'):
            url = re.sub(pat, r'\g<1>' + s, url)
    if y_max is not None:
        s = str(int(y_max))
        for pat in (r'(modelyearto=)\d+', r'(endYear=)\d+', r'(maxYear=)\d+', r'(yearHigh=)\d+'):
            url = re.sub(pat, r'\g<1>' + s, url)
    return url


def _apply_criteria_env_overrides():
    """Optionally override vehicle criteria from env vars (mapped from workflow_dispatch
    inputs), so budgets/years can be changed from the GitHub UI with no code edit. Any
    unset var leaves the hardcoded default. When something changes for a vehicle, the cap
    params baked into its marketplace URLs are rewritten to match. Recognized env vars:

      Outlander: OUTLANDER_YEAR_MIN, OUTLANDER_YEAR_MAX, OUTLANDER_PRICE_2022,
                 OUTLANDER_PRICE_NEWER (applies to 2023+), OUTLANDER_MILEAGE (flat)
      RAV4:      RAV4_YEAR_MIN, RAV4_YEAR_MAX, RAV4_PRICE, RAV4_MILEAGE
    """
    for w in WANTED_VEHICLES:
        dirty = False
        if (w.get("make", "").lower() == "mitsubishi"):
            ymin, ymax = _env_int("OUTLANDER_YEAR_MIN"), _env_int("OUTLANDER_YEAR_MAX")
            p2022, pnew = _env_int("OUTLANDER_PRICE_2022"), _env_int("OUTLANDER_PRICE_NEWER")
            mil = _env_int("OUTLANDER_MILEAGE")
            if ymin: w["year_min"] = ymin; dirty = True
            if ymax: w["year_max"] = ymax; dirty = True
            if p2022 or pnew:
                mp = dict(w["max_price"]) if isinstance(w.get("max_price"), dict) else {}
                if p2022:
                    mp[2022] = p2022
                if pnew:
                    for y in range(2023, w["year_max"] + 1):
                        mp[y] = pnew
                w["max_price"] = mp; dirty = True
            if mil:
                w["max_mileage"] = {y: mil for y in range(w["year_min"], w["year_max"] + 1)}
                dirty = True
        else:  # Toyota RAV4 Prime — flat caps
            ymin, ymax = _env_int("RAV4_YEAR_MIN"), _env_int("RAV4_YEAR_MAX")
            pr, mil = _env_int("RAV4_PRICE"), _env_int("RAV4_MILEAGE")
            if ymin: w["year_min"] = ymin; dirty = True
            if ymax: w["year_max"] = ymax; dirty = True
            if pr: w["max_price"] = pr; dirty = True
            if mil: w["max_mileage"] = mil; dirty = True
        if dirty:
            hp, hm = _get_price_cap(w), _get_mileage_cap(w)
            w["urls"] = {k: _rewrite_url_caps(u, price=hp, mileage=hm,
                                              y_min=w["year_min"], y_max=w["year_max"])
                         for k, u in w["urls"].items()}
            print(f"  Criteria override applied for {w['vehicle']}: "
                  f"years {w['year_min']}-{w['year_max']}, price≤{hp}, mileage≤{hm}")


# -------------------------
# Province detection (for the per-region email tables)
# -------------------------
# Full province names / French variants -> 2-letter code. Full-name matching is
# the most reliable signal (AutoTrader detail URLs and CarGurus seller regions
# use full names); a standalone 2-letter code and a postal-code prefix are
# lower-confidence fallbacks.
CANADA_PROVINCES = {
    "AB": ["alberta"],
    "BC": ["british columbia", "british-columbia", "colombie-britannique"],
    "MB": ["manitoba"],
    "NB": ["new brunswick", "new-brunswick", "nouveau-brunswick"],
    "NL": ["newfoundland and labrador", "newfoundland", "labrador", "terre-neuve"],
    "NS": ["nova scotia", "nova-scotia", "nouvelle-ecosse", "nouvelle-écosse"],
    "NT": ["northwest territories"],
    "NU": ["nunavut"],
    "ON": ["ontario"],
    "PE": ["prince edward island", "prince-edward-island", "ile-du-prince-edouard"],
    "QC": ["quebec", "québec"],
    "SK": ["saskatchewan"],
    "YT": ["yukon"],
}
# First letter of a Canadian postal code -> province.
_POSTAL_PROV = {
    "A": "NL", "B": "NS", "C": "PE", "E": "NB", "G": "QC", "H": "QC",
    "J": "QC", "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON",
    "R": "MB", "S": "SK", "T": "AB", "V": "BC", "X": "NT", "Y": "YT",
}
PROVINCE_NAMES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba",
    "NB": "New Brunswick", "NL": "Newfoundland", "NS": "Nova Scotia",
    "NT": "Northwest Territories", "NU": "Nunavut", "ON": "Ontario",
    "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan",
    "YT": "Yukon",
}


def _postal_to_province(text):
    if not text:
        return None
    m = re.search(r"\b([ABCEGHJKLMNPRSTVXY])\d[A-Za-z]\s?\d[A-Za-z]\d\b", str(text), re.I)
    if m:
        return _POSTAL_PROV.get(m.group(1).upper())
    return None


def _normalize_province(*texts):
    """Best-effort 2-letter province code from any location text, or None."""
    blob = " ".join(str(t) for t in texts if t)
    if not blob.strip():
        return None
    low = blob.lower()
    for code, names in CANADA_PROVINCES.items():
        if any(nm in low for nm in names):
            return code
    # Standalone 2-letter code, but only right after a comma/slash/paren — the
    # "Ottawa, ON" / "/ab/" shape — so we don't match "ON" inside prose.
    codes = "|".join(CANADA_PROVINCES)
    m = re.search(r"[,/(]\s*(" + codes + r")\b", blob.upper())
    if m:
        return m.group(1)
    return _postal_to_province(blob)


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
    if not keep.get("province") and drop.get("province"):
        keep["province"] = drop.get("province")  # keep a known province from the twin
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
    # Defensive: some marketplace cards render a seller-distance figure as "N km away"
    # (how far the seller is from the search location). Strip it so it can't be read as
    # the odometer — no real odometer is written that way. (AutoTrader, whose cards carry
    # only distance and no odometer at all, bypasses this entirely and reads mileage from
    # the detail page via _enrich_mileage_from_detail instead.)
    text = re.sub(r"\d[\d,]*\s*km\s*away", " ", card_text, flags=re.I)
    for m in re.findall(r"(\d{1,3}(?:,\d{3})+|\d{4,6})\s?(?:km|kms|kilometres|kilometers)\b", text, flags=re.I):
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
                    year = _extract_year(text)
                    trim = _extract_trim(text, make, model)
                    sunroof = _extract_sunroof(text)
                    title = a.get_text(" ", strip=True) or text[:100]

                    if price is not None and price > max_price: continue
                    if year:
                        try:
                            if not (year_min <= int(year) <= year_max): continue
                        except ValueError: pass

                    seen_urls.add(full)
                    results.append({
                        "url": full, "title": title, "year": year, "trim": trim,
                        "price": ("$" + format(price, ",")) if price else None,
                        # Not read from the card (that's the seller distance, not the
                        # odometer); filled from the detail page by _enrich_mileage_from_detail.
                        "mileage": None,
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
        year = _extract_year(text)

        if price is not None and price > max_price: continue
        if year:
            try:
                if not (year_min <= int(year) <= year_max): continue
            except ValueError: pass

        trim = _extract_trim(text, make, model)
        sunroof = _extract_sunroof(text)

        results.append({
            "url": full, "title": text[:100], "year": year, "trim": trim,
            "price": ("$" + format(price, ",")) if price else None,
            # Filled from the detail page by _enrich_mileage_from_detail (not the card).
            "mileage": None,
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
        # NB: we deliberately do NOT read mileage from the card. AutoTrader search
        # cards show only the seller's *distance* from the search address ("N km
        # away") — the odometer is not on the card. Reading the card gave that
        # distance as the mileage (e.g. a real 103,000 km car shown as "1,015 km").
        # Mileage is filled from the detail page later by _enrich_mileage_from_detail.
        if price is not None and price > max_price:
            continue
        seen.add(full)
        title = a.get_text(" ", strip=True) or card[:100]
        results.append({
            "url": full, "title": title, "year": year,
            "trim": _extract_trim(title, make, model),
            "price": ("$" + format(price, ",")) if price is not None else None,
            "mileage": None,  # filled from the detail page (see note above)
            "sunroof": _extract_sunroof(card),
            # AutoTrader detail hrefs embed the province, e.g. /a/mitsubishi/outlander phev/calgary/alberta/…
            "province": _normalize_province(href, card),
            "vehicle": vehicle_name,
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
    max_price = _get_price_cap(vehicle_config)  # highest cap; per-year cap re-applied later
    max_km = _get_mileage_cap(vehicle_config)  # <-- CHANGED: use highest cap
    search_url = vehicle_config["urls"]["autotrader"]

    # Warm the session first so we carry the cookies the API expects.
    try:
        session.get(search_url, timeout=25)
    except Exception as e:
        print(f"    AutoTrader warm-up failed (continuing): {e}")

    payload = {
        "Address": "Gatineau, QC",
        "Proximity": -1,   # <-- CHANGED: -1 = National (search all of Canada)
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


def _cargurus_api_params(vehicle_config):
    """Build the CarGurus searchResults query params from the configured /search URL.

    We reuse the *validated* filter URL (which carries the modern
    ``makeModelTrimPaths=<make>,<make>/<model>`` selector, zip, distance and
    sort) as the source of truth, then force our own year/price/mileage caps and
    add pagination. Falls back to composing ``makeModelTrimPaths`` from the
    ``cargurus_make`` / ``cargurus_entity`` config fields if the URL lacks it.
    """
    y_min, y_max = vehicle_config["year_min"], vehicle_config["year_max"]
    max_price = _get_price_cap(vehicle_config)  # highest cap; per-year cap re-applied later
    max_km = _get_mileage_cap(vehicle_config)  # highest cap for the search

    search_url = vehicle_config.get("urls", {}).get("cargurus", "")
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(search_url).query))

    # Ensure the modern make/model selector is present.
    if not params.get("makeModelTrimPaths"):
        mk = vehicle_config.get("cargurus_make")
        ent = vehicle_config.get("cargurus_entity")
        if mk and ent:
            params["makeModelTrimPaths"] = f"{mk},{mk}/{ent}"
        elif ent:  # legacy fallback
            params["entitySelectingHelper.selectedEntity"] = ent

    # Our config caps win over whatever the URL carried.
    params.update({
        "startYear": str(y_min),
        "endYear": str(y_max),
        "maxPrice": str(max_price),
        "maxMileage": str(max_km),
        "sortType": params.get("sortType", "DEAL_SCORE"),
        "sortDirection": params.get("sortDirection", "ASC"),
        "sourceContext": params.get("sourceContext", "carGurusHomePageModel"),
        "offset": "0",
        "maxResults": "50",
        "filtersModified": "true",
    })
    params.setdefault("zip", vehicle_config.get("cargurus_zip", "J8Z 3H5"))
    params.setdefault("distance", "50000")  # nationwide
    return params


def parse_cargurus_api(vehicle_name, vehicle_config):
    """CarGurus is NOT scraped — it's a manual quick-link in the email.

    V4.2: CarGurus sits behind **DataDome** (a commercial CAPTCHA / anti-bot
    service). Verified Jul 2026 from an ordinary residential IP — not just cloud
    IPs: the human `/search` page returns an HTTP 403 CAPTCHA challenge
    (`captcha-delivery.com`), and the `Cars/searchResults.action` JSON endpoint
    returns a literal `null`. There is no free, reliable way past it (a headless
    browser is fingerprinted and challenged too). Rather than waste each run's
    time (and hammer their CAPTCHA) we skip it and rely on the one-click CarGurus
    quick-link in the email, which works fine in the user's real browser.

    (The prior makeModelTrimPaths JSON-API implementation is preserved below but
    unreachable — remove the early return to re-enable if CarGurus ever drops the
    block, or if a paid unblocking/API service is wired in.)
    """
    print("    CarGurus: skipped (DataDome CAPTCHA — not scrapable for free; use the email quick-link)")
    return []

    make = vehicle_config["make"]
    model = vehicle_config["model"]
    y_min, y_max = vehicle_config["year_min"], vehicle_config["year_max"]
    max_price = _get_price_cap(vehicle_config)  # highest cap; per-year cap re-applied later
    max_km = _get_mileage_cap(vehicle_config)

    params = _cargurus_api_params(vehicle_config)
    if not (params.get("makeModelTrimPaths") or params.get("entitySelectingHelper.selectedEntity")):
        print("    CarGurus: no make/model selector configured, skipping API")
        return []

    search_url = vehicle_config["urls"]["cargurus"]
    # Warm the session against the human-facing search page for cookies.
    try:
        session.get(search_url, timeout=25)
    except Exception as e:
        print(f"    CarGurus warm-up failed (continuing): {e}")

    api = "https://www.cargurus.ca/Cars/searchResults.action?" + urllib.parse.urlencode(params)
    data = http_get_json(api, referer=search_url)
    if data is None:
        return []

    # Response is either a bare list or a dict wrapping the list under one of
    # several keys (the exact shape varies with CarGurus deploys).
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("listings", "tiles", "results", "searchResults", "inventoryListing"):
            if isinstance(data.get(key), list):
                items = data[key]
                break

    results = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        lid = it.get("id") or it.get("listingId") or it.get("listingIdStr")
        listing_url = it.get("listingUrl") or it.get("url")
        if listing_url:
            url = urllib.parse.urljoin("https://www.cargurus.ca", str(listing_url))
        elif lid:
            url = f"https://www.cargurus.ca/Cars/inventorylisting/vdp.action?listingId={lid}"
        else:
            continue
        if url in seen:
            continue

        price = it.get("price") or it.get("expectedPrice") or it.get("listPrice")
        if price is None:
            price = _parse_money(it.get("expectedPriceString") or it.get("priceString"))
        km = it.get("mileage")
        if km is None:
            km = _parse_km(it.get("mileageString"))
        year = it.get("carYear") or it.get("year") or it.get("modelYear")
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None

        it_make = it.get("makeName") or it.get("make") or ""
        trim = it.get("trimName") or it.get("trim") or ""
        # The makeModelTrimPaths/entity selector already restricts to the exact
        # model, so trust it and only guard against a gross make mismatch (the
        # JSON's modelName sometimes drops the "PHEV"/"Prime" qualifier, which a
        # full model-token check would wrongly reject).
        if it_make and make.lower() not in str(it_make).lower():
            continue

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

        province = _normalize_province(
            it.get("sellerRegion"), it.get("sellerState"), it.get("dealerState"),
            it.get("sellerCity"), it.get("regionName"), it.get("city"),
        ) or _postal_to_province(it.get("sellerPostalCode") or it.get("postalCode"))
        seen.add(url)
        title = " ".join(str(x) for x in [year, make, model, trim] if x)
        results.append({
            "url": url, "title": title,
            "year": str(year) if year else None, "trim": trim or None,
            "price": ("$" + format(int(float(price)), ",")) if price not in (None, "") else None,
            "mileage": ("{:,} km".format(int(float(km)))) if km not in (None, "") else None,
            "sunroof": None, "province": province, "vehicle": vehicle_name,
        })
    print(f"    CarGurus API: {len(results)} listing(s)")
    return results


def parse_clutch_api(vehicle_name, vehicle_config):
    """Clutch is NOT scraped — it's a manual quick-link in the email.

    V4.2: Clutch was rebuilt as a client-side React app served behind a WAF, so
    the old `<script id="__NEXT_DATA__">` JSON blob this used to read no longer
    exists in the page HTML. Its replacement JSON API
    (`https://api.clutch.ca/v1/vehicles/`) is impractical to scrape for free
    (verified Jul 2026):
      * the `makes` / `models` query params are ignored — it returns the full
        4,700+ car inventory regardless (so we'd have to page through ~196 pages),
      * the list response omits the selling price (price is a separate
        per-vehicle/per-location API call), and
      * the WAF throttles to empty `HTTP 202` bodies after only a couple of hits.
    So we skip it and rely on the one-click Clutch quick-link in the email.

    (The prior __NEXT_DATA__ implementation is preserved below but unreachable;
    remove the early return only if Clutch changes back to server-rendered data.)
    """
    print("    Clutch: skipped (JS app + WAF, no price in feed — not scrapable for free; use the email quick-link)")
    return []

    make = vehicle_config["make"]
    model = vehicle_config["model"]
    y_min, y_max = vehicle_config["year_min"], vehicle_config["year_max"]
    aliases = vehicle_config.get("aliases", [])
    max_price = _get_price_cap(vehicle_config)  # highest cap; per-year cap re-applied later
    max_km = _get_mileage_cap(vehicle_config)  # <-- CHANGED: use highest cap

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
        # Clutch is a centralized online retailer (delivers Canada-wide), so a
        # listing has no meaningful "seller province" — best-effort only.
        province = _normalize_province(
            obj.get("province"), obj.get("region"), obj.get("city"),
            obj.get("location"), obj.get("provinceCode"),
        )
        seen.add(url)
        results.append({
            "url": url, "title": blob_text.strip(),
            "year": str(yri) if yri else None, "trim": trim or None,
            "price": ("$" + format(int(float(price)), ",")) if price not in (None, "") else None,
            "mileage": ("{:,} km".format(int(float(km)))) if km not in (None, "") else None,
            "sunroof": None, "province": province, "vehicle": vehicle_name,
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


def load_dealer_sites_from_file():
    """Load the large probe-only dealer list (dealer_sites.json). Missing file → []."""
    if os.path.exists(DEALER_SITES_JSON):
        try:
            with open(DEALER_SITES_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("website")]
        except Exception as e:
            print(f"Failed to load {DEALER_SITES_JSON}: {e}")
    return []


def _has_vehicle_jsonld(html_text):
    """True if the page carries schema.org Car/Vehicle JSON-LD — i.e. a real dealer
    inventory page rendered. Used to short-circuit probing: if a model-filtered
    inventory page renders but contains none of our model, the filter applied and
    returned nothing, so there's no point trying more path variants on that host."""
    if not html_text:
        return False
    return bool(re.search(r'"@type"\s*:\s*"(?:Car|Vehicle)"', html_text))


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


# Common car makes — used to reject a dealer link whose URL slug names a make
# OTHER than the one we're searching for (see _url_names_other_make).
_KNOWN_CAR_MAKES = (
    "toyota", "honda", "mitsubishi", "mazda", "nissan", "hyundai", "kia",
    "ford", "chevrolet", "chevy", "gmc", "ram", "dodge", "jeep", "chrysler",
    "subaru", "volkswagen", "audi", "bmw", "mercedes", "lexus", "acura",
    "infiniti", "volvo", "porsche", "buick", "cadillac", "lincoln", "genesis",
    "mini", "jaguar", "tesla", "fiat", "suzuki", "land-rover", "range-rover",
)


def _url_names_other_make(href: str, make: str) -> bool:
    """True if the link's URL *slug* names a car make different from `make`.

    Dealer generic/category pages carry the make right in the path
    (e.g. /used/2024-Toyota-RAV4.html, /used/RAM-2500.html). When we're
    searching Mitsubishi, such a link points at the wrong car, so reject it.
    Only the final path segment (the slug) is inspected — never the domain,
    because a Honda/Toyota dealer legitimately lists trade-ins of other makes.
    """
    if not href:
        return False
    mk = (make or "").lower()
    slug = href.lower().split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1]
    for other in _KNOWN_CAR_MAKES:
        if other == mk:
            continue
        # Make token delimited by slug separators (-, _, ., start/end).
        if re.search(r"(?:^|[\W_])" + re.escape(other) + r"(?:$|[\W_])", slug):
            return True
    return False


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

        # Province from any schema.org PostalAddress (on the Vehicle, its Offer,
        # or the seller); falls back to a postal-code prefix.
        def _addr_bits(o):
            bits = []
            if isinstance(o, dict):
                a = o.get("address")
                if isinstance(a, dict):
                    bits += [a.get("addressRegion"), a.get("addressLocality"), a.get("postalCode")]
                elif isinstance(a, str):
                    bits.append(a)
            return [b for b in bits if b]
        addr_texts = (_addr_bits(obj) + _addr_bits(offers)
                      + _addr_bits(offers.get("seller")) + _addr_bits(obj.get("seller")))
        province = _normalize_province(*addr_texts) or _postal_to_province(" ".join(addr_texts))

        seen.add(url)
        results.append({
            "url": url, "title": name or blob.strip(), "year": year, "trim": trim,
            "price": ("$" + format(int(price), ",")) if price is not None else None,
            "mileage": ("{:,} km".format(int(km))) if km is not None else None,
            "sunroof": _extract_sunroof(f"{name} {desc}"),
            "desc": desc, "province": province, "vehicle": vehicle_name,
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
        r'name=[\"\']' + name_alt + r'[\"\'][^>]*?value=[\"\']\s*([\d.,]+)\s*[\"\']',
        r'value=[\"\']\s*([\d.,]+)\s*[\"\'][^>]*?name=[\"\']' + name_alt + r'[\"\']',
    ):
        m = re.search(pat, html_text, re.I)
        if m:
            km = _parse_km(m.group(1))
            if km:
                return int(km)
    # AutoTrader detail pages expose the odometer as clean JSON (the search *card*
    # only carries the seller's distance, never the odometer — see _find_mileage),
    # so AutoTrader listings are always enriched from here. Several equivalent keys:
    #   "mileageFromOdometer":{...,"value":103000,...}
    #   "mileageInKmRaw":103000        "stmil":"103000"        "classified_mileage":103000
    for pat in (
        r'"mileageFromOdometer"\s*:\s*\{[^}]*?"value"\s*:\s*([\d.,]+)',
        r'"mileageInKmRaw"\s*:\s*([\d.,]+)',
        r'\\?"stmil\\?"\s*:\s*\\?"([\d.,]+)',
        r'"classified_mileage"\s*:\s*([\d.,]+)',
    ):
        m = re.search(pat, html_text, re.I)
        if m:
            km = _parse_km(m.group(1))
            if km:
                return int(km)
    return None


def _enrich_mileage_from_detail(listings):
    """Fill in missing mileage by fetching each listing's detail page.

    Two sources need this: dealer inventory pages carry the JSON-LD listing but
    not the odometer, and AutoTrader search cards carry only the seller's
    distance ("N km away"), never the odometer — so both leave `mileage` unset
    and rely on this pass. For any listing still lacking mileage we fetch its
    detail URL and parse the odometer via `_extract_odometer`. Runs concurrently.
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
        # Match make + model against the LINK'S OWN TEXT only — never the wider
        # `card` blob. Dealer search pages echo the requested make/model back in
        # filter chips / breadcrumbs / headings; a greedy ancestor blob then
        # "matches" every unrelated car on the page (a Toyota RAV4 or RAM 2500
        # link was being tagged as our Mitsubishi Outlander PHEV). The anchor's
        # own text names the actual car, so match on that. `card` is used only
        # to read price/mileage/sunroof below.
        if not _matches_model(text, make, token_groups):
            continue
        # Defense in depth: reject a link whose URL slug names a different make.
        if _url_names_other_make(href, make):
            continue
        year = _extract_year(text)
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
            "sunroof": _extract_sunroof(card),
            "province": _normalize_province(card, base_url), "vehicle": vehicle_name,
        })
    return results


def _dealer_probe_paths(make, model):
    """Ordered inventory paths to try on ONE dealer host, most-productive first.

    Model-filtered used-inventory URLs come first (they return ALL matching units,
    not just page 1) in both English and French (many sites are Quebec dealers), then
    a couple of bare index pages as a last resort. We stop at the first path that
    yields a match, so most hosts cost only 1–2 requests. Covers the common Canadian
    dealer platforms (D2C Media / EDealer / Convertus / Sincro / DealerInspire)."""
    mk = urllib.parse.quote_plus(make)
    md = urllib.parse.quote_plus(model)
    # Validated against real dealers (Jul 2026): `/inventory?make=&model=` is the single
    # most productive path (D2C Media, e.g. Rallye Mitsubishi, and the platform Kanata
    # Toyota runs); `/en/used-inventory` and `/occasion` cover the EN/FR index variants.
    # New units returned by /inventory are harmless — they're filtered out by the price
    # cap. Paths that 404'd everywhere (/used-inventory?…, /fr/vehicules-doccasion?…,
    # /en/pre-owned?… — Rallye's old scheme, now dead) were dropped to save requests.
    # Sites that are pure client-side SPAs expose no JSON-LD and won't yield via requests.
    return [
        f"/inventory?make={mk}&model={md}",        # model-filtered (most productive)
        f"/en/used-inventory?make={mk}&model={md}",  # D2C English used, model-filtered
        f"/occasion?make={mk}&model={md}",          # Quebec French used, model-filtered
        "/en/used-inventory",                        # bare EN index (safety net)
        "/occasion",                                 # bare FR index (safety net)
    ]


def _probe_one_dealer(base, make, model, aliases, vehicle_name, y_min, y_max, max_price, max_km):
    """Probe a single dealer host SEQUENTIALLY (polite: never parallel to one host).

    Tries each path in order with a short pause between requests, stopping as soon as
    we find a matching listing — or as soon as a filtered inventory page renders with
    JSON-LD but no match (the filter applied and returned nothing, so trying more path
    variants is pointless). Returns matching listings for this host (deduped by URL)."""
    found, seen = [], set()
    paths = _dealer_probe_paths(make, model)
    for i, path in enumerate(paths):
        html = http_get(base + path)
        if html:
            for lst in find_dealer_listings(html, base, make, model, aliases,
                                            vehicle_name, y_min, y_max, max_price, max_km):
                if lst["url"] not in seen:
                    seen.add(lst["url"])
                    found.append(lst)
            if found:
                break  # got our car(s); no need to try other path variants on this host
            # A model-filtered path (carries ?make=&model=) that rendered real inventory
            # JSON-LD but matched nothing means the filter worked → stop probing this host.
            if "?" in path and _has_vehicle_jsonld(html):
                break
        if i < len(paths) - 1:
            time.sleep(DEALER_REQUEST_DELAY)
    return found


# -------------------------
# Main Scrape Orchestration
# -------------------------
def scrape_and_populate_listings():
    global ALL_LISTINGS, SOURCE_COUNTS, LEASEBUSTERS_LISTINGS
    ALL_LISTINGS = []
    LEASEBUSTERS_LISTINGS = []
    # Pre-seed every source at 0 so one that errors before returning still shows "0"
    # in the email footer (0 = blocked/failed this run, not "not attempted").
    SOURCE_COUNTS = {"Kijiji": 0, "AutoTrader": 0, "CarGurus": 0, "Clutch": 0,
                     "Dealers": 0, "LeaseBusters": 0}

    # Map each dealer website -> display name (Source) and -> province (used as a
    # fallback region when a dealer listing carries no address of its own).
    dealer_name_by_site = {}
    dealer_province_by_site = {}
    # dealers.json + POPULAR_DEALER_SITES (curated, also shown on dealers.html) PLUS the
    # large probe-only list (dealer_sites.json). Deduped by website via setdefault.
    for d in [*load_dealers_from_file(), *POPULAR_DEALER_SITES, *load_dealer_sites_from_file()]:
        w = d.get("website")
        if w:
            dealer_name_by_site.setdefault(w, d.get("name") or _dealer_name_from_site(w))
            prov = d.get("province") or _normalize_province(d.get("city"), d.get("region"))
            if prov:
                dealer_province_by_site.setdefault(w, prov)
    dealer_sites = list(dealer_name_by_site)
    if DEALER_MAX_SITES > 0:
        dealer_sites = dealer_sites[:DEALER_MAX_SITES]  # optional cap (testing)
    
    for wanted in WANTED_VEHICLES:
        vehicle_name = wanted["vehicle"]
        make = wanted["make"]
        model = wanted["model"]
        y_min, y_max = wanted["year_min"], wanted["year_max"]
        max_price = _get_price_cap(wanted)  # highest cap; per-year cap re-applied after dedup
        max_km = _get_mileage_cap(wanted)  # highest cap for the broad search
        aliases = wanted.get("aliases", [])
        urls = wanted["urls"]
        
        print(f"\n{'='*60}")
        print(f"Searching: {vehicle_name}")
        print(f"{'='*60}")
        vehicle_listings = []
        
        # ---- 1. Kijiji RSS (most reliable) ----
        try:
            rss_results = parse_kijiji_rss(vehicle_name, wanted)
            vehicle_listings.extend(_record_source("Kijiji", rss_results))
        except Exception as e:
            print(f"    Kijiji RSS error: {e}")
        
        # ---- 2. AutoTrader (internal search API) ----
        print(f"\n  --- AutoTrader ---")
        try:
            at_listings = parse_autotrader_api(vehicle_name, wanted)
            # Fallback: if the API yields nothing, try headless rendering.
            if not at_listings and PLAYWRIGHT_AVAILABLE:
                print(f"    AutoTrader API empty; trying Playwright fallback...")
                at_html = fetch_rendered_html(urls["autotrader"])
                if at_html:
                    fb = parse_autotrader_listings(at_html, make, model, y_min, y_max, aliases, vehicle_name, max_price, max_km)
                    print(f"    AutoTrader Playwright fallback: {len(fb)} listing(s)")
                    at_listings.extend(fb)
            # AutoTrader cards carry only the seller's distance, not the odometer, so
            # each listing's mileage was left unset — fill it from the detail page.
            # (The per-year cap is then enforced by the post-dedup _within_caps filter.)
            _enrich_mileage_from_detail(at_listings)
            vehicle_listings.extend(_record_source("AutoTrader", at_listings))
        except Exception as e:
            print(f"    AutoTrader error: {e}")

        # ---- 3. CarGurus (internal search API) ----
        print(f"\n  --- CarGurus ---")
        try:
            vehicle_listings.extend(_record_source("CarGurus", parse_cargurus_api(vehicle_name, wanted)))
        except Exception as e:
            print(f"    CarGurus error: {e}")

        # ---- 4. Kijiji Web (requests fallback) ----
        print(f"\n  --- Kijiji Web ---")
        kj_html = http_get(urls["kijiji"])
        if kj_html:
            kj_listings = parse_kijiji_listings(kj_html, make, model, y_min, y_max, aliases, vehicle_name, max_price, max_km)
            print(f"    Kijiji Web result: {len(kj_listings)} listing(s)")
            vehicle_listings.extend(_record_source("Kijiji", kj_listings))

        # ---- 5. Clutch.ca (__NEXT_DATA__ JSON, no browser needed) ----
        print(f"\n  --- Clutch.ca ---")
        try:
            vehicle_listings.extend(_record_source("Clutch", parse_clutch_api(vehicle_name, wanted)))
        except Exception as e:
            print(f"    Clutch error: {e}")

        # ---- 6. Local dealer probing ----
        # Politeness-first for the large list: one worker per HOST (each host is probed
        # sequentially by _probe_one_dealer, never with parallel requests), only
        # DEALER_MAX_WORKERS hosts at a time, and a short pause between a host's requests.
        # Each host stops at the first path that yields a match, so most cost 1–2 fetches.
        print(f"\n  --- Local Dealers ({len(dealer_sites)} sites) ---")
        dealer_found = []
        seen_dealer_urls = set()
        if dealer_sites:
            def _probe(site):
                base = site.rstrip("/")
                try:
                    return site, _probe_one_dealer(base, make, model, aliases, vehicle_name,
                                                   y_min, y_max, max_price, max_km)
                except Exception as e:
                    print(f"    dealer probe error ({site}): {e}")
                    return site, []
            with concurrent.futures.ThreadPoolExecutor(max_workers=DEALER_MAX_WORKERS) as executor:
                for site_label, listings in executor.map(_probe, dealer_sites):
                    for lst in listings:
                        if lst["url"] not in seen_dealer_urls:
                            seen_dealer_urls.add(lst["url"])
                            lst["source"] = (dealer_name_by_site.get(site_label)
                                             or _dealer_name_from_site(site_label))
                            # Fall back to the dealer's known province if the
                            # listing didn't carry an address of its own.
                            if not lst.get("province"):
                                lst["province"] = dealer_province_by_site.get(site_label)
                            dealer_found.append(lst)

        if dealer_found:
            # Collapse the same car found under multiple probe-path URLs BEFORE
            # enrichment so each detail page is fetched once, not per path.
            dealer_found = _dedup_listings(dealer_found, wanted)
            # Dealer inventory pages omit the odometer — fetch each detail page
            # to fill in mileage, then drop anything now shown to be over the cap.
            _enrich_mileage_from_detail(dealer_found)
            dealer_found = [l for l in dealer_found
                            if not ((_parse_km(l.get("mileage")) or 0) > _get_mileage_cap(wanted, int(l.get("year")) if l.get("year") else None))]
            print(f"    Found {len(dealer_found)} real listing(s) on dealer sites")
            vehicle_listings.extend(_record_source("Dealers", dealer_found))

        # ---- 7. LeaseBusters (lease TRANSFERS — kept separate from the purchase
        #        tables because the price is a monthly payment, not a buy price) ----
        print(f"\n  --- LeaseBusters ---")
        try:
            lb_results = parse_leasebusters(vehicle_name, wanted)
            if lb_results:
                LEASEBUSTERS_LISTINGS.extend(lb_results)
                SOURCE_COUNTS["LeaseBusters"] = SOURCE_COUNTS.get("LeaseBusters", 0) + len(lb_results)
        except Exception as e:
            print(f"    LeaseBusters error: {e}")

        # ---- Deduplicate (same car across probe paths + marketplaces) ----
        unique = _dedup_listings(vehicle_listings, wanted)

        # Post-dedup filters: drop anything over its year-specific mileage OR
        # price cap. This second pass catches listings fetched via the broad
        # (highest-cap) query whose year wasn't known at parse time, and enforces
        # each vehicle's per-year caps (Outlander flat $32.5k / 70k across 2023–2024).
        def _within_caps(l):
            yr = int(l.get("year")) if str(l.get("year") or "").isdigit() else None
            km = _parse_km(l.get("mileage"))
            pr = _parse_money(l.get("price"))
            if km is not None and km > _get_mileage_cap(wanted, yr):
                return False
            if pr is not None and pr > _get_price_cap(wanted, yr):
                return False
            return True
        unique = [l for l in unique if _within_caps(l)]

        if unique:
            print(f"\n  ✅ Total unique listings for {vehicle_name}: {len(unique)}")
            ALL_LISTINGS.extend(unique)
        else:
            print(f"\n  ⚠ No listings found for {vehicle_name}. Using fallback search link.")
            ALL_LISTINGS.append({
                "url": urls["autotrader"], "title": f"{vehicle_name} (Click to search)",
                "year": None, "trim": None, "price": None,
                "mileage": None, "sunroof": None, "province": None,
                "vehicle": vehicle_name, "is_fallback": True,
            })
    
    print(f"\n{'='*60}")
    print(f"Total listings across all vehicles: {len(ALL_LISTINGS)}")
    print(f"{'='*60}")


# -------------------------
# New-vs-seen tracking (persisted across runs in seen_listings.json)
# -------------------------
def _load_seen_urls():
    """Return the set of previously-seen normalized URLs, or None if there's no store
    yet (first run — used to establish a baseline without flagging everything new)."""
    if os.path.exists(SEEN_LISTINGS_JSON):
        try:
            with open(SEEN_LISTINGS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("urls"), list):
                return set(data["urls"])
            if isinstance(data, list):
                return set(data)
        except Exception as e:
            print(f"Failed to load {SEEN_LISTINGS_JSON}: {e}")
    return None


def _save_seen_urls(urls):
    try:
        with open(SEEN_LISTINGS_JSON, "w", encoding="utf-8") as f:
            json.dump({"urls": sorted(urls)}, f, indent=1)
    except Exception as e:
        print(f"Failed to write {SEEN_LISTINGS_JSON}: {e}")


def mark_new_and_update_seen():
    """Flag each real listing with ``is_new`` (True if its URL wasn't seen in a prior
    run), then persist the updated seen-set. Returns the count of new listings.

    First run (no store) is a BASELINE: nothing is flagged new (so the first email
    isn't a wall of 🆕), but every current URL is recorded so the *next* run can tell
    what changed. The store is the union of all URLs ever seen, so a car is flagged new
    only once; the matching-listing universe is small, so the file stays tiny."""
    real = [l for l in ALL_LISTINGS if not l.get("is_fallback") and l.get("url")]
    current = {_norm_url(l["url"]) for l in real}
    seen = _load_seen_urls()
    if seen is None:
        for l in real:
            l["is_new"] = False
        _save_seen_urls(current)
        print("Seen-store baseline established (first run — nothing flagged new).")
        return 0
    new_count = 0
    for l in real:
        l["is_new"] = _norm_url(l["url"]) not in seen
        if l["is_new"]:
            new_count += 1
    _save_seen_urls(seen | current)
    print(f"New listings since last run: {new_count}")
    return new_count


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
    ("Backup Cam", r"(?i)\b(back(-| )?up cam|rear(view)? cam|reverse cam)\w*\b"),
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


def _fmt_cap(cap, suffix=""):
    """Format a price/mileage cap (plain int OR year->cap dict) as a short label,
    e.g. 32500 -> '$32,500' / '70,000 km'; a mixed dict -> a low–high range."""
    vals = sorted(set(cap.values())) if isinstance(cap, dict) else [cap]
    pre = "$" if not suffix else ""
    if len(vals) == 1:
        return f"{pre}{vals[0]:,}{suffix}"
    return f"{pre}{vals[0]:,}{suffix} – {pre}{vals[-1]:,}{suffix}"


def _criteria_summary_html():
    """A compact 'Search Criteria' box built from WANTED_VEHICLES so it always
    matches what's actually being searched (no hardcoded numbers to drift)."""
    td = "padding:7px 12px;border-bottom:1px solid #eef2f7;font-size:13px;color:#334155;"
    th = ("padding:7px 12px;border-bottom:2px solid #e2e8f0;text-align:left;font-size:11px;"
          "letter-spacing:.04em;text-transform:uppercase;color:#64748b;font-weight:700;white-space:nowrap;")
    rows = ""
    for i, w in enumerate(WANTED_VEHICLES):
        yrs = str(w["year_min"]) if w["year_min"] == w["year_max"] else f"{w['year_min']}–{w['year_max']}"
        bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
        rows += (f'<tr>'
                 f'<td style="{td}background:{bg};font-weight:600;color:#0f172a;">{w["vehicle"]}</td>'
                 f'<td style="{td}background:{bg};white-space:nowrap;">{yrs}</td>'
                 f'<td style="{td}background:{bg};white-space:nowrap;">up to {_fmt_cap(w["max_price"])}</td>'
                 f'<td style="{td}background:{bg};white-space:nowrap;">up to {_fmt_cap(w["max_mileage"], " km")}</td>'
                 f'</tr>')
    return f"""
    <h3 style="margin-top:26px;margin-bottom:6px;color:#111;">Search Criteria</h3>
    <div style="overflow-x:auto;border:1px solid #e5e7eb;border-radius:10px;">
    <table style="width:100%;min-width:480px;border-collapse:collapse;">
        <thead><tr style="background:#f1f5f9;">
            <th style="{th}">Vehicle</th><th style="{th}">Model Years</th>
            <th style="{th}">Max Price</th><th style="{th}">Max Mileage</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>
    </div>
    <p style="font-size:12px;color:#64748b;margin-top:6px;">
        Searched <strong>nationwide (Canada-wide)</strong>. A sunroof is a ranking
        bonus (not required) for purchase listings. The
        <strong>LeaseBusters</strong> section below is separate: it lists
        <strong>lease takeovers</strong> (monthly payments, not purchase prices),
        filtered to <strong>2023–2024 with a confirmed sunroof</strong>.
    </p>"""


def _leasebusters_section_html():
    """Dedicated section for LeaseBusters lease-transfer listings (monthly payments),
    kept out of the value-ranked purchase tables. Sorted cheapest monthly first."""
    em = "—"
    listings = sorted(LEASEBUSTERS_LISTINGS,
                      key=lambda l: (_parse_money(l.get("monthly")) or 1e9))
    th = ("padding:10px 12px;border-bottom:2px solid #e2e8f0;text-align:left;font-size:11px;"
          "letter-spacing:.04em;text-transform:uppercase;color:#64748b;font-weight:700;white-space:nowrap;")
    def _row(i, l):
        bg = "#ffffff" if i % 2 == 1 else "#f8fafc"
        td = f"padding:10px 12px;border-bottom:1px solid #eef2f7;vertical-align:top;background:{bg};"
        td_nw = td + "white-space:nowrap;"
        w = next((v for v in WANTED_VEHICLES if v["vehicle"] == l.get("vehicle")), None)
        label = _vehicle_label(l, w)
        loc = ", ".join(p for p in [l.get("city"), l.get("distance")] if p) or em
        monthly = l.get("monthly") or em
        if monthly != em and not str(monthly).strip().startswith("$"):
            monthly = "$" + str(monthly)
        return (f'<tr>'
                f'<td style="{td_nw}text-align:center;color:#94a3b8;font-weight:700;">{i}</td>'
                f'<td style="{td}word-break:break-word;"><a href="{l.get("url","#")}" target="_blank" '
                f'style="color:#2563eb;font-weight:600;text-decoration:none;">{label}</a></td>'
                f'<td style="{td_nw}font-weight:700;color:#0f172a;">{monthly}<span style="color:#94a3b8;font-weight:400;">/mo</span></td>'
                f'<td style="{td_nw}color:#475569;">{l.get("mileage") or em}</td>'
                f'<td style="{td_nw}color:#475569;">{l.get("months_remaining") or em}</td>'
                f'<td style="{td}color:#64748b;font-size:13px;">{loc}</td>'
                f'<td style="{td_nw}color:#0a7d2c;font-weight:600;">{l.get("sunroof") or em}</td>'
                f'</tr>')
    if listings:
        body = "".join(_row(i, l) for i, l in enumerate(listings, start=1))
    else:
        body = ('<tr><td colspan="7" style="padding:18px;text-align:center;color:#94a3b8;font-size:13px;">'
                'No lease-transfer matches with a confirmed sunroof this run '
                '&mdash; use the LeaseBusters quick link below.</td></tr>')
    count = len(listings)
    plural = "s" if count != 1 else ""
    return f"""
    <h2 style="margin-top:34px;margin-bottom:0;color:#111;border-bottom:3px solid #16a34a;padding-bottom:6px;">
        LeaseBusters &mdash; Lease Takeovers <span style="font-weight:normal;color:#999;font-size:14px;">({count} match{plural})</span></h2>
    <p style="color:#64748b;font-size:12px;margin-top:6px;margin-bottom:0;">
        These are <strong>lease transfers</strong>, not cars for sale: the price is a
        <strong>monthly payment</strong> and you take over the remaining term/kilometre
        allowance. Filtered to <strong>2023–2024 {WANTED_VEHICLES[0]['model']} with a confirmed sunroof</strong>,
        cheapest monthly first.</p>
    <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;margin-top:10px;border:1px solid #e5e7eb;border-radius:10px;">
    <table style="width:100%;min-width:640px;border-collapse:collapse;font-size:14px;">
        <thead><tr style="background:#f1f5f9;">
            <th style="{th}text-align:center;">#</th><th style="{th}width:32%;">Vehicle</th>
            <th style="{th}">Monthly</th><th style="{th}">Odometer</th>
            <th style="{th}">Months Left</th><th style="{th}">Location</th>
            <th style="{th}">Sunroof</th>
        </tr></thead>
        <tbody>{body}</tbody>
    </table>
    </div>"""


def generate_email_html(est_now):
    # Marketplace quick links
    buttons_html = ""
    for wanted in WANTED_VEHICLES:
        urls = wanted["urls"]
        btn = "display:inline-block;margin:4px 6px 4px 0;padding:8px 14px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;font-size:13px;"
        # LeaseBusters is only present for vehicles we can search there (Outlander).
        lb_button = (f'<a href="{urls["leasebusters"]}" target="_blank" style="{btn}">LeaseBusters (lease takeover)</a>'
                     if urls.get("leasebusters") else "")
        buttons_html += f"""
        <div style="margin-top: 14px; margin-bottom: 6px;"><strong>{wanted['vehicle']} ({wanted['year_min']}-{wanted['year_max']}):</strong></div>
        <a href="{urls['autotrader']}" target="_blank" style="{btn}">AutoTrader.ca</a>
        <a href="{urls['cargurus']}" target="_blank" style="{btn}">CarGurus.ca</a>
        <a href="{urls['kijiji']}" target="_blank" style="{btn}">Kijiji</a>
        <a href="{urls['clutch']}" target="_blank" style="{btn}">Clutch.ca</a>
        <a href="{urls['facebook']}" target="_blank" style="{btn}">Facebook</a>
        <a href="{urls['myers']}" target="_blank" style="{btn}">Myers Auto Group</a>
        {lb_button}
        """
    
    ranked = sorted(ALL_LISTINGS, key=_listing_value_score)
    em_dash = "\u2014"

    def _province_display(listing):
        return listing.get("province") or em_dash

    def listing_row(rank, listing, show_province=False):
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
        # A "NEW" pill for listings not seen in a prior run (see mark_new_and_update_seen).
        new_badge = ('<span style="display:inline-block;margin-right:6px;padding:1px 6px;'
                     'background:#16a34a;color:#fff;border-radius:4px;font-size:11px;'
                     'font-weight:700;vertical-align:middle;">NEW</span>') if listing.get("is_new") else ""
        # Description column: short feature summary incl. trim-aware sunroof.
        desc_disp = _short_description(listing, w) or em_dash

        # Zebra striping for a clean, professional look (odd rows white, even tinted).
        bg = "#ffffff" if rank % 2 == 1 else "#f8fafc"
        td = f"padding:10px 12px;border-bottom:1px solid #eef2f7;vertical-align:top;background:{bg};"
        td_nw = td + "white-space:nowrap;"
        prov_cell = (f'<td style="{td_nw}color:#475569;font-weight:600;">{_province_display(listing)}</td>'
                     if show_province else "")
        return f"""<tr>
<td style="{td_nw}text-align:center;color:#94a3b8;font-weight:700;">{rank}</td>
<td style="{td}word-break:break-word;">{new_badge}<a href="{url}" target="_blank" style="color:#2563eb;font-weight:600;text-decoration:none;">{vehicle_disp}</a></td>
<td style="{td_nw}font-weight:700;color:#0f172a;">{price_disp}</td>
<td style="{td_nw}color:#475569;">{mileage_disp}</td>
{prov_cell}<td style="{td}color:#64748b;font-size:13px;word-break:break-word;">{desc_disp}</td>
<td style="{td_nw}color:#64748b;font-size:13px;">{source}</td>
</tr>"""

    _th = ("padding:10px 12px;border-bottom:2px solid #e2e8f0;text-align:left;"
           "font-size:11px;letter-spacing:.04em;text-transform:uppercase;"
           "color:#64748b;font-weight:700;white-space:nowrap;")

    def _thead(show_province):
        prov_th = f'<th style="{_th}">Prov.</th>' if show_province else ""
        # Only the Vehicle column carries a width hint, so the table's slack goes
        # there (it's the primary column); every other column — Description
        # included — sizes to its own content instead of absorbing leftover space.
        return ('<thead><tr style="background:#f1f5f9;">'
                f'<th style="{_th}text-align:center;">#</th>'
                f'<th style="{_th}width:34%;">Vehicle</th><th style="{_th}">Price</th>'
                f'<th style="{_th}">Mileage</th>{prov_th}'
                f'<th style="{_th}">Description</th>'
                f'<th style="{_th}">Source</th></tr></thead>')

    def _render_table(listings, show_province=False):
        ncols = 7 if show_province else 6
        # Push listings with no detectable province to the bottom. The list is
        # already value-sorted and Python's sort is stable, so this preserves the
        # value ranking within the known-province and unknown-province groups.
        listings = sorted(listings, key=lambda l: 0 if l.get("province") else 1)
        if listings:
            body = "".join(listing_row(i, lst, show_province)
                           for i, lst in enumerate(listings, start=1))
        else:
            body = (f'<tr><td colspan="{ncols}" style="padding:18px;text-align:center;color:#94a3b8;font-size:13px;">'
                    'No listings in this table — use the quick links below.</td></tr>')
        # Auto table layout (no table-layout:fixed): each column sizes to its
        # content, so the Description column is only as wide as its (short) text
        # instead of stretching to fill the row. A horizontal-scroll wrapper with
        # rounded borders keeps it tidy and professional on narrow screens.
        min_w = 600 if show_province else 540
        return f"""
    <div style="overflow-x:auto;-webkit-overflow-scrolling:touch;margin-top:10px;border:1px solid #e5e7eb;border-radius:10px;">
    <table style="width:100%;min-width:{min_w}px;border-collapse:collapse;font-size:14px;">
        {_thead(show_province)}
        <tbody>{body}</tbody>
    </table>
    </div>"""

    def _table_heading(title, listings, note=""):
        count = sum(1 for l in listings if not l.get("is_fallback"))
        plural = "s" if count != 1 else ""
        note_html = (f' <span style="font-weight:normal;color:#0a7d2c;font-size:12px;">{note}</span>'
                     if note else "")
        return (f'<h4 style="margin-top:22px;margin-bottom:0;color:#333;">{title} '
                f'<span style="font-weight:normal;color:#999;font-size:13px;">({count} listing{plural})</span>{note_html}</h4>')

    def _box_heading(title):
        return (f'<h2 style="margin-top:34px;margin-bottom:0;color:#111;'
                f'border-bottom:3px solid #2563eb;padding-bottom:6px;">{title}</h2>')

    parts = []

    # ----- Model years 2023–2024, split by province region -----
    # (Includes both the Outlander PHEV and the RAV4 Prime / RAV4 Plug-in Hybrid.)
    # The searches already enforce the 2023–2024 range, so every ranked listing
    # belongs here (listings whose year couldn't be parsed are kept too — nothing
    # is dropped). Alberta gets its own table (5% GST → cheapest); everything else
    # — Ontario, Quebec, other provinces, and unknown — is one table with a
    # Province column.
    ab = [l for l in ranked if l.get("province") == "AB"]
    rest = [l for l in ranked if l.get("province") != "AB"]
    parts.append(_box_heading("Model Years 2023–2024"))
    parts.append(_table_heading("Alberta", ab, note="5% GST — usually the lowest total cost"))
    parts.append(_render_table(ab, show_province=False))
    parts.append(_table_heading("Ontario, Quebec &amp; Other", rest))
    parts.append(_render_table(rest, show_province=True))

    sections_html = "".join(parts)

    real_count = sum(1 for l in ALL_LISTINGS if not l.get("is_fallback") and l.get("url") and "example.com" not in l.get("url", ""))
    new_count = sum(1 for l in ALL_LISTINGS if l.get("is_new"))

    # "New since last run" banner (only when scraping ran and something is new).
    new_banner = ""
    if new_count:
        new_banner = (f'<div style="margin:14px 0;padding:10px 14px;background:#ecfdf5;'
                      f'border:1px solid #a7f3d0;border-radius:8px;color:#065f46;font-size:14px;">'
                      f'<strong>{new_count} new listing(s)</strong> since the last run '
                      f'(marked <span style="display:inline-block;padding:1px 6px;background:#16a34a;'
                      f'color:#fff;border-radius:4px;font-size:11px;font-weight:700;">NEW</span> below).</div>')

    # Source-health footer: which sources actually returned data this run. A source at 0
    # usually means it was rate-limited / anti-bot-challenged, not that nothing exists.
    if SOURCE_COUNTS:
        order = ["Kijiji", "AutoTrader", "Dealers", "LeaseBusters", "CarGurus", "Clutch"]
        # CarGurus (DataDome CAPTCHA) and Clutch (JS app + WAF, no price in feed)
        # can't be scraped for free — they're manual quick-links, not failures, so
        # show them greyed as "(manual)" rather than an alarming red 0.
        manual = {"CarGurus", "Clutch"}
        keys = order + [k for k in SOURCE_COUNTS if k not in order]
        parts_sh = []
        for k in keys:
            if k in SOURCE_COUNTS:
                if k in manual:
                    parts_sh.append(f'<span style="color:#94a3b8;">{k} (manual)</span>')
                else:
                    n = SOURCE_COUNTS[k]
                    color = "#16a34a" if n else "#dc2626"
                    parts_sh.append(f'<span style="color:{color};">{k} {n}</span>')
        source_health = ("Sources this run: " + " &nbsp;&middot;&nbsp; ".join(parts_sh)
                         + '. An automated source at <span style="color:#dc2626;">0</span> was likely '
                           'rate-limited/blocked this run, not empty. '
                           '<span style="color:#94a3b8;">CarGurus &amp; Clutch are manual</span> '
                           '(bot-blocked) &mdash; use their quick-links below.')
    else:
        source_health = ("Source counts unavailable (scraping disabled this run "
                         "&mdash; showing the last saved results).")

    criteria_html = _criteria_summary_html()
    leasebusters_html = _leasebusters_section_html()

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;margin:0;padding:20px;color:#333;line-height:1.6;">
    <h2 style="color:#2563eb;margin-top:0;">Daily Vehicle Search Results</h2>
    <p style="color:#555;font-size:14px;">Generated on: {est_now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}</p>
    <p style="color:#555;font-size:13px;">{real_count} real listing(s) found. <span style="color:#999;">Click a title to open the actual listing page.</span></p>
    {new_banner}
    {criteria_html}

    <h2 style="margin-top:30px;margin-bottom:0;color:#111;">Ranked Listings (Best Value First)</h2>
    <p style="color:#999;font-size:12px;margin-top:4px;">Grouped by model year and region; ranked by best value within each table. Alberta is split out because its 5% GST usually makes the same car cheaper there.</p>
    {sections_html}

    {leasebusters_html}

    <h3 style="border-bottom:2px solid #eee;padding-bottom:5px;margin-top:40px;">Marketplace Quick Links</h3>
    <p style="font-size:13px;color:#555;">One-click searches using exact strict filters.</p>
    {buttons_html}

    <hr style="margin-top:30px;border:none;border-top:1px solid #eee;">
    <p style="font-size:12px;color:#888;">{source_health}</p>
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
        if eastern_hour != 8:
            print(f"Skipping: Eastern hour is {eastern_hour}, not 8. "
                  f"Triggered by '{github_event}'.")
            return
    
    print(f"{'='*60}")
    print(f"  Vehicle Search Automation V3")
    print(f"  Started: {est_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Playwright available: {PLAYWRIGHT_AVAILABLE}")
    print(f"{'='*60}")

    # Optional: override criteria (years/price/mileage) from env / workflow inputs.
    _apply_criteria_env_overrides()

    if ENABLE_SCRAPE:
        scrape_and_populate_listings()
        # Flag which listings are new since the last run and persist the seen-set.
        mark_new_and_update_seen()

    print(f"\nGenerating HTML files...")
    email_html = generate_email_html(est_now)
    with open("gatineau_phev_rav4_search_results.html", "w", encoding="utf-8") as f:
        f.write(email_html)
    with open("dealers.html", "w", encoding="utf-8") as f:
        f.write(generate_dealers_html())
    
    print(f"Sending email...")
    send_email(
        f"Vehicle Search Update: {est_now.strftime('%b %d')} (Nationwide PHEV/RAV4)",
        email_html
    )
    print(f"\n{'='*60}")
    print(f"  Done!")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
