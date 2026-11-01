"""SofaScore event check: the same game is accepted, another game is rejected (F-3.5).

Fixture ``tests/fixtures/sofascore_wrong_events.json``: the 84 Fan Votes that
forebet_pipeline discarded as 'zly_mecz' on 2026-10-28..31 (Forebet row vs the
SofaScore event it had been matched to), labelled A = same game, B = another game,
? = cannot tell, plus the TOP pick 2026-10-21 'Nuwaidrad vs Al Ittihad' that carried
the event 'Nacional vs Aguada' (B).
"""
import importlib
import json
import os
import sys
import types
from datetime import date, timedelta

import pytest

import sofascore_scraper

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'sofascore_wrong_events.json')


def _import_forebet_pipeline():
    """forebet_pipeline -> forebet_scraper imports undetected_chromedriver, which
    needs distutils (gone in Python 3.12+; CI runs 3.10/3.11). The name check opens no
    browser, so without distutils the module is imported with a stand-in, and the
    modules that saw the stand-in leave sys.modules again (other tests import the
    real thing as before)."""
    try:
        return importlib.import_module('forebet_pipeline')
    except ModuleNotFoundError as e:
        if e.name != 'distutils':
            raise
    stub = types.ModuleType('undetected_chromedriver')
    stub.Chrome = type('Chrome', (), {'quit': lambda self: None})
    sys.modules['undetected_chromedriver'] = stub
    try:
        return importlib.import_module('forebet_pipeline')
    finally:
        for name in ('undetected_chromedriver', 'cloudflare_bypass', 'forebet_scraper',
                     'forebet_listing', 'forebet_pipeline'):
            sys.modules.pop(name, None)


fp = _import_forebet_pipeline()
with open(FIXTURE, encoding='utf-8') as fh:
    ROWS = json.load(fh)['rows']


def _event(monkeypatch, home, away, start_date):
    """SofaScore event/<id> answers with these names and UTC start date."""
    monkeypatch.setattr(sofascore_scraper, 'get_event_team_ids', lambda eid: {
        'home_team_id': 1, 'away_team_id': 2, 'home_team': home, 'away_team': away,
        'start_timestamp': None, 'start_date': start_date})


def _verify(monkeypatch, r):
    _event(monkeypatch, r['ssHome'], r['ssAway'], r['ssDate'])
    return fp._verify_sofascore_event(1, r['home'], r['away'], date_str=r['day'])


def test_fixture_counts():
    labels = [r['label'] for r in ROWS]
    assert (labels.count('A'), labels.count('B'), labels.count('?')) == (54, 26, 5)


def test_no_other_game_is_accepted(monkeypatch):
    wrong = [r for r in ROWS if r['label'] == 'B']
    accepted = [f"{r['home']} vs {r['away']} -> {r['ssHome']} vs {r['ssAway']}"
                for r in wrong if _verify(monkeypatch, r) is not None]
    assert accepted == []
    # Names alone already reject them (the date check is not what saves us).
    assert all(fp.sofascore_names_match(r['home'], r['away'], r['ssHome'], r['ssAway'])[0]
               is None for r in wrong)


def test_same_game_is_accepted(monkeypatch):
    same = [r for r in ROWS if r['label'] == 'A']
    verdicts = [_verify(monkeypatch, r) for r in same]
    accepted = sum(v is not None for v in verdicts)
    assert accepted >= 35, f'{accepted} of {len(same)} same-game events accepted'
    assert {v for v in verdicts if v} == {'direct'}     # every one has our side order


def test_two_days_off_is_rejected_one_day_is_not(monkeypatch):
    day = date(2026, 10, 28)
    for off, want in ((0, 'direct'), (1, 'direct'), (-1, 'direct'), (2, None), (-2, None)):
        _event(monkeypatch, 'Gjøvik Mammuts', 'Comet', (day + timedelta(days=off)).isoformat())
        got = fp._verify_sofascore_event(1, 'Gjovik', 'Comet', date_str=day.isoformat())
        assert got == want, off


