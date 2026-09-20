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
from typing import Any, Dict, List, Optional, Set, Tuple  # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forebet_listing as fbl

SOURCE = 'forebet'

# Sporty, które Forebet publikuje i które obsługujemy równolegle w workflow.
SUPPORTED_SPORTS = [
    'football', 'basketball', 'volleyball', 'handball',
    'hockey', 'tennis', 'baseball', 'rugby',
]

# ── Progi selekcji Forebet ─────────────────────────────────────────────────
# Sporty z remisem: faworyt musi mieć sensowną przewagę, bo przy trzech wynikach
# 40% nie znaczy jeszcze "wskazany zwycięzca".
# Przy trzech wynikach faworytem jest się już od ~34% (100/3 = 33,3), a remisy
# odsiewa wcześniej `pred == 'X'`. Próg 45% wyrzucał 304 z 930 meczów piłki
# (13.09) tylko za to, że prawdopodobieństwo dzieliło się na trzy wyniki — choć
# Forebet jasno wskazywał stronę i była nad kim mieć przewagę.
#
# Przewaga: liczona jako |home - away|, więc remis jej nie rozcieńcza. Wymóg
# 12pp odrzucał kolejne 14 meczów. Zdjęty — wystarczy, że Forebet wskazuje
# stronę z wyższym prawdopodobieństwem (pilnuje tego `pred == expected`),
# a o jakości meczu decydują dalej: lepsza forma faworyta, próg kursu i scoring.
#
# UWAGA co do skutku: dla piłki, tenisa i piłki ręcznej to zmiana prawie
# bezskutkowa, bo te sporty i tak uderzają w limit 200/sport i wypełniają go
# najlepszymi kandydatami. Realnie zyskują sporty z MAŁĄ pulą, gdzie limit nie
# jest wąskim gardłem — 13.09 było ich sporo: koszykówka 4 zdarzenia,
# siatkówka 13, rugby 10, baseball 15, hokej 22.
THREE_WAY_MIN_FAV_PROB = float(os.getenv('FOREBET_MIN_FAV_3WAY', '34'))
THREE_WAY_MIN_GAP = float(os.getenv('FOREBET_MIN_GAP_3WAY', '0'))

# Sporty bez remisu (tenis, koszykówka, siatkówka, baseball): próg 52%.
#
# Historia tego progu: najpierw 60% (mój dobór, odsiewał 10 z 15 meczów
# koszykówki), potem zdjęty do 0. Teraz 52% — i to NIE jest zaostrzenie
# w praktyce, a podłoga dla powiększonej puli.
#
# Dlaczego: przy limicie 60/sport tenis i tak brał tylko najlepszych, a
# najsłabszy faworyt w puli 60 z 13.09 miał 55% — próg 0 nic nie wnosił, bo
# obcinał go limit. Po podniesieniu limitu do 200 pula sięga niżej, aż do
# okolic 50%, czyli do rzutu monetą. 52% wpuszcza „ryzykowne, ale realne"
# (48/52), a zatrzymuje 50/50.
#
# Przy dwóch wynikach 52% to automatycznie 4 pp przewagi, więc osobny próg
# przewagi jest zbędny.
TWO_WAY_MIN_FAV_PROB = float(os.getenv('FOREBET_MIN_FAV_2WAY', '52'))
TWO_WAY_MIN_GAP = float(os.getenv('FOREBET_MIN_GAP_2WAY', '0'))

# Faworyt musi być w lepszej formie niż przeciwnik.
#
# Sprawdzane dopiero po wzbogaceniu, bo forma pochodzi z Livesport (a jako
# zapas z Forebet). Gdy formy nie znamy dla ŻADNEJ ze stron, mecz nie jest
# odrzucany — brak danych to nie dowód przeciw. Taki wiersz dostaje
# `form_unknown`, żeby dało się policzyć, jak często to się zdarza.
REQUIRE_FORM_ADVANTAGE = True

# Minimalny score, by mecz wszedł do maila.
#
# Było 55 — liczba wzięta przeze mnie z powietrza, nigdy nie ustalana. Pomiar
# na 1571 meczach z 4 najnowszych dni pokazał, że to NAJWIĘKSZE wąskie gardło:
# 190 meczów przechodziło WSZYSTKIE pozostałe reguły i ginęło wyłącznie na tym
# progu (mediana ich score: 48,9).
#
# Obniżone do 50. Odzyskuje 84 z tych 190 (~21/dzień), a grupa trzyma jakość:
# 67% ma dodatnie EV, średnio 3,9 źródła, 48 z 84 ma ≥4 źródła.
#
# Dlaczego nie niżej: przy 45 odzyskalibyśmy 148, ale sięgnęlibyśmy w przedział
# 36–45, czyli poniżej rzutu monetą. 50 jest granicą, poniżej której model nie
# ma już nic do powiedzenia.
DEFAULT_MIN_SCORE = float(os.getenv('FOREBET_MIN_SCORE', '50'))

# ── Marża bukmachera jako miara powagi rynku ───────────────────────────────
#
# Odpowiedź na „widzę jakieś losowe ligi". Nie robimy listy lig — byłaby
# ułomna (setki lig, ciągłe zmiany) i subiektywna. Zamiast tego pytamy rynek:
# bukmacher rozszerza marżę dokładnie tam, gdzie ma mało pewności i płynności,
# czyli w ligach egzotycznych. To sygnał obiektywny, darmowy (mamy już kursy)
# i działa dla każdego kraju i sportu bez utrzymywania czegokolwiek.
#
# Pomiar na zakwalifikowanych meczach z 4 dni (marża = suma 1/kurs - 1):
#     4.3%  EFL Cup            13.0%  Prva Liga (Serbia)
#     4.7%  La Liga            13.2%  Division 2 Norrland (Szwecja)
#     6.1%  Premiership (SCO)  13.3%  Primera C Metropolitana (Argentyna)
#     7.1%  Championship       13.6%  Prva Liga RS (Bośnia)
#     7.4%  3. Liga (GER)      16.3%  Serie D Group I (Włochy)
#
# PROGI SĄ PER SPORT, bo naturalna marża zależy i od liczby wyników, i od
# rynku. Zaczynałem od dwóch progów (2-way / 3-way) i to był błąd: wspólny próg
# 12% dla rynków dwuwynikowych wyrzucał MLB, NPB i KBO — najlepsze ligi
# baseballu na świecie — bo moneyline w baseballu ma marże 10–14%, znacznie
# szersze niż tenis (3,4–9,2%). Kalibracja z realnych danych, per sport.
#
# Dlaczego dla piłki 13%, a nie 12%: próg 12% ucinał ją z 32 do 14 i zabierał
# ligi, które NIE są losowe — TFF 1. Lig (12,2%), czeską Division A (12,2%),
# izraelską Liga Leumit (12,6%), kazachską Premier League (12,6%). Granica
# egzotyki leży wyżej: od 13% w górę to już Serie D, Landesliga Burgenland,
# szwedzka Division 2 i bośniacka Prva Liga RS.
#
# Baseball ma 16%, czyli praktycznie wyłączone: w danych nie było ANI JEDNEJ
# egzotycznej ligi baseballu (wszystko to MLB/NPB/KBO), więc nie ma tu czego
# odsiewać i lepiej nie udawać, że jest.
#
# 0 = wyłączone dla danego sportu.
MAX_MARGIN_BY_SPORT = {
    'football': 13.0,    # egzotyka realnie występuje — Serie D, Landesliga
    'hockey': 13.0,      # odsiewa ligi juniorskie (ELJ 13,3%)
    'handball': 13.0,
    'rugby': 13.0,
    'tennis': 11.0,      # obserwowane 3,4–9,2%, więc próg z zapasem
    'basketball': 10.0,  # obserwowane 1,0–8,0%
    'volleyball': 11.0,  # obserwowane 8,2–9,8%
    'baseball': 16.0,    # MLB/NPB/KBO siegaja 14% — nie karzemy ich
}
MAX_MARGIN_DEFAULT = float(os.getenv('FOREBET_MAX_MARGIN_DEFAULT', '13'))


