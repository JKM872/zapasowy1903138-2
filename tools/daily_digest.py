"""Dzienny Excel ze WSZYSTKICH workflow + podsumowanie AI → mail.

Arkusze:
  Podsumowanie  — liczby per workflow/sport + komentarz AI (Groq, 4 klucze)
  TOP           — perełki z tools/top_picks.py
  Forebet       — zakwalifikowane Forebet (A–D)
  Sports        — Sports Scraper (HOME + AWAY)
  Dropping      — OddsSafari dropping odds (zakwalifikowane)
  Tenis stołowy — AiScore/SofaScore (home + away)

Użycie: python tools/daily_digest.py [YYYY-MM-DD] [--email]
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import date
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
COLS = ['Źródło', 'Sport', 'Godz.', 'Mecz', 'Liga', 'Typ', 'Kurs', 'Grade',
        'Score', 'Forma typ', 'Forma rywal', 'H2H', 'Fan Vote', 'Link']


def _load(p: str) -> Any:
    try:
        return json.load(open(p, encoding='utf-8-sig'))
    except Exception:
        return None


def _f(x) -> str:
    return ''.join(x) if isinstance(x, list) else (x or '')


def _time(t) -> str:
    t = str(t or '')
    return t[-5:] if len(t) >= 5 else t


def _row(src, sport, m, side: Optional[str]) -> List[Any]:
    """side = 'home'/'away' (typowana strona) albo None."""
    home, away = m.get('homeTeam') or m.get('home_team'), m.get('awayTeam') or m.get('away_team')
    odds = m.get('odds') if isinstance(m.get('odds'), dict) else {}
    form = m.get('form') if isinstance(m.get('form'), dict) else {}
    fh = form.get('home') or m.get('homeForm')
    fa = form.get('away') or m.get('awayForm')
    h2h = m.get('h2h') if isinstance(m.get('h2h'), dict) else {}
    ss = m.get('sofascore') if isinstance(m.get('sofascore'), dict) else {}
    sc = m.get('scoring') if isinstance(m.get('scoring'), dict) else {}
    pick = (home if side == 'home' else away) if side else ''
    o = odds.get(side) if side else None
    fv = ss.get('homeProb' if side == 'home' else 'awayProb') if ss.get('found') else None
    hw = h2h.get('homeWins' if side == 'home' else 'awayWins')
    aw = h2h.get('awayWins' if side == 'home' else 'homeWins')
    return [src, sport, _time(m.get('time')), f"{home} vs {away}", m.get('league'),
            pick, o, m.get('predictionGrade'), sc.get('prob'),
            _f(fh if side == 'home' else fa), _f(fa if side == 'home' else fh),
            f"{hw}-{aw}" if h2h.get('total') else '', f"{fv}%" if fv is not None else '',
            m.get('matchUrl') or m.get('forebetUrl')]


def collect(day: str) -> Dict[str, List[List[Any]]]:
    R = os.path.join(ROOT, 'results')
    out: Dict[str, List[List[Any]]] = {'TOP': [], 'Forebet': [], 'Sports': [],
                                       'Dropping': [], 'Tenis stołowy': []}
    for r in _load(os.path.join(R, f'top_{day}.json')) or []:
        out['TOP'].append(['TOP', r.get('sport'), r.get('time'), r.get('match'), r.get('league'),
                           r.get('pick'), r.get('odds'), r.get('grade'), r.get('score'),
                           r.get('form'), '', r.get('h2h'), r.get('fanvote'), r.get('signals')])
    for p in sorted(glob.glob(os.path.join(R, f'matches_{day}_*.json'))):
        name = os.path.basename(p)[len(f'matches_{day}_'):-5]
        d = _load(p) or {}
        ms = d.get('matches') if isinstance(d, dict) else None
        if not isinstance(ms, list):
            continue
        for m in ms:
            if not m.get('qualifies'):
                continue
            if name.endswith('_forebet'):
                pick = (m.get('scoring') or {}).get('pick')
                side = 'home' if pick == '1' else ('away' if pick == '2' else None)
                out['Forebet'].append(_row('Forebet', name[:-8], m, side))
            elif name.startswith('table_tennis'):
                side = m.get('focus') or ('away' if 'away' in name else 'home')
                out['Tenis stołowy'].append(_row('TT ' + side, 'table_tennis', m, side))
            else:
                side = m.get('focusTeam') or 'home'
                out['Sports'].append(_row('Sports ' + side.upper(), name, m, side))
    for p in sorted(glob.glob(os.path.join(ROOT, 'outputs', f'oddssafari_dropping_{day}_*.json'))):
        d = _load(p) or {}
        for m in d.get('qualified') or []:
            out['Dropping'].append(['Dropping', m.get('sport'), m.get('event_time'),
                                    f"{m.get('home_team')} vs {m.get('away_team')}", m.get('league'),
                                    m.get('home_team') if m.get('outcome') == '1' else
                                    (m.get('away_team') if m.get('outcome') == '2' else 'X'),
                                    m.get('current_odds'), '', '',
                                    f"spadek {m.get('open_odds')}→{m.get('current_odds')} ({m.get('drop_pct')}%)",
                                    '', '', '', m.get('match_url')])
    for k in out:
        out[k].sort(key=lambda r: str(r[2] or '99:99'))
    return out


def ai_summary(day: str, data: Dict[str, List[List[Any]]]) -> str:
    try:
        import groq_client
    except Exception:
        return 'AI niedostępne.'
    counts = {k: len(v) for k, v in data.items()}
    top = '\n'.join(f"- {r[1]} {r[2]} {r[3]}: {r[5]} @ {r[6]} (grade {r[7]}, {r[13]})"
                    for r in data['TOP'][:25]) or '(brak)'
    prompt = (f"Jesteś analitykiem zakładów sportowych. Dzień {day}. Liczby zakwalifikowanych "
              f"typów per workflow: {counts}.\nPerełki TOP (typ dominuje we wszystkich danych):\n{top}\n\n"
              "Napisz po polsku krótkie podsumowanie dnia (5–8 zdań): które TOP wyglądają "
              "najmocniej i dlaczego, na co uważać (niskie kursy, mało danych, ligi kobiece/niższe), "
              "i propozycję 1 kuponu AKO3 z TOP. Bez obietnic wygranej, rzeczowo.")
    try:
        txt = groq_client.chat(prompt, max_tokens=700, temperature=0.3)
        return txt or 'AI nie odpowiedziało (limity).'
    except Exception as e:
        return f'AI błąd: {type(e).__name__}'


def write_xlsx(day: str, data, summary: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = 'Podsumowanie'
    ws.append([f'Podsumowanie dnia {day}'])
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(['Workflow', 'Zakwalifikowane'])
    for k, v in data.items():
        ws.append([k, len(v)])
    ws.append([])
    ws.append(['Komentarz AI'])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.append([summary])
    c = ws.cell(ws.max_row, 1)
    c.alignment = Alignment(wrap_text=True, vertical='top')
    ws.merge_cells(start_row=ws.max_row, start_column=1, end_row=ws.max_row, end_column=8)
    ws.row_dimensions[ws.max_row].height = 260
    ws.column_dimensions['A'].width = 22
    fill = PatternFill('solid', fgColor='FFD966')
    widths = (12, 11, 7, 38, 18, 24, 7, 7, 7, 30, 12, 7, 9, 40)
    for name, rows in data.items():
        sh = wb.create_sheet(name[:31])
        sh.append(COLS if name != 'TOP' else COLS[:-1] + ['Sygnały'])
        for cell in sh[1]:
            cell.font, cell.fill = Font(bold=True), fill
        for r in rows:
            sh.append(r)
        sh.freeze_panes = 'A2'
        sh.auto_filter.ref = sh.dimensions
        for i, w in enumerate(widths):
            sh.column_dimensions[chr(65 + i)].width = w
    out = os.path.join(ROOT, 'results', f'digest_{day}.xlsx')
    wb.save(out)
    return out


def send(day: str, xlsx: str, data, summary: str) -> None:
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from html import escape
    to, frm, pw = os.getenv('EMAIL_RECIPIENT'), os.getenv('EMAIL_SENDER'), os.getenv('EMAIL_PASSWORD')
    if not (to and frm and pw):
        print('   ℹ️ brak EMAIL_* — mail pominięty')
        return
    rows = ''.join(f"<tr><td>{escape(k)}</td><td>{len(v)}</td></tr>" for k, v in data.items())
    html = (f"<h2>📊 Podsumowanie dnia — {day}</h2><table border='1' cellpadding='5' "
            f"style='border-collapse:collapse'><tr><th>Workflow</th><th>Zakwalifikowane</th></tr>{rows}</table>"
            f"<h3>🤖 Komentarz AI</h3><p style='white-space:pre-wrap'>{escape(summary)}</p>"
            f"<p>Pełna lista we wszystkich zakładkach w załączniku <b>{os.path.basename(xlsx)}</b>.</p>")
    msg = MIMEMultipart()
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    part = MIMEApplication(open(xlsx, 'rb').read(), Name=os.path.basename(xlsx))
    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(xlsx)}"'
    msg.attach(part)
    msg['Subject'] = f"📊 Podsumowanie dnia {day} — TOP {len(data['TOP'])}, razem {sum(len(v) for v in data.values())}"
    msg['From'], msg['To'] = frm, to
    with smtplib.SMTP('smtp.gmail.com', 587) as s:
        s.starttls()
        s.login(frm, pw)
        s.sendmail(frm, [x.strip() for x in to.split(',')], msg.as_string())
    print('   ✅ Mail z podsumowaniem wysłany')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    day = args[0] if args else date.today().isoformat()
    data = collect(day)
    print('📊', {k: len(v) for k, v in data.items()})
    summary = ai_summary(day, data)
    print('🤖', summary[:300])
    xlsx = write_xlsx(day, data, summary)
    print('📁', xlsx)
    if '--email' in sys.argv:
        send(day, xlsx, data, summary)
