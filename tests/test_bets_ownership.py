"""Bets belong to their owner: no unfiltered listing, no cross-user edits."""
import os
import sys

import jwt
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import api_server  # noqa: E402
import auth_middleware  # noqa: E402
from supabase_manager import SupabaseManager  # noqa: E402

SECRET = 'test-secret'


class _Resp:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, store, log, op='select', payload=None):
        self.store, self.log, self.op, self.payload = store, log, op, payload
        self.filters = []

    def select(self, *_a):
        return self

    def update(self, payload):
        self.op, self.payload = 'update', payload
        return self

    def delete(self):
        self.op = 'delete'
        return self

    def eq(self, k, v):
        self.log.append(('eq', k, v))
        self.filters.append((k, v))
        return self

    def gte(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        rows = [r for r in self.store if all(r.get(k) == v for k, v in self.filters)]
        if self.op == 'update':
            self.log.append(('update', self.payload))
            for r in rows:
                r.update(self.payload)
        elif self.op == 'delete':
            self.log.append(('delete',))
            for r in rows:
                self.store.remove(r)
        return _Resp([dict(r) for r in rows])


class FakeClient:
    def __init__(self, store):
        self.store, self.log = store, []

    def table(self, _name):
        return FakeQuery(self.store, self.log)


@pytest.fixture
def mgr(monkeypatch):
    store = [
        {'id': 1, 'user_id': 'A', 'status': 'won', 'stake': 10, 'profit': 10,
         'bet_selection': '1', 'odds_at_bet': 2.0},
        {'id': 2, 'user_id': 'B', 'status': 'lost', 'stake': 10, 'profit': -10,
         'bet_selection': '2', 'odds_at_bet': 3.0},
    ]
    m = SupabaseManager.__new__(SupabaseManager)
    m.client = FakeClient(store)
    monkeypatch.setattr(api_server, 'supabase', m)
    monkeypatch.setattr(api_server, 'SUPABASE_AVAILABLE', True)
    return m


@pytest.fixture
def client():
    api_server.app.config['TESTING'] = True
    return api_server.app.test_client()


def _auth(monkeypatch, user):
    monkeypatch.setattr(auth_middleware, 'SUPABASE_JWT_SECRET', SECRET)
    tok = jwt.encode({'sub': user, 'aud': 'authenticated'}, SECRET, algorithm='HS256')
    return {'Authorization': f'Bearer {tok}'}


def test_anonymous_list_is_empty_in_local_mode(client, mgr, monkeypatch):
    monkeypatch.setattr(auth_middleware, 'SUPABASE_JWT_SECRET', '')
    monkeypatch.setattr(auth_middleware, 'auth_is_configured', lambda: False)
    monkeypatch.setattr(auth_middleware, '_is_deployed', lambda: False)
    resp = client.get('/api/bets')
    assert resp.status_code == 200
    assert resp.get_json()['bets'] == []
    assert mgr.client.log == []


def test_list_requires_token_when_auth_configured(client, mgr, monkeypatch):
    monkeypatch.setattr(auth_middleware, 'SUPABASE_JWT_SECRET', SECRET)
    assert client.get('/api/bets').status_code == 401
    assert client.get('/api/bets/stats').status_code == 401


def test_list_is_filtered_by_user(client, mgr, monkeypatch):
    bets = client.get('/api/bets', headers=_auth(monkeypatch, 'A')).get_json()['bets']
    assert [b['id'] for b in bets] == [1]


def test_user_b_cannot_update_user_a_bet(client, mgr, monkeypatch):
    resp = client.put('/api/bets/1', headers=_auth(monkeypatch, 'B'),
                      json={'actual_result': '2', 'home_score': 0, 'away_score': 1})
    assert resp.status_code == 404
    assert not any(e[0] == 'update' for e in mgr.client.log)
    assert mgr.client.store[0]['status'] == 'won'


def test_user_b_cannot_delete_user_a_bet(client, mgr, monkeypatch):
    resp = client.delete('/api/bets/1', headers=_auth(monkeypatch, 'B'))
    assert resp.status_code == 404
    assert any(r['id'] == 1 for r in mgr.client.store)


def test_owner_can_delete(client, mgr, monkeypatch):
    resp = client.delete('/api/bets/1', headers=_auth(monkeypatch, 'A'))
    assert resp.status_code == 200
    assert not any(r['id'] == 1 for r in mgr.client.store)


def test_stats_filtered_by_user(client, mgr, monkeypatch):
    stats = client.get('/api/bets/stats', headers=_auth(monkeypatch, 'B')).get_json()
    assert stats['total_bets'] == 1
    assert stats['lost_bets'] == 1
    assert ('eq', 'user_id', 'B') in mgr.client.log
