"""tools/top_picks.py consuming the rules file (design K1/K4/K5)."""
import json

import pytest

from tools import top_picks as tp
from tools import top_rules as TR

DAY = '2026-10-26'


def _rules(segments, enforce=True):
    return {'version': 1, 'generatedAt': '2026-10-26T03:00:00Z', 'gitSha': 'x',
            'tuning': {'start': '2026-09-12', 'end': '2026-10-10', 'halfSplit': '2026-09-26', 'n': 1},
            'holdout': {'start': '2026-10-11', 'end': '2026-10-25', 'n': 1},
            'haircut': 0.05, 'minN': 50, 'bands': TR.BANDS, 'segments': segments,
            'enforcement': {'enforce': enforce},
            'defaults': {'decision': 'exclude', 'stakePct': 1.0}}


RULES = _rules({
    'football': {'level': 'sport', 'n': 300, 'decision': 'exclude'},
    'football|2.0-2.5': {'level': 'sport×band', 'n': 120, 'decision': 'inherit'},
    'football|2.0-2.5|home': {'level': 'sport×band×side', 'n': 80, 'decision': 'allow',
                              'pCal': 0.6, 'floorOdds': 2.0},
    'hockey': {'level': 'sport', 'n': 200, 'decision': 'exclude'},
})


def _match(**kw):
    m = {'homeTeam': 'Home FC', 'awayTeam': 'Away FC', 'time': '18:00', 'league': 'Premier League',
         'country': 'England', 'qualifies': True, 'predictionGrade': 'A',
         'scoring': {'pick': '1', 'prob': 70},
         'forebet': {'prediction': '1', 'homeProb': 70, 'awayProb': 30},
         'odds': {'home': 2.1, 'away': 3.0},
         'form': {'home': list('WWWWD'), 'away': list('LLLDW'),
                  'homeAtHome': list('WWWDW'), 'awayAtAway': list('LLDLL')},
         'h2h': {'total': 0}, 'sofascore': {'found': False}}
    m.update(kw)
    return m


@pytest.fixture(autouse=True)
def _rules_and_no_network(monkeypatch):
    assert TR.validate(RULES, now=TR._now().replace(year=2026, month=10, day=27)) is None
    monkeypatch.setattr(tp, 'RULES', RULES)
    monkeypatch.setattr(tp.best_price, 'SOURCES', {})


def test_allowed_segment_passes_with_fields():
    r = tp.evaluate(_match(), 'football', DAY)
    assert r is not None
    assert r['segment'] == 'football|2.0-2.5|home'
    assert r['odds2'] == 2.1 and r['oddsMarket'] == '3way'
    assert r['floorOdds'] == 2.0 and r['pCal'] == 0.6
    assert r['stakePct'] == 2.0                    # A, edge 0.26 -> quarter Kelly clamped
    assert r['kickoffUtc'] == '2026-10-26T15:00:00Z' and r['kickoffApprox'] is True


def test_excluded_segment_returns_none():
    # Same match priced in hockey: sport-level exclude, no allowed band below it.
    hk = _match(odds={'home': 2.1, 'away': 3.0})
    assert tp.evaluate(hk, 'hockey', DAY) is None
    # Football, band 2.0-2.5 but away side: band inherits, no grade segment -> sport exclude.
    away = _match(scoring={'pick': '2', 'prob': 70},
                  forebet={'prediction': '2', 'homeProb': 30, 'awayProb': 70},
                  odds={'home': 3.0, 'away': 2.1},
                  form={'home': list('LLLDW'), 'away': list('WWWWD'),
                        'homeAtHome': list('LLDLL'), 'awayAtAway': list('WWWDW')})
    assert tp.evaluate(away, 'football', DAY, apply_rules=False) is not None
    assert tp.evaluate(away, 'football', DAY) is None


