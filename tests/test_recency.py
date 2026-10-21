"""Ochrona przed danymi z poprzedniego sezonu (recency.py i integracje).

Reguły: brak H2H neutralny, H2H ważone wiekiem, forma sezonowa obok formy
ogólnej, flaga early_season, bramka rynkowa stale_model.
"""
import copy
import json
import os
from datetime import date, timedelta

import pytest

import recency
from recency import (GRADE_ORDER, apply_season, effective_h2h, h2h_weight,
                     implied_probs, lower_grade_if_stale, market_gap_pp,
                     parse_ls_date, season_conflict, season_start, season_view)

TODAY = date(2026, 10, 20)


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).strftime('%d.%m.%y')


# ---------------------------------------------------------------------------
# recency.py — czyste funkcje
# ---------------------------------------------------------------------------
class TestParseLsDate:
    def test_formats(self):
        assert parse_ls_date('09.03.16') == date(2016, 3, 9)
        assert parse_ls_date('09.03.2016') == date(2016, 3, 9)
        assert parse_ls_date('09.03.16 18:00') == date(2016, 3, 9)
        assert parse_ls_date(' 09.03.2016. ') == date(2016, 3, 9)

    def test_invalid(self):
        assert parse_ls_date('09.03.') is None
        assert parse_ls_date('31.02.20') is None
        assert parse_ls_date('') is None
        assert parse_ls_date(None) is None
        assert parse_ls_date(123) is None


class TestH2hWeight:
    def test_boundaries(self):
        assert h2h_weight(TODAY - timedelta(days=365), TODAY) == 1.0
        assert h2h_weight(TODAY - timedelta(days=366), TODAY) == 0.5
        assert h2h_weight(TODAY - timedelta(days=730), TODAY) == 0.5
        assert h2h_weight(TODAY - timedelta(days=731), TODAY) == 0.0
        assert h2h_weight(TODAY + timedelta(days=3), TODAY) == 1.0
        assert h2h_weight(None, TODAY) is None


class TestEffectiveH2h:
    def test_guif_drott_all_stale(self):
        row = {'home_team': 'Guif', 'away_team': 'Drott', 'favorite': 'home',
               'h2h_last5': [{'date': '09.03.16', 'home': 'Guif', 'away': 'Drott',
                              'score': '30-25', 'winner': 'home'}]}
        eff = effective_h2h(row, TODAY)
        assert eff['all_stale'] is True
        assert eff['count'] == 0
        assert eff['ignored'] == 1

    def test_half_weight(self):
        row = {'home_team': 'Alpha', 'away_team': 'Bravo', 'favorite': 'home',
               'h2h_last5': [{'date': _d(400), 'home': 'Alpha', 'away': 'Bravo',
                              'winner': 'home'}]}
        eff = effective_h2h(row, TODAY)
        assert eff['count'] == 0.5 and eff['fav_wins'] == 0.5

    def test_undated_gives_none(self):
        row = {'h2h_last5': [{'date': '', 'winner': 'home'},
                             {'date': 'x', 'winner': 'away'}]}
        assert effective_h2h(row, TODAY) is None
        assert effective_h2h({'h2h_last5': []}, TODAY) is None
        assert effective_h2h({'h2h_last5': 'x'}, TODAY) is None

    def test_name_orientation(self):
        # Spotkanie u Drott: gospodarz meczu H2H to dzisiejszy gość.
        row = {'home_team': 'Guif', 'away_team': 'Drott', 'favorite': 'away',
               'h2h_last5': [{'date': _d(30), 'home': 'Drott', 'away': 'Guif',
                              'winner': 'home'}]}
        eff = effective_h2h(row, TODAY)
        assert eff['away_wins'] == 1.0 and eff['home_wins'] == 0
        assert eff['fav_wins'] == 1.0

    def test_fallback_orientation(self):
        row = {'home_team': 'Alpha', 'away_team': 'Beta', 'favorite': 'home',
               'h2h_last5': [{'date': _d(30), 'home': 'Xxxxx', 'away': 'Yyyyy',
                              'winner': 'home'}]}
        eff = effective_h2h(row, TODAY)
        # Zwycięzca spoza obecnych drużyn — spotkanie pominięte (neutralne).
        assert eff['home_wins'] == 0 and eff['away_wins'] == 0 and eff['count'] == 0
        assert eff['unattributed'] == 1 and eff['all_stale'] is False


class TestSeasonStart:
    def _dated(self, ages):
        return [{'date': TODAY - timedelta(days=a), 'result': 'W'} for a in ages]

    def test_gap(self):
        start, method = season_start(self._dated([5, 12, 20, 90, 100]), TODAY)
        assert method == 'gap' and start == TODAY - timedelta(days=20)

    def test_no_gap_recent(self):
        start, method = season_start(self._dated([5, 12, 20, 30, 40]), TODAY)
        assert method == '60d' and start == TODAY - timedelta(days=60)

    def test_no_gap_old_row_excluded(self):
        dated = self._dated([10, 30, 50, 65, 80])
        start, method = season_start(dated, TODAY)
        assert method == '60d'
        raw = [{'date': e['date'].strftime('%d.%m.%y'), 'result': e['result']} for e in dated]
        assert len(season_view(raw, start)) == 3

    def test_cap_365(self):
        start, method = season_start(self._dated([400, 410, 600]), TODAY)
        assert method == 'gap'
        assert start == TODAY - timedelta(days=365)

    def test_empty(self):
        assert season_start([], TODAY) == (TODAY - timedelta(days=60), '60d')


class TestSeasonView:
    def test_undated_placeholder_excluded(self):
        raw = [{'date': _d(1), 'result': 'W'}, {'date': '', 'result': 'L'},
               {'date': _d(200), 'result': 'D'}]
        assert season_view(raw, TODAY - timedelta(days=60)) == ['W']

    def test_all_undated(self):
        assert season_view([{'date': '', 'result': 'W', 'event': ''}], TODAY) is None
        assert season_view('x', TODAY) is None


class TestSeasonConflict:
    def test_cases(self):
        assert season_conflict(list('WWWLL'), ['L', 'L', 'W']) is True
        assert season_conflict(list('WWWLL'), ['W', 'L']) is False
        assert season_conflict(list('WWLLL'), ['L', 'L', 'L']) is False
        assert season_conflict(list('WWWLL'), None) is False


def _season_row(home_ages, away_ages, home_res='WWWLL', away_res='LLDLW', fav='home'):
    return {
        'favorite': fav,
        'home_form': list(home_res), 'away_form': list(away_res),
        'home_form_home': [], 'away_form_away': [],
        'home_form_dated': [{'date': _d(a), 'result': r} for a, r in zip(home_ages, home_res)],
        'away_form_dated': [{'date': _d(a), 'result': r} for a, r in zip(away_ages, away_res)],
    }


