# TOP rules – holdout report

Generated 2026-11-16T11:02:24Z. Tuning 2026-09-12..2026-10-30 (n=3301, halves split at 2026-10-16); holdout 2026-10-31..2026-11-15 (16 days). The learner never reads holdout rows. Flat 1u, draw = loss, ROI −5% = profit × 0.95; hockey/basketball/baseball 3-way quotes re-priced to the 2-way equivalent ("2-way"); "as stored" = published prices. Max DD in units at −5%. CI = bootstrap 95% (1000×) of ROI −5%.

Segment decisions: {'exclude': 63, 'inherit': 78, 'allow': 6}

## Gate in use by TOP

Mode: **shadow**. The learned rules are enforced automatically only when a rebuild keeps >= 3 TOP picks/day on the holdout with ROI −5% > +0% (TOP replay after rules + floor). Otherwise TOP applies the safe gate (tennis and basketball priced below 1.80 excluded, everything else as evaluate()) and each pick records the learned decision (`learnedDecision`, `learnedSegment`).

This build: enforce = False; holdout TOP replay after rules: 5 picks, 0.3/day, ROI -5% -3.9% (needs >= 3/day and > +0%).

**Caveat (holdout leak):** the 1.80 cut of the safe gate was chosen in the data audit, which also looked at the holdout days, so its holdout numbers below ("as applied") are optimistic. It is re-validated forward on the first 14 settled days from 2026-10-27.

### Forward check of the 1.80 cut (2026-10-27..2026-11-09, TOP replay, 2-way)

Status: **NOT confirmed: picks removed by the 1.80 cut were profitable forward - review the cut**

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| removed by the cut | 106 | 106.0 | 68.9% | +5.5% | +3.7% | — | 9.7 |
| kept | 131 | 131.0 | 54.2% | -1.8% | -4.0% | — | 15.71 |
| removed, basketball | 47 | 47.0 | 63.8% | -4.1% | -5.8% | — | 7.89 |
| removed, tennis | 59 | 59.0 | 72.9% | +13.2% | +11.2% | — | 2.89 |

## Candidates TOP could publish (structural gates, grade A/B/C)

### 2-way prices

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 3264 | 204.0 | 55.5% | -3.5% | -5.6% | -8.3 .. -2.4 | 198.56 |
| after (rules + floor) | 49 | 3.1 | 59.2% | +0.7% | -1.4% | -24.8 .. +21.4 | 4.49 |
| as applied (shadow) | 2636 | 164.8 | 54.4% | -2.3% | -4.4% | -7.9 .. -1.1 | 132.52 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 9 | 66.7% | +0.3% | -1.4% | 0 | — | — | — |
| basketball | 464 | 60.8% | -6.2% | -7.9% | 0 | — | — | — |
| football | 2039 | 52.6% | -1.8% | -4.1% | 0 | — | — | — |
| handball | 87 | 57.5% | -2.0% | -4.0% | 49 | 59.2% | +0.7% | -1.4% |
| hockey | 295 | 60.0% | -6.9% | -8.6% | 0 | — | — | — |
| rugby | 9 | 66.7% | -5.7% | -7.1% | 0 | — | — | — |
| tennis | 238 | 56.3% | -13.1% | -14.6% | 0 | — | — | — |
| volleyball | 123 | 68.3% | +2.9% | +1.1% | 0 | — | — | — |

### as stored

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 3264 | 204.0 | 55.5% | -1.3% | -3.5% | — | 129.58 |
| after (rules + floor) | 49 | 3.1 | 59.2% | +0.7% | -1.4% | — | 4.49 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 9 | 66.7% | +5.7% | +3.7% | 0 | — | — | — |
| basketball | 464 | 60.8% | -6.2% | -7.9% | 0 | — | — | — |
| football | 2039 | 52.6% | -1.8% | -4.1% | 0 | — | — | — |
| handball | 87 | 57.5% | -2.0% | -4.0% | 49 | 59.2% | +0.7% | -1.4% |
| hockey | 295 | 60.0% | +17.7% | +14.8% | 0 | — | — | — |
| rugby | 9 | 66.7% | -5.7% | -7.1% | 0 | — | — | — |
| tennis | 238 | 56.3% | -13.1% | -14.6% | 0 | — | — | — |
| volleyball | 123 | 68.3% | +2.9% | +1.1% | 0 | — | — | — |

