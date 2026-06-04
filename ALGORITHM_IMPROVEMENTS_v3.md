# Prediction Algorithm Improvements (v3)

This document summarizes the changes made to the football and tennis
scoring engines, why they were made, and how they were validated.

## Summary

| Area | Before | After |
|------|--------|-------|
| Football draws | Heuristic `0.28 - abs(form_diff)*0.1`; real H2H draws discarded | Poisson goal model + outcome-resolved H2H draw rate |
| Football goal model | None | Poisson 1/X/2 from expected goals (3 evidence tiers) |
| Poisson weighting | n/a | Adaptive: up-weighted when market is absent/loose, down-weighted when sharp |
| Tennis match model | Flat weighted win-rate average | Hierarchical serve → game → set → match (best-of-3) Markov model |
| Validation | Measurement-only `CalibrationRunner` | Monte-Carlo ablation + reliability diagram in `backtest_engine.py` |
| Test coverage | 83 football + tennis tests | +35 new regression tests |

## Football engine (`football_scoring_engine.py`)

### 1. Poisson goal model (new source)
Football outcomes are best modelled through goals. `_poisson_match_probs()`
builds the full 1/X/2 distribution by summing the joint score-line grid of
two independent Poisson processes. The draw probability emerges naturally
from the diagonal of the grid instead of a hand-tuned constant.

Expected goals (`_expected_goals`) are derived from three evidence tiers, in
priority order:
1. **Forebet exact score** (e.g. "2-1") — a direct goal expectation.
2. **Team scoring/conceding averages** — classic attack-vs-defence xG proxy.
3. **Odds + form + H2H** — infers a *supremacy* (expected goal difference)
   and a league *total*, then splits into the two rates. This tier almost
   always fires, so the calibrated Poisson draw signal reaches nearly every
   match (not just the rare ones with Forebet/goal data).

The tier-3 supremacy multiplier (1.3) was calibrated via the backtest below;
higher values improved accuracy but hurt probability calibration.

### 2. Outcome-resolved H2H (`_h2h_outcome_rates`)
The previous H2H helper folded draws into the win rate at 0.5, discarding the
real, repeatedly-observed draw tendency between two specific teams. The new
helper resolves win/draw/loss separately and shrinks toward a prior when the
sample is small.

### 3. Adaptive Poisson weight
Backtests showed the Poisson signal adds the most value when the market is
absent or loose, and little when a sharp book already prices the game. The
weight now scales with `market_efficiency`: ×1.8 when no usable odds exist,
shrinking toward ×0.6 as the market sharpens.

## Tennis engine (`tennis_scoring_engine.py`)

### Hierarchical serve/point model (new source)
Tennis has a strong structural property: a small per-point edge amplifies
into a large match-win edge. The new model maps an aggregate point-level
advantage (from ranking gap, surface form and overall form) to per-point
serve/return win probabilities, then runs the standard Markov hierarchy:

- `_prob_win_game(p)` — closed-form game (incl. deuce) hold probability
- `_prob_win_set(hold, break)` — 6-game, win-by-2 set with tie-break
- `_prob_win_match_bo3(p_set)` — best-of-3 match

Validated against reality: 64% service-point win → ~81% hold (real ATP hold
rates ≈ 80%); even edge → exactly 0.5; the point→match amplification is
present and bounded.

## Validation (`backtest_engine.py`)

Two modes:

- **Simulation ablation** (`--simulate N`): a Monte-Carlo study with ground
  truth known by construction. True goal rates are drawn, a real scoreline is
  sampled (→ true 1/X/2), and the noisy match row the engine sees is rebuilt
  from odds/form. The engine is scored *with* and *without* the Poisson
  source and compared on accuracy, Brier score, log-loss and draw-Brier.
- **Real-data** (`--real path.json|csv`): evaluates any file containing
  `actual_result` ('1'/'X'/'2'), reporting the same metrics plus a flat-stake
  value-bet ROI and a **reliability diagram** (predicted vs observed hit rate
  per confidence band).

### How to run

```bash
# Ablation across realistic data scenarios
python backtest_engine.py --simulate 8000 --seed 42                  # sharp market
python backtest_engine.py --simulate 8000 --odds-noise 0.30          # loose market
python backtest_engine.py --simulate 8000 --odds-missing 0.4         # missing odds

# Once settled results are exported from Supabase:
python backtest_engine.py --real results/settled_football.json
```

### Measured results (8000-match ablation, adaptive Poisson)

| Scenario | Δ accuracy | Δ Brier | Δ log-loss |
|----------|-----------|---------|-----------|
| Sharp market | +0.0032 | +0.0001 | +0.0002 |
| Noisy market | +0.0033 | +0.0000 | −0.0001 |
| 40% missing odds | +0.0017 | −0.0013 | −0.0017 |

Accuracy improves in every scenario; calibration improves where the market is
weak (the realistic production case) and is neutral where a sharp market
already carries the signal. Note the simulation is *adversarial* toward the
new source because, when present, the synthetic odds are derived near-perfectly
from the true probabilities — so real-world gains are expected to be at least
as large.

## Notes
- All changes are backward compatible: output fields are unchanged, so
  `scrape_and_notify.py` and `ai_prediction_engine.py` need no modification.
- New default weights are picked up automatically by `weight_optimizer.py`
  (it reads `FootballScoringEngine.DEFAULT_WEIGHTS`).
- Draw-less sports (basketball, volleyball, tennis) never receive a Poisson
  draw signal — the source abstains for them.
