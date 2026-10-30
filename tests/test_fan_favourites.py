"""Fan Favourites: thresholds, odds limits, builder, settlement and paywall."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fan_feed  # noqa: E402
import fan_limits as fl  # noqa: E402
from tools import fan_favourites as ff  # noqa: E402

DAY = '2026-10-21'
NOW = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)


def row(home, away, hp, ap, votes=500, odds=(2.2, 3.4, 3.1), time='19:00'):
    return {'homeTeam': home, 'awayTeam': away, 'time': time, 'league': 'L', 'country': 'C',
            'sofascore': {'found': True, 'homeProb': hp, 'awayProb': ap, 'votes': votes, 'url': 'u'},
            'odds': {'home': odds[0], 'draw': odds[1], 'away': odds[2], 'bookmaker': 'Pinnacle'},
            'form': {'home': ['W', 'W', 'L'], 'away': ['L', 'D'], 'homeAtHome': ['W'], 'awayAtAway': ['L']},
            'h2h': {'total': 3, 'homeWins': 2, 'awayWins': 1, 'lastScore': '1-0'},
            'forebet': {'prediction': '1', 'homeProb': 55, 'awayProb': 20},
            'scoring': {'pick': '1', 'prob': 58.0}, 'predictionGrade': 'B'}


def write_rows(tmp_path, sport, rows, avail=None):
    res = tmp_path / 'results'
    res.mkdir(exist_ok=True)
    (res / f'matches_{DAY}_{sport}_forebet.json').write_text(
        json.dumps({'matches': rows}), encoding='utf-8')
    if avail is not None:
        (res / f'availability_{DAY}.json').write_text(json.dumps(avail), encoding='utf-8')
    return str(res)


def test_thresholds_and_bands():
    assert fl.fan_threshold('football') == 60 and fl.fan_threshold('tennis') == 70
    assert fl.select('football', 60, 100) and not fl.select('football', 59.9, 500)
    assert not fl.select('hockey', 69, 500) and not fl.select('hockey', 75, 99)
    assert [fl.band(x) for x in (60, 69.9, 70, 85, 90, 100)] == ['60-70', '60-70', '70-80', '80-90', '90+', '90+']


def test_odds_limits_use_the_pipeline_and_top_floors(tmp_path):
    assert fl.odds_limit('football') == {'min': 2.0, 'source': 'top_floor'}
    assert fl.odds_limit('basketball')['min'] == 1.8
    assert fl.odds_limit('hockey') == {'min': 1.5, 'source': 'sport_floor'}
    assert fl.odds_limit('rugby')['min'] == 1.35
    rules = tmp_path / 'r.json'
    rules.write_text(json.dumps({'segments': {'hockey|1.6-1.8': {'decision': 'allow', 'floorOdds': 1.7}}}))
    assert fl.odds_limit('hockey', 1.65, 'home', str(rules)) == {'min': 1.7, 'source': 'top_rules:hockey|1.6-1.8'}


def test_build_selects_sorts_and_applies_the_limit(tmp_path):
    res = write_rows(tmp_path, 'football', [
        row('A', 'B', 65, 20),                          # 65% at 2.2 -> pick
        row('C', 'D', 80, 10, odds=(1.5, 4, 6)),       # 1.5 < 2.0 -> out
        row('E', 'F', 15, 75, odds=(5, 4, 2.4)),       # away 75% -> pick, first
        row('G', 'H', 90, 5, votes=50),                # too few votes
    ], avail={'football|A|B': {'side': 'home', 'home': [
        {'name': 'X', 'importance': 'star', 'status': 'out'},
        {'name': 'Y', 'importance': 'star', 'status': 'out'}], 'away': []}})
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    assert [p['team'] for p in blk['picks']] == ['F', 'A']
    f, a = blk['picks']
    assert f['side'] == 'away' and f['band'] == '70-80' and f['form']['overall'] == 'LD'
    assert f['impliedPct'] == round(100 / 2.4, 1) and f['edgePct'] == round(75 - 100 / 2.4, 1)
    assert f['limit'] == {'min': 2.0, 'source': 'top_floor'} and f['status'] == 'pick'
    assert a['availability']['verdict'] == 'out' and a['modelProb'] == 0.58
    assert f['availability']['verdict'] == 'unknown'
    assert blk['stats']['belowLimit'] == 1


def test_watch_sports_are_not_staked(tmp_path):
    res = write_rows(tmp_path, 'volleyball', [row('A', 'B', 80, 20, odds=(1.5, None, 2.5))])
    blk = ff.build('volleyball', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    assert blk['watch'] and blk['picks'][0]['status'] == 'watch'


def _board(tmp_path):
    res = write_rows(tmp_path, 'football', [row('A', 'B', 65, 20), row('E', 'F', 15, 75, odds=(5, 4, 2.4))])
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    ff.merge(DAY, 'football', blk, res, now=NOW)
    (tmp_path / 'results' / 'forebet_settled.json').write_text(json.dumps({
        f'{DAY}|football|A|B': {'status': 'settled', 'winner': 'draw', 'score': '1-1'}}), encoding='utf-8')
    return res


def test_settle_draw_is_a_loss_and_merge_keeps_results(tmp_path):
    res = _board(tmp_path)
    import top_feed
    n = ff.settle_file(DAY, top_feed._forebet_settled(res), res, now=NOW)
    assert n == 1
    data = json.load(open(ff.fan_path(DAY, res), encoding='utf-8'))
    a = [p for p in data['sports']['football']['picks'] if p['team'] == 'A'][0]
    assert a['result']['status'] == 'lost' and a['result']['draw']
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    data = ff.merge(DAY, 'football', blk, res, now=NOW)
    a = [p for p in data['sports']['football']['picks'] if p['team'] == 'A'][0]
    assert a['result']['status'] == 'lost'


def test_feed_paywall_and_record(tmp_path):
    res = _board(tmp_path)
    anon = fan_feed.load_fan(res, is_subscriber=False, remote=False, now=NOW)
    picks = anon['days'][0]['sports']['football']['picks']
    settled = [p for p in picks if not p.get('locked')]
    locked = [p for p in picks if p.get('locked')]
    assert len(settled) == 1 and settled[0]['team'] == 'A'
    assert len(locked) == 1 and 'team' not in locked[0] and 'bestPrice' not in locked[0]
    assert locked[0]['band'] == '70-80'
    rec = anon['record']['bySport']['football']
    assert rec == {'n': 1, 'won': 0, 'hitPct': 0.0, 'roiPct': -100.0, 'profitUnits': -1.0, 'avgOdds': 2.2}
    assert anon['record']['byBand']['60-70']['n'] == 1
    sub = fan_feed.load_fan(res, is_subscriber=True, remote=False, now=NOW, sport='football', date=DAY)
    assert all(not p.get('locked') for p in sub['days'][0]['sports']['football']['picks'])
    assert fan_feed.load_fan(res, remote=False, now=NOW, sport='hockey')['days'][0]['sports'] == {}


def test_api_validates_params(monkeypatch):
    monkeypatch.setenv('TOP_FEED_REMOTE', '0')
    import api_server
    c = api_server.app.test_client()
    assert c.get('/api/fan-favourites?sport=chess').status_code == 400
    assert c.get('/api/fan-favourites?date=21-10-2026').status_code == 400
    r = c.get('/api/fan-favourites?sport=football')
    assert r.status_code == 200 and r.get_json()['isSubscriber'] is False
