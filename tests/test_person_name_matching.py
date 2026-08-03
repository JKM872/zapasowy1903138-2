"""Matching 'Surname I.' against 'Firstname Surname'.

Tightening the team-search thresholds stopped a Spanish football fixture being
attached to an Australian hockey query, but it also started rejecting genuine
tennis players, because `similarity_score` is built for club names and collapses
on abbreviated person names:

    Gea A.          vs Alejandro Gea             0.33
    Kovacevic A.    vs Aleksandar Kovacevic      0.58   (threshold 0.60)
    Overbeck C. E.  vs Carol Elizabeth Overbeck  0.44

Lowering the threshold would have undone the cross-sport fix, so the shape is
recognised instead. The rule is deliberately narrow: it fires only when exactly
one side carries initials, which club names do not do.
"""

import pytest

from sofascore_scraper import (_OPPONENT_MIN_SIMILARITY,
                               _TEAM_SEARCH_MIN_SIMILARITY,
                               _person_name_similarity, similarity_score)

REAL_PAIRS = [
    ('Shapovalov D.', 'Denis Shapovalov'),
    ('Gea A.', 'Alejandro Gea'),
    ('Kovacevic A.', 'Aleksandar Kovacevic'),
    ('Borges N.', 'Nuno Borges'),
    ('Vanshelboim E.', 'Eric Vanshelboim'),
    ('Overbeck C. E.', 'Carol Elizabeth Overbeck'),
    ('Bronzetti L.', 'Lucia Bronzetti'),
    ('Niemeier J.', 'Jule Niemeier'),
]

WRONG_PAIRS = [
    ('Shapovalov D.', 'Nadal R.'),
    ('Gea A.', 'CF Badalona Futur'),
    ('Borges N.', 'Bronzetti L.'),
    ('Kovacevic A.', 'Aleksandar Djokovic'),
    ('Gea A.', 'Alejandro Munoz'),
]


class TestRealPlayersAreAccepted:
    @pytest.mark.parametrize('ours,theirs', REAL_PAIRS)
    def test_pair_clears_the_search_threshold(self, ours, theirs):
        assert similarity_score(ours, theirs) >= _TEAM_SEARCH_MIN_SIMILARITY

    @pytest.mark.parametrize('ours,theirs', REAL_PAIRS)
    def test_matching_is_symmetric(self, ours, theirs):
        assert similarity_score(ours, theirs) == pytest.approx(
            similarity_score(theirs, ours))

    def test_the_previously_failing_trio_now_passes(self):
        """The three pairs the tightened threshold started rejecting."""
        for ours, theirs in (('Gea A.', 'Alejandro Gea'),
                             ('Kovacevic A.', 'Aleksandar Kovacevic'),
                             ('Overbeck C. E.', 'Carol Elizabeth Overbeck')):
            assert similarity_score(ours, theirs) >= _TEAM_SEARCH_MIN_SIMILARITY


class TestWrongPairsStayRejected:
    @pytest.mark.parametrize('ours,theirs', WRONG_PAIRS)
    def test_pair_is_below_both_thresholds(self, ours, theirs):
        sim = similarity_score(ours, theirs)
        assert sim < _TEAM_SEARCH_MIN_SIMILARITY, f'sim={sim:.2f}'
        assert sim < _OPPONENT_MIN_SIMILARITY, f'sim={sim:.2f}'

    def test_a_contradicting_initial_is_rejected(self):
        """Same surname, wrong given name — must not be treated as a match."""
        assert _person_name_similarity('Kovacevic A.',
                                       'Novak Kovacevic') == 0.0

    def test_a_different_surname_scores_nothing(self):
        assert _person_name_similarity('Shapovalov D.', 'Denis Nadal') == 0.0


class TestTheRuleIsNarrow:
    def test_two_abbreviated_names_do_not_use_the_rule(self):
        assert _person_name_similarity('Shapovalov D.', 'Nadal R.') == 0.0

    def test_two_full_names_do_not_use_the_rule(self):
        assert _person_name_similarity('Denis Shapovalov',
                                       'Rafael Nadal') == 0.0

    def test_club_names_are_untouched(self):
        for a, b in (('Manchester United', 'Manchester City'),
                     ('CF Badalona Futur', 'CF Can Vidalet'),
                     ('Yunost Minsk', 'Brest')):
            assert _person_name_similarity(a, b) == 0.0

    def test_a_single_token_full_name_does_not_apply(self):
        assert _person_name_similarity('Gea A.', 'Gea') == 0.0

    def test_empty_input_is_safe(self):
        assert _person_name_similarity('', '') == 0.0
        assert _person_name_similarity('Gea A.', '') == 0.0


class TestExistingBehaviourPreserved:
    def test_identical_names_still_score_one(self):
        assert similarity_score('Shapovalov D.', 'Shapovalov D.') == \
            pytest.approx(1.0)

    def test_club_similarity_is_unchanged_for_known_pairs(self):
        assert similarity_score('Bayern Munich', 'Bayern München') >= 0.60
        assert similarity_score('Legia Warszawa', 'Legia Warsaw') >= 0.60

    def test_the_cross_sport_case_stays_rejected(self):
        """The failure the tightening existed to prevent."""
        assert similarity_score('CBR Brave', 'CF Badalona Futur') < \
            _TEAM_SEARCH_MIN_SIMILARITY
        assert similarity_score('Central Coast Rhinos', 'CF Can Vidalet') < \
            _OPPONENT_MIN_SIMILARITY
