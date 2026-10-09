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
