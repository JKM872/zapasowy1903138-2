# TOP rules – holdout report

Generated 2026-11-09T11:23:08Z. Tuning 2026-09-12..2026-10-23 (n=2456, halves split at 2026-10-10); holdout 2026-10-24..2026-11-08 (16 days). The learner never reads holdout rows. Flat 1u, draw = loss, ROI −5% = profit × 0.95; hockey/basketball/baseball 3-way quotes re-priced to the 2-way equivalent ("2-way"); "as stored" = published prices. Max DD in units at −5%. CI = bootstrap 95% (1000×) of ROI −5%.

Segment decisions: {'exclude': 57, 'inherit': 86, 'allow': 4}

## Gate in use by TOP

Mode: **shadow**. The learned rules are enforced automatically only when a rebuild keeps >= 3 TOP picks/day on the holdout with ROI −5% > +0% (TOP replay after rules + floor). Otherwise TOP applies the safe gate (tennis and basketball priced below 1.80 excluded, everything else as evaluate()) and each pick records the learned decision (`learnedDecision`, `learnedSegment`).

This build: enforce = False; holdout TOP replay after rules: 1 picks, 0.1/day, ROI -5% -100.0% (needs >= 3/day and > +0%).

**Caveat (holdout leak):** the 1.80 cut of the safe gate was chosen in the data audit, which also looked at the holdout days, so its holdout numbers below ("as applied") are optimistic. It is re-validated forward on the first 14 settled days from 2026-10-27.

### Forward check of the 1.80 cut (2026-10-27..2026-11-09, TOP replay, 2-way)

Status: **pending (13/14 settled days)**

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| removed by the cut | 84 | 84.0 | 70.2% | +7.5% | +5.6% | — | 7.22 |
| kept | 77 | 77.0 | 57.1% | +3.4% | +1.1% | — | 7.03 |
| removed, basketball | 30 | 30.0 | 63.3% | -5.5% | -7.1% | — | 5.78 |
| removed, tennis | 54 | 54.0 | 74.1% | +14.7% | +12.7% | — | 2.72 |

## Candidates TOP could publish (structural gates, grade A/B/C)

### 2-way prices

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 2129 | 133.1 | 55.6% | -2.4% | -4.5% | -8.3 .. -0.9 | 103.92 |
| after (rules + floor) | 4 | 0.2 | 75.0% | +21.3% | +18.9% | -60.7 .. +62.9 | 1.0 |
| as applied (shadow) | 1743 | 108.9 | 54.2% | -1.7% | -3.9% | -8.2 .. +0.5 | 75.92 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 15 | 60.0% | -10.9% | -12.4% | 0 | — | — | — |
| basketball | 222 | 62.2% | -2.3% | -4.1% | 1 | 100.0% | +55.0% | +52.2% |
| football | 1423 | 52.8% | -1.2% | -3.5% | 0 | — | — | — |
| handball | 32 | 59.4% | -0.3% | -2.3% | 3 | 66.7% | +10.0% | +7.8% |
| hockey | 176 | 58.0% | -9.3% | -11.0% | 0 | — | — | — |
| rugby | 7 | 71.4% | +1.9% | +0.3% | 0 | — | — | — |
| tennis | 214 | 61.2% | -5.8% | -7.4% | 0 | — | — | — |
| volleyball | 40 | 72.5% | +3.9% | +2.3% | 0 | — | — | — |

### as stored

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 2129 | 133.1 | 55.6% | -0.5% | -2.7% | — | 65.82 |
| after (rules + floor) | 4 | 0.2 | 75.0% | +21.3% | +18.9% | — | 1.0 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 15 | 60.0% | -4.9% | -6.6% | 0 | — | — | — |
| basketball | 222 | 62.2% | -2.3% | -4.1% | 1 | 100.0% | +55.0% | +52.2% |
| football | 1423 | 52.8% | -1.2% | -3.5% | 0 | — | — | — |
| handball | 32 | 59.4% | -0.3% | -2.3% | 3 | 66.7% | +10.0% | +7.8% |
| hockey | 176 | 58.0% | +13.6% | +10.9% | 0 | — | — | — |
| rugby | 7 | 71.4% | +1.9% | +0.3% | 0 | — | — | — |
| tennis | 214 | 61.2% | -5.8% | -7.4% | 0 | — | — | — |
| volleyball | 40 | 72.5% | +3.9% | +2.3% | 0 | — | — | — |

