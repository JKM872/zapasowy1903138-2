# pyright: reportMissingImports=false, reportOptionalMemberAccess=false, reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""Tests for telegram_notifier — formatting and failure isolation."""

import importlib
import os
import json
from datetime import datetime
from typing import Any
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helper: reload module with custom env
# ---------------------------------------------------------------------------

def _load_module(**env_overrides: str) -> Any:
    """Reload telegram_notifier with given env overrides."""
    defaults = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "12345",
        "TELEGRAM_ENABLED": "true",
    }
    defaults.update(env_overrides)
    with patch.dict(os.environ, defaults, clear=False):
        import telegram_notifier
        importlib.reload(telegram_notifier)
        return telegram_notifier


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_ROWS = [
    {
        "home_team": "Liverpool",
        "away_team": "Arsenal",
        "sport": "football",
        "qualifies": True,
        "scoring_pick": "1",
        "scoring_confidence": 72,
        "ai_composite_confidence": 75,
        "home_odds": 1.85,
        "away_odds": 3.40,
        "scoring_ev": 0.12,
        "sofascore_home_win_prob": 68,
        "sofascore_draw_prob": 18,
        "sofascore_away_win_prob": 14,
        "forebet_prediction": "1",
        "forebet_probability": 72,
        "match_time": "14.03.2026 20:45",
    },
    {
        "home_team": "Barcelona",
        "away_team": "Real Madrid",
        "sport": "football",
        "qualifies": True,
        "scoring_pick": "X",
        "scoring_confidence": 55,
        "ai_composite_confidence": 0,
        "home_odds": 2.10,
        "away_odds": 2.90,
        "match_time": "14.03.2026 18:30",
    },
    {
        "home_team": "Djokovic",
        "away_team": "Nadal",
        "sport": "tennis",
        "qualifies": True,
        "scoring_pick": "A",
        "scoring_confidence": 68,
        "ai_composite_confidence": 70,
        "home_odds": 1.50,
        "away_odds": 2.60,
        "sofascore_home_win_prob": 85,
        "sofascore_draw_prob": None,
        "sofascore_away_win_prob": 15,
        "match_time": "14.03.2026 19:00",
    },
    {
        "home_team": "TeamA",
        "away_team": "TeamB",
        "sport": "basketball",
        "qualifies": False,
        "scoring_pick": "",
        "scoring_confidence": 0,
    },
]


# ---------------------------------------------------------------------------
# Tests: summary builder
# ---------------------------------------------------------------------------

