"""Kategoria TOP â€” pereĹ‚ki wybrane spoĹ›rĂłd zakwalifikowanych Grade A/B.

Zasada: typowana druĹĽyna DOMINUJE rywala we wszystkim, co mamy:
  * forma ogĂłlna (ostatnie 5) â€” wiÄ™cej punktĂłw niĹĽ rywal,
  * forma u siebie / na wyjeĹşdzie â€” nie gorsza niĹĽ rywala,
  * H2H â€” typowana strona wygraĹ‚a wiÄ™cej (albo brak H2H),
  * Forebet, scoring i rynek wskazujÄ… tÄ™ samÄ… stronÄ™ (kurs â‰¤ kurs rywala),
  * Fan Vote, jeĹ›li jest â€” wiÄ™kszoĹ›Ä‡ za typowanÄ… stronÄ….
PiĹ‚ka: kurs na typowanÄ… druĹĽynÄ™ â‰Ą 2.0 (TOP_MIN_ODDS_FOOTBALL).

UĹĽycie: python tools/top_picks.py [YYYY-MM-DD] [--grades A,B]
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import date
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tools import best_price, league_tier, pricing, staking, top_rules  # noqa: E402

# Learned segment rules (outputs/top_rules.json, tools/top_rules.py); a missing,
# stale or invalid file logs "WARNING rules fallback" and gives the safe gate.
RULES = top_rules.load()
MIN_ODDS = {'football': float(os.getenv('TOP_MIN_ODDS_FOOTBALL', '2.0'))}
# Hokej wraca do TOP: 17.10 trafił 9/12 przy kursach 1.65–2.30.
EXCLUDED_SPORTS = {s for s in os.getenv('TOP_EXCLUDED_SPORTS', '').split(',') if s}
# Backtest 2026-09-12..10-22 (1 714 settled qualified matches, split in halves):
#   old rules  (A/B, 3 wins of 5): 131 picks, 3.9/day, ROI +24.9% (+18.6% at -5% odds)
#   relaxed    (A/B/C, 2 of 5)   : 370 picks, 10/day,  ROI +22.9% (+16.7% at -5% odds)
# The added picks earned on their own in BOTH halves (+43.9% / +15.0%), except
# basketball, where the extra picks were flat after a realistic price
# (-0.2%) — so basketball keeps the old, stricter rules.
MIN_WINS = int(os.getenv('TOP_MIN_WINS', '2'))
DEFAULT_GRADES = tuple(g for g in os.getenv('TOP_GRADES', 'A,B,C').split(',') if g)
STRICT_SPORTS = {s for s in os.getenv('TOP_STRICT_SPORTS', 'basketball').split(',') if s}
STRICT_MIN_WINS = 3
STRICT_GRADES = ('A', 'B')
PTS = {'W': 3, 'D': 1, 'L': 0}


def _pts(form: Optional[List[str]]) -> Optional[int]:
    f = [x for x in (form or []) if x in PTS]
    return sum(PTS[x] for x in f[:5]) if len(f) >= 3 else None


def evaluate(m: Dict[str, Any], sport: str, day: Optional[str] = None,
             apply_rules: bool = True) -> Optional[Dict[str, Any]]:
    """None = nie TOP, inaczej dict z uzasadnieniem.

    ``apply_rules=False`` gives the pre-rules gates only (tools/top_rules.py
    replays them as the "before" set); ``day`` lets the pick carry kickoffUtc.
    """
    # Dane z poprzedniego sezonu (recency w forebet_pipeline): mało meczów w
    # sezonie, model daleko od rynku, albo forma ogólna sprzeczna z sezonową.
    if m.get('earlySeason') or m.get('staleModel') or m.get('seasonFormConflict'):
        return None
    strict = sport in STRICT_SPORTS
    if strict and (m.get('predictionGrade') or '') not in STRICT_GRADES:
        return None
    min_wins = STRICT_MIN_WINS if strict else MIN_WINS
    pick = (m.get('scoring') or {}).get('pick')
    if pick not in ('1', '2'):
        return None
    fb = m.get('forebet') or {}
    if fb.get('prediction') != pick:
        return None
    me, op = ('home', 'away') if pick == '1' else ('away', 'home')
    odds = m.get('odds') or {}
    o_me, o_op = odds.get(me), odds.get(op)
    if not o_me or not o_op or float(o_me) > float(o_op):
        return None
    if float(o_me) < MIN_ODDS.get(sport, 0):
        return None

    # Dominacja liczona ze WSZYSTKICH dostępnych sygnałów (Forebet, forma,
    # forma u siebie/wyjazd, H2H, SofaScore Fan Vote, model). Każdy sygnał
    # musi być za typem albo neutralny — żaden nie może być przeciw — i
    # większość musi być wyraźnie za. Brak danego sygnału nie odrzuca meczu.
    form = m.get('form') or {}
    h2h = m.get('h2h') or {}
    ss = m.get('sofascore') or {}
    signals: Dict[str, int] = {}   # +1 za, 0 neutralnie, -1 przeciw

    def _cmp(a, b):
        if a is None or b is None:
            return None
        return 1 if a > b else (-1 if a < b else 0)

    fp_me = fb.get('homeProb' if me == 'home' else 'awayProb')
    fp_op = fb.get('awayProb' if me == 'home' else 'homeProb')
    signals['forebet'] = _cmp(fp_me, fp_op)
    p_me, p_op = _pts(form.get(me)), _pts(form.get(op))
    signals['forma'] = _cmp(p_me, p_op)
    v_me = _pts(form.get('homeAtHome' if me == 'home' else 'awayAtAway'))
    v_op = _pts(form.get('awayAtAway' if me == 'home' else 'homeAtHome'))
    signals['forma_dom_wyj'] = _cmp(v_me, v_op)
    if h2h.get('effectiveTotal') is not None:
        # H2H ważone wiekiem; same stare spotkania = brak H2H (neutralnie).
        w_me = h2h.get('homeWinsEff' if me == 'home' else 'awayWinsEff') or 0
        w_op = h2h.get('awayWinsEff' if me == 'home' else 'homeWinsEff') or 0
        has_h2h = (h2h.get('effectiveTotal') or 0) > 0
    else:
        w_me = h2h.get('homeWins' if me == 'home' else 'awayWins') or 0
        w_op = h2h.get('awayWins' if me == 'home' else 'homeWins') or 0
        has_h2h = bool(h2h.get('total'))
    signals['h2h'] = _cmp(w_me, w_op) if has_h2h else None
    if ss.get('found'):
        fv_me = ss.get('homeProb' if me == 'home' else 'awayProb') or 0
        signals['fanvote'] = 1 if fv_me > 55 else (-1 if fv_me < 45 else 0)
    sp = (m.get('scoring') or {}).get('prob')
    signals['model'] = None if sp is None else (1 if sp >= 55 else (-1 if sp < 45 else 0))

    # Wnioski z rozliczenia 17.10:
    # (a) faworyt musi mieć min. 3 wygrane z 5 — ogólnie I u siebie/na wyjeździe
    #     (Pribram 1-4 przegrał mimo rywala 0-5),
    # (b) koszykówka: nie typujemy gości z bilansem wyjazdowym 2-3 lub gorszym,
    #     chyba że gospodarz u siebie ma 0-5 (Gaziantep, Maia, Oradea, Avenida).
    def _wins(f):
        f = [x for x in (f or []) if x in PTS][:5]
        return sum(1 for x in f if x == 'W') if len(f) >= 3 else None
    venue_me = form.get('homeAtHome' if me == 'home' else 'awayAtAway')
    venue_op = form.get('awayAtAway' if me == 'home' else 'homeAtHome')
    if (_wins(form.get(me)) or 0) < min_wins:
        return None
    if _wins(venue_me) is not None and _wins(venue_me) < min_wins:
        return None
    if sport == 'basketball' and me == 'away':
        if (_wins(venue_me) or 0) <= 2 and _wins(venue_op) != 0:
            return None

    if m.get('nationalFriendly') is True:    # sparing reprezentacji — pomijamy
        return None

    have = {k: v for k, v in signals.items() if v is not None}
    if not have or any(v < 0 for v in have.values()):
        return None
    if 'forma' not in have or have['forma'] <= 0:   # forma musi być lepsza
        return None
    if sum(1 for v in have.values() if v > 0) < max(3, round(len(have) * 0.75)):
        return None

    try:
        from tools import injuries as _inj
    except Exception:
        _inj = None
    # Absencje: odrzucamy tylko gdy typowana strona traci więcej niż rywal.
    if _inj and _inj.excludes(m, me):
        return None

    team = m.get('homeTeam') if me == 'home' else m.get('awayTeam')

    def _f(x):
        return ''.join(x) if isinstance(x, list) else (x or '')
    season_form = ((_f(form.get('homeSeason' if me == 'home' else 'awaySeason')) + ' / '
                    + _f(form.get('awaySeason' if me == 'home' else 'homeSeason')))
                   if (form.get('homeSeason') is not None or form.get('awaySeason') is not None)
                   else '')
    out = {
        'sport': sport, 'time': m.get('time'), 'league': m.get('league'),
        'match': f"{m.get('homeTeam')} vs {m.get('awayTeam')}", 'pick': team,
        'odds': float(o_me), 'grade': m.get('predictionGrade'),
        'score': (m.get('scoring') or {}).get('prob'),
        'form': f"{''.join(form.get(me) or [])} ({p_me} pkt) vs {''.join(form.get(op) or [])} ({p_op} pkt)",
        'h2h': f"{w_me}-{w_op}" if has_h2h else 'brak',
        'fanvote': f"{ss.get('homeProb' if me == 'home' else 'awayProb')}%" if ss.get('found') else 'brak',
        'signals': f"{sum(1 for v in have.values() if v > 0)}/{len(have)} za",
        'seasonForm': season_form,
        'category': m.get('category'),
        'formBlock': _form_block(m),
        **(_inj.fields(m) if _inj else {}),
    }
    if not apply_rules:
        return out
    return _apply_rules(out, m, sport, me, odds, day)


def _apply_rules(out: Dict[str, Any], m: Dict[str, Any], sport: str, me: str,
                 odds: Dict[str, Any], day: Optional[str]) -> Optional[Dict[str, Any]]:
    """Rules gate (design K1/K5): None when the segment is excluded, else the
    pick with odds2/oddsMarket/segment/floorOdds/pCal/stakePct/kickoffUtc."""
    o2, market = pricing.side_price(odds, sport, me)
    o2 = float(o2 or out['odds'])
    grade = m.get('predictionGrade') or ''
    # Learned rules decide only when outputs/top_rules.json says enforcement.enforce
    # (holdout >= 3 picks/day and ROI -5% > 0); else the safe gate decides and the
    # learned decision is just recorded (top_rules.gate, mode shadow/fallback).
    d = top_rules.gate(RULES, sport, o2, me, grade, league_tier.tier(m, sport))
    if d['decision'] != 'allow':
        return None
    out.update({
        'odds2': o2, 'oddsMarket': market, 'segment': d['segment'],
        'rulesMode': d['mode'], 'learnedDecision': d['learnedDecision'],
        'learnedSegment': d['learnedSegment'],
        'floorOdds': d['floorOdds'] or 1.0, 'pCal': d['pCal'],
        'stakePct': staking.stake_pct(grade, d['pCal'], o2),
        # Forebet time read per sport (pricing.FOREBET_TZ_BY_SPORT); replaced by
        # an explicit source kickoff when best_price finds one.
        'kickoffUtc': pricing.parse_kickoff(day, m.get('time'), None, sport) if day else None,
        'kickoffApprox': True,
    })
    return out


def _live_withdrawn(day: str) -> set:
    """Keys withdrawn by the live job (results/top_live_<day>.json); none when missing."""
    p = os.path.join(ROOT, 'results', f'top_live_{day}.json')
    if not os.path.exists(p):
        return set()
    try:
        live = json.load(open(p, encoding='utf-8-sig'))
    except Exception as e:
        print(f"WARNING top_live_{day}.json unreadable ({type(e).__name__}) – no live withdrawals",
              file=sys.stderr)
        return set()
    if not isinstance(live, dict):
        return set()
    return {k for k, v in live.items() if isinstance(v, dict) and v.get('withdrawn')}


def select_new(picks: List[Dict[str, Any]], old: List[Dict[str, Any]],
               day: str) -> List[Dict[str, Any]]:
    """Picks not yet published today, minus live withdrawals, through the floor gate."""
    known = {_key(r) for r in old}
    # Withdrawn by the live job (pre-kickoff check) => never published again.
    live_out = _live_withdrawn(day)
    new = []
    for r in picks:
        if _key(r) in known:
            continue
        if _key(r) in live_out:
            print(f"   🚫 TOP not re-added (withdrawn live): {r.get('match')}")
            continue
        new.append(r)
    return publish_gate(new, day)


def publish_gate(new: List[Dict[str, Any]], day: str) -> List[Dict[str, Any]]:
    """New picks only: best price, never below floorOdds, stake at the price we get."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    out = []
    for r in new:
        bp = best_price.best_price(r, day)
        price = bp['bestOdds'] or r.get('odds2') or r['odds']
        floor = r.get('floorOdds') or 1.0
        if price < floor:
            print(f"   ⛔ TOP below floor: {r.get('match')} {price:.2f} < {floor:.2f}")
            continue
        r.update({k: bp[k] for k in ('bestOdds', 'bestOddsSource', 'bestOddsAt', 'booksCount')})
        k = pricing.parse_kickoff(day, None, [bp['kickoff']], r.get('sport')) if bp.get('kickoff') else None
        if k:
            r['kickoffUtc'], r['kickoffApprox'] = k, False
        r['stakePct'] = staking.stake_pct(r.get('grade'), r.get('pCal'), price)
        r['publishedAt'] = now
        out.append(r)
    return out


