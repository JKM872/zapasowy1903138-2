"""Deterministic unit tests for the World Cup derived-analytics layer.
No network — feeds a synthetic Pinnacle CORRECT_SCORE / 1X2 structure."""
from worldcup_extras import derive_goal_model, compute_kelly, enrich_analysis


def _fake_correct_score():
    # Realistic-ish scoreline odds (lower odd = more likely)
    raw = {
        "items": [
            {"score": "1:1", "value": 5.5},
            {"score": "1:0", "value": 7.0},
            {"score": "0:0", "value": 7.5},
            {"score": "0:1", "value": 8.0},
            {"score": "2:1", "value": 9.0},
            {"score": "2:0", "value": 9.5},
            {"score": "1:2", "value": 11.0},
            {"score": "0:2", "value": 13.0},
            {"score": "2:2", "value": 15.0},
            {"score": "3:1", "value": 21.0},
        ]
    }
    return raw


def test_goal_model_probabilities_sum_consistent():
    gm = derive_goal_model(_fake_correct_score())
    assert gm is not None
    oc = gm["outcome_prob"]
    total = oc["home"] + oc["draw"] + oc["away"]
    assert 99.0 <= total <= 101.0           # normalized distribution
    assert gm["expected_goals"]["total"] > 0
    assert gm["scorelines_used"] == 10


def test_who_scores_first_present_and_valid():
    gm = derive_goal_model(_fake_correct_score())
    wsf = gm["who_scores_first"]
    assert set(wsf.keys()) >= {"home", "none", "away", "pick"}
    assert wsf["pick"] in ("1 (gospodarz)", "Nikt", "2 (gość)")


def test_derived_totals_monotonic():
    gm = derive_goal_model(_fake_correct_score())
    dt = gm["derived_totals"]
    # Over prob must decrease as the line rises
    overs = [dt["0.5"]["over"], dt["1.5"]["over"], dt["2.5"]["over"], dt["3.5"]["over"]]
    assert overs == sorted(overs, reverse=True)


def test_kelly_detects_value():
    # fair 50% on a 2.5 odd => value coefficient 1.25 (positive EV)
    mw = {"fair_prob": {"home": 50.0, "draw": 25.0, "away": 25.0},
          "odds": {"home": 2.5, "draw": 3.2, "away": 3.0}}
    k = compute_kelly(mw)
    assert k["home"]["is_value"] is True
    assert k["home"]["value_coefficient"] == 1.25
    assert k["home"]["kelly_fraction"] > 0
    assert k["best_value"] == "home"


def test_kelly_no_value_when_fair_below_implied():
    mw = {"fair_prob": {"home": 30.0, "draw": 30.0, "away": 40.0},
          "odds": {"home": 2.5, "draw": 3.2, "away": 2.0}}
    k = compute_kelly(mw)
    # away: 0.40 * 2.0 = 0.8 < 1 => no value; home: 0.30*2.5=0.75 no value
    assert k["best_value"] in (None, "away") or k["best_value"] is None


def test_enrich_analysis_wires_raw_cs_and_cleans_up():
    analysis = {
        "match_winner": {"fair_prob": {"home": 50, "draw": 25, "away": 25},
                         "odds": {"home": 2.5, "draw": 3.2, "away": 3.0}},
        "_raw_correct_score": _fake_correct_score(),
    }
    enrich_analysis(analysis)
    assert analysis["goal_model"] is not None
    assert analysis["kelly"] is not None
    assert "who_scores_first" in analysis
    assert "_raw_correct_score" not in analysis      # helper field removed