## TOP replay (current evaluate())

### 2-way prices

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 304 | 19.0 | 59.5% | -1.3% | -3.2% | -12.4 .. +5.9 | 22.95 |
| after (rules + floor) | 5 | 0.3 | 60.0% | -2.0% | -3.9% | -69.0 .. +60.4 | 1.45 |
| as applied (shadow) | 182 | 11.4 | 54.9% | -2.8% | -4.9% | -17.4 .. +7.1 | 16.86 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 4 | 75.0% | +7.6% | +5.9% | 0 | — | — | — |
| basketball | 74 | 63.5% | -3.4% | -5.1% | 0 | — | — | — |
| football | 88 | 42.0% | -9.3% | -11.7% | 0 | — | — | — |
| handball | 7 | 71.4% | +17.6% | +15.3% | 5 | 60.0% | -2.0% | -3.9% |
| hockey | 51 | 72.5% | +9.8% | +7.9% | 0 | — | — | — |
| rugby | 1 | 100.0% | +40.0% | +38.0% | 0 | — | — | — |
| tennis | 62 | 64.5% | +1.3% | -0.6% | 0 | — | — | — |
| volleyball | 17 | 64.7% | -4.9% | -6.4% | 0 | — | — | — |

### as stored

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 304 | 19.0 | 59.5% | +3.3% | +1.1% | — | 16.86 |
| after (rules + floor) | 5 | 0.3 | 60.0% | -2.0% | -3.9% | — | 1.45 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 4 | 75.0% | +15.0% | +13.0% | 0 | — | — | — |
| basketball | 74 | 63.5% | -3.4% | -5.1% | 0 | — | — | — |
| football | 88 | 42.0% | -9.3% | -11.7% | 0 | — | — | — |
| handball | 7 | 71.4% | +17.6% | +15.3% | 5 | 60.0% | -2.0% | -3.9% |
| hockey | 51 | 72.5% | +36.5% | +33.3% | 0 | — | — | — |
| rugby | 1 | 100.0% | +40.0% | +38.0% | 0 | — | — | — |
| tennis | 62 | 64.5% | +1.3% | -0.6% | 0 | — | — | — |
| volleyball | 17 | 64.7% | -4.9% | -6.4% | 0 | — | — | — |

## Published TOP files in the holdout window

272 published (not withdrawn), 249 joined to settled holdout rows.

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| as stored | 249 | 15.6 | 54.6% | +5.8% | +3.3% | — | 14.61 |
| 2-way | 249 | 15.6 | 54.6% | -1.4% | -3.6% | — | 23.64 |

## Rules (tuning window, non-inherit segments)

