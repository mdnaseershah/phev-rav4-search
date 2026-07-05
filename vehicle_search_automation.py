#!/usr/bin/env python3
"""
Gatineau PHEV/RAV4 Search Automation
Generates an HTML report and emails a dealership-grade, responsive summary.
Also generates a dealers.html file and attaches both files to the email.
"""

import smtplib
import os
from datetime import datetime
import pytz
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.encoders import encode_base64

# -------------------------
# Configuration
# -------------------------
GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS')
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
GATINEAU_RADIUS = 400
BUDGET = 28000

# If you host the HTML report somewhere, set these to the hosted URLs.
# Otherwise leave empty and recipients will be instructed to open the attached files.
VIEW_REPORT_URL = ""   # e.g., "https://yourdomain.com/gatineau_phev_rav4_search_results.html"
VIEW_DEALERS_URL = ""  # e.g., "https://yourdomain.com/dealers.html"

# EST timezone
EST = pytz.timezone('US/Eastern')

# Popular marketplace links
# NOTE: AutoTrader long param link sometimes returns 404 in some clients; use a simpler search URL.
POPULAR_LINKS = [
    {
        "name": "AutoTrader.ca",
        "url": "https://www.autotrader.ca/cars/mitsubishi/outlander-phev/"  # simpler, reliable landing page
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

# -------------------------
# Helpers
# -------------------------
def get_est_time():
    return datetime.now(EST)

def organize_by_year_and_budget(vehicle_list):
    within_budget = {}
    above_budget = {}
    for vehicle in vehicle_list:
        year = vehicle.get('year', 'Unknown')
        try:
            price = int(str(vehicle.get('price', '0')).replace(',', '').replace('$', '').strip())
        except Exception:
            price = 0
        if price <= BUDGET:
            within_budget.setdefault(year, []).append(vehicle)
        else:
            above_budget.setdefault(year, []).append(vehicle)
    return within_budget, above_budget

def format_vehicle_list(vehicle_list):
    text = ""
    for i, vehicle in enumerate(vehicle_list, 1):
        text += f"\n  {i}. {vehicle.get('year','')} {vehicle.get('make','')} {vehicle.get('model','')}\n"
        text += f"     Price: ${vehicle.get('price','')} | Mileage: {vehicle.get('mileage','')} km | Sunroof: {vehicle.get('sunroof','')}\n"
        text += f"     Location: {vehicle.get('city','')}, {vehicle.get('province','')} | Distance: {vehicle.get('distance','')} km\n"
        text += f"     Dealer: {vehicle.get('rating','')}\n"
        text += f"     Link: {vehicle.get('link','')}\n"
    return text

def format_vehicle_list_html(vehicle_list):
    """Return HTML rows. Vehicle name includes the link (no separate Action column)."""
    html = ""
    for i, vehicle in enumerate(vehicle_list, 1):
        name = f"{vehicle.get('year','')} {vehicle.get('make','')} {vehicle.get('model','')}"
        link = vehicle.get('link', '#')
        price = vehicle.get('price', '')
        mileage = vehicle.get('mileage', '')
        sunroof = vehicle.get('sunroof', '')
        city = vehicle.get('city', '')
        province = vehicle.get('province', '')
        distance = vehicle.get('distance', '')
        dealer_rating = vehicle.get('rating', '')
        html += (
            "<tr>"
            f"<td style=\"padding:10px;border-bottom:1px solid #e5e7eb;\">"
            f"<a href=\"{link}\" style=\"color:#0b5fff;text-decoration:none;font-weight:700;\">{name}</a>"
            "</td>"
            f"<td style=\"padding:10px;border-bottom:1px solid #e5e7eb;\">${price}<br>{mileage} km<br>Sunroof: {sunroof}</td>"
            f"<td style=\"padding:10px;border-bottom:1px solid #e5e7eb;\">{city}, {province}<br>{distance} km</td>"
            f"<td style=\"padding:10px;border-bottom:1px solid #e5e7eb;text-align:center;\">{dealer_rating}</td>"
            "</tr>"
        )
    return html

def build_buttons_html():
    """Simple, clean button grid (no extra grey container)."""
    return (
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" style=\"margin-top:12px;\">"
        "<tr>"
        f"<td align=\"center\" width=\"33%\" style=\"padding:6px;\"><a href=\"{POPULAR_LINKS[0]['url']}\" style=\"display:block;background:#2563eb;color:#ffffff;padding:10px 12px;border-radius:8px;text-decoration:none;font-weight:600;\">{POPULAR_LINKS[0]['name']}</a></td>"
        f"<td align=\"center\" width=\"33%\" style=\"padding:6px;\"><a href=\"{POPULAR_LINKS[1]['url']}\" style=\"display:block;background:#2563eb;color:#ffffff;padding:10px 12px;border-radius:8px;text-decoration:none;font-weight:600;\">{POPULAR_LINKS[1]['name']}</a></td>"
        f"<td align=\"center\" width=\"33%\" style=\"padding:6px;\"><a href=\"{POPULAR_LINKS[2]['url']}\" style=\"display:block;background:#2563eb;color:#ffffff;padding:10px 12px;border-radius:8px;text-decoration:none;font-weight:600;\">{POPULAR_LINKS[2]['name']}</a></td>"
        "</tr>"
        "<tr>"
        f"<td align=\"center\" width=\"33%\" style=\"padding:6px;\"><a href=\"{POPULAR_LINKS[3]['url']}\" style=\"display:block;background:#2563eb;color:#ffffff;padding:10px 12px;border-radius:8px;text-decoration:none;font-weight:600;\">{POPULAR_LINKS[3]['name']}</a></td>"
        f"<td align=\"center\" width=\"33%\" style=\"padding:6px;\"><a href=\"{POPULAR_LINKS[4]['url']}\" style=\"display:block;background:#2563eb;color:#ffffff;padding:10px 12px;border-radius:8px;text-decoration:none;font-weight:600;\">{POPULAR_LINKS[4]['name']}</a></td>"
        "<td width=\"33%\" style=\"padding:6px;\"></td>"
        "</tr>"
        "</table>"
    )

# -------------------------
# Email builder & sender
# -------------------------
def send_email(html_content, dealers_html_content, outlander_list, rav4_list):
    est_now = get_est_time()
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Gatineau PHEV / RAV4 Prime Search Results - {est_now.strftime('%B %d, %Y')}"
    msg['From'] = GMAIL_ADDRESS or "no-reply@example.com"
    msg['To'] = RECIPIENT_EMAIL or "recipient@example.com"

    # Organize results
    outlander_within, outlander_above = organize_by_year_and_budget(outlander_list)
    rav4_within, rav4_above = organize_by_year_and_budget(rav4_list)

    # Plain text fallback
    body_text = f"GATINEAU PHEV / RAV4 PRIME SEARCH RESULTS\n\nGenerated: {est_now.strftime('%B %d, %Y at %I:%M %p EST')}\nRadius: {GATINEAU_RADIUS} km\nBudget: ${BUDGET:,} CAD\n\n"
    if outlander_within:
        for year in sorted(outlander_within.keys(), reverse=True):
            body_text += f"\nOutlander {year}:\n"
            body_text += format_vehicle_list(outlander_within[year])
    else:
        body_text += "\nNo Outlander listings within budget.\n"

    if outlander_above:
        body_text += "\nOutlander - Above Budget:\n"
        for year in sorted(outlander_above.keys(), reverse=True):
            body_text += format_vehicle_list(outlander_above[year])

    body_text += "\n\nRAV4 Prime:\n"
    if rav4_within:
        for year in sorted(rav4_within.keys(), reverse=True):
            body_text += f"\nRAV4 {year}:\n"
            body_text += format_vehicle_list(rav4_within[year])
    else:
        body_text += "\nNo RAV4 listings within budget.\n"

    if rav4_above:
        body_text += "\nRAV4 - Above Budget:\n"
        for year in sorted(rav4_above.keys(), reverse=True):
            body_text += format_vehicle_list(rav4_above[year])

    body_text += "\n\nPopular marketplace links:\n"
    for i, link in enumerate(POPULAR_LINKS, 1):
        body_text += f"{i}. {link['name']}: {link['url']}\n"

    body_text += "\nInteractive HTML report attached: gatineau_phev_rav4_search_results.html\n"
    body_text += "Dealers list attached: dealers.html\n"
    body_text += "Open the attached files to view the full report and dealers list in your browser.\n"

    # Build HTML parts
    outlander_within_flat = [v for year in sorted(outlander_within.keys(), reverse=True) for v in outlander_within[year]]
    outlander_above_flat = [v for year in sorted(outlander_above.keys(), reverse=True) for v in outlander_above[year]]
    rav4_within_flat = [v for year in sorted(rav4_within.keys(), reverse=True) for v in rav4_within[year]]
    rav4_above_flat = [v for year in sorted(rav4_above.keys(), reverse=True) for v in rav4_above[year]]

    outlander_within_html = format_vehicle_list_html(outlander_within_flat) if outlander_within_flat else '<tr><td colspan="4" style="padding:12px;text-align:center;color:#6b7280;">No vehicles found within budget.</td></tr>'
    outlander_above_html = format_vehicle_list_html(outlander_above_flat) if outlander_above_flat else ''
    rav4_within_html = format_vehicle_list_html(rav4_within_flat) if rav4_within_flat else '<tr><td colspan="4" style="padding:12px;text-align:center;color:#6b7280;">No vehicles found within budget.</td></tr>'
    rav4_above_html = format_vehicle_list_html(rav4_above_flat) if rav4_above_flat else ''

    buttons_html = build_buttons_html()

    # Build above-budget sections safely
    outlander_above_section = ""
    if outlander_above_html.strip():
        outlander_above_section = (
            "<details>"
            f"<summary>Above Budget (&gt; ${BUDGET:,})</summary>"
            "<table role=\"presentation\">"
            "<thead><tr><th>Vehicle</th><th>Details</th><th>Location</th><th>Dealer</th></tr></thead>"
            "<tbody>"
            f"{outlander_above_html}"
            "</tbody></table></details>"
        )

    rav4_above_section = ""
    if rav4_above_html.strip():
        rav4_above_section = (
            "<details>"
            f"<summary>Above Budget (&gt; ${BUDGET:,})</summary>"
            "<table role=\"presentation\">"
            "<thead><tr><th>Vehicle</th><th>Details</th><th>Location</th><th>Dealer</th></tr></thead>"
            "<tbody>"
            f"{rav4_above_html}"
            "</tbody></table></details>"
        )

    view_report_href = VIEW_REPORT_URL if VIEW_REPORT_URL else "#"
    view_dealers_href = VIEW_DEALERS_URL if VIEW_DEALERS_URL else "#"

    # Final HTML body (single page: Outlander then RAV4)
    html_body = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>"
        "@media (prefers-color-scheme: dark) { body { background:#0b1120; color:#e5e7eb; } .container { background:#0f172a; } .header { background: linear-gradient(135deg,#1e40af,#1e3a8a); color:#fff; } th { background:#0b1220; color:#cbd5e1; } td { color:#e2e8f0; } .view-report-btn { background:#059669; color:#fff; } }"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:0;padding:18px;background:#f3f4f6;color:#111827}"
        ".container{max-width:920px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 8px 24px rgba(2,6,23,0.08)}"
        ".header{padding:20px;text-align:center;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff}"
        ".header h1{margin:0;font-size:20px}.header p{margin:6px 0 0;font-size:13px;opacity:.95}"
        ".content{padding:18px}.section{margin-bottom:22px}.section-title{font-size:16px;font-weight:700;margin:0 0 8px;border-bottom:2px solid #e5e7eb;padding-bottom:6px}"
        ".section-subtitle{color:#6b7280;margin:6px 0 12px;font-size:13px}"
        "table{width:100%;border-collapse:collapse;margin-top:8px}thead tr th{padding:10px;font-size:11px;text-transform:uppercase;color:#6b7280;border-bottom:1px solid #e5e7eb;background:#f3f4f6}tbody tr td{padding:10px;border-bottom:1px solid #e5e7eb;font-size:13px;vertical-align:top}"
        "@media only screen and (max-width:520px){thead{display:none}table,tbody,tr,td{display:block;width:100%}tbody tr{margin-bottom:12px;border:1px solid #e5e7eb;border-radius:8px;padding:8px}td{border:none;padding:8px 10px}td:first-child{font-weight:700;color:#0b5fff}}"
        ".view-report-btn{display:inline-block;padding:10px 16px;background:#16a34a;color:#fff;text-decoration:none;border-radius:999px;font-weight:700}"
        ".market-btn{display:inline-block;padding:10px 14px;background:#2563eb;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;margin:6px 6px 0 0}"
        ".footer{padding:12px 18px;font-size:12px;color:#6b7280;border-top:1px solid #e5e7eb;text-align:center}"
        "</style></head><body>"
        "<div class='container'>"
        "<div class='header'><h1>Gatineau PHEV / RAV4 Prime Search Results</h1>"
        f"<p>Generated {est_now.strftime('%B %d, %Y at %I:%M %p EST')} · Radius {GATINEAU_RADIUS} km · Budget ${BUDGET:,} CAD</p></div>"
        "<div class='content'>"
        "<div class='section'><div class='section-title'>Summary</div>"
        "<div class='section-subtitle'>Full HTML report and dealers list are attached. Open the attachments to view the full pages in your browser.</div>"
        f"<a class='view-report-btn' href='{view_report_href}'>View Full Report</a> "
        f"<a class='view-report-btn' href='{view_dealers_href}' style='background:#2563eb;margin-left:8px;'>Other Dealers</a>"
        "</div>"
        "<div class='section'><div class='section-title'>Mitsubishi Outlander PHEV</div>"
        "<details open><summary>Within Budget (≤ ${budget})</summary>"
        "<table role='presentation'><thead><tr><th>Vehicle</th><th>Details</th><th>Location</th><th>Dealer</th></tr></thead><tbody>"
    ).replace("${budget}", f"{BUDGET:,}")  # safe replacement for budget in the string

    # append outlander within rows
    html_body += outlander_within_html
    html_body += "</tbody></table></details>"
    html_body += outlander_above_section

    # RAV4 section
    html_body += "<div class='section'><div class='section-title'>Toyota RAV4 Prime</div>"
    html_body += "<details open><summary>Within Budget (≤ ${budget})</summary><table role='presentation'><thead><tr><th>Vehicle</th><th>Details</th><th>Location</th><th>Dealer</th></tr></thead><tbody>".replace("${budget}", f"{BUDGET:,}")
    html_body += rav4_within_html
    html_body += "</tbody></table></details>"
    html_body += rav4_above_section

    # Popular links and buttons
    html_body += "<div class='section'><div class='section-title'>Popular Marketplace Links</div><div class='section-subtitle'>Tap or click to open filtered searches.</div>"
    html_body += buttons_html
    # Add Other Dealers button again near bottom for convenience (links to hosted dealers page or attached file)
    html_body += f"<div style='margin-top:12px;'><a class='market-btn' href='{view_dealers_href}'>Other Dealers</a></div>"
    html_body += "</div>"  # close section
    html_body += f"<div class='footer'>Automated every 3 days · HTML report attached · {est_now.strftime('%Y-%m-%d %I:%M %p EST')}</div>"
    html_body += "</div></body></html>"

    # Attach plain text and HTML
    msg.attach(MIMEText(body_text, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    # Attach the standalone HTML report file
    report_filename = 'gatineau_phev_rav4_search_results.html'
    attachment_report = MIMEBase('application', 'octet-stream')
    attachment_report.set_payload(html_content.encode('utf-8'))
    encode_base64(attachment_report)
    attachment_report.add_header('Content-Disposition', f'attachment; filename={report_filename}')
    msg.attach(attachment_report)

    # Attach dealers.html
    dealers_filename = 'dealers.html'
    attachment_dealers = MIMEBase('application', 'octet-stream')
    attachment_dealers.set_payload(dealers_html_content.encode('utf-8'))
    encode_base64(attachment_dealers)
    attachment_dealers.add_header('Content-Disposition', f'attachment; filename={dealers_filename}')
    msg.attach(attachment_dealers)

    # Send email
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

# -------------------------
# HTML report generator (attachment)
# -------------------------
def generate_html_report(outlander_data, rav4_data):
    est_now = get_est_time()

    links_html = ''.join([
        f'<a class="market-card" href="{link["url"]}" target="_blank" rel="noopener" style="display:inline-block;margin:6px;padding:10px 12px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;color:#2563eb;text-decoration:none;font-weight:700;">{link["name"]}</a>'
        for link in POPULAR_LINKS
    ])

    outlander_rows = ''.join([
        f"""<tr>
            <td>{i+1}</td>
            <td><a href="{vehicle['link']}" target="_blank" rel="noopener" style="color:#0b5fff;font-weight:700;text-decoration:none;">{vehicle['year']} {vehicle['make']} {vehicle['model']}</a></td>
            <td>{vehicle['mileage']} km</td>
            <td>${vehicle['price']}</td>
            <td>{vehicle['sunroof']}</td>
            <td>{vehicle['dealer']}<br><span style="color:#64748b;">{vehicle['city']}, {vehicle['province']}</span></td>
            <td>{vehicle['distance']} km</td>
            <td style="text-align:center;">{vehicle['rating']}</td>
            <td style="color:#64748b;">{vehicle['why_ranked']}</td>
        </tr>"""
        for i, vehicle in enumerate(outlander_data)
    ])

    rav4_rows = ''.join([
        f"""<tr>
            <td>{i+1}</td>
            <td><a href="{vehicle['link']}" target="_blank" rel="noopener" style="color:#0b5fff;font-weight:700;text-decoration:none;">{vehicle['year']} {vehicle['make']} {vehicle['model']}</a></td>
            <td>{vehicle['mileage']} km</td>
            <td>${vehicle['price']}</td>
            <td>{vehicle['sunroof']}</td>
            <td>{vehicle['dealer']}<br><span style="color:#64748b;">{vehicle['city']}, {vehicle['province']}</span></td>
            <td>{vehicle['distance']} km</td>
            <td style="text-align:center;">{vehicle['rating']}</td>
            <td style="color:#64748b;">{vehicle['why_ranked']}</td>
        </tr>"""
        for i, vehicle in enumerate(rav4_data)
    ])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Gatineau PHEV / RAV4 Prime Search Results</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;background:#f8fafc;color:#0f172a;padding:20px}}
header{{background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;padding:18px;border-radius:10px}}
h1{{margin:0;font-size:20px}}
.market-grid{{margin:14px 0}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden}}
th,td{{padding:10px;border-bottom:1px solid #e6eef8;font-size:13px}}
th{{background:#f1f5f9;color:#64748b;text-transform:uppercase;font-size:11px}}
a{{color:#0b5fff;text-decoration:none}}
.small{{color:#64748b;font-size:12px}}
</style>
</head>
<body>
<header>
  <h1>Gatineau PHEV / RAV4 Prime Search Results</h1>
  <p class="small">Generated {est_now.strftime('%B %d, %Y at %I:%M %p EST')} · Radius {GATINEAU_RADIUS} km</p>
</header>

<section>
  <h2>Mitsubishi Outlander PHEV (2020–2024)</h2>
  <div class="market-grid">{links_html}</div>
  <table>
    <thead><tr><th>#</th><th>Vehicle</th><th>Mileage</th><th>Price</th><th>Sunroof</th><th>Dealer / Location</th><th>Distance</th><th>Dealer</th><th>Why Ranked</th></tr></thead>
    <tbody>{outlander_rows}</tbody>
  </table>
</section>

<section>
  <h2>Toyota RAV4 Prime (2020–2024)</h2>
  <table>
    <thead><tr><th>#</th><th>Vehicle</th><th>Mileage</th><th>Price</th><th>Sunroof</th><th>Dealer / Location</th><th>Distance</th><th>Dealer</th><th>Why Ranked</th></tr></thead>
    <tbody>{rav4_rows}</tbody>
  </table>
</section>

</body>
</html>
"""
    return html

# -------------------------
# Dealers page generator
# -------------------------
def generate_dealers_page(dealers_list):
    """Generate a simple dealers.html listing (used by Other Dealers button)."""
    rows = ""
    for i, d in enumerate(dealers_list, 1):
        rows += f"<tr><td>{i}</td><td>{d.get('name','')}</td><td>{d.get('city','')}, {d.get('province','')}</td><td>{d.get('phone','')}</td><td>{d.get('website','')}</td></tr>"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Dealers</title>
<style>body{{font-family:Arial,Helvetica,sans-serif;padding:20px;background:#f8fafc}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #e6eef8}}th{{background:#f1f5f9;text-transform:uppercase;color:#64748b}}</style>
</head>
<body>
<h1>Dealers</h1>
<p>List of dealers referenced in the report.</p>
<table>
<thead><tr><th>#</th><th>Dealer</th><th>Location</th><th>Phone</th><th>Website</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""
    return html

# -------------------------
# Main
# -------------------------
def main():
    est_now = get_est_time()
    print("🚗 Starting vehicle search automation...")
    print(f"📅 Run time: {est_now.strftime('%Y-%m-%d %I:%M:%S %p EST')}")

    # Placeholder data (replace with scraping results)
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
            'rating': '5.0/5',
            'link': 'https://www.cargurus.ca/details/428782812',
            'why_ranked': 'Newest year at this price, sunroof confirmed'
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
            'rating': '4.3/5',
            'link': 'https://www.autotrader.ca/',
            'why_ranked': 'Low mileage, local dealer'
        }
    ]

    # Example dealers list for dealers.html (replace with real dealer data from scraping)
    dealers_list = [
        {'name': 'Mitsubishi Vaudreuil', 'city': 'Vaudreuil-Dorion', 'province': 'QC', 'phone': '(450) 123-4567', 'website': 'https://www.mitsubishi-vaudreuil.ca'},
        {'name': 'Toyota Gatineau', 'city': 'Gatineau', 'province': 'QC', 'phone': '(819) 123-4567', 'website': 'https://www.toyotagatineau.ca'}
    ]

    # Generate attachment HTML files
    html_report = generate_html_report(outlander_data, rav4_data)
    with open('gatineau_phev_rav4_search_results.html', 'w', encoding='utf-8') as f:
        f.write(html_report)
    print("✓ HTML report generated: gatineau_phev_rav4_search_results.html")

    dealers_html = generate_dealers_page(dealers_list)
    with open('dealers.html', 'w', encoding='utf-8') as f:
        f.write(dealers_html)
    print("✓ Dealers page generated: dealers.html")

    # Send email (if credentials present)
    if GMAIL_ADDRESS and GMAIL_PASSWORD and RECIPIENT_EMAIL:
        send_email(html_report, dealers_html, outlander_data, rav4_data)
    else:
        print("⚠ Email credentials not set. Skipping email send.")
        print("  Set GMAIL_ADDRESS, GMAIL_PASSWORD, and RECIPIENT_EMAIL environment variables")

if __name__ == '__main__':
    main()
