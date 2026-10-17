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
# Hokej wraca do TOP: 17.10 trafił 9/12 przy kursach 1.65–2.30.
EXCLUDED_SPORTS = {s for s in os.getenv('TOP_EXCLUDED_SPORTS', '').split(',') if s}
MIN_WINS = int(os.getenv('TOP_MIN_WINS', '3'))
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
    if (_wins(form.get(me)) or 0) < MIN_WINS:
        return None
    if _wins(venue_me) is not None and _wins(venue_me) < MIN_WINS:
        return None
    if sport == 'basketball' and me == 'away':
        if (_wins(venue_me) or 0) <= 2 and _wins(venue_op) != 0:
            return None

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
            ('h2h', 'H2H'), ('fanvote', 'Fan Vote'), ('stars', 'Siła')]
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
        for col, w in zip('ABCDEFGHIJKLMN', (11, 7, 11, 16, 38, 24, 7, 7, 7, 10, 34, 7, 9, 7)):
            ws.column_dimensions[col].width = w
    out = os.path.join(ROOT, 'results', 'TOP.xlsx')
    wb.save(out)
    print(f"   📊 Excel: {out} ({len(hist)} TOP w historii)")
    return out


def send_email(picks: List[Dict[str, Any]], day: str, attach: Optional[str] = None,
               new_count: Optional[int] = None) -> None:
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
    grades = ('A', 'B')
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
    known = {_key(r) for r in old}
    new = [r for r in picks if _key(r) not in known]
    merged = old + new
    merged.sort(key=lambda r: (r.get('time') or '99:99'))
    with open(out_p, 'w', encoding='utf-8') as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=1)
    print(f"   ➕ nowe TOP w tym przebiegu: {len(new)} (łącznie dziś {len(merged)})")
    xlsx = write_excel(day)
    if '--email' in sys.argv and new:
        send_email(merged, day, attach=xlsx, new_count=len(new))
    print(f"â­ TOP {day} (Grade {'/'.join(grades)}): {len(picks)}")
    for r in picks:
        print(f"{r['time']} {r['sport']:<10} {r['match']} | {r['league']}\n"
              f"   âžś {r['pick']} @ {r['odds']:.2f} | Grade {r['grade']} score {r['score']}"
              f" | forma {r['form']} | H2H {r['h2h']} | FanVote {r['fanvote']} | {r['signals']}")
