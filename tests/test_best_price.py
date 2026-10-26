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


def test_module_import_not_counted_in_time_budget(monkeypatch):
    # cold import of forebet_pipeline on a fresh checkout takes seconds; only the call is timed
    monkeypatch.setattr(BP, 'BUDGET_S', {'pinnacle': 0.3})
    fake = _src(1.8, 2.1)
    imported = []
    monkeypatch.setattr(BP, '_MODULES', {fake: 'slow_module'})
    monkeypatch.setattr(BP.importlib, 'import_module',
                        lambda name: (time.sleep(0.6), imported.append(name)))
    monkeypatch.setattr(BP, 'SOURCES', {'pinnacle': fake})
    r = BP.best_price(_pick())
    assert imported == ['slow_module']
    assert r['bestOdds'] == 1.8 and r['bestOddsSource'] == 'pinnacle'


def test_oddssafari_matches_nhl_abbreviations(monkeypatch):
    import oddssafari_coupons as osc
    board = [osc.CouponOdds('NY Rangers', 'LA Kings', home_odds=2.25, draw_odds=4.21,
                            away_odds=2.86, bookmakers=13, kickoff='2026-10-26 23:00:00'),
             osc.CouponOdds('EDM Oilers', 'DET Red Wings', home_odds=1.97, draw_odds=4.57,
                            away_odds=3.4, bookmakers=13, kickoff='2026-10-27 01:30:00')]
    monkeypatch.setattr(osc, 'fetch_coupon_board', lambda sport, dates=None: board)
    monkeypatch.setattr(BP, 'SOURCES', {'oddssafari': BP._oddssafari})
    hk = _pick(sport='hockey', match='Edmonton Oilers vs Detroit Red Wings',
               pick='Edmonton Oilers', market='2way_equiv')
    r = BP.best_price(hk, '2026-10-26')
    assert r['bestOddsSource'] == 'oddssafari' and r['booksCount'] == 13
    assert r['kickoff'] == '2026-10-27 01:30:00'
    assert 1.4 < r['bestOdds'] < 1.97                  # 2-way equivalent of the 1X2 home price
    # a fixture missing from the board stays unpriced (coverage, not matching)
    assert BP.best_price(_pick(sport='hockey', match='Vancouver Canucks vs Minnesota Wild',
                               pick='Minnesota Wild', market='2way_equiv'),
                         '2026-10-26')['bestOdds'] is None
