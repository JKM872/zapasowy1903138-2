"""Tests for name-based settlement of mailed picks.

Every test is offline: the SofaScore call is monkeypatched. The cases encode
the faults found on the 2026-07-28 report, where 136 of 136 matches came back
PENDING — a flipped orientation, a cancelled fixture, undated rows and a
name search that resolved 'Tigre' to a club on another continent.
"""

import pytest

import result_resolver as rr


def _row(sport='table_tennis', home='Adamiak Grzegorz', away='Karol Strowski',
         pick='A', **extra):
    row = {
        'sport': sport,
        'home_team': home,
        'away_team': away,
        'scoring_pick': pick,
        'match_date': '2026-07-28',
    }
    row.update(extra)
    return row


def _result(home_name='Grzegorz Adamiak', away_name='Karol Strowski',
            hs=3, as_=2, **extra):
    winner = None if hs == as_ else (home_name if hs > as_ else away_name)
    res = {
        'status': 'finished',
        'home_name': home_name,
        'away_name': away_name,
        'score_home': hs,
        'score_away': as_,
        'winner_name': winner,
        'is_draw': winner is None,
        'source': 'sofascore',
    }
    res.update(extra)
    return res


class TestNormaliseName:
    @pytest.mark.parametrize('raw,expected', [
        ('Kurek, Pawel', 'pawel kurek'),
        ('Tigre (ARG)', 'tigre'),
        ('Michelsen A.', 'michelsen a'),
        ('  Jan   Skvrna  ', 'jan skvrna'),
        ('', ''),
        (None, ''),
    ])
    def test_normalisation(self, raw, expected):
        assert rr.normalise_name(raw) == expected


class TestNameSimilarity:
    def test_comma_swapped_name_matches(self):
        assert rr.same_competitor('Kurek, Pawel', 'Pawel Kurek')

    def test_abbreviated_first_name_matches_on_surname(self):
        assert rr.same_competitor('Michelsen A.', 'Alex Michelsen')

    def test_country_tag_is_ignored(self):
        assert rr.same_competitor('Nacional (URU)', 'Nacional')

    def test_different_people_do_not_match(self):
        assert not rr.same_competitor('Jack Draper', 'Alex Michelsen')

    def test_name_similarity_alone_cannot_separate_lookalike_clubs(self):
        """Documents why names are never the only check.

        'Tigre' (Argentina) scores as similar to 'Tigres UANL' (Mexico), and
        tightening the bar here would break the matches we need — 'Nacional
        (URU)' against 'Club Nacional' scores no higher. Safety therefore comes
        from the fixture date and the team id anchor, not from this number; see
        TestResolveResult.
        """
        assert rr.same_competitor('Tigre', 'Tigres UANL')
        assert rr.name_similarity('Tigre', 'Tigres UANL') < 1.0

    def test_empty_names_never_match(self):
        assert not rr.same_competitor('', 'Anyone')
        assert not rr.same_competitor('Anyone', '')


class TestPredictedWinnerName:
    @pytest.mark.parametrize('pick,expected', [
        ('A', 'Adamiak Grzegorz'),
        ('1', 'Adamiak Grzegorz'),
        ('1.0', 'Adamiak Grzegorz'),
        ('B', 'Karol Strowski'),
        ('2', 'Karol Strowski'),
        ('home', 'Adamiak Grzegorz'),
        ('away', 'Karol Strowski'),
    ])
    def test_pick_resolves_to_a_name(self, pick, expected):
        assert rr.predicted_winner_name(_row(pick=pick)) == expected

    def test_draw_pick_backs_nobody(self):
        assert rr.predicted_winner_name(_row(sport='football', pick='X')) is None
        assert rr.picked_the_draw(_row(pick='X'))

    def test_falls_back_to_favorite(self):
        row = _row(pick='', favorite='B')
        assert rr.predicted_winner_name(row) == 'Karol Strowski'

    def test_falls_back_to_focus_team(self):
        row = _row(pick='', focus_team='away')
        assert rr.predicted_winner_name(row) == 'Karol Strowski'

    def test_defaults_to_home(self):
        assert rr.predicted_winner_name(_row(pick='')) == 'Adamiak Grzegorz'

    def test_missing_teams_yield_nothing(self):
        assert rr.predicted_winner_name({'scoring_pick': '1'}) is None


