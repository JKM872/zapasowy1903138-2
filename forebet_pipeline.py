"""
Forebet Pipeline — selekcja meczów od Forebet
=============================================
Osobny pipeline, w którym **Forebet jest źródłem selekcji**, a nie dodatkiem.

Dlaczego osobno: w głównym workflow (``scrape_and_notify.py``) lista meczów
pochodzi z Livesport, a Forebet jest tylko wzbogaceniem — pytamy go „czy masz
ten mecz?” i dopasowujemy po nazwach drużyn. To dopasowanie czasem działa,
czasem nie, i wtedy predykcja Forebet po prostu znika. Tutaj kolejność jest
odwrócona: bierzemy WSZYSTKIE mecze dnia z Forebet (z wyklikanym „More”),
odsiewamy je regułami Forebet i tylko wybrane wzbogacamy o resztę źródeł.

Przepływ:

1. **Forebet** — pełna lista meczów dnia dla sportu (``forebet_listing``).
2. **Selekcja** — pomijamy remisy (predykcja ``X``) i mecze bez wyraźnej
   przewagi jednej ze stron.
3. **Kursy** — najpierw **Pinnacle** (najniższa marża, więc kurs najbliższy
   prawdziwemu prawdopodobieństwu), a gdy nie wycenił zdarzenia, pozostali
   bukmacherzy Livesport. Brak kursu u Pinnacle i na Livesport = **skip**, bo
   bez ceny nie ma EV ani ROI. Kursy pokazywane przez Forebet lądują w polach
   ``forebet_*`` tylko do wglądu — nie wiemy, od kogo są ani jak świeże, więc
   nie decydują o progu. Próg kursowy identyczny jak w głównym workflow
   (``email_notifier._passes_sport_odds_threshold``).
4. **Livesport** — H2H i forma (ogólna + u siebie / na wyjeździe).
5. **SofaScore Fan Vote** — przez odporny wrapper ``sofascore_fanvote``.
6. **AI** — krótka analiza przez Groq (``gemini_analyzer``, Groq jako backend).
7. **Wyjście** — CSV + JSON w konwencji repo, e-mail i Telegram.

Uruchomienie:
    python forebet_pipeline.py --sport football --date 2026-09-12
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forebet_listing as fbl

SOURCE = 'forebet'

# Sporty, które Forebet publikuje i które obsługujemy równolegle w workflow.
SUPPORTED_SPORTS = [
    'football', 'basketball', 'volleyball', 'handball',
    'hockey', 'tennis', 'baseball', 'rugby',
]

# ── Progi selekcji Forebet ─────────────────────────────────────────────────
# Sens: "wybieramy mecz, gdzie jedna z drużyn ma przewagę". Przewagę mierzymy
# prawdopodobieństwem faworyta i przewagą nad drugą stroną. Sporty bez remisu
# mają wyższe progi, bo tam 50/50 jest punktem odniesienia (przy remisie w
# stawce faworyt rzadko przekracza 60%).
THREE_WAY_MIN_FAV_PROB = 45.0
THREE_WAY_MIN_GAP = 12.0
TWO_WAY_MIN_FAV_PROB = 60.0
TWO_WAY_MIN_GAP = 20.0

# ── Kursy ──────────────────────────────────────────────────────────────────
# Pinnacle ma najniższą marżę na rynku, więc jego kurs jest najbliższy
# prawdziwemu prawdopodobieństwu — dlatego jest źródłem PIERWSZEGO WYBORU dla
# progu kursowego, EV i maila. Kursy pokazywane przez Forebet zostają zapisane
# w polach ``forebet_*``, ale NIE decydują o niczym: nie wiemy, od kogo są i
# jak świeże, a od tej liczby zależy próg i EV.
PRIMARY_BOOKMAKER = 'pinnacle'

# Gdy Pinnacle nie wycenił zdarzenia, pytamy pozostałych bukmacherów Livesport
# (od najostrzejszych do najpopularniejszych). Pierwszy z ceną wygrywa.
LIVESPORT_FALLBACK_BOOKMAKERS = [
    'bet365', 'unibet', 'william_hill', 'bwin',
    'betfair', '1xbet', 'betway', 'nordicbet',
]

# Wagi scoringu — jawne, żeby dało się je zakwestionować i zmienić.
WEIGHTS = {
    'forebet': 0.34,
    'h2h': 0.22,
    'form': 0.18,
    'sofascore': 0.14,
    'odds': 0.12,
}

# H2H uznajemy za wspierające, gdy faworyt wygrał tyle bezpośrednich spotkań.
H2H_MIN_WIN_RATE = 0.55
H2H_MIN_MATCHES = 2

_GENERIC_TOKENS = {
    'fc', 'sc', 'ac', 'as', 'if', 'ff', 'sk', 'bk', 'cf', 'cd', 'ca', 'club',
    'team', 'city', 'united', 'women', 'men', 'youth', 'reserve', 'academy',
    'mecz', 'match', 'pilka', 'nozna', 'koszykowka', 'siatkowka', 'reczna',
    'hokej', 'tenis', 'baseball', 'rugby', 'https', 'http', 'www', 'livesport',
    'com', 'the', 'and',
}


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', text)
                   if not unicodedata.combining(c))


def _tokens(name: str) -> Set[str]:
    """Tokeny nazwy drużyny do dopasowania z URL-em Livesport."""
    clean = _strip_accents((name or '').lower())
    clean = re.sub(r'[^a-z0-9\s-]', ' ', clean)
    parts = re.split(r'[\s-]+', clean)
    return {p for p in parts if len(p) >= 4 and p not in _GENERIC_TOKENS}


def _two_way(sport: str) -> bool:
    return sport.lower() in fbl.TWO_WAY_SPORTS


def _implied_prob(odds: Optional[float]) -> Optional[float]:
    try:
        val = float(odds)
    except (TypeError, ValueError):
        return None
    if val <= 1.0:
        return None
    return 100.0 / val


# ---------------------------------------------------------------------------
# Krok 2: selekcja Forebet
# ---------------------------------------------------------------------------

def select_forebet_matches(matches: List[Dict[str, Any]], sport: str,
                           min_fav_prob: Optional[float] = None,
                           min_gap: Optional[float] = None,
                           ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Odsiej remisy i mecze bez wyraźnej przewagi jednej ze stron.

    Zwraca (wybrane, licznik_odrzuceń). Odrzucone mecze nie są wzbogacane —
    to właśnie oszczędność, która pozwala przeanalizować cały dzień.
    """
    two = _two_way(sport)
    if min_fav_prob is None:
        min_fav_prob = TWO_WAY_MIN_FAV_PROB if two else THREE_WAY_MIN_FAV_PROB
    if min_gap is None:
        min_gap = TWO_WAY_MIN_GAP if two else THREE_WAY_MIN_GAP

    selected: List[Dict[str, Any]] = []
    rejected: Dict[str, int] = {}

    def _reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for m in matches:
        pred = m.get('prediction')

        if not pred:
            _reject('brak_predykcji')
            continue

        # Remisy pomijamy — pipeline typuje zwycięzcę.
        if pred == 'X':
            _reject('remis')
            continue

        home_prob = m.get('home_prob')
        away_prob = m.get('away_prob')
        if home_prob is None or away_prob is None:
            # Bez liczb nie ocenimy przewagi; predykcja sama nie wystarcza.
            _reject('brak_prawdopodobienstw')
            continue

        fav_prob = max(home_prob, away_prob)
        gap = abs(home_prob - away_prob)

        # Predykcja Forebet musi wskazywać stronę z wyższym prawdopodobieństwem.
        # Rozjazd oznacza, że wiersz sparsował się niespójnie.
        expected = '1' if home_prob >= away_prob else '2'
        if pred != expected:
            _reject('predykcja_niespojna_z_prawdopodobienstwami')
            continue

        if fav_prob < min_fav_prob:
            _reject(f'faworyt_ponizej_{min_fav_prob:.0f}%')
            continue

        if gap < min_gap:
            _reject(f'przewaga_ponizej_{min_gap:.0f}pp')
            continue

        m['favorite'] = 'home' if pred == '1' else 'away'
        m['forebet_fav_prob'] = fav_prob
        m['forebet_gap'] = gap
        selected.append(m)

    return selected, rejected


