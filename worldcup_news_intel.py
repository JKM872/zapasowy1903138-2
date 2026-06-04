"""
🏆 World Cup — News & Match Intel
=================================
Przechwytuje i analizuje wiadomości/informacje o KAŻDYM meczu MŚ, żeby przed
spotkaniem mieć komplet kontekstu pozarynkowego: kontuzje, zawieszenia, składy,
powroty, forma, zapowiedzi. To uzupełnia twarde dane (Pinnacle/SofaScore/Forebet)
o "miękki" wywiad, który często rusza linią.

Źródło: Google News RSS (darmowe, bez klucza, zwraca czysty XML). Dla każdego
meczu odpytujemy kilka zapytań (zapowiedź meczu + team news każdej drużyny),
deduplikujemy i klasyfikujemy nagłówki deterministycznie po słowach kluczowych
(PL + EN), licząc "impact" każdej informacji.

Architektura jak w worldcup_forebet_extras:
  • curl_cffi (Chrome TLS) z fallbackiem na urllib (stdlib),
  • cache per-zapytanie z TTL,
  • best-effort — brak sieci / zmiana formatu nie psuje pipeline'u.

Parsowanie i klasyfikacja są oddzielone od sieci, więc są w 100% testowalne
offline (patrz test_worldcup_news_intel.py).
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

try:
    from curl_cffi import requests as _curl
    _CURL_OK = True
except Exception:  # noqa: BLE001
    _CURL_OK = False

_RSS_BASE = "https://news.google.com/rss/search"

# cache: {query_key: (timestamp, [items])}
_NEWS_CACHE: Dict[str, tuple] = {}
_CACHE_TTL = 1800  # 30 min
_MAX_HEADLINES = 25
_FETCH_TIMEOUT = 8           # twardy limit pojedynczego requestu (s)
_MATCH_BUDGET_S = 25.0       # twardy budżet czasu na cały wywiad jednego meczu (s)

# Domyślne lokalizacje Google News (lang, country). EN globalnie + PL dla
# polskiego odbiorcy. Workflow może to nadpisać przez WC_NEWS_LOCALES.
_DEFAULT_LOCALES: List[Tuple[str, str]] = [
    ("en", "US"),
    ("en", "GB"),
    ("pl", "PL"),
]


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, "").strip())
        return v if v > 0 else default
    except (ValueError, AttributeError):
        return default


def _configured_locales() -> List[Tuple[str, str]]:
    """Lokalizacje z env WC_NEWS_LOCALES='en-US,en-GB,pl-PL,es-ES' lub domyślne."""
    raw = (os.getenv("WC_NEWS_LOCALES") or "").strip()
    if not raw:
        return list(_DEFAULT_LOCALES)
    locales: List[Tuple[str, str]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        # akceptuj 'en-US' lub 'en_US' lub 'en:US'
        parts = re.split(r"[-_:]", token)
        if len(parts) == 2 and parts[0] and parts[1]:
            locales.append((parts[0].lower(), parts[1].upper()))
        elif len(parts) == 1:
            locales.append((parts[0].lower(), parts[0].upper()))
    return locales or list(_DEFAULT_LOCALES)


# --------------------------------------------------------------------------- #
# Klasyfikacja nagłówków (PL + EN) — słowa kluczowe -> tagi -> impact
# --------------------------------------------------------------------------- #
# Każdy tag ma wagę "impact": 3 = krytyczny dla typu, 2 = istotny, 1 = kontekst.
_KEYWORDS: Dict[str, List[str]] = {
    "injury": [
        "injury", "injured", "knock", "strain", "hamstring", "acl", "ruled out",
        "sidelined", "fitness doubt", "muscle",
        "kontuzja", "uraz", "kontuzjowany", "naderwanie", "uszkodzenie",
        "pauzuje przez uraz",
    ],
    "suspension": [
        # uwaga: bez gołego "ban" — łapało polityczne "ban on ..." (false positive)
        "suspended", "suspension", "banned", "match ban", "two-match ban",
        "red card", "yellow card accumulation", "booking", "sent off",
        "zawieszony", "zawieszenie", "czerwona kartka", "pauza za kartki", "dyskwalifikacja",
    ],
    "doubt": [
        "doubt", "doubtful", "questionable", "late fitness test", "race against time",
        "uncertain", "may miss", "could miss",
        "wątpliwy", "niepewny", "pod znakiem zapytania", "zagrożony występ",
    ],
    "return": [
        "returns", "return", "back from injury", "fit again", "recovered", "available again",
        "powrót", "wraca", "wyzdrowiał", "gotowy do gry", "do dyspozycji",
    ],
    "lineup": [
        "lineup", "line-up", "starting xi", "predicted xi", "probable lineup",
        "team news", "squad", "named squad", "call-up", "called up",
        "skład", "wyjściowa jedenastka", "przewidywany skład", "powołania", "kadra",
    ],
    "form": [
        "winning run", "unbeaten", "losing streak", "in form", "out of form",
        "morale", "confidence",
        "forma", "seria zwycięstw", "passa", "bez porażki", "kryzys", "morale",
    ],
    "tactics": [
        "tactics", "formation", "system", "approach", "game plan",
        "taktyka", "ustawienie", "formacja", "plan na mecz",
    ],
    "preview": [
        "preview", "prediction", "predictions", "betting tips", "how to watch",
        "head to head", "h2h", "build-up",
        "zapowiedź", "typy", "przewidywania", "kursy", "gdzie oglądać",
    ],
}

_TAG_IMPACT = {
    "injury": 3, "suspension": 3, "doubt": 2, "return": 2,
    "lineup": 2, "form": 1, "tactics": 1, "preview": 1, "general": 0,
}


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9ąćęłńóśźż ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Słowa sygnalizujące, że nagłówek faktycznie dotyczy piłki/meczu, a nie
# polityki/gospodarki itp. (filtr trafień typu "Spain and Germany ban ...").
_FOOTBALL_CONTEXT = [
    "football", "soccer", "match", "vs", "v ", "world cup", "fifa", "group",
    "goal", "striker", "midfielder", "defender", "goalkeeper", "coach", "manager",
    "squad", "lineup", "line-up", "xi", "injury", "injured", "suspended", "fit",
    "kick-off", "kickoff", "friendly", "qualifier", "national team", "cap",
    "piłka", "pilka", "mecz", "reprezentacja", "trener", "bramk", "napastnik",
    "obrońca", "obronca", "pomocnik", "kontuzja", "skład", "sklad", "mundial",
    "mistrzostwa", "gol ", "puchar świata", "puchar swiata",
]
# Twarde wykluczenia — tematy, które nigdy nie są wywiadem meczowym.
_OFFTOPIC = [
    "european commission", "technology companies", "tariff", "stock", "economy",
    "election", "parliament", "court rules", "lawsuit", "chinese technology",
    "interest rate", "inflation", "minister", "diplomatic",
]


def is_football_relevant(title: str) -> bool:
    """Czy nagłówek to realnie kontekst piłkarski/meczowy (anty-polityka/biznes)."""
    t = _norm(title)
    if not t:
        return False
    if any(_norm(x) in t for x in _OFFTOPIC):
        return False
    return any(_norm(x) in t for x in _FOOTBALL_CONTEXT)


def _similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def classify_headline(title: str) -> List[str]:
    """Zwraca listę tagów wykrytych w nagłówku (PL+EN). Pusta -> ['general']."""
    t = _norm(title)
    if not t:
        return ["general"]
    tags: List[str] = []
    for tag, kws in _KEYWORDS.items():
        for kw in kws:
            if _norm(kw) in t:
                tags.append(tag)
                break
    return tags or ["general"]


def headline_impact(tags: List[str]) -> int:
    """Najwyższy impact spośród tagów nagłówka."""
    return max((_TAG_IMPACT.get(tg, 0) for tg in tags), default=0)


def teams_in_headline(title: str, home: str, away: str, threshold: float = 0.6) -> List[str]:
    """Które drużyny występują w nagłówku."""
    t = _norm(title)
    found: List[str] = []
    for team in (home, away):
        if not team:
            continue
        # dopasowanie po pełnej nazwie lub którymkolwiek długim słowie nazwy
        if _similar(team, t) >= threshold or any(
            len(w) >= 4 and w in t for w in _norm(team).split()
        ):
            found.append(team)
    return found


# --------------------------------------------------------------------------- #
# Parsowanie RSS (offline-testowalne)
# --------------------------------------------------------------------------- #
def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def parse_rss(xml_text: str) -> List[Dict[str, Any]]:
    """Parsuje RSS 2.0 (Google News) -> lista {title, source, published, url}."""
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: List[Dict[str, Any]] = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        src_el = it.find("source")
        source = (src_el.text.strip() if src_el is not None and src_el.text else "")
        # Google News tytuł bywa "Nagłówek - Źródło" — wydziel źródło jeśli brak <source>
        if not source and " - " in title:
            head, _, tail = title.rpartition(" - ")
            if head and len(tail) <= 40:
                title, source = head.strip(), tail.strip()
        items.append({
            "title": _strip_tags(title),
            "source": source,
            "published": pub,
            "url": link,
        })
    return items


def _dedupe(items: List[Dict[str, Any]], threshold: float = 0.85) -> List[Dict[str, Any]]:
    """Usuwa zbliżone nagłówki (różne źródła tej samej wiadomości)."""
    out: List[Dict[str, Any]] = []
    for it in items:
        if any(_similar(it["title"], k["title"]) >= threshold for k in out):
            continue
        out.append(it)
    return out


# --------------------------------------------------------------------------- #
# Agregacja wywiadu (offline-testowalne)
# --------------------------------------------------------------------------- #
def build_intel(raw_items: List[Dict[str, Any]], home: str, away: str,
                max_headlines: Optional[int] = None) -> Dict[str, Any]:
    """
    Z surowych nagłówków buduje uporządkowany wywiad meczowy:
    klasyfikuje, deduplikuje, sortuje wg impactu, wyciąga kluczowe absencje
    i składa polskie podsumowanie. Deterministyczne, bez sieci.
    """
    cap = max_headlines if (max_headlines and max_headlines > 0) else _MAX_HEADLINES
    deduped = _dedupe(raw_items)
    # Filtr trafności: odrzuć nagłówki bez kontekstu piłkarskiego (polityka, biznes itp.)
    relevant = [it for it in deduped if is_football_relevant(it.get("title", ""))]
    enriched: List[Dict[str, Any]] = []
    for it in relevant:
        tags = classify_headline(it["title"])
        enriched.append({
            **it,
            "tags": tags,
            "impact": headline_impact(tags),
            "teams": teams_in_headline(it["title"], home, away),
        })

    # Sort: najpierw najwyższy impact, potem obecność konkretnej drużyny
    enriched.sort(key=lambda x: (x["impact"], len(x["teams"])), reverse=True)
    enriched = enriched[:cap]

    def _of(tag: str) -> List[Dict[str, Any]]:
        return [e for e in enriched if tag in e["tags"]]

    injuries = _of("injury")
    suspensions = _of("suspension")
    doubts = _of("doubt")
    returns = _of("return")
    lineup_news = _of("lineup")

    # Kluczowe absencje = kontuzje + zawieszenia (najwyższy priorytet)
    key_absences = [
        {"title": e["title"], "source": e["source"], "teams": e["teams"],
         "type": "injury" if "injury" in e["tags"] else "suspension"}
        for e in enriched if ("injury" in e["tags"] or "suspension" in e["tags"])
    ][:6]

    counts = {
        "headlines": len(enriched),
        "injuries": len(injuries),
        "suspensions": len(suspensions),
        "doubts": len(doubts),
        "returns": len(returns),
        "lineup_news": len(lineup_news),
    }

    summary = _build_summary(counts, key_absences, enriched, home, away)
    sources = sorted({e["source"] for e in enriched if e["source"]})

    return {
        "available": bool(enriched),
        "headlines": enriched,
        "injuries": injuries,
        "suspensions": suspensions,
        "doubts": doubts,
        "returns": returns,
        "lineup_news": lineup_news,
        "key_absences": key_absences,
        "counts": counts,
        "sources": sources,
        "sources_count": len(sources),
        "summary": summary,
    }


def _build_summary(counts: Dict[str, int], key_absences: List[Dict[str, Any]],
                   enriched: List[Dict[str, Any]], home: str, away: str) -> str:
    """Krótkie polskie podsumowanie wywiadu przed meczem."""
    if not enriched:
        return "Brak doniesień medialnych przed meczem."
    parts: List[str] = []
    flags: List[str] = []
    if counts["injuries"]:
        flags.append(f"{counts['injuries']} doniesień o kontuzjach")
    if counts["suspensions"]:
        flags.append(f"{counts['suspensions']} o zawieszeniach")
    if counts["doubts"]:
        flags.append(f"{counts['doubts']} o niepewnych występach")
    if counts["returns"]:
        flags.append(f"{counts['returns']} o powrotach")
    if flags:
        parts.append("⚠️ Sygnały kadrowe: " + ", ".join(flags) + ".")
    else:
        parts.append("Brak istotnych sygnałów kadrowych w mediach.")
    if key_absences:
        top = key_absences[0]
        who = ", ".join(top["teams"]) if top["teams"] else "—"
        parts.append(f"Najważniejsze: {top['title']} ({who}).")
    parts.append(f"Łącznie {counts['headlines']} unikalnych nagłówków.")
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# Warstwa sieciowa
# --------------------------------------------------------------------------- #
def _rss_url(query: str, lang: str, country: str) -> str:
    q = urllib.parse.quote(query)
    ceid = f"{country}:{lang}"
    return (f"{_RSS_BASE}?q={q}&hl={lang}-{country}&gl={country}&ceid="
            + urllib.parse.quote(ceid, safe=":"))


def _fetch_rss(query: str, lang: str, country: str) -> List[Dict[str, Any]]:
    """Pobiera i parsuje jedno zapytanie RSS (curl_cffi -> fallback urllib)."""
    cache_key = f"{lang}|{country}|{query}"
    cached = _NEWS_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]

    url = _rss_url(query, lang, country)
    xml_text: Optional[str] = None

    if _CURL_OK:
        try:
            resp = _curl.get(url, impersonate="chrome", timeout=_FETCH_TIMEOUT)
            if resp.status_code == 200 and "<rss" in resp.text[:200].lower():
                xml_text = resp.text
        except Exception:  # noqa: BLE001
            xml_text = None

    if xml_text is None:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "WorldCupAnalysis/1.0"})
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                xml_text = resp.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            xml_text = None

    items = parse_rss(xml_text) if xml_text else []
    _NEWS_CACHE[cache_key] = (time.time(), items)
    return items


def _query_set(home: str, away: str, deep: bool = False) -> List[str]:
    """Zestaw zapytań pokrywający kontekst meczowy.

    Domyślnie (deep=False) zwięzły zestaw 3 zapytań — szybki i wystarczający.
    deep=True dokłada dodatkowe kąty (predykcje, osobny team news, PL) gdy
    workflow ma większy budżet czasu (WC_NEWS_DEEP=1).
    """
    base = [
        f"{home} vs {away} World Cup",
        f"{home} World Cup squad injury suspension lineup",
        f"{away} World Cup squad injury suspension lineup",
    ]
    if not deep:
        return base
    return base + [
        f"{home} vs {away} preview prediction",
        f"{home} {away} kontuzje skład",          # PL angle
    ]


def fetch_match_intel(home: str, away: str,
                      lang: Optional[str] = None,
                      country: Optional[str] = None,
                      locales: Optional[List[Tuple[str, str]]] = None,
                      max_headlines: Optional[int] = None,
                      budget_s: Optional[float] = None) -> Dict[str, Any]:
    """
    Główne API: zbiera wywiad medialny przed meczem ``home`` vs ``away``.

    Odpytuje zestaw zapytań (zapowiedź + team news obu drużyn; w trybie deep
    także predykcje i kąt PL) w wielu lokalizacjach Google News (domyślnie
    EN-US/EN-GB/PL-PL, można nadpisać przez ``locales`` lub env WC_NEWS_LOCALES).
    Łączy wyniki, deduplikuje globalnie i klasyfikuje.

    Twardy budżet czasu (``budget_s`` / env WC_NEWS_BUDGET_S, domyślnie 25 s)
    gwarantuje, że pipeline nie zawiśnie nawet przy wielu lokalizacjach —
    po przekroczeniu budżetu zwracamy to, co udało się zebrać.

    Best-effort — przy braku sieci zwraca available=False zamiast wyjątku.
    Wsteczna zgodność: ``fetch_match_intel(h, a, "en", "US")`` nadal działa.
    """
    cap = max_headlines or _env_int("WC_NEWS_MAX_HEADLINES", _MAX_HEADLINES)
    budget = budget_s if (budget_s and budget_s > 0) else \
        float(_env_int("WC_NEWS_BUDGET_S", int(_MATCH_BUDGET_S)))
    deep = (os.getenv("WC_NEWS_DEEP") or "").strip() in ("1", "true", "yes", "on")

    empty = build_intel([], home, away, max_headlines=cap)
    if not home or not away:
        return empty

    # Ustal listę lokalizacji do odpytania.
    if locales is not None:
        loc_list = locales
    elif lang and country:
        loc_list = [(lang.lower(), country.upper())]
    else:
        loc_list = _configured_locales()

    queries = _query_set(home, away, deep=deep)
    collected: List[Dict[str, Any]] = []
    seen_urls = set()
    seen_titles: List[str] = []
    deadline = time.time() + budget
    locales_done: List[str] = []
    truncated = False

    for (lg, ctry) in loc_list:
        if time.time() >= deadline:
            truncated = True
            break
        for q in queries:
            if time.time() >= deadline:
                truncated = True
                break
            try:
                items = _fetch_rss(q, lg, ctry)
            except Exception:  # noqa: BLE001
                continue
            for it in items:
                u = it.get("url") or it.get("title")
                if u in seen_urls:
                    continue
                title = it.get("title", "")
                if any(t == title for t in seen_titles):
                    continue
                seen_urls.add(u)
                seen_titles.append(title)
                it["locale"] = f"{lg}-{ctry}"
                collected.append(it)
        locales_done.append(f"{lg}-{ctry}")

    if not collected:
        out = empty
        out["locales_queried"] = locales_done
        out["budget_truncated"] = truncated
        return out

    intel = build_intel(collected, home, away, max_headlines=cap)
    intel["locales_queried"] = locales_done
    intel["queries_per_locale"] = len(queries)
    intel["budget_truncated"] = truncated
    return intel


if __name__ == "__main__":
    import json
    import sys
    h = sys.argv[1] if len(sys.argv) > 1 else "Mexico"
    a = sys.argv[2] if len(sys.argv) > 2 else "South Africa"
    # Opcjonalnie pojedyncza lokalizacja z CLI: python ... Mexico "South Africa" en US
    if len(sys.argv) > 4:
        result = fetch_match_intel(h, a, sys.argv[3], sys.argv[4])
    else:
        result = fetch_match_intel(h, a)
    print(json.dumps(result, indent=2, ensure_ascii=False))
