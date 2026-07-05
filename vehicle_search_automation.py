#!/usr/bin/env python3
"""
Full replacement: vehicle_search_automation.py

Purpose:
- Scrape / assemble search results (placeholder here)
- Build responsive, dealership-grade email HTML
- Ensure "Other Dealers" button appears only at the bottom next to marketplace buttons
- Make dealer names clickable and append prefilter query params when provided
- Generate gatineau_phev_rav4_search_results.html and dealers.html
- Send email via Gmail SMTP when credentials are provided via env vars
"""

import os
import smtplib
import html
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ---------------------------
# Configuration / Environment
# ---------------------------
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")
VIEW_REPORT_URL = os.getenv("VIEW_REPORT_URL", "").strip()
VIEW_DEALERS_URL = os.getenv("VIEW_DEALERS_URL", "").strip()

OUTPUT_REPORT = "gatineau_phev_rav4_search_results.html"
OUTPUT_DEALERS = "dealers.html"

# ---------------------------
# Placeholder data
# Replace this with your scraping output
# Each listing: dict with keys used in the email table
# Each dealer: dict with name, brand, city, distance_km, website, prefilters (optional dict)
# ---------------------------
LISTINGS = [
    {
        "vehicle": "2023 Mitsubishi Outlander PHEV SE",
        "url": "https://example.com/listing/outlander-1",
        "price": "$39,900",
        "mileage": "12,000 km",
        "sunroof": "No",
        "city": "Gatineau, QC",
        "distance_km": 6.5,
        "dealer_name": "Rallye Mitsubishi",
        "dealer_rating": "4.2"
    },
    {
        "vehicle": "2024 Toyota RAV4 Prime XSE",
        "url": "https://example.com/listing/rav4-1",
        "price": "$49,500",
        "mileage": "5,000 km",
        "sunroof": "Yes",
        "city": "Ottawa, ON",
        "distance_km": 11.9,
        "dealer_name": "Bel-Air Toyota",
        "dealer_rating": "4.6"
    },
]

DEALERS = [
    {
        "name": "Toyota Gatineau",
        "brand": "Toyota",
        "city": "Gatineau, QC",
        "distance_km": 2.1,
        "website": "https://www.toyotagatineau.ca",
        # Example prefilter: open dealer site with a search for RAV4 Prime
        "prefilters": {"make": "Toyota", "model": "RAV4+Prime"}
    },
    {
        "name": "Rallye Mitsubishi",
        "brand": "Mitsubishi",
        "city": "Gatineau, QC",
        "distance_km": 6.5,
        "website": "https://www.rallyemitsubishi.ca",
        "prefilters": {"make": "Mitsubishi", "model": "Outlander+PHEV"}
    },
    {
        "name": "Occasion Kadir Dargham",
        "brand": "Independent",
        "city": "Gatineau, QC",
        "distance_km": 4.8,
        "website": "https://www.example-used.ca",
    },
    # Add more dealers as needed...
]

# ---------------------------
# Helpers
# ---------------------------
def build_prefiltered_link(base_url: str, prefilters: dict | None) -> str:
    """
    Append simple query parameters for prefilters to the base_url.
    If base_url already has query params, append with &.
    prefilters values are URL-escaped minimally (spaces -> +).
    """
    if not prefilters:
        return base_url
    # Build query string
    parts = []
    for k, v in prefilters.items():
        # Replace spaces with + and escape minimal characters
        safe_v = str(v).replace(" ", "+")
        parts.append(f"{k}={html.escape(safe_v, quote=True)}")
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{'&'.join(parts)}"

def safe_text(s):
    return html.escape(str(s)) if s is not None else ""

