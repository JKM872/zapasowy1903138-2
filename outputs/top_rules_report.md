# TOP rules – holdout report

Generated 2026-11-23T12:21:13Z. Tuning 2026-09-12..2026-11-06 (n=4566, halves split at 2026-10-23); holdout 2026-11-07..2026-11-22 (16 days). The learner never reads holdout rows. Flat 1u, draw = loss, ROI −5% = profit × 0.95; hockey/basketball/baseball 3-way quotes re-priced to the 2-way equivalent ("2-way"); "as stored" = published prices. Max DD in units at −5%. CI = bootstrap 95% (1000×) of ROI −5%.

Segment decisions: {'exclude': 68, 'inherit': 74, 'allow': 6}

## Gate in use by TOP

Mode: **shadow**. The learned rules are enforced automatically only when a rebuild keeps >= 3 TOP picks/day on the holdout with ROI −5% > +0% (TOP replay after rules + floor). Otherwise TOP applies the safe gate (tennis and basketball priced below 1.80 excluded, everything else as evaluate()) and each pick records the learned decision (`learnedDecision`, `learnedSegment`).

This build: enforce = False; holdout TOP replay after rules: 20 picks, 1.2/day, ROI -5% +3.2% (needs >= 3/day and > +0%).

**Caveat (holdout leak):** the 1.80 cut of the safe gate was chosen in the data audit, which also looked at the holdout days, so its holdout numbers below ("as applied") are optimistic. It is re-validated forward on the first 14 settled days from 2026-10-27.

### Forward check of the 1.80 cut (2026-10-27..2026-11-09, TOP replay, 2-way)

Status: **NOT confirmed: picks removed by the 1.80 cut were profitable forward - review the cut**

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| removed by the cut | 106 | 106.0 | 68.9% | +5.5% | +3.7% | — | 9.7 |
| kept | 132 | 132.0 | 53.8% | -2.5% | -4.7% | — | 16.71 |
| removed, basketball | 47 | 47.0 | 63.8% | -4.1% | -5.8% | — | 7.89 |
| removed, tennis | 59 | 59.0 | 72.9% | +13.2% | +11.2% | — | 2.89 |

## Candidates TOP could publish (structural gates, grade A/B/C)

### 2-way prices

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 3156 | 197.2 | 56.1% | -4.6% | -6.6% | -9.6 .. -3.6 | 216.96 |
| after (rules + floor) | 130 | 8.1 | 61.5% | +1.3% | -0.7% | -14.2 .. +11.7 | 11.29 |
| as applied (shadow) | 2449 | 153.1 | 54.1% | -4.3% | -6.4% | -10.2 .. -3.1 | 161.77 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 4 | 50.0% | -19.8% | -21.3% | 0 | — | — | — |
| basketball | 571 | 60.9% | -5.9% | -7.6% | 0 | — | — | — |
| football | 1694 | 51.9% | -4.0% | -6.2% | 0 | — | — | — |
| handball | 122 | 50.8% | -13.6% | -15.4% | 64 | 53.1% | -10.8% | -12.6% |
| hockey | 392 | 61.0% | -5.5% | -7.2% | 0 | — | — | — |
| rugby | 10 | 60.0% | -14.3% | -15.6% | 0 | — | — | — |
| tennis | 189 | 62.4% | -3.3% | -5.0% | 0 | — | — | — |
| volleyball | 174 | 66.1% | +0.9% | -0.9% | 66 | 69.7% | +13.0% | +10.9% |

### as stored

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 3156 | 197.2 | 56.1% | -1.5% | -3.6% | — | 126.93 |
| after (rules + floor) | 130 | 8.1 | 61.5% | +1.3% | -0.7% | — | 11.29 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 4 | 50.0% | -15.0% | -16.8% | 0 | — | — | — |
| basketball | 571 | 60.9% | -5.9% | -7.6% | 0 | — | — | — |
| football | 1694 | 51.9% | -4.0% | -6.2% | 0 | — | — | — |
| handball | 122 | 50.8% | -13.6% | -15.4% | 64 | 53.1% | -10.8% | -12.6% |
| hockey | 392 | 61.0% | +19.9% | +16.9% | 0 | — | — | — |
| rugby | 10 | 60.0% | -14.3% | -15.6% | 0 | — | — | — |
| tennis | 189 | 62.4% | -3.3% | -5.0% | 0 | — | — | — |
| volleyball | 174 | 66.1% | +0.9% | -0.9% | 66 | 69.7% | +13.0% | +10.9% |

## TOP replay (current evaluate())

