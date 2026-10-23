"""Published TOP record: settlement, summary and the server-side paywall."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import top_feed as t


def setup(tmp_path, picks, settled=None, store=None):
    res = tmp_path / 'results'
    res.mkdir()
    (res / 'top_2026-10-21.json').write_text(json.dumps(picks), encoding='utf-8')
    if settled is not None:
        (res / 'forebet_settled.json').write_text(json.dumps(settled), encoding='utf-8')
    sp = tmp_path / 'store.json'
    sp.write_text(json.dumps(store or {}), encoding='utf-8')
    t._store_cache.update(mtime=None, index={}, path=None)
    return str(res), str(sp)


def pick(match, team, odds=2.0, sport='hockey'):
    return {'match': match, 'pick': team, 'odds': odds, 'sport': sport,
            'time': '19:00', 'grade': 'A', 'league': 'L'}


def test_a_winning_pick_is_settled_from_the_audit(tmp_path):
    res, sp = setup(tmp_path, [pick('Kladno vs Pardubice', 'Pardubice', 2.0)],
                    settled={'2026-10-21|hockey|Kladno|Pardubice':
                             {'status': 'settled', 'winner': 'away', 'score': '1-3'}})
    d = t.load_top(res, sp, is_subscriber=True)
    p = d['days'][0]['picks'][0]
    assert p['result'] == {'status': 'won', 'score': '1-3'}
    assert d['summary']['roi'] == 100.0


def test_a_losing_pick(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A')],
                    settled={'2026-10-21|hockey|A|B': {'status': 'settled', 'winner': 'away', 'score': '0-2'}})
    assert t.load_top(res, sp, True)['days'][0]['picks'][0]['result']['status'] == 'lost'


def test_reversed_orientation_in_the_store_is_handled(tmp_path):
    store = {'u': {'status': 'finished', 'winner': 'home', 'date': '2026-10-21',
                   'home_team': 'B', 'away_team': 'A', 'score_home': 3, 'score_away': 1}}
    res, sp = setup(tmp_path, [pick('A vs B', 'B')], store=store)
    r = t.load_top(res, sp, True)['days'][0]['picks'][0]['result']
    assert r == {'status': 'won', 'score': '1-3'}


def test_unsettled_picks_are_hidden_from_non_subscribers(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A'), pick('C vs D', 'C')],
                    settled={'2026-10-21|hockey|A|B': {'status': 'settled', 'winner': 'home', 'score': '2-0'}})
    day = t.load_top(res, sp, is_subscriber=False)['days'][0]
    assert [p['match'] for p in day['picks']] == ['A vs B'], 'settled stays public'
    assert day['locked'] == 1


def test_subscribers_see_everything(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A'), pick('C vs D', 'C')])
    day = t.load_top(res, sp, is_subscriber=True)['days'][0]
    assert len(day['picks']) == 2 and day['locked'] == 0


def test_pending_picks_do_not_count_toward_roi(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A'), pick('C vs D', 'C')],
                    settled={'2026-10-21|hockey|A|B': {'status': 'settled', 'winner': 'home', 'score': '2-0'}})
    s = t.load_top(res, sp, True)['summary']
    assert s['settled'] == 1 and s['pending'] == 1 and s['hitRate'] == 100.0


def test_no_files_is_not_an_error(tmp_path):
    (tmp_path / 'r').mkdir()
    d = t.load_top(str(tmp_path / 'r'), str(tmp_path / 'none.json'))
    assert d['days'] == [] and d['summary']['settled'] == 0
