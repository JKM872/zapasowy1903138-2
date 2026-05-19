"""
Auto Result Updater - Automatyczne aktualizowanie wyników
==========================================================

Monitoruje zakończone mecze i automatycznie aktualizuje wyniki w bazie danych.
Może działać w tle lub być uruchamiany przez scheduler.

Główne wywołania:
    python auto_result_updater.py --check                 # dziś + wczoraj
    python auto_result_updater.py --check --date 2026-05-19
    python auto_result_updater.py --check --date yesterday
    python auto_result_updater.py --daemon

Zmiana w v2:
- aktualizuje predykcje z OSTATNICH 2 DNI (dziś + wczoraj), nie tylko dziś,
- pobiera wyniki z `scheduled-events/{date}` (jeden request na sport+datę
  zamiast jednego na drużynę),
- używa `_api_get_json` z sofascore_scraper (bypass Cloudflare przez
  curl_cffi / FlareSolverr / WARP), więc działa też w GitHub Actions,
- dopasowuje mecze przez `similarity_score` zamiast prostych sklejeń.
"""

import os
import sys
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

# Local imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import requests  # noqa: F401  (kept for legacy fallback)
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from supabase_manager import SupabaseManager
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# SofaScore helpers — używamy tych samych funkcji co reszta projektu, dzięki
# czemu mamy ten sam bypass Cloudflare (curl_cffi / FlareSolverr / WARP) i te
# same heurystyki dopasowania nazw drużyn.
try:
    from sofascore_scraper import (  # type: ignore
        _api_get_json,
        SOFASCORE_SPORT_SLUGS,
        similarity_score,
    )
    SOFASCORE_HELPERS_AVAILABLE = True
except ImportError:
    SOFASCORE_HELPERS_AVAILABLE = False
    SOFASCORE_SPORT_SLUGS = {  # type: ignore
        'football': 'football',
        'soccer': 'football',
        'basketball': 'basketball',
        'volleyball': 'volleyball',
        'handball': 'handball',
        'rugby': 'rugby',
        'hockey': 'ice-hockey',
        'ice-hockey': 'ice-hockey',
        'tennis': 'tennis',
        'baseball': 'baseball',
    }


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

# Sporty bez remisu — wynik X nie istnieje, zawsze 1/2.
_SPORTS_WITHOUT_DRAW = {
    'volleyball', 'tennis', 'basketball', 'handball',
    'hockey', 'ice-hockey', 'baseball', 'cricket',
}


def _determine_result(home: int, away: int, sport: str = 'football') -> str:
    """Zwraca '1', 'X' lub '2'."""
    if home > away:
        return '1'
    if away > home:
        return '2'
    if sport.lower() in _SPORTS_WITHOUT_DRAW:
        # Sporty bez remisu — wynik 0:0 niemożliwy, ale gdyby był to traktujemy
        # jako brak rozstrzygnięcia (None oznacza pomijanie aktualizacji).
        return ''
    return 'X'


def _fallback_similarity(name1: str, name2: str) -> float:
    """Prosta similarity gdy sofascore_scraper niedostępny."""
    from difflib import SequenceMatcher
    a = (name1 or '').lower().strip()
    b = (name2 or '').lower().strip()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _team_similarity(a: str, b: str) -> float:
    if SOFASCORE_HELPERS_AVAILABLE:
        try:
            return float(similarity_score(a, b))
        except Exception:
            pass
    return _fallback_similarity(a, b)


# ----------------------------------------------------------------------------
# Updater
# ----------------------------------------------------------------------------

