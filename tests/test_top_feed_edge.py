"""top_feed edge additions (design K5 curve, K8): live merge, withdrawn
exclusion and paywall, CLV summary, bankroll, 2-way record, raw-GitHub freshness."""
import json
import logging
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import top_feed as t  # noqa: E402

DAY = '2026-10-21'
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def pick(match, team, odds=2.0, sport='tennis', grade='B', time='19:00', **kw):
    return dict({'match': match, 'pick': team, 'odds': odds, 'sport': sport,
                 'time': time, 'grade': grade, 'league': 'L'}, **kw)


def settled(*rows):
    """rows: (sport, home, away, winner) -> forebet_settled.json content."""
    return {f'{DAY}|{s}|{h}|{a}': {'status': 'settled', 'winner': w, 'score': '2-1'}
            for s, h, a, w in rows}


def setup(tmp_path, picks, live=None, settle=None, extra=None):
    res = tmp_path / 'results'
    res.mkdir()
    (res / f'top_{DAY}.json').write_text(json.dumps(picks), encoding='utf-8')
    if live is not None:
        (res / f'top_live_{DAY}.json').write_text(json.dumps(live), encoding='utf-8')
    if settle is not None:
        (res / 'forebet_settled.json').write_text(json.dumps(settle), encoding='utf-8')
    for name, content in (extra or {}).items():
        (res / name).write_text(json.dumps(content), encoding='utf-8')
    sp = tmp_path / 'store.json'
    sp.write_text('{}', encoding='utf-8')
    t._store_cache.update(mtime=None, index={}, path=None)
    return str(res), str(sp)


def load(res, sp, sub=False, now=NOW, **kw):
    return t.load_top(res, sp, is_subscriber=sub, now=now, **kw)


WITHDRAWN_LIVE = {'withdrawn': True, 'withdrawKind': 'availability',
                  'withdrawReason': 'Key absence: A. Star (out)',
                  'withdrawnAt': '2026-10-21T17:55:00Z'}


# --- withdrawn: excluded from record, counted apart, paywalled until kick-off ---
def test_live_withdrawal_is_excluded_from_record_and_bankroll(tmp_path):
    res, sp = setup(tmp_path,
                    [pick('A vs B', 'A', 2.0), pick('C vs D', 'C', 3.0)],
                    live={'tennis|C vs D': WITHDRAWN_LIVE},
                    settle=settled(('tennis', 'A', 'B', 'home'), ('tennis', 'C', 'D', 'home')))
    d = load(res, sp, sub=True)
    s = d['summary']
    assert (s['picks'], s['settled'], s['won']) == (1, 1, 1)
    assert s['roi'] == 100.0
    assert s['withdrawn'] == {'n': 1, 'availability': 1, 'price': 0}
    assert len(s['bankroll']['points']) == 1
    p = {x['match']: x for x in d['days'][0]['picks']}['C vs D']
    assert p['status'] == 'withdrawn' and p['result']['status'] == 'withdrawn'
    assert p['withdrawReason'] == 'Key absence: A. Star (out)'
    assert p['withdrawKind'] == 'availability'


def test_withdrawn_selection_is_locked_for_visitors_until_kickoff(tmp_path):
    res, sp = setup(tmp_path, [pick('C vs D', 'C', 3.0, kickoffUtc='2026-10-21T19:00:00Z')],
                    live={'tennis|C vs D': dict(WITHDRAWN_LIVE, closingOdds=2.8,
                                                closingSource='pinnacle', clvPct=7.1)})
    before = load(res, sp)['days'][0]
    assert before['locked'] == 0 and len(before['picks']) == 1
    p = before['picks'][0]
    assert p['status'] == 'withdrawn' and p['withdrawReason'] and p['selectionLocked']
    for k in ('pick', 'odds', 'odds2', 'bestOdds', 'closingOdds', 'clvPct', 'stakePct'):
        assert k not in p, k
    after = load(res, sp, now=datetime(2026, 10, 21, 19, 1, tzinfo=timezone.utc))
    p = after['days'][0]['picks'][0]
    assert p['pick'] == 'C' and p['odds'] == 3.0 and 'selectionLocked' not in p
    assert load(res, sp, sub=True)['days'][0]['picks'][0]['pick'] == 'C'


def test_withdrawn_in_top_file_still_counts_as_withdrawn(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A', withdrawn=True, withdrawReason='Key absences: X')],
                    settle=settled(('tennis', 'A', 'B', 'home')))
    s = load(res, sp, sub=True)['summary']
    assert s['settled'] == 0 and s['withdrawn']['n'] == 1 and s['withdrawn']['availability'] == 1


def test_pending_picks_stay_hidden_for_visitors(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A'), pick('C vs D', 'C')],
                    live={'tennis|C vs D': {'bestOdds': 2.1, 'clvPct': 3.0,
                                            'closingSource': 'pinnacle'}},
                    settle=settled(('tennis', 'A', 'B', 'home')))
    day = load(res, sp)['days'][0]
    assert [p['match'] for p in day['picks']] == ['A vs B'] and day['locked'] == 1


