"""Tests for the OddsSafari daily-coupon odds source.

The parsing layer is pure, so it is exercised against a payload shaped exactly
like the live one (verified 2026-07-27: MLB priced by 13 bookmakers). The
network layer is monkeypatched — these tests never touch the internet.
"""

import json

import pytest

from oddssafari_coupons import (CouponOdds, attach_odds_to_rows,
                                extract_payload_from_html, fetch_coupon_odds,
                                find_coupon_match, parse_coupon_payload)


def _payload(*events):
    return {
        'coupons': {
            'EventsGroupDate': {
                '1': {
                    'LeagueNameShow': 'MLB',
                    'LeagueUrls': {'en': '/baseball/usa/mlb'},
                    'Events': list(events),
                }
            }
        }
    }


def _event(home='DET Tigers', away='TOR Blue Jays', bets=None, **extra):
    event = {
        'EventID': 4242,
        'EventName': f'{home} - {away}',
        'EventDate': '2026-07-27 23:10:00',
        'EventParticipant1_Name': home,
        'EventParticipant2_Name': away,
        'EventUrls': {'en': '/baseball/mlb/det-tor'},
        'Bets': bets if bets is not None else [
            {'Outcome': '1', 'Quote': 1.886, 'NumOfBookmakers': 13},
            {'Outcome': '2', 'Quote': 1.952, 'NumOfBookmakers': 13},
        ],
    }
    event.update(extra)
    return event


class TestParseCouponPayload:
    def test_reads_prices_and_metadata(self):
        rows = parse_coupon_payload(_payload(_event()))

        assert len(rows) == 1
        row = rows[0]
        assert row.home_team == 'DET Tigers'
        assert row.away_team == 'TOR Blue Jays'
        assert row.home_odds == pytest.approx(1.886)
        assert row.away_odds == pytest.approx(1.952)
        assert row.draw_odds is None       # baseball has no draw market
        assert row.bookmakers == 13
        assert row.event_date == '2026-07-27'
        assert row.event_time == '23:10'
        assert row.league == 'MLB'
        assert row.match_url.startswith('https://www.oddssafari.com/')

    def test_draw_market_is_kept_when_present(self):
        rows = parse_coupon_payload(_payload(_event(bets=[
            {'Outcome': '1', 'Quote': 2.10, 'NumOfBookmakers': 9},
            {'Outcome': 'X', 'Quote': 3.40, 'NumOfBookmakers': 9},
            {'Outcome': '2', 'Quote': 3.10, 'NumOfBookmakers': 9},
        ])))

        assert rows[0].draw_odds == pytest.approx(3.40)

    def test_falls_back_to_splitting_event_name(self):
        rows = parse_coupon_payload(_payload(_event(
            EventParticipant1_Name='', EventParticipant2_Name='',
            EventName='NYY Yankees - BOS Red Sox')))

        assert (rows[0].home_team, rows[0].away_team) == ('NYY Yankees', 'BOS Red Sox')

    def test_rejects_impossible_quotes(self):
        """A decimal price at or below 1.0 pays nothing — treat it as absent."""
        rows = parse_coupon_payload(_payload(_event(bets=[
            {'Outcome': '1', 'Quote': 1.0, 'NumOfBookmakers': 4},
            {'Outcome': '2', 'Quote': 'n/a', 'NumOfBookmakers': 4},
        ])))

        assert rows[0].home_odds is None
        assert rows[0].away_odds is None

    def test_skips_events_without_participants(self):
        assert parse_coupon_payload(_payload(_event(
            EventParticipant1_Name='', EventParticipant2_Name='',
            EventName='TBD'))) == []

    @pytest.mark.parametrize('payload', [
        None, {}, {'coupons': None}, {'coupons': {'EventsGroupDate': []}},
        {'coupons': {'EventsGroupDate': {'1': 'broken'}}},
    ])
    def test_malformed_payloads_yield_nothing(self, payload):
        assert parse_coupon_payload(payload) == []


