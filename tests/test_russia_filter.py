import json

import pytest
from bs4 import BeautifulSoup

import russia_filter
from livesport_h2h_scraper import _extract_match_links_from_soup


def test_is_russian_variants():
    for t in ("Russia", "ROSJA: Premier Liga", "Russia - Premier League",
              "KHL", "VHL", "Rosyjska Superliga", "VTB United League"):
        assert russia_filter.is_russian(t), t
    for t in ("Poland", "Belarus - Vysshaya Liga", "Prussia Cup", "England",
              "Premier League", "", None):
        assert not russia_filter.is_russian(t), t


def test_disable_by_env(monkeypatch):
    monkeypatch.setenv("SKIP_RUSSIA", "0")
    assert not russia_filter.is_russian("Russia")


def test_filter_rows_dict_and_obj():
    class R:
        def __init__(self, league):
            self.league = league
    rows = [{"country": "Russia", "league": "Premier Liga"},
            {"country": "Poland", "league": "Ekstraklasa"}]
    assert len(russia_filter.filter_rows(rows, "country", "league")) == 1
    objs = [R("Russia - FNL"), R("Spain - LaLiga")]
    assert [o.league for o in russia_filter.filter_rows(objs, "league")] == ["Spain - LaLiga"]


def test_livesport_links_skip_russian_header():
    html = """
    <div class="headerLeague__wrapper"><span>ROSJA:</span><a>Premier Liga</a></div>
    <div class="event__match"><a href="/pl/mecz/pilka-nozna/a-b/x1/">m</a></div>
    <div class="headerLeague__wrapper"><span>POLSKA:</span><a>Ekstraklasa</a></div>
    <div class="event__match"><a href="/pl/mecz/pilka-nozna/c-d/x2/">m</a></div>
    """
    links, _ = _extract_match_links_from_soup(
        BeautifulSoup(html, "html.parser"), "https://www.livesport.com/pl/", set())
    assert len(links) == 1 and "c-d" in links[0]


def test_russian_teams_and_national_sides():
    for t in ("Rosja", "Russia U21", "Rosja K", "Spartak Moskwa", "CSKA Moscow",
              "Zenit St. Petersburg", "Rubin Kazań", "Lokomotiw Moskwa", "Achmat Grozny",
              "Krylja Sowietow Samara", "Ak Bars Kazan", "SKA St. Petersburg",
              "Metallurg Magnitogorsk", "UNICS Kazan", "Dynamo Machaczkała"):
        assert russia_filter.is_russian(t), t
    # Kluby o podobnych nazwach z innych krajów nie mogą wypaść.
    for t in ("Spartak Trnava", "CSKA Sofia", "Lokomotiv Plovdiv", "Dynamo Kyiv",
              "Dynamo Dresden", "Torpedo Kutaisi", "JKS Jarosław", "Metallurg Zhlobin",
              "Belarus", "Legia Warszawa", "Real Madrid"):
        assert not russia_filter.is_russian(t), t


def test_livesport_url_slugs():
    assert russia_filter.is_russian_url(
        "https://www.livesport.com/pl/mecz/pilka-nozna/bialorus-Ab12/rosja-Cd34/?mid=x")
    assert russia_filter.is_russian_url(
        "https://www.livesport.com/pl/mecz/hokej/ak-bars-kazan-Ab12/ska-Cd34/")
    assert not russia_filter.is_russian_url(
        "https://www.livesport.com/pl/mecz/pilka-nozna/legia-Ab12/lech-Cd34/")


def test_individual_sports_are_kept():
    rows = [{"sport": "tennis", "league": "ATP Moscow", "home_team": "Rublev"},
            {"sport": "table_tennis", "league": "Russia - Liga Pro"},
            {"sport": "football", "league": "Russia - Premier League"}]
    kept = russia_filter.filter_rows(rows, "league", "home_team")
    assert [r["sport"] for r in kept] == ["tennis", "table_tennis"]
    assert russia_filter.filter_rows(rows[:1], "league", sport="tennis") == rows[:1]


