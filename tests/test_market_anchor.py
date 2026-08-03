"""Anchoring the published probability onto the bookmaker's price.

Why this exists: every filter tried on the model's own output — grade bands, odds
bands, favourite/underdog, EV thresholds — reversed sign on a held-out window.
That is the expected outcome when the model is less accurate than the price (in
tennis Brier 0.5060 against the market's 0.4157), because then "the model sees
value" largely marks the model's own errors and filtering harder concentrates
them.

Measured with tools/market_blend.py, trained before 2026-06-15 and judged after:
basketball at 0.75 was the best weight in BOTH windows (+5.8% and +25.9% ROI),
and tennis at 0.90 cut held-out staked volume from 1400 bets to 197 and the loss
from 137.7 units to 31.4.
"""

import pytest

from football_scoring_engine import FootballScoringEngine
from tennis_scoring_engine import TennisScoringEngine


def football_match(home_odds=2.00, draw_odds=3.40, away_odds=4.00, **extra):
    return dict({
        'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'basketball',
        'home_odds': home_odds, 'draw_odds': draw_odds, 'away_odds': away_odds,
        'home_form_overall': list('WWWWWWWWWW'),
        'away_form_overall': list('LLLLLLLLLL'),
        'home_wins_in_h2h_last5': 5, 'away_wins_in_h2h_last5': 0,
        'h2h_count': 5,
    }, **extra)


def tennis_match(home_odds=1.50, away_odds=2.60, **extra):
    return dict({
        'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'tennis',
        'home_odds': home_odds, 'away_odds': away_odds,
        'form_a': list('WWWWWWWWWW'), 'form_b': list('LLLLLLLLLL'),
    }, **extra)


class TestFootballAnchorLookup:
    def test_measured_sport_uses_its_measured_value(self):
        assert FootballScoringEngine().market_anchor_for_sport('basketball') \
            == pytest.approx(0.75)

    def test_unmeasured_sport_is_left_alone(self):
        """Held-out samples of 51-95 matches do not justify a change."""
        e = FootballScoringEngine()
        for sport in ('hockey', 'volleyball', 'handball', 'football'):
            assert e.market_anchor_for_sport(sport) == 0.0

    def test_unknown_sport_falls_back_to_the_default(self):
        assert FootballScoringEngine().market_anchor_for_sport('kabaddi') \
            == FootballScoringEngine.MARKET_ANCHOR_DEFAULT

    def test_missing_sport_does_not_raise(self):
        assert FootballScoringEngine().market_anchor_for_sport(None) >= 0.0

    def test_lookup_is_case_insensitive(self):
        e = FootballScoringEngine()
        assert e.market_anchor_for_sport('BasketBall') == pytest.approx(0.75)

    @pytest.mark.parametrize('bad,expected', [(-0.5, 0.0), (2.0, 1.0)])
    def test_out_of_range_values_are_clamped(self, bad, expected):
        e = FootballScoringEngine()
        e.sport_market_anchor['basketball'] = bad
        assert e.market_anchor_for_sport('basketball') == expected


