import json
import os

import odds_movement as om
from tools import availability_agent as aa


def test_compute_direction_and_pct():
    mv = om.compute(2.0, 1.8, since='t', source='x')
    assert mv['changePct'] == -10.0 and mv['direction'] == 'down'
    assert om.compute(2.0, 2.2)['direction'] == 'up'
    assert om.compute(2.0, 2.02)['direction'] == 'flat'
    assert om.compute(None, 2.0) is None and om.compute(1.0, 2.0) is None


def test_line_wording():
    move = {'pick': om.compute(1.85, 1.72), 'opponent': om.compute(2.0, 2.3)}
    txt = om.line(move)
    assert 'market agrees' in txt and '▼7%' in txt and 'opponent ▲15%' in txt
    assert 'market against' in om.line({'pick': om.compute(1.5, 1.7), 'opponent': None})
    assert 'against our pick' in om.line({'pick': None, 'opponent': om.compute(2.0, 1.6)})


def _drop_file(root, day, events):
    os.makedirs(os.path.join(root, 'outputs'), exist_ok=True)
    with open(os.path.join(root, 'outputs', f'oddssafari_dropping_{day}_football.json'), 'w') as fh:
        json.dump({'meta': {'generated_at': f'{day}T07:00:00'}, 'events': events}, fh)


def test_for_pick_swapped_and_live(tmp_path):
    root = str(tmp_path)
    _drop_file(root, '2026-11-14', [
        {'sport': 'football', 'home_team': 'Away FC', 'away_team': 'Home United', 'outcome': '2',
         'open_odds': 2.0, 'current_odds': 1.7, 'event_date': '14/11'},
        {'sport': 'football', 'home_team': 'Other', 'away_team': 'Team', 'outcome': '1',
         'open_odds': 2.0, 'current_odds': 1.7, 'event_date': '15/11'},
    ])
    ix = om.build_index('2026-11-14', root)
    mv = om.for_pick(ix, 'football', 'Home United', 'Away', 'home')
    assert mv['pick']['direction'] == 'down' and mv['stance'] == 'with'
    assert om.for_pick(ix, 'football', 'Other', 'Team', 'home') is None  # other day filtered
    live = {'checks': [{'best': 1.9, 'at': 'a'}, {'best': 2.1, 'at': 'b'}]}
    ix['live'] = {'hockey|A vs B': live}
    mv = om.for_pick(ix, 'hockey', 'A', 'B', 'home')
    assert mv['stance'] == 'against' and mv['pick']['source'] == 'top_live'


def test_compare_dropping():
    events = [{'sport': 'football', 'homeTeam': 'A', 'awayTeam': 'B', 'outcome': '1'},
              {'sport': 'football', 'homeTeam': 'C', 'awayTeam': 'D', 'outcome': '1'},
              {'sport': 'football', 'homeTeam': 'E', 'awayTeam': 'F', 'outcome': '2'}]
    picks = [{'sport': 'football', 'home': 'A', 'away': 'B', 'side': 'home', 'source': 'TOP'},
             {'sport': 'football', 'home': 'D', 'away': 'C', 'side': 'home', 'source': 'Fan'}]
    rel = [r['relation'] for r in om.compare_dropping(events, picks)]
    assert rel == ['with', 'against', 'no_pick']


def test_parse_summary():
    assert aa.parse_summary('x {"summary": "Star A out. Weakens home. Third.", "weakens": "yes"} y') \
        == 'Star A out. Weakens home.'
    assert aa.parse_summary('no json') is None
    assert aa.parse_summary('{"summary": ""}') is None


def test_summaries_only_from_sourced_data():
    store = {'k1': {'checkedAt': 't', 'unknown': True, 'source': None},
             'k2': {'checkedAt': 't', 'source': 'sofascore', 'side': 'home',
                    'home': [{'name': 'X', 'importance': 'star', 'status': 'out', 'reason': 'injury'}], 'away': []}}
    calls = []
    keys = [{'key': 'k1', 'm': {}}, {'key': 'k2', 'sport': 'football',
                                    'm': {'homeTeam': 'H', 'awayTeam': 'A'}}]
    chat = lambda p: calls.append(p) or '{"summary": "X is out, which weakens H."}'  # noqa: E731
    n = aa.summarize_news('d', store, keys, chat=chat, log=lambda *_: None)
    assert n == 1 and store['k1']['aiSummary'] == aa.NO_NEWS
    assert store['k2']['aiSummary'].startswith('X is out') and 'X [star, out: injury]' in calls[0]
    assert aa.summarize_news('d', store, keys, chat=chat, log=lambda *_: None) == 0  # cached


def test_team_news_badges():
    rec = {'source': 'sofascore', 'side': 'away', 'confirmed': True,
           'home': [{'name': 'S', 'importance': 'star', 'status': 'out'}],
           'away': [{'name': 'T', 'importance': 'star', 'status': 'out'},
                    {'name': 'U', 'importance': 'star', 'status': 'out'}]}
    tn = aa.team_news(rec)
    assert tn['badgePick'] == '2 stars out' and tn['badgeOpponent'] == '1 star out'
    assert aa.team_news({'unknown': True}) is None
    assert aa.email_line(None) == f'Team news: {aa.NO_NEWS}'
