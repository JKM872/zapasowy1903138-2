# 🏓 Table Tennis Pipeline (SofaScore-sourced)

A parallel scraping/prediction pipeline for **table tennis** that sources its
match list from **SofaScore** instead of LiveSport.

## Why SofaScore instead of LiveSport?

LiveSport lists too few table-tennis matches — it misses most amateur and
lower-tier events. SofaScore covers virtually all of them. So for table tennis
we pull the day's slate directly from SofaScore's `scheduled-events` API and
enrich each event with the same fan-vote / odds / H2H signals used elsewhere.

## How it works

`table_tennis_pipeline.py` mirrors the phases of `scrape_and_notify.py`, minus
the LiveSport scraping:

| Phase | What happens |
|-------|--------------|
| FAZA 1 | `list_scheduled_events("table_tennis", date)` → all events for the day |
| FAZA 2 | per-event enrichment: fan vote (`/event/{id}/votes`), odds (`/event/{id}/odds`), H2H (`/event/{id}/h2h`) |
| FAZA 2.1 | mandatory fan-vote gate — events without a SofaScore fan vote are dropped |
| FAZA 2.5 | scoring with `TennisScoringEngine` using a **table-tennis profile** |
| FAZA 2.9 | unified `qualification_gate` (odds + fan vote + future-only) |
| OUTPUT | `outputs/table_tennis_{date}.csv` + `results/matches_{date}_table_tennis.json`, optional Telegram |

Everything reuses the existing, battle-tested SofaScore HTTP stack
(`_api_get_json` → curl_cffi / FlareSolverr / Cloudflare WARP), so it inherits
all the Cloudflare-bypass machinery for free.

## Table-tennis scoring profile

Table tennis on SofaScore exposes **fan vote + odds + H2H**, but almost never
rankings, surface, or recent-form lists (unlike ATP/WTA tennis). The default
`TennisScoringEngine` weights/threshold assume that rich data and would
disqualify every table-tennis match. So the pipeline applies a dedicated
profile (`TT_WEIGHTS`, `TT_THRESHOLD` in `table_tennis_pipeline.py`):

```
h2h 0.30 | odds 0.32 | sofascore 0.28 | serve_model 0.05 | form 0.05
threshold = 25   (vs 45 for ATP/WTA tennis)
```

This is re-asserted **after** engine construction so a future tennis
calibration file can never silently override the table-tennis profile.

Calibrated so clear favourites with positive EV qualify while coin-flips do
not (verified in `test_table_tennis_pipeline.py`):

| Scenario | advanced_score | qualifies? |
|----------|---------------|-----------|
| 72/28 vote, 1.55/2.45 odds, H2H 4-2 | ~36 | ✅ |
| 60/40 vote, 1.85/2.00 odds, H2H 3-2 | ~16 | ❌ |
| 52/48 vote, near-even odds, H2H 1-1 | ~2 | ❌ |

## Running

```bash
# Today (UTC)
python table_tennis_pipeline.py

# Specific date, capped for testing, no Telegram
python table_tennis_pipeline.py --date 2026-06-04 --max-matches 50 --no-telegram
```

## GitHub Actions

`.github/workflows/scrape_table_tennis.yml` runs daily at 06:00 UTC (and on
manual dispatch). It stands up FlareSolverr + a Cloudflare WARP SOCKS5 proxy
(same as `scrape.yml`), runs the pipeline, uploads artifacts, and commits the
results JSON/CSV back to the repo (`[skip ci]`).

Required secrets/vars (same as the main scraper): `SOFASCORE_COOKIES`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ENABLED`, Supabase secrets.

## Integration points changed

- `sofascore_scraper.py` — added `table-tennis`/`table_tennis` to
  `SOFASCORE_SPORT_SLUGS` + `SPORTS_WITHOUT_DRAW`; new public helpers
  `list_scheduled_events()` and `get_event_h2h()`.
- `qualification_gate.py` — `table_tennis` entries in `SPORT_MIN_ODDS` (1.35)
  and `FAN_VOTE_THRESHOLDS` (55%).
- `telegram_notifier.py` — `table_tennis` odds/fan-vote thresholds, 🏓 emoji,
  and player-style pick labels. (Tennis behaviour intentionally unchanged.)
- New: `table_tennis_pipeline.py`, `test_table_tennis_pipeline.py`,
  `.github/workflows/scrape_table_tennis.yml`.

## Limitations / next steps

- The table-tennis profile weights/threshold are expert-tuned, not yet
  backtested against settled results (no historical table-tennis labels exist
  locally yet). Once results accumulate, run a backtest to calibrate.
- SofaScore H2H gives aggregate win counts, not per-match scorelines, so the
  H2H goal-margin signal isn't available for table tennis.