class TestBuildSummary:
    def test_contains_formradar_header(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "FormRadar" in text
        assert "14.03.2026" in text

    def test_groups_by_sport(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "FOOTBALL" in text
        assert "TENNIS" in text
        # non-qualifying basketball should not appear
        assert "BASKETBALL" not in text

    def test_match_details_present(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "Liverpool vs Arsenal" in text
        assert "Djokovic vs Nadal" in text

    def test_match_time_shown(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "🕐 20:45" in text  # Liverpool's match time

    def test_form_advantage_shown(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "Przewaga formy: 75%" in text  # Liverpool's confidence

    def test_pick_odds_shown(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "💰 Kurs:" in text

    def test_signal_count(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "Sygnałów dziś:" in text

    def test_responsible_gambling_footer(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "Typuj odpowiedzialnie" in text

    def test_respects_max_per_sport(self):
        mod = _load_module()
        big_rows = [
            {
                "home_team": f"Home{i}",
                "away_team": f"Away{i}",
                "sport": "football",
                "qualifies": True,
                "scoring_pick": "1",
                "scoring_confidence": 60,
                "home_odds": 1.80,
                "away_odds": 3.00,
            }
            for i in range(200)
        ]
        text = mod._build_summary(big_rows, 200, "2026-03-14")
        # Only 10 matches should appear (cap per sport)
        assert text.count("🏠 Home") == 10

    def test_empty_qualifying(self):
        mod = _load_module()
        rows = [{"home_team": "A", "away_team": "B", "sport": "football", "qualifies": False}]
        text = mod._build_summary(rows, 0, "2026-03-14")
        assert "Brak kwalifikujących" in text


# ---------------------------------------------------------------------------
# Tests: send_telegram_summary — enabled / disabled
# ---------------------------------------------------------------------------

class TestSendSummary:
    def test_disabled_skips_sending(self):
        mod = _load_module(TELEGRAM_ENABLED="false")
        result = mod.send_telegram_summary(_ROWS, 3, "2026-03-14")
        assert result is False

    def test_enabled_calls_api(self):
        mod = _load_module()
        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("telegram_notifier.urllib.request.urlopen", return_value=fake_resp) as mock_open:
            result = mod.send_telegram_summary(_ROWS, 3, "2026-03-14")
            assert result is True
            mock_open.assert_called_once()

            # Verify payload structure
            call_args = mock_open.call_args
            req = call_args[0][0]
            body = json.loads(req.data.decode("utf-8"))
            assert body["chat_id"] == "12345"
            assert body["parse_mode"] == "HTML"
            assert "Liverpool" in body["text"]


# ---------------------------------------------------------------------------
# Tests: failure isolation — Telegram error must not propagate
# ---------------------------------------------------------------------------

class TestFailureIsolation:
    def test_http_error_returns_false(self):
        mod = _load_module()
        import urllib.error
        with patch(
            "telegram_notifier.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="", code=403, msg="Forbidden", hdrs=None, fp=None  # type: ignore[arg-type]
            ),
        ):
            result = mod.send_telegram_summary(_ROWS, 3, "2026-03-14")
            assert result is False

    def test_network_error_retries_then_fails(self):
        mod = _load_module()
        import urllib.error
        with patch(
            "telegram_notifier.urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            result = mod.send_telegram_summary(_ROWS, 3, "2026-03-14")
            assert result is False

    def test_missing_token_returns_false(self):
        mod = _load_module(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="12345")
        # Even when enabled, missing token should fail gracefully
        result = mod._send_message("test")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: odds filter
# ---------------------------------------------------------------------------

class TestOddsFilter:
    def test_both_above_threshold(self):
        mod = _load_module()
        assert mod._passes_odds_filter("football", 1.85, 3.40) is True

    def test_home_below_threshold(self):
        mod = _load_module()
        assert mod._passes_odds_filter("football", 1.20, 3.40) is False

    def test_away_below_threshold(self):
        mod = _load_module()
        assert mod._passes_odds_filter("football", 1.85, 1.10) is False

    def test_missing_odds_passes(self):
        mod = _load_module()
        assert mod._passes_odds_filter("football", None, None) is True
        assert mod._passes_odds_filter("football", 1.85, "") is True

    def test_different_sport_threshold(self):
        mod = _load_module()
        # Basketball threshold is 1.30
        assert mod._passes_odds_filter("basketball", 1.30, 1.30) is True
        assert mod._passes_odds_filter("basketball", 1.20, 1.50) is False


# ---------------------------------------------------------------------------
# Tests: fan vote filter
# ---------------------------------------------------------------------------

class TestFanVoteFilter:
    def test_football_above_65(self):
        mod = _load_module()
        m = {"sofascore_home_win_prob": 68, "sofascore_draw_prob": 18, "sofascore_away_win_prob": 14}
        assert mod._passes_fan_vote_filter("football", m) is True

    def test_football_below_65(self):
        mod = _load_module()
        m = {"sofascore_home_win_prob": 40, "sofascore_draw_prob": 35, "sofascore_away_win_prob": 25}
        assert mod._passes_fan_vote_filter("football", m) is False

    def test_tennis_above_80(self):
        mod = _load_module()
        m = {"sofascore_home_win_prob": 85, "sofascore_away_win_prob": 15}
        assert mod._passes_fan_vote_filter("tennis", m) is True

    def test_tennis_below_80(self):
        mod = _load_module()
        m = {"sofascore_home_win_prob": 55, "sofascore_away_win_prob": 45}
        assert mod._passes_fan_vote_filter("tennis", m) is False

    def test_no_sofascore_data_passes(self):
        mod = _load_module()
        assert mod._passes_fan_vote_filter("football", {}) is True

    def test_none_values_ignored(self):
        mod = _load_module()
        m = {"sofascore_home_win_prob": 85, "sofascore_draw_prob": None, "sofascore_away_win_prob": 15}
        assert mod._passes_fan_vote_filter("tennis", m) is True


# ---------------------------------------------------------------------------
# Tests: filters applied in _build_summary
# ---------------------------------------------------------------------------

class TestFiltersInBuildSummary:
    def test_low_odds_excluded(self):
        mod = _load_module()
        rows = [
            {"home_team": "A", "away_team": "B", "sport": "football",
             "qualifies": True, "home_odds": 1.10, "away_odds": 1.10},
        ]
        text = mod._build_summary(rows, 1, "2026-03-14")
        assert "A vs B" not in text
        assert "Brak kwalifikuj\u0105cych" in text

    def test_low_fanvote_excluded(self):
        mod = _load_module()
        rows = [
            {"home_team": "C", "away_team": "D", "sport": "tennis",
             "qualifies": True, "home_odds": 1.50, "away_odds": 2.60,
             "sofascore_home_win_prob": 55, "sofascore_away_win_prob": 45},
        ]
        text = mod._build_summary(rows, 1, "2026-03-14")
        assert "C vs D" not in text

    def test_no_sofascore_still_included(self):
        mod = _load_module()
        rows = [
            {"home_team": "E", "away_team": "F", "sport": "football",
             "qualifies": True, "home_odds": 1.85, "away_odds": 3.40},
        ]
        text = mod._build_summary(rows, 1, "2026-03-14")
        assert "E vs F" in text

    def test_value_tag_shown(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "💰VALUE" in text  # Liverpool has scoring_ev > 0

    def test_forebet_shown(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "Forebet:" in text  # Liverpool has forebet data

    def test_fan_vote_shown(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "👥" in text  # Liverpool has sofascore data


# ---------------------------------------------------------------------------
# Tests: time filter
# ---------------------------------------------------------------------------

class TestTimeFilter:
    def test_past_match_today_excluded(self):
        mod = _load_module()
        now = datetime(2026, 3, 14, 15, 0)
        rows = [
            {"home_team": "A", "away_team": "B", "sport": "football",
             "qualifies": True, "home_odds": 1.85, "away_odds": 3.40,
             "match_time": "14.03.2026 12:00"},
        ]
        text = mod._build_summary(rows, 1, "2026-03-14", _now=now)
        assert "A vs B" not in text

    def test_future_match_today_included(self):
        mod = _load_module()
        now = datetime(2026, 3, 14, 10, 0)
        rows = [
            {"home_team": "A", "away_team": "B", "sport": "football",
             "qualifies": True, "home_odds": 1.85, "away_odds": 3.40,
             "match_time": "14.03.2026 20:45"},
        ]
        text = mod._build_summary(rows, 1, "2026-03-14", _now=now)
        assert "A vs B" in text

    def test_different_date_not_filtered(self):
        mod = _load_module()
        now = datetime(2026, 3, 15, 15, 0)
        rows = [
            {"home_team": "A", "away_team": "B", "sport": "football",
             "qualifies": True, "home_odds": 1.85, "away_odds": 3.40,
             "match_time": "14.03.2026 12:00"},
        ]
        text = mod._build_summary(rows, 1, "2026-03-14", _now=now)
        assert "A vs B" in text

    def test_no_match_time_included(self):
        mod = _load_module()
        now = datetime(2026, 3, 14, 23, 0)
        rows = [
            {"home_team": "A", "away_team": "B", "sport": "football",
             "qualifies": True, "home_odds": 1.85, "away_odds": 3.40},
        ]
        text = mod._build_summary(rows, 1, "2026-03-14", _now=now)
        assert "A vs B" in text

    def test_invalid_match_time_included(self):
        mod = _load_module()
        now = datetime(2026, 3, 14, 23, 0)
        rows = [
            {"home_team": "A", "away_team": "B", "sport": "football",
             "qualifies": True, "home_odds": 1.85, "away_odds": 3.40,
             "match_time": "invalid format"},
        ]
        text = mod._build_summary(rows, 1, "2026-03-14", _now=now)
        assert "A vs B" in text


# ---------------------------------------------------------------------------
# Tests: pick odds
# ---------------------------------------------------------------------------

class TestPickOdds:
    def test_pick_1_uses_home_odds(self):
        mod = _load_module()
        m = {"scoring_pick": "1", "home_odds": 1.85, "away_odds": 3.40}
        assert mod._pick_odds(m) == "1.85"

    def test_pick_2_uses_away_odds(self):
        mod = _load_module()
        m = {"scoring_pick": "2", "home_odds": 1.85, "away_odds": 3.40}
        assert mod._pick_odds(m) == "3.40"

    def test_pick_a_uses_away_odds(self):
        mod = _load_module()
        m = {"scoring_pick": "A", "home_odds": 1.85, "away_odds": 3.40}
        assert mod._pick_odds(m) == "3.40"

    def test_pick_x_uses_draw_odds(self):
        mod = _load_module()
        m = {"scoring_pick": "X", "home_odds": 1.85, "away_odds": 3.40, "draw_odds": 3.10}
        assert mod._pick_odds(m) == "3.10"

    def test_pick_x_fallback_to_home(self):
        mod = _load_module()
        m = {"scoring_pick": "X", "home_odds": 1.85, "away_odds": 3.40}
        assert mod._pick_odds(m) == "1.85"

    def test_missing_odds_returns_empty(self):
        mod = _load_module()
        m = {"scoring_pick": "1"}
        assert mod._pick_odds(m) == ""

    def test_no_pick_fallback_to_home(self):
        mod = _load_module()
        m = {"home_odds": 1.85, "away_odds": 3.40}
        assert mod._pick_odds(m) == "1.85"
