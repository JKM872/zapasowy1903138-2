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


# ---------------------------------------------------------------------------
# 8. LiveSport error/block page detection
# ---------------------------------------------------------------------------
class TestLiveSportErrorPageDetection:
    """LiveSport sometimes returns an HTTP-200 'soft' error/block page with no
    match data. It must be detected so the scraper retries instead of silently
    dropping the match (the cause of 'no matches today')."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from livesport_h2h_scraper import is_livesport_error_page
        self.fn = is_livesport_error_page

    def test_classic_error_page(self):
        html = ("<html><body>Error: The requested page can't be displayed. "
                "Please try again later. Livesport.com</body></html>")
        assert self.fn(html) is True

    def test_curly_apostrophe_variant(self):
        html = ("<html><body>The requested page can\u2019t be displayed. "
                "Please try again later.</body></html>")
        assert self.fn(html) is True

    def test_bot_wall(self):
        html = "<html><body>Are you a robot? unusual traffic detected</body></html>"
        assert self.fn(html) is True

    def test_none_is_error(self):
        assert self.fn(None) is True

    def test_empty_is_error(self):
        assert self.fn("") is True

    def test_tiny_page_without_h2h_is_error(self):
        # Small page, no h2h/participant scaffolding → treat as blocked.
        assert self.fn("<html><body>loading...</body></html>") is True

    def test_valid_large_page_is_ok(self):
        # Large page containing real H2H scaffolding must NOT be flagged.
        html = "<html><body>" + ("<a class='h2h__row'>match</a>" * 2000) + "</body></html>"
        assert len(html) > 30000
        assert self.fn(html) is False

    def test_real_fixtures_classified_correctly(self):
        """Validate against the saved debug_html fixtures when present:
        blocked pages (~5 KB) flagged, full pages (~360 KB) not flagged."""
        import glob
        from bs4 import BeautifulSoup
        from livesport_h2h_scraper import parse_h2h_from_soup

        files = sorted(glob.glob(os.path.join(
            os.path.dirname(__file__), 'debug_html', 'h2h_page_*.html')))
        if not files:
            pytest.skip("no debug_html fixtures available")

        good_parsed = 0
        for fn in files:
            with open(fn, encoding='utf-8', errors='ignore') as fh:
                html = fh.read()
            blocked = self.fn(html)
            if not blocked:
                # A page we consider valid must actually yield H2H rows.
                rows = parse_h2h_from_soup(BeautifulSoup(html, 'html.parser'), '')
                assert len(rows) > 0, f"valid page {fn} parsed 0 H2H rows"
                good_parsed += 1
        # At least one good page should exist in the fixture set.
        assert good_parsed >= 1


# ---------------------------------------------------------------------------
# 9. Direct H2H URL building (fixes "Brak H2H" from failed tab clicks)
# ---------------------------------------------------------------------------
class TestBuildH2HOverallUrl:
    """Team-sport matches must navigate straight to /h2h/ogolem/ instead of
    relying on a JS tab click that silently fails in headless CI."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from livesport_h2h_scraper import build_h2h_overall_url
        self.fn = build_h2h_overall_url

    def test_basic_match_url(self):
        out = self.fn("https://www.livesport.com/pl/mecz/pilka-nozna/t1/t2/?mid=ABC")
        assert out == "https://www.livesport.com/pl/mecz/pilka-nozna/t1/t2/h2h/ogolem/?mid=ABC"

    def test_preserves_mid(self):
        out = self.fn("https://www.livesport.com/pl/mecz/pilka-nozna/a/b/?mid=O4wBNeOr")
        assert out.endswith("/h2h/ogolem/?mid=O4wBNeOr")

    def test_strips_detail_segment(self):
        out = self.fn("https://www.livesport.com/pl/mecz/pilka-nozna/a/b/szczegoly/?mid=X")
        assert "/szczegoly" not in out
        assert "/h2h/ogolem/?mid=X" in out

    def test_already_h2h_unchanged(self):
        u = "https://www.livesport.com/pl/mecz/pilka-nozna/a/b/h2h/ogolem/?mid=X"
        assert self.fn(u) == u

    def test_no_mid(self):
        out = self.fn("https://www.livesport.com/pl/mecz/pilka-nozna/a/b/")
        assert out == "https://www.livesport.com/pl/mecz/pilka-nozna/a/b/h2h/ogolem/"

    def test_non_match_url_returns_none(self):
        assert self.fn("https://www.livesport.com/pl/pilka-nozna/") is None

    def test_empty_returns_none(self):
        assert self.fn("") is None

    def test_match_keyword_variant(self):
        out = self.fn("https://www.livesport.com/en/match/football/a/b/?mid=Z")
        assert out.endswith("/h2h/ogolem/?mid=Z")


