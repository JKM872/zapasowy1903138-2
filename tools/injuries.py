"""Absencje (kontuzje / zawieszenia) dla kandydatów TOP i Twierdzy.

Tylko dla kilkudziesięciu kandydatów dziennie — nie dla wszystkich meczów.
Zdarzenie SofaScore bierzemy z Fan Vote (już zweryfikowane przez
forebet_pipeline._verify_sofascore_event), a gdy go brak — szukamy i
weryfikujemy tak samo. Niezweryfikowane zdarzenie => brak absencji.
Każdy błąd => brak absencji; nigdy nie przerywa runu.

Pokrycie SofaScore (próbka 10.2026): piłka nożna, NBA. Hokej, ręczna,
koszykówka europejska — puste listy; siatkówka — brak lineups.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Miękki sygnał: typowana strona ma ≥2 brakujących kluczowych zawodników,
# albo ≥3 brakujących, gdy SofaScore nie daje informacji o „kluczowości”.
KEY_MISSING_RISK = 2
ANY_MISSING_RISK = 3
MAX_NAMES = 5
SPORTS = {'football', 'basketball'}

_cache: Dict[Tuple[str, str, str], Optional[Dict[str, Any]]] = {}
# (sport, home, away) -> (event_id, 'direct'|'reversed'), ustawiane przez Fan Vote.
events: Dict[Tuple[str, str, str], Tuple[int, str]] = {}


def remember_event(sport: str, home: str, away: str, event_id: int, orient: str) -> None:
    if event_id and orient in ('direct', 'reversed'):
        events[(sport, home or '', away or '')] = (int(event_id), orient)


def _resolve(sport: str, home: str, away: str, day: str) -> Optional[Tuple[int, str]]:
    k = (sport, home or '', away or '')
    if k in events:
        return events[k]
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import sofascore_scraper as ss
    from forebet_pipeline import _verify_sofascore_event
    eid = ss.search_event_via_api(home, away, sport=sport, date_str=day)
    if not eid:
        return None
    orient = _verify_sofascore_event(eid, home, away, date_str=day)
    if orient is None:
        return None
    events[k] = (int(eid), orient)
    return events[k]


def fetch(sport: str, home: str, away: str, day: str) -> Optional[Dict[str, Any]]:
    """{'home': [...], 'away': [...]} względem NASZYCH stron albo None."""
    k = (sport, home or '', away or '')
    if k in _cache:
        return _cache[k]
    res = None
    if sport in SPORTS:
        try:
            ev = _resolve(sport, home, away, day)
            if ev:
                import sofascore_scraper as ss
                mp = ss.get_missing_players(ev[0]) or {}
                if mp.get('available'):
                    h, a = list(mp.get('home') or []), list(mp.get('away') or [])
                    if ev[1] == 'reversed':
                        h, a = a, h
                    res = {'home': h, 'away': a}
        except Exception as e:
            print(f"   ⚠️ Absencje {home}: {type(e).__name__}")
            res = None
    _cache[k] = res
    return res


def _missing(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows or [] if r.get('type') != 'doubtful']


def side_risk(inj: Optional[Dict[str, Any]], side: str) -> bool:
    rows = _missing((inj or {}).get(side))
    if any(r.get('key') is not None for r in rows):
        return sum(1 for r in rows if r.get('key')) >= KEY_MISSING_RISK
    return len(rows) >= ANY_MISSING_RISK


def attach(m: Dict[str, Any], sport: str, day: str, side: str) -> None:
    """Zapisz w meczu injuries/injuryCounts/injury_risk (dla typowanej strony)."""
    if 'injuries' not in m:
        inj = fetch(sport, m.get('homeTeam') or '', m.get('awayTeam') or '', day)
        if inj is None:
            return
        m['injuries'] = inj
        m['injuryCounts'] = {s: len(_missing(inj[s])) for s in ('home', 'away')}
    if 'injuries' in m:
        m['injury_risk'] = side_risk(m['injuries'], side)


def excludes(m: Dict[str, Any], side: str) -> bool:
    """TOP odrzuca injury_risk tylko, gdy rywal ma MNIEJ braków."""
    if not m.get('injury_risk'):
        return False
    c = m.get('injuryCounts') or {}
    op = 'away' if side == 'home' else 'home'
    return (c.get(op) or 0) < (c.get(side) or 0)


def fields(m: Dict[str, Any]) -> Dict[str, Any]:
    """Pola do wiersza TOP/Twierdzy (puste, gdy brak danych)."""
    if 'injuries' not in m:
        return {}
    return {'injuries': m['injuries'], 'injuryCounts': m.get('injuryCounts'),
            'injury_risk': bool(m.get('injury_risk')),
            'injuryLine': line(m['injuries'], m.get('homeTeam'), m.get('awayTeam'))}


def line(inj: Optional[Dict[str, Any]], home: Any, away: Any) -> str:
    """'🩺 Absencje: A: X (kontuzja), Y (zawieszenie); B: Z (wątpliwy)' albo ''."""
    parts = []
    for side, team in (('home', home), ('away', away)):
        rows = (inj or {}).get(side) or []
        if not rows:
            continue
        names = ', '.join(f"{r.get('name')}{'*' if r.get('key') else ''} ({r.get('reason')})"
                          for r in rows[:MAX_NAMES])
        more = f" +{len(rows) - MAX_NAMES}" if len(rows) > MAX_NAMES else ''
        parts.append(f"{team}: {names}{more}")
    return ('🩺 Absencje: ' + '; '.join(parts)) if parts else ''
