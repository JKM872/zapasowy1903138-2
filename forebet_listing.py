"""
Forebet Listing
===============
Listuje **wszystkie** mecze dnia z Forebet dla danego sportu i parsuje z
wiersza wszystko, co Forebet oddaje na stronie przeglądowej:

- nazwy drużyn, godzinę, ligę, URL i ID meczu Forebet
- predykcję 1X2 + prawdopodobieństwa (3-way i 2-way)
- kursy bukmacherskie z ``div.haodd`` (są tylko na części zdarzeń)
- dokładny wynik / średnią goli

Formy tu nie ma świadomie — dostarcza ją Livesport (patrz ``forebet_pipeline``).

Po co osobny moduł: ``forebet_scraper.search_forebet_prediction()`` szuka
JEDNEGO meczu po nazwach drużyn (dopasowanie fuzzy + AI). Tutaj kierunek jest
odwrotny — Forebet jest ŹRÓDŁEM selekcji, więc potrzebujemy pełnej listy dnia,
a nie odpowiedzi na pytanie „czy ten mecz tam jest”.

Uwaga o „More”: każdy sport na Forebet ma przycisk „More”. Klika go wyłącznie
ścieżka Puppeteer (``forebet_puppeteer.js``); curl_cffi i FlareSolverr zwracają
tylko pierwszą porcję wierszy. Dlatego ``list_forebet_matches()`` domyślnie
preferuje Puppeteera i dopiero potem schodzi do szybszych metod.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

import forebet_scraper as fb

# Sporty rozstrzygane bez remisu — Forebet pokazuje dla nich 2 liczby w div.fprc.
TWO_WAY_SPORTS = {
    'basketball', 'volleyball', 'tennis', 'baseball', 'table_tennis',
}

# Formy z Forebet świadomie NIE czytamy. Kolorowe wskaźniki nie występują na
# stronie przeglądowej predictions-1x2 (sprawdzone na zapisanych snapshotach
# wszystkich sportów), a jedynym źródłem formy w pipeline jest Livesport
# (`extract_advanced_team_form`: ogólna + u siebie + na wyjeździe). Skanowanie
# Forebet „na wszelki wypadek" dawało zawsze pustą listę i tylko sugerowało,
# że istnieje drugie źródło formy.


# ---------------------------------------------------------------------------
# Parsowanie pojedynczego wiersza
# ---------------------------------------------------------------------------

def _text(el) -> str:
    return el.get_text(strip=True) if el else ''


def _to_float(raw: Any) -> Optional[float]:
    """Zamień tekst kursu na float. Zwraca None dla ' - ', 'no', pustych."""
    if raw is None:
        return None
    txt = str(raw).strip().replace(',', '.')
    if not txt or txt in {'-', '–', '—'} or txt.lower() in {'no', 'n/a', 'na'}:
        return None
    m = re.search(r'\d+(?:\.\d+)?', txt)
    if not m:
        return None
    try:
        val = float(m.group(0))
    except (TypeError, ValueError):
        return None
    # Kursy dziesiętne poniżej 1.0 nie istnieją; powyżej 1000 to nie kurs
    # (Forebet trzyma w tym samym divie liczby wolumenu, np. 487/491).
    if val < 1.01 or val > 1000:
        return None
    return val


def _parse_teams(row) -> tuple[Optional[str], Optional[str]]:
    """Nazwy drużyn: schema.org spans, potem meta 'A vs B'."""
    home_span = row.find('span', class_='homeTeam')
    away_span = row.find('span', class_='awayTeam')
    if home_span and away_span:
        h_inner = home_span.find('span', itemprop='name')
        a_inner = away_span.find('span', itemprop='name')
        home = _text(h_inner) or _text(home_span)
        away = _text(a_inner) or _text(away_span)
        if home and away:
            return home, away

    meta = row.find('meta', itemprop='name')
    if meta and meta.get('content') and ' vs ' in meta['content']:
        parts = meta['content'].split(' vs ', 1)
        return parts[0].strip(), parts[1].strip()

    return None, None


def _parse_datetime(row) -> tuple[Optional[str], Optional[str]]:
    """Zwraca (date YYYY-MM-DD, time HH:MM) ze span.date_bah / <time datetime>."""
    date_str = None
    time_str = None

    raw = _text(row.find('span', class_='date_bah'))  # '05/01/2026 19:30'
    if raw:
        try:
            parsed = datetime.strptime(raw, '%d/%m/%Y %H:%M')
            return parsed.strftime('%Y-%m-%d'), parsed.strftime('%H:%M')
        except (ValueError, TypeError):
            m = re.search(r'(\d{1,2}:\d{2})', raw)
            if m:
                time_str = m.group(1)

    time_el = row.find('time')
    if time_el and time_el.get('datetime'):
        dt_attr = time_el['datetime'][:10]
        if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_attr):
            date_str = dt_attr

    return date_str, time_str


def _parse_league(row) -> tuple[Optional[str], Optional[str]]:
    """Liga + kraj.

    Bogatsze źródło niż span.shortTag: onclick flagi zawiera
    ``getstag(this, id, 'Israel', 'Premier League', ...)``.
    """
    country = None
    league = None

    flag = row.find('img', class_='flsc')
    if flag and flag.get('onclick'):
        args = re.findall(r"'([^']*)'", flag['onclick'])
        if len(args) >= 2:
            country = args[0].strip() or None
            league = args[1].strip() or None

    if not league:
        tag = _text(row.find('span', class_='shortTag'))
        if tag:
            league_map = getattr(fb, '_FOREBET_LEAGUE_MAP', {}) or {}
            league = league_map.get(tag, tag)

    return league, country


def _parse_match_ref(row) -> tuple[Optional[str], Optional[str]]:
    """URL meczu na Forebet + ID."""
    url = None
    match_id = None

    link = row.find('a', class_='tnmscn', href=True) or row.find('a', href=True)
    if link:
        href = link['href']
        url = href if href.startswith('http') else f"https://www.forebet.com{href}"
        m = re.search(r'(\d{4,})/?$', href)
        if m:
            match_id = m.group(1)

    if not match_id:
        # Fallback: onclick="return getHodd(this,2356552);"
        holder = row.find(attrs={'onclick': re.compile(r'getHodd\(')})
        if holder:
            m = re.search(r'getHodd\(this,\s*(\d+)', holder['onclick'])
            if m:
                match_id = m.group(1)

    if not match_id:
        fav = row.find('div', class_='fav_icon')
        if fav and str(fav.get('id', '')).isdigit():
            match_id = fav['id']

    return url, match_id


def _parse_probabilities(row, two_way: bool) -> Dict[str, Any]:
    """Prawdopodobieństwa i predykcja z ``div.fprc`` (fallback: span.forepr)."""
    out: Dict[str, Any] = {
        'home_prob': None, 'draw_prob': None, 'away_prob': None,
        'probability': None, 'prediction': None,
    }

    fprc = row.find('div', class_='fprc')
    if fprc:
        nums: List[int] = []
        for span in fprc.find_all('span'):
            txt = _text(span)
            if re.fullmatch(r'\d{1,3}', txt):
                nums.append(int(txt))

        if len(nums) >= 3 and not two_way:
            out['home_prob'], out['draw_prob'], out['away_prob'] = nums[0], nums[1], nums[2]
            best = max(nums[:3])
            out['probability'] = float(best)
            out['prediction'] = '1' if best == nums[0] else ('X' if best == nums[1] else '2')
        elif len(nums) >= 2:
            # 2-way: dwie liczby. Dla sportu 3-way z dwiema liczbami też
            # traktujemy jako 1/2 — brak trzeciej wartości znaczy brak remisu.
            out['home_prob'], out['away_prob'] = nums[0], nums[1]
            out['probability'] = float(max(nums[0], nums[1]))
            out['prediction'] = '1' if nums[0] > nums[1] else '2'

    if not out['prediction']:
        pred = _text(row.find('span', class_='forepr'))
        if pred in {'1', 'X', '2'}:
            out['prediction'] = pred

    return out


def _parse_odds(row, two_way: bool) -> Dict[str, Any]:
    """Kursy 1X2 z ``div.haodd`` w przedmeczowym ``div.prmod``.

    Struktura (piłka nożna): ``<div class="bigOnly prmod">`` zawiera
    ``span.lscrsp`` (kurs na gospodarzy) oraz ukryty ``div.haodd`` ze spanami
    ``1, X, 2, no, no, no``. Kursy live siedzą w ``div.la_prmod`` i są tu
    świadomie pomijane — obstawiamy przed meczem.

    Gdy Forebet nie wycenił zdarzenia, spany zawierają ``" - "`` i zwracamy
    None. Przy sporcie 2-way z trzema liczbami układ jest niejednoznaczny,
    więc też zwracamy None: zły kurs jest gorszy niż brak kursu, bo wchodzi
    do progu kursowego i do EV.
    """
    out: Dict[str, Any] = {
        'home_odds': None, 'draw_odds': None, 'away_odds': None,
        'odds_source': None, 'odds_note': None,
    }

    prematch = None
    for div in row.find_all('div', class_='prmod'):
        classes = div.get('class', []) or []
        if 'la_prmod' in classes:
            continue
        prematch = div
        break

    if prematch is None:
        out['odds_note'] = 'no_prmod_div'
        return out

    haodd = prematch.find('div', class_='haodd')
    if haodd is None:
        out['odds_note'] = 'no_haodd_div'
        return out

    spans = haodd.find_all('span')
    raw = [_text(s) for s in spans[:3]]
    vals = [_to_float(r) for r in raw]
    numeric = [v for v in vals if v is not None]

    if not numeric:
        out['odds_note'] = 'forebet_unpriced'
        return out

    if not two_way:
        if len(numeric) >= 3 and all(v is not None for v in vals[:3]):
            out['home_odds'], out['draw_odds'], out['away_odds'] = vals[0], vals[1], vals[2]
            out['odds_source'] = 'forebet'
        else:
            out['odds_note'] = f'forebet_partial_odds({len(numeric)}/3)'
    else:
        if len([v for v in vals[:3] if v is not None]) == 2:
            pair = [v for v in vals[:3] if v is not None]
            out['home_odds'], out['away_odds'] = pair[0], pair[1]
            out['odds_source'] = 'forebet'
        else:
            out['odds_note'] = 'forebet_ambiguous_2way_odds'

    return out


def _is_started(row) -> bool:
    """Czy mecz już trwa/zakończony (wynik lub minuta w wierszu)."""
    score = _text(row.find('b', class_='l_scr')) or _text(row.find(class_='l_scr'))
    if re.search(r'\d\s*[-:]\s*\d', score):
        return True
    minute = _text(row.find('span', class_='l_min'))
    if re.fullmatch(r"\d{1,3}\+?'?", minute):
        return True
    return False


def parse_forebet_row(row, sport: str) -> Optional[Dict[str, Any]]:
    """Sparsuj jeden wiersz ``div.rcnt`` do słownika. None gdy brak drużyn."""
    sport_lower = (sport or '').lower()
    two_way = sport_lower in TWO_WAY_SPORTS

    home, away = _parse_teams(row)
    if not home or not away:
        return None

    date_str, time_str = _parse_datetime(row)
    league, country = _parse_league(row)
    url, match_id = _parse_match_ref(row)

    data: Dict[str, Any] = {
        'home_team': home,
        'away_team': away,
        'sport': sport_lower,
        'match_date': date_str,
        'match_time': time_str,
        'league': league,
        'country': country,
        'forebet_url': url,
        'forebet_id': match_id,
        'started': _is_started(row),
    }
    data.update(_parse_probabilities(row, two_way))
    data.update(_parse_odds(row, two_way))

    exact = row.find('div', class_='ex_sc')
    if exact:
        if exact.find('br'):
            parts = list(exact.stripped_strings)
            data['exact_score'] = f"{parts[0]}-{parts[1]}" if len(parts) == 2 else _text(exact)
        else:
            data['exact_score'] = _text(exact).replace(' ', '')
    else:
        data['exact_score'] = None

    avg = _text(row.find('div', class_='avg_sc'))
    try:
        data['avg_goals'] = float(avg) if avg else None
    except (TypeError, ValueError):
        data['avg_goals'] = None

    return data


# ---------------------------------------------------------------------------
# Pobieranie strony dnia + listowanie
# ---------------------------------------------------------------------------

def _find_rows(soup: BeautifulSoup) -> List[Any]:
    rows = soup.find_all('div', class_='rcnt')
    if rows:
        return rows
    rows = soup.find_all('tr', class_=['tr_0', 'tr_1'])
    if rows:
        return rows
    return []


def _html_from_puppeteer(sport: str, match_date: Optional[str],
                         load_more_clicks: int) -> Optional[str]:
    try:
        return fb.fetch_forebet_with_puppeteer(
            sport, match_date=match_date, load_more_clicks=load_more_clicks
        )
    except TypeError:
        # Starsza sygnatura bez daty — lepiej mieć pierwszą porcję niż nic.
        try:
            return fb.fetch_forebet_with_puppeteer(sport)
        except Exception as e:
            print(f"   ⚠️ Puppeteer fallback error: {e}")
            return None
    except Exception as e:
        print(f"   ⚠️ Puppeteer error: {e}")
        return None


def _html_from_cache_methods(sport: str, match_date: Optional[str]) -> Optional[str]:
    """curl_cffi / FlareSolverr przez prefetch w forebet_scraper (bez 'More')."""
    try:
        ok = fb.prefetch_forebet_html(sport, match_date)
    except Exception as e:
        print(f"   ⚠️ prefetch_forebet_html error: {e}")
        return None
    if not ok:
        return None

    key = f"{sport.lower()}_{match_date}"
    cached = getattr(fb, '_forebet_html_cache', {}).get(key)
    if not cached:
        return None

    html = cached[0]
    # Zapisz na dysk, żeby trafił do artefaktów. curl_cffi/FlareSolverr trzymają
    # HTML tylko w pamięci, więc gdy coś się nie zgadza (za mało meczów, brak
    # paginacji), nie ma czego obejrzeć po runie — zostaje zgadywanie z logu.
    try:
        with open(f'forebet_{sport.lower()}_fetched.html', 'w', encoding='utf-8') as fh:
            fh.write(html)
    except OSError as e:
        print(f"   ⚠️ Nie mogę zapisać HTML do diagnostyki: {e}")
    return html


def _count_rows_for_date(html: str, match_date: str) -> tuple[int, int]:
    """Zwróć (wszystkie wiersze, wiersze z datą == match_date).

    Druga liczba jest testem świeżości. Strona z innego dnia ma wiersze, ale
    żaden nie dotyczy pytanej daty — a bez tego sprawdzenia stary snapshot
    wygląda jak poprawny wynik, bo „wiersze są”.
    """
    soup = BeautifulSoup(html, 'html.parser')
    rows = _find_rows(soup)
    fresh = 0
    for row in rows:
        row_date, _ = _parse_datetime(row)
        if row_date == match_date:
            fresh += 1
    return len(rows), fresh


def fetch_forebet_day_html(sport: str, match_date: Optional[str] = None,
                           prefer_puppeteer: bool = True,
                           load_more_clicks: int = 25) -> Optional[str]:
    """Pobierz HTML strony dnia dla sportu, preferując pełną listę.

    Kolejność: Puppeteer (klika „More” → wszystkie mecze) → curl_cffi/
    FlareSolverr (tylko pierwsza porcja).

    Metoda jest uznana za udaną tylko wtedy, gdy HTML zawiera choć jeden mecz
    z pytaną datą. Inaczej schodzimy do następnej metody: strona z innego dnia
    (stary snapshot, cache FlareSolverr, strona challenge'u) ma wiersze, więc
    licząc same wiersze uznalibyśmy ją za dobry wynik.

    Zwraca None, gdy żadna metoda nie dała HTML-a na właściwy dzień.
    """
    if match_date is None:
        match_date = datetime.now().strftime('%Y-%m-%d')

    attempts: List[str] = ['puppeteer', 'fast'] if prefer_puppeteer else ['fast', 'puppeteer']

    best_html = None
    best_fresh = 0
    for method in attempts:
        if method == 'puppeteer':
            html = _html_from_puppeteer(sport, match_date, load_more_clicks)
        else:
            html = _html_from_cache_methods(sport, match_date)

        if not html:
            print(f"   📄 Forebet {sport} [{method}]: brak HTML")
            continue

        rows, fresh = _count_rows_for_date(html, match_date)
        print(f"   📄 Forebet {sport} [{method}]: {rows} wierszy "
              f"({fresh} na {match_date}), {len(html)} znaków")

        if fresh == 0:
            print(f"   ⚠️ Forebet {sport} [{method}]: żaden wiersz nie dotyczy "
                  f"{match_date} — odrzucam jako nieświeży i próbuję dalej")
            continue

        if fresh > best_fresh:
            best_fresh, best_html = fresh, html

        # Puppeteer z „More” to najpełniejsze źródło — nie ma po co dobierać.
        if method == 'puppeteer':
            break

    return best_html


def list_forebet_matches(sport: str, match_date: Optional[str] = None,
                         prefer_puppeteer: bool = True,
                         load_more_clicks: int = 25,
                         skip_started: bool = True,
                         filter_by_date: bool = True,
                         html: Optional[str] = None) -> List[Dict[str, Any]]:
    """Zwróć listę wszystkich meczów dnia z Forebet dla danego sportu.

    Args:
        sport: football / basketball / volleyball / handball / hockey /
            tennis / rugby / baseball
        match_date: YYYY-MM-DD (domyślnie dzisiaj)
        prefer_puppeteer: użyj Puppeteera (klika „More” = pełna lista)
        load_more_clicks: maks. liczba kliknięć „More”
        skip_started: pomiń mecze już rozpoczęte/zakończone
        filter_by_date: zostaw tylko wiersze z datą == match_date
        html: gotowy HTML (do testów offline; pomija pobieranie)

    Returns:
        Lista słowników z ``parse_forebet_row()``.
    """
    if match_date is None:
        match_date = datetime.now().strftime('%Y-%m-%d')

    if html is None:
        html = fetch_forebet_day_html(
            sport, match_date,
            prefer_puppeteer=prefer_puppeteer,
            load_more_clicks=load_more_clicks,
        )
    if not html:
        print(f"   ❌ Forebet {sport}: brak HTML — 0 meczów")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    rows = _find_rows(soup)
    if not rows:
        print(f"   ❌ Forebet {sport}: nie znaleziono wierszy meczów")
        return []

    matches: List[Dict[str, Any]] = []
    seen: set = set()
    dropped_started = 0
    dropped_date = 0
    dropped_unparsed = 0

    for row in rows:
        try:
            data = parse_forebet_row(row, sport)
        except Exception as e:
            dropped_unparsed += 1
            print(f"   ⚠️ Wiersz Forebet nieparsowalny: {type(e).__name__}: {e}")
            continue

        if not data:
            dropped_unparsed += 1
            continue

        if skip_started and data.get('started'):
            dropped_started += 1
            continue

        if filter_by_date and data.get('match_date') and data['match_date'] != match_date:
            dropped_date += 1
            continue

        key = data.get('forebet_id') or f"{data['home_team']}|{data['away_team']}|{data.get('match_time')}"
        if key in seen:
            continue
        seen.add(key)
        matches.append(data)

    priced = sum(1 for m in matches if m.get('odds_source') == 'forebet')
    print(f"   📋 Forebet {sport} {match_date}: {len(matches)} meczów "
          f"({priced} z kursami Forebet) | odrzucone: "
          f"rozpoczęte={dropped_started}, inna_data={dropped_date}, "
          f"nieparsowalne={dropped_unparsed}")
    return matches


if __name__ == '__main__':
    import argparse
    import json

    ap = argparse.ArgumentParser(description='Listuj mecze dnia z Forebet')
    ap.add_argument('--sport', default='football')
    ap.add_argument('--date', default=datetime.now().strftime('%Y-%m-%d'))
    ap.add_argument('--html', help='Sparsuj lokalny plik HTML (offline)')
    ap.add_argument('--no-puppeteer', action='store_true')
    ap.add_argument('--limit', type=int, default=10)
    args = ap.parse_args()

    raw_html = None
    if args.html:
        with open(args.html, 'r', encoding='utf-8') as fh:
            raw_html = fh.read()

    out = list_forebet_matches(
        args.sport, args.date,
        prefer_puppeteer=not args.no_puppeteer,
        html=raw_html,
        filter_by_date=not bool(raw_html),
        skip_started=not bool(raw_html),
    )
    print(json.dumps(out[:args.limit], ensure_ascii=False, indent=2))
    print(f"\nRazem: {len(out)}")
