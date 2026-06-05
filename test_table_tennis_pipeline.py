# -*- coding: utf-8 -*-
"""
Regression tests for the SofaScore-sourced table tennis pipeline.

Covers:
  - SofaScore slug + draw-less registration
  - list_scheduled_events / get_event_h2h JSON parsing (mocked _api_get_json)
  - vote normalization to 2-way
  - row building from events
  - enrichment + mandatory fan-vote gate
  - scoring with the table-tennis profile (strong favorite qualifies,
    coin-flip does not)
  - fan-vote thresholds registered for table_tennis in both gates
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sofascore_scraper as ss
import table_tennis_pipeline as tt


# ---------------------------------------------------------------------------
# 1. Sport registration
# ---------------------------------------------------------------------------
class TestSportRegistration:
    def test_slug_mapped(self):
        assert ss.SOFASCORE_SPORT_SLUGS.get("table_tennis") == "table-tennis"
        assert ss.SOFASCORE_SPORT_SLUGS.get("table-tennis") == "table-tennis"

    def test_is_draw_less(self):
        assert "table_tennis" in ss.SPORTS_WITHOUT_DRAW

    def test_fan_vote_threshold_gate(self):
        from qualification_gate import FAN_VOTE_THRESHOLDS, SPORT_MIN_ODDS
        assert FAN_VOTE_THRESHOLDS.get("table_tennis") == 55.0
        assert SPORT_MIN_ODDS.get("table_tennis") == 1.35

    def test_fan_vote_threshold_telegram(self):
        import telegram_notifier as tn
        assert tn._FAN_VOTE_THRESHOLDS.get("table_tennis") == 55.0


# ---------------------------------------------------------------------------
# 2. list_scheduled_events
# ---------------------------------------------------------------------------
class TestListScheduledEvents:
    def test_parses_events(self, monkeypatch):
        fake = {
            "events": [
                {
                    "id": 101,
                    "homeTeam": {"name": "Ma Long"},
                    "awayTeam": {"name": "Fan Zhendong"},
                    "tournament": {"name": "WTT", "category": {"name": "World"}},
                    "status": {"type": "notstarted"},
                    "startTimestamp": 1780000000,
                },
                {
                    "id": 102,
                    "homeTeam": {"name": "A"},
                    "awayTeam": {"name": "B"},
                    "tournament": {"name": "Local"},
                    "status": {"type": "finished"},
                    "startTimestamp": 1779000000,
                },
            ]
        }
        monkeypatch.setattr(ss, "_api_get_json", lambda url, timeout=10: fake)
        out = ss.list_scheduled_events("table_tennis", "2026-06-04")
        assert len(out) == 2
        assert out[0]["event_id"] == 101
        assert out[0]["home_team"] == "Ma Long"
        assert out[0]["tournament"] == "WTT"
        assert out[0]["category"] == "World"
        assert out[1]["status"] == "finished"

    def test_skips_missing_team_names(self, monkeypatch):
        fake = {"events": [{"id": 1, "homeTeam": {}, "awayTeam": {"name": "B"}}]}
        monkeypatch.setattr(ss, "_api_get_json", lambda url, timeout=10: fake)
        out = ss.list_scheduled_events("table_tennis", "2026-06-04")
        assert out == []

    def test_none_response(self, monkeypatch):
        monkeypatch.setattr(ss, "_api_get_json", lambda url, timeout=10: None)
        assert ss.list_scheduled_events("table_tennis", "2026-06-04") == []

    def test_uses_correct_slug_in_url(self, monkeypatch):
        captured = {}
        def _fake(url, timeout=10):
            captured["url"] = url
            return {"events": []}
        monkeypatch.setattr(ss, "_api_get_json", _fake)
        ss.list_scheduled_events("table_tennis", "2026-06-04")
        assert "/sport/table-tennis/scheduled-events/2026-06-04" in captured["url"]


# ---------------------------------------------------------------------------
# 3. get_event_h2h
# ---------------------------------------------------------------------------
class TestGetEventH2H:
    def test_parses_team_duel(self, monkeypatch):
        fake = {"teamDuel": {"homeWins": 4, "awayWins": 2, "draws": 0}}
        monkeypatch.setattr(ss, "_api_get_json", lambda url, timeout=10: fake)
        out = ss.get_event_h2h(123)
        assert out == {"home_wins": 4, "away_wins": 2, "draws": 0, "total": 6}

    def test_none_when_no_duel(self, monkeypatch):
        monkeypatch.setattr(ss, "_api_get_json", lambda url, timeout=10: {"teamDuel": {}})
        assert ss.get_event_h2h(123) is None

    def test_zero_event_id(self):
        assert ss.get_event_h2h(0) is None


# ---------------------------------------------------------------------------
# 4. Vote normalization
# ---------------------------------------------------------------------------
class TestVoteNormalization:
    def test_two_way_renormalizes(self):
        out = tt._vote_probs_two_way({
            "sofascore_home_win_prob": 60,
            "sofascore_away_win_prob": 40,
            "sofascore_total_votes": 500,
        })
        assert out["home"] == 60.0
        assert out["away"] == 40.0
        assert out["total_votes"] == 500

    def test_drops_draw_share(self):
        # If a (spurious) draw share is present, home/away renormalize to 100.
        out = tt._vote_probs_two_way({
            "sofascore_home_win_prob": 50,
            "sofascore_away_win_prob": 30,
            "sofascore_total_votes": 100,
        })
        assert out["home"] + out["away"] == pytest.approx(100.0, abs=0.1)

    def test_none_inputs(self):
        assert tt._vote_probs_two_way(None) is None
        assert tt._vote_probs_two_way({"sofascore_home_win_prob": None,
                                       "sofascore_away_win_prob": 50}) is None


# ---------------------------------------------------------------------------
# 5. Row building
# ---------------------------------------------------------------------------
class TestBuildRow:
    def test_basic_fields(self):
        ev = {
            "event_id": 7,
            "home_team": "Ma Long",
            "away_team": "Fan Zhendong",
            "tournament": "WTT",
            "category": "World",
            "start_timestamp": 1780000000,
            "status": "notstarted",
        }
        row = tt._build_row(ev)
        assert row["sport"] == "table_tennis"
        assert row["home_team"] == "Ma Long"
        assert row["focus_team"] == "home"
        assert row["match_url"].endswith("/event/7")
        assert row["match_time"]  # non-empty formatted time


# ---------------------------------------------------------------------------
# 6. Enrichment + mandatory fan-vote gate
# ---------------------------------------------------------------------------
class TestEnrichAndGate:
    def test_enrich_populates_fields(self, monkeypatch):
        monkeypatch.setattr(tt, "get_votes_via_api",
                            lambda eid: {"sofascore_home_win_prob": 70,
                                         "sofascore_away_win_prob": 30,
                                         "sofascore_total_votes": 400})
        monkeypatch.setattr(tt, "get_odds_via_api",
                            lambda eid: {"odds_found": True, "home_odds": 1.6,
                                         "away_odds": 2.3, "bookmaker": "SofaScore"})
        monkeypatch.setattr(tt, "get_event_h2h",
                            lambda eid: {"home_wins": 3, "away_wins": 1, "draws": 0, "total": 4})
        monkeypatch.setattr(tt, "get_team_recent_form",
                            lambda tid, name, limit=5: ['W', 'W', 'L'] if tid == 10 else ['L', 'L', 'W'])
        row = tt._build_row({"event_id": 1, "home_team": "A", "away_team": "B",
                             "home_id": 10, "away_id": 20,
                             "start_timestamp": 1780000000, "status": "notstarted"})
        tt.enrich_row(row)
        assert row["sofascore_found"] is True
        assert row["sofascore_home_win_prob"] == 70.0
        assert row["home_wins_in_h2h_last5"] == 3
        assert row["h2h_count"] == 4
        assert row["form_a"] == ['W', 'W', 'L']
        assert row["form_b"] == ['L', 'L', 'W']

    def test_enrich_without_votes_skips_vote_call(self, monkeypatch):
        called = {"votes": False}
        def _votes(eid):
            called["votes"] = True
            return None
        monkeypatch.setattr(tt, "get_votes_via_api", _votes)
        monkeypatch.setattr(tt, "get_event_h2h", lambda eid: None)
        monkeypatch.setattr(tt, "get_team_recent_form", lambda tid, name, limit=5: [])
        row = tt._build_row({"event_id": 1, "home_team": "A", "away_team": "B",
                             "home_id": 10, "away_id": 20, "start_timestamp": 1780000000})
        tt.enrich_row(row, with_votes=False)
        assert called["votes"] is False  # vote call skipped to save API budget

    def test_odds_gate_keeps_favourite_and_drops_rest(self):
        rows = [
            {"home_odds": 1.55, "away_odds": 2.45},   # favourite 1.55 → pass
            {"home_odds": 1.20, "away_odds": 4.50},   # favourite 1.20 < 1.35 → drop
            {"home_odds": 1.90, "away_odds": 1.90},   # favourite 1.90 → pass
            {"home_odds": None, "away_odds": None},    # no odds → drop
        ]
        passed = tt.apply_odds_gate(rows)
        assert passed == 2
        assert rows[0]["qualifies"] is True
        assert rows[1]["qualifies"] is False
        assert rows[2]["qualifies"] is True
        assert rows[3]["qualifies"] is False
        assert rows[3]["tt_skip_reason"] == "no_odds"

    def test_fetch_odds_populates_row(self, monkeypatch):
        monkeypatch.setattr(tt, "get_odds_via_api",
                            lambda eid: {"odds_found": True, "home_odds": 1.7,
                                         "away_odds": 2.1, "bookmaker": "SofaScore"})
        row = {"event_id": 5}
        assert tt.fetch_odds(row) is True
        assert row["home_odds"] == 1.7
        assert row["away_odds"] == 2.1


# ---------------------------------------------------------------------------
# 7. Scoring with table-tennis profile
# ---------------------------------------------------------------------------
class TestScoring:
    def _row(self, hv, av, ho, ao, hw, aw):
        return {
            "home_team": "A", "away_team": "B", "sport": "table_tennis",
            "qualifies": True,
            "sofascore_home_win_prob": hv, "sofascore_away_win_prob": av,
            "sofascore_total_votes": 600,
            "home_odds": ho, "away_odds": ao,
            "home_wins_in_h2h_last5": hw, "away_wins_in_h2h_last5": aw,
            "h2h_count": hw + aw,
        }

    def test_strong_favorite_qualifies(self):
        rows = [self._row(72, 28, 1.55, 2.45, 4, 2)]
        tt.score_rows(rows)
        assert rows[0]["qualifies"] is True
        assert rows[0]["scoring_pick"] == "A"

    def test_coin_flip_rejected(self):
        rows = [self._row(52, 48, 1.92, 1.88, 1, 1)]
        tt.score_rows(rows)
        assert rows[0]["qualifies"] is False

    def test_favourite_without_fan_vote_still_qualifies(self):
        # KEY requirement: amateur matches with NO fan vote must still qualify
        # when odds + H2H + form make a clear favourite.
        row = {
            "home_team": "Jadam D.", "away_team": "Kuzmicz J.", "sport": "table_tennis",
            "qualifies": True,
            "sofascore_home_win_prob": None, "sofascore_away_win_prob": None,
            "sofascore_total_votes": 0,
            "home_odds": 1.50, "away_odds": 2.55,
            "home_wins_in_h2h_last5": 3, "away_wins_in_h2h_last5": 1, "h2h_count": 4,
            "form_a": ["W", "W", "W", "L", "W"], "form_b": ["L", "L", "W", "L", "L"],
        }
        tt.score_rows([row])
        assert row["qualifies"] is True
        assert row["scoring_pick"] == "A"


# ---------------------------------------------------------------------------
# 8. Recent form fetch (general form, venue-agnostic)
# ---------------------------------------------------------------------------
class TestRecentForm:
    def test_parses_wins_losses(self, monkeypatch):
        import sofascore_scraper as ss
        fake = {"events": [
            # oldest-first; helper reverses to newest-first
            {"status": {"type": "finished"}, "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
             "homeScore": {"current": 3}, "awayScore": {"current": 1}},   # team 1 win
            {"status": {"type": "finished"}, "homeTeam": {"id": 3}, "awayTeam": {"id": 1},
             "homeScore": {"current": 3}, "awayScore": {"current": 0}},   # team 1 loss
        ]}
        monkeypatch.setattr(ss, "_api_get_json", lambda url, timeout=10: fake)
        form = ss.get_team_recent_form(1, "Team1")
        # newest-first: last event (team1 loss) first
        assert form == ['L', 'W']

    def test_skips_unfinished(self, monkeypatch):
        import sofascore_scraper as ss
        fake = {"events": [
            {"status": {"type": "notstarted"}, "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
             "homeScore": {"current": None}, "awayScore": {"current": None}},
        ]}
        monkeypatch.setattr(ss, "_api_get_json", lambda url, timeout=10: fake)
        assert ss.get_team_recent_form(1, "Team1") == []

    def test_zero_team_id(self):
        import sofascore_scraper as ss
        assert ss.get_team_recent_form(0, "x") == []


# ---------------------------------------------------------------------------
# 9. Profile independence
# ---------------------------------------------------------------------------
class TestProfileIndependence:
    def test_profile_weights_independent_of_calibration(self):
        # score_rows must force the TT profile regardless of any tennis
        # calibration file. Verify a scored row carries advanced_score.
        rows = [{
            "home_team": "A", "away_team": "B", "sport": "table_tennis",
            "qualifies": True,
            "sofascore_home_win_prob": 70, "sofascore_away_win_prob": 30,
            "sofascore_total_votes": 600,
            "home_odds": 1.6, "away_odds": 2.3,
            "home_wins_in_h2h_last5": 3, "away_wins_in_h2h_last5": 1, "h2h_count": 4,
        }]
        tt.score_rows(rows)
        assert "advanced_score" in rows[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
