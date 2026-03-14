"""
AI Prediction Engine — Ultra PRO match analysis layer
------------------------------------------------------
Sits on top of existing scoring engines and data sources.
Produces a comprehensive, explainable AI prediction for each match:
  - Composite prediction with calibrated confidence
  - Consensus strength across all sources
  - Risk profile (conflicts, data quality warnings)
  - Factor-by-factor contribution breakdown
  - Professional English verdict and key arguments

Usage:
    from ai_prediction_engine import generate_ai_prediction
    analysis = generate_ai_prediction(match_row)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, cast


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONFIDENCE_TIERS = [
    (85, "VERY HIGH"),
    (70, "HIGH"),
    (55, "MEDIUM"),
    (40, "LOW"),
    (0, "VERY LOW"),
]

_RISK_THRESHOLDS = {
    "low": 3,
    "medium": 5,
    "high": 7,
}


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class AIPrediction:
    """Complete Ultra PRO AI analysis for a single match."""

    # Composite verdict
    pick: str                          # '1', 'X', '2' or 'A', 'B'
    pick_label: str                    # 'Home Win', 'Draw', 'Away Win', 'Player A', etc.
    composite_confidence: float        # 0-100, calibrated
    confidence_tier: str               # VERY HIGH / HIGH / MEDIUM / LOW / VERY LOW

    # Probability distribution
    prob_home: float                   # 0-100
    prob_draw: float                   # 0-100 (0 for tennis)
    prob_away: float                   # 0-100

    # Consensus
    consensus_sources: int             # how many sources agree (0-5)
    consensus_total: int               # total sources available
    consensus_strength: str            # "STRONG" / "MODERATE" / "WEAK" / "DIVIDED"
    source_predictions: Dict[str, str] # {source: pick} e.g. {'forebet': '1', 'scoring': '1'}

    # Value metrics
    ev: float                          # expected value
    edge: float                        # our prob − implied prob (%)
    value_rating: str                  # "EXCELLENT" / "GOOD" / "FAIR" / "NONE"

    # Risk profile
    risk_score: int                    # 0-10
    risk_level: str                    # "LOW" / "MEDIUM" / "HIGH"
    risk_flags: List[str]              # human-readable warning strings

    # Factor breakdown (contribution to final prediction)
    factors: List[Dict[str, Any]]      # [{name, value, weight, impact, quality, description}]

    # Data quality
    data_quality: float                # 0-1
    data_quality_label: str            # "EXCELLENT" / "GOOD" / "FAIR" / "POOR"
    available_sources: List[str]       # which sources had data
    missing_sources: List[str]         # which sources lacked data

    # Key arguments (top drivers + counter-arguments)
    key_arguments_for: List[str]       # top 3 reasons supporting the pick
    key_arguments_against: List[str]   # top 2 reasons against

    # Professional verdict  (English)
    verdict: str                       # 2-3 sentence professional summary
    short_verdict: str                 # 1 sentence for card view

    # Do-not-bet reasons (if any)
    do_not_bet_reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'pick': self.pick,
            'pickLabel': self.pick_label,
            'compositeConfidence': round(self.composite_confidence, 1),
            'confidenceTier': self.confidence_tier,
            'probHome': round(self.prob_home, 1),
            'probDraw': round(self.prob_draw, 1),
            'probAway': round(self.prob_away, 1),
            'consensus': {
                'sources': self.consensus_sources,
                'total': self.consensus_total,
                'strength': self.consensus_strength,
                'predictions': self.source_predictions,
            },
            'ev': round(self.ev, 3),
            'edge': round(self.edge, 1),
            'valueRating': self.value_rating,
            'risk': {
                'score': self.risk_score,
                'level': self.risk_level,
                'flags': self.risk_flags,
            },
            'factors': self.factors,
            'dataQuality': round(self.data_quality, 2),
            'dataQualityLabel': self.data_quality_label,
            'availableSources': self.available_sources,
            'missingSources': self.missing_sources,
            'keyArgumentsFor': self.key_arguments_for,
            'keyArgumentsAgainst': self.key_arguments_against,
            'verdict': self.verdict,
            'shortVerdict': self.short_verdict,
            'doNotBetReasons': self.do_not_bet_reasons,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sf(val: Any, default: float = 0.0) -> float:
    """Safe float conversion with NaN handling."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return default