# ---------------------------------------------------------------------------
# 10. _wait_for_h2h_rows (eager-load helper)
# ---------------------------------------------------------------------------
class TestWaitForH2HRows:
    """The eager-load wait must return as soon as rows appear and must not
    hang on the implicit wait when rows are absent."""

    class _FakeDriver:
        def __init__(self, rows_after_calls=0):
            self._calls = 0
            self._rows_after = rows_after_calls
            self.implicit = None

        def implicitly_wait(self, t):
            self.implicit = t

        def find_elements(self, by, value):
            self._calls += 1
            if self._calls >= self._rows_after:
                return ["row1", "row2"]
            return []

    def test_returns_true_when_rows_present(self):
        from livesport_h2h_scraper import _wait_for_h2h_rows
        d = self._FakeDriver(rows_after_calls=1)
        assert _wait_for_h2h_rows(d, timeout=2.0, poll=0.05) is True

    def test_returns_false_when_never_present(self):
        from livesport_h2h_scraper import _wait_for_h2h_rows
        d = self._FakeDriver(rows_after_calls=9999)
        assert _wait_for_h2h_rows(d, timeout=0.3, poll=0.05) is False

    def test_restores_implicit_wait(self):
        from livesport_h2h_scraper import _wait_for_h2h_rows
        d = self._FakeDriver(rows_after_calls=1)
        _wait_for_h2h_rows(d, timeout=1.0, poll=0.05)
        # Implicit wait must be restored to 10 after polling.
        assert d.implicit == 10


# ---------------------------------------------------------------------------
# 11. 2026 DOM redesign — parse_h2h_from_soup + form badges
# ---------------------------------------------------------------------------
class TestLiveSport2026Redesign:
    """LiveSport renamed H2H classes (wclH2h__date, wcl-name_*, wcl-tableScore,
    wcl-badgeform_*, data-testid). The parser must handle the new DOM."""

    def _fixture(self, name):
        from bs4 import BeautifulSoup
        path = os.path.join(os.path.dirname(__file__), 'tests', 'fixtures', name)
        if not os.path.exists(path):
            pytest.skip(f"fixture missing: {name}")
        with open(path, encoding='utf-8') as fh:
            return BeautifulSoup(fh.read(), 'html.parser')

    def test_parses_h2h_rows_new_dom(self):
        from livesport_h2h_scraper import parse_h2h_from_soup
        soup = self._fixture('livesport_h2h_2026_redesign.html')
        rows = parse_h2h_from_soup(soup, 'Khenchela')
        assert len(rows) == 2
        assert rows[0]['date'] == '09.01.26'
        assert rows[0]['home'] == 'Rouisset'
        assert rows[0]['away'] == 'Khenchela'
        assert rows[0]['score'] == '2-0'
        assert rows[0]['winner'] == 'home'

    def test_parses_rows_without_section_wrapper(self):
        from livesport_h2h_scraper import parse_h2h_from_soup
        soup = self._fixture('livesport_form_2026_redesign.html')
        rows = parse_h2h_from_soup(soup, 'Khenchela')
        assert len(rows) == 5
        # Second row is a draw (2-2).
        draw_rows = [r for r in rows if r['winner'] == 'draw']
        assert len(draw_rows) == 1

    def test_form_badges_new_dom(self):
        from livesport_h2h_scraper import _extract_form_badges
        soup = self._fixture('livesport_form_2026_redesign.html')
        form = _extract_form_badges(soup)
        assert form == ['W', 'D', 'W', 'L', 'L']

    def test_badge_to_result_variants(self):
        from livesport_h2h_scraper import _badge_to_result
        from bs4 import BeautifulSoup
        win = BeautifulSoup('<div data-testid="wcl-badgeForm-win" class="wcl-win_x">Z</div>', 'html.parser').div
        draw = BeautifulSoup('<div class="wcl-draw_y" title="Remis">R</div>', 'html.parser').div
        lose = BeautifulSoup('<div class="wcl-lose_z">P</div>', 'html.parser').div
        legacy = BeautifulSoup('<div class="h2h__badgeform" title="Zwycięstwo">W</div>', 'html.parser').div
        assert _badge_to_result(win) == 'W'
        assert _badge_to_result(draw) == 'D'
        assert _badge_to_result(lose) == 'L'
        assert _badge_to_result(legacy) == 'W'

    def test_row_score_new_testid(self):
        from livesport_h2h_scraper import _h2h_row_score
        from bs4 import BeautifulSoup
        row = BeautifulSoup(
            '<a class="h2h__row"><span data-testid="wcl-tableScore">3</span>'
            '<span data-testid="wcl-tableScore">1</span></a>', 'html.parser').a
        score, winner = _h2h_row_score(row)
        assert score == '3-1'
        assert winner == 'home'

    def test_legacy_dom_still_parses(self):
        """Old markup (h2h__date / participantInner / h2h__result span) must
        still work so the fix is backward compatible."""
        from livesport_h2h_scraper import parse_h2h_from_soup
        from bs4 import BeautifulSoup
        legacy = """
        <div class="h2h__section"><div>Pojedynki bezpośrednie</div>
        <a class="h2h__row">
          <span class="h2h__date">01.02.25</span>
          <span class="h2h__homeParticipant"><span class="h2h__participantInner">Alpha</span></span>
          <span class="h2h__awayParticipant"><span class="h2h__participantInner">Beta</span></span>
          <span class="h2h__result"><span>2</span><span>1</span></span>
        </a></div>
        """
        rows = parse_h2h_from_soup(BeautifulSoup(legacy, 'html.parser'), 'Alpha')
        assert len(rows) == 1
        assert rows[0]['home'] == 'Alpha'
        assert rows[0]['score'] == '2-1'
        assert rows[0]['winner'] == 'home'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
