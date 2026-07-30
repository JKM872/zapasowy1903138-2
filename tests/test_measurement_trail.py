"""What the model claimed must survive next to what happened.

The accuracy report used to store only the pick, the odds and the outcome, so
the questions that decide how the product behaves could not be answered at all:
does Grade A beat Grade C, do positive-EV picks pay, is the stated probability
honest. A segmentation by model probability over 255 settled picks came back
empty, and match_url was dropped too, leaving no key to join anything back on.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import check_results as cr  # noqa: E402
from email_notifier import _MANIFEST_FIELDS  # noqa: E402

sys.path.insert(0, os.path.join(HERE, 'tools'))
import segment_performance as sp  # noqa: E402


CLAIMED = ('scoring_pick', 'scoring_prob', 'scoring_ev', 'scoring_edge',
           'scoring_confidence', 'advanced_score', 'prediction_grade')


def _manifest_row(**extra):
    row = {
        'match_url': 'https://x/1', 'home_team': 'Alpha', 'away_team': 'Beta',
        'sport': 'tennis', 'match_date': '2026-07-29', 'focus_team': 'home',
        'home_odds': 1.80, 'away_odds': 2.10,
        'scoring_pick': '1', 'scoring_prob': 81.9, 'scoring_ev': 0.105,
        'scoring_edge': 6.3, 'scoring_confidence': 74, 'advanced_score': 57.0,
        'prediction_grade': 'A',
    }
    row.update(extra)
    return row


def _finished(winner='Alpha', hs=2, as_=0):
    return {'https://x/1': {
        'status': 'finished', 'source': 'sofascore',
        'home_name': 'Alpha', 'away_name': 'Beta',
        'score_home': hs, 'score_away': as_,
        'winner_name': winner, 'is_draw': False,
    }}


class TestManifestCarriesTheClaim:
    @pytest.mark.parametrize('field', CLAIMED)
    def test_field_is_in_the_manifest(self, field):
        assert field in _MANIFEST_FIELDS


class TestEvaluateCarriesTheClaim:
    @pytest.mark.parametrize('field', CLAIMED)
    def test_field_reaches_the_detail(self, field):
        stats = cr.evaluate([_manifest_row()], _finished())
        assert stats['details'][0][field] == _manifest_row()[field]

    def test_outcome_is_still_settled_by_name(self):
        stats = cr.evaluate([_manifest_row()], _finished())
        assert stats['details'][0]['outcome'] == 'won'

    def test_missing_claim_is_not_invented(self):
        row = _manifest_row()
        for f in CLAIMED:
            row.pop(f)
        stats = cr.evaluate([row], _finished())
        assert stats['details'][0]['prediction_grade'] is None


class TestSavedSummaryKeepsTheClaim:
    @pytest.fixture
    def saved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        stats = cr.evaluate([_manifest_row()], _finished())
        path = cr.save_summary(stats, '2026-07-29')
        return json.load(open(path, encoding='utf-8'))

    @pytest.mark.parametrize('field', CLAIMED)
    def test_claim_survives_the_write(self, saved, field):
        assert saved['matches'][0][field] == _manifest_row()[field]

    def test_join_keys_survive(self, saved):
        """match_url was dropped, so nothing could be joined back."""
        row = saved['matches'][0]
        assert row['match_url'] == 'https://x/1'
        assert row['home_team'] == 'Alpha'
        assert row['away_team'] == 'Beta'
        assert row['match_date'] == '2026-07-29'

    def test_human_readable_names_are_kept_too(self, saved):
        assert saved['matches'][0]['home'] == 'Alpha'

    def test_resolution_is_traceable(self, saved):
        row = saved['matches'][0]
        assert row['winner_name'] == 'Alpha'
        assert row['resolved_by'] == 'sofascore'


class TestSegmentation:
    ROWS = [
        {'outcome': 'won', 'predicted': 'home', 'home_odds': 2.0,
         'away_odds': 1.8, 'sport': 'tennis', 'prediction_grade': 'A',
         'scoring_prob': 80.0, 'scoring_ev': 0.1},
        {'outcome': 'lost', 'predicted': 'home', 'home_odds': 2.0,
         'away_odds': 1.8, 'sport': 'tennis', 'prediction_grade': 'C',
         'scoring_prob': 60.0, 'scoring_ev': -0.1},
    ]

    def test_break_even_is_the_yardstick(self):
        res = sp.measure(self.ROWS)

        assert res['n'] == 2
        assert res['accuracy'] == pytest.approx(50.0)
        assert res['avg_odds'] == pytest.approx(2.0)
        assert res['breakeven'] == pytest.approx(50.0)
        assert res['roi'] == pytest.approx(0.0)
        assert res['net'] == pytest.approx(0.0)

    def test_roi_matches_the_hand_calculation(self):
        res = sp.measure([self.ROWS[0]])
        assert res['net'] == pytest.approx(100.0)
        assert res['roi'] == pytest.approx(100.0)

    def test_unpriced_picks_are_counted_but_not_staked(self):
        rows = self.ROWS + [{'outcome': 'won', 'predicted': 'home',
                             'home_odds': None, 'away_odds': None}]
        res = sp.measure(rows)

        assert res['n'] == 2
        assert res['n_unpriced'] == 1

    def test_all_unpriced_yields_nothing(self):
        assert sp.measure([{'outcome': 'won', 'predicted': 'home'}]) is None

    def test_picked_odds_follows_the_side(self):
        row = {'predicted': 'away', 'home_odds': 2.0, 'away_odds': 3.5}
        assert sp.picked_odds(row) == 3.5

    @pytest.mark.parametrize('value', [None, 'nan', 1.0, 0.5, 'x'])
    def test_unusable_prices_are_rejected(self, value):
        assert sp.picked_odds({'predicted': 'home', 'home_odds': value}) is None

    def test_market_side_labels(self):
        assert sp._market_side({'predicted': 'home', 'home_odds': 1.5,
                                'away_odds': 2.5}) == 'typ = faworyt rynku'
        assert sp._market_side({'predicted': 'home', 'home_odds': 2.5,
                                'away_odds': 1.5}) == 'typ = underdog'
        assert sp._market_side({'predicted': 'home'}) == 'brak kursów'

    def test_report_runs_on_real_shaped_rows(self, capsys):
        sp.report(self.ROWS, min_n=1)
        out = capsys.readouterr().out
        assert 'WSZYSTKO' in out
        assert 'PER GRADE' in out
        assert 'próg' in out

    def test_loader_skips_telegram_duplicates(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        payload = {'date': '2026-07-29', 'matches': self.ROWS}
        for name in ('results_summary_2026-07-29.json',
                     'results_summary_2026-07-29_telegram.json'):
            with open(f'outputs/{name}', 'w', encoding='utf-8') as fh:
                json.dump(payload, fh)

        assert len(sp.load_settled()) == 2, 'the telegram copy must not double-count'
