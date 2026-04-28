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


# ---------------------------------------------------------------------------
# Balanced fast-path: early odds gate + warunkowe pominięcie kosztownych
# kroków ekstrakcji.  Cel: skrócenie FAZY 1 dla tenisa bez utraty trafnych
# kwalifikacji.
# ---------------------------------------------------------------------------

class TestTennisOddsGate:
    """Czysty helper `_tennis_odds_gate_reason` — wczesny skip oparty wyłącznie
    o kursy.  Testowany w izolacji, bez selenium, na sztucznych dictach."""

    def test_below_threshold_home_returns_reason(self):
        from livesport_h2h_scraper import _tennis_odds_gate_reason, TENNIS_MIN_ODDS  # pyright: ignore[reportPrivateUsage]
        reason = _tennis_odds_gate_reason({'home_odds': 1.10, 'away_odds': 5.50})
        assert reason is not None
        assert 'A (1.10)' in reason
        assert str(TENNIS_MIN_ODDS) in reason

    def test_below_threshold_away_returns_reason(self):
        from livesport_h2h_scraper import _tennis_odds_gate_reason  # pyright: ignore[reportPrivateUsage]
        reason = _tennis_odds_gate_reason({'home_odds': 5.50, 'away_odds': 1.20})
        assert reason is not None
        assert 'B (1.20)' in reason

    def test_both_above_threshold_returns_none(self):
        from livesport_h2h_scraper import _tennis_odds_gate_reason  # pyright: ignore[reportPrivateUsage]
        assert _tennis_odds_gate_reason({'home_odds': 1.85, 'away_odds': 2.10}) is None

    def test_missing_odds_returns_none_to_allow_fallback(self):
        # Gate celowo nie odpala gdy brakuje któregoś kursu — zostawiamy
        # szansę kolejnym fallbackom (np. FlashScore).
        from livesport_h2h_scraper import _tennis_odds_gate_reason  # pyright: ignore[reportPrivateUsage]
        assert _tennis_odds_gate_reason({'home_odds': 1.85, 'away_odds': None}) is None
        assert _tennis_odds_gate_reason({'home_odds': None, 'away_odds': 2.10}) is None
        assert _tennis_odds_gate_reason({}) is None

    def test_invalid_odds_returns_none(self):
        from livesport_h2h_scraper import _tennis_odds_gate_reason  # pyright: ignore[reportPrivateUsage]
        assert _tennis_odds_gate_reason({'home_odds': 'n/a', 'away_odds': 'n/a'}) is None

    def test_at_threshold_passes(self):
        # Boundary: dokładnie 1.35 — nie powinno być traktowane jako poniżej.
        from livesport_h2h_scraper import _tennis_odds_gate_reason, TENNIS_MIN_ODDS  # pyright: ignore[reportPrivateUsage]
        assert _tennis_odds_gate_reason(
            {'home_odds': TENNIS_MIN_ODDS, 'away_odds': TENNIS_MIN_ODDS}
        ) is None


class TestTennisShouldSkipExpensiveSteps:
    """Heurystyka pomijania `_extract_last_matches_for_players` /
    `_compute_surface_form` — pomijaj tylko gdy nic z H2H/rankingu/form."""

    def test_skips_when_no_signals_at_all(self):
        from livesport_h2h_scraper import _tennis_should_skip_expensive_steps  # pyright: ignore[reportPrivateUsage]
        out = {'h2h_count': 0, 'ranking_a': None, 'ranking_b': None,
               'form_a': [], 'form_b': []}
        assert _tennis_should_skip_expensive_steps(out) is True

    def test_keeps_full_pipeline_when_h2h_present(self):
        from livesport_h2h_scraper import _tennis_should_skip_expensive_steps  # pyright: ignore[reportPrivateUsage]
        out = {'h2h_count': 2, 'ranking_a': None, 'ranking_b': None,
               'form_a': [], 'form_b': []}
        assert _tennis_should_skip_expensive_steps(out) is False

    def test_keeps_full_pipeline_when_ranking_present(self):
        from livesport_h2h_scraper import _tennis_should_skip_expensive_steps  # pyright: ignore[reportPrivateUsage]
        out = {'h2h_count': 0, 'ranking_a': 50, 'ranking_b': None,
               'form_a': [], 'form_b': []}
        assert _tennis_should_skip_expensive_steps(out) is False

    def test_keeps_full_pipeline_when_form_present(self):
        from livesport_h2h_scraper import _tennis_should_skip_expensive_steps  # pyright: ignore[reportPrivateUsage]
        out = {'h2h_count': 0, 'ranking_a': None, 'ranking_b': None,
               'form_a': ['W', 'L'], 'form_b': []}
        assert _tennis_should_skip_expensive_steps(out) is False

    def test_handles_missing_keys_gracefully(self):
        # Brak kluczy = brak sygnałów = pomijamy.  Helper musi być odporny.
        from livesport_h2h_scraper import _tennis_should_skip_expensive_steps  # pyright: ignore[reportPrivateUsage]
        assert _tennis_should_skip_expensive_steps({}) is True


class TestTennisFastPathIntegration:
    """Integracja: process_match_tennis musi mieć early-skip gate + fast-path
    branching widoczny w kodzie źródłowym i nową kolumnę telemetryczną."""

    def test_early_odds_gate_called_before_h2h_navigation(self):
        # Gate musi być umieszczony PO bloku Livesport API odds, ale PRZED
        # nawigacją do H2H — inaczej oszczędność czasu znika.
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        gate_idx = source.find('_tennis_odds_gate_reason(out)')
        h2h_nav_idx = source.find("# ── STEP 3: Build & validate H2H URL")
        assert gate_idx != -1, 'odds gate not invoked in process_match_tennis'
        assert h2h_nav_idx != -1, 'STEP 3 marker missing'
        assert gate_idx < h2h_nav_idx, 'odds gate must precede H2H navigation'

    def test_fast_path_branch_present(self):
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert '_tennis_should_skip_expensive_steps' in source
        assert 'fast_path_skipped_expensive_steps' in source

    def test_phase_path_field_initialised(self):
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "'tennis_phase_path'" in source

    def test_fast_skip_marks_phase_path(self):
        # Skip ścieżką odds musi ustawić tennis_phase_path='fast_odds_skip',
        # żeby telemetria w scrape_and_notify mogła to policzyć.
        import inspect
        from livesport_h2h_scraper import process_match_tennis  # pyright: ignore[reportUnknownVariableType]
        source = inspect.getsource(process_match_tennis)  # pyright: ignore[reportUnknownArgumentType]
        assert "'fast_odds_skip'" in source
        assert "'partial_data_fastpath'" in source


class TestTennisPhase1Telemetry:
    """scrape_and_notify musi zliczać tennis_phase_paths i czas tenisa."""

    def test_telemetry_counters_in_source(self):
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert 'tennis_phase_paths' in source
        assert 'tennis_total_time' in source
        assert 'tennis_qualifies_count' in source

    def test_telemetry_summary_printed(self):
        with open('scrape_and_notify.py', 'r', encoding='utf-8') as f:
            source = f.read()
        assert 'Phase1 paths:' in source
        assert 'Tennis time:' in source
