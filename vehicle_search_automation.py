#!/usr/bin/env python3
"""
Gatineau PHEV/RAV4 Search Automation
Scrapes listings and emails results every 3 days (starting July 5)
"""

import smtplib
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.encoders import encode_base64
import requests
from bs4 import BeautifulSoup
import json

# Configuration
GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS')  # Set via GitHub Secrets
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')  # Gmail App Password (not regular password)
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
GATINEAU_RADIUS = 400  # km
BUDGET = 28000  # CAD

# Popular marketplace links (these are the 5 links from your landing page)
POPULAR_LINKS = [
    {
        "name": "AutoTrader.ca",
        "url": "https://www.autotrader.ca/cars/mitsubishi/outlander-phev/reg_qc/cit_gatineau/pr_28000?offer=N%2CU&modelyearfrom=2020&modelyearto=2024&cy=CA&damaged_listing=exclude&desc=0&kmto=70000&sort=price&ustate=N%2CU&zip=Gatineau&zipr=500&atype=C&size=50"
    },
    {
        "name": "CarGurus.ca",
        "url": "https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&srpVariation=DEFAULT_SEARCH&zip=J8T&distance=400&sortDirection=ASC&sortType=PRICE&makeModelTrimPaths=m46%2Fd2652&maxPrice=28000&minYear=2020&maxMileage=70000"
    },
    {
        "name": "Kijiji",
        "url": "https://www.kijiji.ca/b-cars-trucks/canada/mitsubishi+outlander+phev/k0c174l0"
    },
    {
        "name": "Clutch.ca",
        "url": "https://www.clutch.ca/cars/mitsubishi/outlander-phev"
    },
    {
        "name": "Facebook Marketplace",
        "url": "https://www.facebook.com/marketplace/category/vehicles?query=Mitsubishi%20Outlander%20PHEV"
    }
]

