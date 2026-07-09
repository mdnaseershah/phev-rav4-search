# 🚗 Vehicle Search Automation

Automatically searches **nationwide (Canada-wide)** for **Mitsubishi Outlander PHEV** and **Toyota RAV4 Prime** listings every 3 days. Sends a ranked email with direct links to actual listings.

## How it works

1. A **GitHub Actions workflow** runs automatically every 3 days at **7:00 AM Eastern**.
2. It scrapes matching vehicles from these sources, mostly via each site's **structured data endpoint** (internal JSON APIs / embedded page JSON) rather than headless rendering:
   - **AutoTrader.ca** (internal search JSON API; Playwright only as a fallback)
   - **CarGurus.ca** (internal `searchResults` JSON API, using the `makeModelTrimPaths` filter)
   - **Kijiji.ca** (RSS feed + web page)
   - **Clutch.ca** (embedded `__NEXT_DATA__` JSON)
   - **Local dealer websites** (~140 Toyota/Honda/Mitsubishi dealers across QC/ON, from `dealer_sites.json`) — read via schema.org JSON-LD + strict anchor probing. Probed politely (a few hosts at a time, sequential per host, short pauses) so no site is hammered; sites that render inventory only via JavaScript can't be read this way and are skipped.
   - *(Facebook Marketplace is a manual quick-link — it needs a logged-in session.)*
   - All searches are **nationwide**: CarGurus `distance=50000`, AutoTrader `Proximity: -1` (National), Kijiji all-Canada location `l0`.
3. It **ranks all listings** by best price-to-value (lowest price wins, mileage penalty, sunroof bonus).
4. It **emails you** the results grouped by model year and region, with clickable links to each listing:
   - **2023–2024** box → an **Alberta** table (split out because Alberta's 5% GST usually makes the same car cheaper) and an **Ontario, Quebec & Other** table (everything else, with a Province column). Nothing is dropped.
   - **2022** box → one table with a **Province** column covering all provinces.
   - Within each table, listings with a known province rank first (by value); any with an undetectable province are grouped at the bottom.
   - **Listings you haven't seen before are marked 🟢 NEW**, with a count at the top — so each email highlights what actually changed since last time (tracked in `seen_listings.json`).
   - A **source-health footer** shows how many listings each source returned this run; a `0` means that site was blocked/rate-limited that run (common for AutoTrader/CarGurus from cloud IPs), not that nothing exists.
5. Results are also published to **GitHub Pages** for viewing in a browser.

You can **change the budgets/years without editing code**: on GitHub go to **Actions → Vehicle Search → Run workflow**, and fill in any of the optional criteria fields (Outlander/RAV4 year/price/mileage). Leave them blank to use the defaults below.

## Vehicle criteria

All searches are nationwide across Canada; the email then buckets 2023–2024 results by region (Alberta vs everything else).

| Vehicle | Years | Max Price | Max Mileage |
|:--------|:------|:----------|:------------|
| **Mitsubishi Outlander PHEV** | 2022 | $30,000 CAD | 70,000 km |
| **Mitsubishi Outlander PHEV** | 2023 | $32,500 CAD | 70,000 km |
| **Mitsubishi Outlander PHEV** | 2024 | $32,500 CAD | 70,000 km |
| **Toyota RAV4 Prime** (a.k.a. RAV4 Plug-in Hybrid) | 2022–2023 | $35,000 CAD | 120,000 km |

## Setup

### 1. Fork or clone this repository

```bash
git clone <your-repo-url>
cd vehicle-search-automation
