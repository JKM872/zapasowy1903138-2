"""
Tests for tennis pipeline fixes  –  Phase 5 regression suite.
Validates field names, no synthetic data, and compatibility mapping.
"""


# ---------------------------------------------------------------------------
# Field name consistency tests
# ---------------------------------------------------------------------------

class TestTennisFieldNames:
    """Ensure the codebase uses consistent field names for tennis."""

    def test_scraper_writes_away_wins_in_h2h_last5(self):
        """process_match_tennis must write 'away_wins_in_h2h_last5' (not 'away_wins_in_h2h')."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        # The new field name should be used
        assert "away_wins_in_h2h_last5" in source
        # The old broken field name should NOT appear as an assignment target
        assert "out['away_wins_in_h2h']" not in source

    def test_scraper_uses_teams_match(self):
        """Tennis H2H counting must use _teams_match (robust matching)."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "_teams_match(" in source

    def test_no_synthetic_form_function_called(self):
        """process_match_tennis must NOT call extract_player_form_simple."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "extract_player_form_simple" not in source

    def test_no_synthetic_surface_function_called(self):
        """process_match_tennis must NOT call calculate_surface_stats_from_h2h."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "calculate_surface_stats_from_h2h" not in source

    def test_uses_new_scoring_engine(self):
        """process_match_tennis must import TennisScoringEngine (not TennisMatchAnalyzer)."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "TennisScoringEngine" in source
        assert "TennisMatchAnalyzer" not in source

    def test_extract_real_form_badges_exists(self):
        """The new _extract_real_form_badges function should exist."""
        from livesport_h2h_scraper import _extract_real_form_badges  # pyright: ignore[reportPrivateUsage]
        assert callable(_extract_real_form_badges)


class TestScrapeAndNotifyFieldNames:
    """Ensure scrape_and_notify.py uses correct field names."""

    def test_no_bare_away_wins_in_h2h(self):
        """scrape_and_notify.py should not read 'away_wins_in_h2h' (without _last5)."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        # Remove comments to avoid false positives
        lines = [l for l in source.split('\n') if not l.strip().startswith('#')]
        code = '\n'.join(lines)
        # The old field name should not appear as a standalone .get argument
        import re
        matches = re.findall(r"\.get\(['\"]away_wins_in_h2h['\"]", code)
        assert len(matches) == 0, f"Found {len(matches)} uses of old field name 'away_wins_in_h2h'"

    def test_json_export_uses_match_time(self):
        """JSON export should use match_time (with fallback to time)."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "row.get('match_time'" in source

    def test_json_export_uses_match_url(self):
        """JSON export should use match_url (with fallback to url)."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "row.get('match_url'" in source

    def test_forebet_exact_score_field(self):
        """JSON export should read forebet_exact_score (with fallback)."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "forebet_exact_score" in source

    def test_tennis_scoring_integration_exists(self):
        """scrape_and_notify.py should have tennis scoring engine integration."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "TennisScoringEngine" in source
        assert "TENNIS SCORING" in source


class TestEmailRendering:
    """Ensure email_notifier.py handles tennis scoring display."""

    def test_tennis_engine_label(self):
        """Email should show 'Tennis Engine' label for tennis matches."""
        with open('email_notifier.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "Tennis Engine" in source

    def test_tennis_prob_a_b_display(self):
        """Email should display A: X% | B: Y% for tennis."""
        with open('email_notifier.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "sc_tpa" in source
        assert "sc_tpb" in source

    def test_threshold_45_in_footer(self):
        """Email footer should reference ≥45/100 for tennis."""
        with open('email_notifier.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "45/100" in source


# ---------------------------------------------------------------------------
# Compatibility mapping
# ---------------------------------------------------------------------------

class TestCompatibilityMapping:
    """Verify that process_match_tennis sets all compat fields."""

    def test_init_dict_has_compat_fields(self):
        """The init dict should have sport, focus_team, home_form, etc."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        # Check that _finalise is called on all exit paths
        assert "_finalise" in source
        # Check that sport is set
        assert "'sport': 'tennis'" in source

    def test_finalise_function_exists(self):
        """_finalise is defined inside process_match_tennis."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "def _finalise" in source


# ---------------------------------------------------------------------------
# v5: New tennis data contract fields
# ---------------------------------------------------------------------------

class TestTennisDataContract:
    """Validate that process_match_tennis defines all v5 required fields."""

    def test_last_h2h_fields_defined(self):
        """process_match_tennis must define last_h2h_date, last_h2h_score."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "'last_h2h_date'" in source
        assert "'last_h2h_score'" in source

    def test_last_match_fields_defined(self):
        """process_match_tennis must define last_match_a/b fields."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "'last_match_a_date'" in source
        assert "'last_match_a_score'" in source
        assert "'last_match_b_date'" in source
        assert "'last_match_b_score'" in source

    def test_surface_form_fields_defined(self):
        """process_match_tennis must define surface_form_a/b and surface_stats_a/b."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "'surface_form_a'" in source
        assert "'surface_form_b'" in source
        assert "'surface_stats_a'" in source
        assert "'surface_stats_b'" in source

    def test_tennis_skip_reason_field(self):
        """process_match_tennis must define tennis_skip_reason."""
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "'tennis_skip_reason'" in source

    def test_hard_skip_function_exists(self):
        """_check_tennis_data_completeness function should exist."""
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        assert callable(_check_tennis_data_completeness)


class TestHardSkipLogic:
    """Test tennis data completeness checking (hard/soft split)."""

    @staticmethod
    def _full_out(**overrides):
        base = {
            'home_team': 'Player A',
            'away_team': 'Player B',
            'last_h2h_date': '01.01.26',
            'last_h2h_score': '2-1',
            'last_match_a_date': '28.03.26',
            'last_match_a_score': '2-0',
            'last_match_b_date': '29.03.26',
            'last_match_b_score': '2-1',
            'home_odds': 1.80,
            'away_odds': 2.10,
            'form_a': ['W', 'L'],
            'form_b': ['W', 'W'],
        }
        base.update(overrides)
        return base

    def test_complete_data_passes(self):
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        hard, soft = _check_tennis_data_completeness(self._full_out())
        assert hard is None
        assert soft == []

    def test_missing_last_h2h_is_soft_warning(self):
        """Missing H2H should be a soft warning, not a hard fail."""
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        hard, soft = _check_tennis_data_completeness(
            self._full_out(last_h2h_date=None, last_h2h_score=None)
        )
        assert hard is None
        assert any('h2h' in w.lower() for w in soft)

    def test_missing_last_match_a_is_soft_warning(self):
        """Missing recent match for player A should be a soft warning."""
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        hard, soft = _check_tennis_data_completeness(
            self._full_out(last_match_a_date=None, last_match_a_score=None)
        )
        assert hard is None
        assert any('missing_recent_matches_A' in w for w in soft)

    def test_missing_last_match_b_is_soft_warning(self):
        """Missing recent match for player B should be a soft warning."""
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        hard, soft = _check_tennis_data_completeness(
            self._full_out(last_match_b_date=None, last_match_b_score=None)
        )
        assert hard is None
        assert any('missing_recent_matches_B' in w for w in soft)

    def test_odds_below_threshold_hard_fails(self):
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        hard, _ = _check_tennis_data_completeness(
            self._full_out(home_odds=1.10, away_odds=5.50)
        )
        assert hard is not None
        assert '1.35' in hard

    def test_missing_odds_hard_fails(self):
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        hard, _ = _check_tennis_data_completeness(
            self._full_out(home_odds=None, away_odds=None)
        )
        assert hard is not None
        assert 'odds' in hard.lower()

    def test_missing_player_names_hard_fails(self):
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        hard, _ = _check_tennis_data_completeness(
            self._full_out(home_team=None)
        )
        assert hard is not None
        assert 'player_names' in hard.lower()

    def test_multiple_soft_warnings_combined(self):
        """All soft-fail conditions should accumulate in warnings list."""
        from livesport_h2h_scraper import _check_tennis_data_completeness  # pyright: ignore[reportPrivateUsage]
        hard, soft = _check_tennis_data_completeness(
            self._full_out(
                last_h2h_date=None, last_h2h_score=None,
                last_match_a_date=None, last_match_a_score=None,
                last_match_b_date=None, last_match_b_score=None,
                form_a=[], form_b=[],
            )
        )
        assert hard is None
        # Expect: missing_h2h, missing_recent_matches_A, missing_recent_matches_B,
        #         missing_form_A, missing_form_B
        assert len(soft) >= 5


class TestSofaScoreMandatory:
    """Verify SofaScore mandatory check exists in scrape_and_notify.py."""

    def test_sofascore_mandatory_check_in_pipeline(self):
        """scrape_and_notify.py should check SofaScore for tennis matches."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert 'Tennis SofaScore check' in source or 'sofascore_home_win_prob' in source
        assert 'tennis_skip_reason' in source

    def test_json_export_has_skip_reason(self):
        """JSON export should include skipReason for tennis."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "'skipReason'" in source

    def test_json_export_has_last_h2h(self):
        """JSON export should include lastH2H for tennis."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "'lastH2H'" in source

    def test_json_export_has_last_match_a_b(self):
        """JSON export should include lastMatchA and lastMatchB for tennis."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "'lastMatchA'" in source
        assert "'lastMatchB'" in source

    def test_json_export_has_surface_form(self):
        """JSON export should include surfaceFormA and surfaceFormB for tennis."""
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert "'surfaceFormA'" in source
        assert "'surfaceFormB'" in source


# ---------------------------------------------------------------------------
# URL builder tests
# ---------------------------------------------------------------------------

class TestBuildTennisH2hUrl:
    """Test _build_tennis_h2h_url normalisation."""

    def test_detail_url(self):
        from livesport_h2h_scraper import _build_tennis_h2h_url  # pyright: ignore[reportPrivateUsage]
        url = 'https://www.livesport.com/pl/tenis/mecz/atp-singles/abc123/szczegoly/'
        result = _build_tennis_h2h_url(url)
        assert result == 'https://www.livesport.com/pl/tenis/mecz/atp-singles/abc123/h2h/wszystkie-nawierzchnie/'

    def test_already_h2h_url(self):
        from livesport_h2h_scraper import _build_tennis_h2h_url  # pyright: ignore[reportPrivateUsage]
        url = 'https://www.livesport.com/pl/tenis/mecz/atp-singles/abc123/h2h/antuka/'
        result = _build_tennis_h2h_url(url)
        assert result == 'https://www.livesport.com/pl/tenis/mecz/atp-singles/abc123/h2h/wszystkie-nawierzchnie/'

    def test_bare_match_url(self):
        from livesport_h2h_scraper import _build_tennis_h2h_url  # pyright: ignore[reportPrivateUsage]
        url = 'https://www.livesport.com/pl/tenis/mecz/atp-singles/abc123/'
        result = _build_tennis_h2h_url(url)
        assert result is not None
        assert result.endswith('/h2h/wszystkie-nawierzchnie/')

    def test_non_tennis_url_returns_none(self):
        from livesport_h2h_scraper import _build_tennis_h2h_url  # pyright: ignore[reportPrivateUsage]
        url = 'https://www.livesport.com/pl/pilka-nozna/mecz/premier-league/abc123/'
        result = _build_tennis_h2h_url(url)
        assert result is None

    def test_empty_url_returns_none(self):
        from livesport_h2h_scraper import _build_tennis_h2h_url  # pyright: ignore[reportPrivateUsage]
        assert _build_tennis_h2h_url('') is None
        assert _build_tennis_h2h_url(None) is None

    def test_non_http_url_returns_none(self):
        from livesport_h2h_scraper import _build_tennis_h2h_url  # pyright: ignore[reportPrivateUsage]
        assert _build_tennis_h2h_url('ftp://example.com/tenis/mecz/x/y') is None

    def test_english_tennis_url(self):
        from livesport_h2h_scraper import _build_tennis_h2h_url  # pyright: ignore[reportPrivateUsage]
        url = 'https://www.livesport.com/en/tennis/match/wta-singles/xyz789/szczegoly/'
        result = _build_tennis_h2h_url(url)
        assert result is not None
        assert '/h2h/wszystkie-nawierzchnie/' in result


# ---------------------------------------------------------------------------
# Player name extraction helper tests
# ---------------------------------------------------------------------------

class TestExtractPlayerNamesFromSoup:
    """Test _extract_player_names_from_soup."""

    def test_exists_and_callable(self):
        from livesport_h2h_scraper import _extract_player_names_from_soup  # pyright: ignore[reportPrivateUsage]
        assert callable(_extract_player_names_from_soup)

    def test_title_based_extraction(self):
        from bs4 import BeautifulSoup
        from livesport_h2h_scraper import _extract_player_names_from_soup  # pyright: ignore[reportPrivateUsage]
        html = '<html><head><title>Djokovic N. - Nadal R. | ATP</title></head><body></body></html>'
        soup = BeautifulSoup(html, 'html.parser')
        pa, pb = _extract_player_names_from_soup(soup)
        assert pa == 'Djokovic N.'
        assert pb == 'Nadal R.'

    def test_empty_html_returns_none(self):
        from bs4 import BeautifulSoup
        from livesport_h2h_scraper import _extract_player_names_from_soup  # pyright: ignore[reportPrivateUsage]
        soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
        pa, pb = _extract_player_names_from_soup(soup)
        assert pa is None
        assert pb is None

    def test_participant_selectors(self):
        from bs4 import BeautifulSoup
        from livesport_h2h_scraper import _extract_player_names_from_soup  # pyright: ignore[reportPrivateUsage]
        html = '''<html><body>
            <div class="duelParticipant__home"><a class="participant__participantName">Sinner J.</a></div>
            <div class="duelParticipant__away"><a class="participant__participantName">Alcaraz C.</a></div>
        </body></html>'''
        soup = BeautifulSoup(html, 'html.parser')
        pa, pb = _extract_player_names_from_soup(soup)
        assert pa == 'Sinner J.'
        assert pb == 'Alcaraz C.'


# ---------------------------------------------------------------------------
# Tennis data_warnings field presence tests
# ---------------------------------------------------------------------------

class TestTennisDataWarningsField:
    """Verify process_match_tennis defines the tennis_data_warnings field."""

    def test_tennis_data_warnings_field_in_source(self):
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert 'tennis_data_warnings' in source

    def test_build_tennis_h2h_url_in_source(self):
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert '_build_tennis_h2h_url' in source
