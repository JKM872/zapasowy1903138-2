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
    assert a['source'] == 'top+fan' and a['price'] == 2.5 and a['limit']['min'] == 2.0


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