class TestApplySeason:
    def test_early_season_three(self):
        row = _season_row([3, 10, 17, 120, 130], [2, 9, 16, 23, 30])
        apply_season(row, TODAY)
        assert row['home_season_match_count'] == 3
        assert row['away_season_match_count'] == 5
        assert row['season_match_count'] == 3
        assert row['early_season'] is True
        assert row['home_season_method'] == 'gap'

    def test_four_not_early(self):
        row = _season_row([3, 10, 17, 24, 130], [2, 9, 16, 23, 30])
        apply_season(row, TODAY)
        assert row['season_match_count'] == 4
        assert row['early_season'] is False

    def test_mismatch_no_keys(self):
        row = _season_row([3, 10, 17, 24, 30], [2, 9, 16, 23, 30])
        row['home_form_dated'][0]['result'] = 'L'   # nie zgadza się z odznakami
        apply_season(row, TODAY)
        assert 'home_season_form' not in row
        assert 'home_season_match_count' not in row
        assert row['season_match_count'] == 5

    def test_conflict_fav_and_opponent(self):
        # Faworyt: WWWLL ogólnie, w sezonie L,L,W (najnowsze pierwsze).
        row = _season_row([3, 10, 17, 120, 130], [2, 9, 16, 23, 30],
                          home_res='LLWWW')
        apply_season(row, TODAY)
        assert row['home_season_form'] == ['L', 'L', 'W']
        assert row['season_form_conflict'] is True
        # Ten sam konflikt tylko u rywala → False.
        row2 = _season_row([3, 10, 17, 120, 130], [2, 9, 16, 23, 30],
                           home_res='LLWWW', fav='away')
        apply_season(row2, TODAY)
        assert row2['season_form_conflict'] is False

    def test_forms_unchanged(self):
        row = _season_row([3, 10, 17, 120, 130], [2, 9, 16, 23, 30])
        row['home_form_home'] = list('WWDWW')
        row['away_form_away'] = list('LLDLL')
        before = copy.deepcopy({k: row[k] for k in
                                ('home_form', 'away_form', 'home_form_home', 'away_form_away')})
        apply_season(row, TODAY)
        for k, v in before.items():
            assert row[k] == v

    def test_unknown(self):
        row = {'favorite': 'home', 'home_form': list('WWWWW')}
        apply_season(row, TODAY)
        assert row['early_season'] is False
        assert row['season_form_conflict'] is False
        assert 'season_match_count' not in row


class TestMarket:
    def test_gap_25(self):
        row = {'sport': 'basketball', 'favorite': 'home', 'forebet_fav_prob': 80,
               'home_odds': 1 / 0.55, 'away_odds': 1 / 0.45}
        assert market_gap_pp(row) == pytest.approx(25.0)

    def test_gap_15(self):
        row = {'sport': 'basketball', 'favorite': 'home', 'forebet_fav_prob': 70,
               'home_odds': 1 / 0.55, 'away_odds': 1 / 0.45}
        assert market_gap_pp(row) == pytest.approx(15.0)

    def test_exactly_20_not_stale(self):
        row = {'sport': 'basketball', 'favorite': 'home', 'forebet_fav_prob': 70,
               'home_odds': 2.0, 'away_odds': 2.0}
        assert market_gap_pp(row) == 20.0
        assert not (market_gap_pp(row) > recency.STALE_MODEL_PP)

    def test_football_without_draw(self):
        row = {'sport': 'football', 'favorite': 'home', 'forebet_fav_prob': 80,
               'home_odds': 1.8, 'away_odds': 4.0}
        assert market_gap_pp(row) is None

    def test_string_odds(self):
        row = {'sport': 'basketball', 'favorite': 'away', 'forebet_fav_prob': '60',
               'home_odds': '1.80', 'away_odds': '2.00'}
        imp = implied_probs(row)
        assert imp['home'] + imp['away'] == pytest.approx(1.0)
        assert market_gap_pp(row) is not None

    def test_only_forebet_odds(self):
        row = {'sport': 'basketball', 'favorite': 'home', 'forebet_fav_prob': 80,
               'forebet_home_odds': 1.5, 'forebet_away_odds': 2.5}
        assert market_gap_pp(row) is None


class TestLowerGrade:
    def test_cases(self):
        r = {'stale_model': True, 'prediction_grade': 'A'}
        lower_grade_if_stale(r)
        assert r['prediction_grade'] == 'B' and r['prediction_grade_raw'] == 'A'
        lower_grade_if_stale(r)
        assert r['prediction_grade'] == 'B'
        f = {'stale_model': True, 'prediction_grade': 'F'}
        lower_grade_if_stale(f)
        assert f['prediction_grade'] == 'F'
        n = {'stale_model': True, 'prediction_grade': None}
        lower_grade_if_stale(n)
        assert n['prediction_grade'] is None
        ns = {'stale_model': False, 'prediction_grade': 'A'}
        lower_grade_if_stale(ns)
        assert ns['prediction_grade'] == 'A'


# ---------------------------------------------------------------------------
# Livesport — datowane wiersze z już wczytanych stron
# ---------------------------------------------------------------------------
_BADGE = {'W': ('win', 'Z'), 'D': ('draw', 'R'), 'L': ('lose', 'P')}


def _ls_row(dt, home, away, gh, ga, badge=None):
    b = ''
    if badge:
        kind, txt = _BADGE[badge]
        b = (f'<span class="h2h__icon"><div class="wcl-badgeform_AKaAR" '
             f'data-testid="wcl-badgeForm-{kind}"><span>{txt}</span></div></span>')
    d = f'<span class="wclH2h__date" data-testid="wcl-stageTime">{dt}</span>' if dt else ''
    return (f'<a class="h2h__row ">{d}'
            f'<div class="h2h__participant h2h__homeParticipant"><span class="wcl-name_x" '
            f'data-testid="wcl-scores-simple-text-01">{home}</span></div>'
            f'<div class="h2h__participant h2h__awayParticipant"><span class="wcl-name_x" '
            f'data-testid="wcl-scores-simple-text-01">{away}</span></div>'
            f'<span class="h2h__result"><span data-testid="wcl-tableScore">{gh}</span>'
            f'<span data-testid="wcl-tableScore">{ga}</span></span>{b}</a>')


def _section(rows):
    return '<div class="h2h__section"><div class="rows">' + ''.join(rows) + '</div></div>'


def _team_rows(team, results, start_age=3):
    out = []
    for i, r in enumerate(results):
        gh, ga = {'W': (2, 0), 'D': (1, 1), 'L': (0, 2)}[r]
        out.append(_ls_row(_d(start_age + 7 * i), team, f'Rival {i}', gh, ga, r))
    return out


HOME_RES, AWAY_RES = list('WWDLW'), list('LDLWL')
HOME_VENUE, AWAY_VENUE = list('WWWDW'), list('LLDLL')


def _page(*sections):
    return '<html><body><div class="h2h">' + ''.join(sections) + '</div></body></html>'


OVERALL = _page(_section(_team_rows('Home FC', HOME_RES)),
                _section(_team_rows('Away FC', AWAY_RES)),
                _section([_ls_row(_d(100), 'Home FC', 'Away FC', 1, 0)]))
VENUE_HOME = _page(_section(_team_rows('Home FC', HOME_VENUE)))
VENUE_AWAY = _page(_section(_team_rows('Away FC', AWAY_VENUE)))
VENUE_EMPTY = _page(_section([]))


class FakeDriver:
    def __init__(self, venue_home=VENUE_HOME):
        self.urls = []
        self._src = ''
        self.venue_home = venue_home

    def get(self, url):
        self.urls.append(url)
        if '/h2h/u-siebie/' in url:
            self._src = self.venue_home
        elif '/h2h/na-wyjezdzie/' in url:
            self._src = VENUE_AWAY
        else:
            self._src = OVERALL

    @property
    def page_source(self):
        return self._src

    def execute_script(self, *a, **k):
        return None


