# CLAUDE.md

This file documents the current (V3) behavior of this repository — for AI assistants and human contributors.

## What this repository does

A self-contained GitHub Actions automation that searches for plug-in hybrid vehicles (Mitsubishi Outlander PHEV and Toyota RAV4 Prime) across multiple Canadian marketplaces every 3 days at 7 AM Eastern. Each run:

1. **Scrapes** AutoTrader.ca, CarGurus.ca, Kijiji (web + RSS), Clutch.ca, Facebook Marketplace, and local dealer websites for matching listings.
2. **Ranks** all found listings by price-to-value (lowest price wins, with mileage penalty and sunroof bonus).
3. **Generates** two HTML files: an email body (`gatineau_phev_rav4_search_results.html`) and a dealer list (`dealers.html`).
4. **Emails** the ranked results to one recipient via Gmail SMTP.
5. **Commits** the HTML files back to the repo and publishes them to GitHub Pages.

There is no database, no persistent state, and no web server — a single Python script invoked by a scheduled workflow.

## Repository layout

- `vehicle_search_automation.py` — the entire application: scraping, HTML generation, email sending (the only Python file).
- `.github/workflows/search.yml` — the GitHub Actions workflow (cron schedule + manual dispatch).
- `dealers.json` — list of local dealers (name, brand, city, distance_km, website). Used for the dealer HTML page and as probe targets.
- `dealers.html` — generated output (dealers table). Overwritten every run, committed back.
- `gatineau_phev_rav4_search_results.html` — generated output (email body). Overwritten every run, committed back.
- `requirements.txt` — Python dependencies.
- `README.md` — user-facing overview.

## Execution flow (`main()`)

1. Compute `est_now = datetime.now(EST)` (pytz handles EDT/EST correctly).
2. **DST-safe schedule guard:** Read `GITHUB_EVENT_NAME` env var (set by workflow). If the run is NOT a manual/local run (i.e. not `workflow_dispatch` or empty) AND the current Eastern hour is not 7, the script exits immediately without doing anything. This allows two cron triggers (11 UTC for EDT, 12 UTC for EST) to both target 7 AM Eastern, with only one actually executing.
3. If `ENABLE_SCRAPE=1`, call `scrape_and_populate_listings()` — collects ALL matching listings from all sources into the global `ALL_LISTINGS` list.
4. Generate `dealers.html` and the email HTML; write both to disk.
5. Send email via `send_email()` (skipped if credentials are missing).
6. The workflow then commits the HTML files back to `main` and deploys to `gh-pages`.

## Key data structures

- `WANTED_VEHICLES` — list of 2 dicts, each with `vehicle`, `make`, `model`, `year_min`, `year_max`, `max_price`, `max_mileage`, `aliases`, and `urls` (pre-built search URLs for each marketplace plus a `kijiji_rss` URL). Currently: Mitsubishi Outlander PHEV (2022–2023, max $32,000, max 70,000 km) and Toyota RAV4 Prime (2021–2023, max $42,000, max 120,000 km).
- `ALL_LISTINGS` — dynamic list populated each run by `scrape_and_populate_listings()`. Each entry is a dict with `url`, `title`, `year`, `trim`, `price`, `mileage`, `sunroof`, `vehicle`, and optionally `is_fallback`. Starts empty every run.
- `_listing_value_score()` — ranking function: lower score = better value. Uses (over_cap, price + mileage_penalty + sunroof_bonus, km) as a tuple for sorting. Over-cap listings (mileage > max) are pushed to the bottom.
- `DEALERS` — fallback list (2 entries) used only if `dealers.json` is missing/fails to load. Normally `dealers.json` (6 entries) is used.

## Search / scraping logic

`scrape_and_populate_listings()` runs per vehicle in this order, **collecting from ALL sources** (not stopping at first success):

1. **Kijiji RSS** — Structured XML feed parsed with BeautifulSoup's XML parser. Returns price, mileage, year, and direct listing URL. Most reliable source.
2. **AutoTrader.ca** — Uses **Playwright** with `wait_until='domcontentloaded'` (NOT `networkidle` — which hangs on heavy JS sites). Dismisses cookie banners, waits for listing elements to appear. Parses the rendered HTML with multiple selector strategies.
3. **CarGurus.ca** — Same Playwright approach as AutoTrader.
4. **Kijiji Web** — Plain `requests` + BeautifulSoup for the Kijiji search results page. Falls back to generic anchor scanning.
5. **Clutch.ca** — Uses Playwright for JS rendering (requests-only fallback if Playwright unavailable).
6. **Local dealer websites** — Probes each dealer's `/used-inventory`, `/inventory`, `/used`, `/search`, `/cars`, `/vehicles` paths concurrently for matching listings.

After collection, listings are deduplicated by URL. If zero listings are found for a vehicle, a fallback entry with the AutoTrader search URL is added.

**Facebook Marketplace:** Skipped in scraping (requires authenticated session). Quick-link button is shown in the email for manual searching.

### Playwright configuration

- **Launch args:** `--no-sandbox`, `--disable-setuid-sandbox`, `--disable-dev-shm-usage`, `--disable-gpu`, `--disable-web-security`, `--disable-features=IsolateOrigins,site-per-process` (required for GitHub Actions runners).
- **Wait strategy:** `domcontentloaded` (~2s) + explicit 5s pause + cookie banner dismissal + optional `wait_for_selector` on listing elements (3s timeout each).
- **Viewport:** 1920×1080 (desktop rendering).
- **User agent:** Chrome 120 on Windows.

## Scheduling

`.github/workflows/search.yml` defines two cron triggers (GitHub Actions cron is UTC-only):

- `0 11 5,8,11,14,17,20,23,26,29 * *` — 7:00 AM Eastern Daylight Time (UTC-4)
- `0 12 5,8,11,14,17,20,23,26,29 * *` — 7:00 AM Eastern Standard Time (UTC-5)

Both fire every 3rd day of the month from day 5. The Python DST guard ensures only one actually sends email. `workflow_dispatch` always runs.

## Secrets / environment variables

Required repository secrets:
- `GMAIL_ADDRESS` — sender Gmail address
- `GMAIL_PASSWORD` — Gmail App Password
- `RECIPIENT_EMAIL` — where the email is sent

Other env vars the script reads:
- `ENABLE_SCRAPE` (default `'0'`) — set to `'1'` by the workflow
- `REQUEST_DELAY` (default `'1.0'`) — seconds between HTTP retries
- `MAX_RETRIES` (default `'2'`) — retry attempts for HTTP/Playwright
- `GITHUB_EVENT_NAME` — set by workflow to `github.event_name`; used by DST guard

## GitHub Actions workflow steps (`search.yml`)

Checkout (with `persist-credentials: true`) → Set up Python 3.12 → Install `requirements.txt` + `playwright install chromium` → Run script (with all env vars) → Upload HTML artifacts (7-day retention) → Commit generated HTML files back to `main` as `GitHub Action` bot (non-failing: `|| true`) → Deploy to `gh-pages` via `peaceiris/actions-gh-pages@v4` with `keep_files: true`.

## Requirements.txt

