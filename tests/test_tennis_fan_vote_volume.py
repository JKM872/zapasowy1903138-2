"""A fan vote should weigh as much as the crowd behind it.

The tennis engine counted any non-zero percentage as a full-strength source, so
a reading from twelve voters carried the same weight as one from 74 392 — and an
AI-estimated reading, which the scraper writes with `sofascore_total_votes = 0`
and `sofascore_estimated_by_ai`, steered the pick as if it were real crowd data.
Measured before the fix: an extreme 90/10 estimate moved cal_a from 0.5000 to
0.5286 in tennis while the football engine correctly ignored it.

The football engine already discounted by volume; these tests pin tennis to the
same rule.
"""

import pytest

from tennis_scoring_engine import (TennisFeatureExtractor, TennisScoringEngine,
                                   _vote_volume_factor)


def match(votes=None, home_pct=90, away_pct=10, **extra):
    m = {
        'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'tennis',
        'home_odds': 2.00, 'away_odds': 2.00,
        'sofascore_home_win_prob': home_pct,
        'sofascore_away_win_prob': away_pct,
    }
    if votes is not None:
        m['sofascore_total_votes'] = votes
    m.update(extra)
    return m


def bare():
    return {'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'tennis',
            'home_odds': 2.00, 'away_odds': 2.00}


class TestVolumeFactor:
    def test_no_votes_is_no_signal(self):
        assert _vote_volume_factor(0) == 0.0

    def test_negative_is_treated_as_none(self):
        assert _vote_volume_factor(-5) == 0.0

    def test_grows_with_the_crowd(self):
        assert (_vote_volume_factor(1) < _vote_volume_factor(50)
                < _vote_volume_factor(200) < _vote_volume_factor(1000))

    def test_saturates_at_full_weight(self):
        assert _vote_volume_factor(1000) == pytest.approx(1.0)
        assert _vote_volume_factor(100000) == pytest.approx(1.0)

    def test_stays_within_range(self):
        for v in (0, 1, 10, 999, 74392):
            assert 0.0 <= _vote_volume_factor(v) <= 1.0

    def test_matches_the_football_curve(self):
        from football_scoring_engine import _sofascore_confidence_factor
        for v in (0, 1, 50, 200, 1000, 5000):
            assert _vote_volume_factor(v) == pytest.approx(
                _sofascore_confidence_factor(v))


class TestEstimatedVoteDoesNotSteerThePick:
    def test_zero_vote_reading_is_ignored(self):
        e = TennisScoringEngine()
        assert e.score_match(match(votes=0)).cal_a == pytest.approx(
            e.score_match(bare()).cal_a)

    def test_ai_estimate_is_ignored(self):
        e = TennisScoringEngine()
        est = match(votes=0, sofascore_estimated_by_ai=True)
        assert e.score_match(est).cal_a == pytest.approx(
            e.score_match(bare()).cal_a)

    def test_a_real_crowd_still_counts(self):
        e = TennisScoringEngine()
        assert e.score_match(match(votes=3000)).cal_a > \
            e.score_match(bare()).cal_a

    def test_a_large_crowd_counts_more_than_a_handful(self):
        e = TennisScoringEngine()
        small = e.score_match(match(votes=12)).cal_a
        large = e.score_match(match(votes=74392)).cal_a
        base = e.score_match(bare()).cal_a
        assert base < small < large

    def test_missing_vote_count_still_works(self):
        """Legacy rows carry percentages without a count; treat as real."""
        e = TennisScoringEngine()
        legacy = match()
        legacy.pop('sofascore_total_votes', None)
        assert e.score_match(legacy).cal_a == pytest.approx(
            e.score_match(bare()).cal_a)

    def test_alternate_vote_field_is_read(self):
        e = TennisScoringEngine()
        m = match()
        m.pop('sofascore_total_votes', None)
        m['sofascore_votes'] = 3000
        assert e.score_match(m).cal_a > e.score_match(bare()).cal_a


class TestDataQualityReflectsIt:
    def test_zero_votes_does_not_count_towards_data_quality(self):
        f_est = TennisFeatureExtractor().extract(match(votes=0))
        f_none = TennisFeatureExtractor().extract(bare())
        assert f_est['_data_quality'] == pytest.approx(f_none['_data_quality'])

    def test_real_votes_do_count(self):
        f_real = TennisFeatureExtractor().extract(match(votes=3000))
        f_none = TennisFeatureExtractor().extract(bare())
        assert f_real['_data_quality'] > f_none['_data_quality']

    def test_volume_factor_is_exposed(self):
        f = TennisFeatureExtractor().extract(match(votes=1000))
        assert f['sofascore_volume_factor'] == pytest.approx(1.0)
