"""Tests for store-derived recent form.

The leak rule is the whole point: form for a match must be built only from
matches that finished before it started. Table-tennis players play three times
a day, so "before" has to mean strictly earlier, not same-day-or-earlier.
"""

import json

import pytest

from team_form import FORM_WINDOW, Appearance, FormProvider


def settled(date, home, away, winner, sh=None, sa=None, sport='football'):
    return {'status': 'finished', 'winner': winner, 'date': date,
            'home_team': home, 'away_team': away, 'score_home': sh,
            'score_away': sa, 'sport': sport}


@pytest.fixture
def provider():
    return FormProvider.from_rows([
        settled('2026-01-01', 'Alpha', 'Beta', 'home', 3, 1),
        settled('2026-01-05', 'Beta', 'Alpha', 'home', 2, 0),
        settled('2026-01-10', 'Alpha', 'Gamma', 'draw', 1, 1),
        settled('2026-01-15', 'Gamma', 'Alpha', 'home', 4, 2),
        settled('2026-01-20', 'Alpha', 'Beta', 'away', 0, 2),
    ])


class TestIndexing:
    def test_each_match_becomes_two_appearances(self):
        p = FormProvider.from_rows([settled('2026-01-01', 'A', 'B', 'home')])
        assert len(p.by_team['football|a']) == 1
        assert len(p.by_team['football|b']) == 1

    def test_winner_and_loser_get_opposite_letters(self):
        p = FormProvider.from_rows([settled('2026-01-01', 'A', 'B', 'home')])
        assert p.by_team['football|a'][0].outcome == 'W'
        assert p.by_team['football|b'][0].outcome == 'L'

    def test_draw_is_a_draw_for_both(self):
        p = FormProvider.from_rows([settled('2026-01-01', 'A', 'B', 'draw')])
        assert p.by_team['football|a'][0].outcome == 'D'
        assert p.by_team['football|b'][0].outcome == 'D'

    def test_scores_are_recorded_from_each_side(self):
        p = FormProvider.from_rows([settled('2026-01-01', 'A', 'B', 'home', 3, 1)])
        assert p.by_team['football|a'][0].score_text == '3-1'
        assert p.by_team['football|b'][0].score_text == '1-3'

    def test_venue_flag_is_recorded(self):
        p = FormProvider.from_rows([settled('2026-01-01', 'A', 'B', 'home')])
        assert p.by_team['football|a'][0].at_home is True
        assert p.by_team['football|b'][0].at_home is False

    def test_unfinished_and_unresolved_rows_are_ignored(self):
        p = FormProvider.from_rows([
            {'status': 'not_finished', 'winner': 'home', 'date': '2026-01-01',
             'home_team': 'A', 'away_team': 'B'},
            settled('2026-01-02', 'A', 'B', 'pending'),
            settled('2026-01-03', '', 'B', 'home'),
            settled('', 'A', 'B', 'home'),
        ])
        assert p.by_team == {}

    def test_newest_first(self, provider):
        dates = [a.date for a in provider.by_team['football|alpha']]
        assert dates == sorted(dates, reverse=True)

    def test_names_are_normalised(self):
        p = FormProvider.from_rows([settled('2026-01-01', '  Alpha   FC ', 'B', 'home')])
        assert p.form('alpha fc') == ['W']
        assert p.form('ALPHA FC') == ['W']


class TestSportsDoNotMix:
    """A club name can belong to several sports at once.

    Found by a smoke run against the real store: the football side of ŁKS Łódź
    came back with 87-96 and 88-69 among its last three results, because the
    basketball club shares the name.
    """

    @pytest.fixture
    def shared_name(self):
        return FormProvider.from_rows([
            settled('2026-05-01', 'LKS', 'Rival FC', 'home', 2, 1, 'football'),
            settled('2026-05-02', 'LKS', 'Rival BC', 'away', 88, 96, 'basketball'),
            settled('2026-05-03', 'LKS', 'Other FC', 'home', 3, 0, 'football'),
        ])

    def test_football_form_excludes_basketball(self, shared_name):
        assert shared_name.form('LKS', sport='football') == ['W', 'W']

    def test_basketball_form_excludes_football(self, shared_name):
        assert shared_name.form('LKS', sport='basketball') == ['L']

    def test_recent_matches_stay_within_the_sport(self, shared_name):
        match = {'home_team': 'LKS', 'away_team': 'Other FC',
                 'sport': 'football', 'match_date': '2026-06-01'}
        shared_name.attach(match)
        assert all(r['score'] in ('2-1', '3-0')
                   for r in match['home_recent_matches'])

    def test_ambiguous_name_without_a_sport_returns_nothing(self, shared_name):
        assert shared_name.form('LKS') == []

    def test_unambiguous_name_without_a_sport_still_resolves(self, shared_name):
        assert shared_name.form('Rival FC') == ['L']

    def test_unknown_sport_for_a_known_name_returns_nothing(self, shared_name):
        assert shared_name.form('LKS', sport='hockey') == []


