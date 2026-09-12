#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Odds history — jak kurs zmienił się od poprzedniej analizy.

Pipeline dropping-odds działa cyklicznie (12:00 / 15:00 / 18:00), ale każdy run
widział wyłącznie własny snapshot. ``drop_pct`` z OddsSafari mierzy spadek od
kursu **otwarcia**, więc nie odpowiada na pytanie „co się zmieniło od kiedy
ostatnio na to patrzyłem”: kurs mógł spaść do 1.84 wczoraj i od tamtej pory
odbić w górę, a raport wciąż pokazywał ten sam spadek od otwarcia.

Ten moduł utrwala kurs każdego rynku po każdym runie i przy następnym liczy
zmianę względem poprzedniego zapisu.

Plik: ``outputs/oddssafari_odds_history_<sport>.json``

Rozbicie na plik per sport jest wymuszone przez workflow: 9 sportów leci
równolegle w matrycy, każdy w osobnym runnerze, i dopiero osobny job zbiera
artefakty. Jeden wspólny plik oznaczałby, że sporty nadpisują sobie historię.

Format::

    {
      "meta": {"sport": "football", "updated_at": "...", "version": 1},
      "markets": {
        "2301413|2": {
          "first_odds": 4.33,
          "first_seen_at": "2026-09-06T12:01:00+02:00",
          "prev_odds": 3.60,
          "prev_seen_at": "2026-09-06T15:01:00+02:00",
          "last_odds": 3.41,
          "last_seen_at": "2026-09-06T18:01:00+02:00",
          "runs": 3,
          "last_run_id": "2026-09-06T18:01:00+02:00",
          "home_team": "Hradec Kralove B",
          "away_team": "Neratovice-Byskovice",
          "event_date": "06/09",
          "event_time": "08:15",
          "league": "Czech Republic - 3. Liga",
          "samples": [{"at": "...", "odds": 4.33}, ...]
        }
      }
    }
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")

STORE_VERSION = 1

# Ile próbek trzymamy na rynek. Do policzenia zmiany wystarczą ``prev_odds``
# i ``last_odds`` — próbki służą wyłącznie diagnostyce (podejrzeniu trendu) i
# nie trafiają ani do maila, ani do JSON-a zdarzeń. Plik jest commitowany do
# repo po każdym runie (runnery są efemeryczne), a przy 9 sportach × 3 runy
# dziennie próbki były największą pozycją w jego rozmiarze — stąd krótkie okno.
MAX_SAMPLES_PER_MARKET = 5

# Po tylu dniach bez kontaktu wpis jest usuwany. Mecz już się rozegrał, więc
# jego kurs nikogo nie interesuje, a store nie ma po co puchnąć.
DEFAULT_MAX_AGE_DAYS = 14

# Poniżej tego progu (w punktach procentowych) traktujemy kurs jako niezmieniony.
# Bez tego zaokrąglenia typu 1.84 -> 1.8401 raportowałyby "wzrost".
FLAT_EPSILON_PCT = 0.5


def store_path_for_sport(sport: Optional[str]) -> str:
    """Ścieżka pliku historii dla danego sportu."""
    label = (sport or "all").strip().lower() or "all"
    label = re.sub(r"[^a-z0-9_]+", "_", label)
    return os.path.join(OUTPUTS_DIR, f"oddssafari_odds_history_{label}.json")


def _stamp(moment: Optional[datetime] = None) -> str:
    """Znacznik czasu bez mikrosekund.

    Mikrosekundy nic tu nie wnoszą (runy są godziny od siebie), a dopisywały
    7 znaków do każdego z kilku timestampów w każdym z setek rynków — w pliku
    commitowanym do repo po każdym runie.
    """
    return (moment or datetime.now().astimezone()).replace(
        microsecond=0
    ).isoformat()


