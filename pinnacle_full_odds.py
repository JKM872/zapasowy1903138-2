"""
🎯 Pinnacle Full Odds Fetcher
=============================
Pobiera KOMPLETNY pakiet rynków od Pinnacle (bookmaker ID 3) z Livesport
GraphQL API — nie tylko 1X2, ale wszystko co API udostępnia:

  • HOME_DRAW_AWAY      — 1X2 (zwycięstwo / remis / przegrana)
  • DOUBLE_CHANCE       — podwójna szansa (1X / 12 / X2)
  • BOTH_TEAMS_TO_SCORE — obie drużyny strzelą (BTTS)
  • OVER_UNDER          — wszystkie linie totali goli (0.5, 1.5, 2.5, ...)
  • ASIAN_HANDICAP      — wszystkie linie handicapu azjatyckiego
  • CORRECT_SCORE       — dokładny wynik (wszystkie scoreline'y)

Każda pozycja zawiera kurs bieżący (`value`), kurs otwarcia (`opening`)
oraz kierunek ruchu linii (UP/DOWN) — co pozwala wykrywać ruchy
"ostrych pieniędzy" (sharp money) i wyliczać prawdopodobieństwo implikowane
po usunięciu marży bukmacherskiej (vig).

Endpoint i nagłówki są wspólne z `livesport_odds_api.LivesportOddsAPI`.
Pinnacle to bukmacher o najniższej marży, więc jego kursy są najbliższe
"prawdziwemu" prawdopodobieństwu — idealny fundament pod analizę value.

Użycie:
    from pinnacle_full_odds import PinnacleFullOdds
    api = PinnacleFullOdds()
    pkg = api.get_full_odds_for_match(match_url)   # dict z wszystkimi rynkami
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from livesport_odds_api import LivesportOddsAPI

# Bukmacher Pinnacle w Livesport GraphQL
PINNACLE_ID = "3"

# Endpoint persisted-query (ten sam co w livesport_odds_api)
GRAPHQL_URL = "https://global.ds.lsapp.eu/odds/pq_graphql"
GRAPHQL_HASH = "ope2"

# Rynki potwierdzone jako dostępne dla Pinnacle przez to API (betScope=FULL_TIME).
# DRAW_NO_BET / ODD_EVEN / HANDICAP / scope FIRST_HALF zwracają 400 i są pominięte.
SUPPORTED_MARKETS = [
    "HOME_DRAW_AWAY",
    "DOUBLE_CHANCE",
    "BOTH_TEAMS_TO_SCORE",
    "OVER_UNDER",
    "ASIAN_HANDICAP",
    "CORRECT_SCORE",
]


def _to_float(val: Any) -> Optional[float]:
    """Bezpieczna konwersja kursu na float (Livesport zwraca stringi)."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_item(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Parsuje pojedynczy EventOddsOverviewItem -> {value, opening, change, active}."""
    if not item or not isinstance(item, dict):
        return None
    value = _to_float(item.get("value"))
    if value is None:
        return None
    opening = _to_float(item.get("opening"))
    change = item.get("change") or {}
    movement = None
    if isinstance(change, dict):
        movement = change.get("type")  # 'UP' | 'DOWN' | None
    drift = None
    if opening and value:
        # dodatni drift = kurs urósł (mniej prawdopodobne wg rynku)
        drift = round(value - opening, 3)
    return {
        "value": value,
        "opening": opening,
        "movement": movement,        # kierunek ruchu kursu
        "drift": drift,              # value - opening
        "active": bool(item.get("active", True)),
    }


def implied_prob(odd: Optional[float]) -> Optional[float]:
    """Prawdopodobieństwo implikowane (z marżą) z kursu dziesiętnego, w %."""
    if not odd or odd <= 1.0:
        return None
    return round(100.0 / odd, 2)


def remove_vig_two_way(odd_a: Optional[float], odd_b: Optional[float]):
    """Usuwa marżę z rynku dwustronnego. Zwraca (prob_a%, prob_b%, vig%)."""
    pa, pb = implied_prob(odd_a), implied_prob(odd_b)
    if pa is None or pb is None:
        return None, None, None
    total = pa + pb
    if total <= 0:
        return None, None, None
    fair_a = round(pa / total * 100, 2)
    fair_b = round(pb / total * 100, 2)
    vig = round(total - 100, 2)
    return fair_a, fair_b, vig