# ---------------------------------------------------------------------------
# Krok 3: kursy i próg kursowy
# ---------------------------------------------------------------------------

def odds_gate(sport: str, home_odds: Any, away_odds: Any,
              min_odds: float = 0.0,
              max_odds: float = 0.0) -> Tuple[bool, Optional[str]]:
    """Sprawdź kursy tą samą zasadą co główny workflow.

    Używa ``email_notifier._passes_sport_odds_threshold`` — jedno źródło prawdy
    dla progów per sport (football 1.50, basketball 1.30, ... fallback 1.35),
    warunek AND na obu kursach. ``max_odds`` jest opcjonalnym górnym
    ograniczeniem (0 = wyłączone).

    Returns:
        (przechodzi, powód_odrzucenia)
    """
    try:
        from email_notifier import _passes_sport_odds_threshold
    except Exception as e:
        print(f"   ⚠️ Nie mogę zaimportować progu kursowego ({e}) — przepuszczam")
        return True, None

    if home_odds is None or away_odds is None:
        return False, 'brak_kursow'

    if not _passes_sport_odds_threshold(sport, home_odds, away_odds, min_odds):
        return False, 'kurs_ponizej_progu'

    if max_odds and max_odds > 0:
        try:
            if float(home_odds) > max_odds and float(away_odds) > max_odds:
                return False, 'kurs_powyzej_maksimum'
        except (TypeError, ValueError):
            pass

    return True, None


# ---------------------------------------------------------------------------
# Krok 4: Livesport (index dnia, H2H, forma, kursy)
# ---------------------------------------------------------------------------

def build_livesport_index(driver: Any, sport: str, date_str: str,
                          max_scrolls: int = 14) -> List[Dict[str, Any]]:
    """Zbierz linki meczów dnia z Livesport raz na sport (do dopasowań).

    Używa ``get_match_links_from_day()`` — tej samej funkcji, na której stoi
    główny workflow. Własna wersja (scroll + ``_extract_match_links_from_soup``)
    zwracała w CI 0 meczów, przez co nie było ani H2H, ani formy, ani kursów.
    Nie ma sensu utrzymywać drugiej implementacji listowania dnia, gdy pierwsza
    jest codziennie sprawdzana w produkcji.
    """
    try:
        from livesport_h2h_scraper import SPORT_URLS, get_match_links_from_day
    except Exception as e:
        print(f"   ⚠️ Helpery Livesport niedostępne: {e}")
        return []

    if sport.lower() not in SPORT_URLS:
        print(f"   ⚠️ Livesport nie zna sportu '{sport}'")
        return []

    try:
        links = get_match_links_from_day(driver, date_str, sports=[sport.lower()]) or []
    except Exception as e:
        print(f"   ⚠️ Livesport index ({sport}) błąd: {type(e).__name__}: {e}")
        return []

    index: List[Dict[str, Any]] = []
    for link in links:
        slug = _strip_accents(link.lower())
        toks = set(re.findall(r'[a-z]{4,}', slug)) - _GENERIC_TOKENS
        if toks:
            index.append({'url': link, 'tokens': toks})

    print(f"   📇 Livesport {sport}: {len(index)} meczów w indeksie dnia")
    return index