class TestExtractPayloadFromHtml:
    def test_pulls_the_coupons_entry_out_of_next_data(self):
        payload = _payload(_event())
        html = (
            '<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({'props': {'pageProps': {'fallback': {
                '/api/coupons?sportId=90&day=1': payload,
                '/api/other': {'noise': True},
            }}}})
            + '</script></body></html>'
        )

        assert extract_payload_from_html(html) == payload

    @pytest.mark.parametrize('html', [
        '', None, '<html>no next data</html>',
        '<script id="__NEXT_DATA__">{not json}</script>',
        '<script id="__NEXT_DATA__">{"props":{"pageProps":{}}}</script>',
    ])
    def test_missing_or_broken_markup_yields_empty(self, html):
        assert extract_payload_from_html(html) == {}


class TestFindCouponMatch:
    COUPON = [
        CouponOdds('DET Tigers', 'TOR Blue Jays', home_odds=1.88, away_odds=1.95),
        CouponOdds('NYY Yankees', 'BOS Red Sox', home_odds=1.60, away_odds=2.30),
    ]

    def test_matches_abbreviated_franchise_names(self):
        """Livesport says "Detroit Tigers", the coupon says "DET Tigers"."""
        found = find_coupon_match('Detroit Tigers', 'Toronto Blue Jays', self.COUPON)

        assert found is not None
        assert found.home_team == 'DET Tigers'

    def test_exact_names_match(self):
        found = find_coupon_match('NYY Yankees', 'BOS Red Sox', self.COUPON)
        assert found.away_team == 'BOS Red Sox'

    def test_unrelated_fixture_is_not_matched(self):
        assert find_coupon_match('Real Madrid', 'Barcelona', self.COUPON) is None

    def test_reversed_fixture_is_not_matched(self):
        """Home/away order carries the pick — a flipped fixture is not a match."""
        assert find_coupon_match('Toronto Blue Jays', 'Detroit Tigers',
                                 self.COUPON) is None

    def test_empty_inputs(self):
        assert find_coupon_match('', '', self.COUPON) is None
        assert find_coupon_match('Detroit Tigers', 'Toronto Blue Jays', []) is None


class TestAttachOddsToRows:
    COUPON = [CouponOdds('DET Tigers', 'TOR Blue Jays',
                         home_odds=1.88, away_odds=1.95, bookmakers=13)]

    @pytest.fixture
    def coupon(self, monkeypatch):
        calls = []

        def fake_fetch(sport, date=None, sport_id=None):
            calls.append((sport, date))
            return list(self.COUPON)

        monkeypatch.setattr('oddssafari_coupons.fetch_coupon_odds', fake_fetch)
        return calls

    def test_fills_missing_odds(self, coupon):
        rows = [{'home_team': 'Detroit Tigers', 'away_team': 'Toronto Blue Jays'}]

        assert attach_odds_to_rows(rows, 'baseball', '2026-07-27') == 1
        assert rows[0]['home_odds'] == pytest.approx(1.88)
        assert rows[0]['away_odds'] == pytest.approx(1.95)
        assert rows[0]['odds_source'] == 'oddssafari_coupon'
        assert '13' in rows[0]['odds_bookmaker']
        assert coupon == [('baseball', '2026-07-27')]

    def test_existing_odds_are_left_alone(self, coupon):
        """A dedicated scraper's price outranks the coupon's average."""
        rows = [{'home_team': 'Detroit Tigers', 'away_team': 'Toronto Blue Jays',
                 'home_odds': 1.75, 'away_odds': 2.05}]

        assert attach_odds_to_rows(rows, 'baseball') == 0
        assert rows[0]['home_odds'] == pytest.approx(1.75)
        assert 'odds_source' not in rows[0]
        assert coupon == []          # no request when there is nothing to fill

    def test_overwrite_replaces_existing_odds(self, coupon):
        rows = [{'home_team': 'Detroit Tigers', 'away_team': 'Toronto Blue Jays',
                 'home_odds': 1.75, 'away_odds': 2.05}]

        assert attach_odds_to_rows(rows, 'baseball', overwrite=True) == 1
        assert rows[0]['home_odds'] == pytest.approx(1.88)

    def test_half_priced_row_is_treated_as_missing(self, coupon):
        rows = [{'home_team': 'Detroit Tigers', 'away_team': 'Toronto Blue Jays',
                 'home_odds': 1.75}]

        assert attach_odds_to_rows(rows, 'baseball') == 1
        assert rows[0]['away_odds'] == pytest.approx(1.95)

    def test_unmatched_row_is_untouched(self, coupon):
        rows = [{'home_team': 'Real Madrid', 'away_team': 'Barcelona'}]

        assert attach_odds_to_rows(rows, 'baseball') == 0
        assert 'home_odds' not in rows[0]

    def test_empty_coupon_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr('oddssafari_coupons.fetch_coupon_odds',
                            lambda *a, **k: [])
        rows = [{'home_team': 'Detroit Tigers', 'away_team': 'Toronto Blue Jays'}]

        assert attach_odds_to_rows(rows, 'baseball') == 0
        assert 'home_odds' not in rows[0]

    def test_no_rows(self, coupon):
        assert attach_odds_to_rows([], 'baseball') == 0
        assert coupon == []

    def test_partial_coupon_prices_are_not_attached(self, monkeypatch):
        """One-sided odds cannot price a fixture, so they are skipped."""
        monkeypatch.setattr(
            'oddssafari_coupons.fetch_coupon_odds',
            lambda *a, **k: [CouponOdds('DET Tigers', 'TOR Blue Jays',
                                        home_odds=1.88, away_odds=None)])
        rows = [{'home_team': 'Detroit Tigers', 'away_team': 'Toronto Blue Jays'}]

        assert attach_odds_to_rows(rows, 'baseball') == 0
        assert 'home_odds' not in rows[0]


