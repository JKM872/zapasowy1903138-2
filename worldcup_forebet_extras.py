"""
🏆 World Cup — Forebet extras (corners, cards, scorers, TOP trends)
===================================================================
Pobiera z Forebet dodatkowe rynki/treści specyficzne dla MŚ, których nie
zwraca API Pinnacle, a które widać na stronie turnieju:

  • corners  — Under/Over 9.5 rożnych + predykcja + avg
  • cards    — Under/Over 4.5 kartek + predykcja + avg
  • scorers  — kto strzeli pierwszy (1 / Nikt / 2)
  • trends   — TOP trends World Cup (serie/statystyki tekstowe)

Korzysta z curl_cffi (Chrome TLS) — tej samej metody bypassu Cloudflare,
której używa forebet_scraper. Dane są dopasowywane do meczu po nazwach drużyn
(fuzzy), z pamięcią podręczną per (data) żeby nie pobierać strony wiele razy.

Wszystko best-effort: brak danych nie psuje pipeline'u.
"""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

try:
    from curl_cffi import requests as _curl
    _CURL_OK = True
except Exception:  # noqa: BLE001
    _CURL_OK = False

_BASE = "https://www.forebet.com/en/football-tips-and-predictions-for-today"
_SUBPAGES = {
    "corners": f"{_BASE}/corners",
    "cards": f"{_BASE}/cards",
    "scorers": f"{_BASE}/scorers",
}

# cache: {(kind): (timestamp, html)}
_HTML_CACHE: Dict[str, tuple] = {}
_CACHE_TTL = 1800  # 30 min


def _norm(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def _fetch(url: str, kind: str) -> Optional[str]:
    """Pobiera HTML strony Forebet z cache + curl_cffi."""
    if not _CURL_OK:
        return None
    cached = _HTML_CACHE.get(kind)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]
    try:
        resp = _curl.get(url, impersonate="chrome", timeout=25)
        if resp.status_code == 200 and "forebet" in resp.text.lower():
            _HTML_CACHE[kind] = (time.time(), resp.text)
            return resp.text
    except Exception:  # noqa: BLE001
        return None
    return None


def _row_matches_teams(text: str, home: str, away: str, threshold: float = 0.55) -> bool:
    """Sprawdza czy fragment tekstu wiersza dotyczy danego meczu."""
    t = _norm(text)
    return _similar(home, t) >= threshold and _similar(away, t) >= threshold


# --------------------------------------------------------------------------- #
# Parsery poszczególnych sekcji (defensywne — strona bywa zmienna)
# --------------------------------------------------------------------------- #
def _parse_ou_rows(html: str, home: str, away: str, line_hint: str) -> Optional[Dict[str, Any]]:
    """Wyłuskuje wiersz Under/Over (corners/cards) dla danego meczu."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.rcnt, tr.tr_0, tr.tr_1, div.schema") or soup.find_all("tr")
    for row in rows:
        txt = row.get_text(" ", strip=True)
        if not txt or len(txt) < 8:
            continue
        if not _row_matches_teams(txt, home, away):
            continue
        pred = None
        m = re.search(r"\b(Over|Under)\b", txt, re.I)
        if m:
            pred = m.group(1).title() + f" {line_hint}"
        avg = None
        am = re.search(r"\b(\d{1,2}\.\d)\b", txt)
        if am:
            avg = float(am.group(1))
        return {"prediction": pred, "avg": avg, "line": line_hint, "raw": txt[:160]}
    return None


def _parse_scorers(html: str, home: str, away: str) -> Optional[Dict[str, Any]]:
    """Wyłuskuje 'kto strzeli pierwszy' (1 / Nikt / 2) dla meczu."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.rcnt, tr.tr_0, tr.tr_1") or soup.find_all("tr")
    for row in rows:
        txt = row.get_text(" ", strip=True)
        if not _row_matches_teams(txt, home, away):
            continue
        # Forebet pokazuje 3 liczby prob. dla 1/Noone/2
        nums = re.findall(r"\b(\d{1,3})\b", txt)
        pick = None
        low = txt.lower()
        if "noone" in low or "no one" in low or "nikt" in low:
            pick = "Nikt"
        return {"raw": txt[:160], "pick": pick,
                "probs": nums[:3] if len(nums) >= 3 else None}
    return None


def _parse_trends(html: str, home: str, away: str) -> List[str]:
    """Zbiera TOP trends World Cup dotyczące którejkolwiek z drużyn."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    trends: List[str] = []
    # Forebet trendy to zwykle krótkie zdania w blokach .tabcont / .trend
    candidates = soup.select(".trend, .tr_trend, .predict_no, .stands, li, p")
    for el in candidates:
        txt = el.get_text(" ", strip=True)
        if not txt or len(txt) < 25 or len(txt) > 240:
            continue
        if _similar(home, txt) >= 0.6 or _similar(away, txt) >= 0.6:
            low = txt.lower()
            if any(k in low for k in ("unbeaten", "won", "win", "lost", "clean sheet",
                                       "undefeated", "scored", "under", "over", "draw",
                                       "streak", "ht/ft", "winless")):
                if txt not in trends:
                    trends.append(txt)
        if len(trends) >= 4:
            break
    return trends


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def fetch_forebet_extras(home: str, away: str) -> Dict[str, Any]:
    """
    Zwraca dodatkowe dane Forebet dla meczu MŚ.
    Klucze: corners, cards, who_scores_first, trends (każdy może być None/[]).
    """
    result: Dict[str, Any] = {
        "corners": None,
        "cards": None,
        "who_scores_first": None,
        "trends": [],
        "available": False,
    }
    if not _CURL_OK or not home or not away:
        return result

    html_corners = _fetch(_SUBPAGES["corners"], "corners")
    if html_corners:
        result["corners"] = _parse_ou_rows(html_corners, home, away, "9.5")

    html_cards = _fetch(_SUBPAGES["cards"], "cards")
    if html_cards:
        result["cards"] = _parse_ou_rows(html_cards, home, away, "4.5")

    html_scorers = _fetch(_SUBPAGES["scorers"], "scorers")
    if html_scorers:
        result["who_scores_first"] = _parse_scorers(html_scorers, home, away)

    # Trends: szukaj na stronie corners/scorers (Forebet pokazuje trendy globalnie)
    for h in (html_scorers, html_corners):
        if h:
            t = _parse_trends(h, home, away)
            if t:
                result["trends"] = t
                break

    result["available"] = any([result["corners"], result["cards"],
                               result["who_scores_first"], result["trends"]])
    return result


if __name__ == "__main__":
    import json
    import sys
    h = sys.argv[1] if len(sys.argv) > 1 else "Mexico"
    a = sys.argv[2] if len(sys.argv) > 2 else "South Africa"
    print(json.dumps(fetch_forebet_extras(h, a), indent=2, ensure_ascii=False))
