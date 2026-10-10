"""Kursy hurtowo z zakładki „Kursy" Livesport — jedno zapytanie na sport i dzień.

Strona https://www.livesport.com/pl/pilka-nozna/kursy/ ładuje kursy z feedu
``fo_{sport}_{dzień}_2_pl_1_0`` (sprawdzone w przeglądarce, 2026-10). Feed ma
id meczu (AA) i kursy 1/X/2 (XA/XB/XC, otwarcie YA/YB/YC) jednego bukmachera
(ODA). Nazwy drużyn bierzemy z feedu listy dnia ``f_{sport}_{dzień}_2_pl_1``
(AE = gospodarz, AF = gość) i łączymy po id.

Zastosowanie: wstępna bramka kursowa i kolejność przetwarzania przed
kosztownym wejściem na stronę meczu (~20–30 s na mecz). Piłka: ~1070 meczów
z kursami na ~1690 w dniu, w ~1 s.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

FEED_BASE = os.getenv('LIVESPORT_FEED_BASE', 'https://local-global.flashscore.ninja/2/x/feed/')
FEED_HEADERS = {'Referer': 'https://www.livesport.com/', 'x-fsign': 'SW9D1eZo'}

# Id sportów Livesport/Flashscore.
SPORT_IDS = {
    'football': 1, 'tennis': 2, 'basketball': 3, 'hockey': 4,
    'baseball': 6, 'handball': 7, 'rugby': 8, 'volleyball': 12,
}

_CACHE: Dict[tuple, List[Dict[str, Any]]] = {}


def _get(feed: str) -> str:
    from curl_cffi import requests as cr
    import time
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            r = cr.get(FEED_BASE + feed, headers=FEED_HEADERS, impersonate='chrome', timeout=25)
            if r.status_code == 200:
                return r.text
        except Exception as e:  # SSLError/timeout bywają chwilowe
            last = e
        time.sleep(1 + attempt)
    if last:
        raise last
    return ''


def _records(text: str) -> List[Dict[str, str]]:
    out = []
    for rec in text.split('~'):
        if not rec.startswith('AA÷'):
            continue
        d: Dict[str, str] = {}
        for kv in rec.split('¬'):
            if '÷' in kv:
                k, v = kv.split('÷', 1)
                d.setdefault(k, v)  # pierwsze wystąpienie (MG powtarza się)
        out.append(d)
    return out


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def day_index(sport: str, day: int) -> List[Dict[str, Any]]:
    """Mecze z kursami dla sportu i przesunięcia dnia (0 = dziś)."""
    key = (sport, day)
    if key in _CACHE:
        return _CACHE[key]
    rows: List[Dict[str, Any]] = []
    sid = SPORT_IDS.get(sport)
    if sid is not None and -1 <= day <= 7:
        try:
            from tools import coupon_builder as cb
            odds = {r['AA']: r for r in _records(_get(f'fo_{sid}_{day}_2_pl_1_0'))}
            for ev in _records(_get(f'f_{sid}_{day}_2_pl_1')):
                o = odds.get(ev.get('AA'))
                h, a = ev.get('AE'), ev.get('AF')
                if not o or not h or not a:
                    continue
                home, away = _f(o.get('XA')), _f(o.get('XC'))
                if not home or not away:
                    continue
                ts = ev.get('AD')
                start = (datetime.fromtimestamp(int(ts), timezone.utc).strftime('%Y-%m-%d')
                         if ts and ts.isdigit() else None)
                rows.append({'home': h, 'away': a, 'th': cb.name_tokens(h), 'ta': cb.name_tokens(a),
                             'start': start, 'event_id': ev.get('AA'),
                             'prices': {'home': home, 'draw': _f(o.get('XB')), 'away': away},
                             'bookmaker_id': o.get('ODA')})
            print(f"   📋 Livesport kursy {sport} (dzień {day:+d}): {len(rows)} meczów z kursami")
        except Exception as e:
            print(f"   ⚠️ Livesport kursy {sport} niedostępne: {type(e).__name__}")
    _CACHE[key] = rows
    return rows


_LOOKUP_CACHE: Dict[tuple, Optional[Dict[str, Any]]] = {}


def lookup(home: str, away: str, sport: str, date_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """Kursy względem NASZYCH stron (home/away) albo None. Wynik cache'owany."""
    key = (home, away, sport, date_str)
    if key not in _LOOKUP_CACHE:
        _LOOKUP_CACHE[key] = _lookup(home, away, sport, date_str)
    v = _LOOKUP_CACHE[key]
    return dict(v) if v else None


def _lookup(home: str, away: str, sport: str, date_str: Optional[str]) -> Optional[Dict[str, Any]]:
    try:
        from tools import coupon_builder as cb
    except Exception:
        return None
    today = datetime.now(timezone(timedelta(hours=2))).date()
    try:
        target = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else today
    except ValueError:
        target = today
    base = (target - today).days
    th, ta = cb.name_tokens(home), cb.name_tokens(away)
    best, best_s, flip = None, 0.0, False
    for day in (base, base + 1, base - 1):
        for ev in day_index(sport, day):
            d = min(cb._overlap(th, ev['th']), cb._overlap(ta, ev['ta']))
            r = min(cb._overlap(th, ev['ta']), cb._overlap(ta, ev['th']))
            s, f = (d, False) if d >= r else (r, True)
            if s > best_s:
                best, best_s, flip = ev, s, f
        if best_s >= 0.99:
            break
    if not best or best_s < 0.5:
        return None
    p = best['prices']
    h, a = (p['away'], p['home']) if flip else (p['home'], p['away'])
    return {'home_odds': h, 'draw_odds': p.get('draw'), 'away_odds': a,
            'bookmaker': f"Livesport (bukm. {best.get('bookmaker_id')})",
            'odds_source': 'livesport_bulk', 'reason': None}
