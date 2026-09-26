#!/usr/bin/env python3
"""Audyt pipeline'u Forebet: czy typy wygrywają i czy dane są zdrowe.

Dwie części:

1. ROZLICZENIE — dla każdego zakwalifikowanego typu z minionych dni szuka
   wyniku w SofaScore, sprawdza, że to TEN mecz (obie drużyny + termin, tak
   samo jak przy kursach), i zapisuje wynik w ``results/forebet_settled.json``.
   Cache sprawia, że każdy mecz rozliczamy raz.

   Potem liczy trafność i ROI (stawka 1 jednostka, kurs z pliku) w podziale na:
   sport, formę faworyta, faworyt/underdog rynku, EV, klasę rynku (marża),
   próg score. Tylko tak widać, CO z tego, co trafia do maila, naprawdę działa.

2. KONTROLE ZDROWIA — automatycznie wykrywa klasy błędów, które wcześniej
   trzeba było wyłapywać ręcznie z maila i logów:
     - brak formy u zakwalifikowanych (tenis: 100%),
     - Forebet niezgodny z rynkiem (tenis: 48% = rzut monetą),
     - Fan Vote przeciw faworytowi Forebet przy zgodności z rynkiem,
     - nierozstrzygnięta orientacja stron,
     - zakwalifikowane z ujemnym EV,
     - duplikaty meczów,
     - Fan Vote nie działa w ogóle dla sportu,
     - brak_kursow dominujący w odrzuceniach.

Wynik: ``outputs/forebet_audit.md`` + ``$GITHUB_STEP_SUMMARY``.

Użycie:
    python tools/forebet_audit.py                 # rozliczenie + kontrole
    python tools/forebet_audit.py --no-settle     # tylko kontrole (bez sieci)
    python tools/forebet_audit.py --days 14 --max-settle 300
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:  # pragma: no cover
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS_DIR = os.path.join(ROOT, 'results')
SETTLED_PATH = os.path.join(RESULTS_DIR, 'forebet_settled.json')
# W results/, a nie outputs/ — outputs/* jest w .gitignore, więc raport nigdy
# nie trafiłby na main i nie dałoby się go przeczytać w repozytorium.
REPORT_PATH = os.path.join(ROOT, 'results', 'forebet_audit.md')

FILE_RE = re.compile(r'matches_(\d{4}-\d{2}-\d{2})_([a-z_]+)_forebet\.json$')

# Po tylu nieudanych próbach przestajemy szukać wyniku meczu — nie chcemy
# odpytywać w nieskończoność o mecz, którego SofaScore nie zna.
MAX_SETTLE_TRIES = 3

# Próbka, poniżej której nie wyciągamy wniosków z trafności. Przy 10 typach
# 60% trafień i 40% trafień to wciąż ten sam szum.
MIN_SAMPLE = 20


# ---------------------------------------------------------------------------
# Wczytywanie
# ---------------------------------------------------------------------------

def load_matches(days: int) -> List[Dict[str, Any]]:
    """Wszystkie zdarzenia z plików Forebet z ostatnich ``days`` dni."""
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    out: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(RESULTS_DIR, '*_forebet.json'))):
        m = FILE_RE.search(os.path.basename(path))
        if not m:
            continue
        date, sport = m.group(1), m.group(2)
        if date < cutoff:
            continue
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        rows = data.get('matches', data) if isinstance(data, dict) else data
        for r in rows or []:
            if isinstance(r, dict):
                r['_date'] = date
                r['_sport'] = sport
                _undo_legacy_swap(r)
                out.append(r)
    return out


def _undo_legacy_swap(r: Dict[str, Any]) -> None:
    """Cofnij błędną zamianę stron w plikach sprzed poprawki.

    Do tej poprawki pipeline zamieniał kursy i formę, gdy uznał, że „Livesport
    ma odwrócone strony". Założenie było fałszywe (slugi w URL-u Livesport są
    alfabetyczne), więc wiersze z ``sidesReversed=True`` mają w pliku kursy i
    formę PRZYPISANE DO ZŁEJ DRUŻYNY. Ponowna zamiana przywraca prawdziwe
    wartości — te, które faktycznie oferował bukmacher.

    Bez tego audyt liczyłby ROI na kursach, których nikt nie mógł zagrać.
    """
    if r.get('sidesReversed') is not True:
        return
    o = r.get('odds')
    if isinstance(o, dict):
        o['home'], o['away'] = o.get('away'), o.get('home')
    f = r.get('form')
    if isinstance(f, dict):
        f['home'], f['away'] = f.get('away'), f.get('home')
        f['homeAtHome'], f['awayAtAway'] = f.get('awayAtAway'), f.get('homeAtHome')
    r['_legacy_swapped'] = True


def match_key(m: Dict[str, Any]) -> str:
    return f"{m['_date']}|{m['_sport']}|{m.get('homeTeam')}|{m.get('awayTeam')}"


def load_settled() -> Dict[str, Any]:
    try:
        with open(SETTLED_PATH, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settled(store: Dict[str, Any]) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    tmp = SETTLED_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(store, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, SETTLED_PATH)


# ---------------------------------------------------------------------------
# Pomocnicze wyliczenia na wierszu
# ---------------------------------------------------------------------------

def pick_of(m: Dict[str, Any]) -> Optional[str]:
    p = (m.get('scoring') or {}).get('pick')
    return p if p in ('1', '2') else None


def pick_odds(m: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """(kurs typu, kurs przeciwnika)."""
    o = m.get('odds') or {}
    h, a = o.get('home'), o.get('away')
    p = pick_of(m)
    if p == '1':
        return h, a
    if p == '2':
        return a, h
    return None, None


def form_points(form: Any) -> Optional[int]:
    tab = {'W': 3, 'D': 1, 'L': 0}
    vals = [tab.get(str(x).upper()[:1]) for x in (form or [])]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def form_verdict(m: Dict[str, Any]) -> str:
    """'lepsza' / 'rowna' / 'gorsza' / 'brak' — z perspektywy TYPU."""
    f = m.get('form') or {}
    ph, pa = form_points(f.get('home')), form_points(f.get('away'))
    if ph is None or pa is None:
        return 'brak'
    mine, theirs = (ph, pa) if pick_of(m) == '1' else (pa, ph)
    return 'lepsza' if mine > theirs else 'rowna' if mine == theirs else 'gorsza'


def margin_of(m: Dict[str, Any]) -> Optional[float]:
    o = m.get('odds') or {}
    vals = [v for v in (o.get('home'), o.get('draw'), o.get('away'))
            if isinstance(v, (int, float)) and v > 1]
    if len(vals) < 2:
        return None
    return (sum(1 / v for v in vals) - 1) * 100


def market_tier(m: Dict[str, Any]) -> str:
    mg = margin_of(m)
    if mg is None:
        return 'n/d'
    return 'czolowa' if mg <= 8 else 'srednia' if mg <= 11.5 else 'nizsza'


def is_market_favourite(m: Dict[str, Any]) -> Optional[bool]:
    mine, theirs = pick_odds(m)
    if not mine or not theirs:
        return None
    return mine < theirs


# ---------------------------------------------------------------------------
# 1. Rozliczenie
# ---------------------------------------------------------------------------

def settle_one(m: Dict[str, Any]) -> Dict[str, Any]:
    """Znajdź wynik meczu w SofaScore i zweryfikuj, że to ten mecz."""
    import sofascore_scraper as ss
    import forebet_pipeline as fp

    home, away = m.get('homeTeam'), m.get('awayTeam')
    sport, date = m['_sport'], m['_date']

    event_id = None
    # Najpierw ID zapisane przez pipeline (od PR z polem sofascore.url) —
    # wtedy nie trzeba szukać ponownie.
    url = str((m.get('sofascore') or {}).get('url') or '')
    found = re.search(r'/match/(\d+)', url)
    if found:
        event_id = int(found.group(1))
    if not event_id:
        event_id = ss.search_event_via_api(home, away, sport=sport, date_str=date)
    if not event_id:
        return {'status': 'not_found'}

    # Ta sama weryfikacja co przy kursach: obie drużyny + termin. Bez niej
    # rozliczylibyśmy typ wynikiem innego meczu (rewanż, drużyna rezerw).
    orient = fp._verify_sofascore_event(event_id, home, away, date_str=date)
    if orient is None:
        return {'status': 'mismatch', 'event_id': event_id}

    res = ss.get_event_result(event_id)
    if not res:
        return {'status': 'unfinished', 'event_id': event_id}

    winner = res['winner']
    sh, sa = res['score_home'], res['score_away']
    if orient == 'reversed':
        winner = {'home': 'away', 'away': 'home'}.get(winner, winner)
        sh, sa = sa, sh
    return {'status': 'settled', 'event_id': event_id, 'winner': winner,
            'score': f'{sh}-{sa}', 'orientation': orient}


def settle(matches: List[Dict[str, Any]], store: Dict[str, Any],
           max_settle: int, time_budget: float) -> Dict[str, int]:
    """Rozlicz zakwalifikowane typy z dni zakończonych. Aktualizuje ``store``."""
    today = datetime.now(timezone.utc).date().isoformat()
    todo = []
    for m in matches:
        if not m.get('qualifies') or not pick_of(m):
            continue
        if m['_date'] >= today:          # mecze dzisiejsze mogą trwać
            continue
        rec = store.get(match_key(m))
        if rec and rec.get('status') == 'settled':
            continue
        if rec and rec.get('tries', 0) >= MAX_SETTLE_TRIES:
            continue
        todo.append(m)

    stats = defaultdict(int)
    started = time.time()
    print(f'🔎 Do rozliczenia: {len(todo)} typów (limit {max_settle})')

    import sofascore_scraper as ss

    def _unreachable() -> bool:
        try:
            return bool(ss.is_sofascore_unreachable())
        except Exception:
            return False

    for i, m in enumerate(todo[:max_settle], 1):
        if time.time() - started > time_budget:
            print(f'   ⏳ Budżet czasu rozliczenia wyczerpany po {i - 1}')
            break
        # SofaScore odcięte (403 / bezpiecznik) — przerywamy. Każde dalsze
        # „nie znaleziono" byłoby fałszywe: nie wiemy, że meczu nie ma, tylko
        # że nie mogliśmy zapytać. Bez tego warunku pierwszy przebieg zapisał
        # 492 fałszywe not_found, a po trzech takich typy porzucane byłyby
        # na zawsze.
        if _unreachable():
            stats['przerwane_sofascore_niedostepne'] = len(todo[:max_settle]) - i + 1
            print(f'   ⛔ SofaScore niedostępne (403) — przerywam rozliczanie po '
                  f'{i - 1}, bez zużywania prób dla pozostałych')
            break
        key = match_key(m)
        prev = store.get(key) or {}
        try:
            rec = settle_one(m)
        except Exception as e:  # sieć, parsowanie — nie przerywamy audytu
            rec = {'status': 'error', 'error': f'{type(e).__name__}: {e}'[:120]}
        # Odpowiedź uzyskana po odcięciu SofaScore jest bezwartościowa —
        # nie zapisujemy jej i nie liczymy próby.
        if rec['status'] != 'settled' and _unreachable():
            stats['przerwane_sofascore_niedostepne'] = len(todo[:max_settle]) - i + 1
            print(f'   ⛔ SofaScore odcięte w trakcie — przerywam po {i - 1}')
            break
        if rec['status'] != 'settled':
            rec['tries'] = prev.get('tries', 0) + 1
        store[key] = rec
        stats[rec['status']] += 1
        if i % 25 == 0:
            save_settled(store)  # nie tracimy postępu przy przerwaniu
            print(f'   … {i}/{len(todo)}  {dict(stats)}')
    save_settled(store)
    return dict(stats)


# ---------------------------------------------------------------------------
# Statystyki trafności
# ---------------------------------------------------------------------------

def outcome(m: Dict[str, Any], store: Dict[str, Any]) -> Optional[Tuple[bool, float]]:
    """(czy trafiony, zysk przy stawce 1) albo None, gdy nierozliczony."""
    rec = store.get(match_key(m))
    if not rec or rec.get('status') != 'settled':
        return None
    odds, _ = pick_odds(m)
    if not odds:
        return None
    want = 'home' if pick_of(m) == '1' else 'away'
    won = rec.get('winner') == want
    return won, (odds - 1.0) if won else -1.0


def group_stats(rows: List[Tuple[Dict[str, Any], bool, float]],
                keyfn) -> List[Tuple[str, int, float, float, float]]:
    """[(grupa, n, trafność %, ROI %, średni kurs)] posortowane po n."""
    groups: Dict[str, List[Tuple[bool, float, float]]] = defaultdict(list)
    for m, won, profit in rows:
        groups[str(keyfn(m))].append((won, profit, pick_odds(m)[0] or 0))
    out = []
    for g, items in groups.items():
        n = len(items)
        hit = 100 * sum(1 for w, _, _ in items if w) / n
        roi = 100 * sum(p for _, p, _ in items) / n
        avg = sum(o for _, _, o in items) / n
        out.append((g, n, hit, roi, avg))
    return sorted(out, key=lambda t: -t[1])


def score_bucket(m: Dict[str, Any]) -> str:
    s = (m.get('scoring') or {}).get('prob') or 0
    return '<55' if s < 55 else '55-60' if s < 60 else '60-65' if s < 65 else '65+'


def ev_bucket(m: Dict[str, Any]) -> str:
    ev = (m.get('scoring') or {}).get('ev')
    if ev is None:
        return 'n/d'
    return 'ujemne' if ev < 0 else '0-0.2' if ev < 0.2 else '0.2+'


def fav_label(m: Dict[str, Any]) -> str:
    f = is_market_favourite(m)
    return 'n/d' if f is None else 'faworyt rynku' if f else 'underdog rynku'


# ---------------------------------------------------------------------------
# 2. Kontrole zdrowia
# ---------------------------------------------------------------------------

def health_checks(matches: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    """Lista (poziom, sport, opis). Poziom: KRYTYCZNE / UWAGA / OK."""
    findings: List[Tuple[str, str, str]] = []
    if not matches:
        return [('KRYTYCZNE', '—', 'brak plików wyników Forebet')]

    latest = max(m['_date'] for m in matches)
    day = [m for m in matches if m['_date'] == latest]
    by_sport: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for m in day:
        by_sport[m['_sport']].append(m)

    for sport, rows in sorted(by_sport.items()):
        q = [m for m in rows if m.get('qualifies')]

        # a) forma — wymóg użytkownika; bez niej bramka nie działa
        if q:
            no_form = sum(1 for m in q if form_verdict(m) == 'brak')
            share = no_form / len(q)
            if share >= 0.9:
                findings.append(('KRYTYCZNE', sport,
                                 f'{no_form}/{len(q)} zakwalifikowanych BEZ formy — '
                                 f'wymóg lepszej formy nie działa'))
            elif share >= 0.3:
                findings.append(('UWAGA', sport,
                                 f'{no_form}/{len(q)} zakwalifikowanych bez formy'))

        # b) zgodność Forebet z rynkiem — ~50% znaczy, że Forebet nic nie wnosi
        agree = total = 0
        for m in rows:
            fb = m.get('forebet') or {}
            o = m.get('odds') or {}
            hp, ap, ho, ao = fb.get('homeProb'), fb.get('awayProb'), o.get('home'), o.get('away')
            if None in (hp, ap, ho, ao) or hp == ap or ho == ao:
                continue
            total += 1
            agree += (hp > ap) == (ho < ao)
        if total >= MIN_SAMPLE:
            pct = 100 * agree / total
            # Kolejność ma znaczenie: <30% sprawdzamy PIERWSZE, bo to inna
            # diagnoza (odwrócone kursy) niż 30–60% (słaby sygnał Forebet).
            if pct < 30:
                findings.append(('KRYTYCZNE', sport,
                                 f'zgodność Forebet/rynek {pct:.0f}% — kursy '
                                 f'prawdopodobnie ODWRÓCONE'))
            elif pct < 60:
                findings.append(('KRYTYCZNE' if pct < 55 else 'UWAGA', sport,
                                 f'Forebet zgodny z rynkiem tylko w {pct:.0f}% '
                                 f'({agree}/{total}) — sygnał bliski rzutowi monetą'))

        # c) orientacja stron nierozstrzygnięta
        unk = sum(1 for m in rows if m.get('oddsOrientationUnknown'))
        if unk and rows and unk / len(rows) > 0.05:
            findings.append(('UWAGA', sport,
                             f'{unk}/{len(rows)} meczów z nieustaloną orientacją stron'))

        # d) zakwalifikowane z ujemnym EV — rynek jest już przed nami
        neg = [m for m in q if ((m.get('scoring') or {}).get('ev') or 0) < 0]
        if neg:
            findings.append(('UWAGA', sport,
                             f'{len(neg)}/{len(q)} zakwalifikowanych z UJEMNYM EV'))

        # e) duplikaty — ten sam mecz dwa razy w mailu
        seen: Dict[str, int] = defaultdict(int)
        for m in q:
            seen[f"{m.get('homeTeam')}|{m.get('awayTeam')}"] += 1
        dup = sum(c - 1 for c in seen.values() if c > 1)
        if dup:
            findings.append(('UWAGA', sport, f'{dup} zduplikowanych typów w mailu'))

        # f) Fan Vote w ogóle nie działa
        with_votes = sum(1 for m in rows if (m.get('sofascore') or {}).get('votes'))
        if len(rows) >= MIN_SAMPLE and with_votes == 0:
            findings.append(('UWAGA', sport,
                             f'Fan Vote: 0 głosów na {len(rows)} meczów — '
                             f'składnik scoringu nie działa'))

        # g) Fan Vote wbrew rynkowi przy zgodnym Forebet — objaw odwróconych głosów
        suspicious = 0
        for m in q:
            ss_ = m.get('sofascore') or {}
            hv, av = ss_.get('homeProb'), ss_.get('awayProb')
            fav = is_market_favourite(m)
            if hv is None or av is None or fav is None or hv == av:
                continue
            votes_for_pick = (hv > av) == (pick_of(m) == '1')
            if votes_for_pick and not fav and max(hv, av) >= 70:
                suspicious += 1
        if q and suspicious >= max(3, len(q) // 3):
            findings.append(('UWAGA', sport,
                             f'{suspicious}/{len(q)} typów: kibice ≥70% za typem, '
                             f'rynek przeciw — sprawdź orientację Fan Vote'))

        # h) brak kursów dominuje
        no_odds = sum(1 for m in rows if 'brak_kursow' in (m.get('skipReasons') or []))
        if len(rows) >= MIN_SAMPLE and no_odds / len(rows) > 0.4:
            findings.append(('UWAGA', sport,
                             f'{no_odds}/{len(rows)} meczów bez kursów'))

        # i) nic się nie kwalifikuje przy dużej puli
        if len(rows) >= 50 and not q:
            findings.append(('UWAGA', sport,
                             f'0 zakwalifikowanych na {len(rows)} przetworzonych'))

    if not any(level != 'OK' for level, _, _ in findings):
        findings.append(('OK', '—', f'brak problemów w danych z {latest}'))
    return findings


# ---------------------------------------------------------------------------
# Raport
# ---------------------------------------------------------------------------

def fmt_table(title: str, rows: List[Tuple[str, int, float, float, float]]) -> List[str]:
    lines = [f'### {title}', '',
             '| grupa | typów | trafność | ROI | śr. kurs |',
             '|---|---:|---:|---:|---:|']
    for g, n, hit, roi, avg in rows:
        note = '' if n >= MIN_SAMPLE else ' ⚠️'
        lines.append(f'| {g}{note} | {n} | {hit:.0f}% | {roi:+.1f}% | {avg:.2f} |')
    lines += ['', f'⚠️ = mniej niż {MIN_SAMPLE} typów, wynik niewiarygodny', '']
    return lines


def build_report(matches, store, settle_stats, findings) -> str:
    rows = []
    for m in matches:
        if not m.get('qualifies'):
            continue
        oc = outcome(m, store)
        if oc:
            rows.append((m, oc[0], oc[1]))

    L: List[str] = ['# Audyt Forebet', '',
                    f'_wygenerowano {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC_', '']

    L += ['## Kontrole zdrowia danych', '']
    icon = {'KRYTYCZNE': '🔴', 'UWAGA': '🟡', 'OK': '🟢'}
    for level, sport, text in sorted(findings, key=lambda f: (f[0] != 'KRYTYCZNE', f[0] != 'UWAGA')):
        L.append(f'- {icon.get(level, "•")} **{level}** `{sport}` — {text}')
    L.append('')

    L += ['## Wyniki typów', '']
    if settle_stats:
        L.append(f'Rozliczanie w tym przebiegu: `{settle_stats}`')
        L.append('')
    if not rows:
        L += ['Brak rozliczonych typów — jeszcze za wcześnie albo SofaScore '
              'niedostępny.', '']
        return '\n'.join(L)

    n = len(rows)
    hit = 100 * sum(1 for _, w, _ in rows if w) / n
    roi = 100 * sum(p for _, _, p in rows) / n
    profit = sum(p for _, _, p in rows)
    L += [f'**{n} rozliczonych typów — trafność {hit:.0f}%, ROI {roi:+.1f}%, '
          f'wynik {profit:+.1f} j.** (stawka 1 j. na typ)', '']

    L += fmt_table('Wg sportu', group_stats(rows, lambda m: m['_sport']))
    L += fmt_table('Typy dotknięte błędną zamianą stron (sprzed poprawki)',
                   group_stats(rows, lambda m: 'zamienione w mailu'
                               if m.get('_legacy_swapped') else 'poprawne'))
    L += fmt_table('Wg formy typu', group_stats(rows, form_verdict))
    L += fmt_table('Faworyt vs underdog rynku', group_stats(rows, fav_label))
    L += fmt_table('Wg EV', group_stats(rows, ev_bucket))
    L += fmt_table('Wg klasy rynku (marża)', group_stats(rows, market_tier))
    L += fmt_table('Wg score', group_stats(rows, score_bucket))
    return '\n'.join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--max-settle', type=int, default=400)
    ap.add_argument('--settle-budget', type=int, default=40 * 60,
                    help='maks. sekund na rozliczanie')
    ap.add_argument('--no-settle', action='store_true',
                    help='tylko kontrole zdrowia, bez odpytywania SofaScore')
    ap.add_argument('--results-dir', default=None,
                    help='katalog z plikami matches_*_forebet.json '
                         '(domyślnie results/)')
    args = ap.parse_args()

    global RESULTS_DIR, SETTLED_PATH
    if args.results_dir:
        RESULTS_DIR = os.path.abspath(args.results_dir)
        SETTLED_PATH = os.path.join(RESULTS_DIR, 'forebet_settled.json')

    matches = load_matches(args.days)
    print(f'📂 Wczytano {len(matches)} zdarzeń z {args.days} dni')

    store = load_settled()
    settle_stats: Dict[str, int] = {}
    if not args.no_settle:
        settle_stats = settle(matches, store, args.max_settle, args.settle_budget)

    findings = health_checks(matches)
    report = build_report(matches, store, settle_stats, findings)

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as fh:
        fh.write(report)
    print(report)

    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as fh:
            fh.write(report + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
