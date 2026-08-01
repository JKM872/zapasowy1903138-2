"""Form has to reach the tennis engine, not just its feature extractor.

The engine kept two independent reads of the form fields: the extractor computed
a form estimate, and a separate `active` gate decided whether that estimate
counted. The two used different key lists, so form supplied as
`home_form_overall` — the field the scrapers, the email card and
team_form.FormProvider all use — produced a perfect estimate that was then
dropped from the weighted average.

The symptom was a Brier of exactly 0.5000 across 2494 held-out matches, equal to
the base rate, and a player on ten straight wins rated 50/50 against one on ten
straight losses. These tests pin both reads to the same keys.
"""

import pytest

from tennis_scoring_engine import (TennisFeatureExtractor, TennisScoringEngine,
                                   _first_form, _streak_len)

WINS = list('WWWWWWWWWW')
LOSSES = list('LLLLLLLLLL')


@pytest.fixture
def engine():
    return TennisScoringEngine()


def match(**extra):
    return dict({'home_team': 'Alpha', 'away_team': 'Beta',
                 'sport': 'tennis'}, **extra)


class TestFirstForm:
    def test_prefers_the_first_key_that_has_data(self):
        m = {'form_a': list('WWW'), 'home_form_overall': list('LLL')}
        assert _first_form(m, 'form_a', 'home_form_overall') == ['W', 'W', 'W']

    def test_skips_a_key_that_is_present_but_empty(self):
        m = {'form_a': [], 'home_form_overall': list('WLW')}
        assert _first_form(m, 'form_a', 'home_form_overall') == ['W', 'L', 'W']

    def test_skips_a_key_holding_junk(self):
        m = {'form_a': 'nonsense', 'home_form_overall': list('WW')}
        assert _first_form(m, 'form_a', 'home_form_overall') == ['W', 'W']

    def test_no_keys_present_is_empty(self):
        assert _first_form({}, 'form_a', 'home_form_overall') == []

    def test_reads_a_string_form(self):
        assert _first_form({'form_a': 'WLW'}, 'form_a') == ['W', 'L', 'W']

    def test_reads_a_separated_string_form(self):
        assert _first_form({'form_a': 'W-L-W'}, 'form_a') == ['W', 'L', 'W']

    def test_reads_a_stringified_list(self):
        assert _first_form({'form_a': "['W', 'L', 'W']"}, 'form_a') == ['W', 'L', 'W']

    def test_draws_become_losses_in_tennis(self):
        assert _first_form({'form_a': 'WDL'}, 'form_a') == ['W', 'L', 'L']

    def test_a_concatenated_run_is_not_truncated(self):
        """"WLWLW" is five results, not one — truncating it hid the signal."""
        assert len(_first_form({'form_a': 'WLWLW'}, 'form_a')) == 5


class TestFormActuallyMovesThePrediction:
    def test_overall_field_moves_the_probability(self, engine):
        st = engine.score_match(match(home_form_overall=WINS,
                                      away_form_overall=LOSSES))
        assert st.cal_a > 0.6, 'forma przez home_form_overall musi wpływać na typ'

    def test_native_and_overall_fields_agree(self, engine):
        native = engine.score_match(match(form_a=WINS, form_b=LOSSES))
        overall = engine.score_match(match(home_form_overall=WINS,
                                           away_form_overall=LOSSES))
        assert native.cal_a == pytest.approx(overall.cal_a)

    def test_reversing_the_form_reverses_the_pick(self, engine):
        a_strong = engine.score_match(match(home_form_overall=WINS,
                                            away_form_overall=LOSSES))
        b_strong = engine.score_match(match(home_form_overall=LOSSES,
                                            away_form_overall=WINS))
        assert a_strong.best_pick != b_strong.best_pick
        assert a_strong.cal_a == pytest.approx(b_strong.cal_b)

    def test_no_form_stays_at_an_even_split(self, engine):
        st = engine.score_match(match())
        assert st.cal_a == pytest.approx(0.5)

    def test_form_on_one_side_only_does_not_activate(self, engine):
        """One-sided form is not a comparison, so it must abstain."""
        st = engine.score_match(match(home_form_overall=WINS))
        assert st.cal_a == pytest.approx(0.5)

    def test_home_form_legacy_field_still_works(self, engine):
        st = engine.score_match(match(home_form=WINS, away_form=LOSSES))
        assert st.cal_a > 0.6

    def test_probabilities_still_sum_to_one(self, engine):
        st = engine.score_match(match(home_form_overall=WINS,
                                      away_form_overall=LOSSES))
        assert st.cal_a + st.cal_b == pytest.approx(1.0)


class TestExtractorAndGateAgree:
    """Whenever the extractor sees form, the engine must count it."""

    @pytest.mark.parametrize('keys', [
        ('form_a', 'form_b'),
        ('home_form_overall', 'away_form_overall'),
        ('home_form', 'away_form'),
    ])
    def test_every_supported_key_pair_is_honoured(self, engine, keys):
        home_key, away_key = keys
        m = match(**{home_key: WINS, away_key: LOSSES})
        feats = TennisFeatureExtractor().extract(m)
        assert feats['form_a'] > feats['form_b'], 'ekstraktor musi widzieć formę'
        assert engine.score_match(m).cal_a > 0.6, 'silnik musi ją policzyć'


class TestStreakStaysNormalised:
    def test_ten_match_win_run_does_not_exceed_one(self):
        feats = TennisFeatureExtractor().extract(
            match(form_a=WINS, form_b=LOSSES))
        assert 0.0 <= feats['streak_a'] <= 1.0
        assert 0.0 <= feats['streak_b'] <= 1.0

    def test_streak_length_itself_is_unclamped(self):
        assert _streak_len(WINS, 'W') == 10

    def test_five_match_run_still_reaches_the_top(self):
        feats = TennisFeatureExtractor().extract(
            match(form_a=list('WWWWW'), form_b=LOSSES))
        assert feats['streak_a'] == pytest.approx(1.0)