def test_livesport_tennis_links_kept():
    html = """
    <div class="headerLeague__wrapper"><span>ROSJA:</span><a>Kazan Challenger</a></div>
    <div class="event__match"><a href="/pl/mecz/tenis/rublev-Ab12/medvedev-Cd34/">m</a></div>
    """
    links, _ = _extract_match_links_from_soup(
        BeautifulSoup(html, "html.parser"), "https://www.livesport.com/pl/tenis/", set())
    assert len(links) == 1


# ── Forebet league codes (S-1): rows carry "RU2" with an empty country ──────

# Every (sport, code) pair seen in results/matches_*_forebet.json 09-12..11-01.
OBSERVED_CODES = [("basketball", "RU2"), ("basketball", "RUC"), ("basketball", "RUS"),
                  ("handball", "RU1"), ("handball", "RUW"),
                  ("hockey", "RU1"), ("hockey", "RU2"), ("hockey", "RU4"), ("hockey", "RUW"),
                  ("volleyball", "RU1"), ("volleyball", "RUC"), ("volleyball", "RUW"),
                  # Non-RU* codes (all codes scanned): per-sport table.
                  ("basketball", "RCW"), ("basketball", "RW2"), ("volleyball", "RW2"),
                  ("volleyball", "RWC"), ("rugby", "PLE")]
FIELDS = ("league", "country", "homeTeam", "awayTeam")


def _row(league, home="Irbis", away="Chaika", **kw):
    # "Irbis" / "Chaika" (MHL) are not caught by any name pattern: only the code tells.
    return {"league": league, "country": "", "homeTeam": home, "awayTeam": away, **kw}


@pytest.mark.parametrize("sport, code", OBSERVED_CODES)
def test_forebet_russian_codes_dropped_for_their_sport(sport, code):
    assert russia_filter.filter_rows([_row(code)], *FIELDS, sport=sport) == []


def test_other_codes_and_individual_sports_kept():
    for code in ("KZ1", "UA1", "RO1", "URC", "FRU", "BY1"):
        assert not russia_filter.is_russian(code), code
        assert russia_filter.filter_rows([_row(code)], *FIELDS, sport="hockey") == [_row(code)]
    tennis = [_row("RU1", "A. Rublev", "K. Khachanov")]
    assert russia_filter.filter_rows(tennis, *FIELDS, sport="tennis") == tennis
    per_row = [_row("RU1", sport="tennis")]
    assert russia_filter.filter_rows(per_row, *FIELDS) == per_row
    # Only a whole field equal to a code: a Belgian "RUS Rebecq" is not one.
    assert not russia_filter.is_russian("RUS Rebecq") and not russia_filter.is_russian("ru1")


def test_sport_specific_codes_not_global():
    # Volleyball RCW = Serbian women's cup, basketball RWC = Romanian league.
    for sport, code in (("volleyball", "RCW"), ("basketball", "RWC"), ("hockey", "PLE")):
        assert russia_filter.filter_rows([_row(code)], *FIELDS, sport=sport) == [_row(code)]
    assert russia_filter.filter_rows([_row("RW2", sport="volleyball")], *FIELDS) == []


def test_adjectival_city_names_are_russian():
    for t in ("Krasnoyarskie Rysi", "Omskie Krylia", "Omskie Yastreby", "Sputnik Almetievsk",
              "Neftyanik Almetyevsk"):
        assert russia_filter.is_russian(t), t


def _qualifying(home, away, league):
    """A grade A row that passes every TOP rule (as tests/test_top_picks_rules._match)."""
    return {"homeTeam": home, "awayTeam": away, "time": "18:00", "league": league, "country": "",
            "qualifies": True, "predictionGrade": "A", "scoring": {"pick": "1", "prob": 70},
            "forebet": {"prediction": "1", "homeProb": 70, "awayProb": 30},
            "odds": {"home": 2.1, "away": 3.0},
            "form": {"home": list("WWWWD"), "away": list("LLLDW"),
                     "homeAtHome": list("WWWDW"), "awayAtAway": list("LLDLL")},
            "h2h": {"total": 0}, "sofascore": {"found": False}}