def max_margin_for(sport: str) -> float:
    """Próg marży dla sportu. Env ``FOREBET_MAX_MARGIN_<SPORT>`` nadpisuje."""
    sport = (sport or '').lower()
    env = os.getenv(f'FOREBET_MAX_MARGIN_{sport.upper()}')
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return MAX_MARGIN_BY_SPORT.get(sport, MAX_MARGIN_DEFAULT)


def bookmaker_margin(row: Dict[str, Any]) -> Optional[float]:
    """Marża bukmachera w punktach procentowych (overround).

    ``suma(1/kurs) - 1``. Dla uczciwego rynku bez marży dałoby 0%.
    None, gdy mamy mniej niż dwa kursy — wtedy nie ma czego liczyć i mecz NIE
    jest za to karany.
    """
    odds = [row.get('home_odds'), row.get('draw_odds'), row.get('away_odds')]
    vals = [v for v in odds if isinstance(v, (int, float)) and v > 1]
    if len(vals) < 2:
        return None
    return (sum(1.0 / v for v in vals) - 1.0) * 100.0

# Ile meczów na sport dostaje krótką analizę AI.
#
# Limit istnieje, bo analiza konkurowała o ten sam budżet Groq co DOPASOWANIE
# meczów do Livesport — i wygrywała, bo woła raz na mecz. Przy 60 meczach × 8
# sportów to blisko 500 zapytań, przy 30 na minutę i 1K na dobę. Skutek widać
# było w logu: „Groq [groq/compound]: limit (429)" na wszystkich modelach, więc
# dopasowanie nie dostawało już nic.
#
# Priorytet jest jasny: dopasowanie odblokowuje kursy, czyli decyduje, czy mecz
# w ogóle wejdzie do maila. Analiza AI to jeden z pięciu składników scoringu i
# jej brak nie zmniejsza liczby źródeł w scoringu — obniża tylko ocenę.
AI_ANALYSIS_MAX_PER_SPORT = 12

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

# Ile meczów maksymalnie wzbogacamy na sport.
#
# Odkąd getrs.php oddaje cały dzień, sama piłka nożna daje ~1400 meczów i ~585
# kandydatów po regułach Forebet. Każdy kandydat to wejście na Livesport po
# H2H, formę i kursy, czyli kilkanaście sekund — 585 meczów to godziny, a
# GitHub ubija joba po 6 h. Bez limitu run nie kończy się wcale i nie dochodzi
# ani do zapisu wyników, ani do maila.
#
# Limit wybiera NAJLEPSZYCH kandydatów (najwyższe prawdopodobieństwo faworyta),
# a nie pierwszych z listy. Lista jest posortowana po godzinie, więc branie
# „od początku" oznaczało nocne mecze z egzotycznych lig — czyli te, których
# Livesport najczęściej nie ma i nikt nie wycenia.
#
# Wartość 60 była zachowawcza. Pomiar na realnym runie piłki (13.09):
# mecz 5 o 11:51:34, mecz 20 o 12:01:36 => ~40 s/mecz, czyli 60 meczów zużywa
# ~40 min z sześciu dostępnych godzin. Przy tym `brak_kursow` odrzucało 236 z
# 504 zdarzeń, więc znaczna część tych 40 min szła na mecze bez rynku.
#
# Podniesione do 200 (~2,2 h przy 40 s/mecz). Wyższy limit jest bezpieczny
# tylko dlatego, że niżej pilnuje go ENRICH_TIME_BUDGET_SECONDS — bez hamulca
# job zginąłby na 6-godzinnym timeoucie GitHuba, tracąc CAŁY dorobek: zapis
# wyników i mail są po pętli.
# 0 = BEZ LIMITU (domyślnie). Zasięg wyznacza czas, nie arbitralna liczba.
#
# Historia: 60 -> 200 -> 0. Limit był potrzebny, dopóki jedynym ogranicznikiem
# był 6-godzinny timeout GitHuba — przekroczenie go zabijało joba, a zapis
# wyników i mail są PO pętli, więc run nie zostawiał niczego.
#
# Odkąd pętli pilnuje ENRICH_TIME_BUDGET_SECONDS (przerywa i przechodzi do
# zapisu), limit przestał chronić cokolwiek, a zaczął po prostu ucinać mecze.
# Przy ~723 kandydatach piłki i ~40 s/mecz cała pula to ~8 h, czyli i tak nie
# zmieści się w 6 h — ale to CZAS ma o tym decydować, nie liczba 200.
#
# Warunek konieczny tej zmiany: pętla musi iść od NAJLEPSZYCH kandydatów.
# Inaczej hamulec ucinałby mecze wieczorne zamiast najsłabszych. Chronologia
# jest przywracana dopiero przy zapisie i mailu.
DEFAULT_MAX_PER_SPORT = int(os.getenv('FOREBET_MAX_PER_SPORT_DEFAULT', '0'))

# Do czego celuje miękka podłoga progu, gdy limitu nie ma. Podłoga odzyskuje
# mecze spod progu tylko wtedy, gdy pula jest MNIEJSZA niż to, co i tak
# przetworzymy — a bez limitu nie ma z czym tego porównać. 200 to liczba,
# którą realnie wyrabiamy w budżecie czasu.
TOP_UP_TARGET = int(os.getenv('FOREBET_TOP_UP_TARGET', '200'))

# Twardy budżet czasu na wzbogacanie. Po jego przekroczeniu przerywamy pętlę i
# przechodzimy do zapisu + maila z tym, co już mamy. Lepiej wysłać 150 meczów
# niż stracić 200 na timeoucie.
#
# 3,5 h zostawia ~2,5 h zapasu na: pobranie Forebet, indeks Livesport,
# scoring, zapis i wysyłkę — te etapy są przed/po pętli i też trwają.
ENRICH_TIME_BUDGET_SECONDS = int(
    os.getenv('FOREBET_ENRICH_BUDGET_SECONDS', str(int(3.5 * 3600)))
)

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
                           top_up_to: Optional[int] = None,
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
    near_misses: List[Dict[str, Any]] = []
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

        m['favorite'] = 'home' if pred == '1' else 'away'
        m['forebet_fav_prob'] = fav_prob
        m['forebet_gap'] = gap

        # Progi sprawdzamy NA KOŃCU, żeby odrzucone dało się jeszcze odzyskać:
        # mecz jest poprawny, tylko słabszy od progu.
        if fav_prob < min_fav_prob:
            _reject(f'faworyt_ponizej_{min_fav_prob:.0f}%')
            near_misses.append(m)
            continue

        if gap < min_gap:
            _reject(f'przewaga_ponizej_{min_gap:.0f}pp')
            near_misses.append(m)
            continue

        selected.append(m)

    # Miękka podłoga. Próg ma chronić od rzutów monetą, gdy kandydatów jest
    # NADMIAR i i tak wybieramy najlepszych. Gdy jest ich mało, odrzucenie
    # marginalnego meczu niczego nie kupuje — tylko zabiera zdarzenie.
    #
    # Powód: podaż Forebet bardzo się różni między sportami. 13.09 piłka dała
    # 930 meczów, a koszykówka 4, siatkówka 13, rugby 10. Sztywny próg 52% przy
    # puli 4 meczów mógłby ją zredukować niemal do zera, choć nie ma z czego
    # wybierać. Dlatego gdy po progu zostaje mniej niż `top_up_to`, dopełniamy
    # najlepszymi z odrzuconych.
    if top_up_to and len(selected) < top_up_to and near_misses:
        need = top_up_to - len(selected)
        extra = sorted(near_misses,
                       key=lambda x: -(x.get('forebet_fav_prob') or 0))[:need]
        if extra:
            worst = min(e.get('forebet_fav_prob') or 0 for e in extra)
            selected.extend(extra)
            rejected['_odzyskane_maly_wybor'] = len(extra)
            rejected['_odzyskane_prog_faworyta'] = round(worst, 1)

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


