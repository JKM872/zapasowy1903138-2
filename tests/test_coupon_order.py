"""C10 A-4: Telegram goes out before network settling; settling respects its budget."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import coupon_builder as cb  # noqa: E402


def test_telegram_before_network_settle(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cb, 'collect', lambda d: [])
    monkeypatch.setattr(cb, 'build_coupons', lambda legs: {})
    monkeypatch.setattr(cb, 'message', lambda d, c, b: 'msg')
    monkeypatch.setattr(cb, 'settle_past', lambda network=True, budget_s=None, **k: calls.append(('settle', network)) or '')
    monkeypatch.setattr(cb, 'send_telegram', lambda t: calls.append(('tg', None)))
    monkeypatch.setattr(sys, 'argv', ['x', '--date', '2026-11-01', '--no-superbet', '--results-dir', str(tmp_path)])
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    assert cb.main() == 0
    assert calls == [('settle', False), ('tg', None), ('settle', True)]


def test_settle_stops_at_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, 'COUPON_DIR', str(tmp_path))
    legs = [{'won': None} for _ in range(3)]
    (tmp_path / 'coupons_2020-01-01.json').write_text(json.dumps(
        {'date': '2020-01-01', 'coupons': {'AKO3': {'legs': legs, 'total_odds': 2.0}}}), encoding='utf-8')
    hits = []
    monkeypatch.setattr(cb, 'settle_leg', lambda d, l: hits.append(1) or True)
    cb.settle_past(budget_s=-1)
    assert hits == []
    cb.settle_past(network=False)
    assert hits == []
