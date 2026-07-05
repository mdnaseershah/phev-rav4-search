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
    """Organize vehicles by year (2024-2020) and budget status"""
    within_budget = {}
    above_budget = {}
    
    for vehicle in vehicle_list:
        year = vehicle['year']
        price = int(str(vehicle['price']).replace(',', ''))
        
        if price <= BUDGET:
            if year not in within_budget:
                within_budget[year] = []
            within_budget[year].append(vehicle)
        else:
            if year not in above_budget:
                above_budget[year] = []
            above_budget[year].append(vehicle)
    
    return within_budget, above_budget

def format_vehicle_list(vehicle_list):
    """Format a list of vehicles with clean professional layout"""
    text = ""
    for i, vehicle in enumerate(vehicle_list, 1):
        text += f"\n  {i}. {vehicle['year']} {vehicle['make']} {vehicle['model']}\n"
        text += f"     💰 ${vehicle['price']}  |  🛣️ {vehicle['mileage']} km  |  🛩️ Sunroof: {vehicle['sunroof']}\n"
        text += f"     📍 {vehicle['city']}, {vehicle['province']}  |  Distance: {vehicle['distance']} km\n"
        text += f"     ⭐ {vehicle['rating']}\n"
        text += f"     Link: {vehicle['link']}\n"
    return text

def format_vehicle_list_html(vehicle_list):
    """Format vehicles as HTML rows"""
    html = ""
    for i, vehicle in enumerate(vehicle_list, 1):
        html += f"""
        <tr>
          <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #1f2937;">
            <strong>{vehicle['year']} {vehicle['make']} {vehicle['model']}</strong>
          </td>
          <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #1f2937;">
            💰 ${vehicle['price']}<br>
            🛣️ {vehicle['mileage']} km<br>
            🛩️ Sunroof: {vehicle['sunroof']}
          </td>
          <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #1f2937;">
            📍 {vehicle['city']}, {vehicle['province']}<br>
            Distance: {vehicle['distance']} km
          </td>
          <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center; color: #059669;">
            ⭐ {vehicle['rating']}
          </td>
          <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center;">
            <a href="{vehicle['link']}" style="display: inline-block; background-color: #2563eb; color: white; padding: 8px 16px; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 13px;">View Listing →</a>
          </td>
        </tr>
        """
    return html

def send_email(html_content, outlander_list, rav4_list):
    """Send email with HTML version (with buttons) and plain text fallback"""
    
    est_now = get_est_time()
    
    # Create email with alternative parts (HTML + plain text)
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Vehicle Search Results - {est_now.strftime('%B %d, %Y')}"
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = RECIPIENT_EMAIL
    
    # Organize results
    outlander_within, outlander_above = organize_by_year_and_budget(outlander_list)
    rav4_within, rav4_above = organize_by_year_and_budget(rav4_list)
    
    # ========== PLAIN TEXT VERSION (Fallback) ==========
    body_text = f"""VEHICLE SEARCH RESULTS

Generated: {est_now.strftime('%B %d, %Y at %I:%M %p EST')}
Search Radius: 400 km from Gatineau, QC
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
    
    body_text += f"\n\nTOYOTA RAV4 PRIME - Within Budget\n"
    
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
    
    body_text += f"\n\nPOPULAR MARKETPLACE LINKS\n\nClick the links below to search directly with filters applied:\n"
    
    for i, link in enumerate(POPULAR_LINKS, 1):
        body_text += f"\n{i}. {link['name']}\n   {link['url']}\n"
    
    body_text += f"""

---

Interactive HTML Report Attached

An interactive HTML report (gatineau_phev_rav4_search_results.html) is attached to this email.
Open it in your browser for tabbed navigation, dealer directory, and additional details.

