"""The AI pick must survive from the analyzer to the calibrator.

Background: the calibrator measured 0 AI coverage across 1000 settled matches,
which read as "the AI never ran". It had run — 100 of 315 mailed rows carried an
answer. The signal was lost in transit instead: `gemini_pick`, the only AI field
the scoring engine can consume, was absent from the manifest field list and from
the settled-data export, so prose was all that survived and prose cannot become
a 1/X/2 probability.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import export_settled as es  # noqa: E402
from email_notifier import _MANIFEST_FIELDS  # noqa: E402
from football_scoring_engine import FeatureExtractor  # noqa: E402


class TestManifestCarriesThePick:
    def test_pick_token_is_a_manifest_field(self):
        assert 'gemini_pick' in _MANIFEST_FIELDS

    def test_provider_is_recorded(self):
        """So a dead backend is visible rather than merely absent."""
        assert 'ai_provider' in _MANIFEST_FIELDS

    def test_prose_fields_are_still_kept_for_humans(self):
        for field in ('gemini_prediction', 'gemini_confidence',
                      'gemini_recommendation'):
            assert field in _MANIFEST_FIELDS


class TestExportCarriesThePick:
    def test_pick_reaches_the_settled_export(self):
        row = es.normalise_row({
            'homeTeam': 'Alpha', 'awayTeam': 'Beta', 'sport': 'football',
            'gemini_pick': '2', 'gemini_confidence': 70,
        })

        assert row['gemini_pick'] == '2'
        assert row['gemini_confidence'] == 70

    def test_ai_pick_is_accepted_as_an_alias(self):
        row = es.normalise_row({
            'homeTeam': 'Alpha', 'awayTeam': 'Beta', 'ai_pick': '1',
        })

        assert row['gemini_pick'] == '1'

    def test_nested_payload_is_read(self):
        row = es.normalise_row({
            'homeTeam': 'Alpha', 'awayTeam': 'Beta',
            'gemini': {'pick': 'X', 'confidence': 55, 'ai_provider': 'groq:x'},
        })

        assert row['gemini_pick'] == 'X'
        assert row['ai_provider'] == 'groq:x'

    def test_absent_ai_is_not_invented(self):
        row = es.normalise_row({'homeTeam': 'Alpha', 'awayTeam': 'Beta'})
        assert not row['gemini_pick']


class TestEngineConsumesThePick:
    @pytest.fixture
    def extractor(self):
        return FeatureExtractor()

    def test_pick_token_becomes_a_signal(self, extractor):
        feats = extractor.extract({
            'home_team': 'A', 'away_team': 'B',
            'gemini_pick': '1', 'gemini_confidence': 70,
        })

        assert feats['gemini_conf'] == pytest.approx(0.70)
        assert feats['gemini_pred'] == pytest.approx(1.0)

    def test_away_pick_points_away(self, extractor):
        feats = extractor.extract({
            'home_team': 'A', 'away_team': 'B',
            'gemini_pick': '2', 'gemini_confidence': 80,
        })

        assert feats['gemini_pred'] == pytest.approx(0.0)

    def test_prose_alone_makes_the_engine_abstain(self, extractor):
        """Prose used to be read by its first character and land on the draw."""
        feats = extractor.extract({
            'home_team': 'A', 'away_team': 'B',
            'gemini_prediction': 'Alpha is likely to win the match',
            'gemini_confidence': 80,
        })

        assert feats.get('gemini_conf', 0.5) == pytest.approx(0.5)

    def test_error_text_is_not_a_signal(self, extractor):
        """67 of 100 rows on 2026-07-28 stored 'Błąd API' as the prediction."""
        feats = extractor.extract({
            'home_team': 'A', 'away_team': 'B',
            'gemini_prediction': 'Błąd API (po 5 modelach)',
            'gemini_confidence': 0,
        })

        assert feats.get('gemini_conf', 0.5) == pytest.approx(0.5)

    def test_confidence_without_a_pick_is_ignored(self, extractor):
        feats = extractor.extract({
            'home_team': 'A', 'away_team': 'B', 'gemini_confidence': 90,
        })

        assert feats.get('gemini_conf', 0.5) == pytest.approx(0.5)


class TestGroqUnavailabilityIsAnnounced:
    def test_missing_key_is_reported_once(self, monkeypatch, capsys):
        """Silence here is what hid the outage for a thousand matches."""
        import gemini_analyzer as ga

        monkeypatch.setattr('groq_client.api_key', lambda: None)
        ga._GROQ_WARNED.clear()

        assert ga._analyze_with_groq('prompt') is None
        first = capsys.readouterr().out
        assert 'GROQ_API_KEY' in first

        # Repeating per match would bury the run in identical lines.
        assert ga._analyze_with_groq('prompt') is None
        assert capsys.readouterr().out == ''
