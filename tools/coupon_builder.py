#!/usr/bin/env python3
"""Kupony dnia: AKO3, AKO7 i AKO wszystkich zdarzeń — z obu pipeline'ów.

Źródła (dzień ``--date``):
  * Sport Scraper Pipeline  — results/matches_<data>_<sport>.json
  * Forebet Pipeline        — results/matches_<data>_<sport>_forebet.json

Kroki:
  1. Zbiera zakwalifikowane zdarzenia z obu źródeł i łączy duplikaty (ten sam
     mecz w obu = „potwierdzony przez 2 źródła"). Gdy źródła typują RÓŻNE
     strony, mecz jest wykluczany z kuponów — nie wiadomo, która ma rację.
  2. Filtr formy dla AKO3/AKO7: typowany co najmniej FORM_FAV_MIN/5 wygranych,
     rywal najwyżej FORM_DOG_MAX/5. Kolejność: największa różnica formy.
     AKO-wszystkie nie ma filtra formy — to pomiar łącznej skuteczności.
  3. Kurs z Superbetu (publiczna oferta, bez logowania) + kod zdarzenia.
     Gdy Superbet nie ma meczu, zostaje kurs z pipeline'u (oznaczony).
  4. Zapis do results/coupons/coupons_<data>.json, wysyłka na Telegram.
  5. Rozliczenie kuponów z poprzednich dni (wynik każdego zdarzenia przez
     SofaScore, ta sama weryfikacja co w audycie) i bilans łączny.

Superbet nie udostępnia linku, który wczytuje zdarzenia do kuponu (sprawdzone
w kodzie strony: udostępnianie działa tylko dla już postawionych kuponów),
dlatego wiadomość podaje kod zdarzenia i kurs — nie gotowy kupon.

Bot NIE loguje się do bukmachera i NIE stawia zakładów.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:  # pragma: no cover
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS = os.path.join(ROOT, 'results')
COUPON_DIR = os.path.join(RESULTS, 'coupons')

FORM_FAV_MIN = int(os.getenv('COUPON_FORM_FAV_MIN', '4'))
FORM_DOG_MAX = int(os.getenv('COUPON_FORM_DOG_MAX', '1'))
SIZES = (('AKO3', 3), ('AKO7', 7))

SPORTS = ('football', 'tennis', 'basketball', 'hockey', 'handball',
          'volleyball', 'baseball', 'rugby')
SUPERBET_SPORT_ID = {'football': 5, 'tennis': 2, 'basketball': 4,
                     'volleyball': 1, 'hockey': 3, 'handball': 11}
SUPERBET_OFFER = ('https://production-superbet-offer-pl.freetls.fastly.net/'
                  'v2/pl-PL/events/by-date')
SUPERBET_SITEMAP = 'https://superbet.pl/sitemap/events.xml'
SUPERBET_SPORT_SLUG = {'football': 'pilka-nozna', 'tennis': 'tenis',
                       'basketball': 'koszykowka', 'volleyball': 'siatkowka',
                       'hockey': 'hokej-na-lodzie', 'handball': 'pilka-reczna'}


def superbet_slug(name: str) -> str:
    """Slug nazwy jak na superbet.pl (zgodność 1033/1036 z sitemapą)."""
    import unicodedata
    s = (name.replace('&', ' and ').replace("'", '').replace('’', '')
         .replace('.', '').replace('/', '').replace('ı', 'i')
         .replace('ł', 'l').replace('Ł', 'L').replace('ø', 'o').replace('Ø', 'O'))
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def superbet_sitemap() -> Dict[str, str]:
    """eventId -> dokładny adres strony meczu z sitemapy superbet.pl."""
    from curl_cffi import requests as cr
    try:
        x = cr.get(SUPERBET_SITEMAP, impersonate='chrome124', timeout=40).text
    except Exception as e:
        print(f'⚠️ Superbet sitemap: {type(e).__name__}')
        return {}
    out = {}
    for loc in re.findall(r'<loc>(https://superbet\.pl/kursy/[^<]+)</loc>', x):
        m = re.search(r'-(\d+)$', loc)
        if m:
            out[m.group(1)] = loc
    print(f'🗺️ Superbet sitemap: {len(out)} adresów meczów')
    return out


# ---------------------------------------------------------------------------
# Nazwy i tokeny
# ---------------------------------------------------------------------------

def _fp():
    import forebet_pipeline as fp
    return fp


def name_tokens(name: str) -> set:
    """Tokeny nazwy z tłumaczeniem PL→EN (główny pipeline pisze po polsku)."""
    fp = _fp()
    toks = fp._tokens(name) or fp._short_tokens(name)
    return set(toks) | {fp._EN_BY_PL[t] for t in toks if t in fp._EN_BY_PL}


def _overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    hits = sum(1 for x in a if any(x == y or (len(x) >= 5 and y.startswith(x))
                                   or (len(y) >= 5 and x.startswith(y)) for y in b))
    return hits / min(len(a), len(b))


def wins(form: Any) -> Optional[int]:
    seq = [str(x).upper()[:1] for x in (form or [])][:5]
    seq = [c for c in seq if c in 'WDL']
    return seq.count('W') if len(seq) >= 3 else None


# ---------------------------------------------------------------------------
# 1. Zbieranie z obu pipeline'ów
# ---------------------------------------------------------------------------

def _load(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    rows = d.get('matches', d) if isinstance(d, dict) else d
    return [r for r in rows or [] if isinstance(r, dict) and r.get('qualifies')]


def _leg(source: str, sport: str, r: Dict[str, Any], pick: str,
         fh: Any, fa: Any) -> Dict[str, Any]:
    o = r.get('odds') or {}
    home, away = str(r.get('homeTeam') or ''), str(r.get('awayTeam') or '')
    fav, dog = (fh, fa) if pick == '1' else (fa, fh)
    return {
        'sport': sport, 'home': home, 'away': away, 'pick': pick,
        'pick_team': home if pick == '1' else away,
        'time': r.get('time'), 'league': r.get('league'),
        'odds_pipeline': o.get('home') if pick == '1' else o.get('away'),
        'odds_home': o.get('home'), 'odds_away': o.get('away'),
        'fav_form': list(fav or []), 'dog_form': list(dog or []),
        'fav_wins': wins(fav), 'dog_wins': wins(dog),
        'livesport': r.get('matchUrl'),
        'score': (r.get('scoring') or {}).get('prob'),
        'sources': [source],
    }


def collect(date: str) -> List[Dict[str, Any]]:
    legs: List[Dict[str, Any]] = []
    for sport in SPORTS:
        # Sport Scraper: typuje stronę focusTeam (home w scrape.yml, away w AWAY).
        for r in _load(os.path.join(RESULTS, f'matches_{date}_{sport}.json')):
            pick = '2' if r.get('focusTeam') == 'away' else '1'
            legs.append(_leg('sportscraper', sport, r, pick,
                             r.get('homeForm'), r.get('awayForm')))
        # Forebet: strona z scoring.pick.
        for r in _load(os.path.join(RESULTS, f'matches_{date}_{sport}_forebet.json')):
            pick = (r.get('scoring') or {}).get('pick')
            if pick not in ('1', '2'):
                continue
            f = r.get('form') or {}
            legs.append(_leg('forebet', sport, r, pick, f.get('home'), f.get('away')))
    # 🇷🇺 Siatka bezpieczeństwa: ligi rosyjskie nie trafiają na kupony.
    import russia_filter
    legs = [l for l in legs if not russia_filter.is_russian(l.get('league'))]
    return merge(legs)


def merge(legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Połącz ten sam mecz z obu źródeł. Sprzeczne typy → konflikt."""
    out: List[Dict[str, Any]] = []
    for leg in legs:
        th, ta = name_tokens(leg['home']), name_tokens(leg['away'])
        twin = None
        for o in out:
            if o['sport'] != leg['sport']:
                continue
            oh, oa = name_tokens(o['home']), name_tokens(o['away'])
            if _overlap(th, oh) >= 0.5 and _overlap(ta, oa) >= 0.5:
                twin = (o, False)
            elif _overlap(th, oa) >= 0.5 and _overlap(ta, oh) >= 0.5:
                twin = (o, True)          # te same drużyny, odwrotne strony
            if twin:
                break
        if not twin:
            out.append(leg)
            continue
        o, flipped = twin
        same_team = (leg['pick'] == o['pick']) != flipped
        if not same_team:
            o['conflict'] = True
        o['sources'] = sorted(set(o['sources']) | set(leg['sources']))
        for k in ('fav_form', 'dog_form', 'fav_wins', 'dog_wins', 'livesport'):
            if not o.get(k) and leg.get(k) and same_team:
                o[k] = leg[k]
    return out


