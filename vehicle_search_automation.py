#!/usr/bin/env python3
"""
vehicle_search_automation.py

Full replacement: conservative scraper + HTML/email generator.
- Populates LISTINGS[*]['url'] with real listing URLs when available (AutoTrader, Kijiji, CarGurus, dealer sites).
- Stricter link selection to avoid landing on unrelated listings.
- Preserves email layout, fonts, colors, and behavior (marketplace buttons moved to bottom).
- Generates gatineau_phev_rav4_search_results.html and dealers.html and sends email if credentials provided.

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

ENABLE_SCRAPE = os.getenv('ENABLE_SCRAPE', '0') == '1'
REQUEST_DELAY = float(os.getenv('REQUEST_DELAY', '1.0'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '2'))

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GatineauSearchBot/1.0; +https://example.com)",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
}

DEALERS_JSON = "dealers.json"  # optional: full dealers list

# -------------------------
# Marketplaces and helpers
# -------------------------
MARKETPLACE_LINKS = [
    {"name": "AutoTrader.ca", "url": "https://www.autotrader.ca/cars/mitsubishi/outlander-phev/reg_qc/cit_gatineau"},
    {"name": "CarGurus.ca", "url": "https://www.cargurus.ca/search?zip=J8T&distance=400&sortDirection=ASC&sortType=PRICE"},
    {"name": "Kijiji", "url": "https://www.kijiji.ca/b-cars-trucks/canada/mitsubishi+outlander+phev"},
    {"name": "Facebook Marketplace", "url": "https://www.facebook.com/marketplace/category/vehicles"},
]

# -------------------------
# Vehicles to find (you can extend)
# -------------------------
WANTED_VEHICLES = [
    {"vehicle": "2023 Mitsubishi Outlander PHEV SE", "make": "Mitsubishi", "model": "Outlander PHEV"},
    {"vehicle": "2024 Toyota RAV4 Prime XSE", "make": "Toyota", "model": "RAV4 Prime"},
]

# -------------------------
# Placeholder LISTINGS (kept for backward compatibility)
# These will be updated by the scraper when ENABLE_SCRAPE=1
# -------------------------
LISTINGS = [
    {
        "vehicle": "2023 Mitsubishi Outlander PHEV SE",
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
        "vehicle": "2024 Toyota RAV4 Prime XSE",
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
    # ... add more or use dealers.json
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
# Marketplace-specific builders/parsers (STRICTER)
# -------------------------
def build_autotrader_search_url(make: str, model: str, location="Gatineau, QC"):
    make_q = urllib.parse.quote_plus(make)
    model_q = urllib.parse.quote_plus(model)
    loc_q = urllib.parse.quote_plus(location)
    return f"https://www.autotrader.ca/cars/{make_q}/{model_q}/?loc={loc_q}&prx=400"

def build_kijiji_search_url(query: str):
    q = urllib.parse.quote_plus(query)
    return f"https://www.kijiji.ca/b-cars-trucks/canada/{q}/k0c174l1700199"

def build_cargurus_search_url(make: str, model: str):
    q = urllib.parse.quote_plus(f"{make} {model}")
    return f"https://www.cargurus.ca/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action?keyword={q}"

# --- STRICTER: build_marketplace_search_url ---
def build_marketplace_search_url(vehicle_name: str, prefer: str = "autotrader") -> str:
    """
    Build a marketplace search URL for a vehicle name.
    Extracts year/make/model/trim tokens to form a precise search.
    prefer: 'autotrader' or 'kijiji' (fallback to google).
    """
    s = vehicle_name.strip()
    year_match = re.match(r'^(19|20)\d{2}', s)
    year = year_match.group(0) if year_match else ""
    tokens = s.split()
    if year:
        tokens = tokens[1:]
    make = tokens[0] if len(tokens) >= 1 else ""
    # model may be multiple tokens (e.g., "RAV4 Prime", "Outlander PHEV SE")
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
        return f"https://www.kijiji.ca/b-cars-trucks/canada/{q}/k0c174l1700199"
    else:
        return f"https://www.google.com/search?q={q}+Gatineau+cars"

# --- STRICTER: parse_autotrader_first_listing ---
def parse_autotrader_first_listing(html_text):
    """
    Stricter parse for AutoTrader search results:
    - Prefer anchors whose visible text contains year, make and model tokens.
    - If none match, fall back to data-listing-id anchors or first reasonable /cars/ link.
    """
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "lxml")

    anchors = [a for a in soup.select("a[href]") if a.get("href")]
    # First pass: anchors whose visible text contains year and vehicle keywords
    for a in anchors:
        href = a.get("href", "")
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        text = (a.get_text(" ", strip=True) or "")
        if re.search(r'\b(19|20)\d{2}\b', text) and re.search(r'\b(outlander|rav4|prime|phev)\b', text, re.I):
            return urllib.parse.urljoin("https://www.autotrader.ca", href)
    # Second pass: anchors where text contains vehicle keywords and href looks like listing
    for a in anchors:
        href = a.get("href", "")
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        text = (a.get_text(" ", strip=True) or "").lower()
        if any(k in text for k in ["outlander", "rav4", "prime", "phev", "toyota", "mitsubishi"]):
            if "/cars/" in href or "listing" in href or "/v1/" in href:
                return urllib.parse.urljoin("https://www.autotrader.ca", href)
    # Third pass: data-listing-id anchors
    for tag in soup.find_all(attrs={"data-listing-id": True}):
        a = tag.find("a", href=True)
        if a:
            href = a["href"]
            if href:
                return urllib.parse.urljoin("https://www.autotrader.ca", href)
    # Final fallback: first reasonable /cars/ link
    for a in anchors:
        href = a.get("href", "")
        if "/cars/" in href:
            return urllib.parse.urljoin("https://www.autotrader.ca", href)
    return None

# --- STRICTER: parse_kijiji_first_listing ---
def parse_kijiji_first_listing(html_text):
    """
    Stricter parse for Kijiji:
    - Prefer anchors whose visible text contains make and model tokens.
    - Prefer links with '/v-view-details.html' or listing-card anchors.
    """
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "lxml")
    anchors = [a for a in soup.select("a[href]") if a.get("href")]
    for a in anchors:
        href = a.get("href", "")
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        text = (a.get_text(" ", strip=True) or "").lower()
        if any(k in text for k in ["outlander", "rav4", "prime", "phev", "toyota", "mitsubishi"]):
            if "/v-view-details.html" in href or "/v-cars-trucks" in href or "/v-autos" in href:
                return urllib.parse.urljoin("https://www.kijiji.ca", href)
    first = soup.select_one("div.search-item a[href], .search-item a[href], .regular-ad a[href]")
    if first:
        href = first.get("href")
        if href:
            return urllib.parse.urljoin("https://www.kijiji.ca", href)
    for a in anchors:
        href = a.get("href", "")
        if "/v-view-details.html" in href or "/v-cars-trucks" in href:
            return urllib.parse.urljoin("https://www.kijiji.ca", href)
    return None

def parse_cargurus_first_listing(html_text):
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "lxml")
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if href.startswith("/Cars/inventory/") or "/cars/" in href.lower():
            return urllib.parse.urljoin("https://www.cargurus.ca", href)
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
        if not href:
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
    parts = vehicle_name.split()
    if parts and parts[0].isdigit():
        parts = parts[1:]
    make = parts[0] if len(parts) >= 1 else ""
    model = parts[1] if len(parts) >= 2 else ""
    return build_autotrader_search_url(make, model)

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
        print(f"Searching marketplaces for: {vehicle_name}")

        at_url = build_autotrader_search_url(make, model)
        at_html = http_get(at_url)
        at_listing = parse_autotrader_first_listing(at_html)
        if at_listing:
            print(f"  AutoTrader -> {at_listing}")
            found_map[vehicle_name] = at_listing
            continue

        cg_url = build_cargurus_search_url(make, model)
        cg_html = http_get(cg_url)
        cg_listing = parse_cargurus_first_listing(cg_html)
        if cg_listing:
            print(f"  CarGurus -> {cg_listing}")
            found_map[vehicle_name] = cg_listing
            continue

        kj_url = build_kijiji_search_url(f"{make} {model}")
        kj_html = http_get(kj_url)
        kj_listing = parse_kijiji_first_listing(kj_html)
        if kj_listing:
            print(f"  Kijiji -> {kj_listing}")
            found_map[vehicle_name] = kj_listing
            continue

        print("  Probing dealer websites for direct listings (this may take a while)...")
        for site in tqdm(dealer_sites, desc="Probing dealers", unit="site"):
            try:
                found = probe_dealer_for_listing(site, make, model)
                if found:
                    print(f"    Found on dealer site {site} -> {found}")
                    found_map[vehicle_name] = found
                    break
            except Exception as e:
                print(f"    Probe failed for {site}: {e}")
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
# HTML generation (unchanged layout)
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
    for link in MARKETING_LINKS_PLACEHOLDER():
        buttons_html += f'<a href="{link["url"]}" style="display:inline-block;margin:8px 8px 8px 0;padding:10px 16px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;" target="_blank" rel="noopener">{link["name"]}</a>\n'
    outlander_rows = []
    rav4_rows = []
    for listing in LISTINGS:
        raw_url = listing.get('url') or ""
        if not raw_url or "example.com" in raw_url.lower():
            vehicle_href = generate_marketplace_search_url(listing.get('vehicle',''))
        else:
            vehicle_href = raw_url
        row = f"""<tr>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;"><a href="{vehicle_href}" target="_blank" rel="noopener" style="color:#2563eb;text-decoration:none;">{listing['vehicle']}</a></td>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;">{listing['price']} · {listing['mileage']} · Sunroof: {listing['sunroof']}</td>
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
    <h1>🚗 Vehicle Search Results</h1>
    <div class="meta">Generated: {est_now.strftime('%B %d, %Y at %I:%M %p EST')}</div>
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
    <strong>📎 Dealers List:</strong> The attached <strong>dealers.html</strong> file contains all {len(load_dealers_from_file())} dealers in your area. 
    Download it and open in your browser to see the full list with clickable links.
  </div>

  <div class="footer">
    Next update: Every 3 days at 8 AM EST<br>
    Generated: {est_now.strftime('%Y-%m-%d %I:%M %p EST')}
  </div>
