# -*- coding: utf-8 -*-
"""Tests for the AiScore table-tennis parser (pure functions, offline)."""

import os

import pytest

from aiscore_scraper import (
    parse_aiscore_matches,
    filter_h2h,
    h2h_record,
    recent_form,
    favourite_meets_h2h_threshold,
    normalize_name,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "aiscore_tt_h2h.html")


@pytest.fixture(scope="module")
def h2h_html():
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        return fh.read()


def test_parses_all_six_matches(h2h_html):
    matches = parse_aiscore_matches(h2h_html)
    assert len(matches) == 6
    # Every match must carry both team names.
    for m in matches:
        assert m["home"]
        assert m["away"]


def test_normalize_name_handles_comma_and_order():
    assert normalize_name("Komorowicz, Jakub") == normalize_name("Jakub Komorowicz")
    assert normalize_name("Michal Szostak") == normalize_name("Szostak Michal")


def test_winner_derived_from_score_not_collect_badge(h2h_html):
    matches = parse_aiscore_matches(h2h_html)
    # Match 1 in fixture: Szostak 1, Komorowicz 3 -> Komorowicz wins
    first = matches[0]
    assert first["home_score"] == 1
    assert first["away_score"] == 3
    assert normalize_name(first["winner"]) == normalize_name("Komorowicz, Jakub")


def test_h2h_record_szostak_four_of_six(h2h_html):
    matches = parse_aiscore_matches(h2h_html)
    rec = h2h_record(matches, "Michal Szostak", "Komorowicz, Jakub")
    assert rec["total"] == 6
    assert rec["a_wins"] == 4          # Szostak
    assert rec["b_wins"] == 2          # Komorowicz
    assert rec["a_win_rate"] == pytest.approx(0.6667, abs=1e-3)


def test_filter_h2h_returns_only_direct_pair(h2h_html):
    matches = parse_aiscore_matches(h2h_html)
    direct = filter_h2h(matches, "Michal Szostak", "Komorowicz, Jakub")
    assert len(direct) == 6


def test_favourite_meets_threshold_at_60pct(h2h_html):
    matches = parse_aiscore_matches(h2h_html)
    # Szostak is the favourite with 66.7% -> passes the 60% rule.
    passes, rec = favourite_meets_h2h_threshold(
        matches, "Michal Szostak", "Komorowicz, Jakub", threshold=0.60
    )
    assert passes is True
    assert rec["fav_win_rate"] == pytest.approx(0.6667, abs=1e-3)

    # Komorowicz as the "favourite" only has 33.3% -> fails.
    fails, rec2 = favourite_meets_h2h_threshold(
        matches, "Komorowicz, Jakub", "Michal Szostak", threshold=0.60
    )
    assert fails is False
    assert rec2["fav_win_rate"] == pytest.approx(0.3333, abs=1e-3)


def test_recent_form_for_szostak(h2h_html):
    matches = parse_aiscore_matches(h2h_html)
    form = recent_form(matches, "Michal Szostak", limit=6)
    # 6 H2H matches all involve Szostak; 4 wins / 2 losses, most-recent first.
    assert len(form) == 6
    assert form.count("W") == 4
    assert form.count("L") == 2


def test_recent_form_home_venue_split(h2h_html):
    matches = parse_aiscore_matches(h2h_html)
    # Matches where Szostak was the HOME side (first 4 in the fixture).
    home_form = recent_form(matches, "Michal Szostak", venue="home", limit=10)
    away_form = recent_form(matches, "Michal Szostak", venue="away", limit=10)
    assert len(home_form) == 4
    assert len(away_form) == 2


# ---------------------------------------------------------------------------
# Pipeline integration (process_match) — uses a fake driver + mocked Fan Vote
# ---------------------------------------------------------------------------

class _FakeDriver:
    """Minimal stand-in: scrape_match_page only needs page_source + get/exec."""

    def __init__(self, html):
        self._html = html

    def get(self, url):
        pass

    def execute_script(self, *a, **k):
        return None

    @property
    def page_source(self):
        return self._html

    def quit(self):
        pass


def test_process_match_home_focus_qualifies(monkeypatch, h2h_html):
    import table_tennis_aiscore_pipeline as pipe

    # Fan Vote present (mandatory gate satisfied).
    monkeypatch.setattr(
        pipe, "get_sofascore_prediction",
        lambda *a, **k: {"found": True, "home_win_prob": 62.0,
                         "away_win_prob": 38.0, "total_votes": 120},
    )
    driver = _FakeDriver(h2h_html)
    row = pipe.process_match(driver, "https://www.aiscore.com/table-tennis/match-x",
                             focus="home", date_str="2026-06-05", verbose=False)
    assert row is not None
    # Szostak (home) has 66.7% H2H -> H2H gate passes; Fan Vote present -> qualifies.
    assert row["qualifies"] is True
    assert row["sofascore_found"] is True
    assert row["h2h_fav_win_rate"] == pytest.approx(0.6667, abs=1e-3)


def test_process_match_blocks_without_fan_vote(monkeypatch, h2h_html):
    import table_tennis_aiscore_pipeline as pipe

    # Fan Vote MISSING -> mandatory gate must block qualification.
    monkeypatch.setattr(pipe, "get_sofascore_prediction", lambda *a, **k: {"found": False})
    driver = _FakeDriver(h2h_html)
    row = pipe.process_match(driver, "https://www.aiscore.com/table-tennis/match-x",
                             focus="home", date_str="2026-06-05", verbose=False)
    assert row is not None
    assert row["qualifies"] is False
    assert row["tt_skip_reason"] == "sofascore_fan_vote_required"


def test_process_match_away_focus_blocked_by_h2h(monkeypatch, h2h_html):
    import table_tennis_aiscore_pipeline as pipe

    monkeypatch.setattr(
        pipe, "get_sofascore_prediction",
        lambda *a, **k: {"found": True, "home_win_prob": 40.0,
                         "away_win_prob": 60.0, "total_votes": 50},
    )
    driver = _FakeDriver(h2h_html)
    # away = Komorowicz with only 33.3% H2H -> below 60% -> blocked.
    row = pipe.process_match(driver, "https://www.aiscore.com/table-tennis/match-x",
                             focus="away", date_str="2026-06-05", verbose=False)
    assert row is not None
    assert row["qualifies"] is False
    assert "h2h_fav_win_rate" in row["tt_skip_reason"]