class TestSettleFromResult:
    def test_correct_pick_is_a_win(self):
        assert rr.settle_from_result(_row(), _result())['outcome'] == 'won'

    def test_wrong_pick_is_a_loss(self):
        assert rr.settle_from_result(_row(pick='B'), _result())['outcome'] == 'lost'

    def test_settles_correctly_when_orientation_is_flipped(self):
        """The manifest's home/away order need not match the source's.

        Position-based settlement credited the wrong side here; name-based
        settlement does not care which slot the winner occupied.
        """
        row = _row(home='Jacek Przewlocki', away='Marcin Kowalczyk', pick='A')
        # The source lists Kowalczyk as home, and he won 3-1.
        res = _result(home_name='Marcin Kowalczyk', away_name='Jacek Przewlocki',
                      hs=3, as_=1)

        settled = rr.settle_from_result(row, res)

        assert settled['outcome'] == 'lost'
        assert settled['winner_name'] == 'Marcin Kowalczyk'

    def test_score_is_shown_in_the_row_orientation(self):
        """A '3-1' next to a lost pick reads like a bug, so the score is flipped."""
        row = _row(home='Jacek Przewlocki', away='Marcin Kowalczyk', pick='A')
        res = _result(home_name='Marcin Kowalczyk', away_name='Jacek Przewlocki',
                      hs=3, as_=1)

        settled = rr.settle_from_result(row, res)

        assert settled['score'] == '1-3'
        assert settled['orientation_flipped'] is True

    def test_score_is_untouched_when_orientation_agrees(self):
        settled = rr.settle_from_result(_row(), _result(hs=3, as_=2))
        assert settled['score'] == '3-2'
        assert 'orientation_flipped' not in settled

    def test_draw_in_a_draw_sport(self):
        row = _row(sport='football', home='Alpha', away='Beta', pick='1')
        res = _result(home_name='Alpha', away_name='Beta', hs=1, as_=1)

        assert rr.settle_from_result(row, res)['outcome'] == 'draw'

    def test_backing_the_draw_and_getting_it_is_a_win(self):
        row = _row(sport='football', home='Alpha', away='Beta', pick='X')
        res = _result(home_name='Alpha', away_name='Beta', hs=2, as_=2)

        assert rr.settle_from_result(row, res)['outcome'] == 'won'

    def test_backing_the_draw_and_losing_it_is_a_loss(self):
        row = _row(sport='football', home='Alpha', away='Beta', pick='X')
        res = _result(home_name='Alpha', away_name='Beta', hs=2, as_=0)

        assert rr.settle_from_result(row, res)['outcome'] == 'lost'

    def test_cancelled_fixture_is_void_not_pending(self):
        """Michelsen vs Draper was called off — re-checking will never settle it."""
        res = {'status': 'void', 'event_status': 'canceled', 'source': 'sofascore'}

        settled = rr.settle_from_result(_row(), res)

        assert settled['outcome'] == 'void'
        assert settled['actual'] == 'canceled'

    def test_no_result_stays_pending(self):
        assert rr.settle_from_result(_row(), None)['outcome'] == 'pending'

    def test_unfinished_result_stays_pending(self):
        res = {'status': 'inprogress', 'source': 'sofascore'}
        assert rr.settle_from_result(_row(), res)['outcome'] == 'pending'


class TestOutcomeFromEvent:
    @staticmethod
    def _event(status='finished', hs=3, as_=1, home='Alpha', away='Beta'):
        return {
            'id': 1,
            'status': {'type': status},
            'homeTeam': {'name': home},
            'awayTeam': {'name': away},
            'homeScore': {'current': hs},
            'awayScore': {'current': as_},
            'startTimestamp': 1785196800,
        }

    def test_finished_event_yields_a_winner_name(self):
        out = rr._outcome_from_event(self._event(), 'table-tennis')
        assert out['winner_name'] == 'Alpha'
        assert out['winner'] == 'home'

    def test_level_score_is_not_a_result_where_draws_cannot_happen(self):
        assert rr._outcome_from_event(
            self._event(hs=1, as_=1), 'table-tennis') is None

    def test_level_score_is_a_draw_in_football(self):
        out = rr._outcome_from_event(self._event(hs=1, as_=1), 'football')
        assert out['is_draw'] is True
        assert out['winner'] == 'draw'

    @pytest.mark.parametrize('status', ['canceled', 'postponed', 'suspended'])
    def test_called_off_statuses_are_void(self, status):
        out = rr._outcome_from_event(self._event(status=status), 'tennis')
        assert out['status'] == 'void'
        assert out['event_status'] == status

    def test_not_started_is_not_a_result(self):
        assert rr._outcome_from_event(
            self._event(status='notstarted'), 'tennis') is None

    def test_missing_score_is_not_a_result(self):
        event = self._event()
        event['homeScore'] = {}
        assert rr._outcome_from_event(event, 'tennis') is None


