"""Integration tests for worldcup_analyzer.analyze_match using a recorded
Pinnacle odds package (no network). Verifies the full enrichment chain:
markets -> analysis -> goal_model / kelly / who_scores_first / verdict."""
from worldcup_analyzer import analyze_match


def _recorded_pkg():
    """A trimmed but realistic PinnacleFullOdds.get_full_odds_for_match() output."""
    def item(v, o, mv=None):
        return {"value": v, "opening": o, "movement": mv,
                "drift": round(v - o, 3), "active": True}
    return {
        "event_id": "TEST1234",
        "bookmaker": "Pinnacle",
        "success": True,
        "markets_available": ["HOME_DRAW_AWAY", "OVER_UNDER",
                              "BOTH_TEAMS_TO_SCORE", "CORRECT_SCORE"],
        "markets": {
            "HOME_DRAW_AWAY": {
                "home": item(2.6, 2.45, "UP"),
                "draw": item(3.1, 3.15, "DOWN"),
                "away": item(2.7, 2.7),
                "fair_prob": {"home": 35.7, "draw": 29.9, "away": 34.4},
                "vig": 7.76,
            },
            "OVER_UNDER": {
                "main_line": 2.5,
                "lines": [
                    {"line": 1.5, "over": item(1.4, 1.18), "under": item(2.75, 4.0),
                     "fair_prob": {"over": 66.0, "under": 34.0}, "vig": 5.0},
                    {"line": 2.5, "over": item(2.2, 2.0), "under": item(1.58, 1.7),
                     "fair_prob": {"over": 41.8, "under": 58.2}, "vig": 4.0},
                ],
            },
            "BOTH_TEAMS_TO_SCORE": {
                "yes": item(1.85, 1.53), "no": item(1.85, 2.25),
                "fair_prob": {"yes": 50.0, "no": 50.0}, "vig": 8.0,
            },
            "CORRECT_SCORE": {
                "most_likely": "1:1",
                "items": [
                    {"score": "1:1", "value": 5.75, "opening": 5.0,
                     "movement": "UP", "drift": 0.75, "active": True},
                    {"score": "1:0", "value": 7.0, "opening": 6.0,
                     "movement": "UP", "drift": 1.0, "active": True},
                    {"score": "0:0", "value": 7.25, "opening": 6.5,
                     "movement": "UP", "drift": 0.75, "active": True},
                    {"score": "0:1", "value": 7.25, "opening": 6.5,
                     "movement": "UP", "drift": 0.75, "active": True},
                    {"score": "2:1", "value": 9.5, "opening": 8.0,
                     "movement": "UP", "drift": 1.5, "active": True},
                    {"score": "2:0", "value": 11.0, "opening": 10.0,
                     "movement": "UP", "drift": 1.0, "active": True},
                    {"score": "1:2", "value": 12.0, "opening": 11.0,
                     "movement": "UP", "drift": 1.0, "active": True},
                ],
            },
        },
    }


def test_analyze_produces_core_sections():
    a = analyze_match(_recorded_pkg(), {"home_team": "Mexico", "away_team": "South Africa"})
    assert a["match_winner"]["pick"] in ("home", "draw", "away")
    assert a["totals"]["main_line"] == 2.5
    assert a["btts"]["recommendation"] is not None
    assert a["correct_score"]["most_likely"] == "1:1"
    assert a["markets_count"] == 4


def test_analyze_enriches_goal_model_and_kelly():
    a = analyze_match(_recorded_pkg(), {"home_team": "Mexico", "away_team": "South Africa"})
    assert a.get("goal_model") is not None
    gm = a["goal_model"]
    assert gm["expected_goals"]["total"] > 0
    assert set(gm["who_scores_first"]) >= {"home", "none", "away", "pick"}
    assert "kelly" in a and a["kelly"] is not None
    # helper field must be cleaned
    assert "_raw_correct_score" not in a


def test_who_scores_first_surfaced_top_level():
    a = analyze_match(_recorded_pkg(), {"home_team": "A", "away_team": "B"})
    assert a.get("who_scores_first") == a["goal_model"]["who_scores_first"]


def test_verdict_mentions_new_insights():
    a = analyze_match(_recorded_pkg(), {"home_team": "Mexico", "away_team": "South Africa"})
    v = a["verdict"]
    assert "Model goli" in v
    assert "Pierwszy gol" in v


def test_line_movement_signal_detected():
    # home odds drifted 2.45 -> 2.6 (UP >=12%? 0.15/2.45=6.1% -> not strong)
    # Use a stronger drop to trigger sharp-money note.
    pkg = _recorded_pkg()
    pkg["markets"]["HOME_DRAW_AWAY"]["away"] = {
        "value": 2.2, "opening": 2.7, "movement": "DOWN",
        "drift": -0.5, "active": True}
    a = analyze_match(pkg, {"home_team": "Mexico", "away_team": "South Africa"})
    assert any("sharp money" in s or "spadł" in s for s in a["signals"])
