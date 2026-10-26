"""tools/top_rules.py – decision table, poisoned holdout, load() fallback, CLI."""
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from tools import top_rules as TR

TE = '2026-10-10'
HOLDOUT = {'start': '2026-10-11', 'end': '2026-10-26', 'n': 0}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(TR, '_WARNED', set())
    monkeypatch.setattr(TR, '_CACHE', {})
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    monkeypatch.delenv('SUPABASE_KEY', raising=False)


# ── decision table on in-memory rows ──────────────────────────────────────

def _rows(n, sport='hockey', odds2=1.9, side='home', grade='B', tier='T2',
          wins_h1=None, wins_h2=None, start='2026-09-12'):
    """n rows split evenly over two halves (09-12.. and 10-02..); wins per half."""
    out = []
    half = n // 2
    for i in range(n):
        first = i < half
        day = (date.fromisoformat(start if first else '2026-10-02') + timedelta(days=i % 7)).isoformat()
        k = i if first else i - half
        won = k < (wins_h1 if first else wins_h2)
        out.append({'day': day, 'time': '18:00', 'sport': sport, 'src': 'forebet', 'grade': grade,
                    'side': side, 'odds': odds2, 'odds2': odds2, 'market': '2way',
                    'band': TR.band(odds2), 'tier': tier, 'struct': True, 'top': True,
                    'won': won, 'draw': False, 'key': f'{sport}{side}{grade}{odds2}{i}{start}'})
    return out


def _build(rows):
    return TR.build_rules(rows, TE, holdout=HOLDOUT, generated_at='2026-10-26T03:00:00Z')


def test_allow_needs_n50_positive_roi_and_both_halves():
    rules = _build(_rows(60, wins_h1=18, wins_h2=18))          # 60% @1.9 -> ROI-5% +11.3%
    s = rules['segments']['hockey|1.8-2.0|home']
    assert (s['level'], s['n'], s['decision']) == ('sport×band×side', 60, 'allow')
    p = (36 + 2 * 0.6) / 62                                    # parent hit rate 0.6
    assert s['pCal'] == round(p, 3)
    assert s['floorOdds'] == max(TR.pricing.floor_price(p), 1.8)
    d = TR.decide(rules, 'hockey', 1.9, 'home', 'B', 'T2')
    assert (d['decision'], d['segment'], d['floorOdds']) == ('allow', 'hockey|1.8-2.0|home', s['floorOdds'])
    assert TR.validate(rules, datetime(2026, 10, 27, tzinfo=timezone.utc)) is None


def test_negative_roi_excluded_and_one_bad_half_excluded():
    rules = _build(_rows(60, wins_h1=12, wins_h2=12))          # 40% @1.9 -> negative
    assert rules['segments']['hockey|1.8-2.0|home']['decision'] == 'exclude'
    rules = _build(_rows(60, wins_h1=30, wins_h2=10))          # overall +, H2 -
    s = rules['segments']['hockey|1.8-2.0|home']
    assert s['roi'] > 0 and s['h2'] < 0 and s['decision'] == 'exclude'
    assert TR.decide(rules, 'hockey', 1.9, 'home', 'B', 'T2')['decision'] == 'exclude'


def test_small_cell_inherits_parent():
    rows = _rows(60, side='home', wins_h1=18, wins_h2=18) + _rows(20, side='away', wins_h1=0, wins_h2=0)
    rules = _build(rows)
    segs = rules['segments']
    assert segs['hockey|1.8-2.0|away']['decision'] == 'inherit'
    assert segs['hockey|1.8-2.0']['n'] == 80
    d = TR.decide(rules, 'hockey', 1.9, 'away', 'B', 'T2')
    assert d['segment'] == 'hockey|1.8-2.0' and d['decision'] == segs['hockey|1.8-2.0']['decision']


def test_top_level_sport_below_50_is_excluded():
    rules = _build(_rows(30, sport='volleyball', wins_h1=15, wins_h2=15))
    assert rules['segments']['volleyball']['decision'] == 'exclude'
    assert rules['segments']['volleyball|1.8-2.0|home']['decision'] == 'inherit'
    d = TR.decide(rules, 'volleyball', 1.9, 'home', 'B', 'T2')
    assert (d['decision'], d['segment']) == ('exclude', 'volleyball')