def _form_block(m: Dict[str, Any]) -> str:
    """Wspólny blok 'Forma' / 'Sezon' (form_schema) jako tekst wieloliniowy."""
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import form_schema
        return '\n'.join(form_schema.form_lines(
            form_schema.block_from_json(m.get('form')), m.get('homeTeam') or '',
            m.get('awayTeam') or ''))
    except Exception:
        return ''


def collect(day: str, grades=DEFAULT_GRADES) -> List[Dict[str, Any]]:
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'results', f'matches_{day}_*_forebet.json'))):
        sport = os.path.basename(p)[len(f'matches_{day}_'):-len('_forebet.json')]
        if sport in EXCLUDED_SPORTS:
            continue
        try:
            ms = json.load(open(p, encoding='utf-8-sig')).get('matches') or []
        except Exception:
            continue
        for m in ms:
            if m.get('qualifies') and (m.get('predictionGrade') or '') in grades:
                r = evaluate(m, sport, day)
                if r:
                    out.append(r)
    return sorted(out, key=lambda r: (r['time'] or '99:99'))


def enrich_fanvote(m: Dict[str, Any], sport: str, day: str) -> None:
    """Dociągnij Fan Vote z SofaScore (przez przekaźnik), gdy go brak."""
    ss = m.get('sofascore') or {}
    if ss.get('found'):
        return
    try:
        sys.path.insert(0, ROOT)
        import sofascore_fanvote as fv
        from forebet_pipeline import _orient_fan_vote
        v = fv.get_fan_vote(m.get('homeTeam'), m.get('awayTeam'), sport, day)
        _orient_fan_vote(v, m.get('homeTeam'), m.get('awayTeam'))
        _remember_event(v, sport, m)
        if v.get('sofascore_found'):
            m['sofascore'] = {'found': True, 'votes': v.get('sofascore_total_votes'),
                              'homeProb': v.get('sofascore_home_win_prob'),
                              'awayProb': v.get('sofascore_away_win_prob')}
    except Exception as e:
        print(f"   ⚠️ Fan Vote {m.get('homeTeam')}: {type(e).__name__}")