MATCH_URL = 'https://www.livesport.com/pl/mecz/pilka-nozna/away-fc-x/home-fc-y/?mid=ABC'


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr('time.sleep', lambda *_: None)


class TestExtractDatedRows:
    def _sec(self, html):
        from bs4 import BeautifulSoup
        return BeautifulSoup(_section([html]), 'html.parser').find('div', class_='h2h__section')

    def test_badge_row_tracked_away_wins(self):
        import livesport_h2h_scraper as ls
        sec = self._sec(_ls_row('01.10.26', 'Other', 'Home FC', 0, 2, 'W'))
        assert ls.extract_dated_rows(sec, 'Home FC') == [{'date': '01.10.26', 'result': 'W', 'event': ''}]

    def test_badgeless_name_match(self):
        import livesport_h2h_scraper as ls
        sec = self._sec(_ls_row('01.10.26', 'Other', 'Home FC', 3, 1))
        assert ls.extract_dated_rows(sec, 'Home FC') == [{'date': '01.10.26', 'result': 'L', 'event': ''}]

    def test_badgeless_no_match_dropped(self):
        import livesport_h2h_scraper as ls
        sec = self._sec(_ls_row('01.10.26', 'Other', 'Third', 3, 1))
        assert ls.extract_dated_rows(sec, 'Home FC') == []
        assert ls.extract_dated_rows(sec, '') == []

    def test_undated_badge_placeholder(self):
        import livesport_h2h_scraper as ls
        sec = self._sec(_ls_row('', 'Home FC', 'Other', 2, 0, 'W'))
        assert ls.extract_dated_rows(sec, 'Home FC') == [{'date': '', 'result': 'W', 'event': ''}]


class TestNoExtraPageLoads:
    def test_three_loads_with_and_without_names(self, no_sleep):
        import livesport_h2h_scraper as ls
        d1, d2 = FakeDriver(), FakeDriver()
        r1 = ls.extract_advanced_team_form(MATCH_URL, d1)
        r2 = ls.extract_advanced_team_form(MATCH_URL, d2, 'Home FC', 'Away FC')
        assert len(d1.urls) == 3 and d1.urls == d2.urls
        assert '/h2h/ogolem/' in d1.urls[0]
        assert '/h2h/u-siebie/' in d1.urls[1]
        assert '/h2h/na-wyjezdzie/' in d1.urls[2]
        for r in (r1, r2):
            assert [e['result'] for e in r['home_form_overall_dated']] == r['home_form_overall']
            assert [e['result'] for e in r['away_form_overall_dated']] == r['away_form_overall']
            assert [e['result'] for e in r['home_form_home_dated']] == r['home_form_home']
            assert [e['result'] for e in r['away_form_away_dated']] == r['away_form_away']
        for k in ('home_form_overall', 'away_form_overall', 'home_form_home', 'away_form_away'):
            assert r1[k] == r2[k]
        assert r1['home_form_overall'] == HOME_RES

    def test_empty_venue_fallback(self, no_sleep):
        import livesport_h2h_scraper as ls
        d1, d2 = FakeDriver(VENUE_EMPTY), FakeDriver(VENUE_EMPTY)
        r1 = ls.extract_advanced_team_form(MATCH_URL, d1)
        r2 = ls.extract_advanced_team_form(MATCH_URL, d2, 'Home FC', 'Away FC')
        assert len(d1.urls) == 4 and len(d2.urls) == 4
        assert r2['home_form_home_dated'] == []
        assert r1['home_form_home'] == r2['home_form_home']

    def test_fetch_h2h_and_form(self, no_sleep):
        import forebet_pipeline as fp
        drv = FakeDriver()
        out = fp.fetch_h2h_and_form(drv, MATCH_URL, 'Home FC', 'football', away_team='Away FC')
        assert len(drv.urls) == 4
        assert '/h2h/ogolem/' in drv.urls[0] and '/h2h/ogolem/' in drv.urls[1]
        assert '/h2h/u-siebie/' in drv.urls[2] and '/h2h/na-wyjezdzie/' in drv.urls[3]
        assert out['home_form_dated'] and out['away_form_dated']
        assert [e['result'] for e in out['home_form_dated']] == out['home_form']
        assert [e['result'] for e in out['away_form_dated']] == out['away_form']
        drv2 = FakeDriver(VENUE_EMPTY)
        fp.fetch_h2h_and_form(drv2, MATCH_URL, 'Home FC', 'football', away_team='Away FC')
        assert len(drv2.urls) == 5


# ---------------------------------------------------------------------------
# forebet_pipeline — scoring, kwalifikacja, ocena
# ---------------------------------------------------------------------------
def _fb_row(**kw):
    row = {
        'sport': 'football', 'home_team': 'Guif', 'away_team': 'Drott',
        'favorite': 'home', 'forebet_fav_prob': 65,
        'home_form': list('WWWDL'), 'away_form': list('LLDLW'),
        'home_form_home': [], 'away_form_away': [],
        'home_odds': 1.8, 'draw_odds': 3.6, 'away_odds': 4.5,
        'h2h_last5': [], 'h2h_count': 0,
        'home_wins_in_h2h_last5': 0, 'away_wins_in_h2h_last5': 0,
        'skip_reason': None,
    }
    row.update(kw)
    return row


def _score(row):
    import forebet_pipeline as fp
    fp.score_row(row)
    fp.apply_qualification(row, 0, 1)
    return row


_H2H_KEYS = ('h2h_last5', 'h2h_count', 'home_wins_in_h2h_last5', 'away_wins_in_h2h_last5')