class TestFootballAnchorEffect:
    def _probs(self, engine, match):
        sm = engine.score_match(match)
        return sm.cal_home, sm.cal_draw, sm.cal_away

    def test_anchoring_moves_the_pick_towards_the_price(self):
        strong = FootballScoringEngine()
        strong.sport_market_anchor['basketball'] = 0.0
        anchored = FootballScoringEngine()
        anchored.sport_market_anchor['basketball'] = 0.9

        m = football_match(home_odds=4.00, away_odds=1.40, draw_odds=0)
        own = self._probs(strong, m)[0]
        pulled = self._probs(anchored, m)[0]
        # The model loves the home side on form; the price does not.
        assert pulled < own

    def test_full_anchor_reproduces_the_margin_free_price(self):
        e = FootballScoringEngine()
        e.sport_market_anchor['basketball'] = 1.0
        m = football_match(home_odds=2.00, away_odds=2.00, draw_odds=0)
        home, _, away = self._probs(e, m)
        assert home == pytest.approx(away, abs=0.02)

    def test_probabilities_still_sum_to_one(self):
        e = FootballScoringEngine()
        e.sport_market_anchor['basketball'] = 0.75
        assert sum(self._probs(e, football_match())) == pytest.approx(1.0)

    def test_no_draw_sport_keeps_zero_draw_mass(self):
        e = FootballScoringEngine()
        e.sport_market_anchor['basketball'] = 0.75
        home, draw, away = self._probs(e, football_match(draw_odds=0))
        assert draw == 0.0
        assert home + away == pytest.approx(1.0)

    def test_a_match_without_a_price_is_untouched(self):
        """There is nothing to anchor to, so the model must stand alone."""
        plain = FootballScoringEngine()
        plain.sport_market_anchor['basketball'] = 0.0
        anchored = FootballScoringEngine()
        anchored.sport_market_anchor['basketball'] = 0.9
        m = football_match(home_odds=0, draw_odds=0, away_odds=0)
        assert self._probs(plain, m) == pytest.approx(self._probs(anchored, m))

    def test_zero_anchor_changes_nothing(self):
        a = FootballScoringEngine()
        a.sport_market_anchor['basketball'] = 0.0
        b = FootballScoringEngine()
        b.sport_market_anchor.pop('basketball', None)
        m = football_match()
        assert self._probs(a, m) == pytest.approx(self._probs(b, m))


class TestFootballAnchorFromCalibration:
    def test_calibration_file_overrides_the_default(self, tmp_path):
        import json
        path = tmp_path / 'cal.json'
        path.write_text(json.dumps({'market_anchor': {'hockey': 0.5}}),
                        encoding='utf-8')
        e = FootballScoringEngine(calibration_path=str(path))
        assert e.market_anchor_for_sport('hockey') == pytest.approx(0.5)

    def test_out_of_range_file_value_is_ignored(self, tmp_path):
        import json
        path = tmp_path / 'cal.json'
        path.write_text(json.dumps({'market_anchor': {'basketball': 5.0}}),
                        encoding='utf-8')
        e = FootballScoringEngine(calibration_path=str(path))
        assert e.market_anchor_for_sport('basketball') == pytest.approx(0.75)

    def test_garbage_file_value_is_ignored(self, tmp_path):
        import json
        path = tmp_path / 'cal.json'
        path.write_text(json.dumps({'market_anchor': {'basketball': 'x'}}),
                        encoding='utf-8')
        e = FootballScoringEngine(calibration_path=str(path))
        assert e.market_anchor_for_sport('basketball') == pytest.approx(0.75)


