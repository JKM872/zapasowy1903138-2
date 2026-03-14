"""
Tests for form data serialization roundtrip:
  CSV string → parse_form_list / _normalize_form → clean list of W/D/L
"""
from email_notifier import parse_form_list
from ai_prediction_engine import _normalize_form


# ---------------------------------------------------------------------------
# parse_form_list (email_notifier)
# ---------------------------------------------------------------------------

class TestParseFormList:
    def test_dash_separated(self) -> None:
        assert parse_form_list('W-L-D-W-W') == ['W', 'L', 'D', 'W', 'W']

    def test_comma_separated(self) -> None:
        assert parse_form_list('W,L,D') == ['W', 'L', 'D']

    def test_stringified_list(self) -> None:
        assert parse_form_list("['W', 'L', 'D']") == ['W', 'L', 'D']

    def test_single_chars(self) -> None:
        assert parse_form_list('WLDWW') == ['W', 'L', 'D', 'W', 'W']

    def test_actual_list(self) -> None:
        assert parse_form_list(['W', 'L', 'D']) == ['W', 'L', 'D']

    def test_none_returns_empty(self) -> None:
        assert parse_form_list(None) == []

    def test_nan_string_returns_empty(self) -> None:
        assert parse_form_list('nan') == []

    def test_na_string_returns_empty(self) -> None:
        assert parse_form_list('N/A') == []

    def test_empty_string_returns_empty(self) -> None:
        assert parse_form_list('') == []

    def test_float_nan_returns_empty(self) -> None:
        assert parse_form_list(float('nan')) == []


# ---------------------------------------------------------------------------
# _normalize_form (ai_prediction_engine)
# ---------------------------------------------------------------------------

class TestNormalizeForm:
    def test_dash_separated(self) -> None:
        assert _normalize_form('W-L-D-W-W') == ['W', 'L', 'D', 'W', 'W']

    def test_comma_separated(self) -> None:
        assert _normalize_form('W,L,D') == ['W', 'L', 'D']

    def test_stringified_list(self) -> None:
        assert _normalize_form("['W', 'L', 'D']") == ['W', 'L', 'D']

    def test_single_chars(self) -> None:
        assert _normalize_form('WLDWW') == ['W', 'L', 'D', 'W', 'W']

    def test_actual_list(self) -> None:
        assert _normalize_form(['W', 'L', 'D']) == ['W', 'L', 'D']

    def test_none_returns_empty(self) -> None:
        assert _normalize_form(None) == []

    def test_nan_string_returns_empty(self) -> None:
        assert _normalize_form('nan') == []

    def test_na_string_returns_empty(self) -> None:
        assert _normalize_form('N/A') == []

    def test_empty_string_returns_empty(self) -> None:
        assert _normalize_form('') == []

    def test_no_dashes_treated_as_loss(self) -> None:
        """BUG #2 regression: dashes must NOT be scored as losses."""
        result = _normalize_form('W-L-D')
        assert '-' not in result
        assert result == ['W', 'L', 'D']

    def test_roundtrip_dash_join(self) -> None:
        """Simulate CSV roundtrip: list → '-'.join → _normalize_form → list."""
        original = ['W', 'W', 'L', 'D', 'W']
        csv_string = '-'.join(original)
        restored = _normalize_form(csv_string)
        assert restored == original