def _normalize(text: str) -> str:
    """Uproszczona nazwa drużyny do klucza zapasowego."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(text.split())


def market_key(
    match_id: Optional[str],
    outcome: Optional[str],
    *,
    home_team: str = "",
    away_team: str = "",
) -> str:
    """Stabilny klucz rynku.

    ``match_id`` to OddsSafari ``EventID`` — jest stałe między runami, więc jest
    kluczem pierwszego wyboru. Gdy go brak, spadamy na znormalizowane nazwy
    drużyn, żeby wiersz bez ID nie zgubił historii.
    """
    side = (str(outcome or "").strip().upper()) or "?"
    if match_id:
        return f"{str(match_id).strip()}|{side}"
    return f"{_normalize(home_team)}_vs_{_normalize(away_team)}|{side}"


@dataclass
class OddsChange:
    """Zmiana kursu względem poprzedniego zapisu.

    ``change_pct`` jest **ze znakiem**: wartość ujemna to spadek kursu (rynek
    bardziej wierzy w ten wynik), dodatnia to wzrost.
    """

    prev_odds: float
    prev_seen_at: Optional[str]
    current_odds: float
    change_pct: float
    direction: str  # 'down' | 'up' | 'flat'
    runs_seen: int
    first_odds: Optional[float] = None
    first_seen_at: Optional[str] = None
    change_from_first_pct: Optional[float] = None
    samples: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_new(self) -> bool:
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prev_odds": self.prev_odds,
            "prev_seen_at": self.prev_seen_at,
            "current_odds": self.current_odds,
            "change_pct": self.change_pct,
            "direction": self.direction,
            "runs_seen": self.runs_seen,
            "first_odds": self.first_odds,
            "first_seen_at": self.first_seen_at,
            "change_from_first_pct": self.change_from_first_pct,
        }


def _classify(prev_odds: float, current_odds: float) -> tuple:
    """Zwróć ``(change_pct_ze_znakiem, kierunek)``."""
    if not prev_odds or prev_odds <= 0:
        return 0.0, "flat"
    change = (current_odds - prev_odds) / prev_odds * 100.0
    change = round(change, 2)
    if abs(change) < FLAT_EPSILON_PCT:
        return change, "flat"
    return change, ("up" if change > 0 else "down")


class OddsHistoryStore:
    """Trwały store kursów, jeden plik na sport."""

    def __init__(self, sport: Optional[str] = None, path: Optional[str] = None):
        self.sport = (sport or "all").strip().lower() or "all"
        self.path = path or store_path_for_sport(self.sport)
        self._markets: Dict[str, Dict[str, Any]] = {}
        self._loaded_ok = False
        self._load()

    # -- I/O ---------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.isfile(self.path):
            logger.info("Historia kursów: brak pliku %s — pierwszy run", self.path)
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            # Uszkodzony plik nie może wywalić pipeline'u — kursy i tak są
            # zebrane, po prostu ten run nie pokaże zmiany.
            logger.warning("Nie udało się wczytać %s: %s", self.path, exc)
            return
        if isinstance(data, dict):
            markets = data.get("markets")
            if isinstance(markets, dict):
                self._markets = markets
                self._loaded_ok = True
        logger.info(
            "Historia kursów: wczytano %d rynków z %s",
            len(self._markets), os.path.basename(self.path),
        )

    def save(self) -> bool:
        """Zapisz store. Zwraca True przy powodzeniu."""
        payload = {
            "meta": {
                "sport": self.sport,
                "version": STORE_VERSION,
                "updated_at": _stamp(),
                "markets": len(self._markets),
            },
            "markets": self._markets,
        }
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            # Zapis przez plik tymczasowy: przerwany run nie zostawi
            # okrojonego JSON-a, który przy następnym starcie byłby nieczytelny
            # i wyzerowałby całą historię.
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                # Zapis zwarty, bez wcięć: to store maszynowy, a nie plik do
                # czytania, i ląduje w repo po każdym runie.
                json.dump(
                    payload, f, ensure_ascii=False, default=str,
                    separators=(",", ":"),
                )
            os.replace(tmp, self.path)
            return True
        except OSError as exc:
            logger.warning("Nie udało się zapisać %s: %s", self.path, exc)
            return False

    # -- odczyt ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._markets)

    @property
    def loaded_ok(self) -> bool:
        """True gdy istniejący plik dał się wczytać (albo go nie było)."""
        return self._loaded_ok or not os.path.isfile(self.path)

    def lookup(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._markets.get(key)
        return dict(entry) if isinstance(entry, dict) else None

    # -- zapis -------------------------------------------------------------

    def observe(
        self,
        *,
        match_id: Optional[str],
        outcome: Optional[str],
        current_odds: Optional[float],
        home_team: str = "",
        away_team: str = "",
        event_date: Optional[str] = None,
        event_time: Optional[str] = None,
        league: Optional[str] = None,
        run_id: Optional[str] = None,
        now: Optional[str] = None,
    ) -> Optional[OddsChange]:
        """Zapisz obecny kurs i zwróć zmianę względem poprzedniego zapisu.

        Zwraca ``None``, gdy rynek widzimy pierwszy raz (nie ma z czym
        porównywać) albo gdy nie ma kursu.

        Odczyt i zapis są w jednej operacji celowo: rozbicie na osobne
        ``lookup`` + ``record`` zbyt łatwo prowadzi do porównania kursu z samym
        sobą, jeśli kolejność wywołań się odwróci.
        """
        if current_odds is None:
            return None
        try:
            current = float(current_odds)
        except (TypeError, ValueError):
            return None
        if current <= 0:
            return None

        key = market_key(match_id, outcome, home_team=home_team, away_team=away_team)
        stamp = now or _stamp()
        run = run_id or stamp

        entry = self._markets.get(key)
        if not isinstance(entry, dict):
            entry = None

        change: Optional[OddsChange] = None

        if entry is None:
            entry = {
                "first_odds": current,
                "first_seen_at": stamp,
                "prev_odds": None,
                "prev_seen_at": None,
                "last_odds": current,
                "last_seen_at": stamp,
                "runs": 1,
                "last_run_id": run,
                "samples": [[stamp, current]],
            }
        elif entry.get("last_run_id") == run:
            # Ten sam run (np. ponowna próba) — nie zapisujemy drugiej próbki,
            # bo porównanie wyszłoby względem samego siebie i pokazało 0%.
            prev_odds = entry.get("prev_odds")
            if prev_odds:
                pct, direction = _classify(float(prev_odds), current)
                change = self._build_change(entry, prev_odds, current, pct, direction)
            return change
        else:
            prev_odds = entry.get("last_odds")
            prev_seen_at = entry.get("last_seen_at")

            if prev_odds:
                pct, direction = _classify(float(prev_odds), current)
                entry["prev_odds"] = float(prev_odds)
                entry["prev_seen_at"] = prev_seen_at
                entry["last_odds"] = current
                entry["last_seen_at"] = stamp
                entry["runs"] = int(entry.get("runs") or 0) + 1
                entry["last_run_id"] = run
                samples = entry.get("samples")
                if not isinstance(samples, list):
                    samples = []
                # Para [czas, kurs] zamiast {"at":..., "odds":...}: same nazwy
                # kluczy kosztowały tu więcej niż przechowywane wartości.
                # Starszy format zostaje w pliku i wypada z okna sam.
                samples.append([stamp, current])
                entry["samples"] = samples[-MAX_SAMPLES_PER_MARKET:]
                change = self._build_change(
                    entry, float(prev_odds), current, pct, direction
                )
            else:
                entry["last_odds"] = current
                entry["last_seen_at"] = stamp
                entry["runs"] = int(entry.get("runs") or 0) + 1
                entry["last_run_id"] = run

        # Metadane meczu odświeżamy zawsze — nazwy drużyn i godzina bywają
        # korygowane przez źródło.
        if home_team:
            entry["home_team"] = home_team
        if away_team:
            entry["away_team"] = away_team
        if event_date:
            entry["event_date"] = event_date
        if event_time:
            entry["event_time"] = event_time
        if league:
            entry["league"] = league

        self._markets[key] = entry
        return change

    def _build_change(
        self,
        entry: Dict[str, Any],
        prev_odds: float,
        current: float,
        pct: float,
        direction: str,
    ) -> OddsChange:
        first_odds = entry.get("first_odds")
        from_first = None
        if first_odds:
            try:
                from_first = round(
                    (current - float(first_odds)) / float(first_odds) * 100.0, 2
                )
            except (TypeError, ValueError, ZeroDivisionError):
                from_first = None
        return OddsChange(
            prev_odds=round(float(prev_odds), 3),
            prev_seen_at=entry.get("prev_seen_at"),
            current_odds=round(current, 3),
            change_pct=pct,
            direction=direction,
            runs_seen=int(entry.get("runs") or 1),
            first_odds=round(float(first_odds), 3) if first_odds else None,
            first_seen_at=entry.get("first_seen_at"),
            change_from_first_pct=from_first,
            samples=list(entry.get("samples") or []),
        )

    # -- utrzymanie --------------------------------------------------------

    def prune(self, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> int:
        """Usuń rynki niewidziane od *max_age_days*. Zwraca liczbę usuniętych."""
        if max_age_days <= 0:
            return 0
        cutoff = datetime.now().astimezone() - timedelta(days=max_age_days)
        stale: List[str] = []
        for key, entry in self._markets.items():
            raw = (entry or {}).get("last_seen_at")
            if not raw:
                stale.append(key)
                continue
            try:
                seen = datetime.fromisoformat(str(raw))
            except ValueError:
                continue
            if seen.tzinfo is None:
                seen = seen.astimezone()
            if seen < cutoff:
                stale.append(key)
        for key in stale:
            self._markets.pop(key, None)
        if stale:
            logger.info("Historia kursów: usunięto %d starych rynków", len(stale))
        return len(stale)


__all__ = [
    "OddsChange",
    "OddsHistoryStore",
    "DEFAULT_MAX_AGE_DAYS",
    "FLAT_EPSILON_PCT",
    "MAX_SAMPLES_PER_MARKET",
    "market_key",
    "store_path_for_sport",
]
