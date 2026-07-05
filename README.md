# phev-rav4-search

Automated weekly search for a **Mitsubishi Outlander PHEV** and a **Toyota RAV4 Prime** around Gatineau, QC. A GitHub Actions workflow runs the search, builds an HTML summary, and emails it to a recipient with a dealers list attached.

## What it searches

Each run looks for real listings across multiple sources, in this order, and falls back to a precise search link if no direct listing is found:

1. **Popular marketplaces:** AutoTrader.ca, CarGurus.ca, Kijiji, and Clutch.ca
2. **Facebook Marketplace** (best-effort; Facebook requires a logged-in session to show results, so this typically falls back to a direct search link rather than a specific listing)
3. **Local dealer websites** (see `dealers.json`) — their inventory/search pages are probed directly for a matching vehicle

### Trusted marketplace buttons

Every email includes quick-search buttons for:

- AutoTrader.ca
- CarGurus.ca
- Kijiji
- Clutch.ca
- Facebook Marketplace

## Schedule

The workflow runs every 3 days and sends the email at **7:00 AM Gatineau (US/Eastern) time**, year-round.

GitHub Actions cron always runs in UTC and has no concept of timezones or daylight saving time, so a single fixed UTC cron would drift by an hour twice a year. To handle this correctly, the workflow defines two cron triggers each run day — one tuned for Eastern Daylight Time and one for Eastern Standard Time — and `vehicle_search_automation.py` checks the real Eastern time at runtime, skipping whichever trigger does not correspond to 7 AM locally. The result is exactly one email sent at 7 AM Gatineau time, with daylight saving transitions handled automatically. Manual runs (`workflow_dispatch`) always proceed regardless of the time.

## Files

- `vehicle_search_automation.py` — scraper, HTML generator, and email sender
- `dealers.json` — local dealer list used for the "All Dealers" attachment and for direct dealer-site probing
- `dealers.html` / `gatineau_phev_rav4_search_results.html` — generated output, committed back to the repo and published via GitHub Pages after each run
- `.github/workflows/search.yml` — the scheduled GitHub Actions workflow
- `requirements.txt` — Python dependencies

## Setup

Configure these repository secrets for email sending:

- `GMAIL_ADDRESS`
- `GMAIL_PASSWORD` (an [App Password](https://myaccount.google.com/apppasswords), not your regular Gmail password)
- `RECIPIENT_EMAIL`

Optionally set the `VIEW_DEALERS_URL` repository variable to link to the published dealers page.

To run locally:

```bash
pip install -r requirements.txt
ENABLE_SCRAPE=1 python vehicle_search_automation.py
```

## Recent fixes

- **Vehicle name linked to the wrong listing:** the AutoTrader scraper could match editorial/review articles (e.g. "expert reviews") instead of an actual for-sale listing, and the fallback link builder truncated multi-word models (e.g. "Outlander PHEV" -> "Outlander"), which could send users to the regular gas model instead of the PHEV. Both are fixed — editorial/review/blog pages are now excluded, and full model names are preserved.
- **Added Clutch.ca** as a trusted marketplace alongside AutoTrader, CarGurus, and Kijiji.
- **Added Facebook Marketplace and local dealer sites** to the automated search, not just the popular marketplaces.
- **Fixed the send time** to 7:00 AM Gatineau time year-round, correctly handling daylight saving time.
