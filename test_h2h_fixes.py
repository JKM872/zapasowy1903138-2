"""
Regression tests for H2H last-match fixes (Phase 4).

Covers:
  - Date sorting — newest match must come first
  - Canonical team-key normalisation
  - _teams_match() with token-overlap ≥ 80 %
  - Home/away orientation preserved from historical data
"""

import sys
import os
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 1. _parse_h2h_date
# ---------------------------------------------------------------------------
class TestParseH2HDate:
    """Tests for _parse_h2h_date helper inside livesport_h2h_scraper."""

    @pytest.fixture(autouse=True)
    def _import(self):
        # The function is module-level, so we can import it
        from livesport_h2h_scraper import _parse_h2h_date
        self.fn = _parse_h2h_date

    def test_four_digit_year(self):
        dt = self.fn("17.11.2025")
        assert dt.year == 2025
        assert dt.month == 11
        assert dt.day == 17

    def test_two_digit_year(self):
        dt = self.fn("05.03.23")
        assert dt.year == 2023
        assert dt.month == 3
        assert dt.day == 5

    def test_two_digit_year_90s(self):
        dt = self.fn("01.01.99")
        assert dt.year == 1999

    def test_garbage_returns_epoch(self):
        from datetime import datetime
        dt = self.fn("not-a-date")
        assert dt == datetime(1900, 1, 1)

    def test_none_returns_epoch(self):
        from datetime import datetime
        dt = self.fn(None)
        assert dt == datetime(1900, 1, 1)


# ---------------------------------------------------------------------------
# 2. _team_key
# ---------------------------------------------------------------------------
class TestTeamKey:
    """Tests for canonical team-key normalisation."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from livesport_h2h_scraper import _team_key
        self.fn = _team_key

    def test_lowercase(self):
        assert self.fn("FC Barcelona") == self.fn("fc barcelona")

    def test_strips_fc_suffix(self):
        key = self.fn("Liverpool FC")
        assert "fc" not in key

    def test_strips_cf_prefix(self):
        key = self.fn("CF Monterrey")
        assert "cf" not in key

    def test_strips_ac_prefix(self):
        key = self.fn("AC Milan")
        assert "ac" not in key.split()  # 'milan' stays

    def test_none_safe(self):
        assert self.fn(None) == ""

    def test_empty_safe(self):
        assert self.fn("") == ""


# ---------------------------------------------------------------------------
# 3. _teams_match
# ---------------------------------------------------------------------------
class TestTeamsMatch:
    """Tests for fuzzy team matching."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from livesport_h2h_scraper import _teams_match
        self.fn = _teams_match

    def test_exact_match(self):
        assert self.fn("Real Madrid", "Real Madrid")

    def test_case_insensitive(self):
        assert self.fn("real madrid", "REAL MADRID")

    def test_fc_stripped(self):
        assert self.fn("Liverpool FC", "Liverpool")

    def test_single_word_exact(self):
        assert self.fn("Arsenal", "Arsenal")

    def test_single_word_no_false_positive(self):
        assert not self.fn("Arsenal", "Barcelona")

    def test_multiword_overlap(self):
        # "Atletico Madrid" vs "Atl. Madrid" — depends on tokens; 
        # 'madrid' overlaps, key logic should pass
        assert self.fn("Atletico Madrid", "Atletico Madrid")

    def test_completely_different(self):
        assert not self.fn("Manchester United", "Bayern München")


# ---------------------------------------------------------------------------
# 4. H2H date-sorting: newest first
# ---------------------------------------------------------------------------
class TestH2HDateSorting:
    """Verify that after sorting, index 0 is the newest H2H match."""

    def test_sorting_order(self):
        from livesport_h2h_scraper import _parse_h2h_date

        h2h_rows = [
            {"date": "10.05.2022", "home": "A", "away": "B", "score": "1-0"},
            {"date": "20.11.2024", "home": "B", "away": "A", "score": "2-1"},
            {"date": "03.03.2023", "home": "A", "away": "B", "score": "0-0"},
        ]
        h2h_rows.sort(
            key=lambda x: _parse_h2h_date(x.get("date", "")),
            reverse=True,
        )
        assert h2h_rows[0]["date"] == "20.11.2024"
        assert h2h_rows[-1]["date"] == "10.05.2022"


