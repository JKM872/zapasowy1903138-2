"""The mail provider argument must be checked before the scraping is wasted.

A local variable named `provider` in scrape_and_notify shadowed the function
parameter holding the mail provider, so a FormProvider instance reached
`SMTP_CONFIG[provider]`. The scrape ran for forty minutes, the manifests were
written, the workflow reported success — and no mail was ever sent, because the
failure surfaced as `TypeError: unhashable type: 'FormProvider'` after all the
work was done.

These tests pin the guard that turns that into an immediate, readable error, and
check the pipeline still passes a real provider name through.
"""

import inspect

import pandas as pd
import pytest

import scrape_and_notify
from email_notifier import SMTP_CONFIG, send_split_emails_by_sport


def _csv(tmp_path):
    path = tmp_path / 'matches.csv'
    pd.DataFrame([{
        'match_url': 'http://m1', 'home_team': 'A', 'away_team': 'B',
        'sport': 'basketball', 'home_odds': 1.80, 'away_odds': 2.10,
        'draw_odds': None, 'qualifies': True, 'channel_qualifies': True,
        'scoring_pick': '1',
    }]).to_csv(path, index=False, encoding='utf-8')
    return str(path)


class TestProviderGuard:
    @pytest.mark.parametrize('bad', [
        object(), 123, None, ['gmail'], {'gmail': 1}, 'protonmail',
    ])
    def test_a_non_provider_is_rejected_immediately(self, bad, tmp_path,
                                                    monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError) as exc:
            send_split_emails_by_sport(
                csv_file=_csv(tmp_path), to_email='a@b.test',
                from_email='c@d.test', password='x', provider=bad,
                date='2026-08-02')
        assert 'dostawca' in str(exc.value).lower()

    def test_the_error_names_the_allowed_values(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError) as exc:
            send_split_emails_by_sport(
                csv_file=_csv(tmp_path), to_email='a@b.test',
                from_email='c@d.test', password='x', provider='nope',
                date='2026-08-02')
        for name in SMTP_CONFIG:
            assert name in str(exc.value)

    def test_the_error_names_the_type_it_got(self, tmp_path, monkeypatch):
        """The original failure hid which object arrived; this must not."""
        monkeypatch.chdir(tmp_path)

        class FormProvider:
            pass

        with pytest.raises(ValueError) as exc:
            send_split_emails_by_sport(
                csv_file=_csv(tmp_path), to_email='a@b.test',
                from_email='c@d.test', password='x', provider=FormProvider(),
                date='2026-08-02')
        assert 'FormProvider' in str(exc.value)

    def test_a_real_provider_passes_the_guard(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Dummy credentials stop before SMTP, so reaching that point proves the
        # guard let a valid provider through.
        sent = send_split_emails_by_sport(
            csv_file=_csv(tmp_path), to_email='a@b.test',
            from_email='noreply@localhost', password='dummy',
            provider='gmail', date='2026-08-02')
        assert sent == 0

    def test_every_configured_provider_is_accepted(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for name in SMTP_CONFIG:
            sent = send_split_emails_by_sport(
                csv_file=_csv(tmp_path), to_email='a@b.test',
                from_email='noreply@localhost', password='dummy',
                provider=name, date='2026-08-02')
            assert sent == 0


class TestPipelineDoesNotShadowTheProvider:
    def test_scrape_and_send_email_still_takes_a_provider(self):
        sig = inspect.signature(scrape_and_notify.scrape_and_send_email)
        assert sig.parameters['provider'].default == 'gmail'

    def _assigned_names(self, func) -> set:
        """Names rebound anywhere inside *func*, via AST rather than text.

        Text matching cannot tell an assignment from a keyword argument: the
        legitimate call `send_split_emails_by_sport(provider=provider, ...)`
        looks exactly like a rebind of `provider` to a line-based check.
        """
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                if isinstance(node.target, ast.Name):
                    names.add(node.target.id)
            elif isinstance(node, ast.For):
                if isinstance(node.target, ast.Name):
                    names.add(node.target.id)
        return names

    def test_nothing_rebinds_the_mail_provider(self):
        """`provider` belongs to the mail provider and must stay a string."""
        assigned = self._assigned_names(scrape_and_notify.scrape_and_send_email)
        assert 'provider' not in assigned, (
            'nadpisanie parametru `provider` — dokładnie ten błąd wstrzymał wysyłkę')

    def test_the_form_step_uses_a_distinct_name(self):
        assigned = self._assigned_names(scrape_and_notify.scrape_and_send_email)
        assert 'form_provider' in assigned, (
            'krok formy ma trzymać FormProvider we własnej zmiennej')
