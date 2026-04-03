#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prediction Data Contract — Unified schema for all sports
=========================================================

Defines the canonical fields every match prediction must have,
regardless of sport. Provides enrichment functions that compute
derived quality/availability signals from raw scraper data.

Used by scrape_and_notify.py (enrichment phase) and prediction_evaluator.py.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import math


# ═══════════════════════════════════════════════════════════════════════════
# DATA QUALITY & AVAILABILITY SIGNALS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DataQualityReport:
    """Per-match data quality assessment."""
    sources_available: int = 0        # How many sources provided data (0-4)
    sources_total: int = 4            # H2H, Forebet, SofaScore, Gemini
    h2h_available: bool = False
    forebet_available: bool = False
    sofascore_available: bool = False
    gemini_available: bool = False
    odds_available: bool = False
    form_available: bool = False
    scoring_available: bool = False

    # Freshness
    h2h_count: int = 0               # Number of H2H meetings
    h2h_recency_days: Optional[int] = None  # Days since last H2H

    # Consensus
    sources_agree: int = 0            # How many sources agree on winner
    consensus_strength: str = 'none'  # 'strong', 'moderate', 'weak', 'none'
    market_model_gap: Optional[float] = None  # Diff between model prob and implied prob

    @property
    def quality_score(self) -> float:
        """0.0 to 1.0 overall quality."""
        score = 0.0
        if self.h2h_available:
            score += 0.2
            if self.h2h_count >= 3:
                score += 0.05
        if self.forebet_available:
            score += 0.2
        if self.sofascore_available:
            score += 0.15
        if self.odds_available:
            score += 0.25
        if self.form_available:
            score += 0.1
        if self.gemini_available:
            score += 0.1
        return min(1.0, score)

    @property
    def skip_reason(self) -> Optional[str]:
        """Reason to skip this match, or None if OK."""
        if self.quality_score < 0.25:
            return 'insufficient_data'
        if not self.odds_available:
            return 'no_odds'
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sources_available': self.sources_available,
            'quality_score': round(self.quality_score, 2),
            'h2h_available': self.h2h_available,
            'forebet_available': self.forebet_available,
            'sofascore_available': self.sofascore_available,
            'gemini_available': self.gemini_available,
            'odds_available': self.odds_available,
            'form_available': self.form_available,
            'h2h_count': self.h2h_count,
            'consensus_strength': self.consensus_strength,
            'market_model_gap': round(self.market_model_gap, 3) if self.market_model_gap is not None else None,
            'skip_reason': self.skip_reason,
        }


# ═══════════════════════════════════════════════════════════════════════════
# INJURY / AVAILABILITY FLAGS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PlayerAvailability:
    """Availability status for a player or team."""
    status: str = 'unknown'          # 'available', 'injured', 'doubtful', 'suspended', 'unknown'
    injury_type: Optional[str] = None  # 'knee', 'muscle', etc.
    days_out: Optional[int] = None     # Expected days out
    source: str = 'none'             # Where this info came from
    confidence: float = 0.0          # 0-1 confidence in this info

    def to_dict(self) -> Dict[str, Any]:
        return {
            'status': self.status,
            'injury_type': self.injury_type,
            'days_out': self.days_out,
            'source': self.source,
            'confidence': round(self.confidence, 2),
        }


