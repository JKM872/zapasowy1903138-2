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
