import json

import pytest

from tools import web_search as ws
from tools import availability_agent as aa

TAVILY = {'results': [{'url': 'https://a.com/news', 'title': 'Team news', 'content': 'Kane out with ankle'},
                      {'url': 'ftp://bad', 'title': 'x', 'content': 'y'}]}
BRAVE = {'web': {'results': [{'url': 'https://b.com/x', 'title': 'Injuries', 'description': 'Saka doubtful',
                              'extra_snippets': ['hamstring']}, {'title': 'no url'}]}}


def test_parse_tavily():
    r = ws.parse_tavily(TAVILY)
    assert r == [{'url': 'https://a.com/news', 'title': 'Team news', 'snippet': 'Kane out with ankle'}]
    assert ws.parse_tavily({}) == []


def test_parse_brave():
    r = ws.parse_brave(BRAVE)
    assert len(r) == 1 and r[0]['url'] == 'https://b.com/x' and 'hamstring' in r[0]['snippet']
    assert ws.parse_brave({'web': None}) == []


@pytest.fixture
def tmp_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, 'ROOT', str(tmp_path))
    monkeypatch.setattr(ws, '_DEAD', set())
    monkeypatch.setattr(ws, 'STATS', {})
    monkeypatch.setenv('TAVILY_API_KEYS', 'tk1,tk2')
    monkeypatch.setenv('BRAVE_API_KEYS', 'bk1')
    return tmp_path


def test_daily_allowance_and_tiers(tmp_usage):
    u = ws.load_usage('2026-11')
    # 2 keys * 950 over 11 days left (20..30 Nov)
    assert ws.daily_allowance(u, 'tavily', ['a', 'b'], '2026-11-20') == 1900 // 11
    u['days'] = {'2026-11-20': {'tavily': 110}}
    assert ws.allowed(u, 'tavily', ['a', 'b'], '2026-11-20', 'top')
    assert not ws.allowed(u, 'tavily', ['a', 'b'], '2026-11-20', 'ab')   # A/B only gets 60%


def test_key_cap_and_charge(tmp_usage):
    u = ws.load_usage('2026-11')
    ws.charge(u, 'tavily', 'tk1', '2026-11-20')
    assert ws.key_left(u, 'tavily', 'tk1') == ws.key_cap('tavily') - 1
    assert 'tk1' not in json.dumps(u)   # only hashes are persisted


def test_search_rotates_dead_keys_falls_back_and_caches(tmp_usage):
    calls = []

    def fake(provider, key, q):
        calls.append((provider, key))
        if provider == 'tavily':
            return (432 if key == 'tk1' else 429), []
        return 200, ws.parse_brave(BRAVE)
    res, prov = ws.search('football|a|b', 'football', 'A', 'B', '2026-11-20', 'top', call=fake)
    assert prov == 'brave' and res[0]['url'] == 'https://b.com/x'
    assert calls == [('tavily', 'tk1'), ('tavily', 'tk2'), ('brave', 'bk1')]
    res2, prov2 = ws.search('football|a|b', 'football', 'A', 'B', '2026-11-20', 'top', call=fake)
    assert prov2 == 'brave' and len(calls) == 3        # cache hit, no new call
    s = ws.month_summary('2026-11-20')
    assert s['brave']['used'] == 1 and s['tavily']['used'] == 0


def test_search_exhausted_key_skipped(tmp_usage):
    u = ws.load_usage('2026-11')
    u['used'] = {'tavily': {ws.kid('tk1'): ws.key_cap('tavily'), ws.kid('tk2'): ws.key_cap('tavily')}}
    ws.save_usage(u)
    seen = []
    res, prov = ws.search('k', 'tennis', 'A', 'B', '2026-11-20', 'top',
                          call=lambda p, k, q: (seen.append(p), (200, ws.parse_tavily(TAVILY)))[1])
    assert seen == ['brave'] and prov == 'brave'


def test_parse_search_llm_sourced_only():
    urls = ['https://a.com/news']
    txt = json.dumps({'home': [{'name': 'Kane', 'importance': 'star', 'status': 'out', 'url': 'https://a.com/news'},
                               {'name': 'Ghost', 'importance': 'star', 'status': 'out', 'url': 'https://made.up'}],
                      'away': [], 'confidence': 'high'})
    r = aa.parse_search_llm(txt, urls)
    assert [p['name'] for p in r['home']] == ['Kane'] and r['sources'] == urls and r['source'] == 'search'
    # nothing sourced -> None (stays unknown, never blocks)
    assert aa.parse_search_llm(json.dumps({'home': [], 'away': []}), urls) is None
    low = json.dumps({'home': [{'name': 'Kane', 'importance': 'star', 'status': 'out', 'url': urls[0]}],
                      'away': [], 'confidence': 'low'})
    assert aa.parse_search_llm(low, urls)['home'][0]['status'] == 'doubtful'