def match_livesport_url(home: str, away: str,
                        index: List[Dict[str, Any]]) -> Optional[str]:
    """Dopasuj mecz Forebet do URL Livesport po tokenach z obu nazw.

    Obie drużyny muszą trafić w slug. Wymóg na jedną stronę pozwalałby przypiąć
    kursy do innego meczu tej samej drużyny, a zły kurs jest gorszy niż brak
    kursu — wchodzi do progu kursowego i do scoringu.
    """
    home_tokens = _tokens(home)
    away_tokens = _tokens(away)
    if not home_tokens or not away_tokens:
        return None

    best_url, best_score = None, 0
    for entry in index:
        toks = entry['tokens']
        h_hits = len(home_tokens & toks)
        a_hits = len(away_tokens & toks)
        if not h_hits or not a_hits:
            continue
        score = h_hits + a_hits
        if score > best_score:
            best_score, best_url = score, entry['url']
    return best_url


def fetch_h2h_and_form(driver: Any, match_url: str, home_team: str,
                       sport: str) -> Dict[str, Any]:
    """H2H (do 5 spotkań) + forma z Livesport dla dopasowanego meczu."""
    out: Dict[str, Any] = {
        'h2h_last5': [], 'h2h_count': 0,
        'home_wins_in_h2h_last5': 0, 'away_wins_in_h2h_last5': 0,
        'last_h2h_date': None, 'last_h2h_score': None,
        'home_form': [], 'away_form': [],
        'home_form_home': [], 'away_form_away': [],
    }

    try:
        from bs4 import BeautifulSoup
        from livesport_h2h_scraper import (
            build_h2h_overall_url, parse_h2h_from_soup, extract_advanced_team_form,
        )
    except Exception as e:
        print(f"      ⚠️ Livesport H2H/forma niedostępne: {e}")
        return out

    # H2H — bezpośredni URL zamiast klikania zakładki (klik w headless
    # regularnie cicho zawodzi).
    try:
        h2h_url = build_h2h_overall_url(match_url) or match_url
        driver.get(h2h_url)
        time.sleep(2.0)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        h2h = parse_h2h_from_soup(soup, home_team) or []
        out['h2h_last5'] = h2h
        out['h2h_count'] = len(h2h)
        out['home_wins_in_h2h_last5'] = sum(1 for m in h2h if m.get('winner') == 'home')
        out['away_wins_in_h2h_last5'] = sum(1 for m in h2h if m.get('winner') == 'away')
        if h2h:
            out['last_h2h_date'] = h2h[0].get('date')
            out['last_h2h_score'] = h2h[0].get('score')
    except Exception as e:
        print(f"      ⚠️ H2H błąd: {e}")

    # Forma — ogólna + u siebie / na wyjeździe (to jest ta forma "po
    # naciśnięciu przycisku form": osobne podstrony /h2h/u-siebie/ itd.).
    try:
        form = extract_advanced_team_form(match_url, driver) or {}
        out['home_form'] = form.get('home_form_overall') or []
        out['away_form'] = form.get('away_form_overall') or []
        out['home_form_home'] = form.get('home_form_home') or []
        out['away_form_away'] = form.get('away_form_away') or []
    except Exception as e:
        print(f"      ⚠️ Forma błąd: {e}")

    return out


def resolve_odds(match_url: Optional[str], sport: str) -> Dict[str, Any]:
    """Pobierz kursy: najpierw Pinnacle, potem pozostali bukmacherzy Livesport.

    Pinnacle jest pytany OSOBNO i jako pierwszy, bo to jego kurs traktujemy
    jako referencyjny (najniższa marża = najbliżej prawdziwego
    prawdopodobieństwa). Dopiero gdy nie wycenił zdarzenia, schodzimy do
    reszty bukmacherów na Livesport.

    Gdy nie ma ani Pinnacle, ani żadnego innego kursu na Livesport, zwracamy
    puste kursy z ``reason='brak_kursow'`` — mecz zostanie pominięty. Bez ceny
    nie ma EV ani ROI, więc typ jest nierozliczalny.

    Returns:
        {'home_odds', 'draw_odds', 'away_odds', 'bookmaker', 'odds_source', 'reason'}
    """
    out: Dict[str, Any] = {
        'home_odds': None, 'draw_odds': None, 'away_odds': None,
        'bookmaker': None, 'odds_source': None, 'reason': None,
    }

    if not match_url:
        out['reason'] = 'brak_url_livesport'
        return out

    try:
        from livesport_odds_api import LivesportOddsAPI
    except Exception as e:
        print(f"      ⚠️ livesport_odds_api niedostępny: {e}")
        out['reason'] = 'brak_modulu_kursow'
        return out

    try:
        api = LivesportOddsAPI()
        event_id = api.extract_event_id_from_url(match_url)
        if not event_id:
            out['reason'] = 'brak_event_id'
            return out

        # 1) Pinnacle — źródło referencyjne
        for label, bookmakers in (
            (PRIMARY_BOOKMAKER, [PRIMARY_BOOKMAKER]),
            ('livesport', LIVESPORT_FALLBACK_BOOKMAKERS),
        ):
            res = api.get_odds_from_multiple_bookmakers(
                event_id, sport=sport, bookmakers=bookmakers
            ) or {}
            if res.get('success') and res.get('home_odds') is not None:
                out['home_odds'] = res.get('home_odds')
                out['draw_odds'] = res.get('draw_odds')
                out['away_odds'] = res.get('away_odds')
                out['bookmaker'] = res.get('bookmaker')
                out['odds_source'] = label
                if label == PRIMARY_BOOKMAKER:
                    print(f"      💰 Pinnacle: {out['home_odds']}/"
                          f"{out['draw_odds'] or '-'}/{out['away_odds']}")
                else:
                    print(f"      💰 Livesport ({out['bookmaker']}): "
                          f"{out['home_odds']}/{out['draw_odds'] or '-'}/{out['away_odds']}")
                return out

        out['reason'] = 'brak_kursow'
        print("      ⛔ Brak kursów: ani Pinnacle, ani inny bukmacher Livesport")
    except Exception as e:
        print(f"      ⚠️ Kursy błąd: {type(e).__name__}: {e}")
        out['reason'] = 'blad_pobierania_kursow'

    return out


