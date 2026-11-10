import h2h_summary as hs
from tools.top_picks import h2h_texts

ROWS = [
    {'date': '12.04.26', 'home': 'Arsenal', 'away': 'Chelsea', 'score': '2 - 1'},
    {'date': '01.10.25', 'home': 'Chelsea', 'away': 'Arsenal', 'score': '0 - 3'},
    {'date': '05.03.25', 'home': 'Arsenal', 'away': 'Chelsea', 'score': '1 - 1'},
    {'date': '10.10.24', 'home': 'Chelsea FC', 'away': 'Arsenal', 'score': '2 - 0'},
    {'date': '01.01.24', 'home': 'Arsenal', 'away': 'Chelsea', 'score': '4:0'},
]


def test_summarize_last_and_edge():
    s = hs.summarize(ROWS, 'Arsenal', 'Chelsea')
    assert s['last'] == {'date': '2026-04-12', 'score': '2-1', 'winner': 'Arsenal',
                         'home': 'Arsenal', 'away': 'Chelsea'}
    assert s['edge']['team'] == 'Arsenal' and s['edge']['record'] == '3-1-1'
    assert len(s['meetings']) == 5


def test_format_line_and_perspective():
    s = hs.summarize(ROWS, 'Arsenal', 'Chelsea')
    assert hs.format_line(s, 'Arsenal', 'Chelsea') == \
        'H2H: Arsenal 3-1-1 (last: 2026-04-12 Arsenal 2-1 Chelsea)'
    assert hs.format_line(s, 'Arsenal', 'Chelsea', 'Chelsea').startswith('H2H: Chelsea 1-1-3')


def test_missing_is_neutral():
    assert hs.format_line(hs.summarize([], 'A', 'B'), 'A', 'B') == hs.NO_H2H
    assert h2h_texts({'homeTeam': 'A', 'awayTeam': 'B', 'h2h': {}}, 'A')[0] == hs.NO_H2H


def test_top_h2h_integer_not_weighted_float():
    m = {'homeTeam': 'Arsenal', 'awayTeam': 'Chelsea',
         'h2h': {'total': 3, 'homeWins': 3, 'awayWins': 0, 'homeWinsEff': 3.0,
                 'effectiveTotal': 3.0, 'lastDate': '12.04.26', 'lastScore': '2 - 1'}}
    line, last = h2h_texts(m, 'Arsenal')
    assert line == 'H2H: Arsenal 3-0-0 (last: 2026-04-12 2-1)'
    assert '3.0' not in line and last == '2026-04-12 2-1'
