"""Ochrona przed nieaktualnymi danymi (poprzedni sezon).

Czyste funkcje, bez I/O i bez zależności poza stdlib:

* wiek H2H: spotkania starsze niż ~24 mies. są ignorowane, 12–24 mies. liczą
  się w połowie (``effective_h2h``),
* forma sezonowa: widok formy tylko z bieżącego sezonu, liczony z datowanych
  wierszy Livesport — DODATKOWO, istniejąca forma (ostatnie 5) się nie zmienia
  (``apply_season``),
* bramka rynkowa: Forebet > rynek o więcej niż 20 pp → ``stale_model``
  (``market_gap_pp``, ``lower_grade_if_stale``).

Żadna funkcja nie rzuca wyjątku na złe dane wejściowe.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

H2H_IGNORE_DAYS = 730
H2H_HALF_DAYS = 365
SEASON_GAP_DAYS = 35
FORM_FALLBACK_DAYS = 60
SEASON_MAX_DAYS = 365
EARLY_SEASON_MIN = 4
CONFLICT_OVERALL_MIN_W = 3
CONFLICT_SEASON_MAX_W = 1
CONFLICT_SEASON_MIN_N = 3
STALE_MODEL_PP = 20.0
NAME_MATCH_MIN = 0.5
DRAW_SPORTS = {'football', 'handball', 'hockey', 'rugby'}
# Forebet zawsze 1X2 → rynek trójdrogowy. Pozostałe (hokej, rugby) tylko gdy
# Forebet podaje drawProb.
THREE_WAY_SPORTS = {'football', 'handball'}
GRADE_ORDER = ['A', 'B', 'C', 'D', 'F']

_DATE_RE = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?:\s+\d{1,2}:\d{2})?$')


def parse_ls_date(text: Any) -> Optional[date]:
    """``DD.MM.YYYY`` / ``DD.MM.YY`` (opcjonalnie z godziną) → date, inaczej None."""
    if not isinstance(text, str):
        return None
    t = text.strip().rstrip('.').strip()
    m = _DATE_RE.match(t)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
    if len(y) == 4:
        year = int(y)
    else:
        # Pivot jak _parse_h2h_date: YY > bieżący YY + 1 → 19YY (np. '99' → 1999).
        yy = int(y)
        year = 1900 + yy if yy > (date.today().year % 100) + 1 else 2000 + yy
    try:
        return date(year, mo, d)
    except ValueError:
        return None


def h2h_weight(d: Optional[date], today: date) -> Optional[float]:
    """Waga spotkania H2H wg wieku: >730 dni → 0, >365 → 0.5, inaczej 1."""
    if d is None:
        return None
    age = (today - d).days
    if age > H2H_IGNORE_DAYS:
        return 0.0
    if age > H2H_HALF_DAYS:
        return 0.5
    return 1.0


def name_overlap(a: str, b: str) -> float:
    # Bez importu: gdy forebet_pipeline działa jako __main__, import po nazwie
    # wykonałby jego kod drugi raz. Bierzemy matcher z już załadowanego modułu.
    import sys
    for mod_name in ('forebet_pipeline', '__main__'):
        fn = getattr(sys.modules.get(mod_name), '_name_overlap', None)
        if callable(fn):
            try:
                return float(fn(a or '', b or ''))
            except Exception:
                break
    ta = set(re.findall(r'\w+', (a or '').lower()))
    tb = set(re.findall(r'\w+', (b or '').lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def effective_h2h(row: Dict[str, Any], today: date) -> Optional[dict]:
    """Ważone wiekiem H2H; None gdy brak listy lub żadne spotkanie nie ma daty.

    Spotkanie bez daty liczy się z wagą 1.0 (jak dotąd), datowane są starzone.
    """
    h2h = row.get('h2h_last5')
    if not isinstance(h2h, list) or not h2h:
        return None
    entries = []
    dated = 0
    for e in h2h:
        if not isinstance(e, dict):
            return None
        w = h2h_weight(parse_ls_date(e.get('date')), today)
        if w is None:
            w = 1.0
        else:
            dated += 1
        entries.append((e, w))
    if dated == 0:
        return None
    home_team = row.get('home_team') or ''
    away_team = row.get('away_team') or ''
    count = home_w = away_w = 0.0
    ignored = 0
    used = 0
    for e, w in entries:
        winner = e.get('winner')
        if winner in ('home', 'away'):
            wname = e.get('home') if winner == 'home' else e.get('away')
            oh = name_overlap(wname or '', home_team)
            oa = name_overlap(wname or '', away_team)
            if oh >= NAME_MATCH_MIN and oh >= oa:
                home_w += w
            elif oa >= NAME_MATCH_MIN and oa >= oh:
                away_w += w
            else:
                # Zwycięzca nie pasuje do żadnej z obecnych drużyn → spotkanie
                # pominięte (nieznane = neutralne), nie liczy się jako porażka.
                continue
        used += 1
        count += w
        if w == 0:
            ignored += 1
    fav_away = row.get('favorite') == 'away'
    return {
        'count': count,
        'fav_wins': away_w if fav_away else home_w,
        'opp_wins': home_w if fav_away else away_w,
        'home_wins': home_w,
        'away_wins': away_w,
        'ignored': ignored,
        'fresh': used - ignored,
        'unattributed': len(entries) - used,
        'all_stale': used > 0 and count == 0,
    }


def season_start(dated: List[dict], today: date) -> Tuple[date, str]:
    """Start sezonu: pierwsza przerwa >35 dni (od najnowszych), inaczej dziś−60."""
    floor = today - timedelta(days=SEASON_MAX_DAYS)
    start, method = today - timedelta(days=FORM_FALLBACK_DAYS), '60d'
    ds = [e.get('date') for e in (dated or []) if isinstance(e, dict)
          and isinstance(e.get('date'), date)]
    for newer, older in zip(ds, ds[1:]):
        if (newer - older).days > SEASON_GAP_DAYS:
            start, method = newer, 'gap'
            break
    return max(start, floor), method


def season_view(dated_raw: Any, start: date) -> Optional[List[str]]:
    """Wyniki z datą >= start (najnowsze pierwsze); None gdy nic nie ma daty."""
    if not isinstance(dated_raw, list):
        return None
    parsed = []
    for e in dated_raw:
        if not isinstance(e, dict):
            continue
        d = parse_ls_date(e.get('date'))
        # Sparingi to nie mecze sezonu — poza widokiem i licznikiem.
        if d is not None and not is_friendly(e.get('event')):
            parsed.append((d, e.get('result')))
    if not parsed:
        return None
    return [r for d, r in parsed if d >= start]


def wins(form: Any) -> int:
    return sum(1 for r in (form or []) if r == 'W')


def season_conflict(overall: Any, season: Optional[List[str]]) -> bool:
    overall = list(overall or [])
    return (len(overall) >= CONFLICT_OVERALL_MIN_W
            and wins(overall) >= CONFLICT_OVERALL_MIN_W
            and season is not None
            and len(season) >= CONFLICT_SEASON_MIN_N
            and wins(season) <= CONFLICT_SEASON_MAX_W)


def _odd(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 1.0 else None


def implied_probs(row: Dict[str, Any]) -> Optional[dict]:
    """Prawdopodobieństwa rynkowe z kursów bukmachera (bez marży)."""
    h, d, a = _odd(row.get('home_odds')), _odd(row.get('draw_odds')), _odd(row.get('away_odds'))
    if h is None or a is None:
        return None
    # Remis w normalizacji tylko gdy Forebet też podaje remis (rynek 1X2).
    # Bez remisu w Forebet porównujemy z rynkiem warunkowym 'bez remisu':
    # P(home | nie remis) = (1/h) / (1/h + 1/a) — ta sama przestrzeń zdarzeń
    # co dwudrogowe prawdopodobieństwo Forebet (kurs remisu nie zmienia wyniku).
    # Hokej/rugby w Forebet są dwudrogowe (drawProb = None) → porównanie
    # dwudrogowe nawet gdy bukmacher ma kurs na remis.
    sport = str(row.get('sport') or '').lower()
    if sport in THREE_WAY_SPORTS or row.get('forebet_draw_prob') is not None:
        if d is None:
            return None
        odds = {'home': h, 'draw': d, 'away': a}
    else:
        odds = {'home': h, 'away': a}
    total = sum(1.0 / o for o in odds.values())
    return {k: (1.0 / o) / total for k, o in odds.items()}


def market_gap_pp(row: Dict[str, Any]) -> Optional[float]:
    fav = row.get('favorite')
    if fav not in ('home', 'away'):
        return None
    try:
        prob = float(row.get('forebet_fav_prob'))
    except (TypeError, ValueError):
        return None
    if prob != prob or prob < 0 or prob > 100:
        return None
    imp = implied_probs(row)
    if imp is None:
        return None
    return prob - 100.0 * imp[fav]


def lower_grade_if_stale(row: Dict[str, Any]) -> None:
    """Obniż ocenę o jeden poziom dla ``stale_model`` (idempotentnie).

    Najniżej do D: F nie trafia do żadnego maila (A/B, C/D), a mecz ma nie być
    odrzucany.
    """
    if row.get('stale_model') is not True or 'prediction_grade_raw' in row:
        return
    g = row.get('prediction_grade')
    if g not in ('A', 'B', 'C'):
        return
    row['prediction_grade_raw'] = g
    row['prediction_grade'] = GRADE_ORDER[GRADE_ORDER.index(g) + 1]


_VIEWS = (
    ('home_form_dated', 'home_form'),
    ('away_form_dated', 'away_form'),
    ('home_form_home_dated', 'home_form_home'),
    ('away_form_away_dated', 'away_form_away'),
)


def _parsed(raw: List[dict]) -> List[dict]:
    out = []
    for e in raw:
        d = parse_ls_date(e.get('date')) if isinstance(e, dict) else None
        # Sparingi nie wyznaczają startu sezonu (wypełniają przerwę letnią).
        if d is not None and not is_friendly(e.get('event')):
            out.append({'date': d, 'result': e.get('result')})
    return out


_FRIENDLY_RE = re.compile(r'towarzysk|sparing|friendl|club friendly', re.I)


def is_friendly(event: Any) -> bool:
    """Etykieta rozgrywek Livesport (span.h2h__event) oznacza mecz towarzyski."""
    return isinstance(event, str) and bool(_FRIENDLY_RE.search(event))


def apply_season(row: Dict[str, Any], today: date) -> None:
    """Dodaj widoki formy z bieżącego sezonu; istniejąca forma się nie zmienia."""
    raws: Dict[str, List[dict]] = {}
    for dk, fk in _VIEWS:
        raw = row.get(dk)
        raw = [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []
        form = row.get(fk)
        form = list(form) if isinstance(form, list) else []
        res = [e.get('result') for e in raw]
        k = min(len(res), len(form))
        if raw and (k == 0 or res[:k] != form[:k]):
            raw = []
            print(f"[recency] dated form mismatch {dk}")
        raws[dk] = raw

    start_h, method_h = season_start(_parsed(raws['home_form_dated']), today)
    start_a, method_a = season_start(_parsed(raws['away_form_dated']), today)

    views = {
        'home_season_form': season_view(raws['home_form_dated'], start_h),
        'away_season_form': season_view(raws['away_form_dated'], start_a),
        'season_home_form': season_view(raws['home_form_home_dated'], start_h),
        'season_away_form': season_view(raws['away_form_away_dated'], start_a),
    }
    for k, v in views.items():
        if v is not None:
            row[k] = v

    known = []
    for side, start, method in (('home', start_h, method_h), ('away', start_a, method_a)):
        v = views[f'{side}_season_form']
        if v is None:
            continue
        row[f'{side}_season_match_count'] = len(v)
        row[f'{side}_season_start'] = start.isoformat()
        row[f'{side}_season_method'] = method
        known.append(len(v))
    if known:
        row['season_match_count'] = min(known)
    smc = row.get('season_match_count') if known else None
    row['early_season'] = smc is not None and smc < EARLY_SEASON_MIN

    fav = row.get('favorite')
    if fav in ('home', 'away'):
        row['season_form_conflict'] = season_conflict(
            row.get(f'{fav}_form') or [], row.get(f'{fav}_season_form'))
    else:
        row['season_form_conflict'] = False

    # Wspólny schemat (bez sparingów, puchary, reprezentacje) z tych samych
    # datowanych wierszy — niezgodne z formą wiersze odrzucone wyżej.
    import form_schema
    saved = {dk: row.get(dk) for dk, _ in _VIEWS}
    for dk, _ in _VIEWS:
        row[dk] = raws[dk]
    form_schema.apply(row)
    for dk, v in saved.items():
        if v is None:
            row.pop(dk, None)
        else:
            row[dk] = v
