import re

import pytest

import email_notifier as en
from tools import availability_agent as av

DAY = '2026-11-19'


def _m(home, away, pick='1', grade='B'):
    return {'home_team': home, 'away_team': away, 'sport': 'football', 'league': 'Premier League',
            'match_time': f'{DAY} 20:00', 'match_date': DAY, 'home_odds': 1.8, 'away_odds': 4.2,
            'scoring_pick': pick, 'prediction_grade': grade, 'qualifies': True,
            'focus_team': 'home' if pick == '1' else 'away'}


STORE = {
    'football|Arsenal|Leeds': {
        'checkedAt': f'{DAY}T10:00:00+00:00', 'source': 'sofascore', 'confirmed': False, 'side': 'home',
        'board': 'ok', 'top_block': False,
        'home': [{'id': 7, 'name': 'B. Saka', 'importance': 'star', 'status': 'out', 'reason': 'hamstring'}],
        'away': [],
        'keyPlayers': {'home': [{'id': 7, 'name': 'Bukayo Saka', 'share': 0.32, 'avg': 0.8, 'last': 1,
                                 'unit': 'G+A', 'goalie': False}]},
    },
    'football|Chelsea|Fulham': {'checkedAt': f'{DAY}T10:00:00+00:00', 'source': None, 'confirmed': False,
                                'side': 'home', 'board': 'ok', 'top_block': False, 'unknown': True},
}


@pytest.fixture
def store(monkeypatch):
    en._AVAIL_CACHE.clear()
    data = {}
    monkeypatch.setattr(av, 'load', lambda day: data)
    yield data
    en._AVAIL_CACHE.clear()


def _cards(html):
    return re.findall(r'🏠 (\w+) <span', html)


def test_badge_and_key_player_line_with_availability_file(store):
    store.update(STORE)
    rows = [_m('Arsenal', 'Leeds'), _m('Chelsea', 'Fulham')]
    html = en.create_html_email(rows, DAY, forebet_layout=True)
    assert 'Dostępność: Gwiazda nie gra: Bukayo Saka (32% goli i asyst)' in html
    assert 'Bukayo Saka (avg 0.8, last 1 G+A): OUT – sofascore' in html
    assert 'Dostępność: brak danych' in html          # unknown record


def test_without_file_same_matches_and_brak_danych(store):
    rows = [_m('Arsenal', 'Leeds'), _m('Chelsea', 'Fulham')]
    without = en.create_html_email(rows, DAY, forebet_layout=True)
    assert without.count('Dostępność: brak danych') == 2
    store.update(STORE)
    en._AVAIL_CACHE.clear()
    with_ = en.create_html_email(rows, DAY, forebet_layout=True)
    assert _cards(without) == _cards(with_) == ['Arsenal', 'Chelsea']


def test_other_mails_sharing_the_renderer_get_no_badge_unless_asked(store):
    store.update(STORE)
    rows = [_m('Arsenal', 'Leeds')]
    assert 'Dostępność' not in en.create_html_email(rows, DAY)
    assert 'Gwiazda nie gra' in en.create_html_email(rows, DAY, availability=True)


def test_unknown_record_changes_no_grade(store):
    store.update(STORE)
    rows = [_m('Chelsea', 'Fulham', grade='A')]
    en.create_html_email(rows, DAY, forebet_layout=True)
    assert rows[0]['prediction_grade'] == 'A'
    assert av.apply_grade('A', STORE['football|Chelsea|Fulham']['board']) == 'A'


def test_renderer_error_never_breaks_the_mail(store, monkeypatch):
    monkeypatch.setattr(av, 'badge_pl', lambda *a, **k: 1 / 0)
    html = en.create_html_email([_m('Arsenal', 'Leeds')], DAY, forebet_layout=True)
    assert 'Arsenal' in html and 'Dostępność' not in html
