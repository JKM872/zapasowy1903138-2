"""
🏆 World Cup Analytical Pipeline
================================
Nowy, szeroki pakiet analityczny na Mistrzostwa Świata. Codziennie analizuje
DOSŁOWNIE KAŻDY mecz turnieju, wykorzystując komplet rynków Pinnacle.

Przepływ:
  1. Zbierz wszystkie mecze MŚ z danego dnia (Livesport, filtr turnieju).
  2. Dla każdego meczu: H2H + forma (process_match) — bez bramki kwalifikacji,
     bo analizujemy WSZYSTKO, nie tylko "kwalifikujące się" mecze.
  3. Pobierz pełny pakiet rynków Pinnacle (1X2, totale, BTTS, handicapy,
     dokładny wynik, podwójna szansa) + ruchy linii.
  4. Zbuduj analizę (worldcup_analyzer): fair-prob, value-bety, sygnały rynku,
     werdykt PL.
  5. Dołóż werdykt AI (ai_prediction_engine) gdy są dane.
  6. Zapisz results/worldcup_<date>.json + (opcjonalnie) Supabase.

Użycie (CLI):
    python worldcup_pipeline.py --date 2026-06-11 --headless
    python worldcup_pipeline.py --date 2026-06-11 --max-matches 3 --no-supabase
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from livesport_h2h_scraper import (
    start_driver,
    get_match_links_from_day,
    process_match,
)
from pinnacle_full_odds import PinnacleFullOdds
from worldcup_analyzer import analyze_match

# Livesport sluggi turnieju MŚ (filtr substring na URL/tekście linku).
# Strona kanoniczna: /pl/pilka-nozna/swiat/mistrzostwa-swiata/
WORLD_CUP_LEAGUE_SLUGS = [
    "mistrzostwa-swiata",
    "world-championship",
    "world-cup",
]

# Kanoniczne strony turnieju MŚ na Livesport. Zbieramy linki meczów wprost z
# tych zakładek (terminarz = nadchodzące, wyniki = rozegrane), zamiast skanować
# ogólną stronę dnia i filtrować po slugu — linki meczów (/mecz/team1/team2/)
# nie zawierają sluga ligi, więc filtr po lidze dawał 0 trafień.
WORLD_CUP_TOURNAMENT_URLS = [
    "https://www.livesport.com/pl/pilka-nozna/swiat/mistrzostwa-swiata/terminarz/",
    "https://www.livesport.com/pl/pilka-nozna/swiat/mistrzostwa-swiata/wyniki/",
]

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _is_ci() -> bool:
    return os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"


def collect_worldcup_match_links(driver, tournament_urls: Optional[List[str]] = None,
                                 max_scrolls: int = 12) -> List[str]:
    """Zbiera linki meczów wprost ze stron turnieju MŚ (terminarz + wyniki).

    Wchodzi na każdą kanoniczną stronę turnieju, akceptuje consent, ponawia przy
    stronie-blokadzie LiveSport, scrolluje dla lazy-load i wyciąga linki
    ``/mecz/...``. Strony są już zawężone do turnieju, więc NIE filtrujemy po
    slugu ligi (to właśnie filtr powodował 0 trafień przy skanie strony dnia).

    Reużywa pomocników z ``livesport_h2h_scraper`` bez ich modyfikacji.
    Zwraca unikalne URL-e w kolejności odkrycia.
    """
    import time

    try:
        from bs4 import BeautifulSoup
        from livesport_h2h_scraper import (
            _accept_cookies_on_page,
            _extract_match_links_from_soup,
            _count_match_links_in_page,
            is_livesport_error_page,
            _safe_page_source,
        )
    except Exception as e:  # pragma: no cover - import guard
        print(f"   ⚠️ Nie można zaimportować pomocników LiveSport: {e}")
        return []

    urls_to_visit = tournament_urls or WORLD_CUP_TOURNAMENT_URLS
    found: List[str] = []
    seen: set = set()

    for page_url in urls_to_visit:
        print(f"   🌍 Strona turnieju: {page_url}")
        try:
            driver.get(page_url)
            time.sleep(2.5)
            _accept_cookies_on_page(driver)

            # Retry przy stronie-blokadzie LiveSport.
            attempts = 0
            while is_livesport_error_page(_safe_page_source(driver)) and attempts < 3:
                attempts += 1
                print(f"      🚫 Strona błędu/blokady (próba {attempts}/3) — czekam...")
                time.sleep(3.0 * attempts)
                try:
                    driver.get(page_url)
                    time.sleep(3.0)
                    _accept_cookies_on_page(driver)
                except Exception:
                    pass

            # Smart scroll dla lazy-load.
            prev = _count_match_links_in_page(driver)
            stale = 0
            for _ in range(max_scrolls):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.6)
                cur = _count_match_links_in_page(driver)
                if cur <= prev:
                    stale += 1
                    if stale >= 3:
                        break
                else:
                    stale = 0
                prev = cur
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.3)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            # leagues=None: strona już zawężona do turnieju.
            page_links, _dbg = _extract_match_links_from_soup(soup, page_url, seen, leagues=None)
            print(f"      ✓ {len(page_links)} linków meczów")
            found.extend(page_links)
        except Exception as e:
            print(f"      ✗ Błąd przy {page_url}: {e}")
            continue

    print(f"   📊 Łącznie {len(found)} unikalnych linków meczów MŚ ze stron turnieju")
    return found


def _build_frontend_record(row: Dict[str, Any], analysis: Dict[str, Any],
                           date: str) -> Dict[str, Any]:
    """Mapuje wynik na format zgodny z api_server.normalize_match()."""
    home = row.get("home_team") or ""
    away = row.get("away_team") or ""
    odds = analysis.get("match_winner") or {}
    odds_obj = None
    if odds.get("odds"):
        o = odds["odds"]
        if o.get("home") or o.get("away"):
            odds_obj = {
                "home": o.get("home"),
                "draw": o.get("draw"),
                "away": o.get("away"),
                "bookmaker": "Pinnacle",
            }
    return {
        "id": abs(hash(f"{home}_{away}_{row.get('match_time', '')}_{date}")) % (10 ** 12),
        "homeTeam": home,
        "awayTeam": away,
        "time": row.get("match_time") or "",
        "date": date,
        "league": row.get("league") or "Mistrzostwa Świata",
        "country": row.get("country", ""),
        "sport": "football",
        "matchUrl": row.get("match_url") or "",
        "qualifies": True,            # cała oferta MŚ jest pełna — analizujemy wszystko
        "channelQualifies": True,
        # H2H
        "h2h": {
            "home": row.get("home_wins_in_h2h_last5", 0),
            "draw": row.get("draws_in_h2h_last5", 0),
            "away": row.get("away_wins_in_h2h_last5", 0),
            "total": row.get("h2h_count", 0),
            "winRate": int((row.get("win_rate") or 0) * 100),
        },
        "homeForm": row.get("home_form", []),
        "awayForm": row.get("away_form", []),
        "formAdvantage": row.get("form_advantage", False),
        # Odds (Pinnacle 1X2)
        "odds": odds_obj,
        # Forebet (jeśli było)
        "forebet": {
            "prediction": row.get("forebet_prediction"),
            "probability": row.get("forebet_probability"),
        } if row.get("forebet_prediction") else None,
        # SofaScore (jeśli było)
        "sofascore": {
            "home": row.get("sofascore_home_win_prob"),
            "draw": row.get("sofascore_draw_prob"),
            "away": row.get("sofascore_away_win_prob"),
            "votes": row.get("sofascore_total_votes", 0),
        } if row.get("sofascore_home_win_prob") is not None else None,
        # 🏆 NOWE: pełny pakiet analityczny World Cup
        "worldcup": analysis,
        # AI verdict (dołożony niżej, gdy dostępny)
        "aiPrediction": row.get("ai_prediction"),
        "confidence": (analysis.get("match_winner") or {}).get("pick_prob") or 0,
    }


_WEATHER_CACHE: Dict[str, Any] = {}

_WMO = {
    0: "Bezchmurnie", 1: "Przeważnie słonecznie", 2: "Częściowe zachmurzenie",
    3: "Zachmurzenie", 45: "Mgła", 48: "Mgła osadzająca szron",
    51: "Słaba mżawka", 53: "Mżawka", 55: "Gęsta mżawka",
    61: "Słaby deszcz", 63: "Deszcz", 65: "Silny deszcz",
    71: "Słaby śnieg", 73: "Śnieg", 75: "Silny śnieg",
    80: "Przelotny deszcz", 81: "Przelotne opady", 82: "Ulewne przelotne opady",
    95: "Burza", 96: "Burza z gradem", 99: "Burza z silnym gradem",
}


def _fetch_weather(city_hint: str, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Best-effort pogoda przez Open-Meteo (geokoding + forecast, bez klucza).

    city_hint bywa nazwą drużyny narodowej — geokoding często i tak zwróci
    sensowny punkt (np. stolicę), więc traktujemy wynik jako orientacyjny.
    """
    import urllib.request
    import urllib.parse

    if not city_hint:
        return None
    key = city_hint.lower().strip()
    if key in _WEATHER_CACHE:
        return _WEATHER_CACHE[key]
    try:
        geo_url = ("https://geocoding-api.open-meteo.com/v1/search?name="
                   + urllib.parse.quote(city_hint) + "&count=1&language=en")
        req = urllib.request.Request(geo_url, headers={"User-Agent": "WorldCupAnalysis/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            geo = json.loads(resp.read().decode())
        results = geo.get("results") or []
        if not results:
            _WEATHER_CACHE[key] = None
            return None
        lat, lon = results[0]["latitude"], results[0]["longitude"]
        place = results[0].get("name")

        params = (f"latitude={lat}&longitude={lon}"
                  "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
                  "windspeed_10m_max,weathercode&timezone=auto")
        if date:
            params += f"&start_date={date}&end_date={date}"
        fc_url = f"https://api.open-meteo.com/v1/forecast?{params}"
        req2 = urllib.request.Request(fc_url, headers={"User-Agent": "WorldCupAnalysis/1.0"})
        with urllib.request.urlopen(req2, timeout=8) as resp2:
            raw = json.loads(resp2.read().decode())
        daily = raw.get("daily", {})
        code = (daily.get("weathercode") or [None])[0]
        out = {
            "place": place,
            "tempMax": (daily.get("temperature_2m_max") or [None])[0],
            "tempMin": (daily.get("temperature_2m_min") or [None])[0],
            "precipitation": (daily.get("precipitation_sum") or [None])[0],
            "windMax": (daily.get("windspeed_10m_max") or [None])[0],
            "description": _WMO.get(code, "—"),
            "note": "Lokalizacja orientacyjna (geokoding nazwy)",
        }
        _WEATHER_CACHE[key] = out
        return out
    except Exception:  # noqa: BLE001
        _WEATHER_CACHE[key] = None
        return None


def _attach_ai(row: Dict[str, Any]) -> None:
    """Dołącza werdykt AI engine, jeśli dostępny (best-effort)."""
    try:
        from ai_prediction_engine import generate_ai_prediction
        row["ai_prediction"] = generate_ai_prediction(row).to_dict()
    except Exception as e:  # noqa: BLE001 - best effort
        print(f"   ⚠️ AI prediction skip: {e}")


def _save_supabase(records: List[Dict[str, Any]], date: str) -> int:
    """Zapis do Supabase (tabela predictions). Best-effort."""
    try:
        from supabase_manager import SupabaseManager
        sb = SupabaseManager()
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠️ Supabase niedostępne: {e}")
        return 0

    payloads: List[Dict[str, Any]] = []
    for rec in records:
        wc = rec.get("worldcup") or {}
        mw = wc.get("match_winner") or {}
        payloads.append({
            "match_date": date,
            "match_time": rec.get("time"),
            "home_team": rec.get("homeTeam"),
            "away_team": rec.get("awayTeam"),
            "sport": "football",
            "league": rec.get("league"),
            "home_odds": (mw.get("odds") or {}).get("home"),
            "draw_odds": (mw.get("odds") or {}).get("draw"),
            "away_odds": (mw.get("odds") or {}).get("away"),
            "qualifies": True,
            "match_url": rec.get("matchUrl"),
            "gemini_prediction": wc.get("verdict"),
            "gemini_recommendation": "WORLDCUP",
        })
    try:
        return sb.save_bulk_predictions(payloads)
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠️ Supabase zapis nieudany: {e}")
        return 0


# --------------------------------------------------------------------------- #
# Main pipeline
# --------------------------------------------------------------------------- #
def run_pipeline(date: str, headless: bool = True, max_matches: Optional[int] = None,
                 use_supabase: bool = True, request_delay: float = 0.15) -> Dict[str, Any]:
    """Uruchamia pełny dzienny pipeline analityczny MŚ."""
    t0 = time.time()
    print("=" * 70)
    print("🏆 WORLD CUP — DZIENNY PAKIET ANALITYCZNY (Pinnacle full markets)")
    print("=" * 70)
    print(f"📅 Data: {date}")
    print(f"🌍 Turniej: Mistrzostwa Świata (filtr: {', '.join(WORLD_CUP_LEAGUE_SLUGS)})")

    driver = start_driver(headless=headless)
    pinnacle = PinnacleFullOdds(request_delay=request_delay)
    records: List[Dict[str, Any]] = []

    try:
        print("\n🔍 KROK 1/4: Zbieranie meczów MŚ...")
        # Zbieramy linki wprost ze stron turnieju MŚ (terminarz + wyniki).
        urls = collect_worldcup_match_links(driver)
        # Fallback: gdyby strona turnieju nic nie zwróciła, spróbuj starej metody
        # (skan strony dnia z filtrem po slugu ligi).
        if not urls:
            print("   ↩️ Brak linków ze stron turnieju — fallback do skanu dnia...")
            urls = get_match_links_from_day(
                driver, date, sports=["football"], leagues=WORLD_CUP_LEAGUE_SLUGS
            )
        # Deduplikacja zachowując kolejność
        seen = set()
        urls = [u for u in urls if not (u in seen or seen.add(u))]
        print(f"✅ Znaleziono {len(urls)} meczów MŚ")

        if max_matches:
            urls = urls[:max_matches]
            print(f"⚠️ Limit testowy: {len(urls)} meczów")

        print("\n🔬 KROK 2-3/4: Analiza H2H/forma + pełne rynki Pinnacle...")
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] {url}")
            try:
                row = process_match(
                    url, driver,
                    use_forebet=False, use_gemini=False,
                    use_sofascore=True, use_flashscore=False,
                    sport="football",
                )
            except Exception as e:  # noqa: BLE001
                print(f"   ⚠️ process_match błąd: {e}")
                continue

            if not row.get("home_team") or not row.get("away_team"):
                print("   ⏭️  Pominięto — brak nazw drużyn")
                continue

            # Pełny pakiet rynków Pinnacle
            odds_pkg = pinnacle.get_full_odds_for_match(url)
            if odds_pkg.get("success"):
                print(f"   💰 Pinnacle rynki: {', '.join(odds_pkg['markets_available'])}")
            else:
                print("   ⚠️ Brak rynków Pinnacle")

            analysis = analyze_match(odds_pkg, row)

            # 🏆 Forebet extras (corners/cards/scorers/trends) — best effort
            try:
                from worldcup_forebet_extras import fetch_forebet_extras
                extras = fetch_forebet_extras(row.get("home_team"), row.get("away_team"))
                if extras.get("available"):
                    analysis["forebet_extras"] = extras
                    _parts = []
                    if extras.get("corners"):
                        _parts.append("rożne")
                    if extras.get("cards"):
                        _parts.append("kartki")
                    if extras.get("who_scores_first"):
                        _parts.append("1.gol")
                    _trends = extras.get("trends")
                    if _trends:
                        _parts.append(f"+{len(_trends)} trendów")
                    print(f"   📊 Forebet extras: {' '.join(_parts)}")
            except Exception as e:  # noqa: BLE001
                print(f"   ⚠️ Forebet extras skip: {e}")

            # 🌦️ Weather (Open-Meteo, no key) — best effort
            try:
                wx = _fetch_weather(row.get("home_team") or "", date)
                if wx:
                    analysis["weather"] = wx
            except Exception as e:  # noqa: BLE001
                print(f"   ⚠️ Weather skip: {e}")

            # 📰 News & match intel (Google News RSS, no key) — best effort.
            # Komplet kontekstu pozarynkowego: kontuzje, zawieszenia, składy,
            # powroty, zapowiedzi — żeby przed meczem wiedzieć wszystko.
            try:
                from worldcup_news_intel import fetch_match_intel
                intel = fetch_match_intel(row.get("home_team") or "",
                                          row.get("away_team") or "")
                if intel.get("available"):
                    analysis["news_intel"] = intel
                    c = intel.get("counts", {})
                    print(f"   📰 News intel: {c.get('headlines', 0)} nagłówków "
                          f"({c.get('injuries', 0)} kontuzje, "
                          f"{c.get('suspensions', 0)} zawieszenia, "
                          f"{c.get('doubts', 0)} wątpliwe)")
            except Exception as e:  # noqa: BLE001
                print(f"   ⚠️ News intel skip: {e}")

            # Backfill kursów 1X2 do row (dla AI engine)
            mw = analysis.get("match_winner") or {}
            mw_odds = mw.get("odds") or {}
            row.setdefault("home_odds", mw_odds.get("home"))
            row.setdefault("draw_odds", mw_odds.get("draw"))
            row.setdefault("away_odds", mw_odds.get("away"))

            _attach_ai(row)

            record = _build_frontend_record(row, analysis, date)
            records.append(record)
            print(f"   🧠 {analysis.get('verdict', '')[:110]}")

        # ── Zapis JSON ──
        print("\n💾 KROK 4/4: Zapis wyników...")
        os.makedirs(RESULTS_DIR, exist_ok=True)
        outfn = os.path.join(RESULTS_DIR, f"worldcup_{date}.json")
        payload = {
            "tournament": "FIFA World Cup 2026",
            "date": date,
            "generatedAt": datetime.now().isoformat(),
            "bookmaker": "Pinnacle",
            "count": len(records),
            "matches": records,
        }
        with open(outfn, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"✅ Zapisano: {outfn} ({len(records)} meczów)")

        # ── Supabase ──
        if use_supabase and records:
            saved = _save_supabase(records, date)
            print(f"✅ Supabase: zapisano {saved}/{len(records)}")

    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass

    elapsed = time.time() - t0
    print("\n" + "=" * 70)
    print(f"🏁 GOTOWE — {len(records)} meczów w {elapsed/60:.1f} min")
    print("=" * 70)
    return {"date": date, "count": len(records), "elapsed": elapsed}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="World Cup dzienny pakiet analityczny (Pinnacle full markets)")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="Data YYYY-MM-DD (domyślnie dziś)")
    parser.add_argument("--headless", action="store_true", help="Chrome bez GUI")
    parser.add_argument("--max-matches", type=int, default=None,
                        help="Limit meczów (test)")
    parser.add_argument("--no-supabase", action="store_true",
                        help="Nie zapisuj do Supabase")
    parser.add_argument("--request-delay", type=float, default=0.15,
                        help="Opóźnienie między zapytaniami o rynki (s)")
    args = parser.parse_args()

    run_pipeline(
        date=args.date,
        headless=args.headless,
        max_matches=args.max_matches,
        use_supabase=not args.no_supabase,
        request_delay=args.request_delay,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
