#!/usr/bin/env python3
"""
Gatineau PHEV/RAV4 Search Automation
Scrapes listings and emails results every 3 days (starting July 5)
"""

import smtplib
import os
from datetime import datetime
import pytz
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.encoders import encode_base64

# Configuration
GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS')
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
GATINEAU_RADIUS = 400
BUDGET = 28000

# EST timezone
EST = pytz.timezone('US/Eastern')

# Popular marketplace links
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

def get_est_time():
    """Get current time in EST"""
    return datetime.now(EST)

def organize_by_year_and_budget(vehicle_list):
    """Organize vehicles by year and budget status"""
    within_budget = {}
    above_budget = {}
    
    for vehicle in vehicle_list:
        year = vehicle['year']
        price = int(str(vehicle['price']).replace(',', ''))
        
        if price <= BUDGET:
            within_budget.setdefault(year, []).append(vehicle)
        else:
            above_budget.setdefault(year, []).append(vehicle)
    
    return within_budget, above_budget

def format_vehicle_list(vehicle_list):
    """Plain text formatting for fallback"""
    text = ""
    for i, vehicle in enumerate(vehicle_list, 1):
        text += f"\n  {i}. {vehicle['year']} {vehicle['make']} {vehicle['model']}\n"
        text += f"     Price: ${vehicle['price']} | Mileage: {vehicle['mileage']} km | Sunroof: {vehicle['sunroof']}\n"
        text += f"     Location: {vehicle['city']}, {vehicle['province']} | Distance: {vehicle['distance']} km\n"
        text += f"     Rating: {vehicle['rating']}\n"
        text += f"     Link: {vehicle['link']}\n"
    return text

def format_vehicle_list_html(vehicle_list):
    """HTML rows for email sections"""
    html = ""
    for i, vehicle in enumerate(vehicle_list, 1):
        html += f"""
        <tr>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb;">
            <strong>{vehicle['year']} {vehicle['make']} {vehicle['model']}</strong><br>
            <span style="font-size: 12px; color: #6b7280;">#{i}</span>
          </td>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb;">
            <div>💰 ${vehicle['price']}</div>
            <div>🛣️ {vehicle['mileage']} km</div>
            <div>🛩️ Sunroof: {vehicle['sunroof']}</div>
          </td>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb;">
            <div>📍 {vehicle['city']}, {vehicle['province']}</div>
            <div>Distance: {vehicle['distance']} km</div>
          </td>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">
            <span style="display:inline-block;background-color:#dcfce7;color:#15803d;padding:4px 8px;border-radius:6px;font-size:12px;font-weight:600;">
              ⭐ {vehicle['rating']}
            </span>
          </td>
          <td style="padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: center;">
            <a href="{vehicle['link']}" style="display:inline-block;background-color:#2563eb;color:#ffffff;padding:6px 12px;border-radius:6px;font-size:12px;font-weight:600;text-decoration:none;">
              View Listing →
            </a>
          </td>
        </tr>
        """
    return html

def build_buttons_html():
    """Bulletproof responsive button grid for marketplaces"""
    return f"""
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:20px;">
  <tr>
    <td align="center" width="33%" style="padding:6px;">
      <a href="{POPULAR_LINKS[0]['url']}"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        {POPULAR_LINKS[0]['name']}
      </a>
    </td>
    <td align="center" width="33%" style="padding:6px;">
      <a href="{POPULAR_LINKS[1]['url']}"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        {POPULAR_LINKS[1]['name']}
      </a>
    </td>
    <td align="center" width="33%" style="padding:6px;">
      <a href="{POPULAR_LINKS[2]['url']}"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        {POPULAR_LINKS[2]['name']}
      </a>
    </td>
  </tr>
  <tr>
    <td align="center" width="33%" style="padding:6px;">
      <a href="{POPULAR_LINKS[3]['url']}"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        {POPULAR_LINKS[3]['name']}
      </a>
    </td>
    <td align="center" width="33%" style="padding:6px;">
      <a href="{POPULAR_LINKS[4]['url']}"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        {POPULAR_LINKS[4]['name']}
      </a>
    </td>
    <td width="33%"></td>
  </tr>
</table>
"""

