# CLAUDE.md

This file documents the current behavior of this repository — for AI assistants and human contributors.

## Current configuration at a glance

- **Vehicle:** Mitsubishi Outlander PHEV, model years **2023–2024** only (RAV4 Prime was removed). `WANTED_VEHICLES` is a single-entry list.
- **Price cap:** **$35,500** base (non-Alberta); **$38,000** in Alberta (`ab_max_price` — Alberta's 5% GST makes a pricier car there the same total cost). **Mileage cap:** 70,000 km.
- **Excluded trims:** Outlander **ES** (base, no sunroof) — but only when the trim is confidently identified; an unknown-trim listing is kept.
- **Scraped sources:** Kijiji (RSS + web), AutoTrader.ca (JSON API + Playwright fallback), Otogo.ca, local dealer sites (JSON-LD), LeaseBusters (lease transfers — its own email section). **Manual quick-links only** (bot-blocked / login-gated / SPA): CarGurus, Clutch, Facebook, Myers.
- **Schedule:** one automatic email per day, targeted ~8:30 AM Eastern. Three morning cron triggers fire ~6:30 AM (a primary + two backups) to pre-compensate for GitHub's ~1–2 h delay; retry-until-sent; manual runs independent. See [Scheduling](#scheduling).
- **Outputs:** email body (`outlander_phev_search_results.html`), `dealers.html`, and an `.xlsx` attachment (4 tabs: Search Results / Lease Takeovers / Dealers / Recently Sold). The email also has a **Recently Sold / Removed** section. `seen_listings.json` + `run_state.json` persist between runs.
- **Email columns:** Rank, Vehicle, Price, Mileage, [Province], Description, Source, Tracked. "Tracked" = days since we first saw the listing. The **Source** column lists **every** website a cross-posted car appears on, and Price shows the **lowest** among them.
- **Constraints (hard):** everything must stay **free** (plain `requests`, no paid APIs/unblockers) and **polite** (gentle dealer-probe concurrency/delays so no site or GitHub is abused).

<details>
<summary>Condensed changelog (most recent first)</summary>

- **V4.15** — **Price-history tracking.** Each seen-store record keeps a `price_history` (`[date, price]` points, appended only on change, capped to 12). The email **Price** cell shows a compact note when the price has moved — green **▼ $delta (was $orig)** for a drop, red **▲** for a rise (vs. the first price we recorded); Excel gets a **Price History** column (`35,500 → 34,000`) on both the Search Results and Recently Sold tabs. Helpers `_price_history_html` / `_price_history_text`. History follows a record's URL (the row's cheapest source).
- **V4.14** — **"Recently Sold / Removed" section** (email + a new Excel tab): tracked cars that have dropped off the scraped sites, with a **Days on Market** figure (last-seen − first-seen). The seen-store was upgraded to `{"listings": {url: record}}` where each record snapshots the listing (label/price/mileage/province/sources + first/last-seen/sold-on) so a car can still be shown after it disappears. A removal is only flagged **sold** when one of its sources was reachable that run (`_sources_reachable_this_run` vs `SOURCE_COUNTS`), so a blocked scrape doesn't fake a sell-off. Sold rows stay `SOLD_DISPLAY_DAYS` (21); the store still back-reads all older formats.
- **V4.13** — Cross-posted duplicates now show **every source** (each linked) and the **lowest price**. Dedup matches on `(vehicle, year, mileage)` — exact km is a near-unique fingerprint, so **trim was dropped from the key** (a car's trim text differs across sources) and **colour was deliberately skipped** (not reliably present). New helpers `_source_label` / `_listing_sources`; `_better_listing` unions the twins' `sources`. Also: falsy-URL listings no longer clobber each other in dedup, and `seen_listings.json` now prunes URLs absent > `SEEN_TTL_DAYS` (180) so it can't grow forever.
- **V4.12** — "Tracked" / days-on-radar column (email + Excel), built on an upgraded `seen_listings.json` (`{"first_seen": {url: "YYYY-MM-DD"}}`, back-compatible with old `{"urls":[...]}` / bare-list stores → unknown age).
- **V4.11** — Scheduling reworked: retry-until-sent, once-per-day, manual runs independent; crons target ~6:30 AM to offset GitHub's delay; `send_email` returns a bool; five "morning only" triggers.
- **V4.9/4.10** — RAV4 Prime removed (single-vehicle search); price caps set to **$35,500 / $38,000 AB**; email file renamed to `outlander_phev_search_results.*`; Excel (.xlsx) attachment added (openpyxl).
- **V4.6/4.7** — Alberta-only price cap + first Alberta (Calgary-area) dealers (145 probe sites total); extra dealer probe path `/occasion/recherche.html`.
- **V4.3/4.4/4.5** — 2022 dropped; LeaseBusters + Otogo.ca added as real sources; Search Criteria box; ES trims excluded.
- **V4.2** — CarGurus/Clutch → manual quick-links (bot-blocked); dealer anchor-scan wrong-vehicle bug fixed; email table redesigned.
- **V4** — scraping moved to structured-data endpoints (internal JSON APIs / JSON-LD) instead of headless rendering with guess-selectors; Playwright kept only as an AutoTrader fallback.

</details>

## What this repository does

A self-contained GitHub Actions automation that searches **nationwide (Canada-wide)** for the **Mitsubishi Outlander PHEV (2023–2024)** across Canadian marketplaces **every day at ~8:30 AM Eastern**. Each run:

1. **Scrapes** AutoTrader.ca, Kijiji (web + RSS), Otogo.ca, local dealer websites, and LeaseBusters (lease transfers). (CarGurus, Clutch, Facebook, and Myers are bot-blocked / login-gated / SPA-only → one-click **manual quick-links** in the email.)
2. **Ranks** all found listings by price-to-value (lowest price wins, with a mileage penalty and a sunroof bonus).
3. **Generates** an email body (`outlander_phev_search_results.html`) and a dealer list (`dealers.html`).
4. **Emails** the ranked results to one recipient via Gmail SMTP (with the `.xlsx` attached).
5. **Commits** the generated files back to the repo and publishes them to GitHub Pages.

No database, no web server — a single Python script invoked by a scheduled workflow.

## Repository layout

- `vehicle_search_automation.py` — the entire application (scraping, HTML/Excel generation, email). The only Python file.
- `.github/workflows/search.yml` — the GitHub Actions workflow (cron schedule + manual dispatch).
- `dealers.json` — curated local dealers (name, brand, city, distance_km, website). Used for `dealers.html` **and** as probe targets.
- `dealer_sites.json` — large **probe-only** dealer list (145 sites, incl. 7 Alberta). Scraped for inventory but **not** shown on `dealers.html`.
- `dealers.html` — generated (dealers table, from `dealers.json` only). Overwritten each run, committed back.
- `outlander_phev_search_results.html` — generated email body. Overwritten each run, committed back.
- `outlander_phev_search_results.xlsx` — generated Excel attachment (Search Results / Lease Takeovers / Dealers tabs). Attached to the email + uploaded as a workflow artifact, but **not committed** (per-run binary).
- `seen_listings.json` — persistent per-listing store, `{"listings": {norm_url: record}}` (V4.14), where each record holds `first_seen` / `last_seen` / `sold_on` dates, a `price_history` (`[date, price]` points, on-change only, capped to 12), plus a snapshot (`label`, `year`, `trim`, `vehicle`, `price`, `mileage`, `province`, `url`, `sources`). Drives the **NEW** flag, the **Tracked** column, and the **Recently Sold** section (the snapshot lets a car be shown after it disappears). Back-reads older formats (V4.12 `{"first_seen": {url: date}}` and the original `{"urls":[...]}` / bare list → dates only, no snapshot). Committed back each run; absent-for-`SEEN_TTL_DAYS` (180) records and sold records past `SOLD_DISPLAY_DAYS` (21) are pruned. Missing file = baseline (first run flags nothing new).
- `requirements.txt`, `README.md`.

## Execution flow (`main()`)

1. Compute `est_now = datetime.now(EST)` (pytz handles EDT/EST).
2. **Retry-until-sent schedule guard:** `is_manual = os.getenv('GITHUB_EVENT_NAME','') in ('', 'workflow_dispatch')`. A **scheduled** run exits unless the Eastern hour is in the **6 AM–10 PM window** (`6 <= est_now.hour <= 21`) AND the day's email hasn't already sent (per `run_state.json`). The day is marked done **only when the email actually sends** (`send_email` returns a bool; `_record_run_date` runs only `if sent and not is_manual`), so a delayed/failed attempt leaves the day unrecorded and the next cron retries. **Manual runs bypass the guard entirely and never touch `run_state.json`.** See [Scheduling](#scheduling).
3. **`_apply_criteria_env_overrides()`** — optionally override the vehicle's years/price/mileage from env vars (mapped from `workflow_dispatch` inputs), then rewrite the cap params baked into its marketplace URLs. Unset vars leave the hardcoded defaults.
4. If `ENABLE_SCRAPE=1`, `scrape_and_populate_listings()` collects all matching listings into `ALL_LISTINGS` and records per-source counts in `SOURCE_COUNTS`.
5. **`mark_new_and_update_seen()`** (only when scraping ran) — flags each listing `is_new` (URL not seen before), stamps `first_seen` / `days_on_radar`, refreshes each record's snapshot, marks disappeared cars **sold** (guarded by source reachability), builds the `SOLD_LISTINGS` global, and persists the seen-store. First run is a baseline.
6. Generate `dealers.html` + the email HTML + the `.xlsx`; write to disk. The email shows a "N new listing(s)" banner, per-row **NEW** pills, and a **source-health footer** (per-source counts; `0` = blocked/failed this run, not necessarily empty).
7. Send email via `send_email()` (skipped if credentials missing).
8. The workflow commits the HTML files **and `seen_listings.json` and `run_state.json`** back to `main` and deploys to `gh-pages`.

## Key data structures

- `WANTED_VEHICLES` — a **single-entry list**; its one dict has `vehicle`, `make`, `model`, `year_min`, `year_max`, `max_price`, `max_mileage`, `ab_max_price`, `aliases`, `urls` (pre-built search URLs per marketplace + `kijiji_rss`), API ids (`autotrader_model`; `cargurus_make` `m46`; `cargurus_entity` `d2652`), `trims` (most-specific first), `exclude_trims` (`["ES"]`), and `leasebusters` (`{"category_id": 7, "make_id": 31}`). The Outlander: years **2023–2024**, price cap `{2023: 35500, 2024: 35500}`, `ab_max_price` `38000`, mileage cap `{2023: 70000, 2024: 70000}`.
  - `max_price`/`max_mileage` may be a plain int **or** a year→cap dict. `_get_price_cap(vehicle_config, year, province)` / `_get_mileage_cap(vehicle_config, year)` return the year-specific cap, or the **highest** cap when the year is None (for the broad query before per-listing years are known; the exact per-year cap is re-applied in a post-dedup filter). `_get_price_cap` with `province="AB"` returns `ab_max_price` ($38,000); the no-year/no-province broad fetch widens to the global max ($38,000) so AB cars in the $35.5k–$38k band are fetched, then non-AB listings are refiltered to $35,500 post-dedup. **All searches are nationwide** (CarGurus `distance=50000`, AutoTrader `Proximity: -1`, Kijiji `l0`).
- `POPULAR_DEALER_SITES` — extra dealers always probed, `{"name","website","province"}` (currently Rallye Mitsubishi, QC). The name is the listing's Source; the province is a fallback region.
- `dealer_sites.json` — the **large probe-only** list (**145** Toyota/Honda/Mitsubishi dealers, QC/ON + 7 Alberta), merged with `dealers.json` + `POPULAR_DEALER_SITES` (deduped by website). Shape `{"name","website","brand"}` + optional `"province"` (the 7 AB entries set `"province":"AB"` → their listings land in the Alberta email table + get the $38,000 AB cap). Honda/Toyota lots are included because used trade-ins of any brand appear on them. **Do not add pure client-side SPA dealers** (e.g. Myers / Dealer.com / Convertus): their initial HTML has no JSON-LD, so a plain-`requests` probe returns nothing.
- `ALL_LISTINGS` — dynamic list populated each run. Each entry: `url`, `title`, `year`, `trim`, `price`, `mileage`, `sunroof`, `province`, `vehicle`, optionally `desc`, `source` (dealership name), `is_fallback`, `is_new`, `first_seen`, `days_on_radar`, and a `sources` list (`[{"name","url"}]` — every site the car is on, from dedup). `dealer_name_by_site` / `dealer_province_by_site` maps resolve a site to its display name / fallback province.
- **Province detection** (`_normalize_province`, `_postal_to_province`, `CANADA_PROVINCES`, `PROVINCE_NAMES`) — best-effort 2-letter code from any location text: full province name, then a delimited 2-letter code (`"Ottawa, ON"`), then a postal prefix. Each parser sets `province` where it can (AutoTrader from the detail href, dealer JSON-LD from `PostalAddress.addressRegion`, dealers from config). Kijiji/Clutch usually can't (→ `None`).
- `_listing_value_score()` — ranking (lower = better): tuple `(over_cap, price + mileage_penalty + sunroof_bonus, km)`; over-cap mileage is pushed to the bottom.
- `DEALERS` — fallback list used only if `dealers.json` fails to load.

## Search / scraping logic

**Design rationale:** headless rendering of the heavy marketplaces from cloud IPs is exactly the fingerprint they anti-bot-block, and generic guess-selectors rarely matched real markup. So each site is hit at its **structured-data endpoint** instead (JSON API / JSON-LD), which is more reliable and returns clean URLs + price/mileage/year. Every source is wrapped in try/except and logs its result count.

`scrape_and_populate_listings()` runs per vehicle, **collecting from ALL sources** (not stopping at first success):

1. **Kijiji RSS** (`parse_kijiji_rss`) — XML feed (BeautifulSoup XML parser). Price, mileage, year, direct URL. Most reliable source.
2. **AutoTrader.ca** (`parse_autotrader_api`) — warms a `requests` session against the search URL, then POSTs a JSON payload to `/Refinement/Search` (`Proximity: -1` = National). The `AdsHtml` fragment is parsed by `_parse_autotrader_ads_html` for `/a/…` links. **Playwright fallback** if the API returns nothing.
   - **Cards carry distance, not odometer.** With a National search that distance is large and was once misread as mileage. Fix: the parser sets `mileage: None` and `_enrich_mileage_from_detail` fetches each detail page for the real odometer (`_extract_odometer` reads `mileageFromOdometer.value` / `mileageInKmRaw` / `stmil` / `classified_mileage`). The per-year cap is then enforced by `_within_caps`. Detail pages are fetchable via plain `requests` even where the search API is challenged.
3. **CarGurus.ca** — **not scraped (manual quick-link).** Behind **DataDome** (CAPTCHA); verified unscrapable for free even from a residential IP. `parse_cargurus_api` short-circuits `return []`; the old JSON-API code is preserved but unreachable.
4. **Kijiji Web** (`parse_kijiji_listings`) — plain `requests` + BeautifulSoup, with a generic anchor-scan fallback.
5. **Clutch.ca** — **not scraped (manual quick-link).** Rebuilt as a React SPA behind a WAF; the `__NEXT_DATA__` blob is gone and the JSON API ignores filters, omits price, and throttles to empty `HTTP 202`. `parse_clutch_api` short-circuits `return []`.
6. **Local dealer websites** (`find_dealer_listings`, per-host `_probe_one_dealer`) — probes `dealers.json` + `POPULAR_DEALER_SITES` + `dealer_sites.json` (deduped by website). **Politeness-first:** each host is probed **sequentially** (with a `DEALER_REQUEST_DELAY` pause), only `DEALER_MAX_WORKERS` hosts at once, and probing **stops at the first path that yields a match** (~1–2 requests/host). `_dealer_probe_paths` returns a short most-productive-first list: `/inventory?make=&model=`, `/en/used-inventory?make=&model=`, `/occasion?make=&model=`, `/occasion/recherche.html?make=&model=`, then bare index fallbacks. If a **filtered** path renders inventory JSON-LD (`_has_vehicle_jsonld`) but matches nothing, remaining paths are skipped. **Limitation:** pure client-side SPA dealers expose no JSON-LD → contribute nothing (aggregators cover them). Two extraction strategies per page:
   - **JSON-LD** (`_extract_jsonld_vehicles`) — schema.org `Car`/`Vehicle`/`Product` from `<script type="application/ld+json">`. The reliable path (D2C Media / EDealer / Convertus / Sincro). Handles quirks (detail URL on `offers.url`; year embedded in `name`).
   - **Strict anchor scanning (fallback)** — a link is accepted only if its **own visible text** names make + a full model/alias token group, the **href looks like a specific detail page** (`_looks_like_vehicle_detail`), and the **slug doesn't name a different make** (`_url_names_other_make`). Matching on the anchor's own text (not a greedy ancestor blob) fixed a wrong-vehicle bug where a probed non-matching store echoed the search terms in breadcrumbs.
   - **Mileage enrichment** (`_enrich_mileage_from_detail` + `_extract_odometer`) — dealer JSON-LD omits the odometer (it's a hidden detail-page field, e.g. `vehicle_odometer`). Dedup runs **before** enrichment so each detail page is fetched once; the mileage cap is re-applied **after**. Same helper also enriches AutoTrader.
6b. **Otogo.ca** (`parse_otogo`) — a Quebec aggregator (Nuxt SSR, plain `requests`). Runs only for a vehicle with an `otogo` URL (Outlander only). Reads year/make/model/trim/mileage/price from each `/en/car/…` card; filters by year, model, and caps. **PURCHASE listings** → ranked in the normal tables. Cards carry price + mileage, so no enrichment needed.
7. **LeaseBusters.com** (`parse_leasebusters`) — lease-**transfer** marketplace, scraped server-side (no browser). Runs only for a vehicle with a `leasebusters` config (Outlander: `{"category_id": 7, "make_id": 31}`). GET → antiforgery token/cookie, then POST each result page to `/vehicle-search-result`. `_parse_leasebusters_cards` reads monthly payment, odometer, city, months remaining, colour. **Sunroof confirmed per listing** (`_leasebusters_detail_has_sunroof` + trim map — either positive → keep). Only confirmed-sunroof, 2023–2024 kept. Results go into the **separate** `LEASEBUSTERS_LISTINGS` global (price is a **monthly payment**, not a buy price — mixing would corrupt the ranking).

After collection, `_dedup_listings` collapses duplicates, then `_within_caps` drops anything over its year-specific mileage **or** price cap (the broad-query second pass). If zero remain for a vehicle, a fallback entry with the AutoTrader search URL is added (`is_fallback: True`).

**Deduplication (`_dedup_listings`):** the same car surfaces from multiple dealer probe paths and multiple marketplaces. Two passes: (1) exact normalized-URL dedup (`_norm_url`), then (2) a **content-signature** dedup (`_dedup_signature`) keyed on `(vehicle, year, mileage)` when mileage is known (exact km ≈ a unique fingerprint — trim is intentionally excluded so cross-posts whose trim text differs still merge), falling back to `(vehicle, year, trim, price)`, then the normalized URL. When two entries share a signature, `_better_listing` keeps the **lower-priced** one (so its URL becomes the row's primary link and Price is the lowest), carries over a sunroof flag / mileage / richer description / province, and **unions the two twins' `sources`** (deduped by display name) so the Source column can list every website the car is on. Colour is not used (not reliably present across sources); if real dupes still slip through because a site rounds/omits the odometer, tightening the signature is the next step.

**Facebook / Myers** — not scraped (auth / SPA). Manual quick-link buttons.

**Marketplace Quick Links** — built in the `for wanted in WANTED_VEHICLES` loop in `generate_email_html`: AutoTrader, CarGurus, Kijiji, Clutch, Facebook, Myers, plus **Otogo.ca** and **LeaseBusters** buttons only when the vehicle has those `urls` keys.

### HTTP / API helpers

- `http_get` / `http_get_json` — GET text / JSON, with `MAX_RETRIES` + `REQUEST_DELAY` backoff.
- `http_post_json` — POSTs a JSON body (AutoTrader); returns parsed JSON, `{"_raw": <text>}`, or `None`.
- `fetch_rendered_html` — Playwright renderer, used **only** as the AutoTrader fallback.

**Reliability caveat:** the JSON APIs are frequently rate-limited / anti-bot-challenged **not only from GitHub IPs** (reproduced from a residential machine). CarGurus (DataDome) and Clutch (WAF) are effectively unscrapable for free (manual links). When AutoTrader is challenged the logs show the failure and it falls back or contributes nothing; **Kijiji RSS is the most consistently reachable**, dealer JSON-LD second. **You generally cannot reproduce a live scrape from a dev machine** — rely on the per-source count logs from a real run, and on detail-page HTML (which *is* fetchable) to verify individual listings.

### Email output (ranked tables, grouped by region)

Opens with a **Search Criteria box** (`_criteria_summary_html`) built directly from `WANTED_VEHICLES` (Vehicle / Model Years / Max Price / Max Mileage, via `_fmt_cap`), so it can't drift. Notes explain: nationwide; sunroof is a ranking bonus (not required); the LeaseBusters section is separate; an **Excluded trims** line (dynamic from `exclude_trims`); and a one-liner on the **Tracked** column.

`generate_email_html` groups the ranked **purchase** listings into **one 2023–2024 box** with region tables (email clients can't do interactive filtering, so grouping is server-side), bucketed by `province`:

- **Alberta** table (`province == "AB"`) — rendered **first**, with a "5% GST — budget up to $38,000 (usually the lowest total cost)" note (dynamic from `ab_max_price`).
- **Ontario, Quebec & Other** table (`province != "AB"`) — everything else incl. unknown-province, with a **Province** column. Nothing is dropped.

**LeaseBusters section** (`_leasebusters_section_html`) — its own green box from `LEASEBUSTERS_LISTINGS`. Columns **#, Vehicle, Monthly, Odometer, Months Left, Location, Sunroof**, cheapest-monthly first. Empty-state row when none.

**Recently Sold / Removed section** (`_sold_section_html`) — a slate-accented box from the `SOLD_LISTINGS` global (built in `mark_new_and_update_seen`). Columns **#, Vehicle, Last Price, Mileage, Source, Days on Market, Removed**, most-recently-removed first. **Days on Market** = `last_seen − first_seen`; **Removed** = days since `sold_on`. Rendered after LeaseBusters, before the quick links. Because it's snapshot-driven, a car shows here for `SOLD_DISPLAY_DAYS` even though it's no longer scraped; if it reappears it's un-marked and returns to the ranked tables.

Helpers (local to `generate_email_html`): `listing_row(rank, listing, show_province=False)`, `_thead`, `_render_table` (empty-state row + pushes unknown-province listings to the bottom via a stable secondary sort), `_table_heading` / `_box_heading`. Each table ranks independently from 1.

Columns: **Rank, Vehicle, Price, Mileage, [Province], Description, Source, Tracked** (Sunroof folded into Description; Province only on the mixed table).

- **Vehicle** (`_vehicle_label`) — a clean `YEAR Make Model Trim` label (trim via `_clean_trim`), linked to the (cheapest) listing.
- **Price** — the lowest price across the car's sources, with a small `_price_history_html` note beneath it when the tracked price has changed (green ▼ drop / red ▲ rise vs. the first price recorded).
- **Description** (`_short_description`) — up to 5 feature tags via `FEATURE_PATTERNS`; empty → em-dash.
- **Sunroof** is trim-aware (`_sunroof_status` + `SUNROOF_BY_TRIM`): `Sunroof` when the text or trim confirms one, `No Sunroof` when the trim confirms none (Outlander ES = none; panoramic standard LE and up), omitted when unknown.
- **Source** — **every** website the car is listed on, each a separate link (` · `-separated), from the listing's `sources` list (or a single inferred source). Cell wraps.
- **Tracked** — days-on-radar from `listing["days_on_radar"]`: `Today` (age 0), `N day(s)`, em-dash when unknown. Display-only, **not** a ranking factor. On the first run after the seen-store format upgrade, pre-existing URLs have no recorded date → show em-dash for that run, then count forward.
- **NEW pill** — for `is_new` listings; a top banner counts them. Only when scraping ran.
- **Source-health footer** — reads `SOURCE_COUNTS`. Automated sources show their count (green, or **red `0`** = blocked/failed/empty this run); **CarGurus/Clutch show greyed `(manual)`** (intentionally not scraped).

Excel attachment (`generate_results_xlsx`, openpyxl) — 4 tabs: **Search Results** (ranked, filterable; numeric Price/Mileage/**Days Tracked**; Source = comma-joined site names; a "View" link + a **Price History** text column per row), **Lease Takeovers** (LeaseBusters), **Dealers** (every probed dealer + a filtered-inventory link), and **Recently Sold** (from `SOLD_LISTINGS`: Vehicle/Year/Trim/Last Price/Mileage/Province/Source/**Days on Market**/Removed/First Seen/Last Seen/link/**Price History**). Guarded — if openpyxl is missing or the build throws, the email still sends without the file.

## Scheduling

**Goal:** exactly **one automatic email per day, landing ~8:30 AM Eastern**; if an attempt fails, **retry that day until one sends**; **manual runs are fully independent**. The crons **target ~6:30 AM (2 h early) to pre-compensate for GitHub's consistent ~2 h delay**, so the delayed run lands near 8:30.

`search.yml` defines **three** UTC cron triggers (a ~6:30 AM primary in both DST regimes + two hourly morning backups), all on the **off-peak minute `:37`** (GitHub's queue is most delayed at `:00`/`:30`):

- `37 10 * * *` — 6:37 AM EDT (summer primary) / 5:37 AM EST (winter: rejected by the window, too early)
- `37 11 * * *` — 7:37 AM EDT (summer backup) / 6:37 AM EST (winter primary)
- `37 12 * * *` — 8:37 AM EDT (summer backup) / 7:37 AM EST (winter backup) — a ~30 s no-op once the day's email is out

(Conversion: 6:37 AM EDT = 10:37 UTC, 6:37 AM EST = 11:37 UTC.) Only **one** trigger sends — the record-only-on-success dedup makes the rest skip. **Trimmed from five to three** (V4.15) after run history showed the primary landing and sending every day: the two backups exist only for the rare day GitHub drops/badly delays the primary, keeping a safety net in both seasons without the pile of no-op runs (each no-op still spends a couple of Actions minutes installing deps before it skips). Trade-off: still no afternoon retry if GitHub delays every morning trigger past midday.

**Retry-until-sent guard.** The guard:
- accepts a **6 AM–10 PM Eastern window** (`6 <= est_now.hour <= 21`) — rejects only the too-early ~5:37 AM EST winter fire; wide ceiling still accepts a heavily-delayed morning trigger;
- records the day done in **`run_state.json`** (`{"last_run_date_est": "YYYY-MM-DD"}`, committed back) **only when the email actually sent** (`if sent and not is_manual`). A failed/delayed attempt leaves the day unrecorded so the next trigger retries;
- treats **manual runs as independent** — `is_manual` bypasses the window + once-per-day check and never reads/writes `run_state.json` (trade-off: on a day you also run manually you may get two emails — intended).

The first trigger that lands in-window **and** sends records the date; later triggers that day skip. The workflow's `concurrency` group serializes overlapping runs so two can never double-send. **The pre-compensation is a heuristic** — GitHub gives no on-time guarantee, so the retry-until-sent design (not the exact cron time) is what guarantees the daily email lands.

## Secrets / environment variables

Required repository secrets: `GMAIL_ADDRESS`, `GMAIL_PASSWORD`, `RECIPIENT_EMAIL`.

Other env vars:
- `ENABLE_SCRAPE` (default `'0'`, set to `'1'` by the workflow)
- `REQUEST_DELAY` (`'1.0'`), `MAX_RETRIES` (`'2'`)
- `GITHUB_EVENT_NAME` — set by the workflow; drives the manual-vs-scheduled guard
- **Dealer-probe politeness knobs** (deliberately gentle): `DEALER_MAX_WORKERS` (`'6'`), `DEALER_REQUEST_DELAY` (`'0.6'`), `DEALER_MAX_SITES` (`'0'` = no cap)
- **Criteria overrides** (`_apply_criteria_env_overrides()`, from `workflow_dispatch` inputs; unset = hardcoded default; when set, the URL cap params are rewritten): `OUTLANDER_YEAR_MIN`, `OUTLANDER_YEAR_MAX`, `OUTLANDER_PRICE_NEWER` (2023+), `OUTLANDER_MILEAGE`.

## GitHub Actions workflow steps (`search.yml`)

Checkout (`persist-credentials: true`) → Set up Python 3.12 (pip cache) → install `requirements.txt` + `playwright install chromium` → run script (with env vars) → upload HTML/xlsx artifacts (7-day retention) → commit generated HTML **and `seen_listings.json` and `run_state.json`** back to `main` (non-failing `|| true`) → deploy to `gh-pages` via `peaceiris/actions-gh-pages@v4` (`keep_files: true`).

**Hardening:** a `concurrency` group (`vehicle-search`) prevents overlap; `timeout-minutes: 30` caps a hung run; the run step is unmasked so a crash fails the run and GitHub emails you; `workflow_dispatch` is a bare **"Run workflow" button**.

## Requirements.txt

`requests`, `beautifulsoup4`, `lxml`, `pytz`, `tqdm`, `playwright`, `openpyxl`. The workflow runs `pip install -r requirements.txt` then `playwright install chromium`.
