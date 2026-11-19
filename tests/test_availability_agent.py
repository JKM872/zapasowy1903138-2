import pytest

from tools import availability_agent as av


def P(name, imp='star', status='out', reason='injury'):
    return {'name': name, 'importance': imp, 'status': status, 'reason': reason}


def test_two_stars_out_drops_from_ab_and_blocks_top():
    v = av.verdict(av.summarize([P('A'), P('B')]), av.summarize([]))
    assert v['board'] == 'drop' and v['top_block']
    assert av.apply_grade('A', v['board']) == 'C'
    assert av.apply_grade('B', v['board']) == 'C'


def test_one_star_out_downgrades_one_grade():
    v = av.verdict(av.summarize([P('A')]), av.summarize([]))
    assert v['board'] == 'downgrade' and v['top_block']
    assert av.apply_grade('A', 'downgrade') == 'B'
    assert av.apply_grade('B', 'downgrade') == 'C'


def test_equal_losses_on_both_sides_do_not_punish_the_favourite():
    v = av.verdict(av.summarize([P('A')]), av.summarize([P('X')]))
    assert v['board'] == 'ok' and not v['top_block']


def test_doubtful_star_blocks_top_only():
    v = av.verdict(av.summarize([P('A', status='doubtful')]), av.summarize([]))
    assert v['board'] == 'ok' and v['top_block']


def test_squad_players_do_not_matter():
    v = av.verdict(av.summarize([P('a', 'other'), P('b', 'other'), P('c', 'other')]), av.summarize([]))
    assert v['board'] == 'ok' and not v['top_block']


def test_two_key_starters_out_blocks_top_and_downgrades():
    v = av.verdict(av.summarize([P('a', 'key'), P('b', 'key')]), av.summarize([]))
    assert v['board'] == 'downgrade' and v['top_block']


def test_parse_lineups_marks_top_valued_missing_and_benched_stars():
    def pl(name, value, **kw):
        return {'player': {'name': name, 'proposedMarketValueRaw': {'value': value}}, **kw}
    data = {
        'confirmed': True,
        'home': {'players': [pl('Star1', 90), pl('Bench star', 80, substitute=True),
                             pl('Reg', 10), pl('Reg2', 9)],
                 'missingPlayers': [pl('Injured star', 100, type='missing', description='Knee')]},
        'away': {'players': [pl('Z', 5)], 'missingPlayers': []},
    }
    res = av.parse_lineups(data)
    names = {p['name']: p for p in res['home']}
    assert names['Injured star']['importance'] == 'star' and names['Injured star']['status'] == 'out'
    assert names['Bench star']['reason'].startswith('on the bench')
    assert 'Star1' not in names  # starting, so not absent
    v = av.verdict(av.summarize(res['home']), av.summarize(res['away']))
    assert v['board'] == 'drop'


def test_unsourced_llm_answer_is_ignored_and_low_confidence_is_only_doubtful():
    assert av.parse_llm('{"home":[{"name":"X","importance":"star"}],"away":[],"sources":[]}') is None
    r = av.parse_llm('{"home":[{"name":"X","importance":"star","status":"out"}],"away":[],'
                     '"sources":["https://example.com"],"confidence":"low"}')
    assert r['home'][0]['status'] == 'doubtful'


def test_note_lists_only_important_players_of_the_picked_side():
    rec = {'side': 'home', 'home': [P('Star', 'star', reason='knee'), P('Kid', 'other')],
           'away': [P('Opp', 'star')]}
    assert av.note(rec) == 'Key absences: Star* (knee)'


class _R:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, ''

    def json(self):
        return self._b


def test_gemini_429_pair_is_skipped_and_grounding_urls_are_sources(monkeypatch):
    import requests
    import groq_client
    calls = []
    ok = {'candidates': [{'content': {'parts': [{'text': '{"home":[],"away":[],"confidence":"high"}'}]},
                          'groundingMetadata': {'groundingChunks': [{'web': {'uri': 'https://news.example/x'}}]}}]}

    def post(url, **kw):
        calls.append(url)
        if 'm1' in url:
            return _R(429, {'error': {'message': 'Quota exceeded'}})
        return _R(200, ok)
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(groq_client, 'gemini_keys', lambda: ['k'])
    monkeypatch.setenv('AVAIL_GEMINI_MODELS', 'm1,m2')
    av._DEAD.clear(); av.ERRORS.clear()
    txt, urls = av._gemini_grounded('p')
    assert urls == ['https://news.example/x'] and av.ERRORS['m1'].startswith('429: Quota')
    av._gemini_grounded('p')
    assert sum('m1' in u for u in calls) == 1  # exhausted pair not retried
    assert av.parse_llm(txt, urls)['sources'] == ['https://news.example/x']