class TestFetchCouponOdds:
    def test_unknown_sport_makes_no_request(self, monkeypatch):
        monkeypatch.setattr('oddssafari_coupons.SPORT_TO_PAGE_IDS', {})
        monkeypatch.setattr('oddssafari_coupons.discover_sport_page_ids',
                            lambda sport: [])
        monkeypatch.setattr('oddssafari_coupons.fetch_dropping_odds_html',
                            lambda url: pytest.fail('should not fetch'))

        assert fetch_coupon_odds('quidditch') == []

    def test_parses_a_served_page(self, monkeypatch):
        html = ('<script id="__NEXT_DATA__">'
                + json.dumps({'props': {'pageProps': {'fallback': {
                    '/api/coupons?sportId=90': _payload(_event())}}}})
                + '</script>')
        monkeypatch.setattr('oddssafari_coupons.SPORT_TO_PAGE_IDS',
                            {'baseball': ('90',)})
        monkeypatch.setattr('oddssafari_coupons.fetch_dropping_odds_html',
                            lambda url: html)

        rows = fetch_coupon_odds('baseball', '2026-07-27')

        assert len(rows) == 1
        assert rows[0].home_odds == pytest.approx(1.886)

    def test_duplicate_fixtures_across_pages_are_collapsed(self, monkeypatch):
        html = ('<script id="__NEXT_DATA__">'
                + json.dumps({'props': {'pageProps': {'fallback': {
                    '/api/coupons?sportId=90': _payload(_event(), _event())}}}})
                + '</script>')
        monkeypatch.setattr('oddssafari_coupons.SPORT_TO_PAGE_IDS',
                            {'baseball': ('90', '91')})
        monkeypatch.setattr('oddssafari_coupons.fetch_dropping_odds_html',
                            lambda url: html)

        assert len(fetch_coupon_odds('baseball')) == 1

    def test_404_page_is_skipped(self, monkeypatch):
        monkeypatch.setattr('oddssafari_coupons.SPORT_TO_PAGE_IDS',
                            {'baseball': ('90',)})
        monkeypatch.setattr('oddssafari_coupons.fetch_dropping_odds_html',
                            lambda url: '<title>404 | OddsSafari</title>')

        assert fetch_coupon_odds('baseball') == []

    def test_date_filter_keeps_only_that_day(self, monkeypatch):
        payload = _payload(
            _event(home='DET Tigers', EventDate='2026-07-27 23:10:00'),
            _event(home='NYY Yankees', away='BOS Red Sox',
                   EventDate='2026-07-28 18:05:00'),
        )
        html = ('<script id="__NEXT_DATA__">'
                + json.dumps({'props': {'pageProps': {'fallback': {
                    '/api/coupons?sportId=90': payload}}}})
                + '</script>')
        monkeypatch.setattr('oddssafari_coupons.SPORT_TO_PAGE_IDS',
                            {'baseball': ('90',)})
        monkeypatch.setattr('oddssafari_coupons.fetch_dropping_odds_html',
                            lambda url: html)

        rows = fetch_coupon_odds('baseball', '2026-07-28')

        assert [r.home_team for r in rows] == ['NYY Yankees']
