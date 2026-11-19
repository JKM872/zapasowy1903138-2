from tools import key_players as kp


def P(pid, name, **stats):
    pos = stats.pop('position', 'F')
    sub = stats.pop('substitute', False)
    return {'id': pid, 'name': name, 'position': pos, 'substitute': sub, 'stats': stats}


def test_share_is_player_output_over_team_output_and_top_n_needs_two_apps():
    m1 = [P(1, 'Star', points=30, secondsPlayed=2000), P(2, 'Wing', points=10, secondsPlayed=1500),
          P(3, 'Once', points=40, secondsPlayed=1800)]
    m2 = [P(1, 'Star', points=20, secondsPlayed=2000), P(2, 'Wing', points=20, secondsPlayed=1500)]
    out = kp.aggregate('basketball', [m1, m2], n=3)
    assert [p['name'] for p in out] == ['Star', 'Wing']        # 'Once' has one appearance
    star = out[0]
    assert star['share'] == round(50 / 120, 3) and star['avg'] == 25.0 and star['last'] == 30
    assert star['unit'] == 'pts'


def test_top_n_cuts_and_football_uses_goals_plus_assists():
    ms = [[P(i, f'P{i}', goals=i, goalAssist=0, minutesPlayed=90) for i in range(1, 6)] for _ in range(2)]
    out = kp.aggregate('football', ms, n=2)
    assert [p['name'] for p in out] == ['P5', 'P4'] and out[0]['unit'] == 'G+A'
    assert out[0]['share'] == round(10 / 30, 3)


def test_hockey_goalie_ranked_by_saves_separately():
    g = dict(position='G')
    ms = [[P(9, 'Goalie', saves=30, secondsPlayed=3600, **g), P(1, 'Sk', goals=1, assists=1, secondsPlayed=1000)],
          [P(9, 'Goalie', saves=25, secondsPlayed=3600, **g), P(1, 'Sk', goals=0, assists=1, secondsPlayed=1000)]]
    out = kp.aggregate('hockey', ms)
    gk = next(p for p in out if p['goalie'])
    assert gk['share'] == 1.0 and gk['unit'] == 'saves'
    assert next(p for p in out if not p['goalie'])['share'] == 1.0


def test_status_defaults_to_unknown_and_needs_lineup_or_source_for_plays():
    kps = [{'id': 1, 'name': 'Luka Doncic', 'share': 0.3}, {'id': 2, 'name': 'Austin Reaves', 'share': 0.2}]
    assert [p['status'] for p in kp.status_for(kps, {}, 'home')] == ['unknown', 'unknown']
    rec = {'home': [{'id': 1, 'name': 'L. Doncic', 'status': 'out', 'reason': 'ankle'}],
           'extra': {'home': [{'name': 'Austin Reaves', 'status': 'plays', 'reason': 'expected line-up',
                               'source': 'rotowire'}]}}
    st = kp.status_for(kps, rec, 'home')
    assert st[0]['status'] == 'out' and st[0]['source'] == 'sofascore'
    assert st[1]['status'] == 'plays' and st[1]['source'] == 'rotowire'


def test_confirmed_lineup_without_the_player_is_bench():
    kps = [{'id': 1, 'name': 'A Star', 'share': 0.4}, {'id': 2, 'name': 'B Mid', 'share': 0.2}]
    rec = {'confirmed': True, 'lineup': {'away': [{'id': 2, 'name': 'B. Mid'}]}}
    st = {p['name']: p['status'] for p in kp.status_for(kps, rec, 'away')}
    assert st == {'A Star': 'bench', 'B Mid': 'plays'}


def test_confirmed_squad_bench_only_counts_in_football():
    kps = [{'id': 1, 'name': 'Sixth Man', 'share': 0.3}, {'id': 2, 'name': 'Gone', 'share': 0.25}]
    rec = {'lineupInfo': {'confirmed': True, 'lineup': {'home': []},
                          'squad': {'home': [{'id': 1, 'name': 'S. Man', 'sub': True}]}}}
    bb = {p['name']: p['status'] for p in kp.status_for(kps, rec, 'home', 'basketball')}
    assert bb == {'Sixth Man': 'plays', 'Gone': 'out'}
    fb = {p['name']: p['status'] for p in kp.status_for(kps, rec, 'home', 'football')}
    assert fb == {'Sixth Man': 'bench', 'Gone': 'out'}


