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
    assert fl.fan_threshold('football') == 70 and fl.fan_threshold('tennis') == 70
    assert fl.select('football', 70, 100) and not fl.select('football', 69.9, 500)
    assert not fl.select('hockey', 69, 500) and not fl.select('hockey', 75, 99)
    assert [fl.band(x) for x in (60, 69.9, 70, 85, 90, 100)] == ['60-70', '60-70', '70-80', '80-90', '90+', '90+']


def test_odds_limits_are_the_standard_per_sport_limits(tmp_path):
    assert fl.odds_limit('football') == {'min': 1.5, 'source': 'standard'}
    assert fl.odds_limit('basketball')['min'] == 1.3
    assert fl.odds_limit('hockey') == {'min': 1.5, 'source': 'standard'}
    assert fl.odds_limit('baseball')['min'] == 1.4
    assert fl.odds_limit('rugby')['min'] == 1.35
    rules = tmp_path / 'r.json'
    rules.write_text(json.dumps({'segments': {'hockey|1.6-1.8': {'decision': 'allow', 'floorOdds': 1.7}}}))
    assert fl.odds_limit('hockey', 1.65, 'home', str(rules)) == {'min': 1.5, 'source': 'standard'}
    assert fl.passes_standard('football', 1.6, 5.5) and not fl.passes_standard('football', 2.6, 1.4)
    assert not fl.passes_standard('football', 2.0, None)


def test_build_selects_sorts_and_applies_the_limit(tmp_path):
    res = write_rows(tmp_path, 'football', [
        row('A', 'B', 72, 20),                          # 72% at 2.2 -> pick
        row('C', 'D', 80, 10, odds=(1.4, 4, 6)),       # 1.4 < 1.5 -> out
        row('E', 'F', 15, 75, odds=(5, 4, 2.4)),       # away 75% -> pick, first
        row('G', 'H', 90, 5, votes=20),                # too few votes
    ], avail={'football|A|B': {'side': 'home', 'home': [
        {'name': 'X', 'importance': 'star', 'status': 'out'},
        {'name': 'Y', 'importance': 'star', 'status': 'out'}], 'away': []}})
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    assert [p['team'] for p in blk['picks']] == ['F', 'A']
    f, a = blk['picks']
    assert f['side'] == 'away' and f['band'] == '70-80' and f['form']['overall'] == 'LD'
    assert f['impliedPct'] == round(100 / 2.4, 1) and f['edgePct'] == round(75 - 100 / 2.4, 1)
    assert f['limit'] == {'min': 1.5, 'source': 'standard'} and f['status'] == 'pick'
    assert a['availability']['verdict'] == 'out' and a['modelProb'] == 0.58
    assert f['availability']['verdict'] == 'unknown'
    assert blk['stats']['belowLimit'] == 1


def test_c6_standard_limits_counters_and_season_form(tmp_path):
    r1 = row('A', 'B', 72, 20, odds=(1.60, 4.0, 5.5))
    r1.update(homeSeason=['W', 'W'], awaySeason=['L'], homeAtHomeSeason=['W'])
    res = write_rows(tmp_path, 'football', [
        r1, row('C', 'D', 70, 10, odds=(2.6, 3, 1.40)),
        {**row('E', 'F', 70, 10), 'odds': {'home': 2.0, 'draw': 3, 'away': None}}])
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    s = blk['stats']
    assert [p['team'] for p in blk['picks']] == ['A']
    assert s['belowLimit'] == 1 and s['noOdds'] == 1
    assert s['rows'] >= s['withVote'] >= s['fanThr'] >= s['fanOk'] >= s['oddsOk'] >= s['picks'] == 1
    f = blk['picks'][0]['form']
    assert f['season'] == 'WW' and f['opponentSeason'] == 'L' and f['venueSeason'] == 'W'


