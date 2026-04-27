"""Regression tests for email HTML data accuracy.

Pokrywa:
- sekcja "Typ modelu" zsynchronizowana ze `scoring_pick`, a nie z najniższym
  kursem (fix rozbieżności między zielonym kursem a typem modelu),
- poprawnie dobrany odnośnik kursowy (`_pick_odds_value`),
- fallback na Forebet, gdy brakuje `scoring_pick`,
- blok Scoring Engine renderuje się nawet bez `scoring_prob`,
- badge przewagi używa `focus_team` (gospodarze vs goście),
- dla tenisa używamy etykiet "Gracz 1/2", nie "Gospodarze/Goście".
"""

import pytest

from email_notifier import (
    _canonical_pick_code,
    _pick_odds_value,
    _render_model_pick_section,
    _sofascore_from_match,
    create_html_email,
)


class TestCanonicalPickCode:
    @pytest.mark.parametrize("raw,expected", [
        ("1", "1"), ("H", "1"), ("1X", "1"),
        ("2", "2"), ("A", "2"), ("X2", "2"),
        ("X", "X"), ("x", "X"),
        ("", None), (None, None), ("nan", None), ("NONE", None), ("??", None),
    ])
    def test_normalizes_variants(self, raw, expected):
        assert _canonical_pick_code(raw) == expected


class TestPickOddsValue:
    def test_home_pick(self):
        assert _pick_odds_value("1", 1.85, 3.40, 4.20) == 1.85

    def test_away_pick(self):
        assert _pick_odds_value("2", 1.85, 3.40, 4.20) == 4.20

    def test_draw_pick(self):
        assert _pick_odds_value("X", 1.85, 3.40, 4.20) == 3.40

    def test_missing_odds_returns_none(self):
        assert _pick_odds_value("X", 1.85, None, 4.20) is None

    def test_zero_treated_as_missing(self):
        assert _pick_odds_value("1", 0.0, 3.40, 4.20) is None


class TestSofascoreFromMatch:
    def test_flat_keys_preferred(self):
        m = {
            "sofascore_home_win_prob": 60, "sofascore_draw_prob": 20,
            "sofascore_away_win_prob": 20, "sofascore_total_votes": 500,
            "sofascore": {"home": 1, "draw": 1, "away": 1, "votes": 1},
        }
        assert _sofascore_from_match(m) == (60.0, 20.0, 20.0, 500)

    def test_nested_dict_used_when_flat_missing(self):
        m = {"sofascore": {"home": 58, "draw": 13, "away": 29, "votes": 1000}}
        assert _sofascore_from_match(m) == (58.0, 13.0, 29.0, 1000)

    def test_nested_partial(self):
        m = {"sofascore": {"home": 70, "away": 30}}
        h, d, a, v = _sofascore_from_match(m)
        assert (h, a, v) == (70.0, 30.0, 0)
        assert d is None

    def test_json_string_nested(self):
        m = {"sofascore": '{"home": 55, "draw": 25, "away": 20, "votes": 200}'}
        assert _sofascore_from_match(m) == (55.0, 25.0, 20.0, 200)

    def test_no_data(self):
        assert _sofascore_from_match({}) == (None, None, None, 0)


class TestModelPickSection:
    def test_scoring_pick_overrides_bookmaker_favorite(self):
        # Najniższy kurs to `2` (1.60), ale scoring_pick to `1`.
        # Sekcja "Typ modelu" musi pokazać pick '1', nie '2'.
        match = {
            "home_team": "Arsenal", "away_team": "Tottenham",
            "scoring_pick": "1", "forebet_prediction": "2",
        }
        html = _render_model_pick_section(match, 2.40, 3.20, 1.60, False)
        assert "Typ modelu (Scoring)" in html
        assert "Gospodarze (1) \u2014 Arsenal" in html
        assert "@ 2.40" in html
        # Nie może wskazywać na gościa (1.60), mimo że to faworyt bukmachera.
        assert "@ 1.60" not in html

    def test_forebet_fallback_when_no_scoring_pick(self):
        match = {
            "home_team": "A", "away_team": "B",
            "scoring_pick": None, "forebet_prediction": "X",
        }
        html = _render_model_pick_section(match, 2.10, 3.00, 3.50, False)
        assert "Typ modelu (Forebet)" in html
        assert "Remis (X)" in html
        assert "@ 3.00" in html

    def test_empty_when_no_pick(self):
        match = {"home_team": "A", "away_team": "B",
                 "scoring_pick": None, "forebet_prediction": None}
        assert _render_model_pick_section(match, 2.10, 3.00, 3.50, False) == ""

    def test_tennis_uses_player_labels(self):
        match = {"home_team": "Djokovic", "away_team": "Nadal",
                 "scoring_pick": "2"}
        html = _render_model_pick_section(match, 1.85, None, 2.00, True)
        assert "Gracz 2 \u2014 Nadal" in html
        assert "Gospodarze" not in html