def _remember_event(v: Dict[str, Any], sport: str, m: Dict[str, Any]) -> None:
    """Zweryfikowane zdarzenie Fan Vote -> do pobrania absencji bez szukania."""
    import re
    hit = re.search(r'/match/(\d+)', str(v.get('sofascore_url') or ''))
    if hit and v.get('sofascore_orientation') in ('direct', 'reversed'):
        from tools import injuries
        injuries.remember_event(sport, m.get('homeTeam'), m.get('awayTeam'),
                                int(hit.group(1)), v['sofascore_orientation'])


def enrich_injuries(m: Dict[str, Any], sport: str, day: str, side: Optional[str] = None) -> None:
    """Absencje dla kandydata TOP/Twierdzy; błąd => brak danych."""
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from tools import injuries
        if side is None:
            side = 'away' if (m.get('scoring') or {}).get('pick') == '2' else 'home'
        injuries.attach(m, sport, day, side)
    except Exception as e:
        print(f"   ⚠️ Absencje {m.get('homeTeam')}: {type(e).__name__}")


def collect_enriched(day: str, grades=DEFAULT_GRADES) -> List[Dict[str, Any]]:
    """Jak collect(), ale kandydatom bez Fan Vote dociąga go przed oceną."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'results', f'matches_{day}_*_forebet.json'))):
        sport = os.path.basename(p)[len(f'matches_{day}_'):-len('_forebet.json')]
        if sport in EXCLUDED_SPORTS:
            continue
        try:
            ms = json.load(open(p, encoding='utf-8-sig')).get('matches') or []
        except Exception:
            continue
        for m in ms:
            if not (m.get('qualifies') and (m.get('predictionGrade') or '') in grades):
                continue
            if not evaluate(m, sport, day):     # bez szans — nie pytamy SofaScore
                continue
            enrich_fanvote(m, sport, day)
            enrich_injuries(m, sport, day)
            r = evaluate(m, sport, day)
            if r:
                out.append(r)
    return sorted(out, key=lambda r: (r['time'] or '99:99'))


RECENCY_FLAGS = ('earlySeason', 'staleModel', 'seasonFormConflict')
TEAM_MATCH_MIN = 0.5


def recency_flagged(day: str) -> List[tuple]:
    """(sport, home, away) meczów Forebet z flagą recency na dany dzień."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'results', f'matches_{day}_*_forebet.json'))):
        sport = os.path.basename(p)[len(f'matches_{day}_'):-len('_forebet.json')]
        try:
            ms = json.load(open(p, encoding='utf-8-sig')).get('matches') or []
        except Exception:
            continue
        for m in ms:
            if any(m.get(k) for k in RECENCY_FLAGS):
                out.append((sport, m.get('homeTeam') or '', m.get('awayTeam') or ''))
    return out