def test_c6_table_tennis_rows_union_aiscore(tmp_path):
    res = tmp_path / 'results'
    res.mkdir()
    for focus, rs in (('home', [row('A', 'B', 80, 20), row('C', 'D', 80, 20)]),
                      ('away', [row('A', 'B', 80, 20), row('E', 'F', 20, 80)])):
        (res / f'matches_{DAY}_table_tennis_aiscore_{focus}.json').write_text(
            json.dumps({'matches': rs}), encoding='utf-8')
    assert [r['homeTeam'] for r in ff._rows(DAY, 'table_tennis', str(res))] == ['A', 'C', 'E']


def test_watch_sports_are_not_staked(tmp_path):
    res = write_rows(tmp_path, 'volleyball', [row('A', 'B', 80, 20, odds=(1.5, None, 2.5))])
    blk = ff.build('volleyball', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    assert blk['watch'] and blk['picks'][0]['status'] == 'watch'


def _board(tmp_path):
    res = write_rows(tmp_path, 'football', [row('A', 'B', 72, 20), row('E', 'F', 15, 75, odds=(5, 4, 2.4))])
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
    assert anon['record']['byBand']['70-80']['n'] == 1
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


def test_rows_fall_back_to_sports_scraper_before_forebet(tmp_path):
    day = '2026-11-08'
    (tmp_path / f'matches_{day}_football.json').write_text(json.dumps({'matches': [
        {'homeTeam': 'A', 'awayTeam': 'B', 'time': '08.11.2026 14:00',
         'sofascore': {'home': 70, 'draw': 10, 'away': 20, 'votes': 500}}]}), encoding='utf-8')
    rows = ff._rows(day, 'football', str(tmp_path))
    assert len(rows) == 1 and rows[0]['time'] == '14:00'
    assert fl.fan_side(rows[0]) == {'side': 'home', 'fanPct': 70.0, 'votes': 500}


def test_settle_file_marks_void(tmp_path):
    import json as _j
    import top_feed
    from tools import fan_favourites as _ff
    day = '2026-10-20'
    (tmp_path / f'fanvote_{day}.json').write_text(_j.dumps({'sports': {'tennis': {'picks': [
        {'match': 'Alpha vs Beta', 'team': 'Alpha'}]}}}), encoding='utf-8')
    idx = {(day, top_feed._norm('Alpha'), top_feed._norm('Beta')): {'void': True, 'winner': None}}
    assert _ff.settle_file(day, idx, str(tmp_path)) == 1
    d = _j.loads((tmp_path / f'fanvote_{day}.json').read_text(encoding='utf-8'))
    assert d['sports']['tennis']['picks'][0]['result']['status'] == 'void'


def _fp(sport, home, away, band, price, status='pick', result=None, kickoff='2026-10-21T19:00:00Z',
        fan=75, votes=500):
    return {'id': f'{sport}|{DAY}|{home}|{away}', 'sport': sport, 'date': DAY, 'home': home, 'away': away,
            'match': f'{home} vs {away}', 'team': home, 'band': band, 'fanPct': fan, 'votes': votes,
            'kickoff': kickoff, 'bestPrice': {'price': price}, 'status': status, 'result': result}


def _fixed_sample(tmp_path):
    res = tmp_path / 'results'
    res.mkdir(exist_ok=True)
    past = '2026-10-20T19:00:00Z'
    data = {'sports': {
        'football': {'picks': [
            _fp('football', 'A', 'B', '60-70', 2.0, result={'status': 'won', 'score': '2-0'}, kickoff=past),
            _fp('football', 'C', 'D', '70-80', 2.5, result={'status': 'lost', 'score': '0-1'}, kickoff=past),
            _fp('football', 'E', 'F', '60-70', 1.8, kickoff=past,
                result={'status': 'lost', 'score': '1-1', 'draw': True}),
            _fp('football', 'G', 'H', '80-90', 2.2, result={'status': 'void'}, kickoff=past),
            _fp('football', 'I', 'J', '60-70', 1.9)]},
        'tennis': {'picks': [
            _fp('tennis', 'K', 'L', '80-90', 1.7, result={'status': 'won'}, kickoff=past),
            _fp('tennis', 'M', 'N', '90+', 1.9, status='watch', result={'status': 'won'}, kickoff=past),
            _fp('tennis', 'O', 'P', '70-80', 1.6)]}}}
    (res / f'fanvote_{DAY}.json').write_text(json.dumps(data), encoding='utf-8')
    return str(res)


def test_record_unchanged_fixed_sample(tmp_path):
    out = fan_feed.load_fan(_fixed_sample(tmp_path), remote=False, now=NOW)
    rec = out['record']
    none = {'n': 0, 'won': 0, 'hitPct': None, 'roiPct': None, 'profitUnits': None, 'avgOdds': None}
    assert rec['all'] == {'n': 4, 'won': 2, 'hitPct': 50.0, 'roiPct': -7.5, 'profitUnits': -0.3, 'avgOdds': 2.0}
    assert rec['bySport'] == {
        'football': {'n': 3, 'won': 1, 'hitPct': 33.3, 'roiPct': -33.3, 'profitUnits': -1.0, 'avgOdds': 2.1},
        'tennis': {'n': 1, 'won': 1, 'hitPct': 100.0, 'roiPct': 70.0, 'profitUnits': 0.7, 'avgOdds': 1.7}}
    assert rec['byBand'] == {
        '60-70': {'n': 2, 'won': 1, 'hitPct': 50.0, 'roiPct': 0.0, 'profitUnits': 0.0, 'avgOdds': 1.9},
        '70-80': {'n': 1, 'won': 0, 'hitPct': 0.0, 'roiPct': -100.0, 'profitUnits': -1.0, 'avgOdds': 2.5},
        '80-90': {'n': 1, 'won': 1, 'hitPct': 100.0, 'roiPct': 70.0, 'profitUnits': 0.7, 'avgOdds': 1.7},
        '90+': none}


def _merged_ids(res):
    data = json.load(open(ff.fan_path(DAY, res), encoding='utf-8'))
    return [p['id'] for p in data['sports']['football']['picks']]


def _run(res):
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    ff.merge(DAY, 'football', blk, res, now=NOW)
    return blk


def test_merge_keeps_pending_pick_the_new_run_did_not_evaluate(tmp_path):
    res = write_rows(tmp_path, 'football', [row('A', 'B', 72, 20), row('C', 'D', 70, 10)])
    _run(res)
    lost_vote = row('A', 'B', 72, 20)
    lost_vote['sofascore'] = {'found': False}
    write_rows(tmp_path, 'football', [lost_vote, row('C', 'D', 70, 10)])
    blk = _run(res)
    assert f'football|{DAY}|A|B' not in blk['evaluated']
    assert sorted(_merged_ids(res)) == [f'football|{DAY}|A|B', f'football|{DAY}|C|D']


def test_merge_drops_re_evaluated_pick_below_the_odds_limit(tmp_path):
    res = write_rows(tmp_path, 'football', [row('A', 'B', 72, 20), row('C', 'D', 70, 10)])
    _run(res)
    write_rows(tmp_path, 'football', [row('A', 'B', 72, 20, odds=(1.4, 4, 6)), row('C', 'D', 70, 10)])
    _run(res)
    assert _merged_ids(res) == [f'football|{DAY}|C|D']


def test_merge_without_evaluated_key_behaves_as_before(tmp_path):
    res = write_rows(tmp_path, 'football', [row('A', 'B', 72, 20), row('C', 'D', 70, 10)])
    _run(res)
    lost_vote = row('A', 'B', 72, 20)
    lost_vote['sofascore'] = {'found': False}
    write_rows(tmp_path, 'football', [lost_vote, row('C', 'D', 70, 10)])
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    del blk['evaluated']
    ff.merge(DAY, 'football', blk, res, now=NOW)
    assert _merged_ids(res) == [f'football|{DAY}|C|D']


def test_upcoming_sorted_by_kickoff_then_fan_vote_and_started_flagged(tmp_path):
    res = tmp_path / 'results'
    res.mkdir()
    picks = [
        _fp('football', 'A', 'B', '60-70', 2.0, kickoff='2026-10-21T20:00:00Z', fan=65),
        _fp('football', 'C', 'D', '70-80', 2.0, kickoff='2026-10-21T18:00:00Z', fan=70, votes=300),
        _fp('football', 'E', 'F', '80-90', 2.0, kickoff='2026-10-21T18:00:00Z', fan=85),
        _fp('football', 'G', 'H', '70-80', 2.0, kickoff='2026-10-21T18:00:00Z', fan=70, votes=900),
        _fp('football', 'I', 'J', '90+', 2.0, kickoff=None, fan=95),
        _fp('football', 'K', 'L', '90+', 2.0, kickoff='2026-10-21T05:00:00Z', fan=92),   # started
        _fp('football', 'M', 'N', '60-70', 2.0, kickoff='2026-10-21T06:00:00Z', fan=62),  # ko == now
        _fp('football', 'O', 'P', '60-70', 2.0, kickoff='2026-10-21T21:00:00Z', result={'status': 'void'}),
        _fp('football', 'Q', 'R', '60-70', 2.0, kickoff='2026-10-21T22:00:00Z', result={'status': 'won'}),
    ]
    (res / f'fanvote_{DAY}.json').write_text(json.dumps({'sports': {'football': {'picks': picks}}}),
                                             encoding='utf-8')
    for sub in (True, False):
        blk = fan_feed.load_fan(str(res), is_subscriber=sub, remote=False, now=NOW)['days'][0]['sports']['football']
        up = [p['id'].split('|')[2] for p in blk['picks'] if not p['started']]
        assert up == ['E', 'G', 'C', 'A', 'I']
        assert blk['upcoming'] == 5
        started = {p['id'].split('|')[2] for p in blk['picks'] if p['started']}
        assert started == {'K', 'M', 'O', 'Q'}


def test_every_qualifying_pick_appears_on_the_board(tmp_path):
    res = write_rows(tmp_path, 'football', [
        row('A', 'B', 72, 20, time='12:00'), row('C', 'D', 80, 10, time='09:00'),
        row('E', 'F', 15, 75, odds=(5, 4, 2.4), time='21:00'), row('G', 'H', 70, 20, time='12:00'),
        row('X', 'Y', 80, 10, odds=(1.4, 4, 6)), row('V', 'W', 90, 5, votes=20)])
    blk = _run(res)
    built = {p['id'] for p in blk['picks']}
    assert len(built) == 4
    for sub in (True, False):
        board = fan_feed.load_fan(res, is_subscriber=sub, remote=False, now=NOW)
        ids = {p['id'] for p in board['days'][0]['sports']['football']['picks'] if not p['started']}
        assert ids == built


def test_football_69_fails_70_qualifies(tmp_path):
    assert fl.select('football', 69.9, 500) is False
    assert fl.select('football', 70.0, 500) is True
    res = write_rows(tmp_path, 'football', [row('A', 'B', 69, 20), row('C', 'D', 70, 20)])
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    assert [p['team'] for p in blk['picks']] == ['C']


def test_last_match_from_dated_form(tmp_path):
    r1 = row('A', 'B', 80, 10)
    r1['form'].update(homeDated=[{'date': '05.11.26', 'result': 'W', 'score': '2-1', 'event': 'L'}],
                      awayDated=[{'date': '04.11.26', 'result': 'L', 'score': '0-3'}])
    res = write_rows(tmp_path, 'football', [r1, row('C', 'D', 80, 10)])
    blk = ff.build('football', DAY, res, use_best_price=False, now=NOW, log=lambda *_: None)
    by = {p['team']: p for p in blk['picks']}
    assert by['A']['lastMatch'] == {
        'team': {'date': '05.11.26', 'result': 'W', 'score': '2-1', 'event': 'L'},
        'opponent': {'date': '04.11.26', 'result': 'L', 'score': '0-3', 'event': ''}}
    assert by['C']['lastMatch'] == {'team': None, 'opponent': None}