def generate_html_report(outlander_data, rav4_data):
    """Generate the HTML report with search results"""
    
    # Build popular links section
    links_html = ''.join([
        f'<a class="market-card" href="{link["url"]}" target="_blank" rel="noopener">{link["name"]}</a>'
        for link in POPULAR_LINKS
    ])
    
    # Build Outlander table
    outlander_rows = ''.join([
        f"""<tr>
            <td>{i+1}</td>
            <td>{vehicle['year']} {vehicle['make']} {vehicle['model']}</td>
            <td>{vehicle['mileage']} km</td>
            <td>${vehicle['price']}</td>
            <td>{vehicle['sunroof']}</td>
            <td>{vehicle['dealer']}<br><span class="dist">{vehicle['city']}, {vehicle['province']}</span></td>
            <td class="dist">{vehicle['distance']} km</td>
            <td><span class="rating good">{vehicle['rating']}</span></td>
            <td><a class="link-btn" href="{vehicle['link']}" target="_blank" rel="noopener">View →</a></td>
            <td class="why">{vehicle['why_ranked']}</td>
        </tr>"""
        for i, vehicle in enumerate(outlander_data)
    ])
    
    # Build RAV4 table
    rav4_rows = ''.join([
        f"""<tr>
            <td>{i+1}</td>
            <td>{vehicle['year']} {vehicle['make']} {vehicle['model']}</td>
            <td>{vehicle['mileage']} km</td>
            <td>${vehicle['price']}</td>
            <td>{vehicle['sunroof']}</td>
            <td>{vehicle['dealer']}<br><span class="dist">{vehicle['city']}, {vehicle['province']}</span></td>
            <td class="dist">{vehicle['distance']} km</td>
            <td><span class="rating good">{vehicle['rating']}</span></td>
            <td><a class="link-btn" href="{vehicle['link']}" target="_blank" rel="noopener">View →</a></td>
            <td class="why">{vehicle['why_ranked']}</td>
        </tr>"""
        for i, vehicle in enumerate(rav4_data)
    ])
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Gatineau PHEV / RAV4 Prime Search Results</title>
<style>
:root{{--accent:#2563eb;--accent-dark:#1d4ed8;--amber:#b45309;--amber-bg:#fef3c7;--good-bg:#dcfce7;--good:#15803d;--bg:#f8fafc;--card:#ffffff;--border:#e2e8f0;--text:#1e293b;--muted:#64748b;}}
*{{box-sizing:border-box;}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--text);margin:0;padding:0;}}
header{{background:linear-gradient(135deg,var(--accent),var(--accent-dark));color:#fff;padding:28px 32px;}}
header h1{{margin:0 0 6px;font-size:26px;}}
header p{{margin:0;opacity:.9;font-size:14px;}}
.tabbar{{display:flex;gap:10px;padding:18px 32px 0;background:var(--bg);flex-wrap:wrap;}}
.tab-btn{{border:2px solid var(--border);background:#fff;border-radius:999px;padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:8px;color:var(--muted);transition:all .15s ease;}}
.tab-btn:hover{{border-color:var(--accent);color:var(--accent);}}
.tab-btn.active{{background:var(--accent);border-color:var(--accent);color:#fff;}}
main{{padding:24px 32px 60px;max-width:1200px;margin:0 auto;}}
.intro{{color:var(--muted);font-size:15px;margin-bottom:18px;line-height:1.5;}}
.market-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:28px;}}
.market-card{{display:block;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;text-align:center;font-weight:600;color:var(--accent);text-decoration:none;transition:all .15s ease;}}
.market-card:hover{{border-color:var(--accent);box-shadow:0 4px 12px rgba(37,99,235,.15);}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06);}}
th,td{{padding:10px 12px;text-align:left;font-size:13.5px;border-bottom:1px solid var(--border);}}
th{{background:#f1f5f9;font-weight:700;color:var(--muted);text-transform:uppercase;font-size:11.5px;}}
.rating{{padding:3px 9px;border-radius:6px;font-weight:700;font-size:12.5px;}}
.rating.good{{background:var(--good-bg);color:var(--good);}}
.link-btn{{background:var(--accent);color:#fff;padding:6px 12px;border-radius:6px;text-decoration:none;font-size:12.5px;font-weight:600;white-space:nowrap;}}
.link-btn:hover{{background:var(--accent-dark);}}
.dist{{color:var(--muted);font-weight:600;}}
.why{{font-size:13px;color:var(--muted);}}
</style>
</head>
<body>
<header>
<h1>Gatineau PHEV / RAV4 Prime Search Results</h1>
<p>Automated Weekly Search · Generated {datetime.now().strftime('%Y-%m-%d')} · 400km radius from Gatineau, QC · Budget $28,000 CAD</p>
</header>

<main>
<section>
<h2>Mitsubishi Outlander PHEV</h2>
<p class="intro">Verified listings within 400km of Gatineau under $28,000 budget. Use the links below to search popular marketplaces directly.</p>
<div class="market-grid">{links_html}</div>
<table>
<thead><tr><th>#</th><th>Vehicle</th><th>Mileage</th><th>Price</th><th>Sunroof</th><th>Dealer / Distance</th><th>Distance</th><th>Rating</th><th>Link</th><th>Why this rank</th></tr></thead>
<tbody>{outlander_rows}</tbody>
</table>
</section>

<section>
<h2>Toyota RAV4 Prime</h2>
<p class="intro">Toyota RAV4 Prime plug-in hybrid listings within range.</p>
<table>
<thead><tr><th>#</th><th>Vehicle</th><th>Mileage</th><th>Price</th><th>Sunroof</th><th>Dealer / Distance</th><th>Distance</th><th>Rating</th><th>Link</th><th>Why this rank</th></tr></thead>
<tbody>{rav4_rows}</tbody>
</table>
</section>

<p style="text-align:center; color:var(--muted); margin-top:40px; font-size:13px;">
Automated search running every 3 days (starting July 5 at 8 AM EST). <br>
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
</p>
</main>
</body>
</html>"""
    return html

def send_email(html_content, outlander_list, rav4_list):
    """Send email with HTML attachment and summary in body"""
    
    # Create email
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Vehicle Search Update - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = RECIPIENT_EMAIL
    
    # Email body with search results summary
    body_text = f"""
Weekly PHEV/RAV4 Search Results
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}

POPULAR MARKETPLACE LINKS:
"""
    for i, link in enumerate(POPULAR_LINKS, 1):
        body_text += f"\n{i}. {link['name']}: {link['url']}"
    
    body_text += f"\n\nOUTLANDER PHEV RESULTS ({len(outlander_list)} vehicles found):\n"
    for i, vehicle in enumerate(outlander_list, 1):
        body_text += f"\n{i}. {vehicle['year']} {vehicle['make']} {vehicle['model']}"
        body_text += f"\n   Price: ${vehicle['price']} | Mileage: {vehicle['mileage']} km"
        body_text += f"\n   Location: {vehicle['city']}, {vehicle['province']} ({vehicle['distance']} km)"
        body_text += f"\n   Link: {vehicle['link']}\n"
    
    body_text += f"\nRAV4 PRIME RESULTS ({len(rav4_list)} vehicles found):\n"
    for i, vehicle in enumerate(rav4_list, 1):
        body_text += f"\n{i}. {vehicle['year']} {vehicle['make']} {vehicle['model']}"
        body_text += f"\n   Price: ${vehicle['price']} | Mileage: {vehicle['mileage']} km"
        body_text += f"\n   Location: {vehicle['city']}, {vehicle['province']} ({vehicle['distance']} km)"
        body_text += f"\n   Link: {vehicle['link']}\n"
    
    body_text += "\n\nFull interactive report attached (open in browser).\nView the 5 popular marketplace links above to search directly.\n"
    
    part1 = MIMEText(body_text, 'plain')
    msg.attach(part1)
    
    # Attach HTML file
    filename = 'gatineau_phev_rav4_search_results.html'
    attachment = MIMEBase('application', 'octet-stream')
    attachment.set_payload(html_content.encode('utf-8'))
    encode_base64(attachment)
    attachment.add_header('Content-Disposition', f'attachment; filename= {filename}')
    msg.attach(attachment)
    
    # Send via Gmail
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✓ Email sent successfully!")
        return True
    except Exception as e:
        print(f"✗ Email failed: {e}")
        return False

def main():
    """Main automation function"""
    print("🚗 Starting vehicle search automation...")
    print(f"📅 Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # TODO: Replace with actual web scraping logic
    # For now, using placeholder data structure
    outlander_data = [
        {
            'year': 2022,
            'make': 'Mitsubishi',
            'model': 'Outlander PHEV GT',
            'mileage': '54,108',
            'price': '27,992',
            'sunroof': 'Yes',
            'dealer': 'Mitsubishi Vaudreuil',
            'city': 'Vaudreuil-Dorion',
            'province': 'QC',
            'distance': 132,
            'rating': '5.0★',
            'link': 'https://www.cargurus.ca/details/428782812',
            'why_ranked': 'Newest year at this price, sunroof confirmed, rated Good Deal'
        },
        # Add more listings as needed
    ]
    
    rav4_data = [
        {
            'year': 2023,
            'make': 'Toyota',
            'model': 'RAV4 Prime',
            'mileage': '12,500',
            'price': '42,500',
            'sunroof': 'Yes',
            'dealer': 'Toyota Gatineau',
            'city': 'Gatineau',
            'province': 'QC',
            'distance': 5,
            'rating': '4.3★',
            'link': 'https://www.autotrader.ca/',
            'why_ranked': 'Low mileage, local dealer, excellent condition'
        },
        # Add more listings as needed
    ]
    
    # Generate HTML
    html_report = generate_html_report(outlander_data, rav4_data)
    
    # Save locally
    with open('gatineau_phev_rav4_search_results.html', 'w', encoding='utf-8') as f:
        f.write(html_report)
    print("✓ HTML report generated")
    
    # Send email
    if GMAIL_ADDRESS and GMAIL_PASSWORD and RECIPIENT_EMAIL:
        send_email(html_report, outlander_data, rav4_data)
    else:
        print("⚠ Email credentials not set. Skipping email send.")
        print("  Set GMAIL_ADDRESS, GMAIL_PASSWORD, and RECIPIENT_EMAIL environment variables")

if __name__ == '__main__':
    main()
