# TOP rules – holdout report

Generated 2026-11-02T10:10:18Z. Tuning 2026-09-12..2026-10-16 (n=1688, halves split at 2026-10-03); holdout 2026-10-17..2026-11-02 (17 days). The learner never reads holdout rows. Flat 1u, draw = loss, ROI −5% = profit × 0.95; hockey/basketball/baseball 3-way quotes re-priced to the 2-way equivalent ("2-way"); "as stored" = published prices. Max DD in units at −5%. CI = bootstrap 95% (1000×) of ROI −5%.

Segment decisions: {'exclude': 45, 'inherit': 93, 'allow': 4}

## Gate in use by TOP

Mode: **shadow**. The learned rules are enforced automatically only when a rebuild keeps >= 3 TOP picks/day on the holdout with ROI −5% > +0% (TOP replay after rules + floor). Otherwise TOP applies the safe gate (tennis and basketball priced below 1.80 excluded, everything else as evaluate()) and each pick records the learned decision (`learnedDecision`, `learnedSegment`).

This build: enforce = False; holdout TOP replay after rules: 1 picks, 0.1/day, ROI -5% +63.9% (needs >= 3/day and > +0%).

**Caveat (holdout leak):** the 1.80 cut of the safe gate was chosen in the data audit, which also looked at the holdout days, so its holdout numbers below ("as applied") are optimistic. It is re-validated forward on the first 14 settled days from 2026-10-27.

### Forward check of the 1.80 cut (2026-10-27..2026-11-09, TOP replay, 2-way)

Status: **pending (6/14 settled days)**

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| removed by the cut | 46 | 46.0 | 73.9% | +12.9% | +10.9% | — | 2.5 |
| kept | 108 | 108.0 | 57.4% | +8.1% | +5.6% | — | 9.89 |
| removed, basketball | 12 | 12.0 | 83.3% | +23.3% | +21.3% | — | 2.0 |
| removed, tennis | 34 | 34.0 | 70.6% | +9.2% | +7.2% | — | 3.01 |

## Candidates TOP could publish (structural gates, grade A/B/C)

### 2-way prices

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 1968 | 115.8 | 57.0% | -2.2% | -4.3% | -7.8 .. -0.5 | 98.88 |
| after (rules + floor) | 3 | 0.2 | 66.7% | +9.9% | +7.7% | -100.0 .. +63.9 | 1.0 |
| as applied (shadow) | 1550 | 91.2 | 54.8% | -2.5% | -4.7% | -9.0 .. -0.4 | 88.79 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 19 | 52.6% | -16.8% | -18.4% | 0 | — | — | — |
| basketball | 284 | 65.1% | +1.9% | +0.1% | 0 | — | — | — |
| football | 1113 | 53.1% | -1.2% | -3.5% | 0 | — | — | — |
| handball | 38 | 55.3% | -8.3% | -10.1% | 0 | — | — | — |
| hockey | 282 | 58.2% | -9.6% | -11.2% | 3 | 66.7% | +9.9% | +7.7% |
| rugby | 6 | 66.7% | +2.2% | +0.4% | 0 | — | — | — |
| tennis | 195 | 62.6% | -3.9% | -5.6% | 0 | — | — | — |
| volleyball | 31 | 80.6% | +15.4% | +13.6% | 0 | — | — | — |

### as stored

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 1968 | 115.8 | 57.0% | +1.1% | -1.1% | — | 54.45 |
| after (rules + floor) | 3 | 0.2 | 66.7% | +41.7% | +37.9% | — | 1.0 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 19 | 52.6% | -13.6% | -15.3% | 0 | — | — | — |
| basketball | 284 | 65.1% | +1.9% | +0.1% | 0 | — | — | — |
| football | 1113 | 53.1% | -1.2% | -3.5% | 0 | — | — | — |
| handball | 38 | 55.3% | -8.3% | -10.1% | 0 | — | — | — |
| hockey | 282 | 58.2% | +13.5% | +10.8% | 3 | 66.7% | +41.7% | +37.9% |
| rugby | 6 | 66.7% | +2.2% | +0.4% | 0 | — | — | — |
| tennis | 195 | 62.6% | -3.9% | -5.6% | 0 | — | — | — |
| volleyball | 31 | 80.6% | +15.4% | +13.6% | 0 | — | — | — |

## TOP replay (current evaluate())