def _overlap(a: str, b: str) -> float:
    # Ten sam matcher nazw co pipeline (Forebet vs Livesport: „Sydney” vs
    # „Sydney Kings”, sufiksy K/W); recency ma zapasowy, gdy import zawiedzie.
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    if 'forebet_pipeline' not in sys.modules:
        try:
            import forebet_pipeline  # noqa: F401  (rejestruje _name_overlap)
        except Exception:
            pass
    import recency
    return recency.name_overlap(a or '', b or '')


def is_flagged(flagged: List[tuple], sport: str, home: str, away: str) -> bool:
    """Czy mecz (dowolna nazwa / orientacja) jest na liście flag recency."""
    for s, fh, fa in flagged:
        if s != sport:
            continue
        if ((_overlap(home, fh) >= TEAM_MATCH_MIN and _overlap(away, fa) >= TEAM_MATCH_MIN)
                or (_overlap(home, fa) >= TEAM_MATCH_MIN and _overlap(away, fh) >= TEAM_MATCH_MIN)):
            return True
    return False


def drop_flagged(rows: List[Dict[str, Any]], day: str) -> List[Dict[str, Any]]:
    """Usuń z zapisanych TOP mecze, które w bieżących danych mają flagę recency."""
    flagged = recency_flagged(day)
    if not flagged:
        return rows
    out = []
    for r in rows:
        home, _, away = str(r.get('match') or '').partition(' vs ')
        if is_flagged(flagged, r.get('sport'), home, away):
            print(f"   ➖ TOP usunięty (recency): {r.get('match')}")
            continue
        out.append(r)
    return out