class TestForebetRecency:
    def test_ac1_no_h2h_neutral(self):
        import forebet_pipeline as fp
        a = _fb_row()
        fp.apply_recency(a, TODAY)
        _score(a)
        b = {k: v for k, v in _fb_row().items() if k not in _H2H_KEYS}
        _score(b)
        assert a['scoring_prob'] == b['scoring_prob']
        assert 'h2h' not in (a.get('scoring_components') or {})
        assert a['h2h_neutral'] is True

    def test_ac2_guif_drott(self):
        import forebet_pipeline as fp
        a = _fb_row(h2h_count=1, home_wins_in_h2h_last5=1,
                    h2h_last5=[{'date': '09.03.16', 'home': 'Guif', 'away': 'Drott',
                                'score': '30-25', 'winner': 'home'}])
        fp.apply_recency(a, TODAY)
        _score(a)
        assert a['h2h_all_stale'] is True and a['h2h_neutral'] is True
        b = _fb_row()
        fp.apply_recency(b, TODAY)
        _score(b)
        assert a['scoring_prob'] == b['scoring_prob']

    def test_ac3_effective_counts(self):
        import forebet_pipeline as fp
        three = [{'date': _d(400 + i), 'home': 'Guif', 'away': 'Drott', 'winner': 'home'}
                 for i in range(3)]
        a = _fb_row(h2h_last5=three, h2h_count=3, home_wins_in_h2h_last5=3)
        fp.apply_recency(a, TODAY)
        _score(a)
        assert a['h2h_effective_count'] == 1.5 and a['h2h_fresh_count'] == 3
        # Minimum liczy spotkania, nie wagi: 3 mecze sprzed 12–24 mies. zostają.
        assert a['scoring_components']['h2h'] == pytest.approx(1.0)
        four = [{'date': _d(10), 'home': 'Guif', 'away': 'Drott', 'winner': 'home'},
                {'date': _d(20), 'home': 'Guif', 'away': 'Drott', 'winner': 'away'},
                {'date': _d(400), 'home': 'Guif', 'away': 'Drott', 'winner': 'home'},
                {'date': '09.03.16', 'home': 'Guif', 'away': 'Drott', 'winner': 'home'}]
        b = _fb_row(h2h_last5=four, h2h_count=4, home_wins_in_h2h_last5=3,
                    away_wins_in_h2h_last5=1)
        fp.apply_recency(b, TODAY)
        _score(b)
        assert b['h2h_effective_count'] == 2.5
        assert b['scoring_components']['h2h'] == pytest.approx(1.5 / 2.5, abs=1e-3)

    def test_ac4_dated_lists_do_not_change_scoring(self):
        import forebet_pipeline as fp
        a = _fb_row(home_form_dated=[{'date': _d(3 + 7 * i), 'result': r}
                                     for i, r in enumerate('WWWDL')],
                    away_form_dated=[{'date': _d(2 + 7 * i), 'result': r}
                                     for i, r in enumerate('LLDLW')])
        b = {k: v for k, v in copy.deepcopy(a).items() if not k.endswith('_dated')}
        forms = copy.deepcopy({k: a[k] for k in ('home_form', 'away_form')})
        fp.apply_recency(a, TODAY)
        fp.apply_recency(b, TODAY)
        _score(a)
        _score(b)
        for k in ('qualifies', 'skip_reasons', 'scoring_prob', 'form_advantage'):
            assert a[k] == b[k]
        assert 'home_season_form' in a
        for k, v in forms.items():
            assert a[k] == v

    def test_ac5_flags_do_not_change_qualification(self):
        import forebet_pipeline as fp
        a = _fb_row(home_form=list('LLWWW'),
                    home_form_dated=[{'date': _d(a_), 'result': r}
                                     for a_, r in zip([3, 10, 17, 120, 130], 'LLWWW')])
        fp.apply_recency(a, TODAY)
        _score(a)
        assert a['early_season'] is True and a['season_form_conflict'] is True
        b = _fb_row(home_form=list('LLWWW'))
        _score(b)
        assert a['qualifies'] == b['qualifies']
        assert a['skip_reasons'] == b['skip_reasons']
        assert a['scoring_prob'] == b['scoring_prob']

    def test_ac6_stale_model_lowers_grade(self):
        import forebet_pipeline as fp
        from prediction_data_contract import enrich_match_with_contract
        a = _fb_row(sport='basketball', forebet_fav_prob=80, draw_odds=None,
                    home_odds=1 / 0.55, away_odds=1 / 0.45)
        fp.apply_recency(a, TODAY)
        _score(a)
        q = a['qualifies']
        enrich_match_with_contract(a)
        raw = a['prediction_grade']
        recency.lower_grade_if_stale(a)
        assert a['stale_model'] is True and a['market_gap_pp'] == 25.0
        assert a['prediction_grade'] == {'A': 'B', 'B': 'C', 'C': 'D'}.get(raw, raw)
        assert a['qualifies'] == q
        b = _fb_row(sport='basketball', forebet_fav_prob=70, draw_odds=None,
                    home_odds=1 / 0.55, away_odds=1 / 0.45)
        fp.apply_recency(b, TODAY)
        _score(b)
        enrich_match_with_contract(b)
        g = b['prediction_grade']
        recency.lower_grade_if_stale(b)
        assert b['stale_model'] is False and b['prediction_grade'] == g

    def test_ac7_no_dates_no_odds_identical(self):
        import forebet_pipeline as fp
        base = _fb_row(home_odds=None, draw_odds=None, away_odds=None, h2h_count=3,
                       home_wins_in_h2h_last5=2,
                       h2h_last5=[{'date': '', 'winner': 'home'}] * 3)
        a, b = copy.deepcopy(base), copy.deepcopy(base)
        fp.apply_recency(a, TODAY)
        _score(a)
        _score(b)
        for k in ('scoring_prob', 'qualifies', 'skip_reasons'):
            assert a[k] == b[k]

    def test_garbage_does_not_raise(self):
        import forebet_pipeline as fp
        row = _fb_row(h2h_last5='x', home_form_dated='[{"date": "1"}]',
                      forebet_fav_prob='abc', home_odds='zz')
        fp.apply_recency(row, TODAY)
        assert row['stale_model'] is False


class TestGradeNeutral:
    def test_neutral_h2h_in_data_quality(self):
        import forebet_pipeline as fp
        from prediction_data_contract import enrich_match_with_contract
        a = _fb_row()
        fp.apply_recency(a, TODAY)
        _score(a)
        enrich_match_with_contract(a)
        assert a['data_quality']['h2h_available'] is False
        assert a['data_quality']['h2h_neutral'] is True
        one = _fb_row(h2h_count=1, home_wins_in_h2h_last5=1,
                      h2h_last5=[{'date': _d(10), 'home': 'Guif', 'away': 'Drott',
                                  'winner': 'home'}])
        fp.apply_recency(one, TODAY)
        _score(one)
        enrich_match_with_contract(one)
        assert a['data_quality']['quality_score'] == one['data_quality']['quality_score']
        old = _fb_row()
        _score(old)
        enrich_match_with_contract(old)
        assert GRADE_ORDER.index(a['prediction_grade']) <= GRADE_ORDER.index(old['prediction_grade'])

    def test_regression_without_key(self):
        # Bez klucza h2h_neutral (inne pipeline'y) zachowanie jak dotąd:
        # brak H2H obniża jakość, obecne H2H ją podnosi.
        from prediction_data_contract import compute_data_quality
        none = compute_data_quality(_fb_row()).to_dict()
        some = compute_data_quality(_fb_row(h2h_count=3, home_wins_in_h2h_last5=2)).to_dict()
        assert none['h2h_available'] is False and some['h2h_available'] is True
        assert none['quality_score'] < some['quality_score']


# ---------------------------------------------------------------------------
# write_outputs / e-mail
# ---------------------------------------------------------------------------
class TestWriteOutputs:
    def test_json_and_csv(self, tmp_path, monkeypatch):
        import pandas as pd
        import forebet_pipeline as fp
        import email_notifier as en
        monkeypatch.chdir(tmp_path)
        a = _fb_row(h2h_count=1, h2h_last5=[{'date': '09.03.16', 'home': 'Guif',
                                             'away': 'Drott', 'winner': 'home'}],
                    home_form_dated=[{'date': _d(3 + 7 * i), 'result': r}
                                     for i, r in enumerate('WWWDL')])
        fp.apply_recency(a, TODAY)
        _score(a)
        b = _fb_row(home_team='X', away_team='Y')
        _score(b)
        fp.write_outputs([a, b], 'football', '2026-10-20')
        data = json.load(open(tmp_path / 'results' / 'matches_2026-10-20_football_forebet.json',
                              encoding='utf-8'))
        ja, jb = data['matches']
        assert ja['h2h']['allStale'] is True and ja['h2h']['effectiveTotal'] == 0
        assert ja['form']['homeSeason'] == list('WWWDL')
        assert ja['seasonMatchCount'] is None or isinstance(ja['seasonMatchCount'], int)
        assert ja['earlySeason'] is False and ja['staleModel'] is False
        assert jb['h2h']['effectiveTotal'] is None
        assert jb['form']['homeSeason'] is None and jb['earlySeason'] is None
        assert jb['form']['home'] == list('WWWDL')
        df = pd.read_csv(tmp_path / 'outputs' / 'forebet_football_2026-10-20.csv')
        assert 'home_season_form' in df.columns
        assert en.parse_form_list(df['home_season_form'][0]) == list('WWWDL')


