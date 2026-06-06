# -*- coding: utf-8 -*-
"""Tests for the AiScore table-tennis parser (pure functions, offline)."""

import os

import pytest

from aiscore_scraper import (
    parse_aiscore_matches,
    parse_h2h_header,
    h2h_url_for,
    filter_h2h,
    h2h_record,
    recent_form,
    favourite_meets_h2h_threshold,
    normalize_name,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "aiscore_tt_h2h.html")
PAGE_FIXTURE = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "aiscore_tt_h2h_page.html")


@pytest.fixture(scope="module")
def h2h_html():
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def h2h_page_html():
    with open(PAGE_FIXTURE, "r", encoding="utf-8") as fh:
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


# ---------------------------------------------------------------------------
# /h2h sub-page: header parsing, URL building, dedupe across sections
# ---------------------------------------------------------------------------

def test_h2h_url_for_appends_and_is_idempotent():
    base = "https://www.aiscore.com/table-tennis/match-a-b/527rxsr5xw0c47e"
    assert h2h_url_for(base) == base + "/h2h"
    assert h2h_url_for(base + "/h2h") == base + "/h2h"
    assert h2h_url_for(base + "/?x=1#frag") == base + "/h2h"


def test_parse_h2h_header_returns_home_then_away(h2h_page_html):
    header = parse_h2h_header(h2h_page_html)
    assert header is not None
    home, away = header
    assert normalize_name(home) == normalize_name("Michal Szostak")
    assert normalize_name(away) == normalize_name("Komorowicz, Jakub")


def test_full_page_h2h_record_dedupes_to_four_of_six(h2h_page_html):
    # The page has direct H2H + two form sections; the direct meeting must be
    # counted once even if it also appears in a form section.
    matches = parse_aiscore_matches(h2h_page_html)
    rec = h2h_record(matches, "Michal Szostak", "Komorowicz, Jakub")
    assert rec["total"] == 6
    assert rec["a_wins"] == 4
    assert rec["b_wins"] == 2
    assert rec["a_win_rate"] == pytest.approx(0.6667, abs=1e-3)


def test_full_page_form_sections_populate(h2h_page_html):
    matches = parse_aiscore_matches(h2h_page_html)
    # Szostak appears in direct (6) + his form section (4) -> recent_form has data.
    szostak_form = recent_form(matches, "Michal Szostak", limit=10)
    assert "W" in szostak_form and len(szostak_form) >= 5
    komo_form = recent_form(matches, "Komorowicz, Jakub", limit=10)
    assert len(komo_form) >= 5


def test_process_match_uses_header_for_participants(monkeypatch, h2h_page_html):
    import table_tennis_aiscore_pipeline as pipe

    monkeypatch.setattr(
        pipe, "get_sofascore_prediction",
        lambda *a, **k: {"found": True, "home_win_prob": 60.0,
                         "away_win_prob": 40.0, "total_votes": 30},
    )
    driver = _FakeDriver(h2h_page_html)
    row = pipe.process_match(driver, "https://www.aiscore.com/table-tennis/match-a-b/527",
                             focus="home", date_str="2026-06-06", verbose=False)
    assert row is not None
    assert normalize_name(row["home_team"]) == normalize_name("Michal Szostak")
    assert normalize_name(row["away_team"]) == normalize_name("Komorowicz, Jakub")
    assert row["qualifies"] is True
    assert row["h2h_fav_win_rate"] == pytest.approx(0.6667, abs=1e-3)
    # Form must be populated (the user's "brak formy" complaint).
    assert len(row["form_a"]) >= 1


# ---------------------------------------------------------------------------
# SofaScore infrastructure fallback (whole-run Cloudflare block)
# ---------------------------------------------------------------------------

def test_rescue_requalifies_only_fanvote_failures():
    import table_tennis_aiscore_pipeline as pipe

    rows = [
        # H2H passed but no fan vote -> should be rescued.
        {"qualifies": False, "tt_skip_reason": "sofascore_fan_vote_required"},
        # Failed H2H -> must NOT be rescued.
        {"qualifies": False, "tt_skip_reason": "h2h_fav_win_rate 0.50 < 0.60"},
        # Already qualifying -> untouched.
        {"qualifies": True, "tt_skip_reason": None},
    ]
    rescued = pipe._rescue_when_sofascore_unreachable(rows)
    assert rescued == 1
    assert rows[0]["qualifies"] is True
    assert rows[0]["sofascore_unavailable"] is True
    assert rows[0]["tt_skip_reason"] is None
    assert rows[1]["qualifies"] is False          # H2H failure stays rejected
    assert rows[2]["qualifies"] is True


# ---------------------------------------------------------------------------
# Pinnacle odds: AiScore -> Livesport fuzzy URL match
# ---------------------------------------------------------------------------

def test_match_livesport_url_by_surnames():
    import table_tennis_aiscore_pipeline as pipe

    index = [
        {"url": "https://www.livesport.com/pl/mecz/tenis-stolowy/szostak-komorowicz/AbCd12ef/",
         "tokens": {"szostak", "komorowicz"}},
        {"url": "https://www.livesport.com/pl/mecz/tenis-stolowy/cizek-kindl/Zz99Yy88/",
         "tokens": {"cizek", "kindl"}},
    ]
    url = pipe._match_livesport_url("Michal Szostak", "Komorowicz, Jakub", index)
    assert url is not None and "szostak-komorowicz" in url

    # Only one surname overlaps -> below the 2-token threshold -> no match.
    none_url = pipe._match_livesport_url("Michal Szostak", "Nieznany Gracz", index)
    assert none_url is None


def test_resolve_odds_no_url_returns_empty():
    import table_tennis_aiscore_pipeline as pipe
    out = pipe.resolve_odds("A", "B", None)
    assert out == {"home_odds": None, "away_odds": None, "bookmaker": None}