### 2-way prices

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 345 | 21.6 | 61.7% | -0.2% | -2.1% | -10.6 .. +6.2 | 19.91 |
| after (rules + floor) | 20 | 1.2 | 65.0% | +5.2% | +3.2% | -29.3 .. +35.0 | 3.1 |
| as applied (shadow) | 203 | 12.7 | 56.7% | -2.8% | -4.8% | -16.3 .. +6.9 | 15.21 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| basketball | 98 | 69.4% | +5.4% | +3.6% | 0 | — | — | — |
| football | 81 | 38.3% | -19.4% | -21.5% | 0 | — | — | — |
| handball | 14 | 57.1% | -6.4% | -8.3% | 11 | 54.5% | -11.2% | -12.9% |
| hockey | 72 | 72.2% | +10.1% | +8.2% | 0 | — | — | — |
| rugby | 2 | 100.0% | +37.5% | +35.6% | 0 | — | — | — |
| tennis | 56 | 66.1% | +5.0% | +3.1% | 0 | — | — | — |
| volleyball | 22 | 68.2% | -0.3% | -1.9% | 9 | 77.8% | +25.2% | +22.8% |

### as stored

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 345 | 21.6 | 61.7% | +5.9% | +3.7% | — | 13.23 |
| after (rules + floor) | 20 | 1.2 | 65.0% | +5.2% | +3.2% | — | 3.1 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| basketball | 98 | 69.4% | +5.4% | +3.6% | 0 | — | — | — |
| football | 81 | 38.3% | -19.4% | -21.5% | 0 | — | — | — |
| handball | 14 | 57.1% | -6.4% | -8.3% | 11 | 54.5% | -11.2% | -12.9% |
| hockey | 72 | 72.2% | +39.1% | +35.8% | 0 | — | — | — |
| rugby | 2 | 100.0% | +37.5% | +35.6% | 0 | — | — | — |
| tennis | 56 | 66.1% | +5.0% | +3.1% | 0 | — | — | — |
| volleyball | 22 | 68.2% | -0.3% | -1.9% | 9 | 77.8% | +25.2% | +22.8% |

## Published TOP files in the holdout window

269 published (not withdrawn), 233 joined to settled holdout rows.

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| as stored | 233 | 14.6 | 54.1% | +3.2% | +0.7% | — | 14.61 |
| 2-way | 233 | 14.6 | 54.1% | -6.7% | -8.7% | — | 26.52 |

## Rules (tuning window, non-inherit segments)

