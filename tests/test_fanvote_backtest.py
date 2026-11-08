"""tools.fanvote_backtest.calibrate on synthetic rows."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import fanvote_backtest as bt  # noqa: E402


def rows(votes, n, won_every=2, odds=2.0, sport='football'):
    return [{'sport': sport, 'fan': 75, 'votes': votes, 'odds': odds, 'won': i % won_every == 0}
            for i in range(n)]


def test_calibrate_accepts_good_bands():
    data = rows(150, 40) + rows(60, 40) + rows(40, 40) + rows(25, 40, won_every=4)
    assert bt.calibrate(data)['minVotes'] == 30


def test_calibrate_thin_data_is_100():
    assert bt.calibrate(rows(150, 10) + rows(60, 5))['minVotes'] == 100
    assert bt.calibrate(rows(150, 40) + rows(60, 10))['minVotes'] == 100