def test_grade_and_tier_exclusions_override_allowed_band():
    good = _rows(60, grade='A', tier='T1', wins_h1=18, wins_h2=18)
    bad_grade = _rows(60, grade='C', tier='T2', odds2=1.5, wins_h1=10, wins_h2=10)
    rules = _build(good + bad_grade)
    assert rules['segments']['hockey|1.8-2.0|home']['decision'] == 'allow'
    assert rules['segments']['hockey|grade:C']['decision'] == 'exclude'
    assert TR.decide(rules, 'hockey', 1.9, 'home', 'A', 'T1')['decision'] == 'allow'
    d = TR.decide(rules, 'hockey', 1.9, 'home', 'C', 'T1')
    assert (d['decision'], d['segment']) == ('exclude', 'hockey|grade:C')
    bad_tier = _rows(60, grade='B', tier='T3', odds2=1.5, wins_h1=10, wins_h2=10)
    rules = _build(good + bad_tier)
    assert rules['segments']['hockey|tier:T3']['decision'] == 'exclude'
    assert TR.decide(rules, 'hockey', 1.9, 'home', 'A', 'T3')['segment'] == 'hockey|tier:T3'


def test_unknown_sport_uses_default_exclude():
    rules = _build(_rows(60, wins_h1=18, wins_h2=18))
    assert TR.decide(rules, 'rugby', 1.9, 'home', 'A', 'T2')['decision'] == 'exclude'


def test_fallback_gate():
    fb = TR.fallback('file missing')
    assert TR.decide(fb, 'tennis', 1.7, 'home', 'A')['decision'] == 'exclude'
    assert TR.decide(fb, 'basketball', 1.79, 'away', 'B')['decision'] == 'exclude'
    d = TR.decide(fb, 'tennis', 1.85, 'home', 'A')
    assert (d['decision'], d['floorOdds'], d['fallback']) == ('allow', 1.0, True)
    assert TR.decide(fb, 'football', 1.5, 'home', 'C')['decision'] == 'allow'


def test_build_ignores_rows_after_tuning_end():
    base = _rows(60, wins_h1=18, wins_h2=18)
    late = _rows(200, wins_h1=0, wins_h2=0, start='2026-10-11')
    for r in late:
        r['day'] = '2026-10-15'
    assert _build(base)['segments'] == _build(base + late)['segments']


# ── file-based loaders: poisoned holdout ──────────────────────────────────

def _match(day, sport, j, home_odds, away_odds, mid, grade='B'):
    return {'homeTeam': f'{sport} Home {j} {day}', 'awayTeam': f'{sport} Away {j} {day}',
            'time': '18:00', 'league': 'Liga', 'country': 'Poland', 'qualifies': True,
            'predictionGrade': grade, 'scoring': {'pick': '1', 'prob': 60},
            'forebet': {'prediction': '1', 'homeProb': 60, 'awayProb': 40},
            'odds': {'home': home_odds, 'away': away_odds},
            'matchUrl': f'https://www.livesport.com/pl/mecz/x/?mid={mid}'}