class TestEmailSeason:
    def _match(self, **kw):
        m = {'home_team': 'Home FC', 'away_team': 'Away FC', 'match_time': '18:00',
             'home_form': "['W', 'W', 'L']", 'away_form': "['L', 'L', 'W']",
             'home_form_home': "['W', 'W']", 'away_form_away': "['L']",
             'favorite': 'away', 'sport': 'football'}
        m.update(kw)
        return m

    def test_season_line(self):
        import email_notifier as en
        html = en.create_html_email([self._match(home_season_form="['W', 'L']",
                                                 home_season_match_count=2.0)],
                                    '2026-10-20', cards_only=True)
        assert '📅 Sezon' in html and '(2)' in html

    def test_no_season_keys(self):
        import email_notifier as en
        html = en.create_html_email([self._match()], '2026-10-20', cards_only=True)
        assert '📅 Sezon' not in html

    def test_conflict_warning_on_fav_only(self):
        import email_notifier as en
        kw = dict(home_season_form="['W', 'L', 'L']", home_season_match_count=3,
                  away_season_form="['L', 'L', 'W']", away_season_match_count=3)
        base = en.create_html_email([self._match(**kw)], '2026-10-20', cards_only=True)
        conf = en.create_html_email([self._match(season_form_conflict='True', **kw)],
                                    '2026-10-20', cards_only=True)
        assert conf.count('⚠️') == base.count('⚠️') + 1
        away_line = '📅 Sezon: 🔴🔴🟢 (3) ⚠️'
        assert away_line in conf
        assert '📅 Sezon: 🟢🔴🔴 (3) ⚠️' not in conf

    def test_nan_count(self):
        import email_notifier as en
        html = en.create_html_email([self._match(home_season_form="['W']",
                                                 home_season_match_count=float('nan'))],
                                    '2026-10-20', cards_only=True)
        assert '📅 Sezon: 🟢</div>' in html


# ---------------------------------------------------------------------------
# TOP i Twierdza
# ---------------------------------------------------------------------------
def _top_match(**kw):
    m = {'homeTeam': 'Home FC', 'awayTeam': 'Away FC', 'time': '18:00', 'league': 'L',
         'qualifies': True, 'predictionGrade': 'A',
         'scoring': {'pick': '1', 'prob': 70},
         'forebet': {'prediction': '1', 'homeProb': 70, 'awayProb': 30},
         'odds': {'home': 2.1, 'away': 3.0},
         'form': {'home': list('WWWWD'), 'away': list('LLLDW'),
                  'homeAtHome': list('WWWDW'), 'awayAtAway': list('LLDLL')},
         'h2h': {'total': 0}, 'sofascore': {'found': False}}
    m.update(kw)
    return m


class TestTopPicks:
    def test_flags_exclude(self):
        from tools import top_picks as tp
        assert tp.evaluate(_top_match(), 'football') is not None
        for flag in ('earlySeason', 'staleModel', 'seasonFormConflict'):
            assert tp.evaluate(_top_match(**{flag: True}), 'football') is None

    def test_effective_h2h(self):
        from tools import top_picks as tp
        stale = {'total': 3, 'homeWins': 0, 'awayWins': 3, 'effectiveTotal': 0,
                 'homeWinsEff': 0, 'awayWinsEff': 0}
        r = tp.evaluate(_top_match(h2h=stale), 'football')
        assert r is not None and r['h2h'] == 'brak'
        old = {'total': 3, 'homeWins': 0, 'awayWins': 3}
        assert tp.evaluate(_top_match(h2h=old), 'football') is None

    def test_season_form_string(self):
        from tools import top_picks as tp
        m = _top_match()
        m['form'] = dict(m['form'], homeSeason=['W', 'W'], awaySeason=['L'])
        r = tp.evaluate(m, 'football')
        plain = tp.evaluate(_top_match(), 'football')
        assert r['seasonForm'] == 'WW / L'
        assert plain['seasonForm'] == ''
        assert r['form'] == plain['form'] and r['signals'] == plain['signals']

    def test_collect_excludes_flagged(self, tmp_path, monkeypatch):
        from tools import top_picks as tp
        monkeypatch.setattr(tp, 'ROOT', str(tmp_path))
        (tmp_path / 'results').mkdir()
        p = tmp_path / 'results' / 'matches_2026-10-20_football_forebet.json'
        p.write_text(json.dumps({'matches': [
            _top_match(), _top_match(homeTeam='Flag FC', staleModel=True)]}), encoding='utf-8')
        out = tp.collect('2026-10-20')
        assert [r['match'] for r in out] == ['Home FC vs Away FC']


