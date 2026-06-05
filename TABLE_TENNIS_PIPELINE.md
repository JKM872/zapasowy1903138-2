# 🏓 Table Tennis Pipeline (SofaScore-sourced)

A parallel scraping/prediction pipeline for **table tennis** that sources its
match list from **SofaScore** instead of LiveSport.

## Why SofaScore instead of LiveSport?

LiveSport lists too few table-tennis matches — it misses most amateur and
lower-tier events. SofaScore covers virtually all of them. So for table tennis
we pull the day's slate directly from SofaScore's `scheduled-events` API and
enrich each event with the same fan-vote / odds / H2H signals used elsewhere.

## Qualification priorities

Per requirements, the signals that matter (home/away is irrelevant for table tennis):

| Signal | Role |
|--------|------|
| **Odds** | REQUIRED — favourite must be ≥ 1.35 (value filter) |
| **H2H** | used when available (head-to-head record) |
| **Form** | general recent form (previous matches) |
| **Fan vote** | OPTIONAL bonus — amateur matches often have 0 votes and are still kept |

## How it works

`table_tennis_pipeline.py` sources the day's slate from SofaScore and runs:

| Phase | What happens |
|-------|--------------|
| FAZA 1 | `list_scheduled_events("table_tennis", date)` → all events for the day |
| FAZA 2a | **odds gate** — fetch odds (1 cheap call/event), keep only favourite ≥ 1.35 |
| FAZA 2b | enrich survivors ONLY: H2H, recent form, (optional) fan vote |
| FAZA 2.5 | score survivors with `TennisScoringEngine` (table-tennis profile) |
| FAZA 2.9 | unified `qualification_gate` (odds + future-only) |
| OUTPUT | `outputs/table_tennis_{date}.csv` + `results/matches_{date}_table_tennis.json`, optional Telegram |

**Why odds-first?** SofaScore's API 403s after ~700 calls. Listing a day can
return ~2000 table-tennis events. Fetching odds first (one call each) and
dropping everything without a clear favourite means H2H/form/votes are fetched
for only a handful of survivors — which avoids the Cloudflare 403 storm. A
circuit-breaker check (`is_sofascore_unreachable()`) also stops both loops
early if SofaScore goes down mid-run.

## Table-tennis scoring profile

Table tennis on SofaScore exposes **fan vote + odds + H2H**, but almost never
rankings, surface, or recent-form lists (unlike ATP/WTA tennis). The default
`TennisScoringEngine` weights/threshold assume that rich data and would
disqualify every table-tennis match. So the pipeline applies a dedicated
profile (`TT_WEIGHTS`, `TT_THRESHOLD` in `table_tennis_pipeline.py`):

```
odds 0.34 | h2h 0.26 | form 0.20 | sofascore 0.12 | serve_model 0.08
threshold = 25   (vs 45 for ATP/WTA tennis)
```

This is re-asserted **after** engine construction so a future tennis
calibration file can never silently override the table-tennis profile. Fan
vote keeps weight but contributes a neutral 0.5 when absent, so vote-less
amateur matches are **not** penalised.

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