def test_lineup_only_event_is_kept_for_display(monkeypatch):
    import sofascore_scraper as ss
    from tools import availability_agent as av
    data = {'confirmed': True, 'home': {'players': [{'player': {'id': 1, 'name': 'A'}}]},
            'away': {'players': [{'player': {'id': 2, 'name': 'B'}, 'substitute': True}]}}
    monkeypatch.setattr(ss, '_api_get_json', lambda *a, **k: data)
    m = {'sofascore': {'url': 'https://www.sofascore.com/x/match/12345678', 'orientation': 'direct'}}
    assert av.sofascore_check(m) is None                      # legacy behaviour: no verdict data
    res = av.sofascore_check(m, keep_lineup=True)
    assert res['lineupOnly'] and res['squad']['away'] == [{'id': 2, 'name': 'B', 'sub': True}]


def test_name_match_by_surname_and_initial():
    kps = [{'name': 'Toumani Camara', 'share': 0.25}]
    rec = {'extra': {'home': [{'name': 'T. Camara', 'status': 'doubtful', 'reason': 'Ques', 'source': 'rotowire'}]}}
    assert kp.status_for(kps, rec, 'home')[0]['status'] == 'doubtful'
    rec = {'extra': {'home': [{'name': 'J. Camara', 'status': 'out', 'source': 'rotowire'}]}}
    assert kp.status_for(kps, rec, 'home')[0]['status'] == 'unknown'


def test_fmt_line_per_sport():
    assert kp.fmt_line({'name': 'Luka', 'avg': 24.5, 'last': 31, 'unit': 'pts', 'status': 'out',
                        'source': 'rotowire'}) == 'Luka (avg 24.5, last 31 pts): OUT – rotowire'
    assert kp.fmt_line({'name': 'Kane', 'avg': 1.0, 'last': 2, 'unit': 'G+A', 'status': 'unknown'}) \
        == 'Kane (avg 1, last 2 G+A): UNKNOWN'
    assert kp.fmt_line({'name': 'GK', 'avg': 27.5, 'last': 30, 'unit': 'saves', 'status': 'plays',
                        'source': 'dailyfaceoff'}).endswith('saves): PLAYS – dailyfaceoff')


def test_tier_and_reserves_rule():
    assert kp.tier('UEFA Champions League') == 3
    assert kp.tier('Copa del Rey', 'Quarterfinals') == 2
    assert kp.tier('Copa del Rey', 'Round of 32') == 1
    assert kp.tier('LaLiga') == 1
    ts = 1_800_000_000
    cl = {'ts': ts + 2 * 86400, 'tier': 3, 'tournament': 'UEFA Champions League'}
    r = kp.reserves_reason(1, ts, cl)
    assert r['kind'] == 'reserves' and r['days'] == 2.0 and 'European' in r['reason']
    assert kp.reserves_reason(1, ts, {'ts': ts + 6 * 86400, 'tier': 1, 'tournament': 'LaLiga'}) is None
    assert kp.reserves_reason(1, ts, {'ts': ts + 6 * 86400, 'tier': 3}) is None   # too far
    assert kp.reserves_reason(3, ts, cl) is None                                     # same tier
    assert kp.reserves_reason(1, ts, None) is None


def test_network_failure_gives_empty_list(monkeypatch, tmp_path):
    import sofascore_scraper as ss
    monkeypatch.setattr(kp, 'CACHE_PATH', str(tmp_path / 'kp.json'))
    kp._cache.clear()

    def boom(*a, **k):
        raise OSError('net down')
    monkeypatch.setattr(ss, '_api_get_json', boom)
    assert kp.team_key_players('football', 123, '2026-11-19') == []
    assert kp.next_fixture(123, 0, None, '2026-11-19') is None
    assert kp.team_key_players('tennis', 1, '2026-11-19') == []
    kp._cache.clear()
