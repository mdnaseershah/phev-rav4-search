# 🚗 Vehicle Search Automation

Automatically searches for **Mitsubishi Outlander PHEV** and **Toyota RAV4 Prime** listings near Gatineau, QC every 3 days. Sends a ranked email with direct links to actual listings.

## How it works

1. A **GitHub Actions workflow** runs automatically every 3 days at **7:00 AM Eastern**.
2. It scrapes **6 sources** for matching vehicles:
   - **AutoTrader.ca** (via Playwright browser rendering)
   - **CarGurus.ca** (via Playwright browser rendering)
   - **Kijiji.ca** (web + RSS feed)
   - **Clutch.ca** (via Playwright)
   - **6 local dealer websites** (direct probing)
3. It **ranks all listings** by best price-to-value (lowest price wins, mileage penalty, sunroof bonus).
4. It **emails you** a clean HTML table with clickable links to each listing.
5. Results are also published to **GitHub Pages** for viewing in a browser.

## Vehicle criteria

| Vehicle | Years | Max Price | Max Mileage |
|:--------|:------|:----------|:------------|
| **Mitsubishi Outlander PHEV** | 2022 | $32,000 CAD | 70,000 km |
| **Mitsubishi Outlander PHEV** | 2023 | $32,000 CAD | 100,000 km |
| **Toyota RAV4 Prime** | 2021–2023 | $42,000 CAD | 120,000 km |

## Setup

### 1. Fork or clone this repository

```bash
git clone <your-repo-url>
cd vehicle-search-automation
