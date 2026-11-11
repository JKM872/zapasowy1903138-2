"""Weekend Slip: leg pool, disjoint slips, withdrawal, settlement and paywall."""
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import weekend_feed  # noqa: E402
from tools import weekend_slip as ws  # noqa: E402

FRI = '2026-10-23'
SAT = '2026-10-24'
NOW = datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc)


def fan(sport, day, home, away, price, fan_pct=75, league='L', side='home', verdict='ok',
        status='pick', model=0.6, hour=18):
    return {'id': f'{sport}|{day}|{home}|{away}', 'sport': sport, 'date': day, 'league': league,
            'kickoff': f'{day}T{hour:02d}:00:00Z', 'home': home, 'away': away, 'side': side,
            'team': home if side == 'home' else away, 'fanPct': fan_pct, 'status': status,
            'bestPrice': {'price': price, 'bookmaker': 'pinnacle'}, 'modelProb': model,
            'limit': {'min': 2.0 if sport == 'football' else 1.5, 'source': 'top_floor'},
            'availability': {'verdict': verdict}, 'grade': 'B'}


def setup(tmp_path, by_day, top=None):
    res = tmp_path / 'results'
    res.mkdir(exist_ok=True)
    for day, picks in by_day.items():
        sports = {}
        for p in picks:
            sports.setdefault(p['sport'], {'picks': []})['picks'].append(p)
        (res / f'fanvote_{day}.json').write_text(json.dumps({'sports': sports}), encoding='utf-8')
    for day, rows in (top or {}).items():
        (res / f'top_{day}.json').write_text(json.dumps(rows), encoding='utf-8')
    return str(res)


def test_weekend_dates():
    assert ws.friday_of(date(2026, 10, 25)) == date(2026, 10, 23)
    assert ws.friday_of(date(2026, 10, 23)) == date(2026, 10, 23)
    assert ws.friday_of(date(2026, 10, 22)) is None
    assert ws.weekend_days(date(2026, 10, 23)) == [FRI, SAT, '2026-10-25']


def test_pool_filters_limit_availability_watch_and_merges_top(tmp_path):
    res = setup(tmp_path, {FRI: [
        fan('football', FRI, 'A', 'B', 2.4),
        fan('football', FRI, 'C', 'D', 1.8),                    # below 2.0 limit
        fan('football', FRI, 'E', 'F', 2.5, verdict='out'),     # star out
        fan('volleyball', FRI, 'G', 'H', 1.9, status='watch'),  # no record yet
        fan('hockey', FRI, 'I', 'J', 2.0, hour=4),              # already started
    ]}, top={FRI: [{'sport': 'football', 'match': 'A vs B', 'pick': 'A', 'odds': 2.3,
                    'bestOdds': 2.5, 'league': 'L', 'kickoffUtc': f'{FRI}T18:00:00Z'},
                   {'sport': 'hockey', 'match': 'K vs M', 'pick': 'M', 'odds': 1.4,
                    'league': 'H', 'kickoffUtc': f'{FRI}T18:00:00Z'}]})   # 1.4 < 1.5
    pool = ws.leg_pool([FRI], res, NOW)
    assert [l['pick'] for l in pool] == ['A']
    a = pool[0]
    assert a['source'] == 'top+fan' and a['price'] == 2.5 and a['limit']['min'] == 1.5


def test_slips_are_disjoint_multi_day_and_capped(tmp_path):
    legs = [fan('football', FRI, f'T{i}', f'U{i}', 2.2 + i / 10, league=f'L{i % 3}') for i in range(6)]
    legs += [fan('hockey', SAT, 'H1', 'H2', 1.9, league='NHL'), fan('hockey', SAT, 'T0', 'Z', 1.9, league='KHL')]
    res = setup(tmp_path, {FRI: legs[:6], SAT: legs[6:]})
    slips = ws.build_slips(ws.leg_pool([FRI, SAT], res, NOW), [])
    assert 1 <= len(slips) <= ws.MAX_SLIPS
    ids, teams = set(), set()
    for s in slips:
        assert ws.MIN_LEGS <= len(s['legs']) <= ws.MAX_LEGS
        leagues = [ws._league_key(l) for l in s['legs']]
        assert len(set(leagues)) == len(leagues)
        for l in s['legs']:
            assert l['id'] not in ids and not (ws._teams(l) & teams)
            ids.add(l['id'])
            teams |= ws._teams(l)
        assert s['combinedOdds'] == round(eval('*'.join(str(l['price']) for l in s['legs'])), 2)
    assert {l['date'] for l in slips[0]['legs']} == {FRI, SAT}
    assert len(ws.build_slips(ws.leg_pool([FRI, SAT], res, NOW), [], max_new=1)) == 1


