"""The settled export must carry the tennis engine's own inputs.

`results/*.json` stores tennis features in a nested camelCase `tennis` block,
and `normalise_row` never unpacked it. Ranking (engine weight 0.11) and surface
form (0.12) were therefore missing from every exported row, so a coverage report
read 0% — indistinguishable from "the scraper never collects them". It does:
real rows carry rankingA=127 / rankingB=68 and populated surfaceFormA, present
in roughly two thirds of tennis fixtures.

The consequence was worse than a blind spot. Every tennis measurement we ran
re-scored rows with almost a quarter of the weight budget absent, so the
resulting Brier and ROI described a crippled engine.
"""

import pytest

from export_settled import normalise_row


def raw_tennis(**extra):
    row = {
        'homeTeam': 'Gea A.', 'awayTeam': 'Shapovalov D.',
        'sport': 'tennis', 'matchUrl': 'https://example.test/m1',
        'date': '2026-08-02', 'time': '13:30',
        'odds': {'home': 2.25, 'draw': None, 'away': 1.58},
        'h2h': {'home': 4, 'draw': 0, 'away': 0, 'total': 5, 'winRate': 0},
        'tennis': {
            'surface': 'hard',
            'rankingA': 127,
            'rankingB': 68,
            'probA': 42.7,
            'probB': 57.3,
            'surfaceFormA': ['W', 'W', 'W', 'W', 'L'],
            'surfaceFormB': [],
            'lastH2H': None,
            'lastMatchA': None,
            'lastMatchB': None,
            'skipReason': None,
        },
        'scoring': {'pick': '2', 'prob': 57.3, 'ev': -0.095, 'edge': -6.0,
                    'kelly': 0.0, 'confidence': 40.0, 'dataQuality': 0.57},
        'predictionGrade': 'B',
        'qualifies': False,
    }
    row.update(extra)
    return row


class TestTennisBlockIsUnpacked:
    def test_rankings_reach_the_row(self):
        row = normalise_row(raw_tennis())
        assert row['ranking_a'] == 127
        assert row['ranking_b'] == 68

    def test_surface_and_surface_form_reach_the_row(self):
        row = normalise_row(raw_tennis())
        assert row['surface'] == 'hard'
        assert row['surface_form_a'] == ['W', 'W', 'W', 'W', 'L']
        assert row['surface_form_b'] == []

    def test_the_engine_can_read_what_we_exported(self):
        """The whole point: these fields must land where the engine looks."""
        from tennis_scoring_engine import TennisFeatureExtractor
        row = normalise_row(raw_tennis())
        feats = TennisFeatureExtractor().extract(row)
        assert feats['ranking_advantage'] != 0.0, 'ranking musi wpływać'
        assert feats['surface_advantage'] != 0.0, 'forma na korcie musi wpływać'

    def test_ranking_absence_is_not_invented(self):
        row = normalise_row(raw_tennis(tennis={'surface': 'clay'}))
        assert row.get('ranking_a') is None
        assert row['surface'] == 'clay'

    def test_a_missing_tennis_block_does_not_raise(self):
        row = normalise_row(raw_tennis(tennis=None))
        assert row['home_team'] == 'Gea A.'
        assert 'ranking_a' not in row or row['ranking_a'] is None

    def test_a_non_dict_tennis_block_is_ignored(self):
        row = normalise_row(raw_tennis(tennis='nonsense'))
        assert row['home_team'] == 'Gea A.'


class TestNestedLastMatchIsFlattened:
    def test_date_and_result_are_flattened(self):
        row = normalise_row(raw_tennis(tennis={
            'lastMatchA': {'date': '28.07.26', 'result': 'W',
                           'score': '2-0', 'opponent': 'Nadal R.'},
        }))
        assert row['last_match_a_date'] == '28.07.26'
        assert row['last_match_a_result'] == 'W'
        assert row['last_match_a_score'] == '2-0'
        assert row['last_match_a_opponent'] == 'Nadal R.'

    def test_null_last_match_leaves_no_flat_fields(self):
        row = normalise_row(raw_tennis())
        assert 'last_match_a_date' not in row

    def test_both_sides_are_handled(self):
        row = normalise_row(raw_tennis(tennis={
            'lastMatchA': {'date': '28.07.26', 'result': 'W'},
            'lastMatchB': {'date': '27.07.26', 'result': 'L'},
        }))
        assert row['last_match_a_result'] == 'W'
        assert row['last_match_b_result'] == 'L'


class TestScoringAndGradeAreRecorded:
    def test_scoring_block_is_unpacked(self):
        row = normalise_row(raw_tennis())
        assert row['scoring_pick'] == '2'
        assert row['scoring_prob'] == pytest.approx(57.3)
        assert row['scoring_ev'] == pytest.approx(-0.095)
        assert row['scoring_edge'] == pytest.approx(-6.0)

    def test_grade_is_carried_from_camel_case(self):
        assert normalise_row(raw_tennis())['prediction_grade'] == 'B'

    def test_a_null_grade_is_not_carried(self):
        row = normalise_row(raw_tennis(predictionGrade=None))
        assert row.get('prediction_grade') is None

    def test_match_time_is_carried(self):
        assert normalise_row(raw_tennis())['match_time'] == '13:30'

    def test_missing_scoring_block_does_not_raise(self):
        row = normalise_row(raw_tennis(scoring=None))
        assert row.get('scoring_pick') is None


class TestFlatFieldsWin:
    def test_flat_snake_case_overrides_the_nested_block(self):
        """Rows straight from the pipeline already use flat names."""
        row = normalise_row(raw_tennis(ranking_a=5))
        assert row['ranking_a'] == 5

    def test_existing_behaviour_is_untouched(self):
        row = normalise_row(raw_tennis())
        assert row['home_odds'] == pytest.approx(2.25)
        assert row['away_odds'] == pytest.approx(1.58)
        assert row['h2h_count'] == 5
        assert row['sport'] == 'tennis'