</div>
</body>
</html>
"""
    return html

def MARKETING_LINKS_PLACEHOLDER():
    return MARKETPLACE_LINKS

# -------------------------
# Email send (unchanged)
# -------------------------
def send_email(subject, html_body, files_to_attach):
    if not (GMAIL_ADDRESS and GMAIL_PASSWORD and RECIPIENT_EMAIL):
        print("⚠ Email credentials not set. Skipping send.")
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
            print(f"✓ Attached {filepath}")
        except Exception as e:
            print(f"✗ Failed to attach {filepath}: {e}")
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30)
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        server.quit()
        print("✓ Email sent successfully!")
    except Exception as e:
        print(f"✗ Email failed: {e}")

# -------------------------
# Main
# -------------------------
def main():
    est_now = datetime.now(EST)
    if ENABLE_SCRAPE:
        print("ENABLE_SCRAPE=1: attempting to scrape marketplaces and dealer sites for real listing URLs...")
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
    print("✓ Generated dealers.html")
    with open('gatineau_phev_rav4_search_results.html', 'w', encoding='utf-8') as f:
        f.write(email_html)
    print("✓ Generated gatineau_phev_rav4_search_results.html")
    subject = f"Vehicle Search Results - {est_now.strftime('%B %d, %Y')}"
    send_email(subject, email_html, ['gatineau_phev_rav4_search_results.html', 'dealers.html'])

if __name__ == '__main__':
    main()