def test_withdrawal_adjusts_then_voids(tmp_path):
    res = setup(tmp_path, {FRI: [fan('football', FRI, 'A', 'B', 2.0, league='X'),
                                 fan('football', FRI, 'C', 'D', 3.0, league='Y'),
                                 fan('hockey', FRI, 'E', 'F', 2.0, league='Z')]})
    slip = ws.build_slips(ws.leg_pool([FRI], res, NOW), [])[0]
    assert slip['combinedOdds'] == 12.0 and slip['status'] == 'pending'
    (tmp_path / 'results' / f'availability_{FRI}.json').write_text(json.dumps({
        'football|C|D': {'side': 'home', 'home': [
            {'name': 'X', 'importance': 'star', 'status': 'out'},
            {'name': 'Y', 'importance': 'star', 'status': 'out'}], 'away': []}}), encoding='utf-8')
    near = datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc)
    assert ws.recheck([slip], res, near) == 1
    assert slip['status'] == 'adjusted' and slip['combinedOdds'] == 4.0
    slip['legs'][0]['status'] = 'withdrawn'
    ws.slip_numbers(slip)
    assert slip['status'] == 'void'


def _settled_weekend(tmp_path):
    res = setup(tmp_path, {FRI: [fan('football', FRI, 'A', 'B', 2.0, league='X'),
                                 fan('hockey', FRI, 'C', 'D', 2.0, league='Y')]})
    (tmp_path / 'results' / 'forebet_settled.json').write_text(json.dumps({
        f'{FRI}|football|A|B': {'status': 'settled', 'winner': 'home', 'score': '2-0'}}), encoding='utf-8')
    ws.run(FRI, 'build', res, now=NOW, store=str(tmp_path / 'none.json'), log=lambda *_: None)
    return res


def test_settle_draw_lost_and_feed_paywall(tmp_path):
    res = _settled_weekend(tmp_path)
    data = json.load(open(ws.slip_path(FRI, res), encoding='utf-8'))
    s = data['slips'][0]
    assert [l['status'] for l in s['legs']] == ['won', 'pending'] and s['status'] == 'pending'
    anon = weekend_feed.load_weekend(res, is_subscriber=False, remote=False, now=NOW)
    legs = anon['weekends'][0]['slips'][0]['legs']
    assert legs[0]['pick'] == 'A' and legs[1]['locked'] and 'pick' not in legs[1] and 'price' not in legs[1]
    sub = weekend_feed.load_weekend(res, is_subscriber=True, remote=False, now=NOW)
    assert sub['weekends'][0]['slips'][0]['legs'][1]['pick'] == 'C'
    (tmp_path / 'results' / 'forebet_settled.json').write_text(json.dumps({
        f'{FRI}|football|A|B': {'status': 'settled', 'winner': 'home', 'score': '2-0'},
        f'{FRI}|hockey|C|D': {'status': 'settled', 'winner': 'draw', 'score': '1-1'}}), encoding='utf-8')
    anon = weekend_feed.load_weekend(res, is_subscriber=False, remote=False, now=NOW)
    s = anon['weekends'][0]['slips'][0]
    assert s['status'] == 'lost' and s['legs'][1]['pick'] == 'C'
    assert anon['record']['slips'] == 1 and anon['record']['roiPct'] == -100.0


def test_api_validates_friday(monkeypatch):
    monkeypatch.setenv('TOP_FEED_REMOTE', '0')
    import api_server
    c = api_server.app.test_client()
    assert c.get('/api/weekend-slip?friday=23-10-2026').status_code == 400
    r = c.get('/api/weekend-slip')
    assert r.status_code == 200 and r.get_json()['isSubscriber'] is False