def test_grade_exclusion_applies(monkeypatch):
    seg = dict(RULES['segments'])
    seg['football|grade:A'] = {'level': 'sport×grade', 'n': 90, 'decision': 'exclude'}
    monkeypatch.setattr(tp, 'RULES', _rules(seg))
    assert tp.evaluate(_match(), 'football', DAY) is None


def test_enforced_mode_records_learned_decision():
    r = tp.evaluate(_match(), 'football', DAY)
    assert r['rulesMode'] == 'enforced' and r['learnedDecision'] == 'allow'
    assert r['learnedSegment'] == 'football|2.0-2.5|home'


def test_shadow_mode_safe_gate_decides_learned_recorded(monkeypatch):
    monkeypatch.setattr(tp, 'RULES', _rules(RULES['segments'], enforce=False))
    # learned excludes hockey, safe gate passes it -> published, exclusion recorded
    hk = tp.evaluate(_match(), 'hockey', DAY)
    assert hk is not None and hk['rulesMode'] == 'shadow' and hk['segment'] == 'safe-gate'
    assert hk['learnedDecision'] == 'exclude' and hk['learnedSegment'] == 'hockey'
    assert hk['floorOdds'] == 1.0 and hk['pCal'] is None and hk['stakePct'] == 1.0
    # learned allows -> its floor and pCal are kept
    fb = tp.evaluate(_match(), 'football', DAY)
    assert fb['segment'] == 'safe-gate' and fb['learnedDecision'] == 'allow'
    assert fb['floorOdds'] == 2.0 and fb['pCal'] == 0.6 and fb['stakePct'] == 2.0
    # safe gate: tennis below 1.80 stays out
    ten = dict(_match(odds={'home': 1.6, 'away': 2.4}), league='ATP Vienna')
    assert tp.evaluate(ten, 'tennis', DAY) is None


def test_missing_enforcement_block_means_shadow(monkeypatch):
    rules = _rules(RULES['segments'])
    del rules['enforcement']
    monkeypatch.setattr(tp, 'RULES', rules)
    assert tp.evaluate(_match(), 'hockey', DAY)['rulesMode'] == 'shadow'


def test_apply_rules_false_keeps_old_shape():
    r = tp.evaluate(_match(), 'hockey', apply_rules=False)
    assert r is not None and 'segment' not in r and 'odds2' not in r


def test_fallback_when_rules_file_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(TR, '_WARNED', set())
    monkeypatch.setattr(TR, '_CACHE', {})
    rules = TR.load(str(tmp_path / 'top_rules.json'))           # file missing
    assert rules.get('fallback') is True
    monkeypatch.setattr(tp, 'RULES', rules)
    r = tp.evaluate(_match(), 'football', DAY)
    assert r['segment'] == 'fallback' and r['floorOdds'] == 1.0 and r['rulesMode'] == 'fallback'
    assert r['pCal'] is None and r['stakePct'] == 1.0
    # fallback safe gate: tennis below 1.80 excluded, above passes
    ten = dict(_match(odds={'home': 1.6, 'away': 2.4}), league='ATP Vienna')
    assert tp.evaluate(ten, 'tennis', DAY) is None
    ten2 = dict(_match(odds={'home': 1.85, 'away': 2.0}), league='ATP Vienna')
    assert tp.evaluate(ten2, 'tennis', DAY)['segment'] == 'fallback'


def test_hockey_priced_two_way(monkeypatch):
    seg = dict(RULES['segments'])
    seg['hockey'] = {'level': 'sport', 'n': 200, 'decision': 'allow', 'pCal': 0.6, 'floorOdds': 1.3}
    monkeypatch.setattr(tp, 'RULES', _rules(seg))
    r = tp.evaluate(_match(odds={'home': 2.3, 'draw': 4.2, 'away': 2.9}), 'hockey', DAY)
    assert r['odds'] == 2.3 and r['oddsMarket'] == '2way_equiv' and r['odds2'] < 1.9


# ── publish gate (floor) + live withdrawals ─────────────────────────────────