class TestDailyDigest:
    def _setup(self, tmp_path, monkeypatch, tw_match):
        from tools import daily_digest as dd
        from tools import top_picks as tp
        monkeypatch.setattr(dd, 'ROOT', str(tmp_path))
        monkeypatch.setattr(tp, 'ROOT', str(tmp_path))
        monkeypatch.setattr(tp, 'enrich_fanvote', lambda *a, **k: None)
        (tmp_path / 'results').mkdir(parents=True)
        (tmp_path / 'outputs').mkdir()
        fb = _top_match(form={'home': list('WWWWD'), 'away': list('LLLDW'),
                              'homeAtHome': list('WWWDW'), 'awayAtAway': list('LLDLL'),
                              'homeSeason': ['W', 'W'], 'awaySeason': ['L']})
        (tmp_path / 'results' / 'matches_2026-10-20_football_forebet.json').write_text(
            json.dumps({'matches': [fb]}), encoding='utf-8')
        (tmp_path / 'results' / 'matches_2026-10-20_hockey_forebet.json').write_text(
            json.dumps({'matches': [tw_match]}), encoding='utf-8')
        (tmp_path / 'results' / 'top_2026-10-20.json').write_text(json.dumps([
            {'sport': 'football', 'time': '18:00', 'match': 'A vs B', 'league': 'L',
             'pick': 'A', 'odds': 2.1, 'grade': 'A', 'score': 70, 'form': 'x',
             'h2h': 'brak', 'fanvote': 'brak', 'signals': '4/4 za',
             'seasonForm': 'WW / L'}]), encoding='utf-8')
        (tmp_path / 'outputs' / 'oddssafari_dropping_2026-10-20_x.json').write_text(json.dumps(
            {'qualified': [{'sport': 'football', 'event_time': '19:00', 'home_team': 'C',
                            'away_team': 'D', 'outcome': '1', 'current_odds': 1.9,
                            'open_odds': 2.2, 'drop_pct': 14, 'match_url': 'u'}]}),
            encoding='utf-8')
        return dd

    def _tw(self, **kw):
        m = {'homeTeam': 'Fort FC', 'awayTeam': 'Weak FC', 'time': '20:00', 'league': 'L',
             'qualifies': True, 'predictionGrade': 'B',
             'forebet': {'homeProb': 70, 'awayProb': 30},
             'sofascore': {'found': True, 'homeProb': 80, 'awayProb': 20},
             'odds': {'home': 1.5, 'away': 2.6},
             'form': {'home': list('WWWWL'), 'away': list('LLLLW'),
                      'homeAtHome': list('WWWWW'), 'awayAtAway': list('LLLLL'),
                      'homeSeason': ['W', 'W', 'W'], 'awaySeason': ['L']}}
        m.update(kw)
        return m

    def test_collect_15_columns(self, tmp_path, monkeypatch):
        dd = self._setup(tmp_path, monkeypatch, self._tw())
        data = dd.collect('2026-10-20')
        for cat in ('TOP', 'Forebet', 'Dropping'):
            assert data[cat], cat
            assert all(len(r) == 16 for r in data[cat]), cat
        fb = [r for r in data['Forebet'] if r[3] == 'Home FC vs Away FC'][0]
        assert fb[14] == 'WW / L'
        assert fb[9] == 'WWWWD' and fb[10] == 'LLLDW' and fb[11] == ''
        assert fb[12] == '' and fb[13] is None
        assert data['TOP'][0][14] == 'WW / L'

    def test_twierdza_flags(self, tmp_path, monkeypatch):
        dd = self._setup(tmp_path, monkeypatch, self._tw())
        tw = dd.twierdza('2026-10-20')
        fort = [r for r in tw if r['pick'] == 'Fort FC']
        assert fort and fort[0]['seasonForm'] == 'WWW / L'
        rows = dd.twierdza_rows(tw)
        assert all(len(r) == 16 for r in rows)
        for flag in ('earlySeason', 'staleModel', 'seasonFormConflict'):
            dd = self._setup(tmp_path / flag, monkeypatch, self._tw(**{flag: True}))
            assert not [r for r in dd.twierdza('2026-10-20') if r['pick'] == 'Fort FC']

    def test_twierdza_without_season_keys(self, tmp_path, monkeypatch):
        m = self._tw()
        m['form'] = {k: v for k, v in m['form'].items() if 'Season' not in k}
        dd = self._setup(tmp_path, monkeypatch, m)
        fort = [r for r in dd.twierdza('2026-10-20') if r['pick'] == 'Fort FC']
        assert fort and fort[0]['seasonForm'] == ''

    def test_write_xlsx_headers(self, tmp_path, monkeypatch):
        from openpyxl import load_workbook
        dd = self._setup(tmp_path, monkeypatch, self._tw())
        data = dd.collect('2026-10-20')
        data['Twierdza'] = dd.twierdza_rows(dd.twierdza('2026-10-20'))
        out = dd.write_xlsx('2026-10-20', data, 'x')
        wb = load_workbook(out)
        top = [c.value for c in wb['TOP'][1]]
        assert top[-3:] == ['Sygnały', 'Forma sezon', 'Forma / Sezon']
        assert [c.value for c in wb['Forebet'][1]][-2:] == ['Forma sezon', 'Forma / Sezon']
        sport_sheets = [s for s in wb.sheetnames if '_TOP_' in s]
        assert sport_sheets
        for s in sport_sheets:
            assert [c.value for c in wb[s][1]][-2:] == ['Forma sezon', 'Forma / Sezon']


# ---------------------------------------------------------------------------
# Poprawki po review (F1–F5, F7)
# ---------------------------------------------------------------------------
class TestReviewFixes:
    def test_mixed_dated_undated_ages_dated(self):
        row = {'home_team': 'Guif', 'away_team': 'Drott', 'favorite': 'home',
               'h2h_last5': [{'date': '09.03.16', 'home': 'Guif', 'away': 'Drott',
                              'winner': 'home'},
                             {'date': '', 'home': 'Guif', 'away': 'Drott', 'winner': 'away'}]}
        eff = effective_h2h(row, TODAY)
        assert eff['count'] == 1.0 and eff['ignored'] == 1
        assert eff['home_wins'] == 0 and eff['away_wins'] == 1.0

    def test_stale_grade_clamped_at_d(self):
        for raw, exp in (('A', 'B'), ('B', 'C'), ('C', 'D'), ('D', 'D')):
            row = {'stale_model': True, 'prediction_grade': raw}
            recency.lower_grade_if_stale(row)
            assert row['prediction_grade'] == exp
        # D-stale nadal trafia do maila C/D (forebet_pipeline: grade_filter {C, D}).
        assert row['prediction_grade'] in {'C', 'D'}

    def test_rugby_without_draw(self):
        # Forebet rugby jest dwudrogowe → rynek dwudrogowy.
        row = {'sport': 'rugby', 'favorite': 'home', 'forebet_fav_prob': 90,
               'home_odds': 1.8, 'away_odds': 2.0}
        assert set(recency.implied_probs(row)) == {'home', 'away'}
        assert recency.market_gap_pp(row) is not None

    def test_digest_effective_h2h(self):
        from tools import daily_digest as dd
        stale = _top_match(h2h={'total': 1, 'homeWins': 1, 'awayWins': 0,
                                'effectiveTotal': 0, 'homeWinsEff': 0, 'awayWinsEff': 0})
        assert dd._row('Forebet', 'football', stale, 'home')[11] == 'brak'
        half = _top_match(h2h={'total': 2, 'homeWins': 2, 'awayWins': 0,
                               'effectiveTotal': 1.5, 'homeWinsEff': 0.5, 'awayWinsEff': 1.0})
        assert dd._row('Forebet', 'football', half, 'home')[11] == '0.5-1'
        old = _top_match(h2h={'total': 2, 'homeWins': 2, 'awayWins': 0})
        assert dd._row('Forebet', 'football', old, 'home')[11] == '2-0'

    def test_email_stale_h2h_marker(self):
        import email_notifier as en
        base = dict(home_team='Guif', away_team='Drott', match_time='18:00',
                    sport='handball', favorite='home', h2h_count=1,
                    last_h2h_date='09.03.16')
        html = en.create_html_email([dict(base, h2h_all_stale=True)], '2026-10-20',
                                    cards_only=True)
        assert 'H2H nieaktualne' in html
        html = en.create_html_email([base], '2026-10-20', cards_only=True)
        assert 'H2H nieaktualne' not in html and 'pominięte stare H2H' not in html

    def test_twierdza_flag_blocks_sports_copy(self, tmp_path, monkeypatch):
        dd = TestDailyDigest()._setup(tmp_path, monkeypatch, TestDailyDigest()._tw())
        clean = TestDailyDigest()._tw()
        (tmp_path / 'results' / 'matches_2026-10-20_hockey.json').write_text(
            json.dumps({'matches': [clean]}), encoding='utf-8')
        assert [r for r in dd.twierdza('2026-10-20') if r['pick'] == 'Fort FC']
        (tmp_path / 'results' / 'matches_2026-10-20_hockey_forebet.json').write_text(
            json.dumps({'matches': [TestDailyDigest()._tw(staleModel=True)]}), encoding='utf-8')
        assert not [r for r in dd.twierdza('2026-10-20') if r['pick'] == 'Fort FC']

    def test_season_form_colour_by_pick(self, tmp_path, monkeypatch):
        from openpyxl import load_workbook
        dd = TestDailyDigest()._setup(tmp_path, monkeypatch, TestDailyDigest()._tw())
        data = {'TOP': [], 'Forebet': [['F', 'football', '18:00', 'a vs b', 'L', 'a', 1.9,
                                        'A', 70, 'WWW', 'LL', '', '', '', 'LL / WWWW'],
                                       ['F', 'football', '19:00', 'c vs d', 'L', 'c', 1.9,
                                        'A', 70, 'WWW', 'LL', '', '', '', '']]}
        wb = load_workbook(dd.write_xlsx('2026-10-20', data, 'x'))
        sh = wb['Forebet']
        assert sh.cell(2, 15).fill.fgColor.rgb.endswith('FFC7CE')
        assert not sh.cell(3, 15).fill.fgColor.rgb.endswith('FFC7CE')

