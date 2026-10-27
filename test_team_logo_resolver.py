"""
Tests for team_logo_resolver – cache, batch enrichment, edge cases.

These tests mock network calls so they run offline and fast.
"""

from typing import Any, Dict
from unittest.mock import patch, MagicMock
import json
import pytest

from team_logo_resolver import (
    get_logo_url,
    get_logo_url_cached_only,
    enrich_matches_with_logos,
    _normalize_name,  # pyright: ignore[reportPrivateUsage]
    _mem_cache,  # pyright: ignore[reportPrivateUsage]
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_urlopen(badge_url: str = "https://r2.thesportsdb.com/badge.png") -> MagicMock:
    """Return a mock context-manager for urllib.request.urlopen."""
    resp = MagicMock()
    resp.read.return_value = json.dumps({
        "teams": [{"strTeam": "Arsenal", "strBadge": badge_url, "strLogo": ""}]
    }).encode()
    resp.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _fake_urlopen_no_teams() -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps({"teams": None}).encode()
    resp.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.fixture(autouse=True)
def _clear_cache() -> None:  # type: ignore[misc]
    """Reset in-memory cache before each test."""
    _mem_cache.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_strips_and_lowercases(self) -> None:
        assert _normalize_name("  Real Madrid  ") == "real madrid"

    def test_empty(self) -> None:
        assert _normalize_name("") == ""


class TestGetLogoUrl:
    @patch("team_logo_resolver._save_file_cache")
    @patch("team_logo_resolver.urllib.request.urlopen")
    def test_returns_badge(self, mock_open: Any, _save: Any) -> None:
        mock_open.return_value = _fake_urlopen("https://r2.thesportsdb.com/arsenal.png")
        url = get_logo_url("Arsenal")
        assert url == "https://r2.thesportsdb.com/arsenal.png"

    @patch("team_logo_resolver._save_file_cache")
    @patch("team_logo_resolver.urllib.request.urlopen")
    def test_returns_none_for_unknown_team(self, mock_open: Any, _save: Any) -> None:
        mock_open.return_value = _fake_urlopen_no_teams()
        url = get_logo_url("XYZNONEXISTENT")
        assert url is None

    def test_returns_none_for_empty_name(self) -> None:
        assert get_logo_url("") is None
        assert get_logo_url("   ") is None

    @patch("team_logo_resolver._save_file_cache")
    @patch("team_logo_resolver.urllib.request.urlopen")
    def test_uses_cache_on_second_call(self, mock_open: Any, _save: Any) -> None:
        mock_open.return_value = _fake_urlopen("https://r2.thesportsdb.com/a.png")
        get_logo_url("Arsenal")
        # Second call should NOT hit network
        mock_open.reset_mock()
        url2 = get_logo_url("Arsenal")
        assert url2 == "https://r2.thesportsdb.com/a.png"
        mock_open.assert_not_called()

    @patch("team_logo_resolver._save_file_cache")
    @patch("team_logo_resolver.urllib.request.urlopen")
    def test_caches_negative_result(self, mock_open: Any, _save: Any) -> None:
        mock_open.return_value = _fake_urlopen_no_teams()
        url = get_logo_url("Unknown FC")
        assert url is None
        # Should not re-fetch
        mock_open.reset_mock()
        url2 = get_logo_url("Unknown FC")
        assert url2 is None
        mock_open.assert_not_called()


class TestCachedOnlyLookup:
    @patch("team_logo_resolver._save_file_cache")
    @patch("team_logo_resolver.urllib.request.urlopen")
    def test_returns_cached_value(self, mock_open: Any, _save: Any) -> None:
        mock_open.return_value = _fake_urlopen("https://r2.thesportsdb.com/barca.png")
        get_logo_url("Barcelona")
        url = get_logo_url_cached_only("Barcelona")
        assert url == "https://r2.thesportsdb.com/barca.png"

    def test_returns_none_when_not_cached(self) -> None:
        assert get_logo_url_cached_only("NeverCached") is None


class TestEnrichMatches:
    @patch("team_logo_resolver._save_file_cache")
    @patch("team_logo_resolver.urllib.request.urlopen")
    def test_adds_logo_fields(self, mock_open: Any, _save: Any) -> None:
        mock_open.return_value = _fake_urlopen("https://r2.thesportsdb.com/x.png")
        matches: list[Dict[str, Any]] = [
            {"home_team": "Arsenal", "away_team": "Chelsea"},
            {"home_team": "Arsenal", "away_team": "Liverpool"},
        ]
        enrich_matches_with_logos(matches)

        assert matches[0]["home_logo_url"] == "https://r2.thesportsdb.com/x.png"
        assert matches[0]["away_logo_url"] == "https://r2.thesportsdb.com/x.png"
        assert matches[1]["home_logo_url"] == "https://r2.thesportsdb.com/x.png"

    @patch("team_logo_resolver._save_file_cache")
    @patch("team_logo_resolver.urllib.request.urlopen")
    def test_unique_lookups_only(self, mock_open: Any, _save: Any) -> None:
        """Each unique team name should trigger at most one network call."""
        mock_open.return_value = _fake_urlopen("https://r2.thesportsdb.com/y.png")
        matches: list[Dict[str, Any]] = [
            {"home_team": "Arsenal", "away_team": "Chelsea"},
            {"home_team": "Arsenal", "away_team": "Chelsea"},
        ]
        enrich_matches_with_logos(matches)
        # 2 unique teams = 2 calls (Arsenal, Chelsea)
        assert mock_open.call_count == 2

    def test_handles_missing_team_names(self) -> None:
        matches: list[Dict[str, Any]] = [{"sport": "tennis"}]
        enrich_matches_with_logos(matches)
        assert matches[0]["home_logo_url"] is None
        assert matches[0]["away_logo_url"] is None