def test_top_collect_skips_a_qualifying_ru4_hockey_row(tmp_path, monkeypatch):
    from tools import top_picks as tp
    from tools import top_rules
    day = "2026-10-29"
    res = tmp_path / "results"
    res.mkdir()
    rows = [_qualifying("Irbis", "Chaika", "RU4"), _qualifying("Graz99ers", "Klagenfurt", "ICE")]
    (res / f"matches_{day}_hockey_forebet.json").write_text(
        json.dumps({"matches": rows}), encoding="utf-8")
    monkeypatch.setattr(tp, "ROOT", str(tmp_path))
    monkeypatch.setattr(tp, "RULES", top_rules.fallback("test"))     # safe gate: hockey in
    assert [r["match"] for r in tp.collect(day)] == ["Graz99ers vs Klagenfurt"]
    monkeypatch.setenv("SKIP_RUSSIA", "0")
    assert len(tp.collect(day)) == 2                 # the row itself qualifies


def test_fan_favourites_board_skips_russian_code_rows(tmp_path):
    from datetime import datetime, timezone
    from tools import fan_favourites as ff
    day = "2026-10-30"
    res = tmp_path / "results"
    res.mkdir()
    vote = {"found": True, "homeProb": 80, "awayProb": 20, "votes": 500, "url": "u"}
    rows = [dict(_row("RU2"), time="19:00", sofascore=vote,
                 odds={"home": 2.2, "draw": 4.0, "away": 3.1}),
            dict(_row("ICE", "Graz99ers", "Klagenfurt"), time="19:00", sofascore=vote,
                 odds={"home": 2.2, "draw": 4.0, "away": 3.1})]
    (res / f"matches_{day}_hockey_forebet.json").write_text(
        json.dumps({"matches": rows}), encoding="utf-8")
    blk = ff.build("hockey", day, str(res), use_best_price=False,
                   now=datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc), log=lambda *_: None)
    assert [p["home"] for p in blk["picks"]] == ["Graz99ers"] and blk["stats"]["rows"] == 1


def test_weekend_pool_skips_russian_legs(tmp_path):
    from datetime import datetime, timezone
    from tools import weekend_slip as ws
    fri = "2026-10-30"
    res = tmp_path / "results"
    res.mkdir()
    pick = {"sport": "hockey", "date": fri, "kickoff": f"{fri}T18:00:00Z", "side": "home",
            "fanPct": 80, "status": "pick", "bestPrice": {"price": 2.2, "bookmaker": "pinnacle"},
            "modelProb": 0.6, "availability": {"verdict": "ok"}, "grade": "B"}
    picks = [dict(pick, id=f"hockey|{fri}|Irbis|Chaika", league="RU4", home="Irbis",
                  away="Chaika", team="Irbis"),
             dict(pick, id=f"hockey|{fri}|Graz99ers|Klagenfurt", league="ICE", home="Graz99ers",
                  away="Klagenfurt", team="Graz99ers")]
    (res / f"fanvote_{fri}.json").write_text(
        json.dumps({"sports": {"hockey": {"picks": picks}}}), encoding="utf-8")
    pool = ws.leg_pool([fri], str(res), datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc))
    assert [l["match"] for l in pool] == ["Graz99ers vs Klagenfurt"]


def test_ai_analyst_skips_russian_team_sport_candidates():
    from tools import ai_analyst as aa
    top = [{"sport": "hockey", "match": "Irbis vs Chaika", "league": "RU4", "pick": "Irbis"},
           {"sport": "hockey", "match": "Graz99ers vs Klagenfurt", "league": "ICE",
            "pick": "Graz99ers"},
           {"sport": "tennis", "match": "A. Rublev vs J. Sinner", "league": "RU1",
            "pick": "A. Rublev"}]
    out = aa.build_candidates("2001-01-01", top, [])     # no day files: raw data empty
    assert [c["match"] for c in out] == ["Graz99ers vs Klagenfurt", "A. Rublev vs J. Sinner"]