| segment | level | n | hit | ROI −5% | H1 | H2 | decision | pCal | floor |
|---|---|---|---|---|---|---|---|---|---|
| baseball | sport | 119 | 60.5% | -9.7% | -8.7% | -15.0% | exclude | — | — |
| baseball|1.4-1.6 | sport×band | 53 | 54.7% | -19.2% | -21.6% | -5.6% | exclude | — | — |
| baseball|grade:B | sport×grade | 56 | 58.9% | -13.0% | -7.5% | -38.6% | exclude | — | — |
| baseball|tier:T1 | sport×tier | 87 | 60.9% | -11.4% | -12.1% | -5.3% | exclude | — | — |
| basketball | sport | 728 | 64.3% | -2.7% | -3.6% | -0.9% | exclude | — | — |
| basketball|1.0-1.4 | sport×band | 142 | 72.5% | -3.5% | +2.2% | -16.7% | exclude | — | — |
| basketball|1.0-1.4|away | sport×band×side | 55 | 69.1% | -8.1% | +3.9% | -43.0% | exclude | — | — |
| basketball|1.0-1.4|home | sport×band×side | 87 | 74.7% | -0.6% | +1.1% | -3.9% | exclude | — | — |
| basketball|1.4-1.6 | sport×band | 308 | 64.0% | -6.9% | -8.3% | -3.7% | exclude | — | — |
| basketball|1.4-1.6|away | sport×band×side | 132 | 59.8% | -12.8% | -18.0% | +2.6% | exclude | — | — |
| basketball|1.4-1.6|home | sport×band×side | 176 | 67.0% | -2.5% | -0.0% | -7.1% | exclude | — | — |
| basketball|1.6-1.8 | sport×band | 186 | 62.4% | +2.2% | +4.5% | -1.6% | exclude | — | — |
| basketball|1.6-1.8|away | sport×band×side | 74 | 67.6% | +11.4% | -3.3% | +35.7% | exclude | — | — |
| basketball|1.6-1.8|home | sport×band×side | 112 | 58.9% | -3.9% | +9.6% | -26.4% | exclude | — | — |
| basketball|1.8-2.0 | sport×band | 92 | 56.5% | +2.6% | -12.7% | +26.4% | exclude | — | — |
| basketball|1.8-2.0|home | sport×band×side | 59 | 54.2% | -1.3% | -11.2% | +21.3% | exclude | — | — |
| basketball|grade:B | sport×grade | 301 | 65.1% | -1.3% | -0.4% | -2.6% | exclude | — | — |
| basketball|grade:C | sport×grade | 381 | 63.8% | -4.0% | -5.2% | -0.2% | exclude | — | — |
| basketball|tier:T2 | sport×tier | 574 | 63.4% | -4.1% | -5.8% | -0.6% | exclude | — | — |
| basketball|tier:T3 | sport×tier | 111 | 73.0% | +10.0% | +13.5% | +2.2% | allow | 0.728 | 1.4 |
| football | sport | 2107 | 53.1% | -3.4% | -2.9% | -3.7% | exclude | — | — |
| football|1.4-1.6 | sport×band | 290 | 64.5% | -2.6% | +1.1% | -4.3% | exclude | — | — |
| football|1.4-1.6|away | sport×band×side | 114 | 67.5% | +2.0% | -2.6% | +4.7% | exclude | — | — |
| football|1.4-1.6|home | sport×band×side | 176 | 62.5% | -5.5% | +4.2% | -9.5% | exclude | — | — |
| football|1.6-1.8 | sport×band | 600 | 55.8% | -7.8% | -3.7% | -9.7% | exclude | — | — |
| football|1.6-1.8|away | sport×band×side | 220 | 60.5% | -0.1% | +12.0% | -7.6% | exclude | — | — |
| football|1.6-1.8|home | sport×band×side | 380 | 53.2% | -12.3% | -16.0% | -10.8% | exclude | — | — |
| football|1.8-2.0 | sport×band | 441 | 53.5% | -1.8% | -3.3% | -1.3% | exclude | — | — |
| football|1.8-2.0|away | sport×band×side | 192 | 57.3% | +5.3% | -0.7% | +8.5% | exclude | — | — |
| football|1.8-2.0|home | sport×band×side | 249 | 50.6% | -7.3% | -7.3% | -7.3% | exclude | — | — |
| football|2.0-2.5 | sport×band | 731 | 46.8% | -1.3% | -6.6% | +0.5% | exclude | — | — |
| football|2.0-2.5|away | sport×band×side | 367 | 45.0% | -5.2% | -2.1% | -6.5% | exclude | — | — |
| football|2.0-2.5|home | sport×band×side | 364 | 48.6% | +2.6% | -12.5% | +6.9% | exclude | — | — |
| football|grade:A | sport×grade | 64 | 56.2% | -2.1% | +8.5% | -4.8% | exclude | — | — |
| football|grade:B | sport×grade | 616 | 57.6% | +3.4% | +5.8% | +2.6% | allow | 0.576 | 1.78 |
| football|grade:C | sport×grade | 1427 | 50.9% | -6.5% | -6.5% | -6.4% | exclude | — | — |
| football|tier:T1 | sport×tier | 277 | 49.8% | -10.1% | -16.2% | -8.0% | exclude | — | — |
| football|tier:T2 | sport×tier | 1404 | 54.5% | -0.9% | +0.4% | -1.4% | exclude | — | — |
| football|tier:T3 | sport×tier | 426 | 50.5% | -7.6% | -7.4% | -7.7% | exclude | — | — |
| handball | sport | 150 | 60.7% | -1.3% | -0.7% | -3.3% | exclude | — | — |
| handball|1.6-1.8 | sport×band | 69 | 66.7% | +8.4% | +5.8% | +14.7% | allow | 0.665 | 1.6 |
| handball|grade:B | sport×grade | 59 | 71.2% | +15.3% | +15.0% | +16.0% | allow | 0.708 | 1.44 |
| handball|grade:C | sport×grade | 80 | 55.0% | -10.1% | -7.6% | -23.2% | exclude | — | — |
| handball|tier:T2 | sport×tier | 112 | 65.2% | +6.5% | +4.0% | +17.4% | allow | 0.651 | 1.57 |
| hockey | sport | 831 | 62.5% | -8.0% | -5.8% | -14.0% | exclude | — | — |
| hockey|1.0-1.4 | sport×band | 262 | 70.6% | -8.8% | -7.5% | -19.6% | exclude | — | — |
| hockey|1.0-1.4|away | sport×band×side | 104 | 64.4% | -16.5% | -15.7% | -24.5% | exclude | — | — |
| hockey|1.0-1.4|home | sport×band×side | 158 | 74.7% | -3.7% | -1.8% | -17.2% | exclude | — | — |
| hockey|1.4-1.6 | sport×band | 273 | 62.3% | -8.3% | -8.6% | -7.8% | exclude | — | — |
| hockey|1.4-1.6|away | sport×band×side | 106 | 57.5% | -14.8% | -15.5% | -13.6% | exclude | — | — |
| hockey|1.4-1.6|home | sport×band×side | 167 | 65.3% | -4.2% | -4.5% | -3.5% | exclude | — | — |
| hockey|1.6-1.8 | sport×band | 254 | 57.5% | -4.4% | +3.0% | -16.9% | exclude | — | — |
| hockey|1.6-1.8|away | sport×band×side | 120 | 57.5% | -4.3% | +8.1% | -22.2% | exclude | — | — |
| hockey|1.6-1.8|home | sport×band×side | 134 | 57.5% | -4.4% | -1.0% | -11.1% | exclude | — | — |
| hockey|grade:A | sport×grade | 74 | 66.2% | -1.0% | -8.2% | +6.7% | exclude | — | — |
| hockey|grade:B | sport×grade | 341 | 63.3% | -7.1% | -2.9% | -15.5% | exclude | — | — |
| hockey|grade:C | sport×grade | 416 | 61.1% | -10.0% | -7.4% | -21.8% | exclude | — | — |
| hockey|tier:T1 | sport×tier | 80 | 65.0% | +1.2% | +4.0% | -7.0% | exclude | — | — |
| hockey|tier:T2 | sport×tier | 705 | 63.1% | -7.5% | -5.0% | -14.3% | exclude | — | — |
| rugby | sport | 29 | 65.5% | -7.8% | -12.9% | +1.9% | exclude | — | — |
| tennis | sport | 500 | 58.2% | -12.0% | -14.5% | -8.8% | exclude | — | — |
| tennis|1.0-1.4 | sport×band | 61 | 65.6% | -11.9% | -15.7% | -6.7% | exclude | — | — |
| tennis|1.4-1.6 | sport×band | 239 | 61.9% | -10.0% | -9.9% | -10.1% | exclude | — | — |
| tennis|1.4-1.6|away | sport×band×side | 99 | 58.6% | -15.1% | -5.0% | -23.2% | exclude | — | — |
| tennis|1.4-1.6|home | sport×band×side | 140 | 64.3% | -6.4% | -12.6% | +1.5% | exclude | — | — |
| tennis|1.6-1.8 | sport×band | 154 | 54.5% | -10.7% | -16.7% | -2.4% | exclude | — | — |
| tennis|1.6-1.8|away | sport×band×side | 58 | 55.2% | -9.8% | -20.9% | +6.9% | exclude | — | — |
| tennis|1.6-1.8|home | sport×band×side | 96 | 54.2% | -11.3% | -14.0% | -7.6% | exclude | — | — |
| tennis|grade:B | sport×grade | 144 | 65.3% | -1.3% | -9.2% | +6.4% | exclude | — | — |
| tennis|grade:C | sport×grade | 308 | 54.9% | -17.3% | -16.0% | -19.4% | exclude | — | — |
| tennis|tier:T2 | sport×tier | 100 | 49.0% | -26.0% | -27.3% | -25.1% | exclude | — | — |
| tennis|tier:T? | sport×tier | 378 | 60.1% | -9.2% | -12.6% | -4.4% | exclude | — | — |
| volleyball | sport | 102 | 72.5% | +3.8% | +3.3% | +5.1% | allow | 0.723 | 1.41 |
| volleyball|tier:T3 | sport×tier | 57 | 73.7% | +5.6% | +9.0% | -0.7% | exclude | — | — |

## Context (not used for decisions)

Livesport-era qualified graded rows up to tuning.end (older engine, grade semantics differ):

| sport | n | hit | ROI −5% |
|---|---|---|---|
| baseball | 538 | 59.5% | +8.8% |
| basketball | 4089 | 62.3% | -0.6% |
| football | 14691 | 41.5% | -6.5% |
| handball | 928 | 66.7% | -2.5% |
| hockey | 1970 | 60.8% | -5.7% |
| tennis | 1266 | 60.4% | -7.9% |
| volleyball | 1013 | 68.6% | -6.9% |

Supabase cross-check (settled predictions in tuning window): {'skipped': 'SUPABASE_URL / key not set'}