# ---------------------------------------------------------------------------
# Krok 6: AI (Groq)
# ---------------------------------------------------------------------------

def run_ai_analysis(row: Dict[str, Any]) -> Dict[str, Any]:
    """Krótka analiza AI. Groq jest backendem (GROQ_API_KEY w secrets)."""
    out = {
        'gemini_prediction': None, 'gemini_confidence': None,
        'gemini_reasoning': None, 'gemini_recommendation': None,
    }
    try:
        from gemini_analyzer import analyze_match
        from livesport_h2h_scraper import format_form_as_score
    except Exception as e:
        print(f"      ⚠️ Analizator AI niedostępny: {e}")
        return out

    h2h_data = {
        'home_wins': row.get('home_wins_in_h2h_last5', 0),
        'away_wins': row.get('away_wins_in_h2h_last5', 0),
        'draws': max(0, (row.get('h2h_count') or 0)
                     - (row.get('home_wins_in_h2h_last5') or 0)
                     - (row.get('away_wins_in_h2h_last5') or 0)),
        'total': row.get('h2h_count', 0),
    }

    fav = 'gospodarze' if row.get('favorite') == 'home' else 'goście'
    extra = (f"Źródło selekcji: Forebet ({fav} faworytem, "
             f"{row.get('forebet_fav_prob')}% vs przewaga "
             f"{row.get('forebet_gap')}pp). Liga: {row.get('league') or 'n/d'}. "
             f"Fan Vote: {row.get('sofascore_home_win_prob')}%/"
             f"{row.get('sofascore_away_win_prob')}% "
             f"({row.get('sofascore_total_votes') or 0} głosów).")

    try:
        res = analyze_match(
            home_team=row['home_team'],
            away_team=row['away_team'],
            sport=row.get('sport', 'football'),
            h2h_data=h2h_data,
            home_form=format_form_as_score(row.get('home_form') or []),
            away_form=format_form_as_score(row.get('away_form') or []),
            home_form_away=format_form_as_score(row.get('home_form_home') or []),
            away_form_away=format_form_as_score(row.get('away_form_away') or []),
            forebet_prediction=(f"{row.get('forebet_fav_prob')}% "
                                f"{'home' if row.get('favorite') == 'home' else 'away'} win"),
            home_odds=row.get('home_odds'),
            away_odds=row.get('away_odds'),
            draw_odds=row.get('draw_odds'),
            additional_info=extra,
        ) or {}
        out['gemini_prediction'] = res.get('prediction')
        out['gemini_confidence'] = res.get('confidence')
        out['gemini_reasoning'] = res.get('reasoning')
        out['gemini_recommendation'] = res.get('recommendation')
    except Exception as e:
        print(f"      ⚠️ AI błąd: {e}")

    return out


# ---------------------------------------------------------------------------
# Scoring i kwalifikacja
# ---------------------------------------------------------------------------

