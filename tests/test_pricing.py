"""tools/pricing.py – 2-way conversion per sport, haircut, floor, kickoff UTC."""
import json
import os
from datetime import datetime

import pytest

from tools import pricing

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'edge', 'kickoff_verification.json')


def _expected_2way(side, opp, draw):
    ps, po, pd = 1 / side, 1 / opp, 1 / draw
    over = ps + po + pd
    p2 = (ps + pd * ps / (ps + po)) / over
    return round(1 / (p2 * over), 3)


@pytest.mark.parametrize('sport', ['hockey', 'basketball', 'baseball'])
def test_two_way_equiv_sports_convert_draw_quotes(sport):
    odds = {'home': 3.7, 'draw': 4.4, 'away': 1.78}
    h2, a2, market = pricing.two_way(odds, sport)
    assert market == '2way_equiv'
    assert a2 == _expected_2way(1.78, 3.7, 4.4)
    assert h2 == _expected_2way(3.7, 1.78, 4.4)
    assert a2 < 1.78 and h2 < 3.7          # the draw share moves into both sides


def test_two_way_equiv_sport_without_draw_passes_through():
    assert pricing.two_way({'home': 1.9, 'away': 1.95}, 'hockey') == (1.9, 1.95, '2way')


@pytest.mark.parametrize('sport', ['tennis', 'volleyball'])
def test_tennis_volleyball_pass_through(sport):
    assert pricing.two_way({'home': 1.5, 'away': '2.6', 'draw': None}, sport) == (1.5, 2.6, '2way')


def test_football_stays_three_way():
    assert pricing.two_way({'home': 2.1, 'draw': 3.3, 'away': 3.5}, 'football') == (2.1, 3.5, '3way')
    assert pricing.two_way({'home': 2.1, 'away': 3.5}, 'football')[2] == '3way'


def test_side_price_and_missing_prices():
    assert pricing.side_price({'home': 3.7, 'draw': 4.4, 'away': 1.78}, 'hockey', 'away') == (
        _expected_2way(1.78, 3.7, 4.4), '2way_equiv')
    assert pricing.two_way({'home': None, 'draw': 4.0, 'away': 1.8}, 'hockey') == (None, None, '2way_equiv')
    assert pricing.two_way(None, 'tennis') == (None, None, '2way')


def test_haircut_profit():
    assert pricing.haircut_profit(2.0, True) == pytest.approx(0.95)
    assert pricing.haircut_profit(2.0, False) == -1.0


@pytest.mark.parametrize('p', [0.3, 0.5, 0.655, 0.75, 0.9])
def test_floor_price_is_break_even_after_haircut(p):
    f = pricing.floor_price(p)
    assert f == pytest.approx(1 + (1 - p) / (0.95 * p), abs=0.01)
    assert round(f, 2) == f                               # 2 decimals
    ev = lambda o: p * 0.95 * (o - 1) - (1 - p)          # noqa: E731
    assert ev(f) >= -1e-9 and ev(f - 0.01) < 0


def test_floor_price_known_values():
    assert pricing.floor_price(0.5) == 2.06
    assert pricing.floor_price(0.655) == 1.56


def test_parse_kickoff_prefers_explicit_sources():
    assert pricing.parse_kickoff('2026-10-26', '22:00', ['2026-10-26T19:00:00Z'], 'football') == '2026-10-26T19:00:00Z'
    assert pricing.parse_kickoff('2026-10-26', '22:00', [None, 1793046000000]) == '2026-10-26T20:20:00Z'
    # a source more than 3 days away is rejected -> next source / fallback
    assert pricing.parse_kickoff('2026-10-26', '20:00', ['2026-11-01T01:07:00Z'], 'basketball') == '2026-10-26T19:00:00Z'


def test_parse_kickoff_fallback_per_sport_and_night_wrap():
    assert pricing.parse_kickoff('2026-10-26', '22:00', sport='football') == '2026-10-26T19:00:00Z'
    assert pricing.parse_kickoff('2026-10-26', '20:00', sport='basketball') == '2026-10-26T19:00:00Z'
    assert pricing.parse_kickoff('2026-10-26', '21:30', sport='tennis') == '2026-10-26T21:30:00Z'
    # times before 05:00 belong to the night after the file day
    assert pricing.parse_kickoff('2026-10-26', '00:00', sport='basketball') == '2026-10-26T23:00:00Z'
    assert pricing.parse_kickoff('2026-10-26', '00:30', sport='hockey') == '2026-10-27T00:30:00Z'
    # default Europe/Warsaw, summer time (CEST)
    assert pricing.parse_kickoff('2026-09-15', '18:00', sport='handball') == '2026-09-15T16:00:00Z'
    assert pricing.parse_kickoff('2026-10-26', None) is None
    assert pricing.parse_kickoff('2026-10-26', 'TBD') is None


def test_kickoff_fallback_verified_against_pinnacle_fixture():
    """>=20 real Forebet rows agree with Pinnacle startTime within 15 min (2026-10-26)."""
    rows = json.load(open(FIX, encoding='utf-8'))['rows']

    def mins(a, b):
        return abs((datetime.fromisoformat(a.replace('Z', '+00:00'))
                    - datetime.fromisoformat(b.replace('Z', '+00:00'))).total_seconds()) / 60
    agree = [r for r in rows
             if mins(pricing.parse_kickoff(r['day'], r['time'], sport=r['sport']), r['pinnacleStartTime']) <= 15]
    assert len(rows) >= 20 and len(agree) >= 20
    for sport in ('football', 'basketball'):
        sp = [r for r in rows if r['sport'] == sport]
        assert sum(r in agree for r in sp) >= 0.9 * len(sp)