def test_all_keys_exhausted_turns_llm_off_and_unknown_never_blocks(monkeypatch, tmp_path):
    import requests
    import groq_client
    calls = []
    monkeypatch.setattr(requests, 'post', lambda url, **kw: calls.append(url) or _R(429, {}))
    monkeypatch.setattr(groq_client, 'gemini_keys', lambda: ['k1', 'k2'])
    monkeypatch.setenv('AVAIL_GEMINI_MODELS', 'm1')
    av._DEAD.clear(); av.STATS.clear()
    for _ in range(3):
        assert av._gemini_grounded('p') == (None, [])
    assert len(calls) == 2 and av.STATS['llm_off_quota'] == 2
    rec = {'unknown': True, 'board': 'ok', 'top_block': False}
    assert av.apply_grade('A', rec['board']) == 'A' and not rec['top_block']


def test_groq_compound_search_urls_are_sources_and_429_rotates_keys(monkeypatch):
    import requests
    import groq_client
    body = {'choices': [{'message': {
        'content': '{"home":[{"name":"S","importance":"star","status":"out"}],"away":[],"confidence":"high"}',
        'executed_tools': [{'type': 'search', 'search_results': {'results': [
            {'title': 't', 'url': 'https://news.example/inj'}]}}]}}]}
    seen = []

    def post(url, headers=None, **kw):
        seen.append(headers['Authorization'])
        return _R(429, {'error': {'message': 'rate'}}) if 'k1' in headers['Authorization'] else _R(200, body)
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(groq_client, 'api_keys', lambda: ['k1', 'k2'])
    monkeypatch.setenv('AVAIL_GROQ_MODELS', 'groq/compound')
    av._DEAD.clear(); av.ERRORS.clear()
    txt, urls = av._groq_compound('p')
    assert seen == ['Bearer k1', 'Bearer k2'] and urls == ['https://news.example/inj']
    assert av.parse_llm(txt, urls)['home'][0]['status'] == 'out'
    # no search results -> unsourced -> ignored
    assert av.parse_llm(txt, av.compound_urls({'executed_tools': []})) is None


def test_mismatch_row_url_is_ignored_and_verified_row_uses_its_event(monkeypatch):
    import sofascore_scraper as ss
    from tools import injuries
    url = 'https://www.sofascore.com/football/match/16550656'
    bad = {'homeTeam': 'Leeds', 'awayTeam': 'Wolves',
           'sofascore': {'found': False, 'url': url, 'orientation': 'mismatch'}}   # url of another game
    assert av._event_id(bad) is None
    assert av._event_id({**bad, 'sofascore': {'url': url, 'orientation': None}}) is None
    resolved = []
    monkeypatch.setattr(injuries, '_resolve', lambda *a: resolved.append(a) or None)
    monkeypatch.setattr(ss, '_api_get_json', lambda *a, **k: pytest.fail('line-ups of the wrong event'))
    assert av.sofascore_check(bad, 'football', '2026-10-31') is None
    assert resolved == [('football', 'Leeds', 'Wolves', '2026-10-31')]   # name search + verification

    good = {**bad, 'sofascore': {'found': True, 'url': url, 'orientation': 'reversed'}}
    assert av._event_id(good) == 16550656
    lineups = {'confirmed': False, 'away': {'players': [], 'missingPlayers': []},
               'home': {'players': [], 'missingPlayers': [
                   {'player': {'name': 'Star', 'proposedMarketValueRaw': {'value': 9e6}},
                    'type': 'missing', 'description': 'Knee'}]}}
    seen = []
    monkeypatch.setattr(ss, '_api_get_json', lambda u, timeout=10: seen.append(u) or lineups)
    res = av.sofascore_check(good, 'football', '2026-10-31')
    assert seen == ['https://api.sofascore.com/api/v1/event/16550656/lineups'] and len(resolved) == 1
    assert [p['name'] for p in res['away']] == ['Star'] and res['home'] == []   # sides swapped


