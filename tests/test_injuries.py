"""Absencje SofaScore (missingPlayers z /event/{id}/lineups) — bez sieci."""
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sofascore_scraper as ss  # noqa: E402
from tools import injuries  # noqa: E402


def _pl(name, value=None, pos='D'):
    p = {'name': name, 'shortName': name, 'position': pos, 'id': hash(name) % 10**6}
    if value is not None:
        p['proposedMarketValueRaw'] = {'value': value, 'currency': 'EUR'}
    return p


# Kształt jak w realnej odpowiedzi (PL, 10.2026), przycięty.
LINEUPS = {
    'confirmed': False,
    'home': {
        'players': [{'player': _pl(f'H{i}', v)} for i, v in enumerate((1e6, 5e6, 10e6, 20e6, 30e6))],
        'missingPlayers': [
            {'player': _pl('J. Rodon', 18800000), 'type': 'missing', 'reason': 1,
             'description': 'Hamstring Injury', 'externalType': 5},
            {'player': _pl('M. Joseph', 3700000, 'F'), 'type': 'missing', 'reason': 1,
             'description': 'Knee Injury', 'externalType': 5},
            {'player': _pl('X. Red', 25000000), 'type': 'missing', 'reason': 13,
             'description': 'red_card_suspension'},
        ]},
    'away': {
        'players': [],
        'missingPlayers': [
            {'player': _pl('T. Prince', pos='F'), 'type': 'doubtful', 'reason': 1,
             'description': 'Knock Injury'},
            {'player': _pl('C. Coach'), 'type': 'missing', 'reason': 4,
             'description': 'coach_decision'},
        ]},
}


@pytest.fixture(autouse=True)
def _clean():
    ss._missing_cache.clear()
    injuries._cache.clear()
    injuries.events.clear()
    yield
    ss._missing_cache.clear()
    injuries._cache.clear()
    injuries.events.clear()


def test_get_missing_players_parses_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(ss, '_api_get_json', lambda url, timeout=10: calls.append(url) or LINEUPS)
    r = ss.get_missing_players(123)
    assert r['available'] is True
    assert [p['reason'] for p in r['home']] == ['kontuzja', 'kontuzja', 'zawieszenie']
    assert [p['key'] for p in r['home']] == [True, False, True]   # mediana 10M
    assert [p['reason'] for p in r['away']] == ['wątpliwy', 'inne']
    assert r['away'][0]['key'] is None                             # brak wartości
    ss.get_missing_players(123)
    assert len(calls) == 1 and calls[0].endswith('/event/123/lineups')


def test_get_missing_players_failure(monkeypatch):
    def boom(url, timeout=10):
        raise RuntimeError('net')
    monkeypatch.setattr(ss, '_api_get_json', boom)
    assert ss.get_missing_players(5) == {'home': [], 'away': [], 'available': False}
    monkeypatch.setattr(ss, '_api_get_json', lambda url, timeout=10: None)
    assert ss.get_missing_players(6)['available'] is False


def _match():
    return {'homeTeam': 'Leeds', 'awayTeam': 'Wolves', 'scoring': {'pick': '1'}}


def test_attach_risk_and_exclusion(monkeypatch):
    monkeypatch.setattr(ss, '_api_get_json', lambda url, timeout=10: LINEUPS)
    injuries.remember_event('football', 'Leeds', 'Wolves', 123, 'direct')
    m = _match()
    injuries.attach(m, 'football', '2026-10-21', 'home')
    assert m['injuryCounts'] == {'home': 3, 'away': 1}             # doubtful nie liczony
    assert m['injury_risk'] is True                                # 2 kluczowych braków
    assert injuries.excludes(m, 'home') is True                    # rywal ma mniej
    line = injuries.fields(m)['injuryLine']
    assert line.startswith('🩺 Absencje: Leeds: J. Rodon* (kontuzja)')
    assert 'Wolves: T. Prince (wątpliwy)' in line


def test_reversed_event_swaps_sides(monkeypatch):
    monkeypatch.setattr(ss, '_api_get_json', lambda url, timeout=10: LINEUPS)
    injuries.remember_event('football', 'Leeds', 'Wolves', 123, 'reversed')
    m = _match()
    injuries.attach(m, 'football', '2026-10-21', 'home')
    assert m['injuryCounts'] == {'home': 1, 'away': 3}
    assert m['injury_risk'] is False and not injuries.excludes(m, 'home')


