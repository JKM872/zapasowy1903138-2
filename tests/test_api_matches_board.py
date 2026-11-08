import json
import os
import sys
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import api_server  # noqa: E402

DAY = datetime.now().strftime('%Y-%m-%d')


def _row(h, a, t, odds=None, qual=False, **kw):
    r = {'home_team': h, 'away_team': a, 'time': t, 'qualifies': qual}
    if odds:
        r['home_odds'], r['away_odds'] = odds
    r.update(kw)
    return r


@pytest.fixture
def client(tmp_path, monkeypatch):
    rows = [
        _row('A', 'B', '10:00'),
        _row('C', 'D', '11:00', odds=(1.8, 2.1)),
        _row('E', 'F', '12:00', odds=(1.5, 2.5), qual=True),
        _row('G', 'H', '09:00', sofascore_url='https://www.sofascore.com/football/match/123'),
        _row('G', 'H', '09:00', odds=(1.9, 2.0), forebet_prediction='1', forebet_probability=60),
    ]
    (tmp_path / f'matches_{DAY}_football.json').write_text(json.dumps(rows), encoding='utf-8')
    monkeypatch.setattr(api_server, 'RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(api_server, 'SUPABASE_AVAILABLE', False)
    monkeypatch.setattr(api_server, 'resolve_logos_for_page', lambda *_a, **_k: None)
    monkeypatch.setattr(api_server, '_apply_availability', lambda *_a, **_k: None)
    api_server._match_index_cache.update(sig=None, ids={})
    api_server.app.config['TESTING'] = True
    return api_server.app.test_client()


def test_board_sort_puts_qualifying_then_odds_first(client):
    data = client.get(f'/api/matches?date={DAY}&sort=board').get_json()['data']
    homes = [m['homeTeam'] for m in data]
    quals = [m['qualifies'] for m in data]
    assert quals == sorted(quals, reverse=True)
    assert homes.index('A') == len(homes) - 1


def test_default_order_unchanged(client):
    homes = [m['homeTeam'] for m in client.get(f'/api/matches?date={DAY}').get_json()['data']]
    assert homes == ['G', 'A', 'C', 'E']


def test_per_page_capped(client):
    assert client.get(f'/api/matches?date={DAY}&per_page=10000').get_json()['meta']['per_page'] == 500


def test_dedup_carries_event_id(client):
    data = client.get(f'/api/matches?date={DAY}').get_json()['data']
    g = [m for m in data if m['homeTeam'] == 'G']
    assert len(g) == 1
    assert g[0]['sofascoreEventId'] == 123


def test_unknown_match_id_404_without_file_read(client, monkeypatch):
    assert client.get('/api/matches/nope').status_code == 404
    calls = []
    orig = api_server.load_matches_from_file
    monkeypatch.setattr(api_server, 'load_matches_from_file', lambda p: calls.append(p) or orig(p))
    assert client.get('/api/matches/nope').status_code == 404
    assert calls == []