def test_void_leg_is_dropped_like_withdrawn():
    legs = [dict(id=str(i), date='2026-10-30', match=f'H{i} vs A{i}', pick=f'H{i}', price=1.5,
                 modelProb=0.7, status='pending') for i in range(3)]
    idx = {('2026-10-30', 'h0', 'a0'): {'void': True, 'winner': None}}
    import top_feed
    idx = {('2026-10-30', top_feed._norm('H0'), top_feed._norm('A0')): {'void': True, 'winner': None}}
    s = {'id': 'S1', 'legs': legs}
    ws.settle_slips([s], idx)
    assert legs[0]['status'] == 'void'
    assert s['combinedOdds'] == round(1.5 * 1.5, 2) and s['adjusted']


SUN = '2026-10-25'


def _pool_weekend(tmp_path):
    by = {}
    for d, sp in ((FRI, 'football'), (SAT, 'hockey'), (SUN, 'basketball')):
        by[d] = [fan(sp, d, f'{d}A{i}', f'{d}B{i}', 2.2, league=f'{d}L{i}') for i in range(4)]
    return setup(tmp_path, by)


def _build(res, now):
    return ws.run(FRI, 'build', res, now=now, store='none.json', log=lambda *_: None)


def test_day_slots_one_slip_per_day(tmp_path):
    res = _pool_weekend(tmp_path)
    d = _build(res, NOW)
    assert d['added'] == 1 and [s['slot'] for s in d['slips']] == ['S1']
    assert _build(res, NOW)['added'] == 0
    d = _build(res, datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc))
    s2 = d['slips'][-1]
    assert d['added'] == 1 and s2['slot'] == 'S2' and {l['date'] for l in s2['legs']} <= {SAT, SUN}
    d = _build(res, datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc))
    s3 = d['slips'][-1]
    assert d['added'] == 1 and s3['slot'] == 'S3' and {l['date'] for l in s3['legs']} == {SUN}
    assert _build(res, datetime(2026, 10, 25, 7, 0, tzinfo=timezone.utc))['added'] == 0


def test_mail_only_when_slip_added(tmp_path, monkeypatch):
    res = _pool_weekend(tmp_path)
    sent = []
    monkeypatch.setattr(ws, 'send_email', lambda d: sent.append(d))
    monkeypatch.setattr(ws, '_now', lambda: NOW)
    run = ws.run
    monkeypatch.setattr(ws, 'run', lambda fr, mode: run(fr, mode, res, now=NOW, log=lambda *_: None))
    monkeypatch.setattr(ws, '_index', lambda *a, **k: {})
    monkeypatch.setattr(ws, 'settle_slips', lambda *a, **k: 0)
    ws.main(['--email'])
    ws.main(['--email'])
    assert len(sent) == 1


def test_top_withdrawal_hours_before_kickoff(tmp_path):
    res = setup(tmp_path, {FRI: [fan('football', FRI, 'A', 'B', 2.4, league='X'),
                                 fan('hockey', FRI, 'C', 'D', 2.0, league='Y')]},
                top={FRI: [{'sport': 'football', 'match': 'A vs B', 'pick': 'A', 'bestOdds': 2.4,
                            'league': 'X', 'kickoffUtc': f'{FRI}T18:00:00Z'}]})
    slip = ws.build_slips(ws.leg_pool([FRI], res, NOW), [])[0]
    (tmp_path / 'results' / f'top_{FRI}.json').write_text(json.dumps([
        {'sport': 'football', 'match': 'A vs B', 'pick': 'A', 'withdrawn': True,
         'withdrawReason': 'Odds fell below the limit'}]), encoding='utf-8')
    assert ws.recheck([slip], res, datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc)) == 1
    leg = next(l for l in slip['legs'] if l['pick'] == 'A')
    assert leg['status'] == 'withdrawn' and leg['withdrawnReason'] == 'Odds fell below the limit'


