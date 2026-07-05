# CLAUDE.md

This file gives an AI assistant (or a new human contributor) the context needed to safely understand and modify this repository. It documents verified, current behavior only — no assumptions about intent beyond what the code does.

## What this repository does

This is a small, self-contained automation that runs on a schedule via GitHub Actions. Each run:

1. Searches for two specific vehicles (a 2023 Mitsubishi Outlander PHEV SE and a 2024 Toyota RAV4 Prime XSE) across AutoTrader.ca, CarGurus.ca, Kijiji, Clutch.ca, Facebook Marketplace, and a list of local dealer websites.
2. Generates two static HTML files: an email body (`gatineau_phev_rav4_search_results.html`) and a full local-dealers list (`dealers.html`).
3. Emails the results (with both HTML files attached) via Gmail SMTP to one recipient.
4. Commits the two generated HTML files back to the `main` branch and publishes them to the `gh-pages` branch via GitHub Pages.

There is no database, no persistent state beyond the two generated HTML files, and no web server — it is a single Python script invoked by a scheduled workflow.

## Repository layout

- `vehicle_search_automation.py` — the entire application: scraping/search logic, HTML generation, and email sending. This is the only Python file in the repo.
- `.github/workflows/search.yml` — the GitHub Actions workflow that runs the script on a schedule and on manual dispatch.
- `dealers.json` — the list of local dealers (name, brand, city, distance_km, website) used both for the "All Dealers" HTML page and as the set of sites probed directly for listings. Currently contains 6 dealers (Toyota Gatineau, Gatineau Honda, Occasion Kadir Dargham, Rallye Mitsubishi, Lallier Honda Hull, Bel-Air Toyota).
- `dealers.html` — generated output (the full dealers table). Overwritten every run; also committed back to the repo by the workflow.
- `gatineau_phev_rav4_search_results.html` — generated output (the email body, saved as a standalone file too). Overwritten every run; also committed back to the repo by the workflow.
- `requirements.txt` — Python dependencies: `requests`, `beautifulsoup4`, `lxml`, `pytz`, `tqdm`.
- `README.md` — user-facing overview of the project (what it does, schedule, setup).

## Execution flow (main())

1. Compute `est_now = datetime.now(EST)` where `EST = pytz.timezone('US/Eastern')` (this correctly resolves to EDT or EST depending on the date, via pytz).
2. **DST-safe schedule guard:** read `GITHUB_EVENT_NAME` from the environment (set by the workflow to `github.event_name`; empty string if run locally). If this run is NOT a manual/local run (i.e. `GITHUB_EVENT_NAME` is something other than `'workflow_dispatch'` or `''`) AND the current Eastern hour is not 7, the function prints a message and returns immediately without scraping, generating files, or sending email. This exists because the workflow fires two cron triggers per run day (see Scheduling below) and only one of them should actually do the work.
3. If `ENABLE_SCRAPE=1` (set by the workflow), call `scrape_and_populate_listings()` to try to find real listing URLs for each vehicle in `WANTED_VEHICLES` and write them into `LISTINGS`. If scraping is disabled, any `LISTINGS` entry whose URL is empty or contains `example.com` gets a fallback search URL instead.
4. Generate `dealers.html` via `generate_dealers_html()` and the email HTML via `generate_email_html(est_now)`; write both to disk.
5. Send the email via `send_email()`, attaching both generated HTML files. If `GMAIL_ADDRESS`, `GMAIL_PASSWORD`, or `RECIPIENT_EMAIL` are not all set, sending is skipped (printed as a warning) but the script does not error.

## Key data structures (all hardcoded in vehicle_search_automation.py)