# --- CLV ---
def test_clv_headline_is_pinnacle_close_only(tmp_path):
    picks = [pick(f'H{i} vs A{i}', f'H{i}') for i in range(5)]
    live = {
        'tennis|H0 vs A0': {'closingOdds': 1.9, 'closingSource': 'pinnacle', 'clvPct': 5.0},
        'tennis|H1 vs A1': {'closingOdds': 2.1, 'closingSource': 'pinnacle', 'clvPct': -3.0,
                            'closingApprox': True},
        'tennis|H2 vs A2': {'closingOdds': 1.8, 'closingSource': 'oddssafari', 'clvPct': 10.0},
        'tennis|H3 vs A3': {'closingOdds': None, 'clvPct': None},
        'tennis|H4 vs A4': dict(WITHDRAWN_LIVE, closingOdds=1.7, closingSource='pinnacle',
                                clvPct=8.0, withdrawKind='price'),
    }
    res, sp = setup(tmp_path, picks, live=live)
    c = load(res, sp)['summary']['clv']
    assert c['n'] == 3 and c['avgPct'] == 3.3 and c['beatClosePct'] == 66.7
    assert c['nOddsSafari'] == 1 and c['avgPctOddsSafari'] == 10.0
    assert c['nApprox'] == 1 and c['since'] == DAY


def test_clv_empty_is_null_not_zero(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A')])
    c = load(res, sp)['summary']['clv']
    assert c['n'] == 0 and c['avgPct'] is None and c['beatClosePct'] is None


def test_per_pick_live_fields_for_subscribers(tmp_path):
    live = {'tennis|A vs B': {
        'checks': [{'at': '2026-10-21T18:00:00Z', 'minsToKick': 60, 'avail': 'ok',
                    'availAgeMin': 30},
                   {'at': '2026-10-21T18:45:00Z', 'minsToKick': 15}],
        'bestOdds': 2.15, 'bestOddsSource': 'pinnacle', 'bestOddsAt': '2026-10-21T18:45:00Z',
        'booksCount': 13, 'closingOdds': 1.95, 'closingSource': 'pinnacle',
        'closingAt': '2026-10-21T18:45:00Z', 'closingMarket': '2way', 'clvPct': 2.6}}
    res, sp = setup(tmp_path, [pick('A vs B', 'A', 2.0, bestOdds=2.05, bestOddsSource='oddssafari')],
                    live=live)
    p = load(res, sp, sub=True)['days'][0]['picks'][0]
    assert (p['bestOdds'], p['bestOddsSource'], p['booksCount']) == (2.15, 'pinnacle', 13)
    assert (p['closingOdds'], p['clvPct'], p['closingApprox']) == (1.95, 2.6, False)
    assert (p['availStatus'], p['availMinsToKick'], p['availAgeMin']) == ('ok', 60, 30)
    assert p['oddsMarket'] == '2way' and p['odds2'] == 2.0


# --- stake, kickoff, bankroll ---
def test_stake_from_staking_when_missing_and_kickoff_fallback(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A', 2.5, grade='A', pCal=0.6),
                               pick('C vs D', 'C', 2.0, stakePct=1.7,
                                    kickoffUtc='2026-10-21T18:00:00Z', kickoffApprox=False)])
    ps = {p['match']: p for p in load(res, sp, sub=True)['days'][0]['picks']}
    assert ps['A vs B']['stakePct'] == 2.0          # quarter Kelly 0.25*0.5/1.5 -> 8.3% -> clamp 2
    assert ps['A vs B']['kickoffUtc'] == '2026-10-21T19:00:00Z' and ps['A vs B']['kickoffApprox']
    assert ps['C vs D']['stakePct'] == 1.7 and ps['C vs D']['kickoffApprox'] is False


def test_bankroll_compounds_in_kickoff_order_with_flat_curve(tmp_path):
    picks = [pick('A vs B', 'A', 2.0, time='21:00', stakePct=2.0),
             pick('C vs D', 'C', 3.0, time='15:00', stakePct=1.0),
             pick('E vs F', 'E', 2.0, time='18:00'),
             pick('G vs H', 'G', 2.0, time='20:00')]               # pending
    res, sp = setup(tmp_path, picks, settle=settled(
        ('tennis', 'A', 'B', 'home'), ('tennis', 'C', 'D', 'away'), ('tennis', 'E', 'F', 'home')))
    b = load(res, sp, sub=True)['summary']['bankroll']
    assert b['start'] == 100.0
    # 15:00 C lost 1% -> 99; 18:00 E won 1% (default) at 2.0 -> 99.99; 21:00 A won 2% -> 101.99
    assert [p['value'] for p in b['points']] == [99.0, 99.99, 101.99]
    assert [p['flat'] for p in b['points']] == [99.0, 100.0, 101.0]
    assert b['points'][0]['t'] == '2026-10-21T15:00:00Z'
    assert b['final'] == 101.99 and b['maxDrawdownPct'] == 1.0


