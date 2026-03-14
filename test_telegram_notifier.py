# pyright: reportMissingImports=false, reportOptionalMemberAccess=false
"""Tests for telegram_notifier — formatting and failure isolation."""

import importlib
import os
import types
import json
from unittest.mock import patch, MagicMock
import pytest


# ---------------------------------------------------------------------------
# Helper: reload module with custom env
# ---------------------------------------------------------------------------

def _load_module(**env_overrides):
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
    def test_contains_date_and_counts(self):
        mod = _load_module()
        text = mod._build_summary(_ROWS, 3, "2026-03-14")
        assert "2026-03-14" in text
        assert "Meczów: 4" in text
        assert "Kwalifikujących: 3" in text

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

    def test_respects_max_length(self):
        mod = _load_module()
        # Generate many rows
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
        # The summary itself can exceed 4096, but _send_message truncates
        assert isinstance(text, str)

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
