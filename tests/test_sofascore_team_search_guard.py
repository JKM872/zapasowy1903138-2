"""Team search must not attach a stranger's match.

Observed in the production log of run 30742179267: searching for the Australian
ice-hockey fixture

    CBR Brave vs Central Coast Rhinos

returned, and accepted, a Spanish football fixture

    ✅ SofaScore Strategy 2: Found CF Badalona Futur vs CF Can Vidalet (sim:0.32)

Three separate guards were missing: the team returned by `/search/teams` was
taken as `teams[0]` without checking it resembled the query at all, the sport was
never compared, and the opponent was accepted at 0.30. Had that event carried
votes, another sport's crowd would have steered our pick.
"""

import pytest

import sofascore_scraper as ss
from sofascore_scraper import (_OPPONENT_MIN_SIMILARITY,
                               _TEAM_SEARCH_MIN_SIMILARITY, similarity_score)


class TestTheRealFailureIsRejected:
    def test_cbr_brave_does_not_resemble_cf_badalona_futur(self):
        sim = similarity_score('CBR Brave', 'CF Badalona Futur')
        assert sim < _TEAM_SEARCH_MIN_SIMILARITY, (
            f'sim={sim:.2f} — taki kandydat nie może przejść progu')

    def test_opponent_pair_is_below_the_new_threshold(self):
        sim = similarity_score('Central Coast Rhinos', 'CF Can Vidalet')
        assert sim < _OPPONENT_MIN_SIMILARITY, f'sim={sim:.2f}'

    def test_the_old_threshold_would_have_accepted_it(self):
        """Pins why the number changed rather than merely that it did."""
        assert similarity_score('Central Coast Rhinos', 'CF Can Vidalet') < 0.45


class TestThresholdsAreSane:
    def test_team_threshold_is_stricter_than_opponent(self):
        assert _TEAM_SEARCH_MIN_SIMILARITY > _OPPONENT_MIN_SIMILARITY

    def test_thresholds_are_stricter_than_the_date_list_default(self):
        """Global search is riskier than a same-day, same-sport candidate list."""
        assert _OPPONENT_MIN_SIMILARITY > 0.35

    def test_a_genuine_name_still_passes(self):
        for ours, theirs in (
            ('Manchester United', 'Manchester United'),
            ('Bayern Munich', 'Bayern München'),
            ('Legia Warszawa', 'Legia Warsaw'),
            ('Yunost Minsk', 'Yunost Minsk'),
        ):
            assert similarity_score(ours, theirs) >= _TEAM_SEARCH_MIN_SIMILARITY, \
                f'{ours} vs {theirs}'


class TestSearchEventViaApiGuards:
    """Drives the real function with a stubbed API to check each guard."""

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        self.calls = []

        def fake_get(url, timeout=10):
            self.calls.append(url)
            return self.responses.get(url)

        monkeypatch.setattr(ss, '_api_get_json', fake_get)
        # Neuter the other strategies so only Strategy 2 can answer.
        monkeypatch.setattr(ss, '_search_event_for_date',
                            lambda *a, **k: None)
        self.responses = {}

    def _search_url(self, q):
        return (f"https://api.sofascore.com/api/v1/search/teams/"
                f"{q.replace(' ', '%20')}")

    def _events_url(self, team_id, endpoint):
        return (f"https://api.sofascore.com/api/v1/team/{team_id}/"
                f"events/{endpoint}/0")

    def test_a_wrong_sport_team_is_skipped(self):
        self.responses[self._search_url('CBR Brave')] = {
            'teams': [{'id': 54127, 'name': 'CF Badalona Futur',
                       'sport': {'slug': 'football'}}]}
        got = ss.search_event_via_api('CBR Brave', 'Central Coast Rhinos',
                                      sport='hockey', date_str='2026-08-02')
        assert got is None
        assert not any('/events/' in u for u in self.calls), \
            'nie powinniśmy nawet pobierać terminarza obcej drużyny'

    def test_a_dissimilar_team_name_is_skipped(self):
        self.responses[self._search_url('CBR Brave')] = {
            'teams': [{'id': 1, 'name': 'Completely Different FC',
                       'sport': {'slug': 'ice-hockey'}}]}
        assert ss.search_event_via_api('CBR Brave', 'Central Coast Rhinos',
                                       sport='hockey',
                                       date_str='2026-08-02') is None

    def test_event_without_the_resolved_team_is_skipped(self):
        """Name similarity alone must not attach a fixture."""
        self.responses[self._search_url('Yunost Minsk')] = {
            'teams': [{'id': 77, 'name': 'Yunost Minsk',
                       'sport': {'slug': 'ice-hockey'}}]}
        self.responses[self._events_url(77, 'next')] = {'events': [{
            'id': 999,
            'homeTeam': {'id': 111, 'name': 'Yunost Minsk'},
            'awayTeam': {'id': 222, 'name': 'Brest'},
        }]}
        # Neither side carries id 77, so the anchor must reject it.
        assert ss.search_event_via_api('Yunost Minsk', 'Brest',
                                       sport='hockey',
                                       date_str='2026-08-02') is None

    def test_a_correct_event_is_accepted(self):
        self.responses[self._search_url('Yunost Minsk')] = {
            'teams': [{'id': 77, 'name': 'Yunost Minsk',
                       'sport': {'slug': 'ice-hockey'}}]}
        self.responses[self._events_url(77, 'next')] = {'events': [{
            'id': 4242,
            'homeTeam': {'id': 77, 'name': 'Yunost Minsk'},
            'awayTeam': {'id': 222, 'name': 'Brest'},
        }]}
        assert ss.search_event_via_api('Yunost Minsk', 'Brest',
                                       sport='hockey',
                                       date_str='2026-08-02') == 4242

    def test_a_weak_opponent_match_is_rejected(self):
        self.responses[self._search_url('Yunost Minsk')] = {
            'teams': [{'id': 77, 'name': 'Yunost Minsk',
                       'sport': {'slug': 'ice-hockey'}}]}
        self.responses[self._events_url(77, 'next')] = {'events': [{
            'id': 4242,
            'homeTeam': {'id': 77, 'name': 'Yunost Minsk'},
            'awayTeam': {'id': 222, 'name': 'CF Can Vidalet'},
        }]}
        assert ss.search_event_via_api('Yunost Minsk', 'Central Coast Rhinos',
                                       sport='hockey',
                                       date_str='2026-08-02') is None

    def test_missing_sport_slug_does_not_block_a_good_match(self):
        self.responses[self._search_url('Yunost Minsk')] = {
            'teams': [{'id': 77, 'name': 'Yunost Minsk'}]}
        self.responses[self._events_url(77, 'next')] = {'events': [{
            'id': 4242,
            'homeTeam': {'id': 77, 'name': 'Yunost Minsk'},
            'awayTeam': {'id': 222, 'name': 'Brest'},
        }]}
        assert ss.search_event_via_api('Yunost Minsk', 'Brest',
                                       sport='hockey',
                                       date_str='2026-08-02') == 4242

    def test_empty_search_result_is_handled(self):
        self.responses[self._search_url('Nobody')] = {'teams': []}
        assert ss.search_event_via_api('Nobody', 'Ghost', sport='hockey',
                                       date_str='2026-08-02') is None