### 2-way prices

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 340 | 20.0 | 62.9% | +6.5% | +4.3% | -4.8 .. +13.4 | 10.61 |
| after (rules + floor) | 1 | 0.1 | 100.0% | +67.3% | +63.9% | — | 0.0 |
| as applied (shadow) | 226 | 13.3 | 59.7% | +7.3% | +4.9% | -6.9 .. +16.7 | 9.89 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 6 | 66.7% | -0.5% | -2.1% | 0 | — | — | — |
| basketball | 40 | 70.0% | +7.7% | +5.8% | 0 | — | — | — |
| football | 98 | 53.1% | +15.8% | +12.6% | 0 | — | — | — |
| handball | 8 | 75.0% | +22.8% | +20.4% | 0 | — | — | — |
| hockey | 95 | 60.0% | -8.5% | -10.1% | 1 | 100.0% | +67.3% | +63.9% |
| rugby | 1 | 0.0% | -100.0% | -100.0% | 0 | — | — | — |
| tennis | 84 | 71.4% | +10.6% | +8.7% | 0 | — | — | — |
| volleyball | 8 | 87.5% | +24.1% | +22.3% | 0 | — | — | — |

### as stored

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| before | 340 | 20.0 | 62.9% | +12.4% | +9.9% | — | 8.64 |
| after (rules + floor) | 1 | 0.1 | 100.0% | +115.0% | +109.2% | — | 0.0 |

| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |
|---|---|---|---|---|---|---|---|---|
| baseball | 6 | 66.7% | +3.1% | +1.2% | 0 | — | — | — |
| basketball | 40 | 70.0% | +7.7% | +5.8% | 0 | — | — | — |
| football | 98 | 53.1% | +15.8% | +12.6% | 0 | — | — | — |
| handball | 8 | 75.0% | +22.8% | +20.4% | 0 | — | — | — |
| hockey | 95 | 60.0% | +12.4% | +9.8% | 1 | 100.0% | +115.0% | +109.2% |
| rugby | 1 | 0.0% | -100.0% | -100.0% | 0 | — | — | — |
| tennis | 84 | 71.4% | +10.6% | +8.7% | 0 | — | — | — |
| volleyball | 8 | 87.5% | +24.1% | +22.3% | 0 | — | — | — |

## Published TOP files in the holdout window

312 published (not withdrawn), 189 joined to settled holdout rows.

| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |
|---|---|---|---|---|---|---|---|
| as stored | 189 | 11.1 | 61.4% | +11.3% | +8.8% | — | 7.47 |
| 2-way | 189 | 11.1 | 61.4% | +3.7% | +1.6% | — | 9.42 |

## Rules (tuning window, non-inherit segments)