def _pick_label(pick: str, sport: str) -> str:
    if sport == 'tennis':
        return 'Player A' if pick == 'A' else 'Player B'
    return {'1': 'Home Win', 'X': 'Draw', '2': 'Away Win'}.get(pick, pick)


def _confidence_tier(conf: float) -> str:
    for threshold, label in _CONFIDENCE_TIERS:
        if conf >= threshold:
            return label
    return "VERY LOW"


def _consensus_label(agree: int, total: int) -> str:
    if total == 0:
        return "UNKNOWN"
    ratio = agree / total
    if ratio >= 0.8:
        return "STRONG"
    if ratio >= 0.6:
        return "MODERATE"
    if ratio >= 0.4:
        return "WEAK"
    return "DIVIDED"


def _value_label(ev: float, edge: float) -> str:
    if ev >= 0.15 and edge >= 10:
        return "EXCELLENT"
    if ev >= 0.05 and edge >= 5:
        return "GOOD"
    if ev > 0:
        return "FAIR"
    return "NONE"


def _dq_label(dq: float) -> str:
    if dq >= 0.8:
        return "EXCELLENT"
    if dq >= 0.6:
        return "GOOD"
    if dq >= 0.4:
        return "FAIR"
    return "POOR"


def _normalize_form(raw: Any) -> list[str]:
    """Convert form data from any format (CSV string, list, etc.) to a clean list of W/D/L."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip().upper() for x in cast(list[Any], raw) if x and str(x).strip().upper() in ('W', 'D', 'L')]
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s.lower() in ('nan', 'none', 'n/a'):
            return []
        # "['W', 'L', 'D']" — stringified list
        if s.startswith('[') and s.endswith(']'):
            try:
                import ast
                parsed = ast.literal_eval(s)
                if isinstance(parsed, list):
                    return [str(x).strip().upper() for x in cast(list[Any], parsed) if x and str(x).strip().upper() in ('W', 'D', 'L')]
            except (ValueError, SyntaxError):
                pass
        # "W-L-D" or "W,L,D"
        for sep in ['-', ',', ' ', ';']:
            if sep in s:
                parts = [x.strip().upper() for x in s.split(sep) if x.strip()]
                if parts and all(p in ('W', 'D', 'L') for p in parts):
                    return parts
        # "WLDWD" — single chars
        if all(c.upper() in 'WLD' for c in s if c.strip()):
            return [c.upper() for c in s if c.upper() in 'WLD']
    return []


def _form_trend(form_list: Any) -> Tuple[float, str]:
    """Compute form trend from W/D/L list. Returns (score -1..+1, label)."""
    if not form_list or not isinstance(form_list, (list, tuple)):
        return 0.0, "Unknown"
    items: list[str] = [str(x) for x in cast(list[Any], form_list)]
    pts: list[float] = []
    for r_str in items:
        r_str = r_str.upper().strip()
        if r_str == 'W':
            pts.append(1.0)
        elif r_str == 'D':
            pts.append(0.4)
        else:
            pts.append(0.0)
    if len(pts) < 2:
        return 0.0, "Insufficient data"
    recent = pts[:3] if len(pts) >= 3 else pts
    older = pts[3:] if len(pts) > 3 else pts
    avg_recent = sum(recent) / len(recent)
    avg_older = sum(older) / len(older) if older else avg_recent
    trend = avg_recent - avg_older
    if trend > 0.2:
        return trend, "Improving"
    if trend < -0.2:
        return trend, "Declining"
    return trend, "Stable"


def _form_score(form_list: Any) -> float:
    """Overall form quality 0-1."""
    if not form_list or not isinstance(form_list, (list, tuple)):
        return 0.5
    items: list[str] = [str(x) for x in cast(list[Any], form_list)]
    pts: list[float] = []
    weights: list[float] = []
    for i, r_str in enumerate(items):
        r_str = r_str.upper().strip()
        w = 1.0 / (1 + i * 0.2)  # recency weighting
        weights.append(w)
        if r_str == 'W':
            pts.append(1.0 * w)
        elif r_str == 'D':
            pts.append(0.4 * w)
        else:
            pts.append(0.0)
    return sum(pts) / sum(weights) if weights else 0.5


def _form_consistency(form_list: Any) -> float:
    """Form consistency 0-1 (1=very consistent, 0=volatile)."""
    if not form_list or not isinstance(form_list, (list, tuple)) or len(cast(list[Any], form_list)) < 2:
        return 0.5
    items: list[str] = [str(x) for x in cast(list[Any], form_list)]
    pts: list[float] = []
    for r_str in items:
        r_str = r_str.upper().strip()
        if r_str == 'W':
            pts.append(1.0)
        elif r_str == 'D':
            pts.append(0.5)
        else:
            pts.append(0.0)
    mean = sum(pts) / len(pts)
    variance = sum((p - mean) ** 2 for p in pts) / len(pts)
    return max(0.0, 1.0 - (variance ** 0.5) * 2)


# ---------------------------------------------------------------------------
# Source extraction helpers
# ---------------------------------------------------------------------------

def _extract_source_prediction(m: Dict[str, Any], sport: str) -> Dict[str, str]:
    """Extract per-source picks from match row."""
    preds: Dict[str, str] = {}

    # Forebet
    fp = m.get('forebet_prediction', '')
    if fp and str(fp) in ('1', 'X', '2'):
        preds['forebet'] = str(fp)

    # Scoring engine
    sp = m.get('scoring_pick', '')
    if sp:
        preds['scoring'] = str(sp)

    # Gemini
    gp = m.get('gemini_prediction', '')
    gr = m.get('gemini_recommendation', '')
    if gp:
        # Extract from prediction text (e.g. "Liverpool win" → '1')
        gp_stripped = str(gp).strip()
        if gr in ('HIGH', 'MEDIUM'):
            # Use focus_team to infer pick
            ft = m.get('focus_team', 'home')
            preds['gemini'] = '1' if ft == 'home' else '2'
        elif gp_stripped in ('1', 'X', '2', 'A', 'B'):
            preds['gemini'] = gp_stripped

    # SofaScore (fan vote majority)
    ss_h = _sf(m.get('sofascore_home_win_prob'))
    ss_d = _sf(m.get('sofascore_draw_prob'))
    ss_a = _sf(m.get('sofascore_away_win_prob'))
    if ss_h + ss_d + ss_a > 0:
        if sport == 'tennis':
            preds['sofascore'] = 'A' if ss_h >= ss_a else 'B'
        else:
            best = max(ss_h, ss_d, ss_a)
            if best == ss_h:
                preds['sofascore'] = '1'
            elif best == ss_d:
                preds['sofascore'] = 'X'
            else:
                preds['sofascore'] = '2'

    # H2H (majority from recent meetings)
    h2h_hw = _sf(m.get('home_wins_in_h2h_last5', m.get('livesport_h2h_home_wins', 0)))
    h2h_aw = _sf(m.get('away_wins_in_h2h_last5', m.get('livesport_h2h_away_wins', 0)))
    if h2h_hw + h2h_aw > 0:
        if sport == 'tennis':
            preds['h2h'] = 'A' if h2h_hw >= h2h_aw else 'B'
        else:
            preds['h2h'] = '1' if h2h_hw >= h2h_aw else '2'

    return preds


def _compute_consensus(source_preds: Dict[str, str], main_pick: str) -> Tuple[int, int]:
    """Count how many sources agree with main_pick."""
    total = len(source_preds)
    agree = sum(1 for v in source_preds.values() if v == main_pick)
    return agree, total


# ---------------------------------------------------------------------------
# Factor analysis
# ---------------------------------------------------------------------------

def _build_factors(m: Dict[str, Any], sport: str) -> List[Dict[str, Any]]:
    """Build factor-by-factor breakdown for explainability."""
    factors: List[Dict[str, Any]] = []

    # 1. H2H
    h2h_hw = _sf(m.get('home_wins_in_h2h_last5', m.get('livesport_h2h_home_wins', 0)))
    h2h_aw = _sf(m.get('away_wins_in_h2h_last5', m.get('livesport_h2h_away_wins', 0)))
    h2h_count = _sf(m.get('h2h_count', 0))
    h2h_wr = _sf(m.get('h2h_win_rate', m.get('livesport_win_rate', 0)))
    if h2h_wr > 1:
        h2h_wr = h2h_wr / 100.0
    h2h_quality = min(1.0, h2h_count / 5) if h2h_count else 0.0

    home = m.get('home_team', 'Home')
    away = m.get('away_team', 'Away')
    h2h_desc = f"{home} won {int(h2h_hw)} of last {int(h2h_count)} meetings ({away}: {int(h2h_aw)})" if h2h_count else "No H2H data"
    h2h_impact = "positive" if h2h_wr >= 0.6 else ("neutral" if h2h_wr >= 0.4 else "negative")
    factors.append({
        'name': 'Head-to-Head',
        'value': round(h2h_wr * 100, 1),
        'weight': 0.20 if sport != 'tennis' else 0.30,
        'impact': h2h_impact,
        'quality': round(h2h_quality, 2),
        'description': h2h_desc,
    })

    # 2. Form
    hf = _normalize_form(m.get('home_form', m.get('livesport_home_form', [])))
    af = _normalize_form(m.get('away_form', m.get('livesport_away_form', [])))
    hf_score = _form_score(hf)
    af_score = _form_score(af)
    _, hf_trend_label = _form_trend(hf)
    _, af_trend_label = _form_trend(af)
    hf_consistency = _form_consistency(hf)
    af_consistency = _form_consistency(af)
    form_diff = hf_score - af_score
    form_quality = 1.0 if (hf and af) else (0.5 if hf or af else 0.0)

    form_impact = "positive" if form_diff > 0.15 else ("neutral" if form_diff > -0.15 else "negative")
    form_desc_parts: list[str] = []
    if hf:
        form_desc_parts.append(f"{home}: {hf_trend_label} ({round(hf_score*100)}%)")
    if af:
        form_desc_parts.append(f"{away}: {af_trend_label} ({round(af_score*100)}%)")
    factors.append({
        'name': 'Recent Form',
        'value': round(form_diff * 100, 1),
        'weight': 0.15 if sport != 'tennis' else 0.25,
        'impact': form_impact,
        'quality': round(form_quality, 2),
        'description': ' | '.join(form_desc_parts) if form_desc_parts else 'No form data',
        'details': {
            'homeScore': round(hf_score, 3),
            'awayScore': round(af_score, 3),
            'homeTrend': hf_trend_label,
            'awayTrend': af_trend_label,
            'homeConsistency': round(hf_consistency, 2),
            'awayConsistency': round(af_consistency, 2),
        }
    })

    # 3. Venue Form (not tennis)
    if sport != 'tennis':
        hfh = _normalize_form(m.get('home_form_home', []))
        afa = _normalize_form(m.get('away_form_away', []))
        hfh_score = _form_score(hfh) if hfh else 0.5
        afa_score = _form_score(afa) if afa else 0.5
        venue_diff = hfh_score - afa_score
        venue_quality = 1.0 if (hfh and afa) else (0.5 if hfh or afa else 0.0)
        venue_impact = "positive" if venue_diff > 0.15 else ("neutral" if venue_diff > -0.15 else "negative")
        venue_desc = f"Home at home: {round(hfh_score*100)}% | Away on road: {round(afa_score*100)}%"
        factors.append({
            'name': 'Venue Form',
            'value': round(venue_diff * 100, 1),
            'weight': 0.10,
            'impact': venue_impact,
            'quality': round(venue_quality, 2),
            'description': venue_desc,
        })

    # 4. Odds (Market)
    ho = _sf(m.get('home_odds'))
    do_ = _sf(m.get('draw_odds'))
    ao = _sf(m.get('away_odds'))
    odds_quality = 1.0 if (ho > 1 and ao > 1) else 0.0
    if ho > 1 and ao > 1:
        total_inv = (1/ho) + (1/ao if ao > 1 else 0) + (1/do_ if do_ > 1 else 0)
        impl_h = (1/ho) / total_inv * 100 if total_inv else 0
        impl_a = (1/ao) / total_inv * 100 if total_inv else 0
        odds_impact = "positive" if impl_h >= 55 else ("neutral" if impl_h >= 40 else "negative")
        odds_desc = f"Market: {home} {impl_h:.0f}% | {away} {impl_a:.0f}% (odds {ho:.2f}/{ao:.2f})"
    else:
        impl_h = 50
        impl_a = 50
        odds_impact = "neutral"
        odds_desc = "No odds data available"
    factors.append({
        'name': 'Market Odds',
        'value': round(impl_h, 1),
        'weight': 0.20 if sport != 'tennis' else 0.10,
        'impact': odds_impact,
        'quality': round(odds_quality, 2),
        'description': odds_desc,
    })

    # 5. Forebet
    fb_prob = _sf(m.get('forebet_probability'))
    fb_pred = m.get('forebet_prediction', '')
    fb_quality = 1.0 if fb_prob > 0 else 0.0
    if fb_prob > 0:
        fb_impact = "positive" if fb_prob >= 60 else ("neutral" if fb_prob >= 45 else "negative")
        fb_desc = f"Forebet predicts {fb_pred} with {fb_prob:.0f}% confidence"
        exact = m.get('forebet_exact_score', '')
        if exact:
            fb_desc += f" (exact: {exact})"
    else:
        fb_impact = "neutral"
        fb_desc = "No Forebet prediction available"
    factors.append({
        'name': 'Forebet Analysis',
        'value': round(fb_prob, 1),
        'weight': 0.15,
        'impact': fb_impact,
        'quality': round(fb_quality, 2),
        'description': fb_desc,
    })

    # 6. SofaScore
    ss_h = _sf(m.get('sofascore_home_win_prob'))
    ss_d = _sf(m.get('sofascore_draw_prob'))
    ss_a = _sf(m.get('sofascore_away_win_prob'))
    ss_votes = _sf(m.get('sofascore_total_votes'))
    ss_quality = 1.0 if (ss_h + ss_a > 0) else 0.0
    if ss_h + ss_a > 0:
        ss_impact = "positive" if ss_h >= 55 else ("neutral" if ss_h >= 40 else "negative")
        ss_desc = f"Fans: {home} {ss_h:.0f}% | Draw {ss_d:.0f}% | {away} {ss_a:.0f}% ({int(ss_votes)} votes)"
    else:
        ss_impact = "neutral"
        ss_desc = "No SofaScore data"
    factors.append({
        'name': 'SofaScore Community',
        'value': round(ss_h, 1),
        'weight': 0.10,
        'impact': ss_impact,
        'quality': round(ss_quality, 2),
        'description': ss_desc,
    })

    # 7. Gemini AI
    gc = _sf(m.get('gemini_confidence'))
    gr = m.get('gemini_recommendation', '')
    gp = m.get('gemini_prediction', '')
    g_quality = 1.0 if gc > 0 else 0.0
    if gc > 0:
        g_impact = "positive" if gr in ('HIGH',) else ("neutral" if gr in ('MEDIUM',) else "negative")
        g_desc = f"Gemini: {gr} ({gc:.0f}%)"
        if gp:
            g_desc += f" — {gp[:80]}"
    else:
        g_impact = "neutral"
        g_desc = "No Gemini analysis available"
    factors.append({
        'name': 'Gemini AI',
        'value': round(gc, 1),
        'weight': 0.10,
        'impact': g_impact,
        'quality': round(g_quality, 2),
        'description': g_desc,
    })

    # 8. Surface (tennis only)
    if sport == 'tennis':
        surface = m.get('surface', '')
        rank_a = _sf(m.get('ranking_a', 0))
        rank_b = _sf(m.get('ranking_b', 0))
        if surface:
            rank_desc = f"Surface: {surface}"
            if rank_a and rank_b:
                rank_desc += f" | Rankings: #{int(rank_a)} vs #{int(rank_b)}"
            factors.append({
                'name': 'Surface & Rankings',
                'value': round(rank_a, 0),
                'weight': 0.20,
                'impact': 'positive' if rank_a < rank_b and rank_a > 0 else 'neutral',
                'quality': 1.0 if surface else 0.0,
                'description': rank_desc,
            })

    return factors


# ---------------------------------------------------------------------------
# Risk analysis
# ---------------------------------------------------------------------------

def _compute_risk(
    m: Dict[str, Any],
    source_preds: Dict[str, str],
    main_pick: str,
    data_quality: float,
    factors: List[Dict[str, Any]],
) -> Tuple[int, str, List[str]]:
    """Compute risk score 0-10 and human-readable flags."""
    risk = 0
    flags: List[str] = []

    # Conflict between sources
    agree, total = _compute_consensus(source_preds, main_pick)
    if total >= 2:
        conflict_ratio = 1.0 - (agree / total)
        if conflict_ratio >= 0.6:
            risk += 3
            conflicts = [f"{k}={v}" for k, v in source_preds.items() if v != main_pick]
            flags.append(f"Source conflict: {', '.join(conflicts)} disagree with pick {main_pick}")
        elif conflict_ratio >= 0.3:
            risk += 1
            flags.append("Some sources disagree on the predicted outcome")

    # Low data quality
    if data_quality < 0.4:
        risk += 3
        flags.append("Insufficient data — fewer than half of analysis sources available")
    elif data_quality < 0.6:
        risk += 1
        flags.append("Limited data coverage across sources")

    # Low H2H count
    h2h_count = _sf(m.get('h2h_count', 0))
    if h2h_count < 3:
        risk += 1
        flags.append(f"Only {int(h2h_count)} head-to-head matches on record")

    # Form inconsistency
    hf = m.get('home_form', [])
    af = m.get('away_form', [])
    if hf and _form_consistency(hf) < 0.4:
        risk += 1
        flags.append(f"Home team form is volatile — results vary widely")
    if af and _form_consistency(af) < 0.4:
        risk += 1
        flags.append(f"Away team form is volatile — results vary widely")

    # Narrow edge
    edge = _sf(m.get('scoring_edge', 0))
    if 0 < edge < 3:
        risk += 1
        flags.append(f"Narrow edge ({edge:.1f}%) — prediction margin is thin")

    # Close odds (implying uncertainty)
    ho = _sf(m.get('home_odds'))
    ao = _sf(m.get('away_odds'))
    if ho > 1 and ao > 1 and abs(ho - ao) < 0.3:
        risk += 1
        flags.append("Very close odds — market sees this as a toss-up")

    risk = min(10, risk)
    level = "HIGH" if risk >= _RISK_THRESHOLDS["high"] else ("MEDIUM" if risk >= _RISK_THRESHOLDS["medium"] else "LOW")
    return risk, level, flags


# ---------------------------------------------------------------------------
# Verdict generation
# ---------------------------------------------------------------------------

def _generate_verdict(
    m: Dict[str, Any],
    pick: str,
    pick_label: str,
    confidence: float,
    consensus_strength: str,
    risk_level: str,
    factors: List[Dict[str, Any]],
    ev: float,
    edge: float,
    sport: str,
) -> Tuple[str, str]:
    """Generate professional English verdict and short verdict."""
    home = m.get('home_team', 'Home')
    away = m.get('away_team', 'Away')

    # Identify top positive and negative factors
    positive = sorted(
        [f for f in factors if f['impact'] == 'positive' and f['quality'] > 0],
        key=lambda x: x['weight'], reverse=True,
    )
    negative = sorted(
        [f for f in factors if f['impact'] == 'negative' and f['quality'] > 0],
        key=lambda x: x['weight'], reverse=True,
    )

    # Short verdict
    parts: list[str] = []
    if confidence >= 75:
        short = f"Strong {pick_label.lower()} signal ({confidence:.0f}% confidence) backed by {consensus_strength.lower()} consensus."
    elif confidence >= 55:
        short = f"Moderate {pick_label.lower()} lean ({confidence:.0f}%) with {consensus_strength.lower()} source agreement."
    else:
        short = f"Low confidence {pick_label.lower()} suggestion ({confidence:.0f}%) — proceed with caution."

    # Long verdict
    if sport == 'tennis':
        parts.append(f"AI analysis favors {home if pick in ('1', 'A') else away} in this matchup.")
    else:
        if pick == '1':
            parts.append(f"AI analysis favors {home} (home win).")
        elif pick == '2':
            parts.append(f"AI analysis favors {away} (away win).")
        else:
            parts.append(f"AI analysis leans toward a draw.")

    # Key drivers
    if positive:
        top_names = [f['name'] for f in positive[:2]]
        parts.append(f"Key drivers: {', '.join(top_names)}.")

    # Risk caveat
    if risk_level == "HIGH":
        parts.append("However, risk level is elevated due to conflicting signals or limited data.")
    elif negative:
        counter = negative[0]['name']
        parts.append(f"Watch out: {counter} presents a counter-argument.")

    # Value
    if ev > 0.05:
        parts.append(f"Positive expected value ({ev:+.3f}) suggests potential market inefficiency.")
    elif ev <= 0:
        parts.append("No positive expected value detected at current odds.")

    verdict = ' '.join(parts)
    return verdict, short


# ---------------------------------------------------------------------------
# Key arguments
# ---------------------------------------------------------------------------

def _extract_arguments(
    factors: List[Dict[str, Any]],
    m: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    """Extract top arguments for and against the pick."""
    args_for: List[str] = []
    args_against: List[str] = []

    for f in factors:
        if f['quality'] <= 0:
            continue
        if f['impact'] == 'positive':
            args_for.append(f['description'])
        elif f['impact'] == 'negative':
            args_against.append(f['description'])

    # Limit
    return args_for[:4], args_against[:3]


# ---------------------------------------------------------------------------
# Do-not-bet guardrails
# ---------------------------------------------------------------------------

def _check_guardrails(
    confidence: float,
    data_quality: float,
    risk_score: int,
    risk_flags: List[str],
    consensus_sources: int,
    consensus_total: int,
) -> List[str]:
    """Return list of reasons to avoid betting. Empty = OK to proceed."""
    reasons: List[str] = []
    if data_quality < 0.3:
        reasons.append("Critically insufficient data — most analysis sources missing")
    if risk_score >= 8:
        reasons.append("Risk score extremely high — multiple warning flags triggered")
    if confidence < 35:
        reasons.append("Confidence too low for a reliable prediction")
    if consensus_total >= 3 and consensus_sources <= 1:
        reasons.append("Severe source disagreement — no meaningful consensus")
    return reasons


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_ai_prediction(match_row: Dict[str, Any]) -> AIPrediction:
    """
    Generate Ultra PRO AI prediction from a fully-enriched match row.

    The match_row should contain all fields from the pipeline
    (H2H, form, forebet, sofascore, gemini, scoring engine, odds).
    """
    sport = match_row.get('sport', 'football')

    # --- Get scoring engine outputs (primary signal) ---
    s_pick = match_row.get('scoring_pick', '')
    s_ev = _sf(match_row.get('scoring_ev'))
    s_edge = _sf(match_row.get('scoring_edge'))
    s_conf = _sf(match_row.get('scoring_confidence'))
    s_dq = _sf(match_row.get('scoring_data_quality'))

    # Probability distribution
    if sport == 'tennis':
        prob_h = _sf(match_row.get('scoring_prob_a', 50))
        prob_d = 0.0
        prob_a = _sf(match_row.get('scoring_prob_b', 50))
    else:
        prob_h = _sf(match_row.get('scoring_prob_home', 33))
        prob_d = _sf(match_row.get('scoring_prob_draw', 33))
        prob_a = _sf(match_row.get('scoring_prob_away', 33))

    # Pick — use scoring engine pick as primary; fall back to forebet or Gemini
    pick = s_pick
    if not pick:
        pick = match_row.get('forebet_prediction', '')
    if not pick:
        ft = match_row.get('focus_team', 'home')
        pick = '1' if ft == 'home' else '2'
        if sport == 'tennis':
            pick = 'A' if ft == 'home' else 'B'

    pick_lbl = _pick_label(pick, sport)

    # --- Source predictions & consensus ---
    source_preds = _extract_source_prediction(match_row, sport)
    agree, total = _compute_consensus(source_preds, pick)
    consensus_str = _consensus_label(agree, total)

    # --- Factor analysis ---
    factors = _build_factors(match_row, sport)

    # --- Data quality (composite) ---
    available = [f['name'] for f in factors if f['quality'] > 0]
    missing = [f['name'] for f in factors if f['quality'] <= 0]
    dq = len(available) / max(1, len(factors))
    # Blend with scoring engine data quality if available
    if s_dq > 0:
        dq = dq * 0.5 + s_dq * 0.5

    # --- Composite confidence ---
    # Weighted blend of scoring confidence, source agreement, and data quality
    conf_base = s_conf if s_conf > 0 else (_sf(match_row.get('gemini_confidence')) or _sf(match_row.get('forebet_probability')) or 50)
    consensus_bonus = (agree / max(1, total)) * 15  # up to +15 for full consensus
    dq_bonus = dq * 10  # up to +10 for full data
    risk_score, risk_level, risk_flags = _compute_risk(match_row, source_preds, pick, dq, factors)
    risk_penalty = risk_score * 1.5  # up to -15 for max risk

    composite_conf = conf_base + consensus_bonus + dq_bonus - risk_penalty
    composite_conf = max(5, min(99, composite_conf))

    conf_tier = _confidence_tier(composite_conf)

    # --- Value ---
    value_rating = _value_label(s_ev, s_edge)

    # --- Verdict ---
    verdict, short_verdict = _generate_verdict(
        match_row, pick, pick_lbl, composite_conf, consensus_str,
        risk_level, factors, s_ev, s_edge, sport,
    )

    # --- Arguments ---
    args_for, args_against = _extract_arguments(factors, match_row)

    # --- Guardrails ---
    dnb = _check_guardrails(composite_conf, dq, risk_score, risk_flags, agree, total)

    return AIPrediction(
        pick=pick,
        pick_label=pick_lbl,
        composite_confidence=composite_conf,
        confidence_tier=conf_tier,
        prob_home=prob_h,
        prob_draw=prob_d,
        prob_away=prob_a,
        consensus_sources=agree,
        consensus_total=total,
        consensus_strength=consensus_str,
        source_predictions=source_preds,
        ev=s_ev,
        edge=s_edge,
        value_rating=value_rating,
        risk_score=risk_score,
        risk_level=risk_level,
        risk_flags=risk_flags,
        factors=factors,
        data_quality=dq,
        data_quality_label=_dq_label(dq),
        available_sources=available,
        missing_sources=missing,
        key_arguments_for=args_for,
        key_arguments_against=args_against,
        verdict=verdict,
        short_verdict=short_verdict,
        do_not_bet_reasons=dnb,
    )