def test_pending_leg_of_lost_slip_stays_locked(tmp_path):
    res = setup(tmp_path, {FRI: [fan('football', FRI, 'A', 'B', 2.0, league='X')],
                           SAT: [fan('hockey', SAT, 'C', 'D', 2.0, league='Y')]})
    (tmp_path / 'results' / 'forebet_settled.json').write_text(json.dumps({
        f'{FRI}|football|A|B': {'status': 'settled', 'winner': 'away', 'score': '0-1'}}), encoding='utf-8')
    ws.run(FRI, 'build', res, now=NOW, store=str(tmp_path / 'none.json'), log=lambda *_: None)
    later = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)
    s = weekend_feed.load_weekend(res, is_subscriber=False, remote=False, now=later)['weekends'][0]['slips'][0]
    assert s['status'] == 'lost'
    assert s['legs'][0]['pick'] == 'A' and s['legs'][1]['locked'] and 'pick' not in s['legs'][1]


def _leg(sport, day, home, away, side, price=2.0):
    return {'id': f'{sport}|{day}|{home}|{away}', 'sport': sport, 'date': day, 'home': home,
            'away': away, 'match': f'{home} vs {away}', 'side': side,
            'pick': home if side == 'home' else away, 'price': price, 'modelProb': 0.5,
            'status': 'pending', 'score': None}


def test_pending_women_leg_settles_from_polish_store_names():
    # 2026-11-06 S2: Sweden W - Canada W stayed pending; Livesport stores 'Szwecja K - Kanada K'.
    import top_feed
    day = '2026-11-06'
    idx = {(day, top_feed._norm('Szwecja K'), top_feed._norm('Kanada K')):
           {'winner': 'away', 'score_home': 1, 'score_away': 5},
           (day, top_feed._norm('Szwecja U18'), top_feed._norm('Kanada')):
           {'winner': 'home', 'score_home': 4, 'score_away': 2}}
    legs = [_leg('hockey', day, 'Sweden W', 'Canada W', 'away', 3.08),
            _leg('football', '2026-11-07', 'Tigres FC (COL)', 'Deportes Quindío', 'away')]
    idx[('2026-11-07', 'tigres', 'quindio')] = {'winner': 'home', 'score_home': 2, 'score_away': 0}
    s = {'id': 'S2', 'legs': legs}
    assert ws.settle_slips([s], idx) == 2
    assert (legs[0]['status'], legs[0]['score']) == ('won', '1-5')
    assert (legs[1]['status'], legs[1]['score']) == ('lost', '2-0')


def test_loose_match_keeps_women_youth_and_reserves_apart():
    import top_feed
    day = '2026-11-06'
    idx = {(day, top_feed._norm('Szwecja'), top_feed._norm('Kanada')): {'winner': 'home'},
           (day, top_feed._norm('Szwecja U18'), top_feed._norm('Kanada U18')): {'winner': 'home'}}
    leg = _leg('hockey', day, 'Sweden W', 'Canada W', 'away')
    ws.settle_slips([{'id': 'S1', 'legs': [leg]}], idx)
    assert leg['status'] == 'pending'


def test_settle_sweeps_every_recent_weekend_with_pending_legs(tmp_path, monkeypatch):
    res = tmp_path / 'results'
    res.mkdir()
    pending = {'slips': [{'id': 'S3', 'legs': [_leg('football', '2026-11-07', 'A', 'B', 'away')]}]}
    done = {'slips': [{'id': 'S1', 'legs': [dict(_leg('football', '2026-10-30', 'C', 'D', 'home'),
                                                 status='won')]}]}
    (res / 'weekend_2026-11-06.json').write_text(json.dumps(pending), encoding='utf-8')
    (res / 'weekend_2026-10-30.json').write_text(json.dumps(done), encoding='utf-8')
    (res / 'weekend_2026-09-04.json').write_text(json.dumps(pending), encoding='utf-8')  # too old
    assert ws.pending_fridays(date(2026, 11, 12), str(res)) == ['2026-11-06']
    idx = {('2026-11-07', 'a', 'b'): {'winner': 'away', 'score_home': '0', 'score_away': '1'}}
    monkeypatch.setattr(ws, '_index', lambda *a, **k: idx)
    ws.run('2026-11-06', 'settle', results=str(res), log=lambda *a: None)
    leg = json.load(open(res / 'weekend_2026-11-06.json', encoding='utf-8'))['slips'][0]['legs'][0]
    assert (leg['status'], leg['score']) == ('won', '0-1')