| segment | level | n | hit | ROI −5% | H1 | H2 | decision | pCal | floor |
|---|---|---|---|---|---|---|---|---|---|
| baseball | sport | 92 | 62.0% | -8.0% | -7.6% | -9.2% | exclude | — | — |
| baseball|tier:T1 | sport×tier | 77 | 61.0% | -11.0% | -8.9% | -19.7% | exclude | — | — |
| basketball | sport | 320 | 65.0% | -3.2% | -2.7% | -3.5% | exclude | — | — |
| basketball|1.0-1.4 | sport×band | 78 | 74.4% | -1.2% | +4.4% | -3.0% | exclude | — | — |
| basketball|1.4-1.6 | sport×band | 136 | 62.5% | -9.2% | -17.1% | -5.2% | exclude | — | — |
| basketball|1.4-1.6|away | sport×band×side | 63 | 57.1% | -17.2% | -39.4% | -3.6% | exclude | — | — |
| basketball|1.4-1.6|home | sport×band×side | 73 | 67.1% | -2.3% | +7.2% | -6.4% | exclude | — | — |
| basketball|1.6-1.8 | sport×band | 73 | 68.5% | +12.3% | +13.6% | +11.5% | allow | 0.684 | 1.6 |
| basketball|grade:B | sport×grade | 108 | 66.7% | -0.2% | -7.1% | +4.3% | exclude | — | — |
| basketball|grade:C | sport×grade | 209 | 64.1% | -4.9% | +1.6% | -7.5% | exclude | — | — |
| basketball|tier:T2 | sport×tier | 258 | 64.0% | -4.6% | -5.1% | -4.4% | exclude | — | — |
| football | sport | 434 | 53.5% | -4.1% | -5.2% | -3.3% | exclude | — | — |
| football|1.4-1.6 | sport×band | 65 | 63.1% | -4.6% | -10.3% | +2.9% | exclude | — | — |
| football|1.6-1.8 | sport×band | 144 | 58.3% | -3.9% | -1.0% | -6.6% | exclude | — | — |
| football|1.6-1.8|away | sport×band×side | 72 | 68.1% | +12.2% | +18.2% | +9.0% | allow | 0.678 | 1.6 |
| football|1.6-1.8|home | sport×band×side | 72 | 48.6% | -20.1% | -12.1% | -31.8% | exclude | — | — |
| football|1.8-2.0 | sport×band | 84 | 48.8% | -10.7% | -14.2% | -8.2% | exclude | — | — |
| football|1.8-2.0|away | sport×band×side | 54 | 51.9% | -5.5% | -9.7% | -3.0% | exclude | — | — |
| football|2.0-2.5 | sport×band | 131 | 46.6% | -2.0% | -4.9% | -0.7% | exclude | — | — |
| football|2.0-2.5|away | sport×band×side | 77 | 46.8% | -2.1% | -13.5% | +2.4% | exclude | — | — |
| football|2.0-2.5|home | sport×band×side | 54 | 46.3% | -1.7% | +5.7% | -5.4% | exclude | — | — |
| football|grade:B | sport×grade | 110 | 58.2% | +0.3% | -2.8% | +9.9% | exclude | — | — |
| football|grade:C | sport×grade | 319 | 51.7% | -5.8% | -7.8% | -4.9% | exclude | — | — |
| football|tier:T2 | sport×tier | 316 | 55.4% | -1.0% | -6.2% | +3.0% | exclude | — | — |
| football|tier:T3 | sport×tier | 75 | 48.0% | -14.5% | -1.7% | -24.5% | exclude | — | — |
| handball | sport | 96 | 64.6% | +5.1% | +9.4% | -0.3% | exclude | — | — |
| handball|grade:C | sport×grade | 53 | 60.4% | -1.1% | +6.4% | -7.8% | exclude | — | — |
| handball|tier:T2 | sport×tier | 74 | 67.6% | +10.5% | +11.1% | +9.5% | allow | 0.675 | 1.51 |
| hockey | sport | 495 | 66.3% | -4.4% | -6.9% | -1.9% | exclude | — | — |
| hockey|1.0-1.4 | sport×band | 210 | 71.9% | -7.2% | -4.4% | -12.0% | exclude | — | — |
| hockey|1.0-1.4|away | sport×band×side | 83 | 67.5% | -12.7% | -18.3% | -5.7% | exclude | — | — |
| hockey|1.0-1.4|home | sport×band×side | 127 | 74.8% | -3.7% | +3.0% | -17.8% | exclude | — | — |
| hockey|1.4-1.6 | sport×band | 144 | 62.5% | -8.2% | -16.5% | -2.3% | exclude | — | — |
| hockey|1.4-1.6|away | sport×band×side | 57 | 57.9% | -14.6% | -18.7% | -12.0% | exclude | — | — |
| hockey|1.4-1.6|home | sport×band×side | 87 | 65.5% | -4.0% | -15.2% | +4.6% | exclude | — | — |
| hockey|1.6-1.8 | sport×band | 119 | 65.5% | +9.2% | -0.1% | +17.2% | exclude | — | — |
| hockey|1.6-1.8|away | sport×band×side | 57 | 68.4% | +14.2% | -0.3% | +25.6% | exclude | — | — |
| hockey|1.6-1.8|home | sport×band×side | 62 | 62.9% | +4.6% | +0.1% | +8.9% | allow | 0.63 | 1.62 |
| hockey|grade:B | sport×grade | 193 | 68.4% | -2.2% | -6.6% | +3.3% | exclude | — | — |
| hockey|grade:C | sport×grade | 276 | 64.5% | -6.2% | -6.4% | -6.1% | exclude | — | — |
| hockey|tier:T2 | sport×tier | 424 | 67.2% | -3.6% | -6.1% | -0.8% | exclude | — | — |
| rugby | sport | 6 | 50.0% | -30.8% | -30.8% | — | exclude | — | — |
| tennis | sport | 200 | 54.0% | -18.1% | -17.5% | -18.6% | exclude | — | — |
| tennis|1.4-1.6 | sport×band | 83 | 60.2% | -12.8% | -14.5% | -11.5% | exclude | — | — |
| tennis|1.4-1.6|home | sport×band×side | 56 | 57.1% | -16.9% | -18.7% | -15.3% | exclude | — | — |
| tennis|1.6-1.8 | sport×band | 68 | 47.1% | -23.4% | -11.7% | -33.2% | exclude | — | — |
| tennis|grade:C | sport×grade | 156 | 54.5% | -16.9% | -14.1% | -19.5% | exclude | — | — |
| tennis|tier:T? | sport×tier | 156 | 55.8% | -15.5% | -12.8% | -17.4% | exclude | — | — |
| volleyball | sport | 45 | 64.4% | -5.6% | +0.4% | -10.0% | exclude | — | — |

## Context (not used for decisions)

Livesport-era qualified graded rows up to tuning.end (older engine, grade semantics differ):

| sport | n | hit | ROI −5% |
|---|---|---|---|
| baseball | 513 | 59.1% | +8.1% |
| basketball | 3752 | 63.1% | +0.1% |
| football | 13967 | 41.3% | -7.2% |
| handball | 838 | 66.9% | -2.1% |
| hockey | 1770 | 60.5% | -6.3% |
| tennis | 1087 | 60.3% | -7.8% |
| volleyball | 897 | 68.2% | -8.4% |

Supabase cross-check (settled predictions in tuning window): {'skipped': 'SUPABASE_URL / key not set'}
