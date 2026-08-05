"""Comment and preference endpoints.

Comments are user-generated content on a paid product, so the guards matter more
than the happy path: an author can only speak as themselves, only delete their
own, cannot post an empty or oversized body, and cannot flood. A failed rate
check refuses rather than waves the request through — a broken guard must not
become an open door.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_server


class FakeSupabase:
    """Records calls so ownership and limits can be asserted."""

    def __init__(self):
        self.comments = []
        self.prefs = {}
        self.recent = 0
        self.next_id = 1
        self.deleted = []

    # ── comments ──
    def get_match_comments(self, match_key, limit=100):
        return [c for c in self.comments if c['match_key'] == str(match_key)]

    def count_recent_comments(self, user_id, seconds=60):
        return self.recent

    def add_match_comment(self, match_key, user_id, body, author_label=''):
        row = {
            'id': self.next_id, 'match_key': str(match_key), 'user_id': user_id,
            'author_label': author_label or None, 'body': body,
            'created_at': '2026-08-05T12:00:00+00:00',
        }
        self.next_id += 1
        self.comments.append(row)
        return row

    def delete_match_comment(self, comment_id, user_id):
        self.deleted.append((comment_id, user_id))
        before = len(self.comments)
        self.comments = [c for c in self.comments
                         if not (c['id'] == comment_id and c['user_id'] == user_id)]
        return len(self.comments) < before

    # ── preferences ──
    def get_user_preferences(self, user_id):
        return self.prefs.get(user_id)

    def upsert_user_preferences(self, user_id, sports, leagues, onboarded=True):
        self.prefs[user_id] = {'user_id': user_id, 'sports': sports,
                               'leagues': leagues, 'onboarded': onboarded}
        return True


@pytest.fixture
def fake(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(api_server, 'supabase', fake)
    monkeypatch.setattr(api_server, 'SUPABASE_AVAILABLE', True)
    return fake


@pytest.fixture
def client(monkeypatch):
    api_server.app.config['TESTING'] = True
    return api_server.app.test_client()


def as_user(monkeypatch, user_id):
    """Make the auth decorators see a specific signed-in reader."""
    import auth_middleware

    def _require(fn):
        import functools
        from flask import request

        @functools.wraps(fn)
        def wrapper(*a, **k):
            request.user_id = user_id
            return fn(*a, **k)
        return wrapper

    # Routes captured the decorator at import time, so patch the view functions.
    for name, view in list(api_server.app.view_functions.items()):
        if name in ('add_match_comment', 'delete_match_comment',
                    'get_preferences', 'put_preferences', 'get_match_comments'):
            api_server.app.view_functions[name] = _require(
                getattr(view, '__wrapped__', view))
    return auth_middleware


class TestReadingComments:
    def test_comments_are_returned_for_a_match(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        fake.add_match_comment('m1', 'user-1', 'Rozgrywający nie zagra')

        resp = client.get('/api/matches/m1/comments')
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body['comments']) == 1
        assert body['comments'][0]['body'] == 'Rozgrywający nie zagra'

    def test_the_author_id_is_never_exposed(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        fake.add_match_comment('m1', 'user-2', 'cokolwiek')

        comment = client.get('/api/matches/m1/comments').get_json()['comments'][0]
        assert 'user_id' not in comment
        assert comment['isMine'] is False

    def test_own_comments_are_flagged(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        fake.add_match_comment('m1', 'user-1', 'moje')
        comment = client.get('/api/matches/m1/comments').get_json()['comments'][0]
        assert comment['isMine'] is True

    def test_without_a_database_the_board_still_opens(self, client, monkeypatch):
        monkeypatch.setattr(api_server, 'SUPABASE_AVAILABLE', False)
        resp = client.get('/api/matches/m1/comments')
        assert resp.status_code == 200
        assert resp.get_json() == {'comments': [], 'available': False}


class TestPostingComments:
    def test_a_comment_is_stored(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        resp = client.post('/api/matches/m1/comments',
                           json={'body': 'Kontuzja w rozgrzewce'})
        assert resp.status_code == 201
        assert resp.get_json()['body'] == 'Kontuzja w rozgrzewce'
        assert fake.comments[0]['user_id'] == 'user-1'

    def test_an_empty_body_is_rejected(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        assert client.post('/api/matches/m1/comments',
                           json={'body': '   '}).status_code == 400

    def test_an_oversized_body_is_rejected(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        resp = client.post('/api/matches/m1/comments',
                           json={'body': 'x' * (api_server.COMMENT_MAX_LEN + 1)})
        assert resp.status_code == 400

    def test_flooding_is_refused(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        fake.recent = api_server.COMMENT_RATE_LIMIT
        resp = client.post('/api/matches/m1/comments', json={'body': 'spam'})
        assert resp.status_code == 429

    def test_an_unverifiable_limit_refuses_rather_than_allows(self, client, fake, monkeypatch):
        """A broken guard must not become an open door."""
        as_user(monkeypatch, 'user-1')
        fake.recent = -1
        resp = client.post('/api/matches/m1/comments', json={'body': 'cokolwiek'})
        assert resp.status_code == 503
        assert fake.comments == []


class TestDeletingComments:
    def test_an_author_deletes_their_own(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        row = fake.add_match_comment('m1', 'user-1', 'moje')
        assert client.delete(f'/api/comments/{row["id"]}').status_code == 200
        assert fake.comments == []

    def test_someone_elses_comment_cannot_be_deleted(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        row = fake.add_match_comment('m1', 'user-2', 'nie moje')
        resp = client.delete(f'/api/comments/{row["id"]}')
        assert resp.status_code == 404
        assert len(fake.comments) == 1, 'the comment must survive'

    def test_the_owner_is_part_of_the_query(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        row = fake.add_match_comment('m1', 'user-1', 'moje')
        client.delete(f'/api/comments/{row["id"]}')
        assert fake.deleted == [(row['id'], 'user-1')]


class TestPreferences:
    def test_a_new_reader_has_not_been_onboarded(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        body = client.get('/api/preferences').get_json()
        assert body['onboarded'] is False
        assert body['sports'] == []

    def test_answers_are_stored_and_read_back(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        saved = client.put('/api/preferences', json={
            'sports': ['football', 'tennis'],
            'leagues': ['Premier League'],
        })
        assert saved.status_code == 200

        body = client.get('/api/preferences').get_json()
        assert body['sports'] == ['football', 'tennis']
        assert body['leagues'] == ['Premier League']
        assert body['onboarded'] is True

    def test_malformed_payload_is_rejected(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        resp = client.put('/api/preferences',
                          json={'sports': 'football', 'leagues': []})
        assert resp.status_code == 400

    def test_preferences_are_per_reader(self, client, fake, monkeypatch):
        as_user(monkeypatch, 'user-1')
        client.put('/api/preferences', json={'sports': ['tennis'], 'leagues': []})
        as_user(monkeypatch, 'user-2')
        assert client.get('/api/preferences').get_json()['sports'] == []