## TOP replay (current evaluate())

### 2-way prices

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 175 | 10.9 | 64.0% | +6.3% | +4.1% | -9.2 .. +16.4 | 10.59 |
| after (rules + floor) | 1 | 0.1 | 0.0% | -100.0% | -100.0% | — | 1.0 |
| as applied (shadow) | 85 | 5.3 | 56.5% | +3.3% | +1.0% | -19.0 .. +19.8 | 7.03 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 6 | 83.3% | +18.8% | +17.1% | 0 | — | — | — |
| basketball | 35 | 62.9% | -3.9% | -5.5% | 0 | — | — | — |
| football | 45 | 48.9% | +5.0% | +2.2% | 0 | — | — | — |
| handball | 5 | 40.0% | -31.4% | -32.8% | 1 | 0.0% | -100.0% | -100.0% |
| hockey | 19 | 63.2% | -2.4% | -4.1% | 0 | — | — | — |
| tennis | 62 | 74.2% | +15.8% | +13.8% | 0 | — | — | — |
| volleyball | 3 | 100.0% | +37.7% | +35.8% | 0 | — | — | — |

### as stored

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 175 | 10.9 | 64.0% | +8.3% | +6.1% | — | 10.31 |
| after (rules + floor) | 1 | 0.1 | 0.0% | -100.0% | -100.0% | — | 1.0 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 6 | 83.3% | +27.3% | +25.1% | 0 | — | — | — |
| basketball | 35 | 62.9% | -3.9% | -5.5% | 0 | — | — | — |
| football | 45 | 48.9% | +5.0% | +2.2% | 0 | — | — | — |
| handball | 5 | 40.0% | -31.4% | -32.8% | 1 | 0.0% | -100.0% | -100.0% |
| hockey | 19 | 63.2% | +13.6% | +11.1% | 0 | — | — | — |
| tennis | 62 | 74.2% | +15.8% | +13.8% | 0 | — | — | — |
| volleyball | 3 | 100.0% | +37.7% | +35.8% | 0 | — | — | — |

## Published TOP files in the holdout window

353 published (not withdrawn), 187 joined to settled holdout rows.

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| as stored | 187 | 11.7 | 59.9% | +15.0% | +12.3% | — | 8.36 |
| 2-way | 187 | 11.7 | 59.9% | +9.5% | +7.0% | — | 9.18 |

## Rules (tuning window, non-inherit segments)

