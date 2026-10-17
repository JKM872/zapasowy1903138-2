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
MIN_ODDS = {'football': float(os.getenv('TOP_MIN_ODDS_FOOTBALL', '2.0'))}
EXCLUDED_SPORTS = set(os.getenv('TOP_EXCLUDED_SPORTS', 'hockey').split(','))
PTS = {'W': 3, 'D': 1, 'L': 0}


def _pts(form: Optional[List[str]]) -> Optional[int]:
    f = [x for x in (form or []) if x in PTS]
    return sum(PTS[x] for x in f[:5]) if len(f) >= 3 else None


def evaluate(m: Dict[str, Any], sport: str) -> Optional[Dict[str, Any]]:
    """None = nie TOP, inaczej dict z uzasadnieniem."""
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
    w_me = h2h.get('homeWins' if me == 'home' else 'awayWins') or 0
    w_op = h2h.get('awayWins' if me == 'home' else 'homeWins') or 0
    signals['h2h'] = _cmp(w_me, w_op) if h2h.get('total') else None
    if ss.get('found'):
        fv_me = ss.get('homeProb' if me == 'home' else 'awayProb') or 0
        signals['fanvote'] = 1 if fv_me > 55 else (-1 if fv_me < 45 else 0)
    sp = (m.get('scoring') or {}).get('prob')
    signals['model'] = None if sp is None else (1 if sp >= 55 else (-1 if sp < 45 else 0))

    have = {k: v for k, v in signals.items() if v is not None}
    if not have or any(v < 0 for v in have.values()):
        return None
    if 'forma' not in have or have['forma'] <= 0:   # forma musi być lepsza
        return None
    if sum(1 for v in have.values() if v > 0) < max(3, round(len(have) * 0.75)):
        return None

    team = m.get('homeTeam') if me == 'home' else m.get('awayTeam')
    return {
        'sport': sport, 'time': m.get('time'), 'league': m.get('league'),
        'match': f"{m.get('homeTeam')} vs {m.get('awayTeam')}", 'pick': team,
        'odds': float(o_me), 'grade': m.get('predictionGrade'),
        'score': (m.get('scoring') or {}).get('prob'),
        'form': f"{''.join(form.get(me) or [])} ({p_me} pkt) vs {''.join(form.get(op) or [])} ({p_op} pkt)",
        'h2h': f"{w_me}-{w_op}" if h2h.get('total') else 'brak',
        'fanvote': f"{ss.get('homeProb' if me == 'home' else 'awayProb')}%" if ss.get('found') else 'brak',
        'signals': f"{sum(1 for v in have.values() if v > 0)}/{len(have)} za",
    }


def collect(day: str, grades=('A', 'B')) -> List[Dict[str, Any]]:
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
                r = evaluate(m, sport)
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
        if v.get('sofascore_found'):
            m['sofascore'] = {'found': True, 'votes': v.get('sofascore_total_votes'),
                              'homeProb': v.get('sofascore_home_win_prob'),
                              'awayProb': v.get('sofascore_away_win_prob')}
    except Exception as e:
        print(f"   ⚠️ Fan Vote {m.get('homeTeam')}: {type(e).__name__}")


def collect_enriched(day: str, grades=('A', 'B')) -> List[Dict[str, Any]]:
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
            if not evaluate(m, sport):          # bez szans — nie pytamy SofaScore
                continue
            enrich_fanvote(m, sport, day)
            r = evaluate(m, sport)
            if r:
                out.append(r)
    return sorted(out, key=lambda r: (r['time'] or '99:99'))


def send_email(picks: List[Dict[str, Any]], day: str) -> None:
    import smtplib
    from email.mime.text import MIMEText
    from html import escape
    to, frm, pw = (os.getenv('EMAIL_RECIPIENT'), os.getenv('EMAIL_SENDER'),
                   os.getenv('EMAIL_PASSWORD'))
    if not (to and frm and pw):
        print('   ℹ️ Mail TOP pominięty (brak EMAIL_*)')
        return
    rows = ''.join(
        f"<tr><td>{escape(str(r['time']))}</td><td>{escape(r['sport'])}</td>"
        f"<td>{escape(r['match'])}<br><small>{escape(str(r['league']))}</small></td>"
        f"<td><b>{escape(str(r['pick']))}</b> @ {r['odds']:.2f}</td>"
        f"<td>{escape(str(r['grade']))} / {r['score']}</td><td>{escape(r['form'])}</td>"
        f"<td>{escape(r['h2h'])}</td><td>{escape(r['fanvote'])}</td><td>{escape(r['signals'])}</td></tr>"
        for r in picks)
    html = (f"<h2>⭐ TOP — {day}</h2><p>Perełki z Grade A/B: typowana drużyna dominuje "
            f"we wszystkich danych (Forebet, forma, dom/wyjazd, H2H, SofaScore, model).</p>"
            f"<table border='1' cellpadding='5' style='border-collapse:collapse;font-family:sans-serif'>"
            f"<tr><th>Godz.</th><th>Sport</th><th>Mecz</th><th>Typ</th><th>Grade/score</th>"
            f"<th>Forma</th><th>H2H</th><th>Fan Vote</th><th>Sygnały</th></tr>{rows}</table>")
    msg = MIMEText(html, 'html', 'utf-8')
    msg['Subject'] = f"⭐ TOP — {day} ({len(picks)})"
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
    grades = ('A', 'B')
    for a in sys.argv[1:]:
        if a.startswith('--grades='):
            grades = tuple(a.split('=', 1)[1].split(','))
    picks = collect_enriched(day, grades) if '--fanvote' in sys.argv else collect(day, grades)
    if '--email' in sys.argv and picks:
        send_email(picks, day)
    out_p = os.path.join(ROOT, 'results', f'top_{day}.json')
    with open(out_p, 'w', encoding='utf-8') as fh:
        json.dump(picks, fh, ensure_ascii=False, indent=1)
    print(f"â­ TOP {day} (Grade {'/'.join(grades)}): {len(picks)}")
    for r in picks:
        print(f"{r['time']} {r['sport']:<10} {r['match']} | {r['league']}\n"
              f"   âžś {r['pick']} @ {r['odds']:.2f} | Grade {r['grade']} score {r['score']}"
              f" | forma {r['form']} | H2H {r['h2h']} | FanVote {r['fanvote']} | {r['signals']}")
