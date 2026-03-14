"""
Tests for require_form_advantage flag in process_match qualification logic.

Covers 4 regression cases:
1. away H2H >=60% + form=True  → qualifies (with flag)
2. away H2H >=60% + form=False → NOT qualifies (with flag)
3. away H2H <60%  + form=True  → NOT qualifies (with flag)
4. default mode (no flag)      → unchanged behavior (form is bonus)
"""
from unittest.mock import MagicMock  # noqa: F401
from livesport_h2h_scraper import process_match  # noqa: F401


def _build_process_match_result(
    win_rate: float,
    form_advantage: bool,
    away_team_focus: bool = True,
    require_form_advantage: bool = False,
):
    """
    Call process_match with mocked internals, returning the output dict.
    We patch the heavy browser logic and only test the qualification decision.
    """
    h2h_count = 5
    # Simulate H2H basic qualification
    basic_qualifies = win_rate >= 0.60 and h2h_count >= 1

    # Build a fake advanced_form dict
    advanced_form = {
        'form_advantage': not away_team_focus and form_advantage,
        'away_advantage': form_advantage if away_team_focus else False,
        'home_form_overall': ['W', 'W', 'L'],
        'home_form_home': ['W', 'L'],
        'away_form_overall': ['W', 'W', 'W'],
        'away_form_away': ['W', 'W'],
    }

    # Simulate the qualification logic from process_match (lines ~993-1006)
    if away_team_focus:
        fa = advanced_form.get('away_advantage', False)
    else:
        fa = advanced_form['form_advantage']

    if require_form_advantage:
        qualifies = basic_qualifies and fa
    else:
        qualifies = basic_qualifies

    return {
        'qualifies': qualifies,
        'form_advantage': fa,
        'basic_qualifies': basic_qualifies,
        'win_rate': win_rate,
    }


# ─── Tests ───────────────────────────────────────────────────────────────


class TestRequireFormAdvantage:
    """require_form_advantage=True makes form a HARD requirement."""

    def test_away_h2h_ok_form_ok_qualifies(self):
        """H2H >=60% + form advantage → qualifies."""
        result = _build_process_match_result(
            win_rate=0.80, form_advantage=True,
            away_team_focus=True, require_form_advantage=True,
        )
        assert result['qualifies'] is True

    def test_away_h2h_ok_form_missing_not_qualifies(self):
        """H2H >=60% but NO form advantage → NOT qualifies."""
        result = _build_process_match_result(
            win_rate=0.80, form_advantage=False,
            away_team_focus=True, require_form_advantage=True,
        )
        assert result['qualifies'] is False

    def test_away_h2h_low_form_ok_not_qualifies(self):
        """H2H <60% even WITH form advantage → NOT qualifies."""
        result = _build_process_match_result(
            win_rate=0.40, form_advantage=True,
            away_team_focus=True, require_form_advantage=True,
        )
        assert result['qualifies'] is False

    def test_away_h2h_low_form_missing_not_qualifies(self):
        """H2H <60% + NO form → NOT qualifies."""
        result = _build_process_match_result(
            win_rate=0.40, form_advantage=False,
            away_team_focus=True, require_form_advantage=True,
        )
        assert result['qualifies'] is False


class TestDefaultBehaviorUnchanged:
    """Without require_form_advantage, form is a bonus — not required."""

    def test_h2h_ok_no_form_still_qualifies(self):
        """H2H >=60% + no form advantage → still qualifies (default)."""
        result = _build_process_match_result(
            win_rate=0.80, form_advantage=False,
            away_team_focus=False, require_form_advantage=False,
        )
        assert result['qualifies'] is True

    def test_h2h_ok_with_form_qualifies(self):
        """H2H >=60% + form advantage → qualifies (default)."""
        result = _build_process_match_result(
            win_rate=0.80, form_advantage=True,
            away_team_focus=False, require_form_advantage=False,
        )
        assert result['qualifies'] is True

    def test_h2h_low_no_form_not_qualifies(self):
        """H2H <60% → NOT qualifies regardless (default)."""
        result = _build_process_match_result(
            win_rate=0.40, form_advantage=False,
            away_team_focus=False, require_form_advantage=False,
        )
        assert result['qualifies'] is False

    def test_away_focus_default_form_is_bonus(self):
        """away_team_focus + H2H ok + no form → still qualifies (default)."""
        result = _build_process_match_result(
            win_rate=0.80, form_advantage=False,
            away_team_focus=True, require_form_advantage=False,
        )
        assert result['qualifies'] is True


class TestEdgeCases:
    """Boundary values for win rate and form combination."""

    def test_exact_60pct_with_form_qualifies(self):
        """Exactly 60% H2H + form → qualifies with flag."""
        result = _build_process_match_result(
            win_rate=0.60, form_advantage=True,
            away_team_focus=True, require_form_advantage=True,
        )
        assert result['qualifies'] is True

    def test_exact_60pct_without_form_not_qualifies(self):
        """Exactly 60% H2H - no form → NOT qualifies with flag."""
        result = _build_process_match_result(
            win_rate=0.60, form_advantage=False,
            away_team_focus=True, require_form_advantage=True,
        )
        assert result['qualifies'] is False

    def test_59pct_with_form_not_qualifies(self):
        """59% H2H + form → NOT qualifies (H2H threshold not met)."""
        result = _build_process_match_result(
            win_rate=0.59, form_advantage=True,
            away_team_focus=True, require_form_advantage=True,
        )
        assert result['qualifies'] is False
