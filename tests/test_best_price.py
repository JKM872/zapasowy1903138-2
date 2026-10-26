"""tools/best_price.py – max comparable quote, outlier guard, failing sources skipped."""
import time

import pytest

from tools import best_price as BP


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(BP, '_DEAD', set())
    monkeypatch.setattr(BP, '_BOARDS', {})


def _src(home=None, away=None, draw=None, **extra):
    def fn(h, a, sport, day):
        return dict({'home': home, 'draw': draw, 'away': away}, **extra)
    return fn


def _pick(sport='tennis', match='Alpha A. vs Beta B.', pick='Alpha A.', market='2way'):
    return {'sport': sport, 'match': match, 'pick': pick, 'odds': 1.9, 'odds2': 1.9,
            'oddsMarket': market}


def test_max_over_sources(monkeypatch):
    monkeypatch.setattr(BP, 'SOURCES', {
        'pinnacle': _src(1.92, 1.95),
        'oddssafari': _src(2.01, 1.85, books=13, kickoff='2026-10-26 18:00:00'),
        'livesport': _src(1.97, 1.9)})
    r = BP.best_price(_pick(), '2026-10-26')
    assert r['bestOdds'] == 2.01 and r['bestOddsSource'] == 'oddssafari'
    assert r['booksCount'] == 13 and r['bestOddsAt'].endswith('Z')
    assert r['kickoff'] == '2026-10-26 18:00:00'
    assert set(r['quotes']) == {'pinnacle', 'oddssafari', 'livesport'}


def test_away_side_uses_away_price(monkeypatch):
    monkeypatch.setattr(BP, 'SOURCES', {'pinnacle': _src(1.5, 2.6)})
    r = BP.best_price(_pick(pick='Beta B.'))
    assert r['bestOdds'] == 2.6


def test_outlier_guard_drops_stale_line(monkeypatch):
    # 2.60 > 1.25 x median(1.90, 1.95) -> ignored as a stale line
    monkeypatch.setattr(BP, 'SOURCES', {
        'pinnacle': _src(1.9, 2.0), 'oddssafari': _src(2.6, 1.5), 'livesport': _src(1.95, 1.9)})
    r = BP.best_price(_pick())
    assert 'oddssafari' not in r['quotes']
    assert r['bestOdds'] == 1.95 and r['bestOddsSource'] == 'livesport'


def test_drop_outliers_two_quotes():
    assert BP.drop_outliers({'a': 2.0, 'b': 2.6}) == {'a': 2.0}
    assert BP.drop_outliers({'a': 2.0, 'b': 2.4}) == {'a': 2.0, 'b': 2.4}
    assert BP.drop_outliers({'a': 2.0}) == {'a': 2.0}


def test_failing_source_skipped_and_not_retried(monkeypatch, capsys):
    calls = []

    def boom(h, a, sport, day):
        calls.append(1)
        raise ConnectionError('down')
    monkeypatch.setattr(BP, 'SOURCES', {'pinnacle': boom, 'livesport': _src(1.88, 2.0)})
    r = BP.best_price(_pick())
    assert r['bestOdds'] == 1.88 and r['bestOddsSource'] == 'livesport'
    assert 'WARNING best price: pinnacle tennis skipped' in capsys.readouterr().err
    BP.best_price(_pick())
    assert len(calls) == 1                      # dead for the rest of the run


def test_slow_source_times_out(monkeypatch):
    monkeypatch.setattr(BP, 'BUDGET_S', {'pinnacle': 0.2})
    monkeypatch.setattr(BP, 'TIMEOUT_S', 0.2)

    def slow(h, a, sport, day):
        time.sleep(2)
        return {'home': 3.0, 'away': 1.2}
    monkeypatch.setattr(BP, 'SOURCES', {'pinnacle': slow})
    t0 = time.time()
    r = BP.best_price(_pick())
    assert time.time() - t0 < 1.5
    assert r['bestOdds'] is None and r['quotes'] == {} and r['booksCount'] == 0


def test_all_sources_fail_gives_none(monkeypatch):
    monkeypatch.setattr(BP, 'SOURCES', {'pinnacle': lambda *a: None, 'livesport': lambda *a: {}})
    r = BP.best_price(_pick())
    assert r['bestOdds'] is None and r['bestOddsSource'] is None


def test_quote_range(monkeypatch):
    monkeypatch.setattr(BP, 'SOURCES', {'pinnacle': _src(60.0, 1.1), 'livesport': _src(1.005, 9.0)})
    assert BP.best_price(_pick())['bestOdds'] is None


def test_football_stays_three_way(monkeypatch):
    monkeypatch.setattr(BP, 'SOURCES', {'pinnacle': _src(2.1, 3.5, draw=3.4)})
    fb = _pick(sport='football', match='Home FC vs Away FC', pick='Home FC', market='3way')
    assert BP.best_price(fb)['quotes'] == {'pinnacle': 2.1}
    # a 3-way quote never prices a 2-way pick
    assert BP.best_price(_pick(sport='football', market='2way'))['bestOdds'] is None


def test_hockey_three_way_converted_to_two_way(monkeypatch):
    monkeypatch.setattr(BP, 'SOURCES', {'livesport': _src(2.3, 2.9, draw=4.2),
                                        'pinnacle': _src(1.8, 2.1)})
    hk = _pick(sport='hockey', match='Home HC vs Away HC', pick='Home HC', market='2way_equiv')
    r = BP.best_price(hk)
    assert r['quotes']['pinnacle'] == 1.8
    assert 1.6 < r['quotes']['livesport'] < 1.9          # 2-way equivalent, not 2.30