class TestNoLeak:
    def test_before_excludes_the_match_itself(self, provider):
        # Alpha played on the 10th; form for that date must not contain it.
        assert provider.form('Alpha', before='2026-01-10') == ['L', 'W']

    def test_same_day_matches_are_excluded(self):
        p = FormProvider.from_rows([
            settled('2026-03-01', 'Player', 'X', 'home'),
            settled('2026-03-01', 'Player', 'Y', 'home'),
            settled('2026-02-28', 'Player', 'Z', 'away'),
        ])
        assert p.form('Player', before='2026-03-01') == ['L']

    def test_future_matches_never_appear(self, provider):
        assert provider.form('Alpha', before='2026-01-02') == ['W']

    def test_no_before_date_returns_everything(self, provider):
        assert len(provider.form('Alpha')) == 5

    def test_unknown_team_is_empty_not_an_error(self, provider):
        assert provider.form('Nobody', before='2026-06-01') == []


class TestVenueSplit:
    def test_home_venue_only_counts_home_appearances(self, provider):
        for app in provider.appearances('Alpha', venue='home'):
            assert app.at_home is True

    def test_away_venue_only_counts_away_appearances(self, provider):
        for app in provider.appearances('Alpha', venue='away'):
            assert app.at_home is False

    def test_venue_split_partitions_the_history(self, provider):
        home = provider.appearances('Alpha', venue='home', window=99)
        away = provider.appearances('Alpha', venue='away', window=99)
        total = provider.appearances('Alpha', window=99)
        assert len(home) + len(away) == len(total)

    def test_alpha_home_form_matches_the_fixtures(self, provider):
        # Alpha at home: 01-01 W (3-1), 01-10 D (1-1), 01-20 L (0-2).
        assert provider.form('Alpha', venue='home') == ['L', 'D', 'W']

    def test_alpha_away_form_matches_the_fixtures(self, provider):
        # Alpha away: 01-05 L, 01-15 L.
        assert provider.form('Alpha', venue='away') == ['L', 'L']


class TestWindow:
    def test_window_caps_the_result(self):
        rows = [settled(f'2026-04-{d:02d}', 'Machine', f'Foe{d}', 'home')
                for d in range(1, 26)]
        p = FormProvider.from_rows(rows)
        assert len(p.form('Machine')) == FORM_WINDOW
        assert len(p.form('Machine', window=3)) == 3

    def test_default_window_is_ten(self):
        assert FORM_WINDOW == 10

    def test_window_takes_the_most_recent(self):
        rows = [settled(f'2026-04-{d:02d}', 'Team', f'Foe{d}',
                        'home' if d > 20 else 'away') for d in range(1, 26)]
        p = FormProvider.from_rows(rows)
        assert p.form('Team', window=4) == ['W', 'W', 'W', 'W']


