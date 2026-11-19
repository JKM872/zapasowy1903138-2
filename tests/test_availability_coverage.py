import json

from tools import availability_coverage as cov


def test_coverage_counts_known_vs_unknown_per_sport(tmp_path):
    day = '2026-11-19'
    rows = [{'homeTeam': 'A', 'awayTeam': 'B', 'qualifies': True, 'league': 'NBA', 'scoring': {'pick': '1'}},
            {'homeTeam': 'C', 'awayTeam': 'D', 'qualifies': True, 'league': 'NBA', 'scoring': {'pick': '2'}},
            {'homeTeam': 'E', 'awayTeam': 'F', 'qualifies': True, 'league': 'LT2', 'scoring': {'pick': '1'}},
            {'homeTeam': 'G', 'awayTeam': 'H', 'qualifies': False, 'league': 'NBA'}]
    (tmp_path / f'matches_{day}_basketball_forebet.json').write_text(json.dumps({'matches': rows}), encoding='utf-8')
    store = {'basketball|A|B': {'source': 'sofascore', 'side': 'home', 'home': [], 'away': [], 'signals': []},
             'basketball|C|D': {'source': None, 'unknown': True, 'side': 'away'}}
    q = cov.qualifying_rows(day, str(tmp_path))
    assert len(q) == 3
    c = cov.coverage(q, store)['basketball']
    assert (c['rows'], c['records'], c['known'], c['unknown']) == (3, 2, 1, 2)
    assert c['status']['no_key_absence'] == 1
    txt = cov.render(day, {'basketball': c}, q)
    assert '| basketball | 3 | 2 | 1 | 2 | 33% |' in txt
    assert '| basketball | NBA | 2 | 1 (50%) | sofascore, rotowire_nba |' in txt