class TestResolveResult:
    def test_refuses_to_settle_without_a_date(self, monkeypatch):
        """Undated name matching settled 'Tigre' against Colombian clubs."""
        monkeypatch.setattr(
            'sofascore_scraper.find_team_by_name',
            lambda *a, **k: pytest.fail('must not search without a date'))

        assert rr.resolve_result('Tigre', 'Nacional', 'football', None) is None

    def test_undated_search_is_possible_when_explicitly_allowed(self, monkeypatch):
        calls = []
        monkeypatch.setattr('sofascore_scraper.find_team_by_name',
                            lambda name, slug=None: calls.append(name) or None)

        rr.resolve_result('Alpha', 'Beta', 'tennis', None, allow_undated=True)

        assert calls, 'the search should have been attempted'

    def test_event_on_another_date_is_rejected(self, monkeypatch):
        monkeypatch.setattr('sofascore_scraper.find_team_by_name',
                            lambda name, slug=None: {'id': 7, 'name': name})
        monkeypatch.setattr(
            'sofascore_scraper._api_get_json',
            lambda url, timeout=10: {'events': [{
                'id': 2,
                'status': {'type': 'finished'},
                'homeTeam': {'id': 7, 'name': 'Alpha'},
                'awayTeam': {'id': 8, 'name': 'Beta'},
                'homeScore': {'current': 3}, 'awayScore': {'current': 0},
                'startTimestamp': 1785196800,   # 2026-07-28
            }]})

        assert rr.resolve_result('Alpha', 'Beta', 'tennis', '2026-07-30') is None
        assert rr.resolve_result('Alpha', 'Beta', 'tennis', '2026-07-28')

    def test_opponent_must_match(self, monkeypatch):
        monkeypatch.setattr('sofascore_scraper.find_team_by_name',
                            lambda name, slug=None: {'id': 7, 'name': name})
        monkeypatch.setattr(
            'sofascore_scraper._api_get_json',
            lambda url, timeout=10: {'events': [{
                'id': 2,
                'status': {'type': 'finished'},
                'homeTeam': {'id': 7, 'name': 'Alpha'},
                'awayTeam': {'id': 9, 'name': 'Someone Else'},
                'homeScore': {'current': 3}, 'awayScore': {'current': 0},
                'startTimestamp': 1785196800,
            }]})

        assert rr.resolve_result('Alpha', 'Beta', 'tennis', '2026-07-28') is None

    def test_event_must_involve_the_resolved_team(self, monkeypatch):
        """Guards against a name fluke attaching a stranger's fixture."""
        monkeypatch.setattr('sofascore_scraper.find_team_by_name',
                            lambda name, slug=None: {'id': 7, 'name': name})
        monkeypatch.setattr(
            'sofascore_scraper._api_get_json',
            lambda url, timeout=10: {'events': [{
                'id': 2,
                'status': {'type': 'finished'},
                'homeTeam': {'id': 111, 'name': 'Alpha'},
                'awayTeam': {'id': 222, 'name': 'Beta'},
                'homeScore': {'current': 3}, 'awayScore': {'current': 0},
                'startTimestamp': 1785196800,
            }]})

        assert rr.resolve_result('Alpha', 'Beta', 'tennis', '2026-07-28') is None

    def test_unknown_team_yields_nothing(self, monkeypatch):
        monkeypatch.setattr('sofascore_scraper.find_team_by_name',
                            lambda name, slug=None: None)

        assert rr.resolve_result('Nobody', 'Nowhere', 'tennis', '2026-07-28') is None


class TestSettleMatch:
    def test_fallback_date_is_used_when_the_row_has_none(self, monkeypatch):
        """Every table-tennis row on 2026-07-28 had match_date=None."""
        seen = {}

        def fake_resolve(home, away, sport, date, **kw):
            seen['date'] = date
            return None

        monkeypatch.setattr(rr, 'resolve_result', fake_resolve)
        rr.settle_match(_row(match_date=None), fallback_date='2026-07-28')

        assert seen['date'] == '2026-07-28'

    def test_row_date_wins_over_the_fallback(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(rr, 'resolve_result',
                            lambda h, a, s, d, **k: seen.update(date=d))

        rr.settle_match(_row(match_date='2026-07-20'), fallback_date='2026-07-28')

        assert seen['date'] == '2026-07-20'
