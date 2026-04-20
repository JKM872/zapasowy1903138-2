# pyright: reportMissingParameterType=false, reportUnknownParameterType=false
"""Tests for the OddsSafari dropping-odds scraper and pipeline.

Covers:
- HTML fixture parsing into structured rows
- Sport slug mapping (known, unknown, aliases)
- ``is_qualifying_row`` boundary behaviour
- Livesport URL resolver scoring (with ``get_match_links_from_day`` mocked)
- Pipeline serialization of an event
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from oddssafari_dropping_scraper import (
    DroppingOddsRow,
    is_qualifying_row,
    is_livesport_supported_sport,
    map_slug_to_internal,
    parse_dropping_odds_table,
)
from oddssafari_dropping_pipeline import (
    _focus_team_from_outcome,
    _serialize_event,
    resolve_livesport_match_url,
)
from ci_oddssafari_summary import main as ci_oddssafari_main


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

FIXTURE_PATH = os.path.join(
    HERE, "tests", "fixtures", "oddssafari_table.html"
)


def _load_fixture() -> str:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# parse_dropping_odds_table
# ---------------------------------------------------------------------------


class TestParseDroppingOddsTable:
    def test_parses_all_rows(self):
        rows = parse_dropping_odds_table(_load_fixture())
        # 6 match rows (including two outcomes for Bayamon and the MMA/tennis
        # rows): 1 soccer + 2 basketball + 1 ofc + 1 tennis + 1 mma = 6
        assert len(rows) == 6

    def test_carries_league_header_between_rows(self):
        rows = parse_dropping_odds_table(_load_fixture())
        leagues = [r.league for r in rows]
        assert leagues[0].startswith("Argentina")
        assert leagues[1].startswith("Puerto Rico")
        assert leagues[2].startswith("Puerto Rico")
        assert leagues[3].startswith("International Clubs")
        assert leagues[4].startswith("ATP")
        assert leagues[5].startswith("International Clubs - MMA")

    def test_extracts_teams_and_outcome(self):
        rows = parse_dropping_odds_table(_load_fixture())
        first = rows[0]
        assert first.home_team == "San Lorenzo"
        assert first.away_team == "Velez Sarsfield"
        assert first.outcome == "2"

    def test_parses_numeric_columns(self):
        rows = parse_dropping_odds_table(_load_fixture())
        first = rows[0]
        assert first.open_odds == 2.98
        assert first.current_odds == 1.85
        assert first.drop_pct == -38.0

    def test_extracts_sport_from_match_url(self):
        rows = parse_dropping_odds_table(_load_fixture())
        slugs = {r.sport_slug for r in rows}
        assert {"soccer", "basketball", "tennis", "mma"} <= slugs

    def test_match_id_parsed_from_url(self):
        rows = parse_dropping_odds_table(_load_fixture())
        first = rows[0]
        assert first.match_id == "2213259"

    def test_absolute_url_is_resolved(self):
        rows = parse_dropping_odds_table(_load_fixture())
        for row in rows:
            assert row.match_url.startswith("https://www.oddssafari.com/")

    def test_event_date_time_parsed(self):
        rows = parse_dropping_odds_table(_load_fixture())
        assert rows[0].event_date == "20/04"
        assert rows[0].event_time == "22:30"


# ---------------------------------------------------------------------------
# Sport slug mapping
# ---------------------------------------------------------------------------


class TestSportMapping:
    def test_soccer_maps_to_football(self):
        assert map_slug_to_internal("soccer") == "football"

    def test_ice_hockey_normalized(self):
        assert map_slug_to_internal("ice-hockey") == "hockey"

    def test_unknown_slug_returns_none(self):
        assert map_slug_to_internal("cornhole") is None

    def test_case_insensitive(self):
        assert map_slug_to_internal("Basketball") == "basketball"

    def test_mma_is_unsupported(self):
        assert map_slug_to_internal("mma") is None
        assert is_livesport_supported_sport("mma") is False

    def test_tennis_is_supported(self):
        assert is_livesport_supported_sport("tennis") is True


# ---------------------------------------------------------------------------
# is_qualifying_row
# ---------------------------------------------------------------------------


def _row(
    *,
    current=1.80,
    slug="soccer",
    home="Home FC",
    away="Away FC",
    outcome="1",
):
    return DroppingOddsRow(
        league="L",
        match_url="https://example.com/matches/soccer/a/b/c/1",
        match_id="1",
        sport_slug=slug,
        sport=map_slug_to_internal(slug),
        home_team=home,
        away_team=away,
        event_date="21/04",
        event_time="20:00",
        outcome=outcome,
        open_odds=2.00,
        current_odds=current,
        drop_pct=-10.0,
    )


class TestIsQualifyingRow:
    def test_in_range_qualifies(self):
        ok, reason = is_qualifying_row(_row(current=1.60))
        assert ok is True
        assert reason is None

    def test_below_min_does_not_qualify(self):
        ok, reason = is_qualifying_row(_row(current=1.34))
        assert ok is False
        assert reason == "odds_out_of_range"

    def test_above_max_does_not_qualify(self):
        ok, reason = is_qualifying_row(_row(current=2.01))
        assert ok is False
        assert reason == "odds_out_of_range"

    def test_inclusive_lower_bound(self):
        ok, _ = is_qualifying_row(_row(current=1.35))
        assert ok is True

    def test_inclusive_upper_bound(self):
        ok, _ = is_qualifying_row(_row(current=2.00))
        assert ok is True

    def test_unsupported_sport_rejected(self):
        ok, reason = is_qualifying_row(_row(slug="mma"))
        assert ok is False
        assert reason == "unsupported_sport"

    def test_missing_teams_rejected(self):
        ok, reason = is_qualifying_row(_row(home="", away="X"))
        assert ok is False
        assert reason == "missing_teams"

    def test_missing_current_odds_rejected(self):
        row = _row()
        row.current_odds = None
        ok, reason = is_qualifying_row(row)
        assert ok is False
        assert reason == "missing_current_odds"


# ---------------------------------------------------------------------------
# Focus team mapping
# ---------------------------------------------------------------------------


class TestFocusTeamMapping:
    def test_outcome_1(self):
        assert _focus_team_from_outcome("1") == ("home", False)

    def test_outcome_2(self):
        assert _focus_team_from_outcome("2") == ("away", True)

    def test_outcome_x(self):
        assert _focus_team_from_outcome("X") == ("draw", False)

    def test_outcome_unknown(self):
        assert _focus_team_from_outcome("") == (None, False)


# ---------------------------------------------------------------------------
# Livesport URL resolver
# ---------------------------------------------------------------------------


class TestResolveLivesportMatchUrl:
    def test_picks_best_candidate(self):
        candidates = [
            "https://www.livesport.com/pl/mecz/foo-bar/abc",
            "https://www.livesport.com/pl/mecz/san-lorenzo-velez-sarsfield/xyz",
            "https://www.livesport.com/pl/mecz/other-match/def",
        ]
        with patch(
            "livesport_h2h_scraper.get_match_links_from_day",
            return_value=candidates,
        ):
            url, conf = resolve_livesport_match_url(
                driver=object(),
                home_team="San Lorenzo",
                away_team="Velez Sarsfield",
                sport="football",
                date="2026-04-21",
            )
        assert "san-lorenzo" in url
        assert conf > 0.5

    def test_returns_none_when_no_candidates_match(self):
        with patch(
            "livesport_h2h_scraper.get_match_links_from_day",
            return_value=[
                "https://www.livesport.com/pl/mecz/foo-bar/abc",
            ],
        ):
            url, conf = resolve_livesport_match_url(
                driver=object(),
                home_team="San Lorenzo",
                away_team="Velez Sarsfield",
                sport="football",
                date="2026-04-21",
            )
        assert url is None
        assert conf == 0.0

    def test_empty_url_list_returns_none(self):
        with patch(
            "livesport_h2h_scraper.get_match_links_from_day",
            return_value=[],
        ):
            url, conf = resolve_livesport_match_url(
                driver=object(),
                home_team="A",
                away_team="B",
                sport="football",
                date="2026-04-21",
            )
        assert url is None
        assert conf == 0.0


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerializeEvent:
    def test_qualified_event_keeps_raw_fields_and_flags(self):
        row = _row(outcome="1")
        event = _serialize_event(
            row,
            qualifies=True,
            skip_reason=None,
            enrichment={
                "status": "enriched",
                "livesport_url": "https://ls/m",
                "livesport_confidence": 0.9,
                "enrichment": {"win_rate": 0.6},
                "error": None,
            },
        )
        assert event["qualifies"] is True
        assert event["skip_reason"] is None
        assert event["dropped_outcome"] == "1"
        assert event["focus_team"] == "home"
        assert event["away_team_focus"] is False
        assert event["enrichment_status"] == "enriched"
        assert event["livesport_url"] == "https://ls/m"
        assert event["enrichment"] == {"win_rate": 0.6}

    def test_rejected_event_captures_reason(self):
        row = _row(slug="mma")
        event = _serialize_event(
            row,
            qualifies=False,
            skip_reason="unsupported_sport",
        )
        assert event["qualifies"] is False
        assert event["skip_reason"] == "unsupported_sport"
        assert event.get("enrichment") is None


# ---------------------------------------------------------------------------
# ci_oddssafari_summary.py
# ---------------------------------------------------------------------------


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


class TestCiOddsSafariSummary:
    def test_missing_file_is_graceful(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist.json"
        rc = ci_oddssafari_main(["prog", str(missing)])
        captured = capsys.readouterr().out
        assert rc == 0
        assert "No output file" in captured
        assert str(missing) in captured

    def test_valid_payload_renders_markdown(self, tmp_path, capsys):
        path = tmp_path / "oddssafari_dropping_2026-04-21.json"
        _write_json(path, {
            "meta": {
                "totals": {"events": 42, "qualified": 7},
                "filter": {"min_odds": 1.35, "max_odds": 2.0},
                "enrichment_status_counts": {
                    "enriched": 5, "resolve_failed": 2,
                },
                "skip_reason_counts": {
                    "odds_out_of_range": 25,
                    "unsupported_sport": 8,
                    "missing_teams": 2,
                },
            },
            "events": [],
            "qualified": [],
        })

        rc = ci_oddssafari_main(["prog", str(path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert str(path) in out
        assert "Events: **42**" in out
        assert "qualified: **7**" in out
        assert "min=1.35" in out and "max=2.0" in out
        assert "enriched" in out and "resolve_failed" in out
        assert "Top skip reasons" in out
        assert "`odds_out_of_range`: 25" in out

    def test_top_skip_reasons_are_capped_and_sorted(self, tmp_path, capsys):
        path = tmp_path / "summary.json"
        reasons = {f"reason_{i}": (10 - i) for i in range(8)}
        _write_json(path, {
            "meta": {
                "totals": {"events": 0, "qualified": 0},
                "filter": {"min_odds": 1.35, "max_odds": 2.0},
                "skip_reason_counts": reasons,
            },
        })

        rc = ci_oddssafari_main(["prog", str(path)])
        out = capsys.readouterr().out
        assert rc == 0
        shown = [line for line in out.splitlines() if line.startswith("  - `reason_")]
        assert len(shown) == 5
        assert shown[0].startswith("  - `reason_0`:")
        assert shown[-1].startswith("  - `reason_4`:")

    def test_malformed_json_does_not_crash(self, tmp_path, capsys):
        path = tmp_path / "broken.json"
        path.write_text("{not valid json", encoding="utf-8")
        rc = ci_oddssafari_main(["prog", str(path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Could not read" in out

    def test_missing_argument_returns_error(self, capsys):
        rc = ci_oddssafari_main(["prog"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "usage" in err.lower()