# ---------------------------------------------------------------------------
# 2. Superbet
# ---------------------------------------------------------------------------

def superbet_index(date: str) -> Dict[str, List[Dict[str, Any]]]:
    from curl_cffi import requests as cr
    idx: Dict[str, List[Dict[str, Any]]] = {}
    for sport, sid in SUPERBET_SPORT_ID.items():
        url = (f'{SUPERBET_OFFER}?currentStatus=active&offerState=prematch'
               f'&startDate={date}+00:00:00&endDate={date}+23:59:59&sportId={sid}')
        data, err = None, None
        for imp in ('chrome124', 'chrome120', 'safari17_0'):
            try:
                data = cr.get(url, impersonate=imp, timeout=25).json().get('data') or []
                break
            except Exception as e:
                err = e
        if data is None:
            try:
                import requests
                data = requests.get(url, timeout=25).json().get('data') or []
            except Exception as e:
                print(f'⚠️ Superbet {sport}: {type(err).__name__} / {type(e).__name__}')
                continue
        rows = []
        for ev in data:
            parts = re.split(r'[·\u00b7]', str(ev.get('matchName') or ''))
            if len(parts) != 2:
                continue
            prices = {}
            for od in ev.get('odds') or []:
                # Rynek „Mecz" / „Zwycięzca": kody 1/2 (piłka ma też X).
                if od.get('code') in ('1', 'X', '2') and od.get('status') == 'active' \
                        and re.search(r'mecz|zwyci', str(od.get('marketName')), re.I):
                    prices.setdefault(od['code'], od.get('price'))
            rows.append({'home': parts[0].strip(), 'away': parts[1].strip(),
                         'th': name_tokens(parts[0]), 'ta': name_tokens(parts[1]),
                         'event_id': ev.get('eventId'), 'code': ev.get('matchCode'),
                         'prices': prices})
        idx[sport] = rows
        print(f'🟡 Superbet {sport}: {len(rows)} zdarzeń')
    return idx