| segment | level | n | hit | ROI −5% | H1 | H2 | decision | pCal | floor |
|---|---|---|---|---|---|---|---|---|---|
| baseball | sport | 111 | 60.4% | -9.8% | -7.1% | -19.9% | exclude | — | — |
| baseball|1.4-1.6 | sport×band | 51 | 56.9% | -16.0% | -21.5% | +1.8% | exclude | — | — |
| baseball|grade:B | sport×grade | 53 | 60.4% | -11.1% | -3.3% | -49.4% | exclude | — | — |
| baseball|tier:T1 | sport×tier | 85 | 60.0% | -12.4% | -11.6% | -19.7% | exclude | — | — |
| basketball | sport | 604 | 64.9% | -1.9% | -3.7% | -0.1% | exclude | — | — |
| basketball|1.0-1.4 | sport×band | 112 | 75.9% | +1.0% | -2.5% | +8.1% | exclude | — | — |
| basketball|1.0-1.4|home | sport×band×side | 66 | 75.8% | +0.9% | -4.2% | +10.4% | exclude | — | — |
| basketball|1.4-1.6 | sport×band | 264 | 64.4% | -6.3% | -9.8% | -3.2% | exclude | — | — |
| basketball|1.4-1.6|away | sport×band×side | 118 | 58.5% | -14.8% | -17.8% | -11.7% | exclude | — | — |
| basketball|1.4-1.6|home | sport×band×side | 146 | 69.2% | +0.6% | -2.2% | +2.9% | exclude | — | — |
| basketball|1.6-1.8 | sport×band | 151 | 62.9% | +3.0% | +12.3% | -5.0% | exclude | — | — |
| basketball|1.6-1.8|away | sport×band×side | 60 | 66.7% | +9.7% | +8.5% | +11.2% | allow | 0.665 | 1.6 |
| basketball|1.6-1.8|home | sport×band×side | 91 | 60.4% | -1.4% | +15.5% | -13.6% | exclude | — | — |
| basketball|1.8-2.0 | sport×band | 77 | 54.5% | -0.8% | -17.6% | +11.9% | exclude | — | — |
| basketball|1.8-2.0|home | sport×band×side | 52 | 53.8% | -1.7% | -8.7% | +4.3% | exclude | — | — |
| basketball|grade:B | sport×grade | 239 | 66.9% | +1.3% | -0.5% | +2.8% | exclude | — | — |
| basketball|grade:C | sport×grade | 335 | 63.6% | -4.3% | -5.6% | -2.5% | exclude | — | — |
| basketball|tier:T2 | sport×tier | 484 | 64.0% | -3.2% | -5.0% | -1.4% | exclude | — | — |
| basketball|tier:T3 | sport×tier | 91 | 73.6% | +10.7% | +14.5% | +6.3% | allow | 0.734 | 1.39 |
| football | sport | 1202 | 52.7% | -4.9% | -4.0% | -5.4% | exclude | — | — |
| football|1.4-1.6 | sport×band | 173 | 65.9% | -0.4% | -4.6% | +2.2% | exclude | — | — |
| football|1.4-1.6|away | sport×band×side | 71 | 67.6% | +2.2% | -6.3% | +10.0% | exclude | — | — |
| football|1.4-1.6|home | sport×band×side | 102 | 64.7% | -2.2% | -2.8% | -1.9% | exclude | — | — |
| football|1.6-1.8 | sport×band | 358 | 55.3% | -8.8% | -4.6% | -11.6% | exclude | — | — |
| football|1.6-1.8|away | sport×band×side | 147 | 61.9% | +2.2% | +10.6% | -6.1% | exclude | — | — |
| football|1.6-1.8|home | sport×band×side | 211 | 50.7% | -16.4% | -20.1% | -14.6% | exclude | — | — |
| football|1.8-2.0 | sport×band | 248 | 53.2% | -2.3% | -10.7% | +2.0% | exclude | — | — |
| football|1.8-2.0|away | sport×band×side | 120 | 54.2% | -0.7% | -5.5% | +3.2% | exclude | — | — |
| football|1.8-2.0|home | sport×band×side | 128 | 52.3% | -3.9% | -20.3% | +1.1% | exclude | — | — |
| football|2.0-2.5 | sport×band | 400 | 45.0% | -5.1% | -0.9% | -7.2% | exclude | — | — |
| football|2.0-2.5|away | sport×band×side | 214 | 43.9% | -8.0% | -2.1% | -11.2% | exclude | — | — |
| football|2.0-2.5|home | sport×band×side | 186 | 46.2% | -1.9% | +0.7% | -3.0% | exclude | — | — |
| football|grade:B | sport×grade | 352 | 56.0% | -1.1% | +0.3% | -1.7% | exclude | — | — |
| football|grade:C | sport×grade | 813 | 51.0% | -6.7% | -5.7% | -7.5% | exclude | — | — |
| football|tier:T1 | sport×tier | 155 | 45.8% | -18.8% | -11.0% | -21.9% | exclude | — | — |
| football|tier:T2 | sport×tier | 817 | 53.6% | -3.3% | -1.0% | -4.8% | exclude | — | — |
| football|tier:T3 | sport×tier | 230 | 53.9% | -1.4% | -12.6% | +4.2% | exclude | — | — |
| handball | sport | 136 | 61.8% | +0.4% | +3.8% | -5.9% | exclude | — | — |
| handball|1.6-1.8 | sport×band | 63 | 65.1% | +5.8% | +4.5% | +7.7% | allow | 0.65 | 1.6 |
| handball|grade:B | sport×grade | 53 | 73.6% | +18.8% | +13.2% | +28.8% | allow | 0.732 | 1.39 |
| handball|grade:C | sport×grade | 75 | 56.0% | -8.4% | -0.1% | -24.1% | exclude | — | — |
| handball|tier:T2 | sport×tier | 108 | 64.8% | +6.0% | +9.3% | +0.5% | allow | 0.648 | 1.58 |
| hockey | sport | 774 | 63.4% | -6.6% | -3.6% | -11.0% | exclude | — | — |
| hockey|1.0-1.4 | sport×band | 247 | 70.4% | -9.1% | -5.0% | -26.8% | exclude | — | — |
| hockey|1.0-1.4|away | sport×band×side | 100 | 63.0% | -18.6% | -9.4% | -55.2% | exclude | — | — |
| hockey|1.0-1.4|home | sport×band×side | 147 | 75.5% | -2.6% | -2.1% | -5.0% | exclude | — | — |
| hockey|1.4-1.6 | sport×band | 257 | 63.0% | -7.3% | -10.3% | -4.1% | exclude | — | — |
| hockey|1.4-1.6|away | sport×band×side | 98 | 58.2% | -14.0% | -17.5% | -10.4% | exclude | — | — |
| hockey|1.4-1.6|home | sport×band×side | 159 | 66.0% | -3.1% | -5.9% | -0.2% | exclude | — | — |
| hockey|1.6-1.8 | sport×band | 233 | 59.7% | -0.8% | +11.5% | -11.6% | exclude | — | — |
| hockey|1.6-1.8|away | sport×band×side | 106 | 60.4% | +0.5% | +13.4% | -12.3% | exclude | — | — |
| hockey|1.6-1.8|home | sport×band×side | 127 | 59.1% | -1.8% | +9.8% | -11.0% | exclude | — | — |
| hockey|grade:A | sport×grade | 67 | 67.2% | +0.1% | -3.6% | +2.3% | exclude | — | — |
| hockey|grade:B | sport×grade | 309 | 64.1% | -6.1% | -3.3% | -10.3% | exclude | — | — |
| hockey|grade:C | sport×grade | 398 | 62.3% | -8.1% | -3.8% | -15.4% | exclude | — | — |
| hockey|tier:T1 | sport×tier | 74 | 67.6% | +5.1% | +5.2% | +4.9% | allow | 0.675 | 1.51 |
| hockey|tier:T2 | sport×tier | 654 | 64.1% | -6.2% | -3.0% | -11.0% | exclude | — | — |
| rugby | sport | 25 | 64.0% | -9.7% | -7.8% | -12.6% | exclude | — | — |
| tennis | sport | 373 | 58.2% | -12.2% | -18.2% | -6.3% | exclude | — | — |
| tennis|1.4-1.6 | sport×band | 177 | 64.4% | -6.5% | -16.3% | +0.9% | exclude | — | — |
| tennis|1.4-1.6|away | sport×band×side | 69 | 62.3% | -10.3% | -7.8% | -11.7% | exclude | — | — |
| tennis|1.4-1.6|home | sport×band×side | 108 | 65.7% | -4.1% | -20.4% | +10.5% | exclude | — | — |
| tennis|1.6-1.8 | sport×band | 111 | 52.3% | -14.7% | -19.9% | -7.8% | exclude | — | — |
| tennis|1.6-1.8|home | sport×band×side | 66 | 51.5% | -15.8% | -20.7% | -7.9% | exclude | — | — |
| tennis|grade:B | sport×grade | 94 | 62.8% | -5.6% | -28.9% | +11.7% | exclude | — | — |
| tennis|grade:C | sport×grade | 247 | 56.7% | -14.6% | -15.6% | -13.1% | exclude | — | — |
| tennis|tier:T2 | sport×tier | 67 | 53.7% | -19.0% | -28.4% | -9.4% | exclude | — | — |
| tennis|tier:T? | sport×tier | 289 | 59.2% | -10.8% | -15.6% | -6.1% | exclude | — | — |
| volleyball | sport | 76 | 71.1% | +2.2% | -8.4% | +16.1% | exclude | — | — |

## Context (not used for decisions)

Livesport-era qualified graded rows up to tuning.end (older engine, grade semantics differ):

| sport | n | hit | ROI −5% |
|---|---|---|---|
| baseball | 523 | 59.1% | +8.0% |
| basketball | 3862 | 62.8% | -0.2% |
| football | 14303 | 41.3% | -6.8% |
| handball | 874 | 67.0% | -1.6% |
| hockey | 1893 | 60.6% | -6.3% |
| tennis | 1189 | 60.4% | -7.8% |
| volleyball | 944 | 68.1% | -7.8% |

Supabase cross-check (settled predictions in tuning window): {'skipped': 'SUPABASE_URL / key not set'}
