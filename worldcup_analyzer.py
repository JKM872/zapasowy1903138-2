"""
🏆 World Cup Analyzer
=====================
Warstwa analityczna budująca SZEROKI pakiet wniosków z pełnych rynków
Pinnacle (`pinnacle_full_odds.PinnacleFullOdds`). Dla każdego meczu liczy:

  • Fair (bez marży) prawdopodobieństwa 1X2 oraz pewny typ
  • Główny rynek totali (Over/Under) + rekomendacja
  • BTTS (obie strzelą) z fair probability
  • Najbardziej prawdopodobny dokładny wynik + top 5 scoreline'ów
  • Handicap azjatycki (linia główna)
  • Sygnały ruchu linii / "ostrych pieniędzy" (opening → current)
  • Tagi value-bet, gdy kurs odbiega od konsensusu rynku
  • Tekstowy werdykt analityczny (PL) dla użytkownika

Pinnacle ma najniższą marżę na rynku, więc po usunięciu vigu jego kursy są
najlepszym dostępnym estymatorem prawdziwego prawdopodobieństwa — całość
analizy jest "Pinnacle-first".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _pct(x: Optional[float]) -> str:
    return f"{x:.0f}%" if isinstance(x, (int, float)) else "—"


def _odd(item: Optional[Dict[str, Any]]) -> Optional[float]:
    return item.get("value") if isinstance(item, dict) else None


def _movement_note(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """Opisuje ruch kursu dla pojedynczej pozycji."""
    if not isinstance(item, dict):
        return None
    mv = item.get("movement")
    op, cur = item.get("opening"), item.get("value")
    if not mv or op is None or cur is None or op == cur:
        return None
    direction = "↑ w górę" if mv == "UP" else "↓ w dół"
    return f"{op} → {cur} ({direction})"


# --------------------------------------------------------------------------- #
# Sub-analyses
# --------------------------------------------------------------------------- #
def _analyze_1x2(market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not market:
        return None
    fair = market.get("fair_prob") or {}
    probs = {k: v for k, v in fair.items() if v is not None}
    if not probs:
        return None
    pick_key = max(probs, key=lambda k: probs[k])
    label = {"home": "1 (gospodarz)", "draw": "X (remis)", "away": "2 (gość)"}[pick_key]
    return {
        "fair_prob": fair,
        "vig": market.get("vig"),
        "pick": pick_key,
        "pick_label": label,
        "pick_prob": probs[pick_key],
        "odds": {
            "home": _odd(market.get("home")),
            "draw": _odd(market.get("draw")),
            "away": _odd(market.get("away")),
        },
        "movement": {
            "home": _movement_note(market.get("home")),
            "draw": _movement_note(market.get("draw")),
            "away": _movement_note(market.get("away")),
        },
    }


def _analyze_totals(market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not market:
        return None
    main = market.get("main_line")
    main_row = next((ln for ln in market.get("lines", []) if ln["line"] == main), None)
    if not main_row:
        return None
    fp = main_row.get("fair_prob") or {}
    over_p, under_p = fp.get("over"), fp.get("under")
    rec = None
    if over_p is not None and under_p is not None:
        rec = f"Over {main}" if over_p >= under_p else f"Under {main}"
    return {
        "main_line": main,
        "over_odds": _odd(main_row.get("over")),
        "under_odds": _odd(main_row.get("under")),
        "fair_prob": fp,
        "recommendation": rec,
        "all_lines": [ln["line"] for ln in market.get("lines", [])],
    }


def _analyze_btts(market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not market:
        return None
    fp = market.get("fair_prob") or {}
    yes_p, no_p = fp.get("yes"), fp.get("no")
    rec = None
    if yes_p is not None and no_p is not None:
        rec = "BTTS: Tak" if yes_p >= no_p else "BTTS: Nie"
    return {
        "yes_odds": _odd(market.get("yes")),
        "no_odds": _odd(market.get("no")),
        "fair_prob": fp,
        "recommendation": rec,
    }


def _analyze_correct_score(market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not market:
        return None
    items = market.get("items") or []
    top = items[:5]
    return {
        "most_likely": market.get("most_likely"),
        "top5": [{"score": it["score"], "odds": it["value"],
                  "prob": round(100.0 / it["value"], 1) if it["value"] else None}
                 for it in top],
    }


def _analyze_asian_handicap(market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not market:
        return None
    lines = market.get("lines") or []
    # główna linia AH = ta najbliżej zbalansowania kursów home/away
    best, best_gap = None, None
    for ln in lines:
        h, a = _odd(ln.get("home")), _odd(ln.get("away"))
        if h is None or a is None:
            continue
        gap = abs(h - a)
        if best_gap is None or gap < best_gap:
            best_gap, best = gap, ln
    if not best:
        return None
    return {
        "main_line": best["line"],
        "home_odds": _odd(best.get("home")),
        "away_odds": _odd(best.get("away")),
        "fair_prob": best.get("fair_prob"),
        "all_lines": [ln["line"] for ln in lines],
    }


# --------------------------------------------------------------------------- #
# Sharp-money / line-movement detector
# --------------------------------------------------------------------------- #
def _detect_signals(odds_pkg: Dict[str, Any]) -> List[str]:
    """Sygnały ruchu linii — gdzie 'ostre pieniądze' przesuwają kurs."""
    signals: List[str] = []
    markets = odds_pkg.get("markets", {})

    x2 = markets.get("HOME_DRAW_AWAY")
    if x2:
        for side, name in (("home", "gospodarza"), ("away", "gościa"), ("draw", "remis")):
            item = x2.get(side)
            if isinstance(item, dict) and item.get("drift") is not None:
                drift = item["drift"]
                # spadek kursu o >=8% względem otwarcia = pieniądze na tę opcję
                if item.get("opening") and drift <= -0.08 * item["opening"]:
                    signals.append(
                        f"Kurs na {name} spadł {item['opening']}→{item['value']} "
                        f"— rynek ładuje tę opcję (sharp money)")
                elif item.get("opening") and drift >= 0.12 * item["opening"]:
                    signals.append(
                        f"Kurs na {name} wzrósł {item['opening']}→{item['value']} "
                        f"— rynek odpływa od tej opcji")

    ou = markets.get("OVER_UNDER")
    if ou:
        main = ou.get("main_line")
        row = next((ln for ln in ou.get("lines", []) if ln["line"] == main), None)
        if row:
            ov = row.get("over") or {}
            if ov.get("drift") is not None and ov.get("opening") and ov["drift"] <= -0.1 * ov["opening"]:
                signals.append(f"Kurs Over {main} spadł — rynek oczekuje goli")
    return signals


# --------------------------------------------------------------------------- #
# Value-bet vs other sources (forebet / sofascore / ai)
# --------------------------------------------------------------------------- #
def _detect_value(x2: Optional[Dict[str, Any]], match_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Porównuje fair-prob Pinnacle z innymi źródłami i szuka edge'u."""
    out: List[Dict[str, Any]] = []
    if not x2:
        return out
    fair = x2.get("fair_prob") or {}
    odds = x2.get("odds") or {}

    # Edge = nasze prawdopodobieństwo (źródło) > implikowane fair Pinnacle
    sources = {
        "Forebet": match_row.get("forebet_probability"),
    }
    # SofaScore fan vote
    ss_home = match_row.get("sofascore_home_win_prob")
    if ss_home is not None:
        sources["SofaScore(dom)"] = ss_home

    for side in ("home", "draw", "away"):
        odd = odds.get(side)
        fair_p = fair.get(side)
        if not odd or fair_p is None:
            continue
        # value, gdy kurs > fair (czyli implikowane < fair) — czyli płacą więcej niż ryzyko
        implied = 100.0 / odd
        edge = round(fair_p - implied, 1)
        if edge >= 4.0:  # min 4 p.p. przewagi
            out.append({
                "market": "1X2",
                "selection": side,
                "odds": odd,
                "fair_prob": fair_p,
                "implied_prob": round(implied, 1),
                "edge": edge,
            })
    return out