def _pick(**kw):
    r = tp.evaluate(_match(), 'football', DAY)
    r.update(kw)
    return r


def _stub_best(monkeypatch, odds, kickoff=None):
    monkeypatch.setattr(tp.best_price, 'best_price', lambda pick, day=None: {
        'bestOdds': odds, 'bestOddsSource': 'pinnacle' if odds else None,
        'bestOddsAt': '2026-10-26T10:00:00Z' if odds else None,
        'booksCount': 1 if odds else 0, 'quotes': {}, 'kickoff': kickoff})


def test_floor_gate_blocks_new_pick_below_floor(monkeypatch, capsys):
    _stub_best(monkeypatch, 1.95)                       # floorOdds 2.0
    assert tp.publish_gate([_pick()], DAY) == []
    assert 'below floor' in capsys.readouterr().out


def test_floor_gate_uses_odds2_when_no_source(monkeypatch):
    _stub_best(monkeypatch, None)
    out = tp.publish_gate([_pick()], DAY)
    assert len(out) == 1 and out[0]['bestOdds'] is None and out[0]['booksCount'] == 0
    assert out[0]['publishedAt'].endswith('Z')
    assert tp.publish_gate([_pick(odds2=1.99)], DAY) == []


def test_floor_gate_passes_and_sets_fields(monkeypatch):
    _stub_best(monkeypatch, 2.2, kickoff='2026-10-26 17:30:00')
    out = tp.publish_gate([_pick()], DAY)
    assert len(out) == 1
    r = out[0]
    assert r['bestOdds'] == 2.2 and r['bestOddsSource'] == 'pinnacle' and r['booksCount'] == 1
    assert r['kickoffUtc'] == '2026-10-26T17:30:00Z' and r['kickoffApprox'] is False
    assert r['stakePct'] == 2.0 and r['odds'] == 2.1   # stored odds not mutated


def test_withdrawn_in_live_not_re_added(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tp, 'ROOT', str(tmp_path))
    (tmp_path / 'results').mkdir()
    _stub_best(monkeypatch, None)
    a = _pick()
    b = dict(_pick(), match='Other FC vs Away FC')
    live = {tp._key(a): {'withdrawn': True, 'withdrawKind': 'availability'},
            tp._key(b): {'withdrawn': False, 'checks': []}}
    (tmp_path / 'results' / f'top_live_{DAY}.json').write_text(json.dumps(live), encoding='utf-8')
    out = tp.select_new([a, b], [], DAY)
    assert [r['match'] for r in out] == ['Other FC vs Away FC']
    assert 'not re-added (withdrawn live)' in capsys.readouterr().out


def test_live_file_missing_or_bad_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, 'ROOT', str(tmp_path))
    (tmp_path / 'results').mkdir()
    _stub_best(monkeypatch, None)
    assert len(tp.select_new([_pick()], [], DAY)) == 1
    (tmp_path / 'results' / f'top_live_{DAY}.json').write_text('{bad', encoding='utf-8')
    assert len(tp.select_new([_pick()], [], DAY)) == 1
    # already published picks are not new
    assert tp.select_new([_pick()], [_pick()], DAY) == []


# ── enforcement switch + forward check of the 1.80 cut (tools/top_rules) ───

def _hrow(day, sport='football', odds2=2.1, won=True, side='home', grade='A', tier='T1', top=True):
    return {'day': day, 'time': '18:00', 'sport': sport, 'src': 'forebet', 'grade': grade,
            'side': side, 'odds': odds2, 'odds2': odds2, 'market': '3way', 'band': TR.band(odds2),
            'tier': tier, 'struct': True, 'top': top, 'won': won, 'draw': False}