def _write_root(root, poison=False):
    res, out = root / 'results', root / 'outputs'
    res.mkdir(parents=True)
    out.mkdir(parents=True)
    store, settled = {}, {}
    d0 = date(2026, 9, 12)
    for i in range(45):                                    # 09-12 .. 10-26
        day = (d0 + timedelta(days=i)).isoformat()
        post = day > TE
        if post and not poison:
            continue
        for sport, ho, ao in (('tennis', 1.7, 2.2), ('basketball', 1.9, 2.0)):
            ms = []
            for j in range(4):
                mid = f'{sport[:2]}{i:02d}{j}'
                ms.append(_match(day, sport, j, ho, ao, mid))
                won = (j < 3) if not post else (j < (4 if sport == 'tennis' else 0))
                store[f'https://www.livesport.com/pl/mecz/x/?mid={mid}'] = {
                    'status': 'finished', 'winner': 'home' if won else 'away', 'date': day,
                    'home_team': ms[-1]['homeTeam'], 'away_team': ms[-1]['awayTeam']}
            (res / f'matches_{day}_{sport}_forebet.json').write_text(
                json.dumps({'date': day, 'matches': ms}), encoding='utf-8')
        if post:                                           # Livesport-era file after tuning.end
            ls = [_match(day, 'tennis', 9 + j, 1.5, 2.6, f'ls{i:02d}{j}', grade='A') for j in range(30)]
            for m in ls:
                store[m['matchUrl']] = {'status': 'finished', 'winner': 'home', 'date': day,
                                        'home_team': m['homeTeam'], 'away_team': m['awayTeam']}
                settled[f"{day}|tennis|{m['homeTeam']}|{m['awayTeam']}"] = {'status': 'settled', 'winner': 'home'}
            (res / f'matches_{day}_tennis.json').write_text(json.dumps({'matches': ls}), encoding='utf-8')
    # a tuning-window match whose only result is dated after tuning.end
    m = _match(TE, 'tennis', 99, 1.7, 2.2, 'late01')
    p = res / f'matches_{TE}_tennis_forebet.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    data['matches'].append(m)
    p.write_text(json.dumps(data), encoding='utf-8')
    if poison:
        store[m['matchUrl']] = {'status': 'finished', 'winner': 'away', 'date': '2026-10-11',
                                'home_team': m['homeTeam'], 'away_team': m['awayTeam']}
        settled[f"2026-10-11|tennis|{m['homeTeam']}|{m['awayTeam']}"] = {'status': 'settled', 'winner': 'away'}
    (out / 'result_store.json').write_text(json.dumps(store), encoding='utf-8')
    (res / 'forebet_settled.json').write_text(json.dumps(settled), encoding='utf-8')
    return str(root)


def test_poisoned_holdout_does_not_change_rules(tmp_path):
    clean = _write_root(tmp_path / 'clean')
    poisoned = _write_root(tmp_path / 'poisoned', poison=True)
    lc, lp = TR.load_learning_rows(TE, clean), TR.load_learning_rows(TE, poisoned)
    assert lc and max(r['day'] for r in lp) <= TE
    assert sorted(r['key'] for r in lc) == sorted(r['key'] for r in lp)
    rc, rp = _build(lc), _build(lp)
    assert rc['segments'] == rp['segments'] and rc['tuning'] == rp['tuning']
    # the holdout loader does see the poisoned rows
    hold = TR.load_holdout_rows(TE, poisoned, sources=('forebet', 'livesport'))
    assert {r['src'] for r in hold} == {'forebet', 'livesport'}
    assert min(r['day'] for r in hold) > TE


def test_unsettled_forebet_row_does_not_suppress_settled_livesport_duplicate(tmp_path):
    TR._STORE_CACHE.clear()
    res, out = tmp_path / 'results', tmp_path / 'outputs'
    res.mkdir()
    out.mkdir()
    day = '2026-10-01'
    fb = _match(day, 'tennis', 1, 1.7, 2.2, 'fb001')            # no result for this mid
    ls = dict(fb, matchUrl='https://www.livesport.com/pl/mecz/x/?mid=ls001')
    (res / f'matches_{day}_tennis_forebet.json').write_text(json.dumps({'matches': [fb]}), encoding='utf-8')
    (res / f'matches_{day}_tennis.json').write_text(json.dumps({'matches': [ls]}), encoding='utf-8')
    (out / 'result_store.json').write_text(json.dumps({ls['matchUrl']: {
        'status': 'finished', 'winner': 'home', 'date': '2026-10-02',
        'home_team': 'x', 'away_team': 'y'}}), encoding='utf-8')
    rows = TR.load_learning_rows(TE, str(tmp_path))
    assert [(r['src'], r['won']) for r in rows] == [('livesport', True)]
    TR._STORE_CACHE.clear()


# ── load(): validation + fallback ─────────────────────────────────────────

def _valid(tmp_path):
    rules = _build(_rows(60, wins_h1=18, wins_h2=18))
    p = tmp_path / 'top_rules.json'
    p.write_text(json.dumps(rules), encoding='utf-8')
    return p, rules


NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)


