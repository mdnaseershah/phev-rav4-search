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
    return datetime.now(EST)

def organize_by_year_and_budget(vehicle_list):
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
    text = ""
    for i, vehicle in enumerate(vehicle_list, 1):
        text += f"\n  {i}. {vehicle['year']} {vehicle['make']} {vehicle['model']}\n"
        text += f"     💰 ${vehicle['price']}  |  🛣️ {vehicle['mileage']} km  |  🛩️ Sunroof: {vehicle['sunroof']}\n"
        text += f"     📍 {vehicle['city']}, {vehicle['province']}  |  Distance: {vehicle['distance']} km\n"
        text += f"     ⭐ {vehicle['rating']}\n"
        text += f"     Link: {vehicle['link']}\n"
    return text

def format_vehicle_list_html(vehicle_list):
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
    est_now = get_est_time()

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Vehicle Search Results - {est_now.strftime('%B %d, %Y')}"
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = RECIPIENT_EMAIL

    outlander_within, outlander_above = organize_by_year_and_budget(outlander_list)
    rav4_within, rav4_above = organize_by_year_and_budget(rav4_list)

    # ------------------------------
    # RESPONSIVE OUTLOOK-SAFE BUTTONS
    # ------------------------------
    buttons_html = """
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:20px;">
  <tr>
    <td align="center" width="33%" style="padding:6px;">
      <a href="https://www.autotrader.ca/cars/mitsubishi/outlander-phev/reg_qc/cit_gatineau/pr_28000?offer=N%2CU&modelyearfrom=2020&modelyearto=2024&cy=CA&damaged_listing=exclude&desc=0&kmto=70000&sort=price&ustate=N%2CU&zip=Gatineau&zipr=500&atype=C&size=50"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        AutoTrader.ca
      </a>
    </td>

    <td align="center" width="33%" style="padding:6px;">
      <a href="https://www.cargurus.ca/search?sourceContext=carGurusHomePageModel&srpVariation=DEFAULT_SEARCH&zip=J8T&distance=400&sortDirection=ASC&sortType=PRICE&makeModelTrimPaths=m46%2Fd2652&maxPrice=28000&minYear=2020&maxMileage=70000"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        CarGurus.ca
      </a>
    </td>

    <td align="center" width="33%" style="padding:6px;">
      <a href="https://www.kijiji.ca/b-cars-trucks/canada/mitsubishi+outlander+phev/k0c174l0"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        Kijiji
      </a>
    </td>
  </tr>

  <tr>
    <td align="center" width="33%" style="padding:6px;">
      <a href="https://www.clutch.ca/cars/mitsubishi/outlander-phev"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        Clutch.ca
      </a>
    </td>

    <td align="center" width="33%" style="padding:6px;">
      <a href="https://www.facebook.com/marketplace/category/vehicles?query=Mitsubishi%20Outlander%20PHEV"
         style="background:#2563eb;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 16px;display:block;border-radius:8px;">
        Facebook Marketplace
      </a>
    </td>

    <td width="33%"></td>
  </tr>
</table>
"""

    # ------------------------------
    # HTML BODY (with buttons)
    # ------------------------------
    html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Segoe UI,Roboto,Arial,sans-serif;">
  <h2 style="color:#2563eb;">Popular Marketplace Links</h2>
  <p>Click the buttons below to search directly with filters applied:</p>
  {buttons_html}
</body>
</html>
"""

    # Attach plain text fallback
    msg.attach(MIMEText("Vehicle search results attached.", "plain"))

    # Attach HTML body
    msg.attach(MIMEText(html_body, "html"))

    # Attach HTML report file
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
    except Exception as e:
        print(f"✗ Email failed: {e}")

def generate_html_report(outlander_data, rav4_data):
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
</head>
<body>
<h1>Search Results</h1>
<p>Generated {est_now.strftime('%B %d, %Y')}</p>
<table>
<thead><tr><th>#</th><th>Vehicle</th><th>Mileage</th><th>Price</th><th>Sunroof</th><th>Dealer</th><th>Distance</th><th>Rating</th><th>Link</th><th>Why Ranked</th></tr></thead>
<tbody>{outlander_rows}</tbody>
</table>

<table>
<thead><tr><th>#</th><th>Vehicle</th><th>Mileage</th><th>Price</th><th>Sunroof</th><th>Dealer</th><th>Distance</th><th>Rating</th><th>Link</th><th>Why Ranked</th></tr></thead>
<tbody>{rav4_rows}</tbody>
</table>

</body>
</html>
"""
    return html

def main():
    est_now = get_est_time()
    print("🚗 Starting vehicle search automation...")
    print(f"📅 Run time: {est_now.strftime('%Y-%m-%d %I:%M:%S %p EST')}")

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

if __name__ == '__main__':
    main()
