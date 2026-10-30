"""Fan Favourites section of the main e-mail (email_notifier)."""
import pytest

import email_notifier as en
import fan_limits


def _m(home_team='A', away_team='B', sport='football', home=65, away=35, votes=200,
       home_odds=2.2, away_odds=1.7, **kw):
    d = {'home_team': home_team, 'away_team': away_team, 'sport': sport,
         'sofascore': {'home': home, 'away': away, 'votes': votes},
         'home_odds': home_odds, 'away_odds': away_odds, 'match_time': '30.10.2026 18:30'}
    d.update(kw)
    return d


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ('FANVOTE_EMAIL_MIN_PCT', 'FANVOTE_EMAIL_MIN_PCT_FOOTBALL', 'FANVOTE_EMAIL_MIN_VOTES'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(fan_limits, 'passes_limit', lambda sport, odds, side: odds >= 2.0)


def test_football_60_others_70():
    rows = en.select_fan_favourites([
        _m('F', sport='football', home=62, away=38),
        _m('H', sport='hockey', home=65, away=35),
        _m('T', sport='tennis', home=72, away=28),
    ])
    assert [r['team'] for r in rows] == ['T', 'F']


def test_min_votes_and_missing_data():
    rows = en.select_fan_favourites([
        _m('Few', votes=50),
        {'home_team': 'X', 'away_team': 'Y', 'sport': 'football', 'home_odds': 2.5},
        _m('Ok', votes=100),
    ])
    assert [r['team'] for r in rows] == ['Ok']


def test_odds_limit_and_missing_odds():
    rows = en.select_fan_favourites([
        _m('Low', home_odds=1.5),
        _m('None', home_odds=None),
        _m('Good', home_odds=2.4),
    ])
    assert [r['team'] for r in rows] == ['Good']


def test_away_side_and_sorted_desc_with_metrics():
    rows = en.select_fan_favourites([
        _m('H1', home=61, away=39),
        _m('H2', 'Aw', home=20, away=80, away_odds=2.5, home_odds=5.0),
    ])
    assert [r['team'] for r in rows] == ['Aw', 'H1']
    top = rows[0]
    assert top['side'] == 'away' and top['odds'] == 2.5
    assert top['implied_pct'] == pytest.approx(40.0)
    assert top['edge_pct'] == pytest.approx(40.0)
    assert top['same_as_focus'] is False


def test_env_overrides(monkeypatch):
    monkeypatch.setenv('FANVOTE_EMAIL_MIN_PCT_FOOTBALL', '75')
    monkeypatch.setenv('FANVOTE_EMAIL_MIN_PCT', '50')
    monkeypatch.setenv('FANVOTE_EMAIL_MIN_VOTES', '10')
    rows = en.select_fan_favourites([
        _m('F', home=70, away=30, votes=20),
        _m('V', sport='volleyball', home=55, away=45, votes=20),
    ])
    assert [r['team'] for r in rows] == ['V']


def test_bad_env_falls_back(monkeypatch):
    monkeypatch.setenv('FANVOTE_EMAIL_MIN_PCT', 'abc')
    assert en.fan_favourites_thresholds()['min_pct'] == fan_limits.FAN_MIN_DEFAULT


def test_render_section():
    html = en._render_fan_favourites_section([_m('Lech', home=78, away=22, votes=178)])
    assert 'Fan Favourites (1)' in html and '78%' in html and '178' in html
    assert '2.20' in html and '18:30' in html
    assert en._render_fan_favourites_section([_m(home=50, away=50)]) == ''
