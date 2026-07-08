# CLAUDE.md

This file documents the current (V4) behavior of this repository — for AI assistants and human contributors.

> **V4 change (scraping layer):** AutoTrader, CarGurus, and Clutch are now scraped via their **structured data endpoints** (internal JSON APIs / embedded page JSON) instead of headless Playwright rendering with generic CSS selectors. Playwright is retained only as a fallback for AutoTrader. Dealer probing was rewritten to stop returning junk nav/homepage links. See [Search / scraping logic](#search--scraping-logic).

## What this repository does

A self-contained GitHub Actions automation that searches **nationwide (Canada-wide)** for plug-in hybrid vehicles (Mitsubishi Outlander PHEV and Toyota RAV4 Prime, model years **2022–2024**) across multiple Canadian marketplaces every 3 days at 7 AM Eastern. Each run:

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

- `WANTED_VEHICLES` — list of 2 dicts, each with `vehicle`, `make`, `model`, `year_min`, `year_max`, `max_price`, `max_mileage`, `aliases`, `urls` (pre-built search URLs for each marketplace plus a `kijiji_rss` URL), V4 API identifiers (`autotrader_model` — AutoTrader taxonomy model name, note RAV4 Prime uses `"RAV4"` because Prime is a *variant* there, not a top-level model; `cargurus_make` — CarGurus make id, e.g. `m46` for Mitsubishi, `m7` for Toyota; `cargurus_entity` — CarGurus model entity id, e.g. `d2652` / `d2992`), and `trims` (known trims, most-specific first, used to build the clean Vehicle label in the email). Currently:
  - **Mitsubishi Outlander PHEV** — years **2022–2024**; **year-specific price cap** `{2022: 29000, 2023: 35000, 2024: 35000}`; **year-specific mileage cap** `{2022: 70000, 2023: 105000, 2024: 100000}`.
  - **Toyota RAV4 Prime** — years **2022–2023** (2021 and 2024 excluded); flat max **$35,000** / **120,000 km**. 2023+ units are badged "RAV4 Plug-in Hybrid" — the `aliases` list covers both names.

  Both `max_price` and `max_mileage` may be **either a plain int or a year→cap dict**. `_get_price_cap(vehicle_config, year)` and `_get_mileage_cap(vehicle_config, year)` return the year-specific cap, or the **highest** cap when the year is None/unknown (used to build the broad search query before per-listing years are known; the exact per-year cap is re-applied in a post-dedup filter). **All searches are nationwide (Canada-wide)** — CarGurus `distance=50000`, AutoTrader `Proximity: -1` (National), Kijiji all-Canada location `l0`.
- `POPULAR_DEALER_SITES` — extra dealers always probed for inventory in addition to `dealers.json`. Each entry is a `{"name", "website", "province"}` dict (same shape as `dealers.json`, plus an optional `province`); the name is shown as the listing's Source and the province is used as a fallback region for that dealer's listings. Currently Rallye Mitsubishi (QC). Add more dealers here.
- `ALL_LISTINGS` entries may also carry a `desc` field (short description text, → email Description column), a `province` field (2-letter code, used to bucket listings into the regional email tables), and, for dealer listings, a `source` field holding the dealership name (→ email Source column). A `dealer_name_by_site` map (built in `scrape_and_populate_listings` from `dealers.json` + `POPULAR_DEALER_SITES`, falling back to `_dealer_name_from_site`) resolves each site to its display name; a parallel `dealer_province_by_site` map supplies the fallback province.
- `ALL_LISTINGS` — dynamic list populated each run by `scrape_and_populate_listings()`. Each entry is a dict with `url`, `title`, `year`, `trim`, `price`, `mileage`, `sunroof`, `province`, `vehicle`, and optionally `is_fallback`. Starts empty every run.
- **Province detection** (`_normalize_province`, `_postal_to_province`, `CANADA_PROVINCES`, `PROVINCE_NAMES`) — best-effort 2-letter province code from any location text: full province name (most reliable — AutoTrader detail URLs and CarGurus seller regions carry these), then a comma/slash-delimited 2-letter code (`"Ottawa, ON"`), then a postal-code prefix. Each parser sets `province` where it can: AutoTrader from the `/a/make/model/city/province/id` href, CarGurus from `sellerRegion`/`sellerCity`/postal, dealer JSON-LD from the schema.org `PostalAddress.addressRegion`, dealers from their configured province. Kijiji and Clutch usually can't determine it (→ `None`).
- `_listing_value_score()` — ranking function: lower score = better value. Uses `(over_cap, price + mileage_penalty + sunroof_bonus, km)` as a tuple for sorting. Over-cap listings (mileage > year-specific cap via `_get_mileage_cap`) are pushed to the bottom.
- `DEALERS` — fallback list (2 entries) used only if `dealers.json` is missing/fails to load. Normally `dealers.json` (6 entries) is used.

## Search / scraping logic

**Design rationale (V4):** Headless rendering of the heavy marketplaces from GitHub Actions cloud IPs is exactly the fingerprint they anti-bot-block, and generic guess-selectors (`div[class*='card']`) rarely matched the real listing markup — so pre-V4 only Kijiji ever returned results. V4 hits each site's **structured data endpoint** instead, which is both more reliable and returns clean listing URLs plus price/mileage/year already parsed. Every source is wrapped in try/except and logs its result count, so a run's Actions log shows exactly what each source returned (useful for tuning when a site changes its API or blocks the runner).

`scrape_and_populate_listings()` runs per vehicle in this order, **collecting from ALL sources** (not stopping at first success):

1. **Kijiji RSS** (`parse_kijiji_rss`) — Structured XML feed parsed with BeautifulSoup's XML parser. Returns price, mileage, year, and direct listing URL. Most reliable source. Uses `_get_mileage_cap(vehicle_config, year)` for mileage filtering.
2. **AutoTrader.ca** (`parse_autotrader_api`) — Warms a `requests` session against the search URL (for cookies), then POSTs a JSON payload to `https://www.autotrader.ca/Refinement/Search`. The payload sets `Proximity: -1` (National) so the search is nationwide. The response's `AdsHtml` fragment (rendered listing cards) is parsed by `_parse_autotrader_ads_html` for `/a/…` detail links. Uses `autotrader_model` from config. Uses `_get_mileage_cap(vehicle_config, year)` for mileage filtering. **Fallback:** if the API returns nothing and Playwright is available, falls back to the old headless render + `parse_autotrader_listings`.
   - **Distance-read-as-mileage bug (fixed by detail-page enrichment):** AutoTrader search cards carry the seller's *distance* from the search `Address` (`Gatineau, QC`) but **not** the odometer. Because the search is National (`Proximity: -1`) that distance is large (e.g. 2,873 km), and the parser was reading it as the mileage — reporting a real 103,000 km / 85,834 km / 99,998 km car as ~1,015 / 2,873 / 2,870 km. Confirmed by fetching the detail pages: the odometer is only there, not on the card. **Fix:** `_parse_autotrader_ads_html` (and the Playwright fallback `parse_autotrader_listings`) no longer read mileage from the card — they set `mileage: None` — and `scrape_and_populate_listings` then calls `_enrich_mileage_from_detail(at_listings)` (the same helper the dealer path uses, formerly `_enrich_dealer_mileage`) to fetch each detail page and read the real odometer. `_extract_odometer` was extended to parse AutoTrader's detail-page JSON keys (`mileageFromOdometer.value`, `mileageInKmRaw`, `stmil`, `classified_mileage` — all equal 103000 on that page). The per-year mileage cap is then enforced by the post-dedup `_within_caps` filter, so cars now shown to be over-cap (e.g. the 103,000 km unit vs. the 2024 cap of 100,000) are correctly dropped. Detail pages **are** fetchable via plain `requests` even where the search API is challenged. (`_find_mileage` retains a defensive `N km away` strip for any other card-based parser, but AutoTrader no longer relies on it.)
3. **CarGurus.ca** (`parse_cargurus_api` + `_cargurus_api_params`) — GETs the `Cars/searchResults.action` JSON endpoint. **V4.1 fix:** CarGurus migrated its filter from the old `entitySelectingHelper.selectedEntity=<model>` param (which no longer filters, so results came back empty/irrelevant) to `makeModelTrimPaths=<makeId>,<makeId>/<modelId>` (e.g. Outlander PHEV = `m46,m46/d2652`, RAV4 Prime = `m7,m7/d2992`). `_cargurus_api_params` builds the request from the *validated* `/search` filter URL in config (reusing its `makeModelTrimPaths`, `zip`, `distance=50000` for nationwide, and sort), then forces the config's own year/price/mileage caps and adds pagination; it composes `makeModelTrimPaths` from `cargurus_make`/`cargurus_entity` if the URL lacks it, and falls back to the legacy entity param if no make id is set. Warms the session against the search page first (cookies). Builds `listingUrl`/`inventorylisting/vdp.action?listingId=…` links. Parses defensively (handles bare-list or wrapped-list responses and multiple field-name variants), trusts the model-entity selector and only guards against a gross make mismatch. Uses `_get_mileage_cap(vehicle_config, year)` for mileage filtering.
4. **Kijiji Web** (`parse_kijiji_listings`) — Plain `requests` + BeautifulSoup for the Kijiji search results page. Falls back to generic anchor scanning.
5. **Clutch.ca** (`parse_clutch_api`) — Clutch is a Next.js site, so listings are embedded in the `<script id="__NEXT_DATA__">` JSON on the initial HTML — fetched with plain `requests` (no browser). Recursively walks the JSON for listing-shaped objects. Filters by make/model/year/price/mileage using `_get_mileage_cap(vehicle_config, year)`.
6. **Local dealer websites** (`find_dealer_listings`) — Probes each dealer (from `dealers.json` **plus** `POPULAR_DEALER_SITES`, e.g. Rallye Mitsubishi) concurrently. For each vehicle it probes two kinds of paths across **both the Used/Pre-Owned and Certified Pre-Owned (CPO) sections**: **model-filtered** URLs built from the make/model (e.g. `/en/pre-owned?make=Mitsubishi&model=Outlander+PHEV`, `/en/certified-inventory?make=…&model=…`, plus `/en/inventory?…`, `/pre-owned?…`, `/certified-inventory?…`, `/inventory?…`) and plain **index** paths (`/en/pre-owned`, `/en/certified-inventory`, `/en/certified`, `/en/inventory?type=used`, `/en/inventory`, `/en/used-inventory`, `/used-inventory`, `/certified-inventory`, `/inventory?type=used`, `/inventory`, `/used`, `/vehicles`). The filtered URLs matter because a dealer's bare inventory index typically shows only page 1 — e.g. Rallye's used 2022 Outlander PHEV only appears under the model-filtered URL, not the index. Both sections are probed because a CPO unit isn't always cross-listed under plain pre-owned; results are deduped by URL. `requests` follows 301s, so `/en/used-inventory` → `/en/pre-owned` resolves automatically. For each fetched page it tries two extraction strategies in order:
   - **JSON-LD (`_extract_jsonld_vehicles`)** — parses schema.org `Car`/`Vehicle`/`Product` structured data from `<script type="application/ld+json">` blocks. This is the reliable path for standard Canadian dealer platforms (D2C Media / EDealer / Convertus / Sincro) like Rallye Mitsubishi. Handles the common quirks: the detail URL is often on the `offers.url` (not top-level `url`), and the year is embedded in the `name`. Filters by make/model/year/price/mileage. No headless browser needed.
   - **Strict anchor scanning (fallback)** — a link is only accepted if its **visible text names the make + a full model/alias token group** AND the **href looks like a specific vehicle-detail page** (`_looks_like_vehicle_detail`: a detail path segment + a ≥4-digit stock/VIN/id, not a bare category index).

   Returns all real matches per site, deduped. (This replaces the pre-V4 `find_listing_in_dealer_html`, which matched the make anywhere in the URL and so returned the dealer's own homepage/nav link.)

   **Mileage enrichment (`_enrich_mileage_from_detail` + `_extract_odometer`):** These dealer platforms do **not** include mileage in their JSON-LD — the odometer lives only on the vehicle *detail* page as a hidden form field (e.g. `<input type="hidden" name="vehicle_odometer" value="43356" />`), so listings scraped from inventory pages come back with no mileage. After the dealer listings for a vehicle are collected and deduped, `_enrich_mileage_from_detail` fetches each mileage-less listing's detail URL concurrently and `_extract_odometer` reads the hidden `(vehicle_)odometer`/`mileage`/`kilometers` field (name/value in either attribute order; the empty `trade_vehicle_odometer` trade-in field is excluded), falling back to JSON-LD/other structured keys (`mileageFromOdometer`, and AutoTrader's `mileageInKmRaw`/`stmil`/`classified_mileage`). Dedup runs **before** enrichment so each detail page is fetched once (the same car appears under several probe-path URLs), and the year-specific mileage cap (`_get_mileage_cap`) is re-applied **after** enrichment now that the real odometer is known. **The same helper also enriches AutoTrader listings** (whose cards carry distance, not odometer — see the AutoTrader source above).

After collection, listings are deduplicated by `_dedup_listings` (see below). A **post-dedup filter** (`_within_caps`) then drops any listing whose mileage **or price** exceeds its year-specific cap — a second pass that catches listings fetched via the broad (highest-cap) query whose year wasn't known at parse time (e.g. a 2022 Outlander must clear the tighter $29k / 70k km caps, not the 2023 ones). If zero listings remain for a vehicle, a fallback entry with the AutoTrader search URL is added (`is_fallback: True`).

**Deduplication (`_dedup_listings`):** The same physical car surfaces multiple times — from several dealer probe paths (index vs model-filtered vs certified, each yielding a slightly different URL), and from more than one marketplace (e.g. the same unit on AutoTrader *and* Kijiji). URL-only dedup left these as duplicate rows. `_dedup_listings` runs two passes: (1) exact normalized-URL dedup (`_norm_url` strips scheme/`www`/query/fragment/trailing slash + lowercases), then (2) a **content-signature** dedup (`_dedup_signature`) keyed on the car's own attributes — `(vehicle, year, trim, mileage)` when mileage is known (exact km is a near-unique fingerprint), falling back to `(vehicle, year, trim, price)` when mileage is absent (typical for dealer JSON-LD), and to the normalized URL only when neither is known. `trim` is resolved via `_clean_trim` so trim spelling variants collapse together. When two entries share a signature, `_better_listing` keeps the lower-priced one and carries over a sunroof flag, mileage, or richer description from the discarded twin so no detail is lost.

**Facebook Marketplace:** Skipped in scraping (requires authenticated session). Quick-link button is shown in the email for manual searching.

### HTTP / API helpers

- `http_get` / `http_get_json` — GET returning text / parsed JSON, with `MAX_RETRIES` and `REQUEST_DELAY` backoff.
- `http_post_json` — POSTs a JSON body (used for AutoTrader); returns parsed JSON, or `{"_raw": <text>}` if the body isn't JSON, or `None` on failure.
- `fetch_rendered_html` — the Playwright renderer, now used **only** as the AutoTrader fallback. Launch args (`--no-sandbox`, `--disable-dev-shm-usage`, etc.), `domcontentloaded` wait strategy, cookie-banner dismissal, 1920×1080 viewport, and Chrome-120 user agent are unchanged from V3.

**Reliability caveat:** the JSON APIs are frequently rate-limited or anti-bot-challenged — **not only from GitHub Actions IPs.** Observed while debugging from an ordinary residential Windows machine (July 2026): a POST to `https://www.autotrader.ca/Refinement/Search` came back as an AutoTrader "We can't find the page you're looking for" error page (no `AdsHtml`), and a plain GET of the AutoTrader search URL returned a 165-byte challenge stub. CarGurus similarly returns 403s to automated fetches. When this happens the logs show `JSON POST/GET … failed` or "returned no AdsHtml", and the run falls back (AutoTrader → Playwright) or that source simply contributes nothing that run; Kijiji RSS is the most consistently reachable source. Tuning (headers, session warm-up, or leaning on the Playwright fallback) may be needed. The exact API field names are handled with multiple fallbacks but could drift if the sites change. **Practical consequence for debugging:** you generally cannot reproduce a live scrape from a dev machine — rely on the per-source count logs from an actual run, and on the detail-page HTML (which *is* fetchable) to verify individual listings.

### Email output (ranked tables, grouped by year + region)

The email body (`generate_email_html`) groups the ranked listings into **two model-year boxes**, each containing one or more region tables (a plain interactive dropdown isn't possible in email — Gmail/Outlook strip `<script>` and can't filter `<select>`, so grouping is done server-side). Listings are bucketed by `_listing_year` and by their `province` field:

1. **Model Years 2023–2024** box — both vehicles, split by province:
   - **Alberta** table (`province == "AB"`), flagged with a "5% GST — usually the lowest total cost" note (the reason for splitting Alberta out — its sales tax is much lower).
   - **Ontario, Quebec & Other** table (`province != "AB"`) — everything not in Alberta, including Ontario, Quebec, other provinces, and listings with no detectable province. Carries a **Province** column so each row's region (or an em-dash for unknown) is visible. Nothing is dropped.
2. **Model Year 2022** box — a single table for both vehicles with a **Province** column, showing **all** provinces (unknown → em-dash).

Helpers (all local to `generate_email_html`): `listing_row(rank, listing, show_province=False)` renders a row and conditionally adds the province cell; `_colgroup`/`_thead` build the 6- or 7-column table head; `_render_table(listings, show_province)` wraps a scrollable table with an empty-state row when empty; `_table_heading`/`_box_heading` render the headings (with per-table listing counts). Each table ranks its rows independently starting at 1. **`_render_table` also pushes listings with no detectable province to the bottom** via a stable secondary sort (`0 if province else 1`) — since the list is already value-sorted, this keeps the value ranking within the known- and unknown-province groups while grouping the unknowns last.

Columns are **Rank, Vehicle, Price, Mileage, [Province], Description, Source** (Sunroof is folded into Description, see below; Province appears only on the mixed-province tables). The **Source** shows the marketplace name for marketplace listings (AutoTrader, CarGurus, Kijiji, …) and the **dealership name** for dealer listings (e.g. "Rallye Mitsubishi") — from the listing's `source` field when present, else inferred from the URL. Each table uses `table-layout:fixed` with a `<colgroup>` inside an `overflow-x:auto` wrapper (`min-width` 640/700px) so it's neat on desktop and horizontally scrollable on narrow screens.

- **Vehicle** (`_vehicle_label`) shows *only* a clean `YEAR Make Model Trim` label — never marketing/description text. The trim is resolved by `_clean_trim`, which matches the vehicle's configured `trims` list (most-specific first) against the listing's title/desc; a short raw trim is accepted as a fallback. The label is the clickable link to the actual listing.
- **Description** (`_short_description`) is a short, clear feature summary (up to 5 tags such as `Sunroof, Leather, Heated Seats, CarPlay, AWD`) matched from the listing's title/`desc` via `FEATURE_PATTERNS`. Empty → em-dash.
- **Sunroof in the Description is trim-aware** (`_sunroof_status` + `SUNROOF_BY_TRIM`): it leads the Description as `Sunroof` when we're confident the car has one (the listing text mentions it, **or** the trim implies it) and `No Sunroof` when the trim confirms it has none; when genuinely unknown it's simply omitted. `SUNROOF_BY_TRIM` is a validated per-vehicle trim→bool map — for the Canadian Outlander PHEV (both the 2022 3rd-gen and all-new 2023 lineups) the base **ES has no sunroof** while the **panoramic sunroof is standard from LE up** (LE / SEL / GT / GT Premium / Black Edition). `SE` is intentionally omitted (inconsistent across model years) and RAV4 Prime is omitted entirely (its moonroof is an option package on both SE and XSE, so it can't be inferred from trim — those fall back to listing text).

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
