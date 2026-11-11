from tools import match_details as md

EV = {'event': {'tournament': {'name': 'Knoxville, USA', 'category': {'name': 'Challenger'}},
                'roundInfo': {'round': 6, 'name': 'Round of 32'}, 'groundType': 'Hardcourt indoor',
                'homeTeam': {'id': 1}, 'awayTeam': {'id': 2}}}


def _last(team_id):
    return {'events': [
        {'status': {'type': 'finished'}, 'startTimestamp': 1794356100, 'winnerCode': 1,
         'homeTeam': {'id': team_id, 'name': 'Me'}, 'awayTeam': {'id': 9, 'name': 'Rival'},
         'homeScore': {'current': 2, 'period1': 1, 'period2': 6, 'period3': 6},
         'awayScore': {'current': 1, 'period1': 6, 'period2': 4, 'period3': 4},
         'time': {'period1': 1324, 'period2': 2380, 'period3': 2433, 'currentPeriodStartTimestamp': 5},
         'roundInfo': {'name': 'Round of 64'}, 'tournament': {'name': 'Knoxville, USA'}},
        {'status': {'type': 'notstarted'}, 'homeTeam': {'id': team_id}, 'awayTeam': {'id': 8}},
    ]}


def fake_get(url):
    if url.endswith('/event/77'):
        return EV
    return _last(int(url.split('/team/')[1].split('/')[0]))


def test_details_tennis():
    d = md.details(77, 'tennis', 'away', get=fake_get)
    assert d['round'] == 'Round of 32' and d['tournament'] == 'Knoxville, USA'
    assert d['surface'] == 'Hardcourt indoor' and d['category'] == 'Challenger'
    m = d['team'][0]
    assert len(d['team']) == 1 and m['opponent'] == 'Rival' and m['venue'] == 'H'
    assert m['result'] == 'W' and m['score'] == '2-1 (1-6 6-4 6-4)'
    assert m['durationMin'] == 102 and m['date'] == '2026-11-11'


def test_event_id_from_url():
    assert md.event_id({'sofascoreUrl': 'https://www.sofascore.com/tennis/match/17534657'}) == 17534657
    assert md.event_id({'eventId': 5}) == 5 and md.event_id({}) is None


def test_football_no_duration():
    ev = _last(1)['events'][0]
    assert md.score_text(ev, 'football', False) == '1-2'
    assert 'durationMin' not in md.last_matches(1, 'football', get=fake_get)[0]