| segment | level | n | hit | ROI −5% | H1 | H2 | decision | pCal | floor |
|---|---|---|---|---|---|---|---|---|---|
| baseball | sport | 104 | 60.6% | -9.3% | -9.8% | -7.9% | exclude | — | — |
| baseball|tier:T1 | sport×tier | 78 | 60.3% | -12.1% | -12.0% | -13.2% | exclude | — | — |
| basketball | sport | 506 | 64.8% | -2.8% | +0.5% | -4.8% | exclude | — | — |
| basketball|1.0-1.4 | sport×band | 101 | 76.2% | +1.5% | +0.5% | +2.5% | allow | 0.76 | 1.34 |
| basketball|1.0-1.4|home | sport×band×side | 58 | 75.9% | +1.1% | -7.2% | +8.3% | exclude | — | — |
| basketball|1.4-1.6 | sport×band | 222 | 64.4% | -6.5% | -9.3% | -4.9% | exclude | — | — |
| basketball|1.4-1.6|away | sport×band×side | 102 | 57.8% | -16.0% | -19.8% | -13.0% | exclude | — | — |
| basketball|1.4-1.6|home | sport×band×side | 120 | 70.0% | +1.6% | +4.2% | +0.5% | allow | 0.699 | 1.46 |
| basketball|1.6-1.8 | sport×band | 125 | 63.2% | +3.5% | +18.6% | -4.7% | exclude | — | — |
| basketball|1.6-1.8|away | sport×band×side | 50 | 62.0% | +2.0% | +23.5% | -12.3% | exclude | — | — |
| basketball|1.6-1.8|home | sport×band×side | 75 | 64.0% | +4.5% | +14.5% | -0.2% | exclude | — | — |
| basketball|1.8-2.0 | sport×band | 58 | 50.0% | -9.4% | -0.2% | -13.5% | exclude | — | — |
| basketball|grade:B | sport×grade | 193 | 66.8% | +0.4% | +5.1% | -2.7% | exclude | — | — |
| basketball|grade:C | sport×grade | 294 | 63.6% | -4.9% | -2.8% | -6.2% | exclude | — | — |
| basketball|tier:T2 | sport×tier | 405 | 63.5% | -4.6% | -2.7% | -5.8% | exclude | — | — |
| basketball|tier:T3 | sport×tier | 78 | 75.6% | +12.5% | +22.3% | +6.4% | allow | 0.754 | 1.35 |
| football | sport | 689 | 54.0% | -2.8% | -4.4% | -1.8% | exclude | — | — |
| football|1.4-1.6 | sport×band | 105 | 68.6% | +3.5% | -5.8% | +11.4% | exclude | — | — |
| football|1.4-1.6|home | sport×band×side | 58 | 70.7% | +6.6% | -1.4% | +14.6% | exclude | — | — |
| football|1.6-1.8 | sport×band | 214 | 57.5% | -5.2% | -0.5% | -9.0% | exclude | — | — |
| football|1.6-1.8|away | sport×band×side | 89 | 67.4% | +11.1% | +24.5% | -0.2% | exclude | — | — |
| football|1.6-1.8|home | sport×band×side | 125 | 50.4% | -16.8% | -19.1% | -14.9% | exclude | — | — |
| football|1.8-2.0 | sport×band | 135 | 51.9% | -4.8% | -14.1% | +1.9% | exclude | — | — |
| football|1.8-2.0|away | sport×band×side | 71 | 53.5% | -2.2% | -1.8% | -2.6% | exclude | — | — |
| football|1.8-2.0|home | sport×band×side | 64 | 50.0% | -7.7% | -33.6% | +5.8% | exclude | — | — |
| football|2.0-2.5 | sport×band | 218 | 45.0% | -5.0% | -4.1% | -5.3% | exclude | — | — |
| football|2.0-2.5|away | sport×band×side | 120 | 48.3% | +1.6% | -4.0% | +4.1% | exclude | — | — |
| football|2.0-2.5|home | sport×band×side | 98 | 40.8% | -13.0% | -4.3% | -17.1% | exclude | — | — |
| football|grade:B | sport×grade | 183 | 60.7% | +6.9% | -0.5% | +15.4% | exclude | — | — |
| football|grade:C | sport×grade | 490 | 51.4% | -6.5% | -7.0% | -6.2% | exclude | — | — |
| football|tier:T1 | sport×tier | 84 | 50.0% | -9.7% | -15.0% | -7.9% | exclude | — | — |
| football|tier:T2 | sport×tier | 491 | 55.0% | -1.3% | -2.8% | -0.3% | exclude | — | — |
| football|tier:T3 | sport×tier | 114 | 52.6% | -4.2% | -6.5% | -2.4% | exclude | — | — |
| handball | sport | 121 | 61.2% | -0.7% | +5.2% | -8.6% | exclude | — | — |
| handball|1.6-1.8 | sport×band | 52 | 67.3% | +9.3% | +1.5% | +17.7% | allow | 0.671 | 1.6 |
| handball|grade:C | sport×grade | 70 | 55.7% | -9.1% | +5.7% | -23.1% | exclude | — | — |
| handball|tier:T2 | sport×tier | 96 | 63.5% | +3.8% | +11.9% | -6.7% | exclude | — | — |
| hockey | sport | 656 | 63.7% | -7.2% | -4.1% | -11.4% | exclude | — | — |
| hockey|1.0-1.4 | sport×band | 236 | 71.2% | -8.2% | -6.1% | -15.3% | exclude | — | — |
| hockey|1.0-1.4|away | sport×band×side | 96 | 64.6% | -16.6% | -11.9% | -28.7% | exclude | — | — |
| hockey|1.0-1.4|home | sport×band×side | 140 | 75.7% | -2.5% | -2.5% | -2.5% | exclude | — | — |
| hockey|1.4-1.6 | sport×band | 210 | 61.9% | -9.1% | -11.2% | -7.1% | exclude | — | — |
| hockey|1.4-1.6|away | sport×band×side | 81 | 58.0% | -14.6% | -18.6% | -11.1% | exclude | — | — |
| hockey|1.4-1.6|home | sport×band×side | 129 | 64.3% | -5.7% | -6.9% | -4.4% | exclude | — | — |
| hockey|1.6-1.8 | sport×band | 178 | 59.6% | -0.8% | +12.6% | -13.2% | exclude | — | — |
| hockey|1.6-1.8|away | sport×band×side | 78 | 61.5% | +2.7% | +9.8% | -6.5% | exclude | — | — |
| hockey|1.6-1.8|home | sport×band×side | 100 | 58.0% | -3.5% | +15.5% | -17.2% | exclude | — | — |
| hockey|grade:B | sport×grade | 249 | 65.5% | -5.4% | -5.4% | -5.4% | exclude | — | — |
| hockey|grade:C | sport×grade | 360 | 62.8% | -8.2% | -3.2% | -14.7% | exclude | — | — |
| hockey|tier:T1 | sport×tier | 63 | 65.1% | +1.4% | +9.7% | -5.2% | exclude | — | — |
| hockey|tier:T2 | sport×tier | 555 | 64.5% | -6.7% | -3.9% | -10.9% | exclude | — | — |
| rugby | sport | 22 | 63.6% | -10.4% | -16.8% | -5.1% | exclude | — | — |
| tennis | sport | 288 | 56.2% | -14.9% | -21.2% | -9.9% | exclude | — | — |
| tennis|1.4-1.6 | sport×band | 127 | 61.4% | -11.1% | -17.4% | -6.9% | exclude | — | — |
| tennis|1.4-1.6|home | sport×band×side | 80 | 61.3% | -11.1% | -25.2% | +0.9% | exclude | — | — |
| tennis|1.6-1.8 | sport×band | 95 | 51.6% | -16.0% | -20.8% | -12.0% | exclude | — | — |
| tennis|1.6-1.8|home | sport×band×side | 58 | 51.7% | -15.7% | -21.8% | -9.6% | exclude | — | — |
| tennis|grade:B | sport×grade | 75 | 61.3% | -8.1% | -35.9% | +6.7% | exclude | — | — |
| tennis|grade:C | sport×grade | 196 | 55.1% | -16.2% | -18.0% | -14.3% | exclude | — | — |
| tennis|tier:T? | sport×tier | 230 | 57.8% | -12.8% | -17.8% | -9.2% | exclude | — | — |
| volleyball | sport | 70 | 71.4% | +3.3% | +9.6% | -1.5% | exclude | — | — |

## Context (not used for decisions)

Livesport-era qualified graded rows up to tuning.end (older engine, grade semantics differ):

| sport | n | hit | ROI −5% |
|---|---|---|---|
| baseball | 517 | 59.0% | +7.9% |
| basketball | 3847 | 62.9% | -0.1% |
| football | 14262 | 41.3% | -6.8% |
| handball | 868 | 67.2% | -1.3% |
| hockey | 1837 | 60.5% | -6.7% |
| tennis | 1141 | 60.2% | -8.0% |
| volleyball | 941 | 68.3% | -7.5% |

Supabase cross-check (settled predictions in tuning window): {'skipped': 'SUPABASE_URL / key not set'}