def remove_vig_three_way(odd_h, odd_d, odd_a):
    """Usuwa marżę z rynku 1X2. Zwraca (h%, d%, a%, vig%)."""
    ph, pd, pa = implied_prob(odd_h), implied_prob(odd_d), implied_prob(odd_a)
    parts = [p for p in (ph, pd, pa) if p is not None]
    if len(parts) < 2:
        return None, None, None, None
    total = sum(parts)
    if total <= 0:
        return None, None, None, None
    fair_h = round(ph / total * 100, 2) if ph is not None else None
    fair_d = round(pd / total * 100, 2) if pd is not None else None
    fair_a = round(pa / total * 100, 2) if pa is not None else None
    vig = round(total - 100, 2)
    return fair_h, fair_d, fair_a, vig


class PinnacleFullOdds:
    """Pobiera pełny pakiet rynków Pinnacle dla wydarzenia Livesport."""

    def __init__(self, geo_ip_code: str = "PL", geo_subdivision: str = "PL10",
                 request_delay: float = 0.15, timeout: int = 12):
        self.timeout = timeout
        self.request_delay = request_delay
        # Reużyj ekstrakcji event_id z istniejącego klienta
        self._id_helper = LivesportOddsAPI(bookmaker_id=PINNACLE_ID,
                                           geo_ip_code=geo_ip_code,
                                           geo_subdivision=geo_subdivision)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
            "Origin": "https://www.livesport.com",
            "Referer": "https://www.livesport.com/",
            "x-geoip-code": geo_ip_code,
            "x-geoip-subdivision": geo_subdivision,
        })

    # ------------------------------------------------------------------ #
    # Low-level fetch
    # ------------------------------------------------------------------ #
    def _fetch_market(self, event_id: str, bet_type: str) -> Optional[Dict[str, Any]]:
        """Pobiera surowy obiekt rynku z GraphQL lub None."""
        params = {
            "_hash": GRAPHQL_HASH,
            "eventId": event_id,
            "bookmakerId": PINNACLE_ID,
            "betType": bet_type,
            "betScope": "FULL_TIME",
        }
        try:
            r = self.session.get(GRAPHQL_URL, params=params, timeout=self.timeout)
            if r.status_code != 200:
                return None
            data = r.json()
            return (data.get("data") or {}).get("findPrematchOddsForBookmaker")
        except (requests.RequestException, ValueError):
            return None

    # ------------------------------------------------------------------ #
    # Per-market parsers
    # ------------------------------------------------------------------ #
    def _parse_1x2(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        home = _parse_item(raw.get("home"))
        draw = _parse_item(raw.get("draw"))
        away = _parse_item(raw.get("away"))
        if not home and not away:
            return None
        fh, fd, fa, vig = remove_vig_three_way(
            home["value"] if home else None,
            draw["value"] if draw else None,
            away["value"] if away else None,
        )
        return {
            "home": home, "draw": draw, "away": away,
            "fair_prob": {"home": fh, "draw": fd, "away": fa},
            "vig": vig,
        }

    def _parse_double_chance(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ho_d = _parse_item(raw.get("homeOrDraw"))
        aw_d = _parse_item(raw.get("awayOrDraw"))
        no_d = _parse_item(raw.get("noDraw"))
        if not any([ho_d, aw_d, no_d]):
            return None
        return {"homeOrDraw": ho_d, "awayOrDraw": aw_d, "homeOrAway": no_d}

    def _parse_btts(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        yes = _parse_item(raw.get("yes"))
        no = _parse_item(raw.get("no"))
        if not yes and not no:
            return None
        fy, fn, vig = remove_vig_two_way(
            yes["value"] if yes else None,
            no["value"] if no else None,
        )
        return {"yes": yes, "no": no,
                "fair_prob": {"yes": fy, "no": fn}, "vig": vig}

    def _parse_over_under(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        lines: List[Dict[str, Any]] = []
        for opp in raw.get("opportunities") or []:
            over = _parse_item(opp.get("over"))
            under = _parse_item(opp.get("under"))
            handicap = _to_float((opp.get("handicap") or {}).get("value"))
            if handicap is None or (not over and not under):
                continue
            fo, fu, vig = remove_vig_two_way(
                over["value"] if over else None,
                under["value"] if under else None,
            )
            lines.append({
                "line": handicap, "over": over, "under": under,
                "fair_prob": {"over": fo, "under": fu}, "vig": vig,
            })
        if not lines:
            return None
        lines.sort(key=lambda x: x["line"])
        return {"lines": lines, "main_line": _closest_main_total(lines)}

    def _parse_asian_handicap(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        lines: List[Dict[str, Any]] = []
        for opp in raw.get("opportunities") or []:
            home = _parse_item(opp.get("home"))
            away = _parse_item(opp.get("away"))
            handicap = _to_float((opp.get("handicap") or {}).get("value"))
            if handicap is None or (not home and not away):
                continue
            fh, fa, vig = remove_vig_two_way(
                home["value"] if home else None,
                away["value"] if away else None,
            )
            lines.append({
                "line": handicap, "home": home, "away": away,
                "fair_prob": {"home": fh, "away": fa}, "vig": vig,
            })
        if not lines:
            return None
        lines.sort(key=lambda x: x["line"])
        return {"lines": lines}

    def _parse_correct_score(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for it in raw.get("items") or []:
            parsed = _parse_item(it.get("item"))
            score = it.get("score")
            if parsed and score:
                items.append({"score": score, **parsed})
        if not items:
            return None
        items.sort(key=lambda x: x["value"])  # najniższy kurs = najbardziej prawdopodobny
        return {"items": items, "most_likely": items[0]["score"] if items else None}

    _PARSERS = {
        "HOME_DRAW_AWAY": "_parse_1x2",
        "DOUBLE_CHANCE": "_parse_double_chance",
        "BOTH_TEAMS_TO_SCORE": "_parse_btts",
        "OVER_UNDER": "_parse_over_under",
        "ASIAN_HANDICAP": "_parse_asian_handicap",
        "CORRECT_SCORE": "_parse_correct_score",
    }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get_full_odds_for_event(self, event_id: str,
                                markets: Optional[List[str]] = None) -> Dict[str, Any]:
        """Pobiera i parsuje wszystkie obsługiwane rynki dla event_id."""
        markets = markets or SUPPORTED_MARKETS
        out: Dict[str, Any] = {
            "event_id": event_id,
            "bookmaker": "Pinnacle",
            "markets": {},
            "markets_available": [],
        }
        for bt in markets:
            raw = self._fetch_market(event_id, bt)
            if self.request_delay:
                time.sleep(self.request_delay)
            if not raw:
                continue
            parser = getattr(self, self._PARSERS[bt])
            parsed = parser(raw)
            if parsed:
                out["markets"][bt] = parsed
                out["markets_available"].append(bt)
        out["success"] = bool(out["markets_available"])
        return out

    def get_full_odds_for_match(self, match_url: str,
                                markets: Optional[List[str]] = None) -> Dict[str, Any]:
        """Główne wejście: pobiera pełny pakiet rynków na podstawie URL meczu."""
        event_id = self._id_helper.extract_event_id_from_url(match_url)
        if not event_id:
            return {"success": False, "error": "no_event_id",
                    "markets": {}, "markets_available": []}
        return self.get_full_odds_for_event(event_id, markets)


def _closest_main_total(lines: List[Dict[str, Any]]) -> Optional[float]:
    """Zwraca linię totala najbliższą zbalansowaniu kursów over/under (główna linia)."""
    best, best_gap = None, None
    for ln in lines:
        ov = (ln.get("over") or {}).get("value")
        un = (ln.get("under") or {}).get("value")
        if ov is None or un is None:
            continue
        gap = abs(ov - un)
        if best_gap is None or gap < best_gap:
            best_gap, best = gap, ln["line"]
    return best


# ============================================================================
# CLI test
# ============================================================================
if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pinnacle_full_odds.py <match_url>")
        sys.exit(1)

    api = PinnacleFullOdds()
    pkg = api.get_full_odds_for_match(sys.argv[1])
    print(json.dumps(pkg, indent=2, ensure_ascii=False))
    print(f"\nRynki dostępne: {pkg.get('markets_available')}")