- `WANTED_VEHICLES` — list of 2 dicts, each with `vehicle` (full display name), `make`, and `model`. This drives what `scrape_and_populate_listings()` searches for. Currently: Mitsubishi Outlander PHEV (SE trim) and Toyota RAV4 Prime (XSE trim).
- `LISTINGS` — list of 2 placeholder dicts (one per wanted vehicle) with `vehicle`, `price`, `mileage`, `sunroof`, `city`, `distance_km`, `dealer_name`, `dealer_rating`, and `url`. The price/mileage/sunroof/city/dealer fields shown in the email are these static placeholder values — the scraper only ever updates the `url` field; it does not re-scrape price/mileage/etc. from the real listing. This is a structural limitation: the email always shows the same hardcoded price/mileage/dealer text regardless of what was actually found.
- `DEALERS` — a 2-entry fallback list used only if `dealers.json` is missing or fails to load. In normal operation `dealers.json` (6 entries) is what's actually used.
- `MARKETPLACE_LINKS` — the 5 buttons shown in every email: AutoTrader.ca, CarGurus.ca, Kijiji, Clutch.ca, Facebook Marketplace. These are static links (not vehicle-specific searches for all of them — AutoTrader's is a fixed Outlander-PHEV/Gatineau URL, CarGurus' is a fixed radius/sort URL, Kijiji's is a fixed Outlander-PHEV search, Clutch's is just the general inventory page, Facebook's is the general vehicles category).

## Search / scraping logic

`scrape_and_populate_listings()` tries, per vehicle, in this fixed order, stopping at the first success:

1. AutoTrader (`build_autotrader_search_url` + `parse_autotrader_first_listing`)
2. CarGurus (`build_cargurus_search_url` + `parse_cargurus_first_listing`)
3. Kijiji (`build_kijiji_search_url` + `parse_kijiji_first_listing`)
4. Clutch.ca (`build_clutch_search_url` + `parse_clutch_first_listing`)
5. Facebook Marketplace (`build_facebook_marketplace_search_url` + `parse_facebook_first_listing`)
6. Each dealer website from `dealers.json`, probed via `probe_dealer_for_listing()` (tries a fixed list of common inventory paths, then a few search-query patterns, then the homepage)

If none of these succeed, `generate_marketplace_search_url()` builds a fallback AutoTrader search URL (via `build_marketplace_search_url`) instead of a specific listing.

All HTML parsing uses `requests` + `BeautifulSoup` (`lxml` parser) against the plain server-rendered HTML — there is no headless browser / JS execution (no Selenium/Playwright). `NON_LISTING_HREF_MARKERS` (`/editorial/`, `/expert-reviews/`, `/research/`, `/news/`, `/reviews/`, `/help`, `/about`, `/blog/`) and the `_is_listing_candidate()` helper are used across all parsers to reject links to editorial/informational content rather than actual listings.

**Known limitation (observed in production, run #22, 2026-07-05):** AutoTrader's search-results page appears to be largely JS-rendered, so the first two matching passes in `parse_autotrader_first_listing()` (which require visible link text containing the year/make/model) often find nothing in the static HTML, and the function falls through to its last-resort fallback (`any anchor whose href contains "/cars/"`). In practice this returns a generic model category page (e.g. `autotrader.ca/cars/mitsubishi/outlander` — note: without "-phev" and without a location filter) rather than an individual for-sale listing. This is a genuine improvement over the pre-fix behavior (which could return unrelated editorial articles), but it is not yet a specific listing. Getting individual listings would likely require a headless-browser approach or an official API, which this script does not currently use.

**Facebook Marketplace note:** `parse_facebook_first_listing()` intentionally does not attempt to log in or bypass authentication. Facebook Marketplace requires a logged-in session to render listings, so an unauthenticated `requests.get()` will almost always return no usable listing links, and the code falls back to the generic search URL. This is by design, not a bug to fix by adding login/bypass logic.

## Scheduling

`.github/workflows/search.yml` defines two `schedule` cron triggers (GitHub Actions cron is UTC-only and has no DST awareness):

- `0 11 5,8,11,14,17,20,23,26,29 * *` — intended to match 7:00 AM Eastern Daylight Time (UTC-4)
- `0 12 5,8,11,14,17,20,23,26,29 * *` — intended to match 7:00 AM Eastern Standard Time (UTC-5)

Both fire on the same set of days (every 3rd day of the month, from day 5). The workflow passes `GITHUB_EVENT_NAME: ${{ github.event_name }}` into the Python process; `main()` uses this plus the real `pytz`-computed Eastern hour to decide whether to actually proceed (see Execution flow above), so only one of the two triggers per day results in an email being sent, and the 7 AM target is correct across the DST transition. `workflow_dispatch` (manual runs) always proceeds regardless of the current hour.

## Secrets / environment variables

Required repository secrets (Settings → Secrets and variables → Actions):

- `GMAIL_ADDRESS` — sender Gmail address
- `GMAIL_PASSWORD` — a Gmail App Password (not the account password)
- `RECIPIENT_EMAIL` — where the email is sent

Optional repository variable:

- `VIEW_DEALERS_URL` — passed through to the script's environment but not currently read/used anywhere inside `vehicle_search_automation.py` (it's set as an env var in the workflow and in the script's top-level env config, but no code references `os.getenv('VIEW_DEALERS_URL')`). Safe to ignore or remove unless it's meant for future use.

Other env vars the script reads: `ENABLE_SCRAPE` (default `'0'`), `REQUEST_DELAY` (default `1.0` seconds between HTTP requests), `MAX_RETRIES` (default `2`). The workflow sets `ENABLE_SCRAPE=1` and `REQUEST_DELAY=1.0`.

## GitHub Actions workflow steps (search.yml)

Checkout (with `persist-credentials: true` so later steps can push) → set up Python 3.11 → install `requirements.txt` → run `vehicle_search_automation.py` → upload `gatineau_phev_rav4_search_results.html` and `dealers.html` as a 30-day artifact → commit those same two files back to `main` as the `GitHub Action` bot user (non-failing: uses `|| true` so a no-op commit doesn't fail the job) → deploy the repo root to the `gh-pages` branch via `peaceiris/actions-gh-pages@v4` with `keep_files: true` (old published files are preserved, not wiped, on each deploy). The workflow has `permissions: contents: write` at the top level to allow the push-back and Pages deploy.

## Editing this repo via GitHub's web UI (gotcha)

GitHub's web-based code editor (CodeMirror) auto-indents as you type. Typing a large multi-line replacement directly into it can cause indentation to stack/compound line by line and corrupt the file. If replacing a whole file's contents through the browser, insert the text via `document.execCommand('insertText', false, fullText)` on the focused `.cm-content` element instead of simulating keystrokes — this inserts the text as a single operation and avoids the auto-indent problem. This was encountered and worked around while building this repo's current state.

## Recent history relevant to future changes

- Vehicle name links in the email used to be able to point to AutoTrader editorial/review articles instead of real listings (root cause: keyword-only text matching with no check on the link's path). Fixed by adding `NON_LISTING_HREF_MARKERS` / `_is_listing_candidate()`.
- The fallback link builder used to truncate multi-word models (e.g. "Outlander PHEV" → "Outlander", "RAV4 Prime" → "RAV4"), risking a link to the wrong (non-hybrid) trim. Fixed by having `generate_marketplace_search_url()` delegate to `build_marketplace_search_url()`, which keeps the full multi-word model.
- Clutch.ca and Facebook Marketplace were added as both email buttons and automated search sources; local dealer probing already existed and was preserved.
- The send schedule was changed from a single fixed-UTC cron (which drifted between 7-8 AM Eastern depending on DST) to the dual-cron + runtime-guard approach described above.
