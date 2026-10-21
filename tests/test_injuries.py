"""Absencje SofaScore (missingPlayers z /event/{id}/lineups) — bez sieci."""
import os
import sys

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
