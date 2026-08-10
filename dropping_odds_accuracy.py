#!/usr/bin/env python3
"""SkutecznoĹ›Ä‡ typĂłw z pipeline'u OddsSafari dropping odds.

Odpowiada na pytanie, czy spadek kursu faktycznie wskazuje zwyciÄ™zcÄ™: bierze
zdarzenia z ``outputs/oddssafari_dropping_*.json``, dopasowuje je do
rozstrzygniÄ™Ä‡ i liczy trafnoĹ›Ä‡ oraz ROI, takĹĽe w podziale na segmenty.

Dlaczego osobny skrypt, a nie ``check_results.py``: ten drugi czyta
``outputs/mailed_manifest_*`` (karta gĹ‚Ăłwnego pipeline'u) i nie dotyka
zdarzeĹ„ dropping odds. Sporej ich czÄ™Ĺ›ci nie ma na karcie gĹ‚Ăłwnego pipeline'u,
wiÄ™c nie trafiajÄ… teĹĽ do ``result_store.json``.

RozstrzygniÄ™cia pobiera z dwĂłch ĹşrĂłdeĹ‚:

1. ``outputs/result_store.json`` â€” dopasowanie po URL Livesportu, a gdy go nie
   ma (zdarzenia ze Ĺ›cieĹĽki SofaScore), po znormalizowanych nazwach druĹĽyn.
2. SofaScore API po ``sofascore_event_id`` (tylko z ``--settle``), co domyka
   mecze, ktĂłrych gĹ‚Ăłwny pipeline nigdy nie widziaĹ‚.

ROI liczy przy stawce jednej jednostki na typ po kursie ``current_odds`` z
momentu scrapowania. To zaĹ‚oĹĽenie optymistyczne â€” realnie kurs mĂłgĹ‚ siÄ™ dalej
zmieniÄ‡ â€” wiÄ™c wynik traktuj jako gĂłrne oszacowanie.

PrzykĹ‚ady::

    python dropping_odds_accuracy.py                     # caĹ‚e archiwum
    python dropping_odds_accuracy.py --days 30           # ostatnie 30 dni
    python dropping_odds_accuracy.py --settle            # dociÄ…gnij braki z API
    python dropping_odds_accuracy.py --sport tennis
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

OUTPUTS_DIR = "outputs"
RESULT_STORE = os.path.join(OUTPUTS_DIR, "result_store.json")
DROPPING_GLOB = os.path.join(OUTPUTS_DIR, "oddssafari_dropping_*.json")
# RozstrzygniÄ™cia dociÄ…gniÄ™te z API trzymamy osobno, ĹĽeby nie mieszaÄ‡ ich ze
# store'em, ktĂłry utrzymuje check_results.py.
SETTLED_CACHE = os.path.join(OUTPUTS_DIR, "dropping_odds_settled.json")

OUTCOME_TO_SIDE = {"1": "home", "2": "away", "X": "draw", "x": "draw"}


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    return " ".join(name.split())


def _tokens(name: str) -> set:
    return {t for t in _normalize(name).split() if len(t) >= 4}


def _same_team(a: str, b: str) -> bool:
    """Czy to ta sama druĹĽyna, przy rĂłĹĽnych pisowniach w ĹşrĂłdĹ‚ach."""
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb and (ta & tb):
        return True
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _norm_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return url.split("?")[0].rstrip("/")


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    return default if f != f else f  # NaN


def _date_from_filename(path: str) -> Optional[str]:
    m = re.search(r"oddssafari_dropping_(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return m.group(1) if m else None


def _load_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# RozstrzygniÄ™cia
# ---------------------------------------------------------------------------


def _flip_result(res: Dict[str, Any]) -> Dict[str, Any]:
    """Przeorientuj wynik, gdy ĹşrĂłdĹ‚o ma zamienione strony gospodarz/goĹ›Ä‡."""
    flipped = dict(res)
    winner = res.get("winner")
    if winner == "home":
        flipped["winner"] = "away"
    elif winner == "away":
        flipped["winner"] = "home"
    flipped["score_home"] = res.get("score_away")
    flipped["score_away"] = res.get("score_home")
    flipped["home_team"] = res.get("away_team")
    flipped["away_team"] = res.get("home_team")
    return flipped


class Settler:
    """Ustala wynik meczu z dostÄ™pnych ĹşrĂłdeĹ‚."""

    def __init__(self, settle_via_api: bool = False):
        self.settle_via_api = settle_via_api
        self.by_url: Dict[str, Dict[str, Any]] = {}
        # Dopasowanie po nazwach idzie przez indeks odwrĂłcony token -> rekordy.
        # Liniowe skanowanie store'u nie ma tu prawa dziaĹ‚aÄ‡: przy 128 tys.
        # rozstrzygniÄ™Ä‡ i 2 tys. zdarzeĹ„ to Ä‡wierÄ‡ miliarda porĂłwnaĹ„.
        self.records: List[Tuple[set, set, Dict[str, Any]]] = []
        self.by_token: Dict[str, List[int]] = defaultdict(list)
        self.api_cache: Dict[str, Dict[str, Any]] = _load_json(SETTLED_CACHE) or {}
        self.api_calls = 0
        self.stats = defaultdict(int)

        store = _load_json(RESULT_STORE) or {}
        for url, res in store.items():
            if not isinstance(res, dict) or res.get("status") != "finished":
                continue
            if not res.get("winner"):
                continue
            n = _norm_url(url)
            if n:
                self.by_url[n] = res
            home, away = res.get("home_team"), res.get("away_team")
            if not (home and away):
                continue
            ht, at = _tokens(home), _tokens(away)
            if not (ht and at):
                continue
            idx = len(self.records)
            self.records.append((ht, at, res))
            for tok in ht | at:
                self.by_token[tok].append(idx)

    def _from_store(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        n = _norm_url(event.get("livesport_url"))
        if n and n in self.by_url:
            self.stats["ze_store_po_url"] += 1
            return self.by_url[n]

        # Zdarzenia ze Ĺ›cieĹĽki SofaScore nie majÄ… URL Livesportu â€” szukamy po
        # nazwach, ale tylko wĹ›rĂłd rekordĂłw dzielÄ…cych choÄ‡ jeden token.
        home, away = event.get("home_team"), event.get("away_team")
        ht, at = _tokens(home or ""), _tokens(away or "")
        if not (ht and at):
            return None

        candidates: Dict[int, int] = defaultdict(int)
        for tok in ht | at:
            for idx in self.by_token.get(tok, ()):
                candidates[idx] += 1
        if not candidates:
            return None

        # Najpierw rekordy dzielÄ…ce najwiÄ™cej tokenĂłw.
        for idx, _score in sorted(candidates.items(), key=lambda kv: -kv[1])[:40]:
            s_ht, s_at, res = self.records[idx]
            if (ht & s_ht) and (at & s_at):
                self.stats["ze_store_po_nazwach"] += 1
                return res
            # ĹąrĂłdĹ‚a bywajÄ… odwrĂłcone w kolejnoĹ›ci gospodarz/goĹ›Ä‡. Wtedy
            # 'winner' w rekordzie dotyczy przeciwnej strony niĹĽ w naszym
            # zdarzeniu, wiÄ™c zwracamy wersjÄ™ przeorientowanÄ… â€” inaczej
            # trafienia policzyĹ‚yby siÄ™ odwrotnie.
            if (ht & s_at) and (at & s_ht):
                self.stats["ze_store_po_nazwach_odwrotnie"] += 1
                return _flip_result(res)
        return None

    def _from_api(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        enr = event.get("enrichment") or {}
        eid = enr.get("sofascore_event_id")
        if not eid:
            return None
        key = str(eid)
        if key in self.api_cache:
            self.stats["z_cache_api"] += 1
            return self.api_cache[key]
        if not self.settle_via_api:
            return None
        try:
            from sofascore_scraper import get_event_result
        except ImportError:
            return None
        try:
            res = get_event_result(int(eid))
            self.api_calls += 1
        except Exception:
            return None
        if res:
            self.api_cache[key] = res
            self.stats["z_api"] += 1
            return res
        return None

    def settle(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._from_store(event) or self._from_api(event)

    def save_cache(self) -> None:
        if not self.api_cache:
            return
        try:
            os.makedirs(OUTPUTS_DIR, exist_ok=True)
            with open(SETTLED_CACHE, "w", encoding="utf-8") as f:
                json.dump(self.api_cache, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"âš ď¸Ź Nie udaĹ‚o siÄ™ zapisaÄ‡ cache rozstrzygniÄ™Ä‡: {exc}")


# ---------------------------------------------------------------------------
# Zbieranie typĂłw
# ---------------------------------------------------------------------------


def collect_picks(
    *,
    days: Optional[int] = None,
    sport: Optional[str] = None,
    qualified_only: bool = True,
    settle_via_api: bool = False,
) -> Tuple[List[Dict[str, Any]], Settler, Dict[str, int]]:
    settler = Settler(settle_via_api=settle_via_api)
    counters: Dict[str, int] = defaultdict(int)

    cutoff = None
    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    picks: List[Dict[str, Any]] = []
    seen = set()

    for path in sorted(glob.glob(DROPPING_GLOB)):
        if "_tmp_" in path:
            continue
        file_date = _date_from_filename(path)
        if cutoff and file_date and file_date < cutoff:
            continue
        data = _load_json(path)
        if not isinstance(data, dict):
            continue

        for event in data.get("events", []):
            counters["zdarzen_w_plikach"] += 1
            if qualified_only and not event.get("qualifies"):
                counters["niekwalifikowane"] += 1
                continue
            if sport and (event.get("sport") or "").lower() != sport.lower():
                continue

            outcome = str(event.get("dropped_outcome") or event.get("outcome") or "")
            side = OUTCOME_TO_SIDE.get(outcome)
            if not side:
                counters["nieznany_typ"] += 1
                continue

            # Ten sam mecz wraca w kilku przebiegach dnia â€” licz raz.
            dedup = (
                file_date or "",
                _normalize(event.get("home_team") or ""),
                _normalize(event.get("away_team") or ""),
                outcome,
            )
            if dedup in seen:
                counters["duplikaty"] += 1
                continue
            seen.add(dedup)

            result = settler.settle(event)
            if not result:
                counters["bez_rozstrzygniecia"] += 1
                continue

            winner = result.get("winner")
            if not winner:
                counters["bez_rozstrzygniecia"] += 1
                continue

            enr = event.get("enrichment") or {}
            odds = _safe_float(event.get("current_odds"))
            picks.append({
                "date": file_date,
                "sport": event.get("sport") or "?",
                "league": event.get("league") or "",
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "side": side,
                "winner": winner,
                "hit": side == winner,
                "odds": odds,
                "drop_pct": _safe_float(event.get("drop_pct")),
                "status": event.get("enrichment_status") or "brak",
                "has_form": bool(enr.get("home_form") or enr.get("home_form_overall")),
                "has_venue": bool(enr.get("home_form_home") or enr.get("away_form_away")),
                "has_h2h": bool(enr.get("h2h_last5")),
                "score": f"{result.get('score_home')}:{result.get('score_away')}",
            })
            counters["rozstrzygnietych"] += 1

    return picks, settler, dict(counters)


# ---------------------------------------------------------------------------
# Raport
# ---------------------------------------------------------------------------


def _summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0, "hits": 0, "hit_rate": 0.0, "avg_odds": 0.0,
                "roi_pct": 0.0, "break_even_pct": 0.0}
    hits = sum(1 for r in rows if r["hit"])
    staked = float(n)
    payout = sum(r["odds"] for r in rows if r["hit"])
    avg_odds = sum(r["odds"] for r in rows) / n
    return {
        "n": n,
        "hits": hits,
        "hit_rate": round(hits / n * 100, 1),
        "avg_odds": round(avg_odds, 2),
        "roi_pct": round((payout - staked) / staked * 100, 1),
        "break_even_pct": round(100 / avg_odds, 1) if avg_odds else 0.0,
    }


def _drop_bucket(r: Dict[str, Any]) -> str:
    d = r["drop_pct"]
    if d < 15:
        return "1) <15%"
    if d < 25:
        return "2) 15-25%"
    if d < 35:
        return "3) 25-35%"
    if d < 50:
        return "4) 35-50%"
    return "5) >=50%"


def _odds_bucket(r: Dict[str, Any]) -> str:
    o = r["odds"]
    if o < 1.6:
        return "1) <1.60"
    if o < 1.9:
        return "2) 1.60-1.90"
    if o < 2.2:
        return "3) 1.90-2.20"
    if o < 2.6:
        return "4) 2.20-2.60"
    return "5) >=2.60"


SEGMENTS = (
    ("sport", lambda r: r["sport"]),
    ("strona", lambda r: r["side"]),
    ("glebokosc spadku", _drop_bucket),
    ("kurs", _odds_bucket),
    ("zrodlo wzbogacenia", lambda r: r["status"]),
    ("kompletnosc danych", lambda r: (
        "forma+venue+H2H" if (r["has_form"] and r["has_venue"] and r["has_h2h"])
        else "forma+venue" if (r["has_form"] and r["has_venue"])
        else "tylko forma" if r["has_form"]
        else "brak danych"
    )),
)


def build_report(
    picks: List[Dict[str, Any]],
    counters: Dict[str, int],
    min_sample: int,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overall": _summarize(picks),
        "counters": counters,
        "segments": {},
        "min_sample": min_sample,
    }
    if picks:
        dates = sorted(r["date"] for r in picks if r["date"])
        if dates:
            report["date_range"] = {"from": dates[0], "to": dates[-1]}

    for label, keyfn in SEGMENTS:
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in picks:
            groups[str(keyfn(r))].append(r)
        report["segments"][label] = {
            k: _summarize(v) for k, v in sorted(groups.items())
        }
    return report


def print_report(report: Dict[str, Any], min_sample: int) -> None:
    o = report["overall"]
    rng = report.get("date_range") or {}
    print("=" * 74)
    print("SKUTECZNOSC DROPPING ODDS (OddsSafari)")
    if rng:
        print(f"Zakres dat: {rng.get('from')} .. {rng.get('to')}")
    print("=" * 74)

    if not o["n"]:
        print("Brak rozstrzygnietych typow do oceny.")
        c = report.get("counters") or {}
        if c:
            print("\nLicznik:")
            for k, v in sorted(c.items()):
                print(f"  {k:<24} {v}")
        return

    print(f"Typow rozstrzygnietych : {o['n']}")
    print(f"Trafionych             : {o['hits']}  ({o['hit_rate']}%)")
    print(f"Sredni kurs            : {o['avg_odds']}")
    print(f"Prog oplacalnosci      : {o['break_even_pct']}%")
    print(f"ROI (1 jedn./typ)      : {o['roi_pct']:+}%")
    verdict = "NA PLUSIE" if o["roi_pct"] > 0 else "NA MINUSIE"
    print(f"Werdykt                : {verdict}")

    for label, seg in report["segments"].items():
        print(f"\n--- {label.upper()} ---")
        hdr = f"{'grupa':<24}{'N':>5}{'traf.':>7}{'trafnosc':>10}{'kurs':>7}{'ROI':>9}"
        print(hdr)
        print("-" * len(hdr))
        for name, s in sorted(seg.items(), key=lambda kv: -kv[1]["n"]):
            mark = "" if s["n"] >= min_sample else "  (mala proba)"
            print(f"{name:<24}{s['n']:>5}{s['hits']:>7}{s['hit_rate']:>9}%"
                  f"{s['avg_odds']:>7}{s['roi_pct']:>8}%{mark}")

    c = report.get("counters") or {}
    if c:
        print("\n--- DOPASOWANIE DANYCH ---")
        for k, v in sorted(c.items()):
            print(f"  {k:<24} {v}")

    print("\nUwaga: ROI liczone po kursie z momentu scrapowania, wiec jest")
    print("gornym oszacowaniem. Grupy oznaczone '(mala proba)' maja ponizej")
    print(f"{min_sample} typow i nie sa istotne statystycznie.")


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Liczy trafnosc i ROI typow dropping odds z OddsSafari."
    )
    p.add_argument("--days", type=int, default=None,
                   help="Ogranicz do ostatnich N dni (domyslnie cale archiwum).")
    p.add_argument("--sport", default=None, help="Tylko jeden sport.")
    p.add_argument("--all-events", action="store_true",
                   help="Licz takze zdarzenia niekwalifikujace sie.")
    p.add_argument("--settle", action="store_true",
                   help="Dociagnij brakujace wyniki z SofaScore API (siec).")
    p.add_argument("--min-sample", type=int, default=20,
                   help="Prog, ponizej ktorego segment jest oznaczany jako mala proba.")
    p.add_argument("--output", default=None,
                   help="Sciezka raportu JSON (domyslnie outputs/dropping_odds_accuracy.json).")
    p.add_argument("--fail-on-empty", action="store_true",
                   help="Zwroc kod 1, gdy nie ma zadnych rozstrzygnietych typow.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    picks, settler, counters = collect_picks(
        days=args.days,
        sport=args.sport,
        qualified_only=not args.all_events,
        settle_via_api=args.settle,
    )
    for k, v in settler.stats.items():
        counters[k] = v

    report = build_report(picks, counters, args.min_sample)
    print_report(report, args.min_sample)

    if args.settle:
        settler.save_cache()
        if settler.api_calls:
            print(f"\nZapytan do SofaScore API: {settler.api_calls}")

    out_path = args.output or os.path.join(OUTPUTS_DIR, "dropping_odds_accuracy.json")
    try:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nRaport zapisany: {out_path}")
    except OSError as exc:
        print(f"âš ď¸Ź Nie udalo sie zapisac raportu: {exc}")

    if args.fail_on_empty and not report["overall"]["n"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