# --------------------------------------------------------------------------- #
# Verdict builder
# --------------------------------------------------------------------------- #
def _build_verdict(analysis: Dict[str, Any], home: str, away: str) -> str:
    parts: List[str] = []
    x2 = analysis.get("match_winner")
    if x2:
        parts.append(
            f"Pinnacle (bez marży) faworyzuje {x2['pick_label']} "
            f"~{_pct(x2['pick_prob'])}.")
    tot = analysis.get("totals")
    if tot and tot.get("recommendation"):
        parts.append(f"Linia goli: {tot['recommendation']}.")
    btts = analysis.get("btts")
    if btts and btts.get("recommendation"):
        parts.append(btts["recommendation"] + ".")
    cs = analysis.get("correct_score")
    if cs and cs.get("most_likely"):
        parts.append(f"Najprawdopodobniejszy wynik: {cs['most_likely']}.")
    gm = analysis.get("goal_model")
    if gm:
        xg = gm.get("expected_goals", {})
        if xg.get("total") is not None:
            parts.append(f"Model goli: ~{xg['total']} gola ({xg.get('home')}–{xg.get('away')}).")
        wsf = gm.get("who_scores_first")
        if wsf and wsf.get("pick"):
            parts.append(f"Pierwszy gol: {wsf['pick']}.")
    kelly = analysis.get("kelly")
    if kelly and kelly.get("best_value"):
        bv = kelly["best_value"]
        side_lbl = {"home": home, "draw": "remis", "away": away}.get(bv, bv)
        coef = (kelly.get(bv) or {}).get("value_coefficient")
        parts.append(f"Kelly value: {side_lbl} (coef {coef}).")
    sig = analysis.get("signals") or []
    if sig:
        parts.append("Sygnał rynku: " + sig[0] + ".")
    val = analysis.get("value_bets") or []
    if val:
        v = val[0]
        side_lbl = {"home": home, "draw": "remis", "away": away}.get(v["selection"], v["selection"])
        parts.append(f"Potencjalny value: {side_lbl} @ {v['odds']} (edge +{v['edge']} p.p.).")
    if not parts:
        return "Brak wystarczających danych rynkowych Pinnacle dla tego meczu."
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def analyze_match(odds_pkg: Dict[str, Any], match_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Buduje pełny pakiet analityczny z surowego pakietu rynków Pinnacle.

    Args:
        odds_pkg: wynik PinnacleFullOdds.get_full_odds_for_match()
        match_row: opcjonalne dane meczu (forebet/sofascore/teams) do value-betów

    Returns:
        Dict z analizą gotową do serializacji JSON / wyświetlenia.
    """
    match_row = match_row or {}
    markets = odds_pkg.get("markets", {})

    match_winner = _analyze_1x2(markets.get("HOME_DRAW_AWAY"))
    totals = _analyze_totals(markets.get("OVER_UNDER"))
    btts = _analyze_btts(markets.get("BOTH_TEAMS_TO_SCORE"))
    correct_score = _analyze_correct_score(markets.get("CORRECT_SCORE"))
    asian_handicap = _analyze_asian_handicap(markets.get("ASIAN_HANDICAP"))
    double_chance = markets.get("DOUBLE_CHANCE")
    signals = _detect_signals(odds_pkg)
    value_bets = _detect_value(match_winner, match_row)

    analysis = {
        "bookmaker": "Pinnacle",
        "markets_available": odds_pkg.get("markets_available", []),
        "markets_count": len(odds_pkg.get("markets_available", [])),
        "match_winner": match_winner,
        "double_chance": _simplify_dc(double_chance),
        "totals": totals,
        "btts": btts,
        "asian_handicap": asian_handicap,
        "correct_score": correct_score,
        "signals": signals,
        "value_bets": value_bets,
        # przekazujemy surowy rynek do modułu pochodnych (usuwany po wzbogaceniu)
        "_raw_correct_score": markets.get("CORRECT_SCORE"),
    }

    # 🏆 Głęboka analiza pochodna: model goli, Kelly, kto strzeli pierwszy
    try:
        from worldcup_extras import enrich_analysis
        enrich_analysis(analysis)
    except Exception as e:  # noqa: BLE001 - best effort
        analysis.pop("_raw_correct_score", None)
        analysis.setdefault("goal_model", None)
        analysis.setdefault("kelly", None)

    home = match_row.get("home_team", "gospodarz")
    away = match_row.get("away_team", "gość")
    analysis["verdict"] = _build_verdict(analysis, home, away)
    return analysis


def _simplify_dc(dc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not dc:
        return None
    return {
        "homeOrDraw": _odd(dc.get("homeOrDraw")),
        "awayOrDraw": _odd(dc.get("awayOrDraw")),
        "homeOrAway": _odd(dc.get("homeOrAway")),
    }