def _key(r: Dict[str, Any]) -> str:
    return f"{r['sport']}|{r['match']}"


def write_excel(day: str) -> Optional[str]:
    """results/TOP.xlsx — arkusz „Do gry” (dzisiaj) + „Wszystkie” (historia)."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        print('   ⚠️ brak openpyxl — pomijam Excel')
        return None
    hist = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'results', 'top_*.json'))):
        d = os.path.basename(p)[4:-5]
        try:
            for r in json.load(open(p, encoding='utf-8-sig')):
                hist.append({'date': d, **r})
        except Exception:
            pass
    cols = [('date', 'Data'), ('time', 'Godz.'), ('sport', 'Sport'), ('league', 'Liga'),
            ('match', 'Mecz'), ('pick', 'Typ'), ('odds', 'Kurs'), ('grade', 'Grade'),
            ('score', 'Score'), ('signals', 'Sygnały za'), ('form', 'Forma'),
            ('h2h', 'H2H'), ('fanvote', 'Fan Vote'), ('stars', 'Siła'),
            ('seasonForm', 'Forma sezon')]
    wb = Workbook()
    hdr_fill = PatternFill('solid', fgColor='FFD966')
    for title, rows in (('Do gry', [r for r in hist if r['date'] == day]),
                        ('Wszystkie', list(reversed(hist)))):
        ws = wb.active if title == 'Do gry' else wb.create_sheet(title)
        ws.title = title
        ws.append([c[1] for c in cols])
        for c in ws[1]:
            c.font, c.fill = Font(bold=True), hdr_fill
        for r in rows:
            full = str(r.get('signals', '')).split('/')
            r['stars'] = '⭐⭐⭐' if len(full) == 2 and full[0] == full[1].split()[0] else '⭐⭐'
            ws.append([r.get(k) for k, _ in cols])
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        for col, w in zip('ABCDEFGHIJKLMNO', (11, 7, 11, 16, 38, 24, 7, 7, 7, 10, 34, 7, 9, 7, 14)):
            ws.column_dimensions[col].width = w
    out = os.path.join(ROOT, 'results', 'TOP.xlsx')
    wb.save(out)
    print(f"   📊 Excel: {out} ({len(hist)} TOP w historii)")
    return out


def _analyst_html(analyst: Optional[List[Dict[str, Any]]]) -> str:
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from tools.ai_analyst import html_section
        return html_section(analyst or [])
    except Exception:
        return ''


def _analyst_saved(day: str) -> List[Dict[str, Any]]:
    try:
        from tools.ai_analyst import load
        return load(day)
    except Exception:
        return []


def run_analyst(day: str, merged: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analityk AI na TOP + Twierdza; każdy błąd => []."""
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from tools import ai_analyst
        try:
            from tools.daily_digest import twierdza
            tw = twierdza(day)
        except Exception as e:
            print(f"   ⚠️ Twierdza dla analityka: {type(e).__name__}")
            tw = []
        return ai_analyst.run(day, merged, tw)
    except Exception as e:
        print(f"   ⚠️ Analityk AI: {type(e).__name__}")
        return []