from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def _rec(source=None, hours_ago=1, **kw):
    return {'checkedAt': (NOW - timedelta(hours=hours_ago)).isoformat(), 'source': source,
            'confirmed': False, 'signals': [], **kw}


def test_unknown_record_is_rechecked_after_3h_and_inside_the_window():
    ko_far = NOW + timedelta(hours=8)
    assert not av.needs_check(_rec(None, hours_ago=1), ko_far, NOW)
    assert av.needs_check(_rec(None, hours_ago=3.5), ko_far, NOW)
    ko_soon = NOW + timedelta(minutes=90)            # inside the 120-min line-up window
    assert av.needs_check(_rec(None, hours_ago=0.4), ko_soon, NOW)
    assert av.needs_check(_rec('sofascore', hours_ago=0.4), ko_soon, NOW)
    assert not av.needs_check(_rec('sofascore', hours_ago=5), ko_far, NOW)   # known stays until the window
    assert not av.needs_check(_rec('sofascore', confirmed=True, hours_ago=5), ko_soon, NOW)
    old = _rec('sofascore', hours_ago=4)
    old.pop('signals')                                  # written before key players existed
    assert av.needs_check(old, ko_far, NOW)


def _write_day(tmp_path, day, rows):
    import json
    (tmp_path / 'results').mkdir(exist_ok=True)
    (tmp_path / 'results' / f'matches_{day}_football_forebet.json').write_text(
        json.dumps({'matches': rows}), encoding='utf-8')


def test_candidates_all_qualifying_adds_info_only_rows(monkeypatch, tmp_path):
    day = '2026-11-19'
    rows = [{'homeTeam': 'A', 'awayTeam': 'B', 'qualifies': True, 'predictionGrade': 'A', 'scoring': {'pick': '1'}},
            {'homeTeam': 'C', 'awayTeam': 'D', 'qualifies': True, 'predictionGrade': 'C', 'scoring': {'pick': '2'}},
            {'homeTeam': 'E', 'awayTeam': 'F', 'qualifies': False, 'predictionGrade': 'C', 'scoring': {'pick': '1'}}]
    _write_day(tmp_path, day, rows)
    monkeypatch.setattr(av, 'ROOT', str(tmp_path))
    assert [c['key'] for c in av.candidates(day)] == ['football|A|B']
    allq = {c['key']: c for c in av.candidates(day, all_qualifying=True)}
    assert set(allq) == {'football|A|B', 'football|C|D'}
    assert allq['football|C|D']['info_only'] and allq['football|C|D']['side'] == 'away'
    assert not allq['football|A|B'].get('info_only')


def _kp(name, share, pid=None):
    return {'id': pid, 'name': name, 'share': share, 'avg': 1.0, 'last': 1, 'unit': 'G+A', 'goalie': False}


def test_star_out_needs_20pct_share():
    rec = {'side': 'home', 'source': 'sofascore', 'home': [{'id': 7, 'name': 'H. Kane', 'status': 'out',
                                                            'importance': 'key', 'reason': 'knee'}], 'away': [],
           'keyPlayers': {'home': [_kp('Harry Kane', 0.32, 7)]}}
    sig = av.signals(rec, 'home')
    assert sig[0]['kind'] == 'star_out' and sig[0]['share'] == 0.32
    assert av.badge_pl(rec, 'home', 'football')['text'] == 'Gwiazda nie gra: Harry Kane (32% goli i asyst)'
    rec['keyPlayers']['home'][0]['share'] = 0.10
    assert not [s for s in av.signals(rec, 'home') if s['kind'] == 'star_out']
    assert av.status_of(rec, 'home') == 'no_key_absence'


