#!/usr/bin/env python3
"""Statyczna strona (GitHub Pages) z gotowych JSON-ów w results/.

Bez serwera i bazy: czyta top_<d>.json, ai_analyst_<d>.json, twierdza_<d>.json,
forebet_settled.json, watchdog_<d>.json i zapisuje site/index.html,
site/historia.html oraz archiwum site/dzien/<d>.html.

Użycie:  python tools/build_site.py [--results results] [--out site]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY_RE = re.compile(r'_(\d{4}-\d{2}-\d{2})\.json$')
ICONS = {'football': '⚽', 'tennis': '🎾', 'basketball': '🏀', 'hockey': '🏒',
         'handball': '🤾', 'volleyball': '🏐', 'baseball': '⚾', 'rugby': '🏉',
         'table_tennis': '🏓'}
SPORT_PL = {'football': 'Piłka nożna', 'tennis': 'Tenis', 'basketball': 'Koszykówka',
            'hockey': 'Hokej', 'handball': 'Piłka ręczna', 'volleyball': 'Siatkówka',
            'baseball': 'Baseball', 'rugby': 'Rugby', 'table_tennis': 'Tenis stołowy'}
SMALL_SAMPLE = 30
FOOTER = '18+ · Graj odpowiedzialnie · To nie jest porada finansowa'


def _load(path: str) -> Any:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get('picks') or data.get('items') or []
    return [r for r in (data or []) if isinstance(r, dict)]


def days_available(results: str) -> List[str]:
    days = set()
    for pat in ('top_*.json', 'ai_analyst_*.json', 'twierdza_*.json'):
        for p in glob.glob(os.path.join(results, pat)):
            m = DAY_RE.search(p)
            if m:
                days.add(m.group(1))
    return sorted(days)


def load_day(results: str, day: str) -> Dict[str, List[Dict[str, Any]]]:
    return {k: _rows(_load(os.path.join(results, f'{k}_{day}.json')))
            for k in ('top', 'ai_analyst', 'twierdza')}


# ---------- drobne wizualizacje ----------
def _e(v: Any) -> str:
    return escape('' if v is None else str(v))


def pills(text: Any) -> str:
    """Zamienia ciągi W/D/L (min. 3 znaki) na kolorowe pigułki, resztę escapuje."""
    out = []
    for tok in re.split(r'(\b[WDLwdl]{3,}\b)', '' if text is None else str(text)):
        if re.fullmatch(r'[WDLwdl]{3,}', tok):
            out.append('<span class="f">' + ''.join(
                f'<i class="{c}">{c}</i>' for c in tok.upper()) + '</span>')
        else:
            out.append(escape(tok))
    return ''.join(out)


def _pct(v: Any) -> Optional[int]:
    try:
        return max(0, min(100, int(round(float(str(v).strip().rstrip('%'))))))
    except (TypeError, ValueError):
        return None


def fan_bar(v: Any) -> str:
    p = _pct(v)
    if p is None:
        return ''
    return (f'<div class="fv" title="Fan Vote {p}%"><span>Fan Vote</span>'
            f'<b style="width:{p}%"></b><em>{p}%</em></div>')


def odds_badge(o: Any) -> str:
    try:
        f = float(o)
    except (TypeError, ValueError):
        return ''
    cls = 'lo' if f < 1.6 else ('mid' if f < 2.2 else 'hi')
    return f'<span class="odds {cls}">@ {f:.2f}</span>'


def stars(n: Any) -> str:
    try:
        n = max(0, min(5, int(n)))
    except (TypeError, ValueError):
        return ''
    return f'<span class="stars" aria-label="pewność {n}/5">{"★" * n}{"☆" * (5 - n)}</span>'


def _sport(s: Any) -> str:
    s = str(s or '')
    return f'{ICONS.get(s, "🏅")} {escape(SPORT_PL.get(s, s))}'


def _superbet(r: Dict[str, Any]) -> str:
    sb = r.get('superbet')
    url = r.get('superbetUrl') or (sb.get('url') if isinstance(sb, dict) else None)
    if not url or not str(url).startswith('https://superbet.pl/'):
        return ''
    return f'<a class="sb" href="{escape(str(url))}" rel="nofollow noopener" target="_blank">Superbet ↗</a>'


# ---------- karty ----------
def ai_card(r: Dict[str, Any]) -> str:
    v = str(r.get('verdict') or '').upper()
    cls = {'GRAJ': 'go', 'OBSERWUJ': 'watch', 'ODPUŚĆ': 'skip'}.get(v, 'watch')
    risks = ''.join(f'<li>{_e(x)}</li>' for x in (r.get('risks') or []) if x)
    return (f'<article class="card ai" data-sport="{_e(r.get("sport"))}" data-verdict="{_e(v)}">'
            f'<header><span class="badge {cls}">{_e(v)}</span>{stars(r.get("confidence"))}'
            f'<span class="sp">{_sport(r.get("sport"))}</span></header>'
            f'<h3>{_e(r.get("match"))}</h3>'
            f'<p class="pick">{_e(r.get("pick"))} {odds_badge(r.get("odds"))}'
            f'<small>{_e(r.get("source"))}</small></p>'
            f'<p>{_e(r.get("reason"))}</p>'
            + (f'<ul class="risks">{risks}</ul>' if risks else '') + '</article>')


def pick_card(r: Dict[str, Any], kind: str, verdict: str = '') -> str:
    form_lines = []
    if kind == 'TOP':
        form_lines.append(('Forma', r.get('form')))
    else:
        form_lines += [('Forma', r.get('form')), ('U siebie / wyjazd', r.get('venue'))]
    form_lines += [('Blok formy', r.get('formBlock')), ('Sezon', r.get('seasonForm'))]
    rows = ''.join(f'<div><dt>{escape(k)}</dt><dd>{pills(v)}</dd></div>'
                   for k, v in form_lines if v)
    extra = ''
    if r.get('h2h'):
        extra += f'<div><dt>H2H</dt><dd>{_e(r.get("h2h"))}</dd></div>'
    if r.get('forebet'):
        extra += f'<div><dt>Forebet</dt><dd>{_e(r.get("forebet"))}%</dd></div>'
    if r.get('signals'):
        extra += f'<div><dt>Sygnały</dt><dd>{_e(r.get("signals"))}</dd></div>'
    inj = r.get('injuryLine')
    if inj:
        extra += f'<div><dt>Absencje</dt><dd>{_e(inj)}</dd></div>'
    grade = _e(r.get('grade'))
    return (f'<article class="card" data-sport="{_e(r.get("sport"))}" data-verdict="{_e(verdict)}">'
            f'<header><span class="time">{_e(r.get("time"))}</span>'
            f'<span class="sp">{_sport(r.get("sport"))}</span>'
            f'<span class="lg">{_e(r.get("league"))}</span>'
            f'<span class="grade g{grade}">{grade}</span></header>'
            f'<h3>{_e(r.get("match"))}</h3>'
            f'<p class="pick">{_e(r.get("pick"))} {odds_badge(r.get("odds"))}</p>'
            f'<dl>{rows}{extra}</dl>{fan_bar(r.get("fanvote"))}{_superbet(r)}</article>')


# ---------- rozliczenia ----------
def _sides(match: Any) -> Tuple[str, str]:
    parts = str(match or '').split(' vs ', 1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ('', '')


def settle(day: str, r: Dict[str, Any], settled: Dict[str, Any]) -> Optional[Tuple[bool, float]]:
    home, away = _sides(r.get('match'))
    rec = settled.get(f'{day}|{r.get("sport")}|{home}|{away}')
    if not isinstance(rec, dict) or rec.get('status') != 'settled':
        return None
    pick = str(r.get('pick') or '').strip()
    side = 'home' if pick == home else ('away' if pick == away else None)
    try:
        odds = float(r.get('odds'))
    except (TypeError, ValueError):
        return None
    if side is None or odds <= 1:
        return None
    hit = rec.get('winner') == side
    return hit, round(odds - 1 if hit else -1.0, 4)


def history(results: str, days: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    settled = _load(os.path.join(results, 'forebet_settled.json')) or {}
    cats: Dict[str, List[Dict[str, Any]]] = {'TOP': [], 'Twierdza': [], 'AI GRAJ': []}
    for d in days:
        data = load_day(results, d)
        sources = {'TOP': data['top'], 'Twierdza': data['twierdza'],
                   'AI GRAJ': [r for r in data['ai_analyst']
                               if str(r.get('verdict') or '').upper() == 'GRAJ']}
        for cat, rows in sources.items():
            n = hits = 0
            profit = 0.0
            for r in rows:
                s = settle(d, r, settled)
                if s:
                    n += 1
                    hits += s[0]
                    profit += s[1]
            if n:
                cats[cat].append({'day': d, 'n': n, 'hits': hits, 'profit': round(profit, 2)})
    return cats


def svg_chart(series: List[Dict[str, Any]]) -> str:
    if not series:
        return ''
    cum, acc = [], 0.0
    for s in series:
        acc += s['profit']
        cum.append(acc)
    w, h, pad = 320, 120, 8
    lo, hi = min(0.0, *cum), max(0.0, *cum)
    span = (hi - lo) or 1.0
    step = (w - 2 * pad) / max(1, len(cum) - 1)
    y = lambda v: h - pad - (v - lo) / span * (h - 2 * pad)  # noqa: E731
    pts = ' '.join(f'{pad + i * step:.1f},{y(v):.1f}' for i, v in enumerate(cum))
    col = '#3ddc84' if cum[-1] >= 0 else '#ff5c6c'
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Skumulowany zysk {cum[-1]:+.2f} j.">'
            f'<line x1="0" x2="{w}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#555" stroke-dasharray="4"/>'
            f'<polyline fill="none" stroke="{col}" stroke-width="2.5" points="{pts}"/></svg>')


def history_html(cats: Dict[str, List[Dict[str, Any]]]) -> str:
    out = []
    for cat, series in cats.items():
        n = sum(s['n'] for s in series)
        hits = sum(s['hits'] for s in series)
        profit = sum(s['profit'] for s in series)
        if not n:
            out.append(f'<section class="hist"><h2>{escape(cat)}</h2>'
                       f'<p class="warn">Brak rozliczonych typów.</p></section>')
            continue
        warn = (f'<p class="warn">⚠️ Mała próba ({n} typów) — wyniki mogą być przypadkowe.</p>'
                if n < SMALL_SAMPLE else '')
        rows, acc = [], 0.0
        for s in series:
            acc += s['profit']
            rows.append(f'<tr><td>{s["day"]}</td><td>{s["hits"]}/{s["n"]}</td>'
                        f'<td>{100 * s["hits"] / s["n"]:.0f}%</td>'
                        f'<td class="{"pos" if s["profit"] >= 0 else "neg"}">{s["profit"]:+.2f}</td>'
                        f'<td>{acc:+.2f}</td></tr>')
        out.append(
            f'<section class="hist"><h2>{escape(cat)}</h2>{warn}'
            f'<div class="kpi"><div><b>{hits}/{n}</b><span>trafione</span></div>'
            f'<div><b>{100 * hits / n:.1f}%</b><span>skuteczność</span></div>'
            f'<div><b class="{"pos" if profit >= 0 else "neg"}">{100 * profit / n:+.1f}%</b>'
            f'<span>ROI (stawka 1 j.)</span></div></div>{svg_chart(series)}'
            f'<table><thead><tr><th>Dzień</th><th>Traf.</th><th>%</th><th>Zysk</th>'
            f'<th>Narast.</th></tr></thead><tbody>{"".join(reversed(rows))}</tbody></table></section>')
    return ''.join(out)


# ---------- strona ----------
CSS = """
:root{--bg:#0e1116;--card:#171b22;--line:#262c36;--tx:#e6e9ef;--mut:#8b93a1;--ac:#5b8cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--ac)}nav{position:sticky;top:0;z-index:2;display:flex;gap:.5rem;padding:.6rem 1rem;
background:#0b0e12ee;border-bottom:1px solid var(--line)}nav a{text-decoration:none;padding:.3rem .7rem;
border-radius:99px;color:var(--tx)}nav a.on{background:var(--ac);color:#fff}
main{max-width:1100px;margin:0 auto;padding:1rem}h2{margin:1.4rem 0 .6rem}
.grid{display:grid;gap:.8rem;grid-template-columns:repeat(auto-fill,minmax(290px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:.8rem 1rem}
.card header{display:flex;flex-wrap:wrap;gap:.45rem;align-items:center;font-size:.85rem;color:var(--mut)}
.card h3{margin:.45rem 0 .25rem;font-size:1.02rem}.pick{margin:.2rem 0 .5rem;font-weight:600}
.pick small{margin-left:.4rem;color:var(--mut);font-weight:400}
.time{font-weight:700;color:var(--tx)}.lg{opacity:.8}
.badge{padding:.12rem .55rem;border-radius:6px;font-weight:700;font-size:.78rem;color:#000}
.go{background:#3ddc84}.watch{background:#ffc94d}.skip{background:#ff5c6c}
.stars{color:#ffc94d;letter-spacing:1px}.grade{margin-left:auto;padding:.05rem .5rem;border-radius:6px;
background:#333;color:#fff;font-weight:700}.gA{background:#1f9d55}.gB{background:#3069d6}.gC{background:#8a6d1a}
.odds{padding:.08rem .45rem;border-radius:6px;font-size:.85rem}.odds.lo{background:#1f3b2b;color:#7ff0ad}
.odds.mid{background:#3a3315;color:#ffd866}.odds.hi{background:#40202a;color:#ff9aa8}
dl{margin:0;display:grid;gap:.25rem;font-size:.86rem}dl div{display:flex;gap:.5rem}
dt{color:var(--mut);min-width:6.5rem}dd{margin:0}
.f{display:inline-flex;gap:2px;vertical-align:middle}.f i{font-style:normal;font-size:.7rem;font-weight:700;
width:1.15rem;height:1.15rem;display:grid;place-items:center;border-radius:4px;color:#000}
.f .W{background:#3ddc84}.f .D{background:#c9ced6}.f .L{background:#ff5c6c}
.fv{position:relative;margin-top:.55rem;height:1.25rem;background:#262c36;border-radius:99px;overflow:hidden;
font-size:.75rem}.fv b{position:absolute;inset:0 auto 0 0;background:linear-gradient(90deg,#3069d6,#5b8cff)}
.fv span,.fv em{position:relative;padding:0 .6rem;line-height:1.25rem;font-style:normal}.fv em{float:right}
.risks{margin:.3rem 0 0;padding-left:1.1rem;color:#ffb3bb;font-size:.85rem}
.sb{display:inline-block;margin-top:.5rem;font-size:.85rem}
.filters{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0}.filters button{background:var(--card);
color:var(--tx);border:1px solid var(--line);border-radius:99px;padding:.3rem .75rem;cursor:pointer}
.filters button.on{background:var(--ac);border-color:var(--ac)}
.warn{color:#ffc94d}.kpi{display:flex;gap:.8rem;flex-wrap:wrap}.kpi div{background:var(--card);
border:1px solid var(--line);border-radius:12px;padding:.5rem .9rem}.kpi b{display:block;font-size:1.25rem}
.kpi span{color:var(--mut);font-size:.8rem}.pos{color:#3ddc84}.neg{color:#ff5c6c}
.chart{width:100%;max-width:520px;height:auto;margin:.6rem 0;background:var(--card);border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:.88rem}td,th{padding:.35rem;border-bottom:1px solid var(--line);
text-align:left}.empty{color:var(--mut)}.arch a{margin-right:.6rem}
footer{max-width:1100px;margin:2rem auto;padding:1rem;color:var(--mut);font-size:.85rem;
border-top:1px solid var(--line)}
"""

JS = """
(function(){var s='',v='';function ap(){document.querySelectorAll('.card').forEach(function(c){
var ok=(!s||c.dataset.sport===s)&&(!v||c.dataset.verdict===v);c.style.display=ok?'':'none';});}
document.querySelectorAll('.filters button').forEach(function(b){b.addEventListener('click',function(){
var k=b.dataset.k;b.parentNode.querySelectorAll('button').forEach(function(x){x.classList.remove('on');});
b.classList.add('on');if(k==='s')s=b.dataset.v;else v=b.dataset.v;ap();});});})();
"""


def page(title: str, body: str, active: str, stamp: str, base: str = '') -> str:
    nav = ''.join(f'<a href="{base}{href}" class="{"on" if key == active else ""}">{label}</a>'
                  for key, href, label in (('dzis', 'index.html', 'Dziś'),
                                           ('hist', 'historia.html', 'Historia skuteczności')))
    return (f'<!doctype html><html lang="pl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{escape(title)}</title>'
            f'<style>{CSS}</style></head><body><nav>{nav}</nav><main>{body}</main>'
            f'<footer>{FOOTER}<br>Dane: {escape(stamp)}</footer><script>{JS}</script></body></html>')


def _filters(cards: List[Dict[str, Any]]) -> str:
    sports = sorted({str(r.get('sport')) for r in cards if r.get('sport')})
    sb = ''.join(f'<button data-k="s" data-v="{escape(s)}">{ICONS.get(s, "🏅")} '
                 f'{escape(SPORT_PL.get(s, s))}</button>' for s in sports)
    vb = ''.join(f'<button data-k="v" data-v="{v}">{v}</button>' for v in ('GRAJ', 'OBSERWUJ', 'ODPUŚĆ'))
    return (f'<div class="filters"><button class="on" data-k="s" data-v="">Wszystkie</button>{sb}</div>'
            f'<div class="filters"><button class="on" data-k="v" data-v="">Każdy werdykt</button>{vb}</div>')


def day_body(day: str, data: Dict[str, List[Dict[str, Any]]], days: List[str], base: str = '') -> str:
    verdicts = {(r.get('match'), r.get('pick')): str(r.get('verdict') or '').upper()
                for r in data['ai_analyst']}
    sec = lambda t, inner: (f'<h2>{t}</h2>' + (f'<div class="grid">{inner}</div>' if inner  # noqa: E731
                                                else '<p class="empty">Brak danych.</p>'))
    body = f'<h1>Typy na {escape(day)} <small class="empty">(czas: Europe/Warsaw)</small></h1>'
    body += _filters(data['ai_analyst'] + data['top'] + data['twierdza'])
    body += sec('🤖 Analityk AI', ''.join(ai_card(r) for r in data['ai_analyst']))
    body += sec('⭐ TOP', ''.join(pick_card(r, 'TOP', verdicts.get((r.get('match'), r.get('pick')), ''))
                                 for r in data['top']))
    body += sec('🏰 Twierdza', ''.join(pick_card(r, 'TW', verdicts.get((r.get('match'), r.get('pick')), ''))
                                      for r in data['twierdza']))
    links = ''.join(f'<a href="{base}dzien/{d}.html">{d}</a>' for d in reversed(days))
    body += f'<h2>Archiwum</h2><p class="arch">{links or "—"}</p>'
    return body


def _stamp(results: str, day: Optional[str]) -> str:
    wd = _load(os.path.join(results, f'watchdog_{day}.json')) if day else None
    if isinstance(wd, dict) and wd.get('generated_at'):
        return str(wd['generated_at'])
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def build(results: str, out: str) -> List[str]:
    days = days_available(results)
    today = days[-1] if days else None
    stamp = _stamp(results, today)
    os.makedirs(os.path.join(out, 'dzien'), exist_ok=True)
    written = []

    def w(rel: str, html: str) -> None:
        p = os.path.join(out, rel)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(html)
        written.append(p)

    if today:
        w('index.html', page(f'Typy {today}', day_body(today, load_day(results, today), days),
                             'dzis', stamp))
    else:
        w('index.html', page('Typy', '<h1>Brak danych</h1><p class="empty">Brak plików w results/.</p>',
                             'dzis', stamp))
    w('historia.html', page('Historia skuteczności',
                            '<h1>Historia skuteczności</h1><p class="empty">Rozliczenia z forebet_settled.json, '
                            'stawka 1 j. na typ, typy bez kursu lub wyniku pominięte.</p>'
                            + history_html(history(results, days)), 'hist', stamp))
    for d in days:
        w(f'dzien/{d}.html', page(f'Typy {d}', day_body(d, load_day(results, d), days, '../'),
                                  'dzis', stamp, '../'))
    with open(os.path.join(out, '.nojekyll'), 'w') as f:
        f.write('')
    return written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--results', default=os.path.join(ROOT, 'results'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'site'))
    a = ap.parse_args()
    print(f'🌐 zapisano {len(build(a.results, a.out))} stron do {a.out}')


if __name__ == '__main__':
    main()
