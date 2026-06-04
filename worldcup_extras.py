"""
🏆 World Cup Extras — głęboka analiza pochodna + Kelly + value
==============================================================
Skoro meczów MŚ jest niewiele, analizujemy KAŻDY maksymalnie głęboko.
Ten moduł wyciska komplet wniosków z rynków Pinnacle (zwłaszcza CORRECT_SCORE)
oraz dokłada elementy, których wcześniej nie było:

  • goal_model     — pełny rozkład wyników → xG (home/away/total), P(1X2),
                     P(BTTS), P(clean sheet), P(Over/Under dowolnej linii)
  • who_scores_first — 1 / Nikt / 2 (z modelu goli)
  • kelly          — kryterium Kelly'ego + EV + value coefficient na 1X2
  • derived_totals — prawdopodobieństwa Over/Under dla 0.5–4.5 z rozkładu

Wszystko deterministyczne i policzalne offline z danych, które już pobieramy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Goal model z rynku CORRECT_SCORE
# --------------------------------------------------------------------------- #
def _parse_score(score: str) -> Optional[Tuple[int, int]]:
    """'3:1' -> (3, 1). Obsługuje też '3-1'."""
    if not score:
        return None
    sep = ":" if ":" in score else ("-" if "-" in score else None)
    if not sep:
        return None
    try:
        h, a = score.split(sep)
        return int(h.strip()), int(a.strip())
    except (ValueError, AttributeError):
        return None


def derive_goal_model(correct_score_market: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Buduje rozkład prawdopodobieństwa wyników z kursów Pinnacle CORRECT_SCORE
    i wylicza z niego komplet metryk pochodnych.
    """
    if not correct_score_market:
        return None
    items = correct_score_market.get("items") or []
    dist: List[Tuple[int, int, float]] = []
    inv_sum = 0.0
    for it in items:
        parsed = _parse_score(it.get("score", ""))
        odd = it.get("value")
        if not parsed or not odd or odd <= 1.0:
            continue
        inv = 1.0 / odd
        dist.append((parsed[0], parsed[1], inv))
        inv_sum += inv
    if not dist or inv_sum <= 0:
        return None

    # Normalizacja (usunięcie marży) → realny rozkład P(h,a)
    norm = [(h, a, inv / inv_sum) for (h, a, inv) in dist]

    exp_home = sum(h * p for h, a, p in norm)
    exp_away = sum(a * p for h, a, p in norm)
    p_home = sum(p for h, a, p in norm if h > a)
    p_draw = sum(p for h, a, p in norm if h == a)
    p_away = sum(p for h, a, p in norm if h < a)
    p_btts = sum(p for h, a, p in norm if h >= 1 and a >= 1)
    p_cs_home = sum(p for h, a, p in norm if a == 0)   # gospodarz czyste konto
    p_cs_away = sum(p for h, a, p in norm if h == 0)
    p_no_goals = sum(p for h, a, p in norm if h == 0 and a == 0)

    # Over/Under dla typowych linii (z rozkładu)
    derived_totals = {}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        over = sum(p for h, a, p in norm if (h + a) > line)
        derived_totals[str(line)] = {
            "over": round(over * 100, 1),
            "under": round((1 - over) * 100, 1),
        }

    # Kto strzeli pierwszy — przybliżenie z udziału w oczekiwanych golach,
    # przeskalowane przez P(padnie jakikolwiek gol).
    total_xg = exp_home + exp_away
    p_any_goal = 1 - p_no_goals
    if total_xg > 0:
        share_home = exp_home / total_xg
        first_home = round(share_home * p_any_goal * 100, 1)
        first_away = round((1 - share_home) * p_any_goal * 100, 1)
    else:
        first_home = first_away = 0.0
    first_none = round(p_no_goals * 100, 1)

    return {
        "expected_goals": {
            "home": round(exp_home, 2),
            "away": round(exp_away, 2),
            "total": round(exp_home + exp_away, 2),
        },
        "outcome_prob": {
            "home": round(p_home * 100, 1),
            "draw": round(p_draw * 100, 1),
            "away": round(p_away * 100, 1),
        },
        "btts_prob": round(p_btts * 100, 1),
        "clean_sheet": {
            "home": round(p_cs_home * 100, 1),
            "away": round(p_cs_away * 100, 1),
        },
        "who_scores_first": {
            "home": first_home,
            "none": first_none,
            "away": first_away,
            "pick": _argmax3(first_home, first_none, first_away,
                             ("1 (gospodarz)", "Nikt", "2 (gość)")),
        },
        "derived_totals": derived_totals,
        "scorelines_used": len(norm),
    }


def _argmax3(a: float, b: float, c: float, labels: Tuple[str, str, str]) -> str:
    vals = [a, b, c]
    return labels[vals.index(max(vals))]


# --------------------------------------------------------------------------- #
# Kelly Criterion + value coefficient (1X2)
# --------------------------------------------------------------------------- #
def compute_kelly(match_winner: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Liczy kryterium Kelly'ego, EV i 'value coefficient' dla każdej opcji 1X2.
    Używa fair-prob Pinnacle (bez marży) jako p oraz kursu jako wypłaty.
    """
    if not match_winner:
        return None
    fair = match_winner.get("fair_prob") or {}
    odds = match_winner.get("odds") or {}
    out: Dict[str, Any] = {}
    best = None
    for side in ("home", "draw", "away"):
        odd = odds.get(side)
        p = fair.get(side)
        if not odd or p is None or odd <= 1.0:
            continue
        p_frac = p / 100.0
        b = odd - 1.0
        q = 1.0 - p_frac
        kelly = (b * p_frac - q) / b if b > 0 else 0.0
        ev = round(p_frac * odd - 1.0, 3)               # EV na 1 jednostkę stawki
        value_coef = round(p_frac * odd, 3)             # >1 = value (jak "Coef. Score")
        entry = {
            "odds": odd,
            "fair_prob": p,
            "kelly_fraction": round(max(kelly, 0.0), 4),  # 0 gdy brak value
            "kelly_full": round(kelly, 4),
            "ev": ev,
            "value_coefficient": value_coef,
            "is_value": value_coef > 1.0,
        }
        out[side] = entry
        if entry["is_value"] and (best is None or entry["value_coefficient"] > best[1]):
            best = (side, entry["value_coefficient"])
    if not out:
        return None
    out["best_value"] = best[0] if best else None
    # Rekomendowana stawka = ułamkowy Kelly (1/4) najlepszej opcji value
    if best:
        out["recommended_stake_pct"] = round(out[best[0]]["kelly_fraction"] * 25, 2)
    return out


# --------------------------------------------------------------------------- #
# Main enrichment entry
# --------------------------------------------------------------------------- #
def enrich_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wzbogaca słownik analizy (z worldcup_analyzer.analyze_match) o nowe sekcje:
    goal_model, kelly, who_scores_first. Modyfikuje i zwraca ten sam dict.
    """
    cs = (analysis.get("correct_score") or {})
    # correct_score w analizie ma tylko top5 — potrzebujemy pełnej listy,
    # więc goal_model bazuje na surowym rynku jeśli przekazany w analysis['_raw_cs'].
    raw_cs = analysis.get("_raw_correct_score")
    goal_model = derive_goal_model(raw_cs) if raw_cs else None

    kelly = compute_kelly(analysis.get("match_winner"))

    analysis["goal_model"] = goal_model
    analysis["kelly"] = kelly
    if goal_model:
        analysis["who_scores_first"] = goal_model["who_scores_first"]
    # sprzątanie pola pomocniczego
    analysis.pop("_raw_correct_score", None)
    return analysis
