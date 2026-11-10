"""Osobny mail „🗳️ SofaScore Fan Favourites” z tablicy results/fanvote_<day>.json.

Wysyła tylko typy (status pick/watch), których jeszcze nie było w mailu danego
dnia (ledger outputs/fanfav_mail_sent_<day>.json) i które się nie zaczęły.
Ledger zapisywany dopiero po udanym SMTP. Główne maile pozostają bez zmian.

  python fan_favourites_email.py [--day D] [--days 2] [--force] [--dry-run --html out.html]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Iterable, List, Optional, Set

ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(ROOT, 'results')
OUTPUTS_DIR = os.path.join(ROOT, 'outputs')
SPORT_PL = {'football': 'Piłka nożna', 'basketball': 'Koszykówka', 'hockey': 'Hokej',
            'volleyball': 'Siatkówka', 'handball': 'Piłka ręczna', 'tennis': 'Tenis',
            'baseball': 'Baseball', 'rugby': 'Rugby', 'table_tennis': 'Tenis stołowy'}
SITE = 'https://pickly-dashboard.vercel.app/fan-favourites'


def ledger_path(day: str, outputs_dir: str = OUTPUTS_DIR) -> str:
    return os.path.join(outputs_dir, f'fanfav_mail_sent_{day}.json')


def load_ledger(path: str) -> Set[str]:
    try:
        with open(path, encoding='utf-8') as fh:
            return set(json.load(fh).get('sent') or [])
    except (OSError, ValueError, AttributeError):
        return set()


def save_ledger(path: str, ids: Iterable[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump({'sent': sorted(set(ids)),
                   'updatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
                  fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_board(day: str, results_dir: str = RESULTS_DIR) -> Dict[str, Any]:
    try:
        with open(os.path.join(results_dir, f'fanvote_{day}.json'), encoding='utf-8-sig') as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def _ko(p: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(p.get('kickoff')).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def select_new(board: Dict[str, Any], sent: Set[str], now: datetime) -> List[Dict[str, Any]]:
    out = []
    for sport, blk in (board.get('sports') or {}).items():
        w = blk.get('watch')
        for p in list(blk.get('picks') or []) + (list(w) if isinstance(w, list) else []):
            if p.get('status') not in ('pick', 'watch') or p.get('id') in sent:
                continue
            k = _ko(p)
            if k is not None and k <= now:
                continue
            out.append({**p, 'sport': p.get('sport') or sport})
    return out


def _sport_order(picks: List[Dict[str, Any]]) -> List[str]:
    cnt: Dict[str, int] = {}
    for p in picks:
        cnt[p['sport']] = cnt.get(p['sport'], 0) + 1
    return sorted(cnt, key=lambda s: (s != 'football', -cnt[s], s))


def _e(v: Any) -> str:
    return html.escape('' if v is None else str(v))


def _badge(pct: float) -> str:
    c = '#1b5e20' if pct >= 80 else '#2e7d32' if pct >= 70 else '#f9a825'
    return (f"<span style='background:{c};color:#fff;border-radius:12px;padding:2px 10px;"
            f"font-weight:bold'>{pct:.0f}%</span>")


def _chips(form: Optional[str]) -> str:
    col = {'W': '#2e7d32', 'D': '#9e9e9e', 'L': '#c62828'}
    return ''.join(f"<span style='display:inline-block;width:16px;text-align:center;color:#fff;"
                   f"background:{col.get(c, '#607d8b')};margin:0 1px;border-radius:3px;font-size:11px'>{_e(c)}</span>"
                   for c in (form or ''))


def _local(p: Dict[str, Any]) -> str:
    k = _ko(p)
    if not k:
        return _e(p.get('time') or '?')
    try:
        from zoneinfo import ZoneInfo
        return k.astimezone(ZoneInfo('Europe/Warsaw')).strftime('%d.%m %H:%M')
    except Exception:
        return k.strftime('%d.%m %H:%M UTC')


def _form_or_dash(form: Optional[str]) -> str:
    return _chips(form) if form else '—'


def _last_h2h(h: Dict[str, Any]) -> str:
    last = h.get('last')
    try:
        from h2h_summary import NO_H2H
    except Exception:
        NO_H2H = None
    if last and last != NO_H2H:
        return str(last)
    return ' '.join(str(x) for x in (h.get('lastDate'), h.get('lastScore')) if x) or '—'


def _last_match_txt(m: Any) -> str:
    if not isinstance(m, dict) or not (m.get('date') or m.get('result') or m.get('score')):
        return '—'
    return ' '.join(x for x in (_e(m.get('date')), _chips(m.get('result')), _e(m.get('score'))) if x)


def card(p: Dict[str, Any]) -> str:
    o = p.get('odds') or {}
    bp = p.get('bestPrice') or {}
    f = p.get('form') or {}
    h = p.get('h2h') or {}
    fb = p.get('forebet') or {}
    av = p.get('availability') or {}
    lim = p.get('limit') or {}
    edge = p.get('edgePct')
    ec = '#2e7d32' if (edge or 0) >= 0 else '#c62828'
    watch = (" <span style='color:#ef6c00'>(obserwowane, bez rekordu)</span>"
             if p.get('status') == 'watch' else '')
    links = ' · '.join(f"<a href='{_e(u)}'>{n}</a>" for n, u in (
        ('SofaScore', p.get('sofascoreUrl')), ('Forebet', p.get('forebetUrl')),
        ('Livesport', p.get('matchUrl')), ('Strona', SITE)) if u)
    mp = p.get('modelProb')
    opp = p.get('away') if p.get('side') == 'home' else p.get('home')
    if not opp:
        parts = str(p.get('match') or '').split(' vs ')
        opp = (parts[0] if p.get('team') == parts[-1] else parts[-1]) if len(parts) == 2 else 'rywal'
    lm = p.get('lastMatch') or {}
    return (
        "<div style='border:1px solid #d1c4e9;border-radius:10px;padding:10px;margin:8px 0;"
        "font-family:sans-serif;background:#faf8ff'>"
        f"<div>{_badge(float(p.get('fanPct') or 0))} <b>{_e(p.get('team'))}</b>{watch} "
        f"<small>({_e(p.get('votes'))} głosów)</small></div>"
        f"<div style='margin-top:4px'><b>{_e(p.get('match'))}</b> — {_e(p.get('league'))} · 🕒 {_local(p)}</div>"
        f"<div>Kursy 1/X/2: {_e(o.get('home'))} / {_e(o.get('draw') or '-')} / {_e(o.get('away'))}"
        f" · najlepszy: <b>{_e(bp.get('price'))}</b> {_e(bp.get('bookmaker') or '')}"
        + (f" (Pinnacle {_e(bp.get('pinnacle'))})" if bp.get('pinnacle') else '')
        + f" · limit ≥ {_e(lim.get('min'))}</div>"
        f"<div>Implied {_e(p.get('impliedPct'))}% · edge <b style='color:{ec}'>{_e(edge)}</b> pp</div>"
        f"<div>Forma {_e(p.get('team'))}: {_form_or_dash(f.get('overall'))}"
        f" · dom/wyjazd {_form_or_dash(f.get('venue'))}"
        + (f" · sezon {_chips(f.get('season'))}" if f.get('season') else '') + "</div>"
        f"<div>Forma {_e(opp)}: {_form_or_dash(f.get('opponentOverall'))}"
        f" · dom/wyjazd {_form_or_dash(f.get('opponentVenue'))}</div>"
        f"<div>H2H: {_e(h.get('line') or 'Brak bezpośrednich meczów')}</div>"
        f"<div>Ostatni H2H: {_e(_last_h2h(h))}</div>"
        f"<div>Ostatni mecz {_e(p.get('team'))}: {_last_match_txt(lm.get('team'))}</div>"
        f"<div>Ostatni mecz {_e(opp)}: {_last_match_txt(lm.get('opponent'))}</div>"
        f"<div>Forebet {_e(fb.get('prob'))}% typ {_e(fb.get('pick'))} wynik {_e(fb.get('exactScore'))}"
        f" · model {_e(round(mp * 100, 1) if isinstance(mp, (int, float)) else '-')}%"
        f" · Grade <b>{_e(p.get('grade'))}</b></div>"
        f"<div>Absencje: {_e(av.get('verdict'))} {_e(av.get('note'))}</div>"
        f"<div><small>{links}</small></div></div>")


def build_html(picks: List[Dict[str, Any]], days: List[str],
               boards: Dict[str, Dict[str, Any]]) -> str:
    parts = ["<div style='background:linear-gradient(90deg,#5e35b1,#7c4dff);color:#fff;"
             "padding:14px;border-radius:10px;font-family:sans-serif'>"
             f"<h2 style='margin:0'>🗳️ SofaScore Fan Favourites — {_e(', '.join(days))}</h2>"
             f"<div>Nowe typy: {len(picks)}</div></div>"]
    per = {s: [p for p in picks if p['sport'] == s] for s in _sport_order(picks)}
    if per:
        parts.append("<p style='font-family:sans-serif'>" + ' · '.join(
            f"{_e(SPORT_PL.get(s, s))}: {len(v)}" for s, v in per.items()) + "</p>")
    for d in days:
        b = boards.get(d) or {}
        tot: Dict[str, int] = {}
        for blk in (b.get('sports') or {}).values():
            for k, v in (blk.get('stats') or {}).items():
                if isinstance(v, (int, float)):
                    tot[k] = tot.get(k, 0) + int(v)
        if tot:
            parts.append(f"<p style='font-family:sans-serif;font-size:12px'>Lejek {_e(d)}: mecze {tot.get('rows', 0)}"
                         f" → z głosami {tot.get('withVote', 0)} → próg fanów i głosów {tot.get('fanOk', 0)}"
                         f" → poniżej limitu kursu {tot.get('belowLimit', 0)}, bez kursu {tot.get('noOdds', 0)}"
                         f" → pokazane {tot.get('picks', 0)}</p>")
    thr = (boards.get(days[0]) or {}).get('thresholds') or {}
    mv = thr.get('minVotes', 100)
    import fan_limits
    fp = thr.get('fanPct') or {}
    dr_min = fp.get('drawWithForm', fan_limits.FAN_MIN_1X2_WITH_FORM)
    df_min = fp.get('default', fan_limits.FAN_MIN_DEFAULT)
    parts.append(f"<p style='font-family:sans-serif;font-size:12px'>Progi: ≥ {_e(f'{df_min:g}')}%;"
                 f" sporty z remisem (1X2: piłka nożna, piłka ręczna) ≥ {_e(f'{dr_min:g}')}%"
                 f" gdy jest forma obu drużyn,"
                 f" ≥ {_e(mv)} głosów, standardowy limit kursu dla sportu.</p>")
    for s, v in per.items():
        v.sort(key=lambda p: (-(p.get('fanPct') or 0), -(p.get('votes') or 0)))
        parts.append(f"<h3 style='font-family:sans-serif;color:#5e35b1'>{_e(SPORT_PL.get(s, s))} ({len(v)})</h3>")
        parts.extend(card(p) for p in v)
    return ''.join(parts)


def write_xlsx(picks: List[Dict[str, Any]], path: str) -> Optional[str]:
    try:
        from openpyxl import Workbook
    except ImportError:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = 'Fan Favourites'
    cols = ['date', 'time', 'sport', 'league', 'match', 'team', 'fanPct', 'votes', 'status', 'odds',
            'bestPrice', 'edgePct', 'grade']
    ws.append(cols)
    for p in picks:
        o = p.get('odds') or {}
        ws.append([p.get('date'), p.get('time'), p.get('sport'), p.get('league'), p.get('match'),
                   p.get('team'), p.get('fanPct'), p.get('votes'), p.get('status'),
                   o.get(p.get('side')), (p.get('bestPrice') or {}).get('price'), p.get('edgePct'),
                   p.get('grade')])
    ws.auto_filter.ref = ws.dimensions
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)
    return path


def send(html_body: str, subject: str, to: str, sender: str, password: str,
         provider: str = 'gmail', attach: Optional[str] = None) -> bool:
    from dropping_odds_email import SMTP_CONFIG
    cfg = SMTP_CONFIG.get(provider, SMTP_CONFIG['gmail'])
    msg = MIMEMultipart()
    msg['Subject'], msg['From'], msg['To'] = subject, sender, to
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    if attach and os.path.exists(attach):
        part = MIMEApplication(open(attach, 'rb').read(), Name=os.path.basename(attach))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attach)}"'
        msg.attach(part)
    try:
        server = smtplib.SMTP(cfg['server'], cfg['port'], timeout=30)
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [x.strip() for x in to.split(',')], msg.as_string())
        server.quit()
        return True
    except Exception as e:  # noqa: BLE001
        print(f'❌ Mail SofaScore Fan Favourites nie wysłany: {type(e).__name__}: {e}')
        return False


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--day')
    ap.add_argument('--days', type=int, default=2)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--html')
    ap.add_argument('--to', default=os.getenv('EMAIL_RECIPIENT'))
    ap.add_argument('--from-email', default=os.getenv('EMAIL_SENDER'))
    ap.add_argument('--password', default=os.getenv('EMAIL_PASSWORD'))
    ap.add_argument('--provider', default='gmail')
    ap.add_argument('--results', default=RESULTS_DIR)
    ap.add_argument('--outputs', default=OUTPUTS_DIR)
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    d0 = datetime.strptime(a.day, '%Y-%m-%d').date() if a.day else now.date()
    days = [(d0 + timedelta(days=i)).isoformat() for i in range(max(1, a.days))]
    boards = {d: load_board(d, a.results) for d in days}
    picks: List[Dict[str, Any]] = []
    for d in days:
        sent = set() if a.force else load_ledger(ledger_path(d, a.outputs))
        picks += select_new(boards[d], sent, now)
    if not picks and not a.force:
        print('Fan Favourites: nic nowego — mail nie zostaje wysłany')
        return 0
    body = build_html(picks, days, boards)
    subject = f'🗳️ SofaScore Fan Favourites — {days[0]} ({len(picks)} nowych)' + (
        ' — wysyłka ręczna' if a.force else '')
    if a.dry_run:
        if a.html:
            with open(a.html, 'w', encoding='utf-8') as fh:
                fh.write(body)
        print(f'[dry-run] {subject}')
        return 0
    if not (a.to and a.from_email and a.password):
        print('ℹ️ Mail Fan Favourites pominięty (brak EMAIL_*)')
        return 0
    xlsx = write_xlsx(picks, os.path.join(a.outputs, f'fanfav_{days[0]}.xlsx'))
    if not send(body, subject, a.to, a.from_email, a.password, a.provider, xlsx):
        return 1
    for d in days:
        ids = [p['id'] for p in picks if p.get('date') == d or (p.get('id') or '').split('|')[1:2] == [d]]
        if ids:
            save_ledger(ledger_path(d, a.outputs), load_ledger(ledger_path(d, a.outputs)) | set(ids))
    print(f'✅ Mail SofaScore Fan Favourites wysłany ({len(picks)} typów)')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