# ---------------------------
# HTML generation
# ---------------------------
def generate_dealers_html(dealers):
    rows = []
    for d in dealers:
        link = build_prefiltered_link(d.get("website", "#"), d.get("prefilters"))
        rows.append(f"""
        <tr>
            <td><a href="{html.escape(link)}" target="_blank" rel="noopener">{html.escape(d.get('name',''))}</a></td>
            <td>{html.escape(d.get('brand',''))}</td>
            <td>{html.escape(d.get('city',''))}</td>
            <td>{html.escape(str(d.get('distance_km','')))} km</td>
        </tr>
        """)
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dealers near Gatineau</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:16px;color:#111}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px;border:1px solid #ddd;text-align:left}}
th{{background:#f4f4f4}}
a{{color:#0b66c3;text-decoration:none}}
a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<h2>Dealers within radius (sorted by distance)</h2>
<p>Click a dealer name to open their website. If available, the link includes prefilters for make/model.</p>
<table>
<thead><tr><th>Dealer</th><th>Brand</th><th>Location</th><th>Distance</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</body>
</html>
"""
    return html_doc

def generate_report_html(listings, generated_at_iso):
    # Build rows grouped by brand (Outlander first, then RAV4)
    outlander_rows = []
    rav4_rows = []
    for l in listings:
        row = f"""
        <tr class="result-row">
            <td class="vehicle"><a href="{html.escape(l['url'])}" target="_blank" rel="noopener">{html.escape(l['vehicle'])}</a></td>
            <td class="details">{html.escape(l['price'])} · {html.escape(l['mileage'])} · Sunroof: {html.escape(l['sunroof'])}</td>
            <td class="location">{html.escape(l['city'])} · {html.escape(str(l['distance_km']))} km</td>
            <td class="dealer">{html.escape(l['dealer_name'])} · {html.escape(l.get('dealer_rating',''))}</td>
        </tr>
        """
        if "Outlander" in l['vehicle'] or "Outlander" in l.get('vehicle',''):
            outlander_rows.append(row)
        else:
            rav4_rows.append(row)

    # Marketplace buttons (example)
    marketplace_buttons = """
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
      <tr>
        <td align="left">
          <a href="https://www.autotrader.ca" style="display:inline-block;padding:8px 12px;background:#0b66c3;color:#fff;text-decoration:none;border-radius:4px;margin-right:8px;">AutoTrader</a>
          <a href="https://www.kijiji.ca" style="display:inline-block;padding:8px 12px;background:#ff6f00;color:#fff;text-decoration:none;border-radius:4px;margin-right:8px;">Kijiji</a>
          <a href="https://www.carfax.ca" style="display:inline-block;padding:8px 12px;background:#333;color:#fff;text-decoration:none;border-radius:4px;">Carfax</a>
        </td>
      </tr>
      <tr style="margin-top:8px;">
        <td align="left" style="padding-top:8px;">
          <a href="https://www.facebook.com/marketplace" style="display:inline-block;padding:8px 12px;background:#1877f2;color:#fff;text-decoration:none;border-radius:4px;margin-right:8px;">Facebook Marketplace</a>
          <!-- Other Dealers button will be placed next to Facebook Marketplace in the email footer -->
        </td>
      </tr>
    </table>
    """

    # Other Dealers button logic: if VIEW_DEALERS_URL set, link to it; else link to '#' and instruct to open attached file
    if VIEW_DEALERS_URL:
        other_dealers_href = VIEW_DEALERS_URL
        other_dealers_note = ""
    else:
        other_dealers_href = "#"
        other_dealers_note = "<p style='font-size:13px;color:#666;margin:8px 0 0;'>To view the full dealers list, open the attached <strong>dealers.html</strong>.</p>"

    other_dealers_button = f"""
    <a href="{html.escape(other_dealers_href)}" style="display:inline-block;padding:8px 12px;background:#6c757d;color:#fff;text-decoration:none;border-radius:4px;margin-left:8px;">Other Dealers</a>
    {other_dealers_note}
    """

    # Email HTML (table-based layout, responsive stacking)
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gatineau PHEV / RAV4 Search Results</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:0;padding:0;color:#111}}
.container{{max-width:700px;margin:0 auto;padding:16px}}
.header{{padding:12px 0;border-bottom:1px solid #eee}}
.title{{font-size:20px;margin:0 0 4px}}
.meta{{font-size:13px;color:#666;margin:0}}
.table{{width:100%;border-collapse:collapse;margin-top:12px}}
.table th{{background:#f4f4f4;padding:8px;text-align:left;border:1px solid #e6e6e6}}
.table td{{padding:8px;border:1px solid #e6e6e6;vertical-align:top}}
.vehicle a{{color:#0b66c3;text-decoration:none}}
.vehicle a:hover{{text-decoration:underline}}
/* Responsive: stack rows on narrow screens */
@media only screen and (max-width:520px) {{
  .table, .table thead, .table tbody, .table th, .table td, .table tr {{display:block;width:100%}}
  .table thead {{display:none}}
  .table tr {{margin-bottom:12px;border:1px solid #e6e6e6;padding:8px}}
  .table td {{display:block;border:none;padding:6px 0}}
  .table td:before {{content:attr(data-label);font-weight:bold;display:inline-block;width:110px}}
}}
.footer{{margin-top:18px;padding-top:12px;border-top:1px solid #eee;font-size:13px;color:#666}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="title">Gatineau PHEV / RAV4 Search Results</div>
    <div class="meta">Generated: {html.escape(generated_at_iso)}</div>
  </div>

  <div class="summary" style="margin-top:12px;">
    <p style="margin:0 0 8px;">Summary: Results for Mitsubishi Outlander PHEV and Toyota RAV4 Prime within configured radius.</p>
    <p style="margin:0 0 12px;">
      <a href="{html.escape(VIEW_REPORT_URL) if VIEW_REPORT_URL else '#'}" style="display:inline-block;padding:10px 14px;background:#0b66c3;color:#fff;text-decoration:none;border-radius:4px;">View Full Report</a>
      {"<span style='margin-left:10px;color:#666;'>Open attached report if the button does not link.</span>" if not VIEW_REPORT_URL else ""}
    </p>
  </div>

  <!-- Outlander section -->
  <h3 style="margin:12px 0 6px;">Outlander PHEV</h3>
  <table class="table" role="presentation">
    <thead><tr><th>Vehicle</th><th>Details</th><th>Location</th><th>Dealer</th></tr></thead>
    <tbody>
    {''.join(outlander_rows) if outlander_rows else '<tr><td colspan="4">No Outlander results</td></tr>'}
    </tbody>
  </table>

  <!-- RAV4 section -->
  <h3 style="margin:12px 0 6px;">RAV4 Prime</h3>
  <table class="table" role="presentation">
    <thead><tr><th>Vehicle</th><th>Details</th><th>Location</th><th>Dealer</th></tr></thead>
    <tbody>
    {''.join(rav4_rows) if rav4_rows else '<tr><td colspan="4">No RAV4 results</td></tr>'}
    </tbody>
  </table>

  <!-- Marketplace buttons and Other Dealers button (Other Dealers only in footer area) -->
  <div style="margin-top:14px;">
    {marketplace_buttons}
    <div style="margin-top:8px;">
      {other_dealers_button}
    </div>
  </div>

  <div class="footer">
    <div>Next update: every 3 days. Generated at {html.escape(generated_at_iso)}</div>
  </div>
</div>
</body>
</html>
"""
    return html_doc

# ---------------------------
# Write files
# ---------------------------
def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Wrote {path}")

# ---------------------------
# Email sending
# ---------------------------
def send_email(subject: str, html_body: str, attachments: list[str]):
    if not (GMAIL_ADDRESS and GMAIL_PASSWORD and RECIPIENT_EMAIL):
        print("Email credentials or recipient not set; skipping send.")
        return

    msg = MIMEMultipart("mixed")
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject

    # Alternative part (plain + html)
    alt = MIMEMultipart("alternative")
    plain_text = "Please open the attached HTML report for full details."
    alt.attach(MIMEText(plain_text, "plain"))
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    # Attach generated files
    for path in attachments:
        try:
            with open(path, "rb") as f:
                part = MIMEText(f.read().decode("utf-8"), "html", "utf-8")
                part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
                msg.attach(part)
        except Exception as e:
            print(f"Failed to attach {path}: {e}")

    # Send via Gmail SMTP
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
        server.ehlo()
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        server.quit()
        print("Email sent to", RECIPIENT_EMAIL)
    except Exception as e:
        print("SMTP send failed:", e)

# ---------------------------
# Main
# ---------------------------
def main():
    generated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    # Generate dealers.html
    dealers_html = generate_dealers_html(DEALERS)
    write_file(OUTPUT_DEALERS, dealers_html)

    # Generate main report HTML
    report_html = generate_report_html(LISTINGS, generated_at)
    write_file(OUTPUT_REPORT, report_html)

    # Send email with attachments if credentials present
    subject = f"Gatineau PHEV / RAV4 Search Results — {generated_at}"
    send_email(subject, report_html, [OUTPUT_REPORT, OUTPUT_DEALERS])

if __name__ == "__main__":
    main()