class TestBuildHtmlContract:
    """Higher-level tests on the full HTML output."""

    def _base_match(self):
        return {
            "home_team": "Crystal Palace", "away_team": "West Ham",
            "sport": "football", "match_time": "20.04.2026 20:00",
            "focus_team": "home", "form_advantage": True,
            "home_odds": 2.55, "draw_odds": 3.3, "away_odds": 2.85,
            "scoring_pick": "1", "scoring_prob": 57.5, "scoring_ev": 0.466,
            "scoring_edge": 18.3, "scoring_confidence": 77.0,
            "forebet_prediction": "X", "forebet_probability": 42.0,
            "sofascore_home_win_prob": 58, "sofascore_draw_prob": 13,
            "sofascore_away_win_prob": 29, "sofascore_total_votes": 21338,
        }

    def test_odds_legend_explains_green_highlight(self):
        html = create_html_email([self._base_match()], "2026-04-20")
        # Użytkownik nie może mylić zielonego kursu z typem modelu.
        assert "najni\u017cszy kurs (faworyt bukmachera)" in html

    def test_model_pick_line_present(self):
        html = create_html_email([self._base_match()], "2026-04-20")
        assert "Typ modelu (Scoring)" in html
        assert "Gospodarze (1) \u2014 Crystal Palace" in html
        assert "@ 2.55" in html

    def test_form_advantage_flips_for_away_focus(self):
        match = self._base_match()
        match["focus_team"] = "away"
        html = create_html_email([match], "2026-04-20")
        assert "Przewaga go\u015bci" in html
        assert "Przewaga gospodarzy" not in html

    def test_form_advantage_default_home(self):
        html = create_html_email([self._base_match()], "2026-04-20")
        assert "Przewaga gospodarzy" in html

    def test_scoring_block_renders_without_prob(self):
        match = self._base_match()
        match["scoring_prob"] = None
        html = create_html_email([match], "2026-04-20")
        # Blok musi się pojawić, a brak prob pokazuje się jako "—".
        assert "Scoring Engine" in html
        assert ">\u2014<" in html  # placeholder gdzieś w bloku

    def test_sofascore_block_from_nested_dict(self):
        """Mecz bez płaskich `sofascore_*`, ale z `sofascore={...}` musi pokazać Fan Vote."""
        match = self._base_match()
        for k in ("sofascore_home_win_prob", "sofascore_draw_prob",
                  "sofascore_away_win_prob", "sofascore_total_votes"):
            match.pop(k, None)
        match["sofascore"] = {"home": 58, "draw": 13, "away": 29, "votes": 1000}
        html = create_html_email([match], "2026-04-20")
        assert "SofaScore Fan Vote" in html
        assert "58.0%" in html
        assert "29.0%" in html
        assert "(1000 g\u0142os\u00f3w)" in html

    def test_sofascore_block_hidden_without_any_data(self):
        match = self._base_match()
        for k in ("sofascore_home_win_prob", "sofascore_draw_prob",
                  "sofascore_away_win_prob", "sofascore_total_votes"):
            match.pop(k, None)
        html = create_html_email([match], "2026-04-20")
        assert "SofaScore Fan Vote" not in html

    def test_scoring_block_hidden_when_no_pick_and_no_prob(self):
        match = self._base_match()
        match["scoring_pick"] = None
        match["scoring_prob"] = None
        html = create_html_email([match], "2026-04-20")
        assert "Scoring Engine" not in html
