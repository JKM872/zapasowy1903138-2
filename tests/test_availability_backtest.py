import json

from tools import availability_backtest as bt


def test_aggregate_hit_rate_roi_and_break_even():
    bets = [{'group': 'star_out', 'sport': 'football', 'won': True, 'odds': 2.0},
            {'group': 'star_out', 'sport': 'football', 'won': False, 'odds': 2.0},
            {'group': 'rest', 'sport': 'hockey', 'won': True, 'odds': 1.5}]
    agg = bt.aggregate(bets)
    s = agg['star_out']['football']
    assert (s['n'], s['hits'], s['hit_rate'], s['roi'], s['break_even']) == (2, 1, 0.5, 0.0, 0.5)
    assert agg['rest']['all']['roi'] == 0.5
    txt = bt.render(agg, 1)
    assert '| star_out | football | 2 | 50.0% | +0.0% | 50.0% | too small |' in txt


def test_group_of_maps_statuses():
    assert bt.group_of('star_out') == 'star_out'
    assert bt.group_of('no_key_absence') == 'rest' and bt.group_of('star_doubtful') == 'rest'


def test_collect_joins_rows_records_and_results(tmp_path):
    day = '2026-11-10'
    rows = [{'homeTeam': 'A', 'awayTeam': 'B', 'qualifies': True, 'scoring': {'pick': '1'},
             'odds': {'home': 1.8, 'away': 4.0}},
            {'homeTeam': 'C', 'awayTeam': 'D', 'qualifies': True, 'scoring': {'pick': '2'},
             'odds': {'home': 1.5, 'away': 2.5}}]
    (tmp_path / f'matches_{day}_football_forebet.json').write_text(json.dumps({'matches': rows}))
    (tmp_path / f'availability_{day}.json').write_text(json.dumps({
        'football|A|B': {'source': 'sofascore', 'side': 'home', 'away': [],
                         'home': [{'name': 'S', 'importance': 'star', 'status': 'out'}]}}))
    (tmp_path / 'forebet_settled.json').write_text(json.dumps({
        f'{day}|football|A|B': {'status': 'settled', 'winner': 'away'},
        f'{day}|football|C|D': {'status': 'settled', 'winner': 'away'}}))
    bets = {(b['group'], b['won'], b['odds']) for b in bt.collect(str(tmp_path))}
    assert bets == {('star_out', False, 1.8), ('unknown', True, 2.5)}