class AutoResultUpdater:
    """
    Automatycznie pobiera i aktualizuje wyniki meczów w Supabase.

    Strategia:
      1. Z bazy bierzemy predykcje z `actual_result IS NULL` z ostatnich
         `lookback_days` dni (domyślnie 2: dziś + wczoraj).
      2. Grupujemy je po `(sport, match_date)`.
      3. Dla każdej pary pobieramy `scheduled-events/{date}` — jednym
         requestem dostajemy wszystkie mecze danego sportu w danej dacie.
      4. Dla każdej predykcji szukamy odpowiednika w eventach (similarity).
      5. Jeśli event ma status `finished` — aktualizujemy wynik w bazie.
    """

    DEFAULT_LOOKBACK_DAYS = 2

    def __init__(self, check_interval: int = 300, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.check_interval = check_interval
        self.lookback_days = max(1, lookback_days)
        self.running = False
        self.last_check: Optional[datetime] = None
        self.stats = {
            'checked': 0,
            'updated': 0,
            'errors': 0,
        }
        # Cache: (sport_slug, date) -> list[event] żeby nie ciągnąć tego samego
        # endpointu dwa razy w tym samym przebiegu.
        self._events_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Pobieranie pending predykcji
    # ------------------------------------------------------------------

    def _dates_for_lookback(self, target_date: Optional[str]) -> List[str]:
        """Zwraca listę dat do sprawdzenia.

        - target_date podany → jedna konkretna data,
        - target_date None  → ostatnie `lookback_days` dni licząc od dziś.
        """
        if target_date:
            return [target_date]
        today = datetime.now().date()
        return [
            (today - timedelta(days=i)).strftime('%Y-%m-%d')
            for i in range(self.lookback_days)
        ]

    def get_pending_predictions(self, date: Optional[str] = None) -> List[Dict]:
        """Pobiera predykcje bez wyniku z odpowiedniego okna dat."""
        if not SUPABASE_AVAILABLE:
            return self._get_pending_from_files(date)

        try:
            db = SupabaseManager()
            dates = self._dates_for_lookback(date)
            response = (
                db.client.table('predictions')
                .select('*')
                .in_('match_date', dates)
                .is_('actual_result', 'null')
                .execute()
            )
            data = response.data or []
            print(f"   📥 Pending w bazie: {len(data)} (daty: {', '.join(dates)})")
            return data
        except Exception as exc:
            print(f"Blad pobierania predykcji: {exc}")
            return []

    def _get_pending_from_files(self, date: Optional[str] = None) -> List[Dict]:
        """Fallback - pobiera z plików JSON jeśli Supabase niedostępne."""
        dates = self._dates_for_lookback(date)
        matches: List[Dict[str, Any]] = []
        outputs_dir = os.path.join(os.path.dirname(__file__), 'outputs')

        for d in dates:
            for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey']:
                filepath = os.path.join(outputs_dir, f'matches_{d}_{sport}.json')
                if not os.path.exists(filepath):
                    continue
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for m in data.get('matches', []):
                        if not m.get('actual_result'):
                            m['sport'] = sport
                            m.setdefault('match_date', d)
                            matches.append(m)
                except Exception:
                    pass
        return matches

    # ------------------------------------------------------------------
    # Pobieranie wyników z SofaScore
    # ------------------------------------------------------------------

    def _fetch_events_for_date(self, sport: str, date: str) -> List[Dict[str, Any]]:
        """Pobiera listę eventów (wszystkich statusów) dla sportu + daty.

        Używa `_api_get_json` z sofascore_scraper, czyli z bypassem Cloudflare.
        """
        slug = SOFASCORE_SPORT_SLUGS.get((sport or 'football').lower(), 'football')
        cache_key = (slug, date)
        if cache_key in self._events_cache:
            return self._events_cache[cache_key]

        events: List[Dict[str, Any]] = []
        url = f"https://api.sofascore.com/api/v1/sport/{slug}/scheduled-events/{date}"

        if SOFASCORE_HELPERS_AVAILABLE:
            data = _api_get_json(url, timeout=15)
        else:
            # Fallback bez bypassu CF — w GHA prawdopodobnie 403, ale lokalnie
            # może zadziałać.
            try:
                import requests as _rq
                resp = _rq.get(
                    url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'application/json',
                    },
                    timeout=15,
                )
                data = resp.json() if resp.status_code == 200 else None
            except Exception:
                data = None

        if isinstance(data, dict):
            events = data.get('events', []) or []

        self._events_cache[cache_key] = events
        return events

    def _match_event(
        self,
        prediction: Dict[str, Any],
        events: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Znajduje event SofaScore odpowiadający predykcji."""
        if not events:
            return None

        home = prediction.get('home_team') or prediction.get('homeTeam') or ''
        away = prediction.get('away_team') or prediction.get('awayTeam') or ''
        if not home or not away:
            return None

        best_event = None
        best_combined = 0.0

        for event in events:
            evt_home = (event.get('homeTeam') or {}).get('name', '')
            evt_away = (event.get('awayTeam') or {}).get('name', '')
            if not evt_home or not evt_away:
                continue

            home_sim = _team_similarity(home, evt_home)
            away_sim = _team_similarity(away, evt_away)
            combined = home_sim + away_sim

            # Te same progi co w sofascore_scraper._search_event_for_date.
            cond_both_decent = home_sim >= 0.35 and away_sim >= 0.35
            cond_combined = combined >= 0.85
            cond_one_strong = max(home_sim, away_sim) >= 0.75 and min(home_sim, away_sim) >= 0.25
            cond_exact_one = max(home_sim, away_sim) >= 0.90 and min(home_sim, away_sim) >= 0.20
            is_match = cond_both_decent or cond_combined or cond_one_strong or cond_exact_one

            if is_match and combined > best_combined:
                best_combined = combined
                best_event = event

        return best_event

    def _extract_result(
        self,
        event: Dict[str, Any],
        sport: str,
    ) -> Optional[Dict[str, Any]]:
        """Wyciąga gotowy wynik z eventu SofaScore. Zwraca None jeśli mecz nie
        jest jeszcze zakończony albo brakuje wyniku."""
        status = (event.get('status') or {}).get('type', '')
        if status != 'finished':
            return None

        home_score = (event.get('homeScore') or {}).get('current')
        away_score = (event.get('awayScore') or {}).get('current')
        if home_score is None or away_score is None:
            return None

        try:
            h = int(home_score)
            a = int(away_score)
        except (TypeError, ValueError):
            return None

        result = _determine_result(h, a, sport)
        if not result:
            return None

        return {
            'home_score': h,
            'away_score': a,
            'result': result,
            'source': 'sofascore',
            'event_id': event.get('id'),
        }

    def fetch_result_from_api(self, prediction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Publiczny entry-point: dla danej predykcji znajduje wynik."""
        sport = (prediction.get('sport') or 'football').lower()
        match_date = prediction.get('match_date') or datetime.now().strftime('%Y-%m-%d')
        # SofaScore trzyma mecze pod datą lokalną, więc czasem mecz późnym
        # wieczorem trafia do następnej daty UTC. Sprawdzamy ±1 dzień.
        try:
            base = datetime.strptime(match_date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            base = datetime.now().date()

        candidate_dates = [
            base.strftime('%Y-%m-%d'),
            (base + timedelta(days=1)).strftime('%Y-%m-%d'),
            (base - timedelta(days=1)).strftime('%Y-%m-%d'),
        ]

        for cand_date in candidate_dates:
            events = self._fetch_events_for_date(sport, cand_date)
            if not events:
                continue
            event = self._match_event(prediction, events)
            if not event:
                continue
            result = self._extract_result(event, sport)
            if result:
                return result
        return None

    # ------------------------------------------------------------------
    # Aktualizacja bazy
    # ------------------------------------------------------------------

    def update_prediction(self, prediction_id: int, result: Dict[str, Any]) -> bool:
        """Aktualizuje predykcję wynikiem meczu."""
        if not SUPABASE_AVAILABLE:
            print(f"Supabase niedostepny - wynik: {result}")
            return True

        try:
            db = SupabaseManager()
            return db.update_match_result(
                match_id=prediction_id,
                actual_result=result['result'],
                home_score=result['home_score'],
                away_score=result['away_score'],
            )
        except Exception as exc:
            print(f"Blad aktualizacji: {exc}")
            return False

    # ------------------------------------------------------------------
    # Główny przebieg
    # ------------------------------------------------------------------

    def check_and_update(self, date: Optional[str] = None) -> Dict[str, int]:
        """Sprawdza pending predykcje i aktualizuje wyniki."""
        # Reset cache eventów na każdy przebieg (świeże dane).
        self._events_cache.clear()

        pending = self.get_pending_predictions(date)
        results = {
            'checked': len(pending),
            'updated': 0,
            'not_finished': 0,
            'errors': 0,
        }

        if not pending:
            print("   ℹ️  Brak predykcji do zaktualizowania.")
            self.last_check = datetime.now()
            return results

        # Pre-fetch eventów dla wszystkich (sport, date) w jednym przebiegu —
        # to ogranicza liczbę requestów do 1 na grupę.
        groups: Dict[Tuple[str, str], int] = defaultdict(int)
        for pred in pending:
            sport = (pred.get('sport') or 'football').lower()
            md = pred.get('match_date') or datetime.now().strftime('%Y-%m-%d')
            groups[(sport, md)] += 1

        if groups:
            print(f"   🌐 Sprawdzam {len(groups)} grup(y) sport+data w SofaScore…")

        for prediction in pending:
            self.stats['checked'] += 1

            try:
                result = self.fetch_result_from_api(prediction)
            except Exception as exc:
                results['errors'] += 1
                self.stats['errors'] += 1
                print(f"   ⚠️  Błąd dla {prediction.get('home_team')} - {prediction.get('away_team')}: {exc}")
                continue

            if not result:
                results['not_finished'] += 1
                continue

            pred_id = prediction.get('id') or prediction.get('match_id')
            if pred_id is None:
                results['errors'] += 1
                continue

            if self.update_prediction(pred_id, result):
                results['updated'] += 1
                self.stats['updated'] += 1
                print(
                    f"   ✅ Updated: {prediction.get('home_team')} vs "
                    f"{prediction.get('away_team')} → "
                    f"{result['result']} ({result['home_score']}:{result['away_score']})"
                )
            else:
                results['errors'] += 1
                self.stats['errors'] += 1

        self.last_check = datetime.now()
        return results

    # ------------------------------------------------------------------
    # Daemon
    # ------------------------------------------------------------------

    def run_daemon(self):
        """Uruchamia demon w tle"""
        self.running = True
        print(f"Auto Result Updater uruchomiony (interval: {self.check_interval}s)")

        while self.running:
            try:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Sprawdzam wyniki...")
                results = self.check_and_update()
                print(
                    f"  Sprawdzono: {results['checked']}, "
                    f"Zaktualizowano: {results['updated']}, "
                    f"Niezakończone: {results['not_finished']}"
                )
            except Exception as exc:
                print(f"Blad: {exc}")

            time.sleep(self.check_interval)

    def stop(self):
        self.running = False
        print("Zatrzymywanie...")

    def print_stats(self):
        print("\n" + "=" * 40)
        print("AUTO RESULT UPDATER - STATS")
        print("=" * 40)
        print(f"Sprawdzono: {self.stats['checked']}")
        print(f"Zaktualizowano: {self.stats['updated']}")
        print(f"Bledy: {self.stats['errors']}")
        if self.last_check:
            print(f"Ostatnie sprawdzenie: {self.last_check.strftime('%H:%M:%S')}")
        print("=" * 40)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Auto Result Updater')
    parser.add_argument('--check', action='store_true', help='Sprawdz i zaktualizuj raz')
    parser.add_argument('--daemon', action='store_true', help='Uruchom jako demon')
    parser.add_argument('--interval', type=int, default=300, help='Interwal w sekundach')
    parser.add_argument('--date', type=str, help='Data (YYYY-MM-DD lub "yesterday"). Pusta = dziś + wczoraj.')
    parser.add_argument('--lookback-days', type=int, default=AutoResultUpdater.DEFAULT_LOOKBACK_DAYS,
                        help='Ile dni wstecz sprawdzać (gdy --date nie podano)')
    parser.add_argument('--mode', type=str, choices=['check', 'update', 'daemon'], help='Tryb działania')
    parser.add_argument('--stats', action='store_true', help='Pokaz statystyki')

    args = parser.parse_args()

    target_date = args.date
    if target_date == 'yesterday':
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        print(f"📅 Weryfikacja predykcji z dnia: {target_date}")

    updater = AutoResultUpdater(
        check_interval=args.interval,
        lookback_days=args.lookback_days,
    )

    mode = args.mode
    if not mode:
        if args.check:
            mode = 'check'
        elif args.daemon:
            mode = 'daemon'

    if mode == 'check':
        label = target_date or f"ostatnie {args.lookback_days} dni (dziś + wczoraj)"
        print(f"🔍 Sprawdzam wyniki dla: {label}…")
        results = updater.check_and_update(target_date)
        print(f"\n✅ Wyniki weryfikacji:")
        print(f"   Sprawdzono:     {results['checked']}")
        print(f"   Zaktualizowano: {results['updated']}")
        print(f"   Niezakończone:  {results['not_finished']}")
        print(f"   Błędy:          {results['errors']}")
        if results['checked'] > 0:
            rate = (results['updated'] / results['checked']) * 100
            print(f"\n📊 Wskaźnik aktualizacji: {rate:.1f}%")

    elif mode == 'update':
        results = updater.check_and_update(target_date)
        print(f"\nWyniki: {results}")

    elif mode == 'daemon':
        try:
            updater.run_daemon()
        except KeyboardInterrupt:
            updater.stop()
            updater.print_stats()

    elif args.stats:
        updater.print_stats()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