def _days(start, n):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def test_enforcement_needs_three_per_day_and_positive_roi():
    hold_days = _days('2026-10-11', 16)
    # 3 allowed picks/day (football 2.0-2.5 home), 2 of 3 won at 2.1 -> ROI -5% > 0
    rows = [_hrow(d, won=(i % 3 != 2)) for d in hold_days for i in range(3)]
    e = TR.enforcement(RULES, rows, '2026-10-10', '2026-10-26')
    assert e['enforce'] is True and e['holdoutTopReplay']['perDay'] == 3.0
    # 2 picks/day: profitable but too few
    few = [r for i, r in enumerate(rows) if i % 3 != 2]
    assert TR.enforcement(RULES, few, '2026-10-10', '2026-10-26')['enforce'] is False
    # 3/day but losing
    lose = [dict(r, won=(i % 3 == 0)) for i, r in enumerate(rows)]
    e = TR.enforcement(RULES, lose, '2026-10-10', '2026-10-26')
    assert e['enforce'] is False and e['holdoutTopReplay']['roi5'] < 0
    # rows of excluded segments do not count
    hk = [dict(r, sport='hockey') for r in rows]
    assert TR.enforcement(RULES, hk, '2026-10-10', '2026-10-26')['holdoutTopReplay']['n'] == 0


def test_validate_enforcement_block():
    now = TR._now().replace(year=2026, month=10, day=27)
    assert TR.validate(dict(RULES, enforcement={'enforce': 'yes'}), now=now) == 'bad enforcement block'
    no_block = dict(RULES)
    del no_block['enforcement']
    assert TR.validate(no_block, now=now) is None and not TR.enforced(no_block)
    assert not TR.enforced(TR.fallback('x'))


def test_safe_gate_forward_status():
    launch = TR.SAFE_GATE_LAUNCH
    days = _days(launch, TR.FORWARD_DAYS)
    rows = [_hrow(d, sport='tennis', odds2=1.5, won=False) for d in days[:5]]
    rows += [_hrow(d, sport='tennis', odds2=1.9, won=True) for d in days[:5]]
    f = TR.safe_gate_forward(rows)
    assert f['status'].startswith('pending (5/14') and f['cut']['n'] == 5 and f['kept']['n'] == 5
    full = [_hrow(d, sport='basketball', odds2=1.6, won=False) for d in days]
    assert TR.safe_gate_forward(full)['status'].startswith('confirmed')
    win = [dict(r, won=True) for r in full]
    assert TR.safe_gate_forward(win)['status'].startswith('NOT confirmed')
    # rows before launch or not in TOP replay are ignored
    old = [_hrow('2026-10-20', sport='tennis', odds2=1.5), _hrow(days[0], top=False)]
    assert TR.safe_gate_forward(old)['daysCovered'] == 0


def test_published_pick_withdrawn_only_before_kickoff():
    """Availability block on a published pick: withdrawn before kick-off, kept
    (counted in the record) once the match has started."""
    from datetime import datetime, timezone
    block = {'top_block': True}
    early = {'sport': 'football', 'match': 'A vs B', 'kickoffUtc': '2026-10-26T19:00:00Z'}
    late = {'sport': 'football', 'match': 'C vs D', 'kickoffUtc': '2026-10-26T18:00:00Z'}
    legacy = {'sport': 'football', 'match': 'E vs F', 'time': '22:30'}   # 19:30Z via Forebet time
    ok = {'sport': 'football', 'match': 'G vs H', 'kickoffUtc': '2026-10-26T19:00:00Z'}
    old = [early, late, legacy, ok]
    now = datetime(2026, 10, 26, 18, 20, tzinfo=timezone.utc)
    tp.withdraw_published(old, DAY, lambda r: None if r is ok else block,
                          lambda rec: 'Key absences: X (out)', now)
    assert early['withdrawn'] and early['withdrawKind'] == 'availability'
    assert early['withdrawReason'] == 'Key absences: X (out)'
    assert early['withdrawnAt'] == '2026-10-26T18:20:00Z'
    assert legacy['withdrawn']
    assert 'withdrawn' not in late and 'withdrawn' not in ok
