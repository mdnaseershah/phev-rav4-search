# CLAUDE.md

This file documents the current (V4) behavior of this repository — for AI assistants and human contributors.

> **V4 change (scraping layer):** AutoTrader, CarGurus, and Clutch are now scraped via their **structured data endpoints** (internal JSON APIs / embedded page JSON) instead of headless Playwright rendering with generic CSS selectors. Playwright is retained only as a fallback for AutoTrader. Dealer probing was rewritten to stop returning junk nav/homepage links. See [Search / scraping logic](#search--scraping-logic).

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

- `WANTED_VEHICLES` — list of 2 dicts, each with `vehicle`, `make`, `model`, `year_min`, `year_max`, `max_price`, `max_mileage`, `aliases`, `urls` (pre-built search URLs for each marketplace plus a `kijiji_rss` URL), V4 API identifiers (`autotrader_model` — AutoTrader taxonomy model name, note RAV4 Prime uses `"RAV4"` because Prime is a *variant* there, not a top-level model; `cargurus_entity` — CarGurus model entity id, e.g. `d2652` / `d2992`; `cargurus_zip`), and `trims` (known trims, most-specific first, used to build the clean Vehicle label in the email). Currently: Mitsubishi Outlander PHEV (2022–2023, max $32,000, max 70,000 km) and Toyota RAV4 Prime (2021–2023, max $42,000, max 120,000 km).
- `POPULAR_DEALER_SITES` — extra dealers always probed for inventory in addition to `dealers.json`. Each entry is a `{"name", "website"}` dict (same shape as `dealers.json`); the name is shown as the listing's Source. Currently Rallye Mitsubishi. Add more dealers here.
- `ALL_LISTINGS` entries may also carry a `desc` field (short description text, → email Description column) and, for dealer listings, a `source` field holding the dealership name (→ email Source column). A `dealer_name_by_site` map (built in `scrape_and_populate_listings` from `dealers.json` + `POPULAR_DEALER_SITES`, falling back to `_dealer_name_from_site`) resolves each site to its display name.
- `ALL_LISTINGS` — dynamic list populated each run by `scrape_and_populate_listings()`. Each entry is a dict with `url`, `title`, `year`, `trim`, `price`, `mileage`, `sunroof`, `vehicle`, and optionally `is_fallback`. Starts empty every run.
- `_listing_value_score()` — ranking function: lower score = better value. Uses (over_cap, price + mileage_penalty + sunroof_bonus, km) as a tuple for sorting. Over-cap listings (mileage > max) are pushed to the bottom.
- `DEALERS` — fallback list (2 entries) used only if `dealers.json` is missing/fails to load. Normally `dealers.json` (6 entries) is used.

## Search / scraping logic

**Design rationale (V4):** Headless rendering of the heavy marketplaces from GitHub Actions cloud IPs is exactly the fingerprint they anti-bot-block, and generic guess-selectors (`div[class*='card']`) rarely matched the real listing markup — so pre-V4 only Kijiji ever returned results. V4 hits each site's **structured data endpoint** instead, which is both more reliable and returns clean listing URLs plus price/mileage/year already parsed. Every source is wrapped in try/except and logs its result count, so a run's Actions log shows exactly what each source returned (useful for tuning when a site changes its API or blocks the runner).

`scrape_and_populate_listings()` runs per vehicle in this order, **collecting from ALL sources** (not stopping at first success):

1. **Kijiji RSS** (`parse_kijiji_rss`) — Structured XML feed parsed with BeautifulSoup's XML parser. Returns price, mileage, year, and direct listing URL. Most reliable source.
2. **AutoTrader.ca** (`parse_autotrader_api`) — Warms a `requests` session against the search URL (for cookies), then POSTs a JSON payload to `https://www.autotrader.ca/Refinement/Search`. The response's `AdsHtml` fragment (rendered listing cards) is parsed by `_parse_autotrader_ads_html` for `/a/…` detail links. Uses `autotrader_model` from config. **Fallback:** if the API returns nothing and Playwright is available, falls back to the old headless render + `parse_autotrader_listings`.
3. **CarGurus.ca** (`parse_cargurus_api`) — GETs the `Cars/searchResults.action` JSON endpoint using `cargurus_entity` + `cargurus_zip` + price/year/mileage params. Builds `inventorylisting/vdp.action?listingId=…` links. Parses defensively (handles bare-list or wrapped-list responses and multiple field-name variants).
4. **Kijiji Web** (`parse_kijiji_listings`) — Plain `requests` + BeautifulSoup for the Kijiji search results page. Falls back to generic anchor scanning.
5. **Clutch.ca** (`parse_clutch_api`) — Clutch is a Next.js site, so listings are embedded in the `<script id="__NEXT_DATA__">` JSON on the initial HTML — fetched with plain `requests` (no browser). Recursively walks the JSON for listing-shaped objects. Filters by make/model/year/price/mileage.
6. **Local dealer websites** (`find_dealer_listings`) — Probes each dealer (from `dealers.json` **plus** `POPULAR_DEALER_SITES`, e.g. Rallye Mitsubishi) concurrently. For each vehicle it probes two kinds of paths across **both the Used/Pre-Owned and Certified Pre-Owned (CPO) sections**: **model-filtered** URLs built from the make/model (e.g. `/en/pre-owned?make=Mitsubishi&model=Outlander+PHEV`, `/en/certified-inventory?make=…&model=…`, plus `/en/inventory?…`, `/pre-owned?…`, `/certified-inventory?…`, `/inventory?…`) and plain **index** paths (`/en/pre-owned`, `/en/certified-inventory`, `/en/certified`, `/en/inventory?type=used`, `/en/inventory`, `/en/used-inventory`, `/used-inventory`, `/certified-inventory`, `/inventory?type=used`, `/inventory`, `/used`, `/vehicles`). The filtered URLs matter because a dealer's bare inventory index typically shows only page 1 — e.g. Rallye's used 2022 Outlander PHEV only appears under the model-filtered URL, not the index. Both sections are probed because a CPO unit isn't always cross-listed under plain pre-owned; results are deduped by URL. `requests` follows 301s, so `/en/used-inventory` → `/en/pre-owned` resolves automatically. For each fetched page it tries two extraction strategies in order:
   - **JSON-LD (`_extract_jsonld_vehicles`)** — parses schema.org `Car`/`Vehicle`/`Product` structured data from `<script type="application/ld+json">` blocks. This is the reliable path for standard Canadian dealer platforms (D2C Media / EDealer / Convertus / Sincro) like Rallye Mitsubishi. Handles the common quirks: the detail URL is often on the `offers.url` (not top-level `url`), and the year is embedded in the `name`. Filters by make/model/year/price/mileage. No headless browser needed.
   - **Strict anchor scanning (fallback)** — a link is only accepted if its **visible text names the make + a full model/alias token group** AND the **href looks like a specific vehicle-detail page** (`_looks_like_vehicle_detail`: a detail path segment + a ≥4-digit stock/VIN/id, not a bare category index).

   Returns all real matches per site, deduped. (This replaces the pre-V4 `find_listing_in_dealer_html`, which matched the make anywhere in the URL and so returned the dealer's own homepage/nav link.)

After collection, listings are deduplicated by URL. If zero listings are found for a vehicle, a fallback entry with the AutoTrader search URL is added (`is_fallback: True`).

**Facebook Marketplace:** Skipped in scraping (requires authenticated session). Quick-link button is shown in the email for manual searching.

### HTTP / API helpers

- `http_get` / `http_get_json` — GET returning text / parsed JSON, with `MAX_RETRIES` and `REQUEST_DELAY` backoff.
- `http_post_json` — POSTs a JSON body (used for AutoTrader); returns parsed JSON, or `{"_raw": <text>}` if the body isn't JSON, or `None` on failure.
- `fetch_rendered_html` — the Playwright renderer, now used **only** as the AutoTrader fallback. Launch args (`--no-sandbox`, `--disable-dev-shm-usage`, etc.), `domcontentloaded` wait strategy, cookie-banner dismissal, 1920×1080 viewport, and Chrome-120 user agent are unchanged from V3.

**Reliability caveat:** the JSON APIs can still be rate-limited or challenged from GitHub Actions IPs. When that happens the logs show `JSON POST/GET … failed`, and tuning (headers, or leaning on the Playwright fallback) may be needed. The exact API field names are handled with multiple fallbacks but could drift if the sites change.

### Email output (ranked table)

The ranked table in the email (`generate_email_html` → `listing_row`) has columns: **Rank, Vehicle, Description, Price, Mileage, Sunroof, Source**. The **Source** shows the marketplace name for marketplace listings (AutoTrader, CarGurus, Kijiji, …) and the **dealership name** for dealer listings (e.g. "Rallye Mitsubishi") — taken from the listing's `source` field when present, otherwise inferred from the URL.

- **Vehicle** (`_vehicle_label`) shows *only* a clean `YEAR Make Model Trim` label — never marketing/description text. The trim is resolved by `_clean_trim`, which matches the vehicle's configured `trims` list (most-specific first) against the listing's title/desc; a short raw trim is accepted as a fallback. The label is the clickable link to the actual listing.
- **Description** (`_short_description`) is a short, clear feature summary (up to 5 tags such as `Sunroof, Leather, Heated Seats, CarPlay, AWD`) matched from the listing's title/`desc` via `FEATURE_PATTERNS`. Empty → em-dash. This is where any descriptive text now lives, keeping the Vehicle column clean.

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

