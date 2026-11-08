import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import api_server  # noqa: E402


@pytest.fixture
def client():
    api_server.app.config['TESTING'] = True
    return api_server.app.test_client()


def _acao(client, origin):
    return client.get('/api/health', headers={'Origin': origin}).headers.get('Access-Control-Allow-Origin')


@pytest.mark.parametrize('origin', [
    'https://pickly-dashboard.vercel.app.evil.example',
    'https://pickly-dashboardXvercelXapp.evil.example',
])
def test_lookalike_origins_rejected(client, origin):
    assert _acao(client, origin) is None


@pytest.mark.parametrize('origin', [
    'https://pickly-dashboard.vercel.app',
    'https://pickly-dashboard-git-main-jkm872.vercel.app',
])
def test_real_origins_allowed(client, origin):
    assert _acao(client, origin) == origin
