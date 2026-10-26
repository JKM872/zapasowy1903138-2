"""tools/staking.py – quarter Kelly for grade A, clamped to 1–2% of the bankroll."""
from tools import staking


def test_grade_a_positive_edge_quarter_kelly():
    # edge = 0.6*2.0-1 = 0.2 -> f = 0.25*0.2/1.0 = 5% -> clamped to 2.0
    assert staking.stake_pct('A', 0.6, 2.0) == 2.0
    # edge = 0.56*1.9-1 = 0.064 -> f = 0.25*0.064/0.9 = 1.78% -> 1.8 (round 1 dp)
    assert staking.stake_pct('A', 0.56, 1.9) == 1.8


def test_small_edge_clamps_to_one():
    # edge = 0.52*1.95-1 = 0.014 -> 0.39% -> clamped up to 1.0
    assert staking.stake_pct('A', 0.52, 1.95) == 1.0


def test_no_edge_or_not_grade_a_is_one():
    assert staking.stake_pct('A', 0.5, 1.9) == 1.0          # negative edge
    assert staking.stake_pct('B', 0.7, 2.5) == 1.0          # B never above base
    assert staking.stake_pct('C', 0.7, 2.5) == 1.0


def test_fallback_and_bad_inputs_are_one():
    assert staking.stake_pct('A', None, 2.0) == 1.0         # rules fallback: no pCal
    assert staking.stake_pct('A', 0.6, None) == 1.0
    assert staking.stake_pct('A', 0.6, 1.0) == 1.0
    assert staking.stake_pct('A', 'x', 2.0) == 1.0
    assert staking.stake_pct('A', 1.2, 2.0) == 1.0
    assert staking.stake_pct(None, 0.6, 2.0) == 1.0


def test_always_within_bounds():
    for p in (0.3, 0.5, 0.6, 0.8, 0.95):
        for o in (1.2, 1.6, 2.0, 3.5, 10.0):
            assert 1.0 <= staking.stake_pct('A', p, o) <= 2.0