def livesport_candidate_label(entry: Dict[str, Any]) -> Optional[str]:
    """Czytelne „Gospodarz vs Gość" z URL-a Livesport, do promptu AI."""
    slugs = _url_team_slugs(entry.get('url') or '')
    if not slugs:
        return None
    home = slugs[0].replace('-', ' ').strip().title()
    away = slugs[1].replace('-', ' ').strip().title()
    if not home or not away:
        return None
    return f"{home} vs {away}"


def _call_groq(prompt: str, max_tokens: int = 1200) -> Optional[str]:
    """Wywołanie Groq z rotacją modeli przy limicie (``groq_client.chat``).

    Rotacja jest tu istotna, nie kosmetyczna: limity Groq liczą się per model,
    a osiem sportów w matrixie uderza równolegle w ten sam model. Bez rotacji
    pierwsze 429 kończyło dopasowanie i wracaliśmy do stanu „brak URL-a", czyli
    do braku kursów.
    """
    try:
        import groq_client
    except Exception as e:
        print(f"      ⚠️ Groq niedostępny: {type(e).__name__}: {e}")
        return None
    return groq_client.chat(prompt, max_tokens=max_tokens, temperature=0.0)


def match_livesport_batch_ai(pairs: List[Tuple[str, str]],
                             index: List[Dict[str, Any]],
                             chunk: int = 15,
                             max_candidates: int = 90) -> Dict[str, str]:
    """Dopasuj mecze Forebet do Livesport przez Groq, gdy tokeny zawiodły.

    Dopasowanie po tokenach nie ma szans w wielu realnych przypadkach:
    Livesport jest w wersji polskiej („Poland" vs „polska", „France" vs
    „francja"), skraca nazwy klubów, a w tenisie operuje nazwiskami w innym
    formacie niż Forebet. To dopasowanie odpowiadało za połowę wszystkich strat
    — 143 z 286 analizowanych meczów kończyło się na `brak_kursow`, najczęściej
    właśnie dlatego, że nie było URL-a.

    Odpowiedź AI to numery, nie nazwy — numer albo wskazuje istniejący mecz,
    albo nie, i nie trzeba potem zgadywać, co model miał na myśli.

    Returns:
        {"home|away" (lowercase): url}
    """
    out: Dict[str, str] = {}
    if not pairs or not index:
        return out

    labelled = []
    for entry in index:
        label = livesport_candidate_label(entry)
        if label:
            labelled.append((label, entry['url']))
    if not labelled:
        print("      ⚠️ Brak czytelnych nazw w indeksie Livesport — AI pominięte")
        return out

    labelled = labelled[:max_candidates]
    candidates_text = '\n'.join(f"{i}. {lab}" for i, (lab, _) in enumerate(labelled, 1))

    for start in range(0, len(pairs), chunk):
        batch = pairs[start:start + chunk]
        wanted = '\n'.join(f"{i}. {h} vs {a}" for i, (h, a) in enumerate(batch, 1))

        prompt = (
            "Match each FIXTURE to the same real-world fixture in CANDIDATES.\n"
            "Candidate names may be in Polish, abbreviated, or have the teams in\n"
            "the opposite order — match the fixture, not the word order.\n\n"
            f"FIXTURES:\n{wanted}\n\n"
            f"CANDIDATES:\n{candidates_text}\n\n"
            "Reply with one line per FIXTURE, format: <fixture_number>:<candidate_number>\n"
            "Use 0 as candidate_number when no candidate is the same fixture.\n"
            "No other text."
        )

        answer = _call_groq(prompt)
        if not answer:
            continue

        found = 0
        for line in answer.splitlines():
            m = re.search(r'(\d+)\s*[:\->\.]+\s*(\d+)', line)
            if not m:
                continue
            fx, cand = int(m.group(1)), int(m.group(2))
            if cand <= 0 or fx < 1 or fx > len(batch):
                continue
            if cand > len(labelled):
                continue
            home, away = batch[fx - 1]
            out[f"{home.lower().strip()}|{away.lower().strip()}"] = labelled[cand - 1][1]
            found += 1

        print(f"      🤖 Groq dopasował {found}/{len(batch)} meczów "
              f"(partia {start // chunk + 1})")
        time.sleep(1.0)  # oszczędnie z limitem Groq

    return out


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


def _url_team_slugs(match_url: str) -> Optional[Tuple[str, str]]:
    """Wyciągnij (slug_gospodarza, slug_gościa) z URL-a meczu Livesport.

    Format: ``/mecz/<sport>/<gospodarz>-<id>/<gosc>-<id>/`` — kolejność w
    ścieżce to zawsze gospodarz, potem gość.
    """
    if not match_url:
        return None
    path = match_url.split('?')[0].rstrip('/')
    m = re.search(r'/(?:mecz|match)/[^/]+/([^/]+)/([^/]+)$', path)
    if not m:
        return None
    # Ucinamy końcowy identyfikator Livesport (np. "-zqr59Ejs").
    home = re.sub(r'-[A-Za-z0-9]{6,10}$', '', m.group(1))
    away = re.sub(r'-[A-Za-z0-9]{6,10}$', '', m.group(2))
    return home, away


# Kadry narodowe: Livesport używa polskich nazw w URL-ach, Forebet angielskich.
#
# Bez tego mapowania orientacja stron dla meczów kadr była NIEROZSTRZYGALNA
# (oba wyniki dopasowania 0.0), a pipeline traktował „nie wiem" jak „zgodne"
# i zapisywał kurs gospodarza do gościa. Pomiar na 2358 zdarzeniach: siatkówka
# 38% meczów nierozstrzygniętych, koszykówka 6% — i wśród nich realnie
# odwrócone, np. „USA W vs Costa Rica W" przy URL-u ``kostaryka/usa``.
#
# Tylko kraje, bo klubów to nie dotyczy (ich nazwy własne są takie same).
_EN_BY_PL = {
    'kostaryka': 'costa', 'meksyk': 'mexico', 'szwecja': 'sweden',
    'szwajcaria': 'switzerland', 'francja': 'france', 'wlochy': 'italy',
    'niemcy': 'germany', 'chiny': 'china', 'filipiny': 'philippines',
    'bahrajn': 'bahrain', 'kazachstan': 'kazakhstan', 'rumunia': 'romania',
    'turcja': 'turkey', 'grecja': 'greece', 'nikaragua': 'nicaragua',
    'slowacja': 'slovakia', 'slowenia': 'slovenia', 'lotwa': 'latvia',
    'wenezuela': 'venezuela', 'hiszpania': 'spain', 'polska': 'poland',
    'wegry': 'hungary', 'czechy': 'czechia', 'holandia': 'netherlands',
    'belgia': 'belgium', 'dania': 'denmark', 'norwegia': 'norway',
    'finlandia': 'finland', 'islandia': 'iceland', 'irlandia': 'ireland',
    'anglia': 'england', 'szkocja': 'scotland', 'walia': 'wales',
    'portugalia': 'portugal', 'austria': 'austria', 'chorwacja': 'croatia',
    'serbia': 'serbia', 'bulgaria': 'bulgaria', 'ukraina': 'ukraine',
    'litwa': 'lithuania', 'estonia': 'estonia', 'bialorus': 'belarus',
    'brazylia': 'brazil', 'argentyna': 'argentina', 'kanada': 'canada',
    'japonia': 'japan', 'korea': 'korea', 'tajlandia': 'thailand',
    'indie': 'india', 'egipt': 'egypt', 'tunezja': 'tunisia',
    'maroko': 'morocco', 'algieria': 'algeria', 'rosja': 'russia',
    'izrael': 'israel', 'katar': 'qatar', 'iran': 'iran', 'irak': 'iraq',
    'jordania': 'jordan', 'kuba': 'cuba', 'chile': 'chile', 'peru': 'peru',
    'kolumbia': 'colombia', 'urugwaj': 'uruguay', 'paragwaj': 'paraguay',
    'boliwia': 'bolivia', 'ekwador': 'ecuador', 'australia': 'australia',
    'indonezja': 'indonesia', 'wietnam': 'vietnam', 'singapur': 'singapore',
    'mongolia': 'mongolia', 'kambodza': 'cambodia', 'tajwan': 'taiwan',
}
_PL_BY_EN = {v: k for k, v in _EN_BY_PL.items()}


