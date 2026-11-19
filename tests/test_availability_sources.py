import os

import pytest

from tools import availability_sources as src

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'avail')


def _read(name):
    return open(os.path.join(FIX, name), encoding='utf-8').read()


def test_rotowire_nba_starters_play_and_injury_tags_map_to_out_or_doubtful():
    d = src.parse_rotowire(_read('rotowire_nba.html'), 'rotowire')
    assert set(d) == {'trail blazers', 'bucks'}
    por = {r['name']: r for r in d['trail blazers']}
    assert por['Damian Lillard']['status'] == 'plays'
    assert por['Toumani Camara']['status'] == 'doubtful'
    assert por['Ja Morant']['status'] == 'out'
    assert all(r['source'] == 'rotowire' for r in d['bucks'])


def test_rotowire_nhl_goalie_and_injuries():
    d = src.parse_rotowire(_read('rotowire_nhl.html'), 'rotowire')
    fly = {r['name']: r for r in d['flyers']}
    assert fly['Joseph Woll']['reason'].startswith('starting goalie')
    assert fly['Nikita Grebenkin']['status'] == 'out'


def test_dailyfaceoff_goalies():
    d = src.parse_dailyfaceoff(_read('dailyfaceoff.html'))
    assert d['ottawa senators'][0]['name'] == 'Samuel Ersson'
    assert d['ottawa senators'][0]['status'] == 'plays'


def test_transfermarkt_injuries():
    d = src.parse_transfermarkt(_read('transfermarkt_gb1.html'))
    assert d['nottingham forest'][0] == {'name': 'Xaver Schlager', 'status': 'out', 'reason': 'Hamstring injury',
                                         'source': 'transfermarkt', 'url': ''}
    assert 'aston villa' in d


def test_team_matching_is_strict():
    table = {'thunder': [], 'manchester united': [], 'manchester city': []}
    assert src.match_team('Oklahoma City Thunder', table) == 'thunder'
    assert src.match_team('Manchester United', table) == 'manchester united'
    assert src.match_team('Manchester', table) is None        # ambiguous
    assert src.match_team('Leeds', table) is None


def test_registry_routes_by_sport_and_league_and_skips_disabled():
    assert src.sources_for('basketball', 'NBA') == ['sofascore', 'rotowire_nba']   # official report disabled
    assert src.sources_for('basketball', 'EUR') == ['sofascore']                      # RotoWire EL 404
    assert src.sources_for('hockey', 'NHL') == ['sofascore', 'rotowire_nhl', 'dailyfaceoff_goalies']
    assert src.sources_for('football', 'Premier League', 'England') == ['sofascore', 'transfermarkt_gb1']
    assert src.sources_for('football', 'Premier League', 'Ghana') == ['sofascore']
    assert src.sources_for('volleyball', 'PL1') == ['sofascore']
    reg = src.registry()
    for name, meta in reg['sources'].items():
        assert 'enabled' in meta and 'provides' in meta and 'timeout' in meta, name
        if meta['enabled']:
            assert meta['fetcher'] in src.FETCHERS and meta['timeout'] <= 10, name


@pytest.fixture
def offline(monkeypatch, tmp_path):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr(requests, 'get', boom)
    monkeypatch.setattr(src, 'CACHE_DIR', str(tmp_path))
    src._robots.clear()
    src._parsed.clear()
    yield
    src._robots.clear()
    src._parsed.clear()


def test_every_fetcher_returns_empty_dict_offline(offline):
    assert src.rotowire_nba('2026-11-19') == {}
    assert src.rotowire_nhl('2026-11-19') == {}
    assert src.dailyfaceoff_goalies('2026-11-19') == {}
    assert src.transfermarkt_injuries('GB1', '2026-11-19') == {}
    res = src.rows_for_match('basketball', 'NBA', 'USA', 'Portland Trail Blazers', 'Milwaukee Bucks', '2026-11-19')
    assert res == {'home': [], 'away': [], 'sources': []}


def test_robots_disallow_skips_fetch(monkeypatch, tmp_path):
    import requests
    calls = []

    class R:
        status_code, text = 200, 'User-agent: *\nDisallow: /'
    monkeypatch.setattr(requests, 'get', lambda url, **k: calls.append(url) or R())
    monkeypatch.setattr(src, 'CACHE_DIR', str(tmp_path))
    src._robots.clear()
    assert src.fetch_page('x', 'https://example.org/page', 10, '2026-11-19') is None
    assert calls == ['https://example.org/robots.txt']
    src._robots.clear()


def test_rows_for_match_uses_cached_page(monkeypatch, tmp_path):
    import shutil
    monkeypatch.setattr(src, 'CACHE_DIR', str(tmp_path))
    shutil.copy(os.path.join(FIX, 'rotowire_nba.html'), tmp_path / 'avail_src_rotowire_nba_2026-11-19.html')
    src._parsed.clear()
    res = src.rows_for_match('basketball', 'NBA', '', 'Milwaukee Bucks', 'Portland Trail Blazers', '2026-11-19')
    assert res['sources'] == ['rotowire_nba']
    assert any(r['name'] == 'Ja Morant' and r['status'] == 'out' for r in res['away'])
    src._parsed.clear()