def test_reserves_when_next_match_is_cl_in_two_days_not_league_in_six():
    ts = 1_800_000_000
    rec = {'side': 'away', 'source': None, 'unknown': True,
           'competition': {'name': 'LaLiga', 'tier': 1, 'ts': ts},
           'nextFixture': {'away': {'ts': ts + 2 * 86400, 'tier': 3, 'tournament': 'UEFA Champions League'}}}
    assert av.status_of(rec, 'away') == 'reserves'
    assert av.badge_pl(rec, 'away')['text'].startswith('Możliwe rezerwy: puchary')
    rec['nextFixture']['away'] = {'ts': ts + 6 * 86400, 'tier': 1, 'tournament': 'LaLiga'}
    assert av.status_of(rec, 'away') == 'unknown'


def test_unknown_never_downgrades_or_blocks_and_renders_as_brak_danych():
    rec = {'checkedAt': NOW.isoformat(), 'source': None, 'confirmed': False, 'side': 'home',
           'board': 'ok', 'top_block': False, 'unknown': True}
    assert av.signals(rec) == [] and av.status_of(rec) == 'unknown'
    assert av.apply_grade('A', rec['board']) == 'A' and not rec['top_block']
    assert av.badge_pl(rec)['text'] == 'brak danych' and av.badge_pl(None)['text'] == 'brak danych'


def test_info_only_record_keeps_board_ok_even_with_stars_out(monkeypatch, tmp_path):
    import json
    day = '2026-11-19'
    _write_day(tmp_path, day, [{'homeTeam': 'C', 'awayTeam': 'D', 'qualifies': True, 'predictionGrade': 'C',
                                'scoring': {'pick': '1'}, 'time': '23:59'}])
    monkeypatch.setattr(av, 'ROOT', str(tmp_path))
    two_stars = {'home': [P('S1'), P('S2')], 'away': [], 'confirmed': False, 'source': 'sofascore'}
    monkeypatch.setattr(av, 'resolve_event', lambda *a: (None, None))
    monkeypatch.setattr(av, 'sofascore_check', lambda *a, **k: two_stars)
    monkeypatch.setattr(av, 'enrich', lambda rec, *a, **k: rec)
    store = av.run(day, use_llm=False, all_qualifying=True, ignore_kickoff=True, log=lambda *_: None)
    rec = store['football|C|D']
    assert rec['infoOnly'] and rec['infoVerdict'] == 'drop'
    assert rec['board'] == 'ok' and rec['top_block'] is False
    assert json.load(open(tmp_path / 'results' / f'availability_{day}.json'))['football|C|D']['board'] == 'ok'


def test_failed_recheck_keeps_what_an_earlier_run_found(monkeypatch, tmp_path):
    import json
    day = '2026-11-19'
    _write_day(tmp_path, day, [{'homeTeam': 'A', 'awayTeam': 'B', 'qualifies': True, 'predictionGrade': 'A',
                                'scoring': {'pick': '1'}, 'time': '23:59'}])
    prev = {'checkedAt': '2026-11-19T06:00:00+00:00', 'source': 'sofascore', 'confirmed': False, 'side': 'home',
            'home': [P('S1')], 'away': [], 'board': 'downgrade', 'top_block': True}
    (tmp_path / 'results' / f'availability_{day}.json').write_text(json.dumps({'football|A|B': prev}))
    monkeypatch.setattr(av, 'ROOT', str(tmp_path))
    monkeypatch.setattr(av, 'resolve_event', lambda *a: (None, None))
    monkeypatch.setattr(av, 'sofascore_check', lambda *a, **k: None)
    monkeypatch.setattr(av, 'enrich', lambda rec, *a, **k: rec)
    rec = av.run(day, use_llm=False, force=True, ignore_kickoff=True, log=lambda *_: None)['football|A|B']
    assert rec['source'] == 'sofascore' and rec['board'] == 'downgrade' and rec['top_block']
    assert rec['home'][0]['name'] == 'S1' and 'lastFailAt' in rec


def test_kickoff_uses_warsaw_time_and_explicit_utc():
    from tools import availability_agent as aa
    assert aa._kickoff('2026-10-26', '18:00').strftime('%H:%MZ') == '17:00Z'
    assert aa._kickoff('2026-10-26', '18:00', '2026-10-26T16:05:00Z').strftime('%H:%MZ') == '16:05Z'