def send_email(picks: List[Dict[str, Any]], day: str, attach: Optional[str] = None,
               new_count: Optional[int] = None,
               analyst: Optional[List[Dict[str, Any]]] = None) -> None:
    import smtplib
    from email.mime.text import MIMEText
    from html import escape
    to, frm, pw = (os.getenv('EMAIL_RECIPIENT'), os.getenv('EMAIL_SENDER'),
                   os.getenv('EMAIL_PASSWORD'))
    if not (to and frm and pw):
        print('   ℹ️ Mail TOP pominięty (brak EMAIL_*)')
        return
    def row(r):
        return (
        f"<tr><td>{escape(str(r['time']))}</td><td>{escape(r['sport'])}</td>"
        f"<td>{escape(r['match'])}<br><small>{escape(str(r['league']))}</small>"
        + (f"<br><small>{escape(r['injuryLine'])}{' ⚠️' if r.get('injury_risk') else ''}</small>"
           if r.get('injuryLine') else '') + "</td>"
        f"<td><b>{escape(str(r['pick']))}</b> @ {r['odds']:.2f}</td>"
        f"<td>{escape(str(r['grade']))} / {r['score']}</td><td>{escape(r['form'])}</td>"
        f"<td>{escape(r['h2h'])}</td><td>{escape(r['fanvote'])}</td><td>{escape(r['signals'])}</td>"
        f"<td>{escape(r.get('seasonForm') or '')}</td>"
        f"<td style='white-space:pre;font-size:11px'>{escape(r.get('formBlock') or '')}</td></tr>")
    rows_for = lambda rs: ''.join(row(r) for r in rs)  # noqa: E731
    clubs = [r for r in picks if r.get('category') != 'reprezentacje']
    national = [r for r in picks if r.get('category') == 'reprezentacje']
    rows = rows_for(clubs)
    if national:
        rows += ("<tr><th colspan='11' style='text-align:left'>🏳️ Reprezentacje</th></tr>"
                 + rows_for(national))
    html = (_analyst_html(analyst)
            + f"<h2>⭐ TOP — {day}</h2><p>Perełki z Grade A/B: typowana drużyna dominuje "
            f"we wszystkich danych (Forebet, forma, dom/wyjazd, H2H, SofaScore, model).</p>"
            f"<table border='1' cellpadding='5' style='border-collapse:collapse;font-family:sans-serif'>"
            f"<tr><th>Godz.</th><th>Sport</th><th>Mecz</th><th>Typ</th><th>Grade/score</th>"
            f"<th>Forma</th><th>H2H</th><th>Fan Vote</th><th>Sygnały</th><th>Forma sezon</th><th>Forma / Sezon</th></tr>{rows}</table>")
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    msg = MIMEMultipart()
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    if attach and os.path.exists(attach):
        part = MIMEApplication(open(attach, 'rb').read(), Name=os.path.basename(attach))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attach)}"'
        msg.attach(part)
    extra = f", nowe: {new_count}" if new_count is not None else ''
    msg['Subject'] = f"⭐ TOP — {day} ({len(picks)}{extra})"
    msg['From'], msg['To'] = frm, to
    with smtplib.SMTP('smtp.gmail.com', 587) as s:
        s.starttls()
        s.login(frm, pw)
        s.sendmail(frm, [x.strip() for x in to.split(',')], msg.as_string())
    print(f"   ✅ Mail TOP wysłany ({len(picks)} meczów)")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    day = args[0] if args else date.today().isoformat()
    grades = DEFAULT_GRADES
    for a in sys.argv[1:]:
        if a.startswith('--grades='):
            grades = tuple(a.split('=', 1)[1].split(','))
    picks = collect_enriched(day, grades) if '--fanvote' in sys.argv else collect(day, grades)
    out_p = os.path.join(ROOT, 'results', f'top_{day}.json')
    # Tryb równoległy: workflow odpala się co godzinę w trakcie Forebet —
    # łączymy z tym, co już wysłaliśmy, i mailujemy tylko gdy są NOWE perełki.
    old = []
    if os.path.exists(out_p):
        try:
            old = json.load(open(out_p, encoding='utf-8-sig'))
        except Exception:
            old = []
    # Wcześniejszy przebieg mógł dodać mecz, który teraz ma flagę recency.
    old = drop_flagged(old, day)
    # Availability agent (tools/availability_agent.py): stars missing on the
    # picked side block a new pick; a published pick is marked withdrawn, which
    # the site shows and the record excludes (it was called off before kick-off).
    try:
        from tools import availability_agent as _av
        _avail = _av.load(day)
    except Exception:
        _av, _avail = None, {}

    def _avail_rec(r):
        h, _, a = str(r.get('match') or '').partition(' vs ')
        return _avail.get(f"{r.get('sport')}|{h}|{a}")

    for r in old:
        rec = _avail_rec(r)
        if rec and rec.get('top_block') and not r.get('withdrawn'):
            r['withdrawn'] = True
            r['withdrawReason'] = _av.note(rec) or 'Key player absences'
            print(f"   🚑 TOP wycofany (absencje): {r.get('match')} — {r['withdrawReason']}")
    blocked = [r for r in picks if (_avail_rec(r) or {}).get('top_block')]
    for r in blocked:
        print(f"   🚑 TOP zablokowany (absencje): {r.get('match')} — {_av.note(_avail_rec(r))}")
    picks = [r for r in picks if r not in blocked]
    for r in picks:
        n = _av.note(_avail_rec(r)) if _av else ''
        if n:
            r['availabilityNote'] = n
    new = select_new(picks, old, day)
    merged = old + new
    merged.sort(key=lambda r: (r.get('time') or '99:99'))
    with open(out_p, 'w', encoding='utf-8') as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=1)
    print(f"   ➕ nowe TOP w tym przebiegu: {len(new)} (łącznie dziś {len(merged)})")
    xlsx = write_excel(day)
    if '--email' in sys.argv and new:
        send_email(merged, day, attach=xlsx, new_count=len(new),
                   analyst=run_analyst(day, merged))
    elif merged and len(_analyst_saved(day)) < len(merged):
        run_analyst(day, merged)   # brak/niepełne werdykty bez nowych TOP — tylko zapis
    print(f"â­ TOP {day} (Grade {'/'.join(grades)}): {len(picks)}")
    for r in picks:
        print(f"{r['time']} {r['sport']:<10} {r['match']} | {r['league']}\n"
              f"   âžś {r['pick']} @ {r['odds']:.2f} | Grade {r['grade']} score {r['score']}"
              f" | forma {r['form']} | H2H {r['h2h']} | FanVote {r['fanvote']} | {r['signals']}")