Next update: Every 3 days at 8 AM EST | Powered by GitHub Actions
{est_now.strftime('%Y-%m-%d %I:%M %p EST')}
"""
    
    # ========== HTML VERSION (With Buttons) ==========
    outlander_html_within = format_vehicle_list_html(
        [v for year in sorted(outlander_within.keys(), reverse=True) for v in outlander_within[year]]
    ) if outlander_within else "<tr><td colspan='5' style='padding: 12px; text-align: center; color: #6b7280;'>No vehicles found within budget.</td></tr>"
    
    outlander_html_above = ""
    if outlander_above:
        outlander_html_above = format_vehicle_list_html(
            [v for year in sorted(outlander_above.keys(), reverse=True) for v in outlander_above[year]]
        )
    
    rav4_html_within = format_vehicle_list_html(
        [v for year in sorted(rav4_within.keys(), reverse=True) for v in rav4_within[year]]
    ) if rav4_within else "<tr><td colspan='5' style='padding: 12px; text-align: center; color: #6b7280;'>No vehicles found within budget.</td></tr>"
    
    rav4_html_above = ""
    if rav4_above:
        rav4_html_above = format_vehicle_list_html(
            [v for year in sorted(rav4_above.keys(), reverse=True) for v in rav4_above[year]]
        )
    
    # Build marketplace buttons
    buttons_html = ""
    for link in POPULAR_LINKS:
        buttons_html += f"""
        <a href="{link['url']}" style="display: inline-block; margin: 8px; padding: 12px 20px; background-color: #2563eb; color: white; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; border: 2px solid #2563eb; transition: all 0.2s;">
          {link['name']}
        </a>
        """
    
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    @media (prefers-color-scheme: dark) {{
      body {{ background-color: #111827; color: #f3f4f6; }}
      .container {{ background-color: #1f2937; }}
      .header {{ background: linear-gradient(135deg, #1e40af, #1e3a8a); }}
      table {{ background-color: #374151; }}
      td {{ color: #f3f4f6; }}
      .section-title {{ color: #f3f4f6; border-bottom: 2px solid #4b5563; }}
      .section-subtitle {{ color: #d1d5db; }}
      .footer {{ color: #9ca3af; }}
    }}
    
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background-color: #f9fafb; color: #1f2937; line-height: 1.6; }}
    .container {{ max-width: 800px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .header {{ background: linear-gradient(135deg, #2563eb, #1e40af); color: white; padding: 30px 20px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 24px; font-weight: 700; }}
    .header p {{ margin: 8px 0 0 0; font-size: 14px; opacity: 0.9; }}
    .content {{ padding: 30px 20px; }}
    .section {{ margin-bottom: 40px; }}
    .section-title {{ font-size: 18px; font-weight: 700; margin: 0 0 8px 0; padding-bottom: 8px; border-bottom: 2px solid #e5e7eb; }}
    .section-subtitle {{ font-size: 14px; color: #6b7280; margin: 0 0 16px 0; }}
    .year-heading {{ font-size: 15px; font-weight: 600; margin: 16px 0 8px 0; color: #2563eb; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th {{ text-align: left; padding: 12px; background-color: #f3f4f6; font-weight: 600; font-size: 12px; text-transform: uppercase; color: #6b7280; border-bottom: 2px solid #e5e7eb; }}
    td {{ padding: 12px; border-bottom: 1px solid #e5e7eb; }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .buttons {{ text-align: center; padding: 20px 0; }}
    .button {{ display: inline-block; margin: 8px; padding: 12px 20px; background-color: #2563eb; color: white; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; border: 2px solid #2563eb; }}
    .button:hover {{ background-color: #1d4ed8; border-color: #1d4ed8; }}
    .above-budget {{ background-color: #fef3c7; padding: 12px; border-left: 4px solid #f59e0b; border-radius: 4px; margin-bottom: 16px; }}
    .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #9ca3af; border-top: 1px solid #e5e7eb; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Vehicle Search Results</h1>
      <p>Generated {est_now.strftime('%B %d, %Y at %I:%M %p EST')}</p>
    </div>
    
    <div class="content">
      <!-- Marketplace Links Section -->
      <div class="section">
        <h2 class="section-title">Popular Marketplace Links</h2>
        <p class="section-subtitle">Click the buttons below to search directly with filters applied:</p>
        <div class="buttons">
          {buttons_html}
        </div>
      </div>

      <!-- Outlander Within Budget -->
      <div class="section">
        <h2 class="section-title">Mitsubishi Outlander PHEV - Within Budget</h2>
        <table>
          <thead>
            <tr>
              <th>Vehicle</th>
              <th>Details</th>
              <th>Location</th>
              <th>Rating</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {outlander_html_within}
          </tbody>
        </table>
      </div>

      <!-- Outlander Above Budget -->
      {f'''
      <div class="section">
        <div class="above-budget">
          <strong>⚠️ Above Budget (${BUDGET:,}+)</strong>
        </div>
        <table>
          <thead>
            <tr>
              <th>Vehicle</th>
              <th>Details</th>
              <th>Location</th>
              <th>Rating</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {outlander_html_above}
          </tbody>
        </table>
      </div>
      ''' if outlander_above else ''}

      <!-- RAV4 Within Budget -->
      <div class="section">
        <h2 class="section-title">Toyota RAV4 Prime - Within Budget</h2>
        <table>
          <thead>
            <tr>
              <th>Vehicle</th>
              <th>Details</th>
              <th>Location</th>
              <th>Rating</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rav4_html_within}
          </tbody>
        </table>
      </div>

      <!-- RAV4 Above Budget -->
      {f'''
      <div class="section">
        <div class="above-budget">
          <strong>⚠️ Above Budget (${BUDGET:,}+)</strong>
        </div>
        <table>
          <thead>
            <tr>
              <th>Vehicle</th>
              <th>Details</th>
              <th>Location</th>
              <th>Rating</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rav4_html_above}
          </tbody>
        </table>
      </div>
      ''' if rav4_above else ''}

      <!-- Footer -->
      <div class="footer">
        <p style="margin: 0 0 8px 0;">Interactive HTML report attached (gatineau_phev_rav4_search_results.html)</p>
        <p style="margin: 0;">Automated search every 3 days at 8 AM EST | {est_now.strftime('%Y-%m-%d %I:%M %p EST')}</p>
      </div>
    </div>
  </div>
</body>
</html>
"""
    
    # Attach plain text first (fallback)
    part1 = MIMEText(body_text, 'plain')
    msg.attach(part1)
    
    # Attach HTML (preferred)
    part2 = MIMEText(html_body, 'html')
    msg.attach(part2)
    
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