@dataclass
class AvailabilityReport:
    """Match-level availability assessment."""
    # Tennis specific
    player_a_status: Optional[PlayerAvailability] = None
    player_b_status: Optional[PlayerAvailability] = None

    # Team sport
    home_key_absences: int = 0
    away_key_absences: int = 0

    # Common signals (computed from existing data)
    home_days_since_last: Optional[int] = None
    away_days_since_last: Optional[int] = None
    home_matches_last_7d: int = 0
    away_matches_last_7d: int = 0
    home_retirement_flag: bool = False   # Last match was retirement/walkover
    away_retirement_flag: bool = False
    schedule_density_home: str = 'normal'  # 'congested', 'normal', 'rested'
    schedule_density_away: str = 'normal'

    @property
    def fatigue_risk(self) -> str:
        """Overall fatigue risk level."""
        if (self.home_matches_last_7d >= 4 or self.away_matches_last_7d >= 4):
            return 'high'
        if (self.home_matches_last_7d >= 3 or self.away_matches_last_7d >= 3):
            return 'moderate'
        if (self.home_days_since_last is not None and self.home_days_since_last <= 1) or \
           (self.away_days_since_last is not None and self.away_days_since_last <= 1):
            return 'moderate'
        return 'low'

    @property
    def availability_impact(self) -> float:
        """Impact on prediction reliability, 0.0 (none) to 1.0 (severe)."""
        impact = 0.0

        # Retirement/walkover flags
        if self.home_retirement_flag or self.away_retirement_flag:
            impact += 0.3

        # Schedule congestion
        if self.schedule_density_home == 'congested':
            impact += 0.15
        if self.schedule_density_away == 'congested':
            impact += 0.15

        # Key absences (team sports)
        if self.home_key_absences >= 3 or self.away_key_absences >= 3:
            impact += 0.2
        elif self.home_key_absences >= 1 or self.away_key_absences >= 1:
            impact += 0.1

        # Player injury (tennis)
        if self.player_a_status and self.player_a_status.status in ('injured', 'doubtful'):
            impact += 0.3
        if self.player_b_status and self.player_b_status.status in ('injured', 'doubtful'):
            impact += 0.3

        return min(1.0, impact)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            'home_days_since_last': self.home_days_since_last,
            'away_days_since_last': self.away_days_since_last,
            'home_matches_last_7d': self.home_matches_last_7d,
            'away_matches_last_7d': self.away_matches_last_7d,
            'home_retirement_flag': self.home_retirement_flag,
            'away_retirement_flag': self.away_retirement_flag,
            'schedule_density_home': self.schedule_density_home,
            'schedule_density_away': self.schedule_density_away,
            'fatigue_risk': self.fatigue_risk,
            'availability_impact': round(self.availability_impact, 2),
        }
        if self.player_a_status:
            d['player_a'] = self.player_a_status.to_dict()
        if self.player_b_status:
            d['player_b'] = self.player_b_status.to_dict()
        if self.home_key_absences or self.away_key_absences:
            d['home_key_absences'] = self.home_key_absences
            d['away_key_absences'] = self.away_key_absences
        return d


# ═══════════════════════════════════════════════════════════════════════════
# MODEL EXPLANATION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PredictionExplanation:
    """Human-readable explanation of why this prediction was made."""
    primary_factors: List[str] = field(
        default_factory=lambda: []  # type: ignore[assignment]
    )
    risk_factors: List[str] = field(
        default_factory=lambda: []  # type: ignore[assignment]
    )
    data_quality_note: str = ''
    availability_note: str = ''
    expected_edge: Optional[float] = None   # % edge over market
    consensus_note: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'primary_factors': self.primary_factors[:3],
            'risk_factors': self.risk_factors[:3],
            'data_quality_note': self.data_quality_note,
            'availability_note': self.availability_note,
            'expected_edge': round(self.expected_edge, 1) if self.expected_edge is not None else None,
            'consensus_note': self.consensus_note,
        }


# ═══════════════════════════════════════════════════════════════════════════
# ENRICHMENT FUNCTIONS — Compute from raw row data
# ═══════════════════════════════════════════════════════════════════════════

