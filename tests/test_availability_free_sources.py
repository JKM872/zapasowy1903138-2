from tools import availability_agent as a, availability_sources as src

ESPN = {'injuries': [
    {'displayName': 'Atlanta Hawks', 'injuries': [
        {'status': 'Out', 'shortComment': 'Landale (hip) out', 'date': '2026-11-19T22:07Z',
         'athlete': {'displayName': 'Jock Landale', 'position': {'abbreviation': 'C'}}},
        {'status': 'Day-To-Day', 'athlete': {'displayName': 'Trae Young'}},
        {'status': 'Probable', 'athlete': {'displayName': 'Fine Guy'}}]},
    {'displayName': 'Boston Bruins', 'injuries': [
        {'status': 'Injured Reserve', 'athlete': {'displayName': 'A B'}},
        {'status': '10-Day IL', 'athlete': {'displayName': 'C D'}}]},
    {'displayName': 'Empty', 'injuries': []},
]}


def test_parse_espn_injuries():
    t = src.parse_espn_injuries(ESPN, 'u')
    hawks = t['atlanta hawks']
    assert [(r['name'], r['status']) for r in hawks] == [('Jock Landale', 'out'), ('Trae Young', 'doubtful')]
    assert hawks[0]['source'] == 'espn' and hawks[0]['position'] == 'C' and 'hip' in hawks[0]['reason']
    assert [r['status'] for r in t['boston bruins']] == ['out', 'out']
    assert 'empty' not in t
    assert src.parse_espn_injuries(None) == {}


def test_espn_registered_and_matched(monkeypatch):
    assert 'espn_nba' in src.sources_for('basketball', 'NBA')
    assert 'espn_nhl' in src.sources_for('hockey', 'NHL')
    monkeypatch.setitem(src._parsed, 'espn_basketball/nba', src.parse_espn_injuries(ESPN))
    for k in [k for k in src._parsed if k.startswith('rotowire')]:
        monkeypatch.setitem(src._parsed, k, {})
    res = src.rows_for_match('basketball', 'NBA', None, 'Hawks', 'Celtics', '2026-11-20')
    assert 'espn_nba' in res['sources'] and res['home'][0]['name'] == 'Jock Landale' and res['away'] == []


def _ev(desc, wc, typ='finished'):
    return {'status': {'description': desc, 'type': typ}, 'winnerCode': wc,
            'homeTeam': {'name': 'Home P', 'id': 1}, 'awayTeam': {'name': 'Away P', 'id': 2}}


def test_tennis_walkover_and_orientation():
    r = a.parse_tennis_status(_ev('Walkover', 1))
    assert r['away'][0]['name'] == 'Away P' and r['away'][0]['status'] == 'out' and r['home'] == []
    r = a.parse_tennis_status(_ev('Walkover', 1), 'reversed')
    assert r['home'][0]['name'] == 'Away P' and r['away'] == []
    assert a.parse_tennis_status(_ev('Retired', 2))['home'][0]['reason'] == 'retired'
    assert a.parse_tennis_status(_ev('Canceled', None, 'canceled')) is None
    assert a.parse_tennis_status(_ev('Ended', 1)) is None
    assert a.parse_tennis_status(_ev('Not started', None, 'notstarted')) is None


def test_extra_star_row_gives_signal():
    rec = {'side': 'home', 'sport': 'tennis', 'extra': {'home': [
        {'name': 'Home P', 'importance': 'star', 'status': 'out', 'reason': 'walkover', 'source': 'sofascore_status'}],
        'away': []}}
    assert a.status_of(rec, 'home') == 'star_out'
    assert a.status_of(rec, 'away') == 'no_key_absence'