def test_no_key_info_uses_count_threshold():
    rows = [{'type': 'missing', 'key': None}] * 2
    assert injuries.side_risk({'home': rows}, 'home') is False
    assert injuries.side_risk({'home': rows * 2}, 'home') is True
    m = {'injury_risk': True, 'injuryCounts': {'home': 3, 'away': 3}}
    assert injuries.excludes(m, 'home') is False                   # rywal tak samo osłabiony


def test_unverified_event_gives_nothing(monkeypatch):
    import forebet_pipeline
    monkeypatch.setattr(ss, 'search_event_via_api', lambda *a, **k: 999)
    monkeypatch.setattr(forebet_pipeline, '_verify_sofascore_event', lambda *a, **k: None)
    monkeypatch.setattr(ss, '_api_get_json', lambda url, timeout=10: pytest.fail('no fetch'))
    m = _match()
    injuries.attach(m, 'football', '2026-10-21', 'home')
    assert 'injuries' not in m and injuries.fields(m) == {}


def test_network_error_never_breaks(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError('x')
    monkeypatch.setattr(ss, 'search_event_via_api', boom)
    m = _match()
    from tools.top_picks import enrich_injuries
    enrich_injuries(m, 'football', '2026-10-21')
    assert 'injuries' not in m


def test_unsupported_sport_skipped(monkeypatch):
    monkeypatch.setattr(ss, 'search_event_via_api', lambda *a, **k: pytest.fail('no call'))
    m = _match()
    injuries.attach(m, 'volleyball', '2026-10-21', 'home')
    assert 'injuries' not in m


URL = 'https://www.sofascore.com/football/match/16550656'


def _verified(orientation='direct'):
    """Wiersz Forebet z Fan Vote (kształt z results/matches_*_forebet.json)."""
    return {**_match(), 'sofascore': {'found': orientation in ('direct', 'reversed'), 'votes': 900,
                                      'url': URL, 'orientation': orientation}}


def test_event_from_row_needs_a_verified_orientation():
    assert injuries.event_from_row(_verified()) == (16550656, 'direct')
    assert injuries.event_from_row(_verified('reversed')) == (16550656, 'reversed')
    assert injuries.event_from_row({'sofascoreEventId': '42', 'sofascore': {'orientation': 'reversed'}}) == (42, 'reversed')
    assert injuries.event_from_row({'sofascore': {'eventId': 43, 'orientation': 'direct'}}) == (43, 'direct')
    for orientation in ('mismatch', 'unknown', None):
        assert injuries.event_from_row(_verified(orientation)) is None
    assert injuries.event_from_row({'sofascore': None}) is None
    assert injuries.event_from_row({'sofascore': {'orientation': 'direct', 'url': 'https://www.sofascore.com/'}}) is None


def test_verified_row_never_searches_by_name(monkeypatch):
    monkeypatch.setattr(ss, 'search_event_via_api', lambda *a, **k: pytest.fail('name search'))
    urls = []
    monkeypatch.setattr(ss, '_api_get_json', lambda url, timeout=10: urls.append(url) or LINEUPS)
    m = _verified()
    injuries.attach(m, 'football', '2026-10-21', 'home')
    assert len(urls) == 1 and urls[0].endswith('/event/16550656/lineups')
    assert m['injuryCounts'] == {'home': 3, 'away': 1} and m['injury_risk'] is True
    r = {'homeTeam': 'Brest', 'awayTeam': 'Lens', 'sofascoreEventId': 777,
         'sofascore': {'found': True, 'orientation': 'reversed'}}
    injuries.attach(r, 'football', '2026-10-21', 'home')
    assert urls[-1].endswith('/event/777/lineups')
    assert r['injuryCounts'] == {'home': 1, 'away': 3}         # strony SofaScore odwrócone


def test_mismatch_row_falls_back_to_name_search(monkeypatch):
    fake = types.ModuleType('forebet_pipeline')               # bez distutils lokalnie
    fake._verify_sofascore_event = lambda eid, home, away, date_str=None: 'direct'
    monkeypatch.setitem(sys.modules, 'forebet_pipeline', fake)
    searched = []
    monkeypatch.setattr(ss, 'search_event_via_api', lambda h, a, **k: searched.append((h, a)) or 555)
    urls = []
    monkeypatch.setattr(ss, '_api_get_json', lambda url, timeout=10: urls.append(url) or LINEUPS)
    m = _verified('mismatch')                                  # url = INNY mecz
    injuries.attach(m, 'football', '2026-10-21', 'home')
    assert searched == [('Leeds', 'Wolves')]
    assert len(urls) == 1 and urls[0].endswith('/event/555/lineups')
    assert m['injuryCounts'] == {'home': 3, 'away': 1}