class TestTennisAnchor:
    def test_default_is_the_measured_value(self):
        # 0.93 replaced 0.90 after export_settled started unpacking the nested
        # `tennis` block: with ranking and surface form present the engine scores
        # Brier 0.3808 against the market's 0.3813, and this weight was the best
        # in both windows (+3.5% earlier, +14.6% held out).
        assert TennisScoringEngine().market_anchor() == pytest.approx(0.93)

    def test_football_engine_agrees_on_the_tennis_anchor(self):
        """Both engines must not disagree about how anchored tennis is."""
        from football_scoring_engine import FootballScoringEngine
        assert FootballScoringEngine().market_anchor_for_sport('tennis') == \
            pytest.approx(TennisScoringEngine().MARKET_ANCHOR_DEFAULT)

    def test_anchoring_pulls_towards_the_price(self):
        e = TennisScoringEngine()
        m = tennis_match(home_odds=3.20, away_odds=1.35)

        e.calibration = dict(e.calibration, market_anchor=0.0)
        own = e.score_match(m).cal_a
        e.calibration = dict(e.calibration, market_anchor=0.9)
        pulled = e.score_match(m).cal_a

        assert pulled < own, 'cena nie zgadza sie z forma, wiec typ ma oslabnac'

    def test_full_anchor_matches_the_price(self):
        e = TennisScoringEngine()
        e.calibration = dict(e.calibration, market_anchor=1.0)
        st = e.score_match(tennis_match(home_odds=2.00, away_odds=2.00))
        assert st.cal_a == pytest.approx(0.5, abs=0.02)

    def test_probabilities_sum_to_one(self):
        st = TennisScoringEngine().score_match(tennis_match())
        assert st.cal_a + st.cal_b == pytest.approx(1.0)

    def test_anchor_can_flip_the_published_pick(self):
        """The pick follows the published number, so it must move with it."""
        e = TennisScoringEngine()
        m = tennis_match(home_odds=6.00, away_odds=1.15)
        e.calibration = dict(e.calibration, market_anchor=0.0)
        e.calibration = dict(e.calibration, market_anchor=0.0)
        own_pick = e.score_match(m).best_pick
        e.calibration = dict(e.calibration, market_anchor=1.0)
        anchored_pick = e.score_match(m).best_pick
        assert own_pick == 'A'
        assert anchored_pick == 'B'

    def test_a_match_without_a_price_is_untouched(self):
        e = TennisScoringEngine()
        m = tennis_match(home_odds=0, away_odds=0)
        e.calibration = dict(e.calibration, market_anchor=0.0)
        own = e.score_match(m).cal_a
        e.calibration = dict(e.calibration, market_anchor=0.9)
        assert e.score_match(m).cal_a == pytest.approx(own)

    @pytest.mark.parametrize('bad,expected', [(-1.0, 0.0), (3.0, 1.0),
                                              ('x', 0.93), (None, 0.93)])
    def test_bad_values_are_clamped_or_ignored(self, bad, expected):
        e = TennisScoringEngine()
        e.calibration = dict(e.calibration, market_anchor=bad)
        assert e.market_anchor() == pytest.approx(expected)

    def test_qualification_score_ignores_the_anchor(self):
        """The gate measures our conviction, not the bookmaker's.

        Deriving advanced_score from the anchored probability re-pointed the
        qualification gate at "how lopsided does the market think this is" and
        eliminated tennis entirely: 138 matches, 0 qualified, median score 5.5
        against a threshold of 45. The same fixtures scored 70-77 unanchored.
        """
        e = TennisScoringEngine()
        m = tennis_match(home_odds=1.50, away_odds=2.60,
                         home_wins_in_h2h_last5=4, away_wins_in_h2h_last5=0,
                         h2h_count=4, ranking_a=40, ranking_b=190)

        e.calibration = dict(e.calibration, market_anchor=0.0)
        unanchored = e.score_match(m).advanced_score
        e.calibration = dict(e.calibration, market_anchor=0.9)
        anchored = e.score_match(m).advanced_score

        assert anchored == pytest.approx(unanchored)

    def test_a_confident_pick_still_clears_the_threshold(self):
        e = TennisScoringEngine()
        m = tennis_match(home_odds=1.50, away_odds=2.60,
                         home_wins_in_h2h_last5=4, away_wins_in_h2h_last5=0,
                         h2h_count=4, ranking_a=40, ranking_b=190)
        assert e.score_match(m).advanced_score >= e.threshold

    def test_the_published_probability_is_still_anchored(self):
        """Only the gate is unanchored; what we claim must stay honest."""
        e = TennisScoringEngine()
        m = tennis_match(home_odds=1.50, away_odds=2.60)
        e.calibration = dict(e.calibration, market_anchor=0.0)
        loose = e.score_match(m).cal_a
        e.calibration = dict(e.calibration, market_anchor=0.9)
        assert e.score_match(m).cal_a < loose

    def test_ev_follows_the_anchored_probability(self):
        """EV must be computed from what we publish, not from a discarded number."""
        e = TennisScoringEngine()
        m = tennis_match(home_odds=3.20, away_odds=1.35)
        e.calibration = dict(e.calibration, market_anchor=0.0)
        loose = e.score_match(m)
        e.calibration = dict(e.calibration, market_anchor=0.9)
        tight = e.score_match(m)
        if tight.best_pick == loose.best_pick and tight.best_odds > 1:
            assert tight.ev == pytest.approx(
                tight.best_prob * tight.best_odds - 1.0, abs=1e-6)