def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse various date formats."""
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d.%m.%Y %H:%M', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def compute_data_quality(row: Dict[str, Any]) -> DataQualityReport:
    """Compute data quality report from a raw match row dict."""
    dq = DataQualityReport()

    # H2H
    h2h_count = 0
    try:
        h2h_count = int(row.get('h2h_count', 0) or 0)
    except (TypeError, ValueError):
        pass
    dq.h2h_available = h2h_count > 0
    dq.h2h_count = h2h_count
    if dq.h2h_available:
        dq.sources_available += 1

    # Last H2H date (for tennis)
    last_h2h_date = row.get('last_h2h_date')
    if last_h2h_date:
        dt = _parse_date(str(last_h2h_date))
        if dt:
            dq.h2h_recency_days = (datetime.now() - dt).days

    # Forebet
    dq.forebet_available = bool(row.get('forebet_prediction'))
    if dq.forebet_available:
        dq.sources_available += 1

    # SofaScore
    ss_home = _safe_float(row.get('sofascore_home_win_prob'))
    ss_away = _safe_float(row.get('sofascore_away_win_prob'))
    dq.sofascore_available = (ss_home is not None and ss_away is not None)
    if dq.sofascore_available:
        dq.sources_available += 1

    # Gemini
    dq.gemini_available = bool(row.get('gemini_recommendation'))
    if dq.gemini_available:
        dq.sources_available += 1

    # Odds
    home_odds = _safe_float(row.get('home_odds'))
    away_odds = _safe_float(row.get('away_odds'))
    dq.odds_available = (home_odds is not None and home_odds > 1.0 and
                          away_odds is not None and away_odds > 1.0)

    # Form
    home_form: List[Any] = row.get('home_form') or row.get('homeForm') or []
    away_form: List[Any] = row.get('away_form') or row.get('awayForm') or []
    dq.form_available = len(home_form) > 0 and len(away_form) > 0

    # Scoring
    dq.scoring_available = row.get('scoring_pick') is not None

    # Consensus
    predicted = _predicted_side(row)
    agreements = 0
    total_sources = 0

    if dq.forebet_available:
        total_sources += 1
        fp = str(row.get('forebet_prediction', ''))
        if (predicted == 'home' and fp == '1') or (predicted == 'away' and fp == '2'):
            agreements += 1

    if dq.sofascore_available:
        total_sources += 1
        if (predicted == 'home' and (ss_home or 0) > (ss_away or 0)) or \
           (predicted == 'away' and (ss_away or 0) > (ss_home or 0)):
            agreements += 1

    if dq.gemini_available:
        total_sources += 1
        rec = row.get('gemini_recommendation', '')
        if rec in ('HIGH', 'LOCK'):
            agreements += 1

    dq.sources_agree = agreements
    if total_sources >= 3 and agreements >= 3:
        dq.consensus_strength = 'strong'
    elif total_sources >= 2 and agreements >= 2:
        dq.consensus_strength = 'moderate'
    elif agreements >= 1:
        dq.consensus_strength = 'weak'
    else:
        dq.consensus_strength = 'none'

    # Market vs model gap
    scoring_prob = _safe_float(row.get('scoring_prob'))
    implied = None
    if predicted == 'home' and home_odds and home_odds > 1.0:
        implied = 1.0 / home_odds * 100
    elif predicted == 'away' and away_odds and away_odds > 1.0:
        implied = 1.0 / away_odds * 100

    if scoring_prob is not None and implied is not None:
        dq.market_model_gap = scoring_prob - implied

    return dq


def compute_availability(row: Dict[str, Any], sport: str = '') -> AvailabilityReport:
    """Compute availability report from raw match row dict.

    Extracts signals from existing data:
    - last_match_*_date → days since last match
    - last_match_*_result → retirement/walkover detection
    - form arrays → schedule density approximation
    """
    avail = AvailabilityReport()
    sport = sport or (row.get('sport') or 'football').lower()

    now = datetime.now()

    if sport == 'tennis':
        # Player A last match
        lm_a_date = row.get('last_match_a_date')
        if lm_a_date:
            dt = _parse_date(str(lm_a_date))
            if dt:
                avail.home_days_since_last = (now - dt).days

        # Player B last match
        lm_b_date = row.get('last_match_b_date')
        if lm_b_date:
            dt = _parse_date(str(lm_b_date))
            if dt:
                avail.away_days_since_last = (now - dt).days

        # Retirement / walkover detection from last match result
        lm_a_result = str(row.get('last_match_a_result', '') or '').lower()
        lm_b_result = str(row.get('last_match_b_result', '') or '').lower()
        lm_a_score = str(row.get('last_match_a_score', '') or '').lower()
        lm_b_score = str(row.get('last_match_b_score', '') or '').lower()

        retirement_markers = ['ret', 'w.o', 'walkover', 'retired', 'withdrawal']
        for marker in retirement_markers:
            if marker in lm_a_result or marker in lm_a_score:
                avail.home_retirement_flag = True
            if marker in lm_b_result or marker in lm_b_score:
                avail.away_retirement_flag = True

        # Schedule density from fatigue (already computed by tennis engine)
        if avail.home_days_since_last is not None:
            if avail.home_days_since_last <= 1:
                avail.schedule_density_home = 'congested'
            elif avail.home_days_since_last >= 7:
                avail.schedule_density_home = 'rested'

        if avail.away_days_since_last is not None:
            if avail.away_days_since_last <= 1:
                avail.schedule_density_away = 'congested'
            elif avail.away_days_since_last >= 7:
                avail.schedule_density_away = 'rested'

    else:
        # Team sports — approximate from form arrays
        home_form: List[Any] = row.get('home_form') or row.get('homeForm') or []
        away_form: List[Any] = row.get('away_form') or row.get('awayForm') or []

        # Use form array length as rough match count proxy
        if len(home_form) >= 5:
            avail.home_matches_last_7d = min(len(home_form), 5)
        if len(away_form) >= 5:
            avail.away_matches_last_7d = min(len(away_form), 5)

    return avail


def compute_explanation(row: Dict[str, Any], dq: DataQualityReport,
                        avail: AvailabilityReport) -> PredictionExplanation:
    """Generate prediction explanation from available data."""
    expl = PredictionExplanation()

    # Primary factors
    scoring_prob = _safe_float(row.get('scoring_prob'))
    scoring_edge = _safe_float(row.get('scoring_edge'))
    scoring_ev = _safe_float(row.get('scoring_ev'))

    if scoring_prob and scoring_prob >= 70:
        expl.primary_factors.append(f'Model probability: {scoring_prob:.0f}%')
    if scoring_ev and scoring_ev > 0.1:
        expl.primary_factors.append(f'Positive expected value: {scoring_ev:.2f}')
    if dq.consensus_strength in ('strong', 'moderate'):
        expl.primary_factors.append(f'Source consensus: {dq.consensus_strength} ({dq.sources_agree}/{dq.sources_available})')
    if dq.h2h_count >= 3:
        win_rate = _safe_float(row.get('win_rate'))
        if win_rate and win_rate >= 60:
            expl.primary_factors.append(f'H2H advantage: {win_rate:.0f}% ({dq.h2h_count} meetings)')
    if row.get('form_advantage'):
        expl.primary_factors.append('Form advantage confirmed')

    # Risk factors
    if dq.quality_score < 0.5:
        expl.risk_factors.append(f'Low data quality: {dq.quality_score:.0%}')
    if avail.availability_impact > 0.2:
        expl.risk_factors.append(f'Availability concern (impact: {avail.availability_impact:.0%})')
    if avail.home_retirement_flag or avail.away_retirement_flag:
        expl.risk_factors.append('Recent retirement/walkover detected')
    if avail.fatigue_risk in ('high', 'moderate'):
        expl.risk_factors.append(f'Fatigue risk: {avail.fatigue_risk}')
    if dq.consensus_strength in ('weak', 'none'):
        expl.risk_factors.append('Sources disagree on prediction')

    # Notes
    expl.data_quality_note = f'{dq.sources_available}/{dq.sources_total} sources available (quality: {dq.quality_score:.0%})'
    expl.expected_edge = scoring_edge
    expl.consensus_note = f'{dq.consensus_strength} ({dq.sources_agree} sources agree)'

    if avail.availability_impact > 0:
        parts: List[str] = []
        if avail.home_retirement_flag:
            parts.append('home retirement')
        if avail.away_retirement_flag:
            parts.append('away retirement')
        if avail.fatigue_risk != 'low':
            parts.append(f'fatigue: {avail.fatigue_risk}')
        expl.availability_note = ', '.join(parts) if parts else 'minor concern'

    return expl


def _predicted_side(row: Dict[str, Any]) -> str:
    """Determine which side was predicted from row."""
    sport = (row.get('sport') or 'football').lower()
    if sport == 'tennis':
        pick = row.get('scoring_pick', '')
        if pick:
            return 'home' if '1' in str(pick) or 'A' in str(pick).upper() else 'away'
        fav = row.get('favorite', '')
        if fav:
            return 'home' if str(fav).upper() in ('A', 'PLAYER_A') else 'away'
    return (row.get('focus_team') or 'home').lower()


# ═══════════════════════════════════════════════════════════════════════════
# ENRICHMENT FUNCTION — Call from scrape_and_notify.py
# ═══════════════════════════════════════════════════════════════════════════

def enrich_match_with_contract(row: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a match row dict with data contract fields.

    Adds:
      data_quality: dict with quality metrics
      availability: dict with availability/injury signals
      explanation: dict with prediction explanation
      prediction_grade: A-F overall grade

    This should be called AFTER Phase 2.5 (scoring engines).
    """
    sport = (row.get('sport') or 'football').lower()

    dq = compute_data_quality(row)
    avail = compute_availability(row, sport)
    expl = compute_explanation(row, dq, avail)

    row['data_quality'] = dq.to_dict()
    row['availability'] = avail.to_dict()
    row['explanation'] = expl.to_dict()

    # Overall prediction grade
    scoring_prob = _safe_float(row.get('scoring_prob'))
    grade = _compute_grade(dq, avail, scoring_prob)
    row['prediction_grade'] = grade

    return row