def test_reversed_sides_return_reversed(monkeypatch):
    # Run 2026-09-13: SofaScore lists this women's game with the sides swapped.
    _event(monkeypatch, 'SK Brann Kvinner', 'Lyn', '2026-09-13')
    assert fp._verify_sofascore_event(1, 'Lyn W', 'Brann W', date_str='2026-09-13') == 'reversed'
    assert fp.sofascore_names_match('Gjovik', 'Comet', 'Comet', 'Gjøvik Mammuts')[0] == 'reversed'


def _vote(eid=16341578):
    return {'sofascore_found': True, 'sofascore_home_win_prob': 70,
            'sofascore_away_win_prob': 30, 'sofascore_draw_win_prob': None,
            'sofascore_total_votes': 412,
            'sofascore_url': f'https://www.sofascore.com/ice-hockey/match/{eid}'}


def test_orient_fan_vote_rejects_a_rematch_a_week_later(monkeypatch):
    _event(monkeypatch, 'Gjøvik Mammuts', 'Comet', '2026-11-04')
    v = _vote()
    fp._orient_fan_vote(v, 'Gjovik', 'Comet', '2026-10-28')
    assert v['sofascore_found'] is False and v['sofascore_orientation'] == 'mismatch'
    assert v['sofascore_skip_reason'] == 'zly_mecz' and v['sofascore_home_win_prob'] is None
    # Same day: kept; sides swapped on SofaScore -> percentages swapped to our sides.
    _event(monkeypatch, 'Comet', 'Gjøvik Mammuts', '2026-10-28')
    v = _vote()
    fp._orient_fan_vote(v, 'Gjovik', 'Comet', '2026-10-28')
    assert v['sofascore_orientation'] == 'reversed'
    assert (v['sofascore_home_win_prob'], v['sofascore_away_win_prob']) == (30, 70)


@pytest.mark.parametrize('ours, theirs, want', [
    # Same game, team level written differently (verified events 2026-10-26..11-01).
    (('Frosinone U19', 'Entella U19'), ('Frosinone U20', 'Virtus Entella U20'), 'direct'),
    (('Blackburn U23s', 'Southampton U23s'), ('Blackburn U21', 'Southampton U21'), 'direct'),
    (('Slovan Liberec B', 'FK Caslav'), ('Slovan Liberec U21', 'FK Čáslav'), 'direct'),
    (('Luckenwalde', 'Hertha BSC II'), ('FSV Luckenwalde', 'Hertha BSC II U23'), 'direct'),
    (('Real Oviedo B', 'UD Llanera'), ('Real Oviedo Vetusta', 'UD Llanera'), 'direct'),
    (('Dinamo Minsk II', 'Shakhtyor Soligorsk'), ('Dinamo-2 Minsk', 'FC Soligorsk'), 'direct'),
    (('AZ W', 'PEC Zwolle W'), ('AZ Alkmaar', 'PEC Zwolle Vrouwen'), 'direct'),
    (('A. Li', 'E. Alexandrova'), ('Ann Li', 'Ekaterina Alexandrova'), 'direct'),
    (('Istanbul GSK', 'Istanbul BB'), ('Istanbul Genclik Spor', 'Istanbul BB SK'), 'direct'),
    (('Al Ta\u2019i', 'Jeddah Club'), ('Al Tai', 'Jeddah'), 'direct'),
    # Another game the old check accepted: senior vs youth / reserves / women.
    (('Levadiakos', 'Aris Salonica'), ('Levadiakos U19', 'Aris U19'), None),
    (('Saint Quentin U21', 'Strasbourg U21'), ('Saint-Quentin', 'SIG Strasbourg'), None),
    (('Brno U19', 'Slavia Prague U19'), ('Lokomotiva Brno H.H.', 'SK Slavia Praha'), None),
    (('Zhetysu W', 'Kuanysh W'), ('Kuanysh 2', 'Zhetysu-2'), None),
    (('Arsenal', 'Chelsea'), ('Arsenal W', 'Chelsea W'), None),
])
def test_team_level_markers(ours, theirs, want):
    assert fp.sofascore_names_match(*ours, *theirs)[0] == want
