"""The AI fallback chains must not point at retired models.

On 2026-08-02 the whole "SofaScore AI Vision" path ended in "wyczerpano modele":
both Groq vision entries returned 404 because they had already been shut down —
`meta-llama/llama-4-scout-17b-16e-instruct` on 17.07.2026 and
`meta-llama/llama-4-maverick-17b-128e-instruct` on 09.03.2026. Two Gemini entries
returned 404 for the same reason. The text chain returned 429, which is a spent
quota rather than a bad name, and its models are themselves due to shut down on
16.08.2026.

Source: https://console.groq.com/docs/deprecations

These tests pin the dead names out and keep the chains overridable, so the next
deprecation is a configuration change rather than an outage.
"""

import importlib

import pytest

import sofascore_scraper as ss

# Shutdown dates per Groq's deprecation page, and the Gemini ids the production
# log showed returning 404.
RETIRED = {
    'meta-llama/llama-4-scout-17b-16e-instruct',
    'meta-llama/llama-4-maverick-17b-128e-instruct',
    'qwen/qwen3-32b',
    'moonshotai/kimi-k2-instruct',
    'moonshotai/kimi-k2-instruct-0905',
    'llama3-70b-8192',
    'llama3-8b-8192',
    'gemini-1.5-flash-002',
    'gemini-1.5-flash-8b',
    'gemini-2.0-flash-exp',
}

# Shut down 16.08.2026 — must not be the only thing we rely on.
SUNSETTING = {'llama-3.3-70b-versatile', 'llama-3.1-8b-instant'}


def all_chains():
    return (list(ss._GROQ_VISION_MODEL_CHAIN)
            + list(ss._GROQ_TEXT_MODEL_CHAIN)
            + list(ss._GEMINI_MODEL_CHAIN))


class TestNoRetiredModels:
    def test_no_chain_contains_a_retired_model(self):
        offenders = sorted(set(all_chains()) & RETIRED)
        assert not offenders, f'wycofane modele w łańcuchach: {offenders}'

    def test_no_chain_depends_only_on_a_sunsetting_model(self):
        for name, chain in (('vision', ss._GROQ_VISION_MODEL_CHAIN),
                            ('text', ss._GROQ_TEXT_MODEL_CHAIN)):
            live = [m for m in chain if m not in SUNSETTING]
            assert live, f'łańcuch {name} zawiera tylko modele do wyłączenia'

    def test_every_chain_is_non_empty(self):
        assert ss._GROQ_VISION_MODEL_CHAIN
        assert ss._GROQ_TEXT_MODEL_CHAIN
        assert ss._GEMINI_MODEL_CHAIN

    def test_model_ids_look_like_ids(self):
        for model in all_chains():
            assert model == model.strip()
            assert ' ' not in model
            assert model


class TestVisionChainIsVisionCapable:
    def test_vision_chain_uses_a_multimodal_model(self):
        """GPT-OSS is text-only; the vision path needs a multimodal id."""
        assert any('qwen' in m for m in ss._GROQ_VISION_MODEL_CHAIN)

    def test_vision_chain_has_no_text_only_model(self):
        assert not any(m.startswith('openai/gpt-oss')
                       for m in ss._GROQ_VISION_MODEL_CHAIN)


class TestChainsAreOverridable:
    def test_env_var_replaces_the_vision_chain(self, monkeypatch):
        monkeypatch.setenv('SOFASCORE_GROQ_VISION_MODELS', 'vendor/a,vendor/b')
        reloaded = importlib.reload(ss)
        try:
            assert reloaded._GROQ_VISION_MODEL_CHAIN == ['vendor/a', 'vendor/b']
        finally:
            monkeypatch.delenv('SOFASCORE_GROQ_VISION_MODELS')
            importlib.reload(ss)

    def test_env_var_replaces_the_text_chain(self, monkeypatch):
        monkeypatch.setenv('SOFASCORE_GROQ_TEXT_MODELS', 'vendor/only')
        reloaded = importlib.reload(ss)
        try:
            assert reloaded._GROQ_TEXT_MODEL_CHAIN == ['vendor/only']
        finally:
            monkeypatch.delenv('SOFASCORE_GROQ_TEXT_MODELS')
            importlib.reload(ss)

    def test_blank_env_var_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv('SOFASCORE_GROQ_TEXT_MODELS', '   ')
        reloaded = importlib.reload(ss)
        try:
            assert reloaded._GROQ_TEXT_MODEL_CHAIN == \
                reloaded._GROQ_TEXT_MODEL_CHAIN_DEFAULT
        finally:
            monkeypatch.delenv('SOFASCORE_GROQ_TEXT_MODELS')
            importlib.reload(ss)

    def test_whitespace_and_empties_are_trimmed(self, monkeypatch):
        monkeypatch.setenv('SOFASCORE_GROQ_TEXT_MODELS', ' a , ,b ')
        reloaded = importlib.reload(ss)
        try:
            assert reloaded._GROQ_TEXT_MODEL_CHAIN == ['a', 'b']
        finally:
            monkeypatch.delenv('SOFASCORE_GROQ_TEXT_MODELS')
            importlib.reload(ss)
