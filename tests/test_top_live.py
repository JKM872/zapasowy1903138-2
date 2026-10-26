"""tools/top_live.py: closing odds / CLV and the pre-kickoff final check (design K2/K3)."""
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from tools import top_live as TL

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'edge')
DAY = '2026-10-25'
KO = datetime(2026, 10, 25, 21, 45, tzinfo=timezone.utc)


def _pick(match='Udinese vs Milan', pick='Milan', sport='football', **kw):
    p = {'sport': sport, 'time': '22:45', 'league': 'Serie A', 'match': match, 'pick': pick,
         'odds': 2.2, 'odds2': 2.2, 'oddsMarket': '3way', 'floorOdds': 2.0,
         'kickoffUtc': '2026-10-25T21:45:00Z', 'grade': 'A'}
    p.update(kw)
    return p


def _prices(best=2.1, quote=2.0, market='3way', src='pinnacle'):
    return {'best': best, 'bestSource': 'oddssafari' if best else None, 'books': 13 if best else 0,
            'quote': quote, 'quoteSource': src if quote else None,
            'quoteMarket': market if quote else None}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated results/ dir with the availability fixture; prices from a queue."""
    monkeypatch.setattr(TL, 'RESULTS', str(tmp_path))
    monkeypatch.setattr(TL, '_AVAIL', {})
    shutil.copy(os.path.join(FIX, f'availability_{DAY}.json'), tmp_path / f'availability_{DAY}.json')
    state = {'prices': [], 'calls': []}

    def fake(pick, day):
        state['calls'].append((pick['match'], day))
        return state['prices'].pop(0) if state['prices'] else _prices()
    monkeypatch.setattr(TL, 'fetch_prices', fake)

    def write_top(day, picks):
        (tmp_path / f'top_{day}.json').write_text(json.dumps(picks), encoding='utf-8')
    state['write_top'] = write_top
    state['dir'] = tmp_path
    return state


def _live(env, day=DAY):
    return json.loads((env['dir'] / f'top_live_{day}.json').read_text(encoding='utf-8'))


def at(mins_before):
    return KO - timedelta(minutes=mins_before)


# ------------------------------------------------------------ window selection

def test_window_selects_only_picks_inside_now_minus5_now_plus100(env):
    picks = [_pick(match='Hibernian vs Celtic', pick='Celtic', kickoffUtc='2026-10-25T21:45:00Z'),
             _pick(match='A vs B', pick='A', kickoffUtc='2026-10-25T22:30:00Z'),      # 105 min
             _pick(match='E vs F', pick='E', kickoffUtc='2026-10-25T22:20:00Z'),      # 95 min
             _pick(match='C vs D', pick='C', kickoffUtc='2026-10-25T22:00:00Z')]      # 75 min
    env['write_top'](DAY, picks)
    TL.run(at(60))                                     # now = 20:45
    live = _live(env)
    assert set(live) == {'football|Hibernian vs Celtic', 'football|C vs D'}
    assert live['football|C vs D']['checks'][0]['minsToKick'] == 75
    assert TL.due(at(60)) == 2
    assert [m for _, _, _, m in TL._candidates(at(60))] == [60, 105, 95, 75]


def test_after_midnight_kickoff_is_read_from_yesterdays_file(env):
    # top_2026-10-25 lists the night after it: kickoff 2026-10-26 01:30 UTC.
    env['write_top'](DAY, [_pick(match='Utah Jazz vs Los Angeles Lakers', pick='Los Angeles Lakers',
                                 sport='basketball', oddsMarket='2way_equiv',
                                 kickoffUtc='2026-10-26T01:30:00Z')])
    now = datetime(2026, 10, 26, 0, 30, tzinfo=timezone.utc)      # today = 26th
    out = TL.run(now)
    assert list(out) == [DAY]                                     # written to the pick's day file
    assert _live(env)['basketball|Utah Jazz vs Los Angeles Lakers']['checks'][0]['minsToKick'] == 60
    assert env['calls'] == [('Utah Jazz vs Los Angeles Lakers', DAY)]
    assert not (env['dir'] / 'top_live_2026-10-26.json').exists()


def test_kickoff_falls_back_to_forebet_time_for_old_picks(env):
    p = _pick(match='D. Dietrich vs C. Smith', pick='D. Dietrich', sport='tennis', time='22:30')
    for k in ('kickoffUtc', 'odds2', 'oddsMarket', 'floorOdds'):
        p.pop(k)
    env['write_top'](DAY, [p])
    assert TL.pick_kickoff(p, DAY) == datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc)
    assert TL.due(datetime(2026, 10, 25, 21, 30, tzinfo=timezone.utc)) == 1


def test_top_file_withdrawn_pick_is_skipped(env):
    env['write_top'](DAY, [_pick(withdrawn=True)])
    assert TL.run(at(60)) == {}
    assert env['calls'] == []


# ------------------------------------------------------------ closing odds

def test_closing_overwritten_in_last_25_min_and_clv(env):
    env['write_top'](DAY, [_pick(match='Hibernian vs Celtic', pick='Celtic')])
    env['prices'] = [_prices(quote=2.15), _prices(quote=2.05), _prices(quote=1.98)]
    TL.run(at(60))
    assert 'closingOdds' not in _live(env)['football|Hibernian vs Celtic']
    TL.run(at(24))
    TL.run(at(4))
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec['closingOdds'] == 1.98 and rec['closingApprox'] is False
    assert rec['closingSource'] == 'pinnacle' and rec['closingMinsToKick'] == 4
    assert rec['clvPct'] == round((2.2 / 1.98 - 1) * 100, 1) == 11.1
    assert [c['minsToKick'] for c in rec['checks']] == [60, 24, 4]
    TL.run(KO + timedelta(minutes=3))                  # kickoff passed: closing kept
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec['closingOdds'] == 1.98 and rec['finalCheckMissed'] is False


def test_closing_approx_from_latest_check_within_60_min(env):
    env['write_top'](DAY, [_pick(match='Hibernian vs Celtic', pick='Celtic')])
    env['prices'] = [_prices(quote=2.3), _prices(quote=2.1)]
    TL.run(at(85))
    TL.run(at(45))
    TL.run(KO + timedelta(minutes=2))
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec['closingOdds'] == 2.1 and rec['closingApprox'] is True
    assert rec['closingMinsToKick'] == 45
    assert rec['clvPct'] == 4.8


def test_closing_null_when_latest_check_older_than_60_min(env):
    env['write_top'](DAY, [_pick(match='Hibernian vs Celtic', pick='Celtic')])
    env['prices'] = [_prices(quote=2.1)]
    TL.run(at(80))
    TL.run(KO + timedelta(minutes=1))
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec['closingOdds'] is None and rec['clvPct'] is None


def test_missed_pick_is_logged_and_recorded(env, capsys):
    env['write_top'](DAY, [_pick(match='Hibernian vs Celtic', pick='Celtic')])
    TL.run(KO + timedelta(minutes=2))
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec == {'checks': [], 'closingOdds': None, 'clvPct': None, 'finalCheckMissed': True}
    assert 'MISS final check' in capsys.readouterr().out
    assert TL.run(KO + timedelta(minutes=12)) == {}    # finalized once


def test_market_mismatch_gives_null_clv(env):
    env['write_top'](DAY, [_pick(match='Hibernian vs Celtic', pick='Celtic')])   # 3way pick
    env['prices'] = [_prices(quote=1.6, market='2way')]
    TL.run(at(10))
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec['closingOdds'] == 1.6 and rec['closingMarket'] == '2way'
    assert rec['clvPct'] is None


def test_two_way_and_two_way_equiv_compare():
    assert TL.clv_pct(1.40, '2way_equiv', 1.35, '2way') == 3.7
    assert TL.clv_pct(2.0, '3way', 1.9, '2way_equiv') is None
    assert TL.clv_pct(1.8, None, 1.7, '2way') is None   # unknown publication market


def test_old_hockey_pick_without_market_has_no_clv():
    p = {'sport': 'hockey', 'odds': 1.78}
    assert TL.pick_market(p) is None and TL.pub_odds2(p, None) is None
    t = {'sport': 'tennis', 'odds': 1.5}
    assert TL.pick_market(t) == '2way' and TL.pub_odds2(t, '2way') == 1.5


# ------------------------------------------------------------ withdrawals

def test_withdraw_availability_with_picked_side_players(env):
    env['write_top'](DAY, [_pick()])                   # Udinese vs Milan, record side=away
    TL.run(at(45))                                     # now 21:00, checkedAt 20:49
    rec = _live(env)['football|Udinese vs Milan']
    assert rec['withdrawn'] is True and rec['withdrawKind'] == 'availability'
    assert rec['withdrawReason'] == ('Key absence: A. Rabiot (out), A. Saelemaekers (out), '
                                     'D. Moreira (out)')
    c = rec['checks'][0]
    assert c['avail'] == 'block' and c['availAgeMin'] == 11


def test_withdraw_availability_fallback_reason_board_net_stars(env):
    env['write_top'](DAY, [_pick(match='Derby U23s vs Norwich U23s', pick='Derby U23s')])
    TL.run(at(30))
    rec = _live(env)['football|Derby U23s vs Norwich U23s']
    assert rec['withdrawKind'] == 'availability'
    assert rec['withdrawReason'] == 'Key absence (board: drop, netStars 2)'


def test_availability_matched_by_folded_names(env):
    env['write_top'](DAY, [_pick(match='UDINESE vs Milan.', pick='Milan.')])
    TL.run(at(45))
    assert _live(env)['football|UDINESE vs Milan.']['withdrawKind'] == 'availability'


def test_unknown_record_does_not_withdraw(env):
    env['write_top'](DAY, [_pick(match='D. Dietrich vs C. Smith', pick='D. Dietrich', sport='tennis',
                                 oddsMarket='2way')])
    TL.run(at(45))
    rec = _live(env)['tennis|D. Dietrich vs C. Smith']
    assert not rec.get('withdrawn') and rec['checks'][0]['avail'] == 'unknown'


def test_stale_record_does_not_withdraw(env):
    late = KO + timedelta(hours=3)                     # checkedAt 20:49 -> > 180 min old
    env['write_top'](DAY, [_pick(kickoffUtc=TL._iso(late + timedelta(minutes=40)))])
    TL.run(late)
    rec = _live(env)['football|Udinese vs Milan']
    assert not rec.get('withdrawn')
    assert rec['checks'][0]['avail'] == 'stale' and rec['checks'][0]['availAgeMin'] > 180


def test_missing_record_and_ok_record(env):
    env['write_top'](DAY, [_pick(match='X vs Y', pick='X'),
                           _pick(match='Hibernian vs Celtic', pick='Celtic')])
    TL.run(at(45))
    live = _live(env)
    assert live['football|X vs Y']['checks'][0]['avail'] == 'unknown'
    assert live['football|X vs Y']['checks'][0]['availAgeMin'] is None
    assert live['football|Hibernian vs Celtic']['checks'][0]['avail'] == 'ok'
    assert not any(r.get('withdrawn') for r in live.values())


def test_no_availability_check_outside_20_90(env):
    env['write_top'](DAY, [_pick()])
    TL.run(at(15))
    rec = _live(env)['football|Udinese vs Milan']
    assert 'avail' not in rec['checks'][0] and not rec.get('withdrawn')


def test_malformed_availability_file_is_unknown(env):
    (env['dir'] / f'availability_{DAY}.json').write_text('{broken', encoding='utf-8')
    env['write_top'](DAY, [_pick()])
    TL.run(at(45))
    rec = _live(env)['football|Udinese vs Milan']
    assert rec['checks'][0]['avail'] == 'unknown' and not rec.get('withdrawn')


def test_price_withdrawal_keeps_closing_and_clv(env):
    env['write_top'](DAY, [_pick(match='Hibernian vs Celtic', pick='Celtic', floorOdds=2.1)])
    env['prices'] = [_prices(best=2.05, quote=2.0), _prices(best=2.3, quote=1.9)]
    TL.run(at(50))
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec['withdrawKind'] == 'price'
    assert rec['withdrawReason'] == 'Price fell to 2.05, below the profitable minimum 2.10'
    TL.run(at(10))                                     # still tracked after withdrawal
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec['closingOdds'] == 1.9 and rec['clvPct'] == 15.8
    assert rec['withdrawn'] is True and len(rec['checks']) == 2


def test_no_price_withdrawal_when_no_source_answered(env):
    env['write_top'](DAY, [_pick(match='Hibernian vs Celtic', pick='Celtic', floorOdds=2.1)])
    env['prices'] = [_prices(best=None, quote=None)]
    TL.run(at(50))
    rec = _live(env)['football|Hibernian vs Celtic']
    assert not rec.get('withdrawn') and rec['checks'][0]['best'] is None


def test_withdrawal_is_sticky(env):
    env['write_top'](DAY, [_pick(match='Hibernian vs Celtic', pick='Celtic', floorOdds=2.1)])
    env['prices'] = [_prices(best=2.0), _prices(best=2.4), _prices(best=2.4)]
    TL.run(at(70))
    first = _live(env)['football|Hibernian vs Celtic']
    assert first['withdrawn'] is True
    TL.run(at(40))
    TL.run(at(22))
    rec = _live(env)['football|Hibernian vs Celtic']
    assert rec['withdrawn'] is True and rec['withdrawnAt'] == first['withdrawnAt']
    assert rec['withdrawKind'] == 'price' and len(rec['checks']) == 3


def test_top_picks_respects_live_withdrawal(env, monkeypatch):
    from tools import top_picks as tp
    env['write_top'](DAY, [_pick()])
    TL.run(at(45))
    root = env['dir'] / 'root'
    os.makedirs(root / 'results')
    shutil.copy(env['dir'] / f'top_live_{DAY}.json', root / 'results' / f'top_live_{DAY}.json')
    monkeypatch.setattr(tp, 'ROOT', str(root))
    assert tp._live_withdrawn(DAY) == {'football|Udinese vs Milan'}


def test_dry_run_writes_nothing(env, capsys):
    env['write_top'](DAY, [_pick()])
    out = TL.run(at(45), dry_run=True)
    assert DAY in out and not (env['dir'] / f'top_live_{DAY}.json').exists()
    assert 'dry run' in capsys.readouterr().out


def test_withdraw_reason_doubtful_and_limit():
    rec = {'side': 'home', 'board': 'downgrade', 'home': [
        {'name': 'A', 'importance': 'other', 'status': 'out'},
        {'name': 'B', 'importance': 'star', 'status': 'doubtful'},
        {'name': 'C', 'importance': 'key', 'status': 'probable'}]}
    assert TL.withdraw_reason(rec) == 'Key absence: B (doubtful)'
    assert TL.withdraw_reason({'side': 'away'}) == 'Key absence (board: ?, netStars 0)'


def test_fetch_prices_uses_pinnacle_then_oddssafari_with_own_market(monkeypatch):
    calls = []
    monkeypatch.setattr(TL.best_price, 'best_price',
                        lambda p, d: {'bestOdds': 1.45, 'bestOddsSource': 'livesport', 'booksCount': 1})
    monkeypatch.setattr(TL.best_price, '_DEAD', set())

    def pin(h, a, s, d):
        calls.append('pinnacle')
        return None

    def osf(h, a, s, d):
        calls.append('oddssafari')
        return {'home': 1.9, 'draw': 4.0, 'away': 3.6}
    monkeypatch.setattr(TL.best_price, 'SOURCES', {'pinnacle': pin, 'oddssafari': osf})
    monkeypatch.setattr(TL.best_price, '_MODULES', {})
    pr = TL.fetch_prices({'sport': 'hockey', 'match': 'H vs A', 'pick': 'H'}, DAY)
    assert calls == ['pinnacle', 'oddssafari']
    assert pr['best'] == 1.45 and pr['quoteSource'] == 'oddssafari'
    assert pr['quoteMarket'] == '2way_equiv' and 1.4 < pr['quote'] < 1.9