def send_email(html_content, outlander_list, rav4_list):
    """Send email with dealership-grade layout + attachment"""
    est_now = get_est_time()

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Gatineau PHEV / RAV4 Prime Search Results - {est_now.strftime('%B %d, %Y')}"
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = RECIPIENT_EMAIL

    outlander_within, outlander_above = organize_by_year_and_budget(outlander_list)
    rav4_within, rav4_above = organize_by_year_and_budget(rav4_list)

    # ---------- Plain text fallback ----------
    body_text = f"""GATINEAU PHEV / RAV4 PRIME SEARCH RESULTS

Generated: {est_now.strftime('%B %d, %Y at %I:%M %p EST')}
Search Radius: {GATINEAU_RADIUS} km from Gatineau, QC
Budget: ${BUDGET:,} CAD

MITSUBISHI OUTLANDER PHEV - Within Budget
"""
    if outlander_within:
        for year in sorted(outlander_within.keys(), reverse=True):
            body_text += f"\n{year} Model Year:\n"
            body_text += format_vehicle_list(outlander_within[year])
    else:
        body_text += "\n  No vehicles found within budget.\n"

    if outlander_above:
        body_text += f"\n\nMITSUBISHI OUTLANDER PHEV - Above Budget (${BUDGET:,}+)\n"
        for year in sorted(outlander_above.keys(), reverse=True):
            body_text += f"\n{year} Model Year:\n"
            body_text += format_vehicle_list(outlander_above[year])

    body_text += "\n\nTOYOTA RAV4 PRIME - Within Budget\n"
    if rav4_within:
        for year in sorted(rav4_within.keys(), reverse=True):
            body_text += f"\n{year} Model Year:\n"
            body_text += format_vehicle_list(rav4_within[year])
    else:
        body_text += "\n  No vehicles found within budget.\n"

    if rav4_above:
        body_text += f"\n\nTOYOTA RAV4 PRIME - Above Budget (${BUDGET:,}+)\n"
        for year in sorted(rav4_above.keys(), reverse=True):
            body_text += f"\n{year} Model Year:\n"
            body_text += format_vehicle_list(rav4_above[year])

    body_text += "\n\nPOPULAR MARKETPLACE LINKS\n"
    for i, link in enumerate(POPULAR_LINKS, 1):
        body_text += f"\n{i}. {link['name']}\n   {link['url']}\n"

    body_text += f"""

Interactive HTML report attached: gatineau_phev_rav4_search_results.html
Open it in your browser for full dealer details and ranking explanations.

Next update: Every 3 days at 8 AM EST
"""

    # ---------- HTML version (dealership-grade) ----------

    # Flatten lists for HTML sections
    outlander_within_flat = [v for year in sorted(outlander_within.keys(), reverse=True) for v in outlander_within[year]]
    outlander_above_flat = [v for year in sorted(outlander_above.keys(), reverse=True) for v in outlander_above[year]]
    rav4_within_flat = [v for year in sorted(rav4_within.keys(), reverse=True) for v in rav4_within[year]]
    rav4_above_flat = [v for year in sorted(rav4_above.keys(), reverse=True) for v in rav4_above[year]]

    outlander_within_html = format_vehicle_list_html(outlander_within_flat) if outlander_within_flat else """
        <tr><td colspan="5" style="padding:12px;text-align:center;color:#6b7280;">No vehicles found within budget.</td></tr>
    """
    outlander_above_html = format_vehicle_list_html(outlander_above_flat) if outlander_above_flat else ""
    rav4_within_html = format_vehicle_list_html(rav4_within_flat) if rav4_within_flat else """
        <tr><td colspan="5" style="padding:12px;text-align:center;color:#6b7280;">No vehicles found within budget.</td></tr>
    """
    rav4_above_html = format_vehicle_list_html(rav4_above_flat) if rav4_above_flat else ""

    buttons_html = build_buttons_html()

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<style>
  @media (prefers-color-scheme: dark) {{
    body {{ background-color: #0b1120; color: #e5e7eb; }}
    .container {{ background-color: #1e293b; }}
    .header {{ background: linear-gradient(135deg, #1e40af, #1e3a8a); }}
    table {{ background-color: #0f172a; }}
    th {{ background-color: #1e293b; color: #cbd5e1; }}
    td {{ color: #e2e8f0; }}
    .section-title {{ color: #e2e8f0; border-bottom-color: #334155; }}
    .footer {{ color: #94a3b8; border-top-color: #334155; }}
  }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0;
    padding: 20px;
    background-color: #f3f4f6;
    color: #111827;
  }}

  .container {{
    max-width: 900px;
    margin: 0 auto;
    background-color: #ffffff;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 10px 30px rgba(0,0,0,0.15);
  }}

  .header {{
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    color: white;
    padding: 24px;
    text-align: center;
  }}

  .header h1 {{
    margin: 0;
    font-size: 22px;
    font-weight: 700;
  }}

  .header p {{
    margin: 6px 0 0;
    font-size: 13px;
    opacity: 0.9;
  }}

  .content {{ padding: 24px; }}

  .section {{ margin-bottom: 32px; }}

  .section-title {{
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 8px;
    border-bottom: 2px solid #e5e7eb;
    padding-bottom: 6px;
  }}

  .section-subtitle {{
    font-size: 14px;
    color: #6b7280;
    margin-bottom: 16px;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
    border-radius: 8px;
    overflow: hidden;
  }}

  th {{
    background-color: #f3f4f6;
    padding: 10px;
    font-size: 11px;
    text-transform: uppercase;
    color: #6b7280;
    border-bottom: 1px solid #e5e7eb;
  }}

  td {{
    padding: 10px;
    font-size: 13px;
    border-bottom: 1px solid #e5e7eb;
  }}

  details {{
    background-color: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 16px;
  }}

  summary {{
    cursor: pointer;
    font-weight: 600;
    font-size: 14px;
  }}

  .view-report-btn {{
    display: inline-block;
    background-color: #16a34a;
    color: white;
    padding: 10px 18px;
    border-radius: 999px;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    margin-top: 12px;
  }}

  .footer {{
    padding: 14px 20px;
    font-size: 11px;
    color: #6b7280;
    border-top: 1px solid #e5e7eb;
    text-align: center;
  }}
</style>
</head>

<body>
<div class="container">

  <div class="header">
    <h1>Gatineau PHEV / RAV4 Prime Search Results</h1>
    <p>Generated {est_now.strftime('%B %d, %Y at %I:%M %p EST')} · Radius {GATINEAU_RADIUS} km · Budget ${BUDGET:,} CAD</p>
  </div>

  <div class="content">

    <div class="section">
      <h2 class="section-title">Summary</h2>
      <p class="section-subtitle">
        Full HTML report attached (gatineau_phev_rav4_search_results.html). Open it in your browser for dealer details and ranking explanations.
      </p>
      <a class="view-report-btn" href="#">View Full Report (HTML Attachment)</a>
    </div>

    <div class="section">
      <h2 class="section-title">Mitsubishi Outlander PHEV</h2>

      <details open>
        <summary>Within Budget (≤ ${BUDGET:,})</summary>
        <table>
          <thead>
            <tr>
              <th>Vehicle</th><th>Details</th><th>Location</th><th>Rating</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            {outlander_within_html}
          </tbody>
        </table>
      </details>

      {f"""
      <details>
        <summary>Above Budget (> ${BUDGET:,})</summary>
        <table>
          <thead>
            <tr>
              <th>Vehicle</th><th>Details</th><th>Location</th><th>Rating</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            {outlander_above_html}
          </tbody>
        </table>
      </details>
      """ if outlander_above_html.strip() else ""}
    </div>

    <div class="section">
      <h2 class="section-title">Toyota RAV4 Prime</h2>

      <details open>
        <summary>Within Budget (≤ ${BUDGET:,})</summary>
        <table>
          <thead>
            <tr>
              <th>Vehicle</th><th>Details</th><th>Location</th><th>Rating</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rav4_within_html}
          </tbody>
        </table>
      </details>

      {f"""
      <details>
        <summary>Above Budget (> ${BUDGET:,})</summary>
        <table>
          <thead>
            <tr>
              <th>Vehicle</th><th>Details</th><th>Location</th><th>Rating</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rav4_above_html}
          </tbody>
        </table>
      </details>
      """ if rav4_above_html.strip() else ""}
    </div>

    <div class="section">
      <h2 class="section-title">Popular Marketplace Links</h2>
      <p class="section-subtitle">Tap on iPhone or click on desktop to open filtered searches.</p>
      {buttons_html}
    </div>

  </div>

  <div class="footer">
    Automated every 3 days · HTML report attached · {est_now.strftime('%Y-%m-%d %I:%M %p EST')}
  </div>

</div>
</body>
</html>
"""

    msg.attach(MIMEText(body_text, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    filename = 'gatineau_phev_rav4_search_results.html'
    attachment = MIMEBase('application', 'octet-stream')
    attachment.set_payload(html_content.encode('utf-8'))
    encode_base64(attachment)
    attachment.add_header('Content-Disposition', f'attachment; filename={filename}')
    msg.attach(attachment)

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

def generate_html_report(outlander_data, rav4_data):
    """Generate standalone HTML report (attachment)"""
    est_now = get_est_time()

    links_html = ''.join([
        f'<a class="market-card" href="{link["url"]}" target="_blank" rel="noopener">{link["name"]}</a>'
        for link in POPULAR_LINKS
    ])

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
:root {{
  --accent:#2563eb;
  --accent-dark:#1d4ed8;
  --good-bg:#dcfce7;
  --good:#15803d;
  --bg:#f8fafc;
  --card:#ffffff;
  --border:#e2e8f0;
  --text:#1e293b;
  --muted:#64748b;
}}
body {{
  font-family:'Segoe UI',Arial,sans-serif;
  background:var(--bg);
  color:var(--text);
  margin:0;
  padding:24px;
}}
header {{
  background:linear-gradient(135deg,var(--accent),var(--accent-dark));
  color:#fff;
  padding:20px 24px;
  border-radius:12px;
  margin-bottom:20px;
}}
header h1 {{
  margin:0 0 6px;
  font-size:22px;
}}
header p {{
  margin:0;
  font-size:13px;
  opacity:.9;
}}
.market-grid {{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:10px;
  margin:16px 0 24px;
}}
.market-card {{
  display:block;
  background:var(--card);
  border:1px solid var(--border);
  border-radius:10px;
  padding:12px;
  text-align:center;
  font-weight:600;
  color:var(--accent);
  text-decoration:none;
}}
table {{
  width:100%;
  border-collapse:collapse;
  background:var(--card);
  border-radius:10px;
  overflow:hidden;
  margin-bottom:24px;
}}
th,td {{
  padding:10px 12px;
  border-bottom:1px solid var(--border);
  font-size:13px;
}}
th {{
  background:#f1f5f9;
  font-weight:600;
  font-size:11px;
  text-transform:uppercase;
  color:var(--muted);
}}
.rating {{
  padding:3px 9px;
  border-radius:6px;
  font-weight:700;
  font-size:12px;
}}
.rating.good {{
  background:var(--good-bg);
  color:var(--good);
}}
.link-btn {{
  background:var(--accent);
  color:#fff;
  padding:6px 12px;
  border-radius:6px;
  text-decoration:none;
  font-size:12px;
  font-weight:600;
}}
.dist {{
  color:var(--muted);
  font-size:12px;
}}
.why {{
  color:var(--muted);
  font-size:12px;
}}
</style>
</head>
<body>
<header>
  <h1>Gatineau PHEV / RAV4 Prime Search Results</h1>
  <p>Automated search every 3 days · Generated {est_now.strftime('%B %d, %Y at %I:%M %p EST')} · Radius {GATINEAU_RADIUS} km from Gatineau, QC</p>
</header>

<section>
  <h2>Mitsubishi Outlander PHEV (2020–2024)</h2>
  <div class="market-grid">{links_html}</div>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Vehicle</th>
        <th>Mileage</th>
        <th>Price</th>
        <th>Sunroof</th>
        <th>Dealer / Location</th>
        <th>Distance</th>
        <th>Rating</th>
        <th>Link</th>
        <th>Why Ranked</th>
      </tr>
    </thead>
    <tbody>
      {outlander_rows}
    </tbody>
  </table>
</section>

<section>
  <h2>Toyota RAV4 Prime (2020–2024)</h2>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Vehicle</th>
        <th>Mileage</th>
        <th>Price</th>
        <th>Sunroof</th>
        <th>Dealer / Location</th>
        <th>Distance</th>
        <th>Rating</th>
        <th>Link</th>
        <th>Why Ranked</th>
      </tr>
    </thead>
    <tbody>
      {rav4_rows}
    </tbody>
  </table>
</section>
</body>
</html>
"""
    return html

def main():
    """Main automation function"""
    est_now = get_est_time()
    print("🚗 Starting vehicle search automation...")
    print(f"📅 Run time: {est_now.strftime('%Y-%m-%d %I:%M:%S %p EST')}")

    # Placeholder data – replace with scraped results later
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
        }
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
        }
    ]

    html_report = generate_html_report(outlander_data, rav4_data)

    with open('gatineau_phev_rav4_search_results.html', 'w', encoding='utf-8') as f:
        f.write(html_report)
    print("✓ HTML report generated")

    if GMAIL_ADDRESS and GMAIL_PASSWORD and RECIPIENT_EMAIL:
        send_email(html_report, outlander_data, rav4_data)
    else:
        print("⚠ Email credentials not set. Skipping email send.")
        print("  Set GMAIL_ADDRESS, GMAIL_PASSWORD, and RECIPIENT_EMAIL environment variables")

if __name__ == '__main__':
    main()