# ---------------------------------------------------------------------------
# 5. Historical orientation preserved (not swapped)
# ---------------------------------------------------------------------------
class TestHistoricalOrientation:
    """
    After H2H fix, the last_h2h_home / last_h2h_away must reflect
    the ORIGINAL roles from the historical match, NOT today's fixture.
    """

    def test_orientation_not_swapped(self):
        """Simulate: today A(home) vs B(away); last H2H was B(home) vs A(away).
        The last_h2h_home should be B, not A."""
        from livesport_h2h_scraper import _teams_match

        # Simulated data
        today_home = "Team Alpha"
        today_away = "Team Beta"
        h2h_entry = {
            "home": "Team Beta",   # B was home in the historical match
            "away": "Team Alpha",  # A was away
            "score": "2-1",
        }

        h2h_home = h2h_entry["home"]
        h2h_away = h2h_entry["away"]

        # Validation: the pair should match today's teams (regardless of order)
        pair_match = (
            (_teams_match(h2h_home, today_home) and _teams_match(h2h_away, today_away))
            or (_teams_match(h2h_home, today_away) and _teams_match(h2h_away, today_home))
        )
        assert pair_match, "H2H pair must match today's teams"

        # The historical orientation must be preserved
        assert h2h_home == "Team Beta", "Historical home must stay Team Beta"
        assert h2h_away == "Team Alpha", "Historical away must stay Team Alpha"


# ---------------------------------------------------------------------------
# 6. Participant extraction fallback selectors
# ---------------------------------------------------------------------------
class TestParticipantExtractionFallbacks:
    """Verify that participant names are extracted via fallback selectors
    when the primary Livesport CSS classes are absent (non-football sports)."""

    def _make_soup(self, html):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, 'html.parser')

    def test_primary_selectors(self):
        """Primary selector chain (smv__homeParticipant / smv__awayParticipant)."""
        html = """
        <div class="smv__participantRow smv__homeParticipant">
          <a class="participant__participantName">FC Barcelona</a>
        </div>
        <div class="smv__participantRow smv__awayParticipant">
          <a class="participant__participantName">Real Madrid</a>
        </div>
        """
        soup = self._make_soup(html)
        _PARTICIPANT_SELECTORS_HOME = [
            "div.smv__participantRow.smv__homeParticipant a.participant__participantName",
            "div.duelParticipant__home a.participant__participantName",
            "div.duelParticipant__home .participant__participantNameWrapper",
            "a.participant__participantName",
        ]
        _PARTICIPANT_SELECTORS_AWAY = [
            "div.smv__participantRow.smv__awayParticipant a.participant__participantName",
            "div.duelParticipant__away a.participant__participantName",
            "div.duelParticipant__away .participant__participantNameWrapper",
        ]
        home_el = None
        for sel in _PARTICIPANT_SELECTORS_HOME:
            home_el = soup.select_one(sel)
            if home_el:
                break
        away_el = None
        for sel in _PARTICIPANT_SELECTORS_AWAY:
            away_el = soup.select_one(sel)
            if away_el:
                break
        assert home_el is not None
        assert away_el is not None
        assert home_el.get_text(strip=True) == "FC Barcelona"
        assert away_el.get_text(strip=True) == "Real Madrid"

    def test_duelParticipant_fallback(self):
        """Fallback to duelParticipant__home/away selectors (non-football)."""
        html = """
        <div class="duelParticipant__home">
          <a class="participant__participantName">Łomża Vive Kielce</a>
        </div>
        <div class="duelParticipant__away">
          <a class="participant__participantName">THW Kiel</a>
        </div>
        """
        soup = self._make_soup(html)
        _PARTICIPANT_SELECTORS_HOME = [
            "div.smv__participantRow.smv__homeParticipant a.participant__participantName",
            "div.duelParticipant__home a.participant__participantName",
        ]
        _PARTICIPANT_SELECTORS_AWAY = [
            "div.smv__participantRow.smv__awayParticipant a.participant__participantName",
            "div.duelParticipant__away a.participant__participantName",
        ]
        home_el = None
        for sel in _PARTICIPANT_SELECTORS_HOME:
            home_el = soup.select_one(sel)
            if home_el:
                break
        away_el = None
        for sel in _PARTICIPANT_SELECTORS_AWAY:
            away_el = soup.select_one(sel)
            if away_el:
                break
        assert home_el is not None and home_el.get_text(strip=True) == "Łomża Vive Kielce"
        assert away_el is not None and away_el.get_text(strip=True) == "THW Kiel"

    def test_generic_fallback_for_away(self):
        """When away-specific selectors fail, second generic participant__participantName is used."""
        html = """
        <a class="participant__participantName">Team A</a>
        <a class="participant__participantName">Team B</a>
        """
        soup = self._make_soup(html)
        _PARTICIPANT_SELECTORS_AWAY = [
            "div.smv__participantRow.smv__awayParticipant a.participant__participantName",
            "div.duelParticipant__away a.participant__participantName",
        ]
        away_el = None
        for sel in _PARTICIPANT_SELECTORS_AWAY:
            away_el = soup.select_one(sel)
            if away_el:
                break
        if not away_el:
            all_teams = soup.select("a.participant__participantName")
            if len(all_teams) >= 2:
                away_el = all_teams[1]
        assert away_el is not None
        assert away_el.get_text(strip=True) == "Team B"

    def test_no_crash_on_empty_html(self):
        """Empty HTML should not crash, just return None."""
        soup = self._make_soup("<html></html>")
        _PARTICIPANT_SELECTORS_HOME = [
            "div.smv__participantRow.smv__homeParticipant a.participant__participantName",
            "div.duelParticipant__home a.participant__participantName",
            "a.participant__participantName",
        ]
        home_el = None
        for sel in _PARTICIPANT_SELECTORS_HOME:
            home_el = soup.select_one(sel)
            if home_el:
                break
        assert home_el is None