def is_livesport_reversed(match_url: str, forebet_home: str,
                          forebet_away: str) -> Optional[bool]:
    """Czy Livesport ma drużyny w odwrotnej kolejności niż Forebet?

    To nie jest szczegół. ``LivesportOddsAPI`` zwraca ``home_odds``/``away_odds``
    względem stron LIVESPORT, a my zapisujemy je do pól względem stron FOREBET.
    Gdy kolejność jest odwrócona, kurs gospodarza dostaje cenę gościa — a wtedy
    próg kursowy, EV i sam typ dotyczą złej drużyny.

    Zmierzone na jednym runie: 84 z 191 wycenionych meczów miało odwróconą
    kolejność, m.in. Forebet „Kristiansand vs Fjellhammer" przy URL-u
    ``/fjellhammer-.../kristiansand-...``.

    Returns:
        True = odwrócone, False = zgodne, None = nie da się ustalić.
    """
    slugs = _url_team_slugs(match_url)
    if not slugs:
        return None
    slug_home, slug_away = slugs

    def score(slug: str, name: str) -> float:
        name_tokens = _tokens(name)
        slug_norm = _strip_accents(slug.lower()).replace('-', ' ')
        slug_tokens = {t for t in slug_norm.split() if len(t) >= 4}
        # Krótkie nazwy: „E. Lys vs G. Ce" dawało puste zbiory po obu stronach,
        # więc orientacji nie dało się ustalić i kursy szły bez zamiany.
        if not name_tokens:
            name_tokens = _short_tokens(name)
        if not slug_tokens:
            slug_tokens = {t for t in slug_norm.split() if len(t) >= 2}
        # Kadry narodowe: Livesport ma slugi PO POLSKU (kostaryka, francja,
        # wlochy), a Forebet nazwy po angielsku. Bez tłumaczenia oba wyniki
        # wychodziły 0.0, funkcja zwracała None i kursy trafiały do złej strony.
        name_tokens = name_tokens | {_PL_BY_EN[t] for t in name_tokens
                                     if t in _PL_BY_EN}
        slug_tokens = slug_tokens | {_EN_BY_PL[t] for t in slug_tokens
                                     if t in _EN_BY_PL}
        if not name_tokens or not slug_tokens:
            return 0.0
        # Jaccard po tokenach + premia za podciąg (nazwy bywają skracane).
        inter = len(name_tokens & slug_tokens)
        base = inter / len(name_tokens)
        bonus = sum(1 for t in name_tokens if t in slug_norm) / len(name_tokens)
        return base + bonus

    direct = score(slug_home, forebet_home) + score(slug_away, forebet_away)
    swapped = score(slug_home, forebet_away) + score(slug_away, forebet_home)

    if direct == swapped:
        return None
    return swapped > direct


def _swap_sides(row: Dict[str, Any]) -> None:
    """Odwróć wszystko, co jest względne do stron: kursy, formę, H2H."""
    row['home_odds'], row['away_odds'] = row.get('away_odds'), row.get('home_odds')
    row['home_form'], row['away_form'] = row.get('away_form'), row.get('home_form')
    row['home_form_home'], row['away_form_away'] = (
        row.get('away_form_away'), row.get('home_form_home'))
    row['home_wins_in_h2h_last5'], row['away_wins_in_h2h_last5'] = (
        row.get('away_wins_in_h2h_last5'), row.get('home_wins_in_h2h_last5'))
    for m in (row.get('h2h_last5') or []):
        if isinstance(m, dict) and m.get('winner') in ('home', 'away'):
            m['winner'] = 'away' if m['winner'] == 'home' else 'home'


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


def _short_tokens(name: str) -> Set[str]:
    """Jak ``_tokens``, ale dopuszcza tokeny 2–3 znakowe.

    Osobna funkcja, bo ``_tokens`` (próg 4 znaków) służy też dopasowaniu do
    URL-i Livesport, gdzie krótkie tokeny rodzą fałszywe trafienia. Tutaj
    używamy jej tylko jako zapasu dla nazw, które inaczej dają pustkę.
    """
    clean = _strip_accents((name or '').lower())
    clean = re.sub(r'[^a-z0-9\s-]', ' ', clean)
    parts = re.split(r'[\s-]+', clean)
    return {p for p in parts if len(p) >= 2 and p not in _GENERIC_TOKENS}


