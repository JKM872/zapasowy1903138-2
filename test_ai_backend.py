"""Tests for the AI analysis backend (Gemini -> Groq) and its scoring contract.

Two defects are covered:

1. AI analysis produced nothing for the entire history of the project — 0
   predictions across 160k matches — because Gemini was unavailable and the
   analyser returned a SKIP placeholder instead of trying another provider.
   Groq is now a real backend using the same prompt and parser.

2. The scoring engine derived the AI's side from the FIRST CHARACTER of the
   prose prediction. A sentence like "Wisla is likely to win" resolved to 0.5,
   which the engine interprets as a DRAW signal — at full AI weight. The model
   now returns an explicit ``PICK: 1|X|2`` and the engine reads only that.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from football_scoring_engine import FootballScoringEngine  # noqa: E402


def _ai_response(pick='1', conf=82, rec='HIGH'):
    return (
        f"PICK: {pick}\n"
        "PREDICTION: Home side should edge this one.\n"
        f"CONFIDENCE: {conf}\n"
        "REASONING: Strong H2H and better form.\n"
        "KEY_FACTORS: H2H 3/5, home form\n"
        "RISK_FACTORS: Close odds\n"
        f"RECOMMENDATION: {rec}\n"
    )


class TestResponseParsing:
    def _parse(self, text):
        from gemini_analyzer import _parse_gemini_response
        return _parse_gemini_response(text)

    def test_pick_is_extracted(self):
        assert self._parse(_ai_response('2'))['pick'] == '2'

    def test_draw_pick_is_extracted(self):
        assert self._parse(_ai_response('X'))['pick'] == 'X'

    def test_decorated_pick_is_tolerated(self):
        out = self._parse("PICK: **1** (home win)\nCONFIDENCE: 70\n")
        assert out['pick'] == '1'

    def test_missing_pick_is_empty_not_guessed(self):
        out = self._parse("PREDICTION: Someone will win.\nCONFIDENCE: 60\n")
        assert out['pick'] == ''

    def test_confidence_and_recommendation(self):
        out = self._parse(_ai_response('1', 91, 'HIGH'))
        assert out['confidence'] == 91
        assert out['recommendation'] == 'HIGH'

    def test_factors_are_lists(self):
        out = self._parse(_ai_response())
        assert isinstance(out['key_factors'], list) and out['key_factors']
        assert isinstance(out['risk_factors'], list)


class TestScoringConsumesPickOnly:
    def _feats(self, **kw):
        m = {'home_team': 'A', 'away_team': 'B', 'sport': 'football',
             'home_odds': 2.0, 'draw_odds': 3.4, 'away_odds': 3.6}
        m.update(kw)
        return FootballScoringEngine().extractor.extract(m)

    def test_prose_prediction_no_longer_signals_a_draw(self):
        # The old code mapped 'W' (first char of "Wisla…") to 0.5 == draw.
        f = self._feats(gemini_prediction='Wisla is likely to win the match',
                        gemini_confidence=82)
        assert f['gemini_conf'] == 0.5, 'must abstain without a machine pick'
        assert f['gemini_pred'] == 0.5

    def test_explicit_pick_home(self):
        f = self._feats(gemini_pick='1', gemini_confidence=82)
        assert f['gemini_pred'] == 1.0
        assert f['gemini_conf'] == pytest.approx(0.82)

    def test_explicit_pick_away(self):
        f = self._feats(gemini_pick='2', gemini_confidence=70)
        assert f['gemini_pred'] == 0.0

    def test_explicit_pick_draw(self):
        f = self._feats(gemini_pick='X', gemini_confidence=60)
        assert f['gemini_pred'] == 0.5
        assert f['gemini_conf'] == pytest.approx(0.60)

    def test_legacy_bare_token_still_works(self):
        f = self._feats(gemini_prediction='2', gemini_confidence=64)
        assert f['gemini_pred'] == 0.0
        assert f['gemini_conf'] == pytest.approx(0.64)

    def test_pick_without_confidence_abstains(self):
        f = self._feats(gemini_pick='1', gemini_confidence=0)
        assert f['gemini_conf'] == 0.5

    def test_ai_pick_moves_the_prediction(self):
        engine = FootballScoringEngine()
        base = {'home_team': 'A', 'away_team': 'B', 'sport': 'football',
                'home_odds': 2.5, 'draw_odds': 3.3, 'away_odds': 2.5,
                'gemini_confidence': 90, 'gemini_recommendation': 'HIGH'}
        home = engine.score_match(dict(base, gemini_pick='1'))
        away = engine.score_match(dict(base, gemini_pick='2'))
        assert home.cal_home > away.cal_home, 'AI pick must influence the model'

    def test_high_recommendation_flag(self):
        f = self._feats(gemini_pick='1', gemini_confidence=80,
                        gemini_recommendation='HIGH')
        assert f['gemini_high'] == 1.0


class TestGroqBackend:
    def _groq_ok(self, body):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'choices': [{'message': {'content': body}}]}
        return resp

    def test_groq_used_when_gemini_unavailable(self, monkeypatch):
        monkeypatch.setenv('GROQ_API_KEY', 'k')
        import gemini_analyzer as ga
        monkeypatch.setattr(ga, 'GEMINI_AVAILABLE', False)

        models = MagicMock()
        models.status_code = 200
        models.json.return_value = {'data': [{'id': 'llama-3.3-70b-versatile'}]}

        import groq_client
        groq_client.reset_resolved_model()
        with patch('requests.post', return_value=self._groq_ok(_ai_response('2', 77))), \
             patch('requests.get', return_value=models):
            out = ga.analyze_match(home_team='A', away_team='B', sport='football')

        assert out['error'] is None
        assert out['pick'] == '2'
        assert out['confidence'] == 77
        assert out['ai_provider'].startswith('groq:')

    def test_no_backend_reports_clearly(self, monkeypatch):
        monkeypatch.delenv('GROQ_API_KEY', raising=False)
        import gemini_analyzer as ga
        import groq_client
        monkeypatch.setattr(ga, 'GEMINI_AVAILABLE', False)
        monkeypatch.setattr(groq_client, 'api_key', lambda: None)

        out = ga.analyze_match(home_team='A', away_team='B', sport='football')
        assert out['recommendation'] == 'SKIP'
        assert out['error'] == 'No AI backend available'

    def test_prompt_asks_for_a_machine_readable_pick(self):
        from gemini_analyzer import _build_analysis_prompt
        prompt = _build_analysis_prompt(
            home_team='A', away_team='B', sport='football', h2h_data=None,
            home_form=None, away_form=None, home_form_away=None,
            away_form_away=None, forebet_prediction=None, home_odds=None,
            away_odds=None, draw_odds=None, additional_info=None)
        assert 'PICK:' in prompt
        assert '1 = home win' in prompt