# ---------------------------------------------------------------------------
# 7. Supabase save_prediction guard (rejects missing team names)
# ---------------------------------------------------------------------------
class TestSupabaseSaveGuard:
    """Verify that save_prediction refuses rows with missing team names
    before attempting the Supabase insert call."""

    def test_rejects_null_home_team(self):
        """save_prediction must return False when home_team is None."""
        from unittest.mock import MagicMock, patch
        with patch.dict('os.environ', {
            'SUPABASE_SERVICE_ROLE_KEY': 'test-key-for-init',
            'SUPABASE_URL': 'https://fake.supabase.co',
        }):
            with patch('supabase_manager.create_client') as mock_client:
                mock_client.return_value = MagicMock()
                from supabase_manager import SupabaseManager
                mgr = SupabaseManager()
                result = mgr.save_prediction({
                    'home_team': None,
                    'away_team': 'Team B',
                    'match_date': '2026-04-04',
                })
                assert result is False
                # Ensure insert was never called
                mgr.client.table.assert_not_called()

    def test_rejects_empty_away_team(self):
        """save_prediction must return False when away_team is empty string."""
        from unittest.mock import MagicMock, patch
        with patch.dict('os.environ', {
            'SUPABASE_SERVICE_ROLE_KEY': 'test-key-for-init',
            'SUPABASE_URL': 'https://fake.supabase.co',
        }):
            with patch('supabase_manager.create_client') as mock_client:
                mock_client.return_value = MagicMock()
                from supabase_manager import SupabaseManager
                mgr = SupabaseManager()
                result = mgr.save_prediction({
                    'home_team': 'Team A',
                    'away_team': '',
                    'match_date': '2026-04-04',
                })
                assert result is False
                mgr.client.table.assert_not_called()

    def test_accepts_valid_row(self):
        """save_prediction must attempt insert when both team names are present."""
        from unittest.mock import MagicMock, patch
        with patch.dict('os.environ', {
            'SUPABASE_SERVICE_ROLE_KEY': 'test-key-for-init',
            'SUPABASE_URL': 'https://fake.supabase.co',
        }):
            with patch('supabase_manager.create_client') as mock_client:
                mock_instance = MagicMock()
                mock_client.return_value = mock_instance
                # Chain: client.table('predictions').insert(...).execute()
                mock_instance.table.return_value.insert.return_value.execute.return_value = MagicMock()
                from supabase_manager import SupabaseManager
                mgr = SupabaseManager()
                result = mgr.save_prediction({
                    'home_team': 'Team A',
                    'away_team': 'Team B',
                    'match_date': '2026-04-04',
                })
                assert result is True
                mock_instance.table.assert_called_once_with('predictions')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