def _name_overlap(a: str, b: str) -> float:
    """Udział wspólnych tokenów w krótszej z nazw (0..1).

    Zapas dla krótkich nazw: ``_tokens`` wymaga tokenów ≥4 znaków, więc
    „KVZ", „Lyn" czy „AIK" dawały PUSTY zbiór, a funkcja zwracała 0.0 nawet
    dla nazw identycznych. Weryfikacja SofaScore odrzucała wtedy poprawne
    dopasowania: w runie z 13.09 „Lyn W vs Brann W" dostało prawidłowe
    „SK Brann Kvinner vs Lyn" (odwrócone strony) i poszło do kosza ze
    „zgodność 0.00". To samo trafiało „KVZ FC".
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        ta, tb = _short_tokens(a), _short_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _verify_sofascore_event(event_id: int, home_team: str, away_team: str,
                            date_str: Optional[str] = None,
                            min_overlap: float = 0.5,
                            max_days_off: int = 1) -> Optional[str]:
    """Sprawdź, czy zdarzenie SofaScore to naprawdę TEN mecz.

    Returns:
        'direct'   — zgodne strony,
        'reversed' — ten sam mecz, ale odwrócone strony,
        None       — to inny mecz (albo nie da się sprawdzić).

    Wymagamy, by ZGADZAŁY SIĘ OBIE drużyny. Jedna trafiona nazwa nie wystarcza:
    tak właśnie powstawały dopasowania w rodzaju „Aluminij W vs Primorje W" ->
    „NK Maribor vs NK Aluminij".

    Sprawdzamy TAKŻE termin. Same nazwy nie wystarczają przy dwumeczach — w
    CAF Champions League i Confederations Cup ta sama para gra dwa razy, więc
    wyszukiwarka potrafi oddać rewanż z idealną zgodnością nazw (1.00), a my
    wzięlibyśmy kurs z niewłaściwego meczu. Cena wyglądałaby wiarygodnie, więc
    nic by tego nie wyłapało.

    ``max_days_off`` = 1, bo data Forebet jest lokalna, a SofaScore podaje UTC:
    mecz o 1:00 bywa opisany dniem wcześniejszym. Rewanże są od siebie
    odległe o tydzień, więc tolerancja jednego dnia ich nie przepuszcza.
    """
    try:
        from sofascore_scraper import get_event_team_ids
    except Exception:
        return None

    try:
        info = get_event_team_ids(event_id) or {}
    except Exception as e:
        print(f"      ⚠️ Weryfikacja SofaScore nieudana: {type(e).__name__}: {e}")
        return None

    ss_home = str(info.get('home_team') or '')
    ss_away = str(info.get('away_team') or '')
    if not ss_home or not ss_away:
        return None

    direct = min(_name_overlap(home_team, ss_home), _name_overlap(away_team, ss_away))
    reverse = min(_name_overlap(home_team, ss_away), _name_overlap(away_team, ss_home))

    best = max(direct, reverse)
    if best < min_overlap:
        print(f"      ⛔ SofaScore zwrócił inny mecz: '{ss_home} vs {ss_away}' "
              f"(zgodność {best:.2f} < {min_overlap})")
        return None

    # Kontrola terminu — łapie rewanże, których nazwy nie odróżniają.
    ss_date = info.get('start_date')
    if date_str and ss_date:
        try:
            want = datetime.strptime(date_str, '%Y-%m-%d').date()
            got = datetime.strptime(ss_date, '%Y-%m-%d').date()
            days_off = abs((got - want).days)
        except (TypeError, ValueError):
            days_off = None
        if days_off is not None and days_off > max_days_off:
            print(f"      ⛔ SofaScore: zgodne nazwy, ale INNY termin "
                  f"({ss_date} vs oczekiwany {date_str}, różnica {days_off} dni)"
                  f" — prawdopodobnie rewanż, odrzucam")
            return None

    return 'direct' if direct >= reverse else 'reversed'


def _orient_fan_vote(vote: Dict[str, Any], home_team: str,
                     away_team: str) -> None:
    """Ustaw Fan Vote względem NASZYCH stron. Modyfikuje ``vote`` w miejscu.

    Po co: ``get_sofascore_prediction`` zwraca głosy w kolejności SofaScore,
    a NIE w kolejności przekazanych argumentów. Dowód z testu symetrii na
    „C. Tabur vs H. Mayot": przekazanie Mayota jako gospodarza dało te same
    ``home=62, away=38`` co przekazanie Tabura. Czyli gdy nasza kolejność różni
    się od SofaScore, procenty trafiają do złego gracza.

    To nie jest kosmetyka: Fan Vote jest składnikiem scoringu, więc odwrócony
    głos PODBIJA ocenę błędnego typu i wypycha go do maila. Tak powstawały
    tenisowe „VALUE BET" na zawodnika, którego rynek wyceniał jako outsidera,
    a mail pokazywał obok 82% głosów kibiców „za nim".
    """
    if not vote.get('sofascore_found'):
        return
    hp = vote.get('sofascore_home_win_prob')
    ap = vote.get('sofascore_away_win_prob')
    if hp is None or ap is None:
        return

    url = vote.get('sofascore_url') or ''
    m = re.search(r'/match/(\d+)', str(url))
    if not m:
        vote['sofascore_orientation'] = 'unknown'
        return
    verdict = _verify_sofascore_event(int(m.group(1)), home_team, away_team)
    vote['sofascore_orientation'] = verdict or 'unknown'
    if verdict == 'reversed':
        vote['sofascore_home_win_prob'] = ap
        vote['sofascore_away_win_prob'] = hp
        print(f"      🔄 Fan Vote miał odwrócone strony — zamieniam "
              f"({hp}% / {ap}% → {ap}% / {hp}%)")


def resolve_odds_sofascore(home_team: str, away_team: str, sport: str,
                           date_str: Optional[str] = None) -> Dict[str, Any]:
    """Kursy z SofaScore — trzecie źródło, szukane po NAZWACH drużyn.

    Kluczowa różnica wobec Livesport: nie potrzebuje dopasowanego URL-a.
    SofaScore ma własną wyszukiwarkę zespołów, więc ratuje mecze, których nie
    udało się dopasować do listy dnia Livesport — a to była najczęstsza
    przyczyna `brak_kursow` (8 z 17 meczów siatkówki, wszystkie z sensownym
    score 60–79, wypadały tylko z tego powodu).
    """
    out: Dict[str, Any] = {
        'home_odds': None, 'draw_odds': None, 'away_odds': None,
        'bookmaker': None, 'odds_source': None, 'reason': None,
    }
    try:
        from sofascore_scraper import search_event_via_api, get_odds_via_api
    except Exception as e:
        out['reason'] = f'brak_modulu_sofascore: {type(e).__name__}'
        return out

    try:
        event_id = search_event_via_api(home_team, away_team, sport=sport,
                                        date_str=date_str)
        if not event_id:
            out['reason'] = 'sofascore_brak_eventu'
            return out

        # Weryfikacja dopasowania. Wyszukiwarka SofaScore zwraca zdarzenie po
        # JEDNEJ trafionej nazwie, więc potrafi oddać całkowicie inny mecz:
        # "ŽNK Mura W vs Koper Obala W" dostawało "ŽNK Mura Nona U13 vs ŠŽNK
        # Ombla U13", a "Aluminij W vs Primorje W" -> "NK Maribor vs NK
        # Aluminij". Bez sprawdzenia wzięlibyśmy kurs z innego meczu.
        verdict = _verify_sofascore_event(event_id, home_team, away_team,
                                          date_str=date_str)
        if verdict is None:
            out['reason'] = 'sofascore_zle_dopasowanie'
            return out

        res = get_odds_via_api(event_id) or {}
        if not res.get('odds_found'):
            out['reason'] = 'sofascore_bez_kursow'
            return out

        home_odds = res.get('home_odds')
        away_odds = res.get('away_odds')
        if verdict == 'reversed':
            # SofaScore ma odwrotne strony niż Forebet. Zamieniamy tutaj, bo
            # późniejsza korekta orientacji dotyczy wyłącznie Livesport.
            home_odds, away_odds = away_odds, home_odds
            print("      🔄 SofaScore ma odwrócone strony — zamieniam kursy")

        out['home_odds'] = home_odds
        out['draw_odds'] = res.get('draw_odds')
        out['away_odds'] = away_odds
        out['bookmaker'] = res.get('bookmaker') or 'SofaScore'
        out['odds_source'] = 'sofascore'
        print(f"      💰 SofaScore ({out['bookmaker']}): {out['home_odds']}/"
              f"{out['draw_odds'] or '-'}/{out['away_odds']}")
    except Exception as e:
        out['reason'] = f'sofascore_blad: {type(e).__name__}'
        print(f"      ⚠️ Kursy SofaScore błąd: {type(e).__name__}: {e}")
    return out


def resolve_odds(match_url: Optional[str], sport: str,
                 home_team: Optional[str] = None,
                 away_team: Optional[str] = None,
                 date_str: Optional[str] = None) -> Dict[str, Any]:
    """Pobierz kursy: Pinnacle → pozostali bukmacherzy Livesport → SofaScore.

    Pinnacle jest pytany OSOBNO i jako pierwszy, bo to jego kurs traktujemy
    jako referencyjny (najniższa marża = najbliżej prawdziwego
    prawdopodobieństwa). Potem reszta bukmacherów na Livesport. Na końcu
    SofaScore, który szuka po nazwach drużyn i dlatego działa też bez
    dopasowanego URL-a Livesport.

    ``brak_kursow`` zapada dopiero, gdy ŻADNA z tych platform nie ma ceny.
    Bez ceny nie ma EV ani ROI, więc typ jest nierozliczalny — ale dopóki
    którakolwiek wycenia zdarzenie, mecz zostaje w grze.

    Returns:
        {'home_odds', 'draw_odds', 'away_odds', 'bookmaker', 'odds_source', 'reason'}
    """
    out: Dict[str, Any] = {
        'home_odds': None, 'draw_odds': None, 'away_odds': None,
        'bookmaker': None, 'odds_source': None, 'reason': None,
    }

    def _sofascore_last_chance(reason_if_fail: str) -> Dict[str, Any]:
        """SofaScore jako ostatnia szansa — nie wymaga URL-a Livesport.

        Powód porażki SofaScore zostaje w ``reason``, a nie jest zastępowany
        ogólnym ``brak_kursow``. Inaczej z logu nie da się odróżnić „SofaScore
        nie zna tego zdarzenia" od „zna, ale nikt go nie wycenił" — a to dwie
        różne diagnozy prowadzące do różnych napraw.
        """
        if not (home_team and away_team):
            out['reason'] = reason_if_fail
            return out

        print(f"      ↻ Pytam SofaScore o kursy ({home_team} vs {away_team})")
        ss = resolve_odds_sofascore(home_team, away_team, sport, date_str)
        if ss.get('home_odds') is not None:
            return ss

        ss_reason = ss.get('reason') or 'sofascore_brak_odpowiedzi'
        print(f"      ⛔ SofaScore bez kursów: {ss_reason}")
        out['reason'] = f'{reason_if_fail}|{ss_reason}'
        return out

    if not match_url:
        # Brak dopasowania w Livesport nie może już oznaczać końca drogi —
        # SofaScore szuka po nazwach.
        return _sofascore_last_chance('brak_kursow')

    try:
        from livesport_odds_api import LivesportOddsAPI
    except Exception as e:
        print(f"      ⚠️ livesport_odds_api niedostępny: {e}")
        return _sofascore_last_chance('brak_modulu_kursow')

    try:
        api = LivesportOddsAPI()
        event_id = api.extract_event_id_from_url(match_url)
        if not event_id:
            return _sofascore_last_chance('brak_event_id')

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

        # 3) SofaScore — dopiero teraz wolno uznać, że ceny nie ma nigdzie.
        print("      ↻ Brak kursów na Livesport (Pinnacle + pozostali) — pytam SofaScore")
        return _sofascore_last_chance('brak_kursow')
    except Exception as e:
        print(f"      ⚠️ Kursy błąd: {type(e).__name__}: {e}")
        return _sofascore_last_chance('blad_pobierania_kursow')


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


def _form_points(form: Any) -> Optional[float]:
    """Punkty z formy w skali 0..1 (W=3, D=1, L=0). None gdy brak danych."""
    if not form:
        return None
    seq = [str(x).upper()[:1] for x in form if str(x).strip()]
    seq = [c for c in seq if c in ('W', 'D', 'L')]
    if not seq:
        return None
    return sum(3 if c == 'W' else (1 if c == 'D' else 0) for c in seq) / (3 * len(seq))


def form_advantage(row: Dict[str, Any]) -> Optional[bool]:
    """Czy faworyt jest w lepszej formie niż przeciwnik?

    Kolejność źródeł: forma ogólna z Livesport, a gdy jej nie ma — forma z
    Forebet (``host_form``/``guest_form`` z getrs.php). Zwraca None, gdy dla
    którejkolwiek strony nie znamy formy: to znaczy „nie wiem", a nie „gorsza".

    Remis w formie (identyczne punkty) traktujemy jako BRAK przewagi, bo wymóg
    brzmi „lepsza forma", nie „nie gorsza".
    """
    fav_home = row.get('favorite') == 'home'

    fav_form = (row.get('home_form') if fav_home else row.get('away_form'))
    dog_form = (row.get('away_form') if fav_home else row.get('home_form'))

    if not fav_form or not dog_form:
        fav_form = fav_form or (row.get('forebet_home_form') if fav_home
                                else row.get('forebet_away_form'))
        dog_form = dog_form or (row.get('forebet_away_form') if fav_home
                                else row.get('forebet_home_form'))

    fav_pts = _form_points(fav_form)
    dog_pts = _form_points(dog_form)
    if fav_pts is None or dog_pts is None:
        return None
    return fav_pts > dog_pts


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

    # Wymóg lepszej formy faworyta. Zastąpił próg 60% dla sportów bez remisu:
    # mówi o meczu więcej niż sam procent Forebet.
    if REQUIRE_FORM_ADVANTAGE:
        verdict = form_advantage(row)
        row['form_advantage'] = verdict
        if verdict is False:
            reasons.append('forma_gorsza_od_przeciwnika')
        elif verdict is None:
            # Brak danych o formie nie odrzuca meczu, ale jest odnotowany.
            row['form_unknown'] = True

    # Rynek egzotyczny — szeroka marża bukmachera. Liczona z kursów, które i
    # tak mamy, więc nic nie kosztuje. Mecze bez policzalnej marży (mniej niż
    # dwa kursy) przechodzą: brak danych to nie dowód przeciw.
    margin = bookmaker_margin(row)
    row['bookmaker_margin'] = round(margin, 1) if margin is not None else None
    limit = max_margin_for(row.get('sport') or '')
    if limit and margin is not None and margin > limit:
        reasons.append(f'rynek_egzotyczny_marza_{margin:.1f}%>{limit:.0f}%')

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
                # Orientacja stron — jawnie w wyniku, żeby dało się sprawdzić
                # „czy kurs trafił do właściwej drużyny" bez czytania logów.
                # Brak tych pól był powodem, dla którego zgłoszenia o
                # odwróconych kursach nie dało się zaudytować.
                'sidesReversed': r.get('sides_reversed'),
                'oddsOrientationUnknown': r.get('odds_orientation_unknown',
                                                False),
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
        min_score: Optional[float] = None, min_sources: int = 2,
        use_sofascore: bool = True, use_ai: bool = True,
        use_ai_matching: bool = True,
        use_livesport: bool = True, headless: bool = True,
        send_email: bool = True, send_telegram: bool = False,
        email_cfg: Optional[Dict[str, str]] = None,
        prefer_puppeteer: bool = True,
        load_more_clicks: int = 25) -> Dict[str, Any]:
    """Przejdź cały pipeline dla jednego sportu."""
    sport = sport.lower()
    # None = weź domyślny próg (nadpisywalny przez FOREBET_MIN_SCORE). Trzymamy
    # to tutaj, a nie w sygnaturze, żeby zmiana env działała też dla wywołań
    # programowych, nie tylko z linii poleceń.
    if min_score is None:
        min_score = DEFAULT_MIN_SCORE
    print('=' * 70)
    print(f"🎯 FOREBET PIPELINE — {sport.upper()} — {date_str}")
    print('=' * 70)
    print(f"   ⚙️ próg score ≥ {min_score}, min. źródeł {min_sources}, "
          f"limit {max_matches or DEFAULT_MAX_PER_SPORT}/sport")

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
    # top_up_to = cap: gdy po progach zostaje mniej meczów, niż i tak
    # zmieścimy, odzyskujemy najlepsze z odrzuconych. Próg ma odsiewać nadmiar,
    # nie zawężać i tak małej puli (koszykówka miała 13.09 tylko 4 zdarzenia).
    # Gdy limitu nie ma (0), podłoga celuje w TOP_UP_TARGET — bo „mniej niż
    # zmieścimy" trzeba z czymś porównać, a bez limitu nie ma z czym.
    # Bez tego top_up_to=0 cicho wyłączyłoby podłogę i próg 52% znów obciąłby
    # małe sporty (koszykówka miała 13.09 tylko 4 zdarzenia).
    pre_cap = (max_matches or DEFAULT_MAX_PER_SPORT) or TOP_UP_TARGET
    selected, rejected = select_forebet_matches(all_matches, sport,
                                                top_up_to=pre_cap)
    recovered = rejected.pop('_odzyskane_maly_wybor', 0)
    recovered_floor = rejected.pop('_odzyskane_prog_faworyta', None)
    print(f"   ✅ Wybrane: {len(selected)}/{len(all_matches)}")
    for reason, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
        print(f"      ↳ odrzucone [{reason}]: {count}")
    if recovered:
        print(f"      ↻ odzyskane {recovered} meczów poniżej progu "
              f"(faworyt ≥ {recovered_floor}%) — pula mniejsza niż limit "
              f"{pre_cap}, więc próg nie miał czego odsiewać")

    # Przetwarzamy WSZYSTKIE wybrane mecze, ale zawsze w kolejności JAKOŚCI.
    #
    # Wcześniej po wybraniu najlepszych kandydatów kolejność była przywracana
    # chronologicznie i pętla szła po godzinach. Przy limicie 60 nie miało to
    # znaczenia, bo cała lista i tak się mieściła. Po zdjęciu limitu miałoby
    # fatalne: hamulec czasu ucinałby OGON, czyli mecze wieczorne — niezależnie
    # od tego, jak dobre. Tracilibyśmy La Ligę o 21:00, a przetwarzali mecz
    # rezerw o 11:00.
    #
    # Dlatego pętla idzie od najlepszych, a chronologię przywracamy dopiero
    # przy zapisie i mailu. Gdy czas się skończy, odpada realnie najsłabszy
    # ogon, a nie najpóźniejszy.
    if True:
        # Kolejność: NAJPIERW mecze, które Forebet zdołał wycenić, potem
        # reszta; w obu grupach malejąco po sile faworyta.
        #
        # Dlaczego obecność kursów Forebet: to darmowy sygnał, że mecz w ogóle
        # ma rynek. Pomiar na 504 zdarzeniach z runów 12-13.09:
        #   z kursami Forebet  -> 87% ma realny kurs (90/103)
        #   bez kursow Forebet -> 44% (178/401)
        # a wśród 236 odrzuceń `brak_kursow` aż 94% (223) nie miało kursów
        # Forebet. `brak_kursow` było powodem odrzucenia numer jeden.
        #
        # Samo sortowanie po forebet_fav_prob systematycznie promowało ligi
        # egzotyczne — Forebet jest najpewniejszy tam, gdzie ma najmniej
        # danych, a tam nikt nie wycenia. Stąd „mecze ze słabych lig" w mailu
        # i masowe `brak_kursow`.
        #
        # To NIE jest użycie kursu Forebet do decyzji — o progu i EV nadal
        # decyduje wyłącznie Pinnacle/Livesport/SofaScore. Tu liczy się tylko
        # SAM FAKT wyceny jako wskaźnik pokrycia rynkowego.
        def _priority(m):
            has_market = bool(m.get('home_odds') or m.get('away_odds'))
            return (0 if has_market else 1, -(m.get('forebet_fav_prob') or 0))

        # cap = 0 (domyślnie) oznacza BRAK limitu — o zasięgu decyduje czas,
        # nie arbitralna liczba. Limit zostaje dostępny przez --max-matches
        # i FOREBET_MAX_PER_SPORT_DEFAULT, gdy ktoś chce świadomie przyciąć.
        cap = max_matches if max_matches else DEFAULT_MAX_PER_SPORT
        ordered = sorted(selected, key=_priority)
        by_quality = ordered[:cap] if cap else ordered
        dropped = len(selected) - len(by_quality)
        worst = min((m.get('forebet_fav_prob') or 0) for m in by_quality)
        with_market = sum(1 for m in by_quality
                          if m.get('home_odds') or m.get('away_odds'))
        # BEZ przywracania chronologii — patrz komentarz wyżej.
        selected = by_quality
        if cap:
            print(f"   ✂️ Limit {cap}/sport: wzbogacam {len(selected)} "
                  f"najlepszych kandydatów (odrzucono {dropped}, "
                  f"próg faworyta ≥ {worst}%)")
        else:
            print(f"   ♾️ Bez limitu: wzbogacam WSZYSTKIE {len(selected)} "
                  f"wybrane mecze, od najlepszych "
                  f"(budżet czasu {ENRICH_TIME_BUDGET_SECONDS / 3600:.1f} h "
                  f"decyduje, gdzie się zatrzymamy)")
        print(f"      ↳ z rynkiem (kursy Forebet): {with_market}/{len(selected)}"
              f" — pierwszeństwo, bo 87% z nich ma realny kurs vs 44% bez")
        print(f"      ↳ kolejność: jakość, nie godzina — hamulec czasu ucina "
              f"najsłabszy ogon, nie mecze wieczorne")

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

    # Dopasowanie do Livesport: najpierw tanie tokeny, potem Groq na resztę.
    # Robimy to ZBIORCZO przed pętlą, żeby AI dostało jedno zapytanie na ~20
    # meczów, a nie jedno na mecz.
    url_by_pair: Dict[str, str] = {}
    if index:
        unmatched: List[Tuple[str, str]] = []
        for m in survivors:
            url = match_livesport_url(m['home_team'], m['away_team'], index)
            key = f"{m['home_team'].lower().strip()}|{m['away_team'].lower().strip()}"
            if url:
                url_by_pair[key] = url
            else:
                unmatched.append((m['home_team'], m['away_team']))

        print(f"   🔎 Dopasowanie po tokenach: {len(url_by_pair)}/{len(survivors)}")
        if unmatched and use_ai_matching:
            print(f"   🤖 Groq dopasowuje pozostałe {len(unmatched)} meczów...")
            ai_hits = match_livesport_batch_ai(unmatched, index)
            for key, url in ai_hits.items():
                url_by_pair.setdefault(key, url)
            print(f"   🔎 Po Groq: {len(url_by_pair)}/{len(survivors)} dopasowanych")

    rows: List[Dict[str, Any]] = []
    ai_analysed = 0
    enrich_started = time.time()
    budget_hit = False

    for i, m in enumerate(survivors, 1):
        # Hamulec czasu. Zapis wyników i mail są PO tej pętli, więc job ubity
        # na 6-godzinnym timeoucie GitHuba nie zostawia niczego. Lepiej oddać
        # niepełną listę niż stracić całość.
        elapsed = time.time() - enrich_started
        if elapsed > ENRICH_TIME_BUDGET_SECONDS:
            budget_hit = True
            remaining = len(survivors) - i + 1
            print(f"\n   ⏳ Budżet czasu wyczerpany "
                  f"({elapsed / 3600:.1f} h > "
                  f"{ENRICH_TIME_BUDGET_SECONDS / 3600:.1f} h) — przerywam po "
                  f"{i - 1}/{len(survivors)} meczach, pomijam {remaining}.")
            print("      ↳ przechodzę do zapisu i maila z tym, co już mam")
            break

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
            # Forma z Forebet (getrs.php) jako zapas dla wymogu lepszej formy,
            # gdy meczu nie udało się dopasować do Livesport.
            'forebet_home_form': m.get('forebet_home_form') or [],
            'forebet_away_form': m.get('forebet_away_form') or [],
            'h2h_last5': [], 'h2h_count': 0,
            'home_wins_in_h2h_last5': 0, 'away_wins_in_h2h_last5': 0,
            'last_h2h_date': None, 'last_h2h_score': None,
            'skip_reason': None,
        }

        # Livesport: dopasowanie + H2H/forma/kursy
        if driver is not None:
            ls_url = url_by_pair.get(f"{home.lower().strip()}|{away.lower().strip()}")
            row['match_url'] = ls_url
            if ls_url:
                print(f"      🔗 Livesport: {ls_url}")
                enrich = fetch_h2h_and_form(driver, ls_url, home, sport)
                for key, val in enrich.items():
                    if val:
                        row[key] = val

            else:
                print("      ⚠️ Brak dopasowania w Livesport (bez H2H/formy)")

        # Kursy: Pinnacle → pozostali bukmacherzy Livesport → SofaScore.
        # Poza pętlą `if ls_url`, bo SofaScore szuka po nazwach drużyn i nie
        # potrzebuje URL-a. Wcześniej brak dopasowania w Livesport oznaczał, że
        # nie pytaliśmy o kurs NIGDZIE — i mecz ginął na `brak_kursow`, choć
        # cena mogła istnieć.
        odds = resolve_odds(row.get('match_url'), sport,
                            home_team=home, away_team=away, date_str=date_str)
        row['home_odds'] = odds.get('home_odds')
        row['draw_odds'] = odds.get('draw_odds')
        row['away_odds'] = odds.get('away_odds')
        row['odds_source'] = odds.get('odds_source')
        row['bookmaker'] = odds.get('bookmaker')
        row['odds_note'] = odds.get('reason')

        # Livesport bywa listuje mecz z odwróconymi stronami. Kursy, forma i
        # H2H są względne do stron LIVESPORT, a nasze pola do stron FOREBET —
        # bez tej korekty kurs gospodarza dostawał cenę gościa.
        # Kursy z SofaScore są szukane po naszych nazwach, więc ich nie ruszamy.
        row['sides_reversed'] = False
        if row.get('match_url') and row.get('odds_source') != 'sofascore':
            reversed_sides = is_livesport_reversed(row['match_url'], home, away)
            if reversed_sides:
                _swap_sides(row)
                row['sides_reversed'] = True
                print(f"      🔄 Livesport ma odwrócone strony — zamieniam kursy/formę/H2H "
                      f"(H={row.get('home_odds')}, A={row.get('away_odds')})")
            elif reversed_sides is None:
                # „Nie wiem" NIE może znaczyć „zgodne". Dotąd taki mecz
                # przechodził dalej z kursami, które mogły być po złej stronie,
                # i trafiał do maila jako pewny typ. To właśnie widać było jako
                # „kursy są odwrotnie".
                row['odds_orientation_unknown'] = True
                print("      ⚠️ Nie mogę ustalić orientacji stron w Livesport "
                      "— odrzucam te kursy, żeby nie podać ceny złej strony")
                for key in ('home_odds', 'draw_odds', 'away_odds',
                            'odds_source', 'bookmaker'):
                    row[key] = None
                # Druga szansa: SofaScore szuka po nazwach i weryfikuje OBIE
                # drużyny, więc nie ma tu problemu orientacji.
                if use_sofascore:
                    alt = resolve_odds_sofascore(home, away, sport,
                                                 date_str=date_str)
                    for key in ('home_odds', 'draw_odds', 'away_odds',
                                'odds_source', 'bookmaker'):
                        row[key] = alt.get(key)
                    if alt.get('home_odds') or alt.get('away_odds'):
                        print(f"      ↻ Kursy z SofaScore (orientacja "
                              f"potwierdzona po nazwach): "
                              f"H={row.get('home_odds')}, "
                              f"A={row.get('away_odds')}")

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
                _orient_fan_vote(vote, home, away)
                row.update(vote)
                if vote.get('sofascore_found'):
                    print(f"      🗳️ Fan Vote: {vote['sofascore_home_win_prob']}% / "
                          f"{vote['sofascore_away_win_prob']}% "
                          f"({vote['sofascore_total_votes']} głosów)")
                else:
                    print(f"      🗳️ Fan Vote: brak ({vote.get('sofascore_skip_reason')})")
            except Exception as e:
                print(f"      ⚠️ Fan Vote wrapper błąd: {e}")

        # AI — krótka analiza, tylko dla ograniczonej liczby meczów.
        # Budżet Groq jest wspólny z dopasowaniem meczów, a dopasowanie jest
        # ważniejsze: ono decyduje o dostępności kursów.
        if use_ai and not row['skip_reason']:
            if ai_analysed < AI_ANALYSIS_MAX_PER_SPORT:
                row.update(run_ai_analysis(row))
                ai_analysed += 1
                if row.get('gemini_recommendation'):
                    print(f"      🤖 AI: {row['gemini_recommendation']} "
                          f"({row.get('gemini_confidence')}%)")
            else:
                row['ai_skipped_budget'] = True
                if ai_analysed == AI_ANALYSIS_MAX_PER_SPORT:
                    print(f"      ℹ️ Limit analiz AI ({AI_ANALYSIS_MAX_PER_SPORT}) "
                          f"wyczerpany — oszczędzam budżet Groq na dopasowania")
                    ai_analysed += 1  # komunikat tylko raz

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
    # Chronologia DOPIERO tutaj. Pętla szła od najlepszych kandydatów, żeby
    # hamulec czasu ucinał najsłabszy ogon, ale mail i JSON mają być
    # uporządkowane po godzinie rozpoczęcia — tak się je czyta.
    rows.sort(key=lambda r: (str(r.get('match_date') or ''),
                             str(r.get('match_time') or '99:99')))

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
        # Jawny sygnał, że lista jest niepełna z powodu czasu, a nie reguł.
        # Bez tego niepełny run wyglądałby jak słaby dzień na Forebet.
        'enrich_budget_exhausted': budget_hit,
        'not_processed_time': max(0, len(selected) - len(rows)) if budget_hit else 0,
        'qualified': qualified,
        'channel_qualified': sum(1 for r in rows if r.get('channel_qualifies')),
        'with_odds': sum(1 for r in rows if r.get('home_odds') is not None),
        'odds_pinnacle': sum(1 for r in rows if r.get('odds_source') == PRIMARY_BOOKMAKER),
        'odds_livesport_fallback': sum(1 for r in rows if r.get('odds_source') == 'livesport'),
        'odds_sofascore': sum(1 for r in rows if r.get('odds_source') == 'sofascore'),
        'skipped_no_odds': sum(1 for r in rows if r.get('skip_reason') == 'brak_kursow'),
        'matched_livesport': sum(1 for r in rows if r.get('match_url')),
        'form_advantage_ok': sum(1 for r in rows if r.get('form_advantage') is True),
        'form_advantage_worse': sum(1 for r in rows if r.get('form_advantage') is False),
        'form_unknown': sum(1 for r in rows if r.get('form_unknown')),
        'sides_reversed': sum(1 for r in rows if r.get('sides_reversed')),
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
          f"SofaScore={summary['odds_sofascore']}, "
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
    ap.add_argument('--max-matches', type=int,
                    default=int(os.getenv('FOREBET_MAX_PER_SPORT', '0')) or None,
                    help=(f'Ile meczów wzbogacać (domyślnie {DEFAULT_MAX_PER_SPORT}; '
                          f'wybierani są najlepsi kandydaci, nie pierwsi z listy)'))
    ap.add_argument('--min-odds', type=float, default=0.0,
                    help='Dodatkowy dolny próg kursu (0 = tylko próg per sport)')
    ap.add_argument('--max-odds', type=float, default=0.0,
                    help='Górne ograniczenie kursu (0 = wyłączone)')
    ap.add_argument('--min-score', type=float, default=DEFAULT_MIN_SCORE,
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
    ap.add_argument('--no-ai-matching', action='store_true',
                    help='Bez dopasowywania meczów do Livesport przez Groq')
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
        use_ai_matching=not args.no_ai_matching,
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