def test_bankroll_empty(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A')])
    b = load(res, sp)['summary']['bankroll']
    assert b == {'start': 100.0, 'points': [], 'final': 100.0, 'maxDrawdownPct': 0.0}


# --- corrected 2-way record ---
def test_old_hockey_pick_is_repriced_two_way_and_as_stored_kept(tmp_path):
    forebet = {'matches': [{'homeTeam': 'Kladno', 'awayTeam': 'Pardubice',
                            'odds': {'home': 3.2, 'draw': 4.2, 'away': 2.0}}]}
    res, sp = setup(tmp_path, [pick('Kladno vs Pardubice', 'Pardubice', 2.0, sport='hockey')],
                    settle=settled(('hockey', 'Kladno', 'Pardubice', 'away')),
                    extra={f'matches_{DAY}_hockey_forebet.json': forebet})
    d = load(res, sp, sub=True)
    p = d['days'][0]['picks'][0]
    o2, _ = t.pricing.side_price(forebet['matches'][0]['odds'], 'hockey', 'away')
    assert p['oddsMarket'] == '2way_equiv' and p['odds2'] == round(2.0 * o2 / 2.0, 3)
    assert p['odds2'] < 2.0
    s = d['summary']
    assert s['roiAsStored'] == 100.0 and s['roi'] == round((p['odds2'] - 1) * 100, 1)
    assert s['pricedAsStored'] == 0


def test_hockey_pick_without_source_quote_is_priced_as_stored(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A', 2.0, sport='hockey')],
                    settle=settled(('hockey', 'A', 'B', 'home')))
    s = load(res, sp, sub=True)['summary']
    assert s['roi'] == s['roiAsStored'] == 100.0 and s['pricedAsStored'] == 1


def test_stored_odds2_is_used_for_new_picks(tmp_path):
    res, sp = setup(tmp_path, [pick('A vs B', 'A', 1.8, sport='hockey', odds2=1.4,
                                    oddsMarket='2way_equiv')],
                    settle=settled(('hockey', 'A', 'B', 'home')))
    s = load(res, sp, sub=True)['summary']
    assert s['roi'] == 40.0 and s['roiAsStored'] == 80.0


# --- raw GitHub freshness ---
@pytest.fixture
def remote(monkeypatch):
    calls = []
    files = {}

    def fake(url, timeout):
        calls.append((url, timeout))
        name = url.rsplit('/', 1)[1]
        if name not in files:
            raise OSError('HTTP Error 404: Not Found')
        return files[name]

    t._remote_cache.clear()
    t._remote_warned['at'] = 0.0
    monkeypatch.setattr(t, '_http_get_json', fake)
    return calls, files


def test_remote_copy_replaces_slug_for_recent_days(tmp_path, remote):
    calls, files = remote
    res, sp = setup(tmp_path, [pick('A vs B', 'A')])
    files[f'top_{DAY}.json'] = [pick('A vs B', 'A'), pick('C vs D', 'C')]
    files[f'top_live_{DAY}.json'] = {'tennis|C vs D': WITHDRAWN_LIVE}
    files['top_2026-10-20.json'] = [pick('E vs F', 'E')]      # not in slug yet
    d = load(res, sp, sub=True, remote=True)
    assert [x['date'] for x in d['days']] == [DAY, '2026-10-20']
    assert len(d['days'][0]['picks']) == 2
    assert d['summary']['withdrawn']['n'] == 1
    assert all(c[1] == t.REMOTE_TIMEOUT_S and c[0].startswith(t.RAW_BASE) for c in calls)
    n = len(calls)
    load(res, sp, sub=True, remote=True)
    assert len(calls) == n, 'TTL cache: no refetch within REMOTE_TTL_S'


def test_remote_failure_falls_back_to_slug_with_one_warning(tmp_path, remote, caplog):
    calls, _files = remote
    res, sp = setup(tmp_path, [pick('A vs B', 'A')],
                    live={'tennis|A vs B': {'clvPct': 4.0, 'closingSource': 'pinnacle'}})
    with caplog.at_level(logging.WARNING, logger='top_feed'):
        d = load(res, sp, sub=True, remote=True)
    assert len(d['days'][0]['picks']) == 1 and d['summary']['clv']['n'] == 1
    assert len(calls) == 4                                   # 2 days x (top, live)
    assert sum('raw GitHub fetch' in r.message for r in caplog.records) == 1


def test_remote_is_off_for_non_default_dirs(tmp_path, remote):
    calls, _files = remote
    res, sp = setup(tmp_path, [pick('A vs B', 'A')])
    load(res, sp)
    assert calls == []