def score_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Policz wsparcie dla typu Forebet z dostępnych źródeł.

    Każdy komponent zwraca 0..1 dla strony typowanej przez Forebet. Wagi są w
    ``WEIGHTS``. Komponenty bez danych nie są liczone, a wagi normalizowane —
    inaczej brak Fan Vote wyglądałby jak głos przeciw.
    """
    fav_home = row.get('favorite') == 'home'
    parts: Dict[str, float] = {}

    fav_prob = row.get('forebet_fav_prob')
    if fav_prob is not None:
        parts['forebet'] = min(1.0, float(fav_prob) / 100.0)

    h2h_total = row.get('h2h_count') or 0
    if h2h_total >= H2H_MIN_MATCHES:
        fav_wins = (row.get('home_wins_in_h2h_last5') if fav_home
                    else row.get('away_wins_in_h2h_last5')) or 0
        parts['h2h'] = fav_wins / h2h_total

    fav_form = (row.get('home_form') if fav_home else row.get('away_form')) or []
    dog_form = (row.get('away_form') if fav_home else row.get('home_form')) or []
    if fav_form and dog_form:
        def _pts(form: List[str]) -> float:
            return sum(3 if r == 'W' else (1 if r == 'D' else 0) for r in form) / (3 * len(form))
        fav_pts, dog_pts = _pts(fav_form), _pts(dog_form)
        # 0.5 = równo; przewaga formy faworyta przesuwa w górę.
        parts['form'] = max(0.0, min(1.0, 0.5 + (fav_pts - dog_pts) / 2))

    ss_home = row.get('sofascore_home_win_prob')
    ss_away = row.get('sofascore_away_win_prob')
    if ss_home is not None and ss_away is not None:
        try:
            fav_vote = float(ss_home) if fav_home else float(ss_away)
            parts['sofascore'] = max(0.0, min(1.0, fav_vote / 100.0))
        except (TypeError, ValueError):
            pass

    fav_odds = row.get('home_odds') if fav_home else row.get('away_odds')
    imp = _implied_prob(fav_odds)
    if imp is not None:
        parts['odds'] = max(0.0, min(1.0, imp / 100.0))

    total_weight = sum(WEIGHTS[k] for k in parts)
    score = (sum(WEIGHTS[k] * v for k, v in parts.items()) / total_weight) if total_weight else 0.0

    row['scoring_components'] = {k: round(v, 3) for k, v in parts.items()}
    row['scoring_sources'] = len(parts)
    row['scoring_pick'] = '1' if fav_home else '2'
    row['scoring_prob'] = round(score * 100, 1)
    row['advanced_score'] = round(score * 100, 1)

    # EV liczone kursem faworyta; bez kursu nie ma EV i tego nie udajemy.
    if fav_odds:
        try:
            row['scoring_ev'] = round(score * float(fav_odds) - 1, 3)
            row['scoring_edge'] = round(score * 100 - (imp or 0), 1)
        except (TypeError, ValueError):
            row['scoring_ev'] = None
            row['scoring_edge'] = None
    else:
        row['scoring_ev'] = None
        row['scoring_edge'] = None

    return row


def apply_qualification(row: Dict[str, Any], min_score: float,
                        min_sources: int) -> Dict[str, Any]:
    """Ustaw flagi kwalifikacji + powody odrzucenia (jawne, nie milczące)."""
    reasons: List[str] = []

    if row.get('skip_reason'):
        reasons.append(row['skip_reason'])

    score = row.get('scoring_prob') or 0
    if score < min_score:
        reasons.append(f'score_{score}<{min_score}')

    if (row.get('scoring_sources') or 0) < min_sources:
        reasons.append(f"zrodla_{row.get('scoring_sources')}<{min_sources}")

    # H2H nie ma tu osobnej bramki: wchodzi do score z wagą WEIGHTS['h2h'],
    # więc odrzucanie po nim drugi raz karałoby ten sam sygnał dwukrotnie.

    row['skip_reasons'] = reasons
    row['qualifies'] = not reasons

    # E-mail ignoruje Fan Vote (jak w głównym pipeline), kanał go uwzględnia.
    row['email_qualifies'] = row['qualifies']
    row['channel_qualifies'] = row['qualifies'] and bool(row.get('sofascore_found'))
    return row


# ---------------------------------------------------------------------------
# Wyjście
# ---------------------------------------------------------------------------

def write_outputs(rows: List[Dict[str, Any]], sport: str,
                  date_str: str) -> Dict[str, str]:
    """CSV (dla e-maila) + JSON (dla frontendu), nazwy z sufiksem ``forebet``."""
    os.makedirs('outputs', exist_ok=True)
    os.makedirs('results', exist_ok=True)

    csv_path = os.path.join('outputs', f'forebet_{sport}_{date_str}.csv')
    json_path = os.path.join('results', f'matches_{date_str}_{sport}_forebet.json')

    list_cols = ('h2h_last5', 'home_form', 'away_form', 'home_form_home',
                 'away_form_away', 'skip_reasons', 'scoring_components',
                 'data_quality', 'availability', 'explanation')
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        for col in list_cols:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: str(x) if isinstance(x, (list, dict)) else x)
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    except Exception as e:
        print(f"   ⚠️ CSV (pandas) nieudany, zapis minimalny: {e}")
        import csv as _csv
        if rows:
            keys = sorted({k for r in rows for k in r.keys()})
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as fh:
                w = _csv.DictWriter(fh, fieldnames=keys)
                w.writeheader()
                for r in rows:
                    w.writerow({k: (str(r.get(k)) if isinstance(r.get(k), (list, dict))
                                    else r.get(k)) for k in keys})

    frontend = {
        'date': date_str,
        'sport': sport,
        'source': SOURCE,
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'matches': [
            {
                'homeTeam': r.get('home_team'),
                'awayTeam': r.get('away_team'),
                'time': r.get('match_time'),
                'league': r.get('league'),
                'country': r.get('country'),
                'source': SOURCE,
                'matchUrl': r.get('match_url'),
                'forebetUrl': r.get('forebet_url'),
                'qualifies': bool(r.get('qualifies')),
                'channelQualifies': bool(r.get('channel_qualifies')),
                'emailQualifies': bool(r.get('email_qualifies')),
                'skipReasons': r.get('skip_reasons') or [],
                'forebet': {
                    'prediction': r.get('forebet_prediction'),
                    'probability': r.get('forebet_probability'),
                    'homeProb': r.get('forebet_home_prob'),
                    'drawProb': r.get('forebet_draw_prob'),
                    'awayProb': r.get('forebet_away_prob'),
                    'exactScore': r.get('forebet_exact_score'),
                    'avgGoals': r.get('forebet_avg_goals'),
                    'favorite': r.get('favorite'),
                    'gap': r.get('forebet_gap'),
                },
                'h2h': {
                    'total': r.get('h2h_count'),
                    'homeWins': r.get('home_wins_in_h2h_last5'),
                    'awayWins': r.get('away_wins_in_h2h_last5'),
                    'lastDate': r.get('last_h2h_date'),
                    'lastScore': r.get('last_h2h_score'),
                },
                'form': {
                    'home': r.get('home_form'),
                    'away': r.get('away_form'),
                    'homeAtHome': r.get('home_form_home'),
                    'awayAtAway': r.get('away_form_away'),
                },
                'sofascore': {
                    'found': r.get('sofascore_found'),
                    'votes': r.get('sofascore_total_votes'),
                    'unavailable': r.get('sofascore_unavailable'),
                    'skipReason': r.get('sofascore_skip_reason'),
                },
                'odds': {
                    'home': r.get('home_odds'),
                    'draw': r.get('draw_odds'),
                    'away': r.get('away_odds'),
                    # 'pinnacle' albo 'livesport' — po czym widać, czy kurs
                    # jest referencyjny, czy z fallbacku.
                    'source': r.get('odds_source'),
                    'bookmaker': r.get('bookmaker'),
                    'note': r.get('odds_note'),
                    # Kursy Forebet trzymane obok, do porównania. Nie wchodzą
                    # do progu ani EV.
                    'forebet': {
                        'home': r.get('forebet_home_odds'),
                        'draw': r.get('forebet_draw_odds'),
                        'away': r.get('forebet_away_odds'),
                    },
                },
                'ai': {
                    'prediction': r.get('gemini_prediction'),
                    'confidence': r.get('gemini_confidence'),
                    'recommendation': r.get('gemini_recommendation'),
                    'reasoning': r.get('gemini_reasoning'),
                },
                'scoring': {
                    'pick': r.get('scoring_pick'),
                    'prob': r.get('scoring_prob'),
                    'ev': r.get('scoring_ev'),
                    'edge': r.get('scoring_edge'),
                    'sources': r.get('scoring_sources'),
                    'components': r.get('scoring_components'),
                },
                'predictionGrade': r.get('prediction_grade'),
                'dataQuality': r.get('data_quality'),
            }
            for r in rows
        ],
    }
    with open(json_path, 'w', encoding='utf-8') as fh:
        json.dump(frontend, fh, ensure_ascii=False, indent=2, default=str)

    return {'csv': csv_path, 'json': json_path}


# ---------------------------------------------------------------------------
# Orkiestracja
# ---------------------------------------------------------------------------

def run(sport: str, date_str: str, max_matches: Optional[int] = None,
        min_odds: float = 0.0, max_odds: float = 0.0,
        min_score: float = 55.0, min_sources: int = 2,
        use_sofascore: bool = True, use_ai: bool = True,
        use_livesport: bool = True, headless: bool = True,
        send_email: bool = True, send_telegram: bool = False,
        email_cfg: Optional[Dict[str, str]] = None,
        prefer_puppeteer: bool = True,
        load_more_clicks: int = 25) -> Dict[str, Any]:
    """Przejdź cały pipeline dla jednego sportu."""
    sport = sport.lower()
    print('=' * 70)
    print(f"🎯 FOREBET PIPELINE — {sport.upper()} — {date_str}")
    print('=' * 70)

    # ── FAZA 1: lista meczów z Forebet ──
    print("\n[1/6] Forebet — lista meczów dnia")
    all_matches = fbl.list_forebet_matches(
        sport, date_str,
        prefer_puppeteer=prefer_puppeteer,
        load_more_clicks=load_more_clicks,
    )
    if not all_matches:
        print(f"❌ Forebet {sport}: brak meczów — koniec")
        paths = write_outputs([], sport, date_str)
        return {'sport': sport, 'date': date_str, 'forebet_total': 0,
                'selected': 0, 'qualified': 0, 'outputs': paths}

    # ── FAZA 2: selekcja (bez remisów, z przewagą) ──
    print("\n[2/6] Selekcja Forebet (bez remisów, wymagana przewaga)")
    selected, rejected = select_forebet_matches(all_matches, sport)
    print(f"   ✅ Wybrane: {len(selected)}/{len(all_matches)}")
    for reason, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
        print(f"      ↳ odrzucone [{reason}]: {count}")

    if max_matches:
        selected = selected[:max_matches]
        print(f"   ✂️ Ograniczono do {len(selected)} meczów (--max-matches)")

    if not selected:
        paths = write_outputs([], sport, date_str)
        return {'sport': sport, 'date': date_str, 'forebet_total': len(all_matches),
                'selected': 0, 'qualified': 0, 'outputs': paths}

    # ── FAZA 3: kursy Forebet tylko do wglądu ──
    # Kursy widoczne na Forebet NIE decydują o niczym: nie wiemy, od którego
    # bukmachera pochodzą ani jak są świeże, a od tej liczby zależy próg
    # kursowy i EV. Odsianie meczu na ich podstawie mogłoby wyrzucić zdarzenie,
    # które u Pinnacle mieści się w progu. Zostają zapisane w polach
    # `forebet_*` do porównania, a rozstrzyga Pinnacle (FAZA 4).
    survivors = selected
    forebet_priced = sum(1 for m in selected if m.get('odds_source') == 'forebet')
    print(f"\n[3/6] Kursy Forebet: {forebet_priced}/{len(selected)} zdarzeń wycenionych "
          f"(tylko do wglądu — o progu decyduje Pinnacle)")

    # ── FAZA 4: Livesport (index, H2H, forma, kursy) ──
    driver = None
    index: List[Dict[str, Any]] = []
    if use_livesport and survivors:
        print("\n[4/6] Livesport — H2H, forma, kursy")
        try:
            from livesport_h2h_scraper import start_driver
            driver = start_driver(headless=headless)
            index = build_livesport_index(driver, sport, date_str)
        except Exception as e:
            print(f"   ⚠️ Livesport driver nie wystartował: {e}")
            driver = None
    else:
        print("\n[4/6] Livesport — pominięty")

    rows: List[Dict[str, Any]] = []

    for i, m in enumerate(survivors, 1):
        home, away = m['home_team'], m['away_team']
        print(f"\n   [{i}/{len(survivors)}] {home} vs {away} "
              f"({m.get('match_time') or '??:??'}, {m.get('league') or 'n/d'})")

        row: Dict[str, Any] = {
            'sport': sport,
            'source': SOURCE,
            'home_team': home,
            'away_team': away,
            'match_time': m.get('match_time'),
            'match_date': m.get('match_date') or date_str,
            'league': m.get('league'),
            'country': m.get('country'),
            'forebet_url': m.get('forebet_url'),
            'forebet_id': m.get('forebet_id'),
            'match_url': None,
            'favorite': m.get('favorite'),
            'forebet_fav_prob': m.get('forebet_fav_prob'),
            'forebet_gap': m.get('forebet_gap'),
            'forebet_prediction': m.get('prediction'),
            'forebet_probability': m.get('probability'),
            'forebet_home_prob': m.get('home_prob'),
            'forebet_draw_prob': m.get('draw_prob'),
            'forebet_away_prob': m.get('away_prob'),
            'forebet_exact_score': m.get('exact_score'),
            'forebet_avg_goals': m.get('avg_goals'),
            # Kursy Forebet — wyłącznie do wglądu/porównania. O progu, EV i
            # mailu decydują `home_odds`/`away_odds` z Pinnacle (lub innego
            # bukmachera Livesport), ustawiane poniżej.
            'forebet_home_odds': m.get('home_odds'),
            'forebet_draw_odds': m.get('draw_odds'),
            'forebet_away_odds': m.get('away_odds'),
            'forebet_odds_note': m.get('odds_note'),
            'home_odds': None,
            'draw_odds': None,
            'away_odds': None,
            'odds_source': None,
            'bookmaker': None,
            # Forma pochodzi wyłącznie z Livesport (Forebet jej nie publikuje
            # na stronie przeglądowej) — puste listy oznaczają "jeszcze nie
            # pobrano", a brak dopasowania w Livesport zostawia je puste.
            'home_form': [],
            'away_form': [],
            'home_form_home': [],
            'away_form_away': [],
            'h2h_last5': [], 'h2h_count': 0,
            'home_wins_in_h2h_last5': 0, 'away_wins_in_h2h_last5': 0,
            'last_h2h_date': None, 'last_h2h_score': None,
            'skip_reason': None,
        }

        # Livesport: dopasowanie + H2H/forma/kursy
        if driver is not None:
            ls_url = match_livesport_url(home, away, index)
            row['match_url'] = ls_url
            if ls_url:
                print(f"      🔗 Livesport: {ls_url}")
                enrich = fetch_h2h_and_form(driver, ls_url, home, sport)
                for key, val in enrich.items():
                    if val:
                        row[key] = val

                # Kursy: Pinnacle jako pierwszy, potem reszta Livesport.
                odds = resolve_odds(ls_url, sport)
                row['home_odds'] = odds.get('home_odds')
                row['draw_odds'] = odds.get('draw_odds')
                row['away_odds'] = odds.get('away_odds')
                row['odds_source'] = odds.get('odds_source')
                row['bookmaker'] = odds.get('bookmaker')
                row['odds_note'] = odds.get('reason')
            else:
                print("      ⚠️ Brak dopasowania w Livesport (bez H2H/formy/kursów)")
                row['odds_note'] = 'brak_url_livesport'

        # Próg kursowy na kursach Pinnacle/Livesport. Brak kursów = skip:
        # bez ceny nie ma EV ani ROI, wiec typ jest nierozliczalny.
        ok, reason = odds_gate(sport, row.get('home_odds'), row.get('away_odds'),
                               min_odds, max_odds)
        if not ok:
            row['skip_reason'] = reason
            print(f"      ⛔ {reason} (H={row.get('home_odds')}, A={row.get('away_odds')}"
                  f", źródło={row.get('odds_source') or 'brak'})")

        # Fan Vote — tylko dla meczów, które jeszcze są w grze
        if use_sofascore and not row['skip_reason']:
            try:
                import sofascore_fanvote as fanvote
                vote = fanvote.get_fan_vote(home, away, sport, date_str)
                row.update(vote)
                if vote.get('sofascore_found'):
                    print(f"      🗳️ Fan Vote: {vote['sofascore_home_win_prob']}% / "
                          f"{vote['sofascore_away_win_prob']}% "
                          f"({vote['sofascore_total_votes']} głosów)")
                else:
                    print(f"      🗳️ Fan Vote: brak ({vote.get('sofascore_skip_reason')})")
            except Exception as e:
                print(f"      ⚠️ Fan Vote wrapper błąd: {e}")

        # AI — krótka analiza
        if use_ai and not row['skip_reason']:
            row.update(run_ai_analysis(row))
            if row.get('gemini_recommendation'):
                print(f"      🤖 AI: {row['gemini_recommendation']} "
                      f"({row.get('gemini_confidence')}%)")

        score_row(row)
        apply_qualification(row, min_score, min_sources)

        try:
            from prediction_data_contract import enrich_match_with_contract
            enrich_match_with_contract(row)
        except Exception as e:
            print(f"      ⚠️ Kontrakt danych błąd: {e}")

        flag = '✅' if row['qualifies'] else '⛔'
        print(f"      {flag} score={row['scoring_prob']} "
              f"grade={row.get('prediction_grade')} "
              f"źródła={row['scoring_sources']}"
              + (f" | {row['skip_reasons']}" if row['skip_reasons'] else ''))

        rows.append(row)

    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass

    # ── FAZA 5: wyjście ──
    print("\n[5/6] Zapis wyników")
    paths = write_outputs(rows, sport, date_str)
    print(f"   💾 {paths['csv']}")
    print(f"   💾 {paths['json']}")

    try:
        import sofascore_fanvote as fanvote
        fanvote.print_summary()
    except Exception:
        pass

    # ── FAZA 6: powiadomienia ──
    print("\n[6/6] Powiadomienia")
    qualified = sum(1 for r in rows if r.get('qualifies'))

    if send_email and email_cfg and email_cfg.get('to') and email_cfg.get('from'):
        try:
            from email_notifier import send_email_notification
            send_email_notification(
                csv_file=paths['csv'],
                to_email=email_cfg['to'],
                from_email=email_cfg['from'],
                password=email_cfg.get('password', ''),
                provider=email_cfg.get('provider', 'gmail'),
                subject=f"🎯 Forebet {sport.title()} — {date_str}",
                date=date_str,
                # Bez kursu nie ma EV ani ROI, więc typ jest nierozliczalny.
                skip_no_odds=True,
                min_odds_threshold=min_odds,
                grade_filter={'A', 'B'},
                fallback_grades={'C', 'D'},
            )
            print("   ✅ E-mail wysłany (Grade A/B → C/D)")
        except Exception as e:
            print(f"   ⚠️ E-mail błąd: {e}")
    elif send_email:
        print("   ℹ️ E-mail pominięty (brak --to/--from-email)")

    if send_telegram:
        try:
            from telegram_notifier import send_telegram_summary
            cq = sum(1 for r in rows if r.get('channel_qualifies'))
            send_telegram_summary(rows, cq, date_str)
            print("   ✅ Telegram wysłany")
        except Exception as e:
            print(f"   ⚠️ Telegram błąd: {e}")

    summary = {
        'sport': sport,
        'date': date_str,
        'forebet_total': len(all_matches),
        'selected': len(selected),
        'processed': len(rows),
        'qualified': qualified,
        'channel_qualified': sum(1 for r in rows if r.get('channel_qualifies')),
        'with_odds': sum(1 for r in rows if r.get('home_odds') is not None),
        'odds_pinnacle': sum(1 for r in rows if r.get('odds_source') == PRIMARY_BOOKMAKER),
        'odds_livesport_fallback': sum(1 for r in rows if r.get('odds_source') == 'livesport'),
        'skipped_no_odds': sum(1 for r in rows if r.get('skip_reason') == 'brak_kursow'),
        'with_h2h': sum(1 for r in rows if (r.get('h2h_count') or 0) > 0),
        'with_fanvote': sum(1 for r in rows if r.get('sofascore_found')),
        'with_ai': sum(1 for r in rows if r.get('gemini_recommendation')),
        'rejected_by_forebet_rules': rejected,
        'outputs': paths,
    }

    print('\n' + '=' * 70)
    print(f"🎯 KONIEC {sport.upper()} — {qualified} kwalifikujących się "
          f"z {len(rows)} przetworzonych ({len(all_matches)} na Forebet)")
    print(f"   kursy={summary['with_odds']} "
          f"(Pinnacle={summary['odds_pinnacle']}, "
          f"inni Livesport={summary['odds_livesport_fallback']}, "
          f"bez kursów={summary['skipped_no_odds']}) "
          f"h2h={summary['with_h2h']} "
          f"fanvote={summary['with_fanvote']} ai={summary['with_ai']}")
    print('=' * 70)

    with open(os.path.join('outputs', f'forebet_summary_{sport}_{date_str}.json'),
              'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)

    return summary


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Forebet Pipeline — selekcja meczów od Forebet')
    ap.add_argument('--sport', default='football',
                    help=f"Sport ({', '.join(SUPPORTED_SPORTS)})")
    ap.add_argument('--date', default=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                    help='Data YYYY-MM-DD (domyślnie dziś UTC)')
    ap.add_argument('--max-matches', type=int, default=None,
                    help='Ogranicz liczbę analizowanych meczów (testy)')
    ap.add_argument('--min-odds', type=float, default=0.0,
                    help='Dodatkowy dolny próg kursu (0 = tylko próg per sport)')
    ap.add_argument('--max-odds', type=float, default=0.0,
                    help='Górne ograniczenie kursu (0 = wyłączone)')
    ap.add_argument('--min-score', type=float, default=55.0,
                    help='Minimalny score, by mecz się kwalifikował')
    ap.add_argument('--min-sources', type=int, default=2,
                    help='Minimalna liczba źródeł w scoringu')
    ap.add_argument('--load-more-clicks', type=int, default=25,
                    help='Maks. kliknięć "More" na Forebet')
    ap.add_argument('--no-puppeteer', action='store_true',
                    help='Nie używaj Puppeteera (mniej meczów: brak "More")')
    ap.add_argument('--no-livesport', action='store_true', help='Bez H2H/formy')
    ap.add_argument('--no-sofascore', action='store_true', help='Bez Fan Vote')
    ap.add_argument('--no-ai', action='store_true', help='Bez analizy AI')
    ap.add_argument('--headless', action='store_true', default=True)
    ap.add_argument('--no-headless', dest='headless', action='store_false')
    ap.add_argument('--to', default=os.getenv('EMAIL_RECIPIENT', ''))
    ap.add_argument('--from-email', default=os.getenv('EMAIL_SENDER', ''))
    ap.add_argument('--password', default=os.getenv('EMAIL_PASSWORD', ''))
    ap.add_argument('--provider', default='gmail')
    ap.add_argument('--no-email', action='store_true')
    ap.add_argument('--telegram', action='store_true',
                    help='Wyślij podsumowanie na Telegram')
    args = ap.parse_args()

    if args.sport not in SUPPORTED_SPORTS:
        print(f"⚠️ Sport '{args.sport}' nie jest na liście {SUPPORTED_SPORTS} "
              f"— próbuję mimo to")

    summary = run(
        sport=args.sport,
        date_str=args.date,
        max_matches=args.max_matches,
        min_odds=args.min_odds,
        max_odds=args.max_odds,
        min_score=args.min_score,
        min_sources=args.min_sources,
        use_sofascore=not args.no_sofascore,
        use_ai=not args.no_ai,
        use_livesport=not args.no_livesport,
        headless=args.headless,
        send_email=not args.no_email,
        send_telegram=args.telegram,
        email_cfg={
            'to': args.to,
            'from': args.from_email,
            'password': args.password,
            'provider': args.provider,
        },
        prefer_puppeteer=not args.no_puppeteer,
        load_more_clicks=args.load_more_clicks,
    )
    print(json.dumps({k: v for k, v in summary.items() if k != 'outputs'},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