def test_load_valid_file(tmp_path, capsys):
    p, rules = _valid(tmp_path)
    got = TR.load(str(p), now=NOW)
    assert not got.get('fallback') and got['segments'] == rules['segments']
    assert 'rules fallback' not in capsys.readouterr().err


@pytest.mark.parametrize('mutate,reason', [
    (lambda p, r: p.unlink(), 'file missing'),
    (lambda p, r: p.write_text('{"version": 1, ', encoding='utf-8'), 'invalid JSON'),
    (lambda p, r: p.write_text(json.dumps({**r, 'version': 2}), encoding='utf-8'), 'unknown version'),
    (lambda p, r: p.write_text(json.dumps({**r, 'generatedAt': '2026-10-01T00:00:00Z'}), encoding='utf-8'), 'stale'),
    (lambda p, r: p.write_text(json.dumps({**r, 'holdout': {'start': '2026-10-05', 'end': '2026-10-26'}}),
                               encoding='utf-8'), 'tuning.end'),
    (lambda p, r: p.write_text(json.dumps({**r, 'segments': {'x': {'decision': 'allow', 'floorOdds': 0.5,
                                                                    'pCal': 0.6}}}), encoding='utf-8'),
     'out of range'),
    (lambda p, r: p.write_text(json.dumps({**r, 'segments': {'x': {'decision': 'maybe'}}}), encoding='utf-8'),
     'bad segment'),
])
def test_load_falls_back(tmp_path, capsys, mutate, reason):
    p, rules = _valid(tmp_path)
    mutate(p, rules)
    got = TR.load(str(p), now=NOW)
    assert got['fallback'] is True and reason in got['reason']
    assert TR.decide(got, 'tennis', 1.6, 'home', 'A')['decision'] == 'exclude'
    err = capsys.readouterr().err
    assert 'WARNING rules fallback' in err and reason in err
    TR.load(str(p), now=NOW)
    assert 'WARNING' not in capsys.readouterr().err        # once per process


def test_load_caches_without_now(tmp_path):
    p, _ = _valid(tmp_path)
    first = TR.load(str(p))                                 # generatedAt is in the past -> may be stale
    p.unlink()
    assert TR.load(str(p)) is first


# ── CLI ───────────────────────────────────────────────────────────────────

def test_cli_build_report(tmp_path):
    root = _write_root(tmp_path / 'r', poison=True)
    assert TR.main(['--build', '--report', '--tuning-end', TE, '--root', root]) == 0
    out = os.path.join(root, 'outputs')
    rules = json.load(open(os.path.join(out, 'top_rules.json'), encoding='utf-8'))
    assert TR.validate(rules) is None
    assert rules['tuning']['end'] == TE and rules['holdout']['start'] == '2026-10-11'
    rep = json.load(open(os.path.join(out, 'top_rules_report.json'), encoding='utf-8'))
    u = rep['universes']['candidates']['twoWay']
    assert set(u) == {'before', 'after', 'applied', 'perSport'} and u['before']['n'] > 0
    assert {'n', 'hit', 'roiRaw', 'roi5', 'maxDD', 'ci95'} <= set(u['before'])
    assert 'asStored' in rep['universes']['topReplay']
    assert isinstance(rules['enforcement']['enforce'], bool)
    assert rep['gateMode'] in ('enforced', 'shadow') and 'status' in rep['safeGateForward']
    md = open(os.path.join(out, 'top_rules_report.md'), encoding='utf-8').read()
    assert 'holdout 2026-10-11..2026-10-26' in md
    assert 'Caveat (holdout leak)' in md and 'Forward check of the 1.80 cut' in md


def test_cli_short_holdout_fails_and_keeps_old_file(tmp_path, capsys):
    root = _write_root(tmp_path / 'r', poison=True)
    old = os.path.join(root, 'outputs', 'top_rules.json')
    open(old, 'w', encoding='utf-8').write('{"old": true}')
    assert TR.main(['--build', '--tuning-end', '2026-10-20', '--root', root]) == 1
    assert 'ERROR holdout' in capsys.readouterr().err
    assert json.load(open(old, encoding='utf-8')) == {'old': True}