class TestDisplayOnlyMode:
    """The pipeline shows store form without letting it score.

    Measured on settled rows carrying real prices, feeding store form to the
    engine lowered ROI in both sports with a credible sample, so the recent
    matches belong in the email card and nowhere near the pick.
    """

    def test_recent_matches_are_still_written(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-02-01'}
        provider.attach(match, set_form_fields=False)
        assert match['home_recent_matches']
        assert match['away_recent_matches']

    def test_no_engine_readable_form_field_is_set(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-02-01'}
        provider.attach(match, set_form_fields=False)
        for field in ('home_form_overall', 'home_form_home',
                      'away_form_overall', 'away_form_away'):
            assert field not in match

    def test_existing_scraper_form_is_left_intact(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-02-01',
                 'home_form_overall': ['W', 'W', 'W']}
        provider.attach(match, set_form_fields=False)
        assert match['home_form_overall'] == ['W', 'W', 'W']

    def test_default_still_sets_the_form_fields(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-02-01'}
        provider.attach(match)
        assert match['home_form_overall']


class TestMinHistoryGate:
    def test_a_thin_history_is_not_used(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-02-01'}
        provider.attach(match, min_history=99)
        assert 'home_form_overall' not in match

    def test_a_sufficient_history_is_used(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-02-01'}
        provider.attach(match, min_history=3)
        assert match['home_form_overall'] == ['L', 'L', 'D', 'L', 'W']

    def test_gate_counts_history_before_the_match_only(self, provider):
        early = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-01-06'}
        provider.attach(early, min_history=3)
        assert 'home_form_overall' not in early

    def test_zero_gate_disables_the_check(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-02-01'}
        provider.attach(match, min_history=0)
        assert match['home_form_overall']

    def test_recent_matches_ignore_the_gate(self, provider):
        """The list is for reading; a short history is still worth showing."""
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'football', 'match_date': '2026-02-01'}
        provider.attach(match, min_history=99)
        assert match['home_recent_matches']


class TestAttach:
    def test_fills_all_four_form_fields(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'match_date': '2026-02-01'}
        provider.attach(match)
        assert match['home_form_overall'] == ['L', 'L', 'D', 'L', 'W']
        assert match['home_form_home'] == ['L', 'D', 'W']
        assert match['away_form_overall']
        assert match['away_form_away']

    def test_respects_the_match_date(self, provider):
        early = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'match_date': '2026-01-06'}
        provider.attach(early)
        assert early['home_form_overall'] == ['L', 'W']

    def test_scraper_form_is_not_overwritten_by_default(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'match_date': '2026-02-01',
                 'home_form_overall': ['W', 'W', 'W']}
        provider.attach(match)
        assert match['home_form_overall'] == ['W', 'W', 'W']

    def test_overwrite_replaces_scraper_form(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'match_date': '2026-02-01',
                 'home_form_overall': ['W', 'W', 'W']}
        provider.attach(match, overwrite=True)
        assert match['home_form_overall'] == ['L', 'L', 'D', 'L', 'W']

    def test_empty_scraper_form_is_filled(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'match_date': '2026-02-01', 'home_form_overall': []}
        provider.attach(match)
        assert match['home_form_overall'] == ['L', 'L', 'D', 'L', 'W']

    def test_recent_matches_carry_dates_and_scores(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'match_date': '2026-02-01'}
        provider.attach(match)
        recent = match['home_recent_matches']
        assert recent[0]['date'] == '2026-01-20'
        assert recent[0]['score'] == '0-2'
        assert recent[0]['outcome'] == 'L'
        assert recent[0]['opponent'] == 'Beta'

    def test_unknown_teams_leave_the_match_untouched(self, provider):
        match = {'home_team': 'Nobody', 'away_team': 'Ghost',
                 'match_date': '2026-02-01'}
        provider.attach(match)
        assert 'home_form_overall' not in match
        assert 'home_recent_matches' not in match

    def test_missing_team_names_do_not_raise(self, provider):
        match = {'match_date': '2026-02-01'}
        provider.attach(match)
        assert match == {'match_date': '2026-02-01'}

    def test_falls_back_to_date_when_match_date_absent(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta',
                 'date': '2026-01-06'}
        provider.attach(match)
        assert match['home_form_overall'] == ['L', 'W']

    def test_without_any_date_it_uses_full_history(self, provider):
        match = {'home_team': 'Alpha', 'away_team': 'Beta'}
        provider.attach(match)
        assert len(match['home_form_overall']) == 5


class TestFromStore:
    def test_missing_file_yields_an_empty_provider(self):
        p = FormProvider.from_store('outputs/definitely_not_here.json')
        assert p.by_team == {}
        assert p.form('Alpha') == []

    def test_broken_json_yields_an_empty_provider(self, tmp_path):
        bad = tmp_path / 'store.json'
        bad.write_text('{not json', encoding='utf-8')
        assert FormProvider.from_store(str(bad)).by_team == {}

    def test_reads_a_real_store_shape(self, tmp_path):
        store = tmp_path / 'store.json'
        store.write_text(json.dumps({
            'https://x/match/1': settled('2026-01-01', 'Alpha', 'Beta',
                                         'home', 3, 1),
            'https://x/match/2': settled('2026-01-02', 'Beta', 'Alpha',
                                         'home', 1, 0),
        }), encoding='utf-8')
        p = FormProvider.from_store(str(store))
        assert p.form('Alpha') == ['L', 'W']
        assert p.played('Alpha') == 2