# ---------------------------------------------------------------------------
# Poprawki po review r2
# ---------------------------------------------------------------------------
class TestReviewFixesR2:
    def test_twierdza_alias_names_blocked(self, tmp_path, monkeypatch):
        D = TestDailyDigest()
        dd = D._setup(tmp_path, monkeypatch, D._tw(homeTeam='Other', awayTeam='Team'))
        (tmp_path / 'results' / 'matches_2026-10-20_hockey.json').write_text(
            json.dumps({'matches': [D._tw()]}), encoding='utf-8')
        assert [r for r in dd.twierdza('2026-10-20') if r['pick'] == 'Fort FC']
        # Forebet: inne nazwy niż Livesport/Sports („Fort” vs „Fort FC”).
        (tmp_path / 'results' / 'matches_2026-10-20_hockey_forebet.json').write_text(
            json.dumps({'matches': [D._tw(homeTeam='Fort', awayTeam='Weak',
                                          earlySeason=True)]}), encoding='utf-8')
        assert not [r for r in dd.twierdza('2026-10-20') if r['pick'] == 'Fort FC']

    def test_is_flagged_aliases_and_reversed(self):
        from tools import top_picks as tp
        fl = [('basketball', 'Sydney', 'Albirex Niigata W')]
        assert tp.is_flagged(fl, 'basketball', 'Sydney Kings', 'Albirex Niigata K')
        assert tp.is_flagged(fl, 'basketball', 'Albirex Niigata', 'Sydney Kings')
        assert not tp.is_flagged(fl, 'football', 'Sydney Kings', 'Albirex Niigata K')
        assert not tp.is_flagged(fl, 'basketball', 'Perth Wildcats', 'Albirex Niigata')

    def test_top_file_revalidated(self, tmp_path, monkeypatch):
        from tools import top_picks as tp
        monkeypatch.setattr(tp, 'ROOT', str(tmp_path))
        (tmp_path / 'results').mkdir()
        (tmp_path / 'results' / 'matches_2026-10-20_football_forebet.json').write_text(
            json.dumps({'matches': [_top_match(homeTeam='Old FC', staleModel=True)]}),
            encoding='utf-8')
        old = [{'sport': 'football', 'match': 'Old FC vs Away FC'},
               {'sport': 'football', 'match': 'Good FC vs Other FC'}]
        assert [r['match'] for r in tp.drop_flagged(old, '2026-10-20')] == \
            ['Good FC vs Other FC']

    def test_two_half_age_meetings_keep_h2h(self):
        import forebet_pipeline as fp
        two = [{'date': _d(400 + i), 'home': 'Guif', 'away': 'Drott', 'winner': 'home'}
               for i in range(2)]
        a = _fb_row(h2h_last5=two, h2h_count=2, home_wins_in_h2h_last5=2)
        fp.apply_recency(a, TODAY)
        _score(a)
        assert a['h2h_neutral'] is False
        assert a['scoring_components']['h2h'] == pytest.approx(1.0)

    def test_email_stale_model_note(self):
        import email_notifier as en
        base = dict(home_team='A', away_team='B', match_time='18:00', sport='football',
                    favorite='home', prediction_grade='C')
        html = en.create_html_email([dict(base, stale_model=True, market_gap_pp=25.0,
                                          prediction_grade_raw='B')],
                                    '2026-10-20', cards_only=True)
        assert 'model +25 pp nad rynkiem (było B)' in html
        assert 'nad rynkiem' not in en.create_html_email([base], '2026-10-20',
                                                         cards_only=True)

    def test_tennis_stale_h2h_marker(self):
        import email_notifier as en
        m = dict(home_team='P One', away_team='P Two', match_time='18:00', sport='tennis',
                 favorite='player_a', h2h_count=1, h2h_all_stale=True)
        assert 'H2H nieaktualne' in en.create_html_email([m], '2026-10-20', cards_only=True)

    def test_short_season_list_colour_by_share(self, tmp_path, monkeypatch):
        from openpyxl import load_workbook
        dd = TestDailyDigest()._setup(tmp_path, monkeypatch, TestDailyDigest()._tw())
        row = ['F', 'football', '18:00', 'a vs b', 'L', 'a', 1.9, 'A', 70, 'WWW', 'LL',
               '', '', '', 'WW / L']
        wb = load_workbook(dd.write_xlsx('2026-10-20', {'TOP': [], 'Forebet': [row]}, 'x'))
        assert not wb['Forebet'].cell(2, 15).fill.fgColor.rgb.endswith('FFC7CE')