def generate_html_report(outlander_data, rav4_data):
    """Generate the HTML report with search results"""
    
    est_now = get_est_time()
    
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
<p>Automated search every 3 days | Generated {est_now.strftime('%B %d, %Y')} | 400 km radius from Gatineau, QC</p>
</header>

<main>
<section>
<h2>Mitsubishi Outlander PHEV (2020-2024)</h2>
<p class="intro">Search results within 400 km of Gatineau. Click the links below to search popular marketplaces directly.</p>
<div class="market-grid">{links_html}</div>
<table>
<thead><tr><th>#</th><th>Vehicle</th><th>Mileage</th><th>Price</th><th>Sunroof</th><th>Dealer / Distance</th><th>Distance</th><th>Rating</th><th>Link</th><th>Why Ranked</th></tr></thead>
<tbody>{outlander_rows}</tbody>
</table>
</section>

<section>
<h2>Toyota RAV4 Prime (2020-2024)</h2>
<p class="intro">RAV4 Prime plug-in hybrid listings within range.</p>
<table>
<thead><tr><th>#</th><th>Vehicle</th><th>Mileage</th><th>Price</th><th>Sunroof</th><th>Dealer / Distance</th><th>Distance</th><th>Rating</th><th>Link</th><th>Why Ranked</th></tr></thead>
<tbody>{rav4_rows}</tbody>
</table>
</section>

<p style="text-align:center; color:var(--muted); margin-top:40px; font-size:13px;">
Automated search every 3 days starting July 5, 2024 at 8 AM EST | Generated {est_now.strftime('%Y-%m-%d %I:%M %p EST')}
</p>
</main>
</body>
</html>"""
    return html

def main():
    """Main automation function"""
    est_now = get_est_time()
    print("🚗 Starting vehicle search automation...")
    print(f"📅 Run time: {est_now.strftime('%Y-%m-%d %I:%M:%S %p EST')}")
    
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