def _compute_grade(dq: DataQualityReport, avail: AvailabilityReport,
                   scoring_prob: Optional[float]) -> str:
    """Compute A-F prediction grade."""
    score = 0.0

    # Data quality contribution (0-40 points)
    score += dq.quality_score * 40

    # Consensus contribution (0-20 points)
    consensus_map = {'strong': 20, 'moderate': 12, 'weak': 5, 'none': 0}
    score += consensus_map.get(dq.consensus_strength, 0)

    # Availability (penalty)
    score -= avail.availability_impact * 15

    # Model probability contribution (0-20 points)
    if scoring_prob is not None:
        if scoring_prob >= 75:
            score += 20
        elif scoring_prob >= 65:
            score += 15
        elif scoring_prob >= 55:
            score += 10
        else:
            score += 5

    # Edge contribution (0-20 points)
    if dq.market_model_gap is not None:
        if dq.market_model_gap > 15:
            score += 20
        elif dq.market_model_gap > 10:
            score += 15
        elif dq.market_model_gap > 5:
            score += 10
        elif dq.market_model_gap > 0:
            score += 5

    if score >= 80:
        return 'A'
    elif score >= 65:
        return 'B'
    elif score >= 50:
        return 'C'
    elif score >= 35:
        return 'D'
    else:
        return 'F'