class TestReviewLoop3:
    def test_no_h2h_passes_default_min_sources(self):
        import forebet_pipeline as fp
        today = date.today()
        none = fp.apply_recency(_fb_row(), today)
        fp.score_row(none)
        fp.apply_qualification(none, 0, 2)
        fresh = _fb_row(h2h_last5=[
            {'date': _d(30), 'home': 'Guif', 'away': 'Drott', 'winner': 'home'},
            {'date': _d(60), 'home': 'Drott', 'away': 'Guif', 'winner': 'away'}],
            h2h_count=2, home_wins_in_h2h_last5=2)
        fp.apply_recency(fresh, today)
        fp.score_row(fresh)
        fp.apply_qualification(fresh, 0, 2)
        assert not any(r.startswith('zrodla') for r in none['skip_reasons'])
        assert none['qualifies'] == fresh['qualifies']

    def test_hockey_two_way_market(self):
        row = {'sport': 'hockey', 'favorite': 'home', 'forebet_fav_prob': 60,
               'forebet_draw_prob': None,
               'home_odds': 2.0, 'draw_odds': 4.0, 'away_odds': 3.0}
        imp = implied_probs(row)
        assert set(imp) == {'home', 'away'}
        assert market_gap_pp(row) == pytest.approx(0.0)

    def test_hockey_three_way_when_forebet_has_draw(self):
        row = {'sport': 'hockey', 'favorite': 'home', 'forebet_fav_prob': 60,
               'forebet_draw_prob': 20,
               'home_odds': 2.0, 'draw_odds': 4.0, 'away_odds': 3.0}
        assert set(implied_probs(row)) == {'home', 'draw', 'away'}

    def test_unmatched_winner_is_neutral(self):
        row = {'home_team': 'Poland W', 'away_team': 'Spain W', 'favorite': 'home',
               'h2h_last5': [
                   {'date': _d(30), 'home': 'Polska K', 'away': 'Hiszpania K', 'winner': 'home'},
                   {'date': _d(60), 'home': 'Poland W', 'away': 'Spain W', 'winner': 'home'},
                   {'date': _d(90), 'home': 'Spain W', 'away': 'Poland W', 'winner': 'away'}]}
        eff = effective_h2h(row, TODAY)
        assert eff['count'] == 2.0 and eff['fav_wins'] == 2.0 and eff['unattributed'] == 1

    def test_sports_only_twierdza_market_gap(self, tmp_path, monkeypatch):
        dd = TestDailyDigest()._setup(tmp_path, monkeypatch, TestDailyDigest()._tw())
        sp = TestDailyDigest()._tw(homeTeam='Gap FC', awayTeam='Other FC',
                                   forebet={'homeProb': 90, 'awayProb': 10},
                                   odds={'home': 2.5, 'away': 1.6})
        ok = TestDailyDigest()._tw(homeTeam='Fine FC', awayTeam='Other2 FC')
        (tmp_path / 'results' / 'matches_2026-10-20_basketball.json').write_text(
            json.dumps({'matches': [sp, ok]}), encoding='utf-8')
        picks = [r['pick'] for r in dd.twierdza('2026-10-20')]
        assert 'Gap FC' not in picks and 'Fine FC' in picks

    def test_digest_revalidates_persisted_top(self, tmp_path, monkeypatch):
        dd = TestDailyDigest()._setup(tmp_path, monkeypatch, TestDailyDigest()._tw())
        (tmp_path / 'results' / 'top_2026-10-20.json').write_text(json.dumps([
            {'sport': 'football', 'time': '18:00', 'match': 'Home FC vs Away FC',
             'league': 'L', 'pick': 'Home FC'}]), encoding='utf-8')
        assert dd.collect('2026-10-20')['TOP']
        (tmp_path / 'results' / 'matches_2026-10-20_football_forebet.json').write_text(
            json.dumps({'matches': [_top_match(staleModel=True)]}), encoding='utf-8')
        assert dd.collect('2026-10-20')['TOP'] == []
    def test_friendlies_do_not_hide_season_start(self):
        # Przerwa letnia wypełniona sparingami: start = pierwszy mecz ligowy.
        raw = [{'date': _d(a), 'result': r, 'event': ev} for a, r, ev in (
            (3, 'L', 'Liga'), (10, 'L', 'Liga'), (20, 'W', 'Towarzyskie klubowe'),
            (27, 'W', 'Towarzyskie klubowe'), (80, 'W', 'Liga'))]
        row = {'home_form': [e['result'] for e in raw], 'home_form_dated': raw,
               'away_form': [], 'favorite': 'home'}
        apply_season(row, TODAY)
        assert row['home_season_match_count'] == 2 and row['early_season'] is True
        assert row['home_season_method'] == 'gap'

    def test_stale_model_no_edge_bonus(self):
        from prediction_data_contract import compute_data_quality as b
        base = {'favorite': 'home', 'scoring_prob': 80, 'home_odds': 2.0, 'away_odds': 2.0}
        assert b(dict(base)).market_model_gap == pytest.approx(30)
        assert b(dict(base, stale_model=True)).market_model_gap == 0.0

class TestReviewLoop4:
    @staticmethod
    def _fr_row(spec):
        raw = [{'date': _d(a), 'result': r,
                'event': 'Towarzyskie klubowe' if f else 'Liga'} for a, r, f in spec]
        return {'home_form': [e['result'] for e in raw], 'home_form_dated': raw,
                'away_form': [], 'favorite': 'home'}

    def test_three_friendlies_not_counted(self):
        # L L F F F bez przerwy > 35 dni (fallback 60 dni) → liczą się 2 mecze.
        row = self._fr_row([(3, 'L', 0), (8, 'L', 0), (14, 'W', 1), (20, 'W', 1), (26, 'W', 1)])
        apply_season(row, TODAY)
        assert row['home_season_form'] == ['L', 'L']
        assert row['home_season_match_count'] == 2 and row['early_season'] is True

    def test_two_friendlies_not_counted(self):
        row = self._fr_row([(3, 'L', 0), (8, 'L', 0), (14, 'L', 0), (20, 'W', 1), (26, 'W', 1)])
        apply_season(row, TODAY)
        assert row['home_season_match_count'] == 3 and row['early_season'] is True

    def test_winter_restart_with_friendlies(self):
        # Udokumentowane: przerwa zimowa > 35 dni po usunięciu sparingów = nowy start.
        row = self._fr_row([(3, 'W', 0), (10, 'W', 0), (20, 'W', 1), (30, 'W', 1), (60, 'W', 0)])
        apply_season(row, TODAY)
        assert row['home_season_method'] == 'gap' and row['early_season'] is True

    def test_pre_2000_two_digit_year(self):
        assert parse_ls_date('09.03.99') == date(1999, 3, 9)
        assert parse_ls_date('09.03.16') == date(2016, 3, 9)
        row = {'home_team': 'Guif', 'away_team': 'Drott', 'favorite': 'home',
               'h2h_last5': [{'date': '09.03.99', 'home': 'Guif', 'away': 'Drott',
                              'winner': 'home'}]}
        eff = effective_h2h(row, TODAY)
        assert eff['count'] == 0 and eff['all_stale'] is True

    def test_hockey_quoted_draw_uses_no_draw_conditional(self):
        # Forebet bez remisu → rynek warunkowy 'bez remisu': 0.5/(0.5+1/3) = 60%.
        row = {'sport': 'hockey', 'favorite': 'home', 'forebet_fav_prob': 80,
               'forebet_draw_prob': None,
               'home_odds': 2.0, 'draw_odds': 4.0, 'away_odds': 3.0}
        assert 100 * implied_probs(row)['home'] == pytest.approx(60.0)
        assert market_gap_pp(row) == pytest.approx(20.0)
        assert market_gap_pp(dict(row, forebet_fav_prob=81)) > recency.STALE_MODEL_PP

    def test_neutral_h2h_not_reported_available(self):
        from prediction_data_contract import compute_data_quality as b
        dq = b({'h2h_neutral': True, 'h2h_count': 0, 'favorite': 'home',
                'home_odds': 2.0, 'away_odds': 2.0})
        assert dq.h2h_available is False and dq.h2h_neutral is True
        real = b({'h2h_count': 3, 'favorite': 'home', 'home_odds': 2.0, 'away_odds': 2.0})
        assert dq.quality_score == pytest.approx(real.quality_score - 0.05)

    def test_stale_grade_lowered_once_after_cap(self):
        row = {'stale_model': True, 'prediction_grade': 'B'}
        lower_grade_if_stale(row)
        lower_grade_if_stale(row)
        assert row['prediction_grade'] == 'C' and row['prediction_grade_raw'] == 'B'

    def test_sports_row_gets_season_flags(self):
        import livesport_h2h_scraper as ls
        adv = {'home_form_overall_dated': [{'date': _d(a), 'result': 'W'} for a in (3, 10, 17)]
               + [{'date': _d(120), 'result': 'W'}, {'date': _d(130), 'result': 'W'}]}
        out = {'home_form': list('WWWWW'), 'away_form': []}
        ls._apply_season_flags(out, adv, False)
        assert out['early_season'] is True and 'favorite' not in out