def attach_superbet(legs: List[Dict[str, Any]], idx) -> None:
    sitemap = superbet_sitemap()
    for leg in legs:
        th, ta = name_tokens(leg['home']), name_tokens(leg['away'])
        best, best_s, flipped = None, 0.0, False
        for ev in idx.get(leg['sport'], []):
            d = min(_overlap(th, ev['th']), _overlap(ta, ev['ta']))
            r = min(_overlap(th, ev['ta']), _overlap(ta, ev['th']))
            s, fl = (d, False) if d >= r else (r, True)
            if s > best_s:
                best, best_s, flipped = ev, s, fl
        if not best or best_s < 0.5:
            continue
        side = leg['pick'] if not flipped else {'1': '2', '2': '1'}[leg['pick']]
        eid = str(best['event_id'])
        url = sitemap.get(eid) or (
            f"https://superbet.pl/kursy/{SUPERBET_SPORT_SLUG.get(leg['sport'], leg['sport'])}/"
            f"{superbet_slug(best['home'])}-vs-{superbet_slug(best['away'])}-{eid}")
        leg['superbet'] = {'code': best['code'], 'event_id': best['event_id'],
                           'price': best['prices'].get(side),
                           'name': f"{best['home']} – {best['away']}",
                           'url': url, 'url_exact': eid in sitemap}


def odds_of(leg: Dict[str, Any]) -> Optional[float]:
    p = (leg.get('superbet') or {}).get('price') or leg.get('odds_pipeline')
    try:
        return float(p) if p else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 3. Kupony
# ---------------------------------------------------------------------------

def form_ok(leg: Dict[str, Any]) -> bool:
    return (leg.get('fav_wins') is not None and leg.get('dog_wins') is not None
            and leg['fav_wins'] >= FORM_FAV_MIN and leg['dog_wins'] <= FORM_DOG_MAX)


def odds_ok(leg: Dict[str, Any]) -> bool:
    """Ten sam limit kursowy co w pipeline'ach (kurs poniżej progu = odpada).

    Potrzebne, bo Sport Scraper oznacza `qualifies` PRZED progiem kursowym —
    bez tego do kuponu wchodziły kursy 1.00–1.06.
    """
    ok, _ = _fp().odds_gate(leg['sport'], leg.get('odds_home'), leg.get('odds_away'),
                            0.0, 0.0)
    return ok


def build_coupons(legs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    usable = [l for l in legs if not l.get('conflict') and odds_of(l) and odds_ok(l)]
    strong = sorted(
        [l for l in usable if form_ok(l)],
        key=lambda l: (-(l['fav_wins'] - l['dog_wins']),
                       -len(l['sources']), -(l.get('score') or 0)))
    coupons = {}
    for name, n in SIZES:
        if len(strong) >= n:
            coupons[name] = strong[:n]
    coupons['AKO_WSZYSTKIE'] = usable
    out = {}
    for name, cl in coupons.items():
        total = 1.0
        for l in cl:
            total *= odds_of(l)
        out[name] = {'legs': cl, 'total_odds': round(total, 2), 'size': len(cl)}
    return out


# ---------------------------------------------------------------------------
# 4. Telegram
# ---------------------------------------------------------------------------

def _esc(s: Any) -> str:
    """Telegram wysyła z parse_mode=HTML — nazwy z &, < psułyby wiadomość."""
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _leg_line(i: int, l: Dict[str, Any]) -> str:
    sb = l.get('superbet') or {}
    src = '🟡SB' if sb.get('price') else '⚪'
    form = (f"{''.join(l['fav_form'][:5])}/{''.join(l['dog_form'][:5])}"
            if l.get('fav_form') and l.get('dog_form') else 'forma —')
    two = '✅✅' if len(l['sources']) > 1 else ''
    match = f"{_esc(l['home'])} – {_esc(l['away'])}"
    if sb.get('url'):
        match = f'<a href="{_esc(sb["url"])}">{match}</a>'   # klik → strona meczu
    code = f" kod {sb['code']}" if sb.get('code') else ''
    return (f"{i}. {match}\n"
            f"   ➜ {_esc(l['pick_team'])} @ {odds_of(l):.2f} {src}{code} | {form} {two}")


def message(date: str, coupons, balance: Optional[str]) -> str:
    lines = [f'🎯 KUPONY {date}', '']
    for name in ('AKO3', 'AKO7'):
        c = coupons.get(name)
        if not c:
            lines += [f'— {name}: za mało zdarzeń z formą ≥{FORM_FAV_MIN}/5 '
                      f'vs ≤{FORM_DOG_MAX}/5', '']
            continue
        lines.append(f"🔥 {name} @ {c['total_odds']}")
        lines += [_leg_line(i, l) for i, l in enumerate(c['legs'], 1)]
        lines.append('')
    a = coupons['AKO_WSZYSTKIE']
    tot = a['total_odds']
    tot_s = f'{tot:.2f}' if tot < 1e6 else f'{tot:.1e}'
    lines.append(f"📊 AKO WSZYSTKICH: {a['size']} zdarzeń @ {tot_s} "
                 f"(pomiar skuteczności — nie do grania)")
    if balance:
        lines += ['', balance]
    lines += ['', 'Kliknij nazwę meczu → otwiera się na Superbecie.',
              '🟡SB = kurs Superbet, ⚪ = kurs z pipeline (brak w Superbet)',
              '✅✅ = typ z obu pipeline\'ów | forma typowany/rywal']
    return '\n'.join(lines)


def send_telegram(text: str) -> None:
    if os.getenv('TELEGRAM_ENABLED', 'false').lower() != 'true':
        print('ℹ️ Telegram wyłączony (TELEGRAM_ENABLED != true)')
        return
    from telegram_notifier import _send_message
    for i in range(0, len(text), 3900):   # limit Telegrama 4096 znaków
        _send_message(text[i:i + 3900])


# ---------------------------------------------------------------------------
# 5. Rozliczenie
# ---------------------------------------------------------------------------

def settle_leg(date: str, l: Dict[str, Any]) -> Optional[bool]:
    from tools.forebet_audit import settle_one
    rec = settle_one({'_date': date, '_sport': l['sport'],
                      'homeTeam': l['home'], 'awayTeam': l['away']})
    if rec.get('status') != 'settled':
        return None
    return rec['winner'] == ('home' if l['pick'] == '1' else 'away')


def settle_past(days: int = 30) -> str:
    try:
        import sofascore_scraper as ss
    except Exception:
        ss = None
    today = datetime.now(timezone.utc).date().isoformat()
    stats = {k: [0, 0, 0.0] for k in ('AKO3', 'AKO7', 'AKO_WSZYSTKIE')}  # won, n, profit
    legs_won = legs_n = 0
    for path in sorted(glob.glob(os.path.join(COUPON_DIR, 'coupons_*.json')))[-days:]:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
        date = doc['date']
        changed = False
        if date < today:
            for c in doc['coupons'].values():
                for l in c['legs']:
                    if l.get('won') is None and l.get('tries', 0) < 3:
                        if ss and ss.is_sofascore_unreachable():
                            break
                        try:
                            l['won'] = settle_leg(date, l)
                        except Exception:
                            l['won'] = None
                        l['tries'] = l.get('tries', 0) + 1
                        changed = True
        if changed:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=1)
        for name, c in doc['coupons'].items():
            res = [l.get('won') for l in c['legs']]
            if name == 'AKO_WSZYSTKIE':
                legs_won += sum(1 for r in res if r is True)
                legs_n += sum(1 for r in res if r is not None)
            if not res or any(r is None for r in res) or name not in stats:
                continue
            won = all(res)
            s = stats[name]
            s[0] += won
            s[1] += 1
            s[2] += (c['total_odds'] - 1) if won else -1
    out = ['📈 BILANS (stawka 1 j./kupon, rozliczone dni):']
    for name, (w, n, p) in stats.items():
        if n:
            out.append(f'  {name}: {w}/{n} weszło, wynik {p:+.1f} j.')
    if legs_n:
        out.append(f'  pojedyncze zdarzenia: {legs_won}/{legs_n} '
                   f'({100 * legs_won / legs_n:.0f}%)')
    return '\n'.join(out) if len(out) > 1 else ''


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument('--no-superbet', action='store_true')
    ap.add_argument('--no-settle', action='store_true')
    ap.add_argument('--no-telegram', action='store_true')
    ap.add_argument('--results-dir', default=None)
    args = ap.parse_args()

    global RESULTS, COUPON_DIR
    if args.results_dir:
        RESULTS = os.path.abspath(args.results_dir)
        COUPON_DIR = os.path.join(RESULTS, 'coupons')

    legs = collect(args.date)
    both = sum(1 for l in legs if len(l['sources']) > 1)
    conf = sum(1 for l in legs if l.get('conflict'))
    print(f'📥 {len(legs)} zdarzeń (oba źródła: {both}, sprzeczne: {conf})')
    if not args.no_superbet:
        attach_superbet(legs, superbet_index(args.date))
        print(f'🟡 z kursem Superbet: '
              f'{sum(1 for l in legs if (l.get("superbet") or {}).get("price"))}/{len(legs)}')

    coupons = build_coupons(legs)
    os.makedirs(COUPON_DIR, exist_ok=True)
    path = os.path.join(COUPON_DIR, f'coupons_{args.date}.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'date': args.date, 'generated': datetime.now(timezone.utc).isoformat(),
                   'form_rule': f'>={FORM_FAV_MIN}/5 vs <={FORM_DOG_MAX}/5',
                   'coupons': coupons}, fh, ensure_ascii=False, indent=1, default=list)

    balance = '' if args.no_settle else settle_past()
    text = message(args.date, coupons, balance)
    print('\n' + text)
    if not args.no_telegram:
        send_telegram(text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as fh:
            fh.write('```\n' + text + '\n```\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
