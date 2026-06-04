#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qualification Gate — Unified channel qualification for all output channels
==========================================================================

Centralizes the odds, fan-vote, future-only, and data-quality filters
that were previously scattered across telegram_notifier.py and
email_notifier.py.  Both channels now consume the same qualification
decision made here.

Each match row receives:
  - channel_qualifies (bool)  — passes all shared filters
  - channel_skip_reasons (list[str]) — human-readable reasons for rejection

Usage from scrape_and_notify.py:
    from qualification_gate import apply_qualification_gate
    apply_qualification_gate(rows, date)
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

_WARSAW_TZ: ZoneInfo = ZoneInfo("Europe/Warsaw")

# ── Per-sport minimum odds thresholds ──────────────────────────────────────
SPORT_MIN_ODDS: Dict[str, float] = {
    "football": 1.50,
    "basketball": 1.30,
    "handball": 1.45,
    "volleyball": 1.30,
    "hockey": 1.50,
    "tennis": 1.35,
    "table_tennis": 1.35,
    "table-tennis": 1.35,
    "baseball": 1.40,
}
SPORT_MIN_ODDS_FALLBACK = 1.35

# ── SofaScore fan vote thresholds (dominant vote %) ────────────────────────
# Tennis is a 2-way sport where 55/45 splits are common and meaningful; a
# dedicated SofaScore check already runs in scrape_and_notify.py (FAZA 2.1),
# so the secondary channel gate uses a much softer threshold to avoid
# silently dropping all tennis matches.
FAN_VOTE_THRESHOLDS: Dict[str, float] = {
    "football": 65.0,
    "tennis": 55.0,
    "table_tennis": 55.0,
    "table-tennis": 55.0,
}
FAN_VOTE_DEFAULT_THRESHOLD = 80.0

# Sports where pitcher/starter data is required for gate (soft-fail by default
# until the scraper populates these fields reliably for baseball).
# When True, missing pitcher data blocks channel_qualifies. When False, it is
# only recorded as a non-blocking warning in channel_skip_reasons_warnings.
BASEBALL_PITCHER_REQUIRED: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# INDIVIDUAL FILTERS
# ═══════════════════════════════════════════════════════════════════════════

def _passes_odds_filter(sport: str, match: Dict[str, Any]) -> bool:
    """Both home_odds and away_odds must be >= sport threshold when present.
    Missing odds → pass (don't penalize scrapers that couldn't fetch odds)."""
    ho = match.get("home_odds")
    ao = match.get("away_odds")
    if not ho or not ao:
        return True  # missing odds → don't block qualification
    try:
        ho_f, ao_f = float(ho), float(ao)
    except (ValueError, TypeError):
        return True
    threshold = SPORT_MIN_ODDS.get(sport, SPORT_MIN_ODDS_FALLBACK)
    return ho_f >= threshold and ao_f >= threshold


def _fan_vote_diagnostics(sport: str, match: Dict[str, Any]) -> tuple:
    """Zwróć (passes, dominant, threshold, reason).

    - ``passes`` (bool): True gdy mecz przechodzi filtr fan-vote.
    - ``dominant`` (Optional[float]): najwyższy procent z H/D/A albo None.
    - ``threshold`` (float): próg per sport zastosowany do oceny.
    - ``reason`` (Optional[str]): kod logujący (``fan_vote_missing`` /
      ``fan_vote_below_threshold:DOMINANT/THRESHOLD``) albo None gdy passes.

    Brak danych SofaScore → zwracamy ``passes=True`` (nie penalizujemy
    scrapera, który nie znalazł meczu), ale zapisujemy ``fan_vote_missing``
    jako warning, żeby powód był jawny w logach gate i w `channel_skip_reasons_warnings`.
    """
    h = match.get("sofascore_home_win_prob")
    d = match.get("sofascore_draw_prob")
    a = match.get("sofascore_away_win_prob")
    probs = [p for p in (h, d, a) if p is not None]
    threshold = FAN_VOTE_THRESHOLDS.get(sport, FAN_VOTE_DEFAULT_THRESHOLD)
    if not probs:
        return True, None, threshold, "fan_vote_missing"
    try:
        dominant = max(float(p) for p in probs)
    except (ValueError, TypeError):
        return True, None, threshold, "fan_vote_unparseable"
    if dominant >= threshold:
        return True, dominant, threshold, None
    return False, dominant, threshold, f"fan_vote_below_threshold:{dominant:.0f}/{threshold:.0f}"


def _passes_fan_vote_filter(sport: str, match: Dict[str, Any]) -> bool:
    """Dominant SofaScore fan vote must meet threshold. No data → pass.

    Cienki adapter zachowany dla zewnętrznych konsumentów; pełną diagnostykę
    daje :func:`_fan_vote_diagnostics`.
    """
    passes, _, _, _ = _fan_vote_diagnostics(sport, match)
    return passes


def _parse_match_time(match_time_str: Any) -> Optional[datetime]:
    """Parse 'DD.MM.YYYY HH:MM' → naive datetime, or None."""
    if not match_time_str:
        return None
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})', str(match_time_str))
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)),
                        int(m.group(4)), int(m.group(5)))
    except ValueError:
        return None


def _is_future_match(match: Dict[str, Any], now_warsaw: datetime) -> bool:
    """True if match hasn't started yet or we can't determine.
    Same-day matches whose start time is in the past → False.
    Different-date or unparseable → True (kept)."""
    parsed = _parse_match_time(match.get("match_time"))
    if parsed is None:
        return True
    if parsed.date() != now_warsaw.date():
        return True
    return parsed.hour * 60 + parsed.minute > now_warsaw.hour * 60 + now_warsaw.minute


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED GATE
# ═══════════════════════════════════════════════════════════════════════════

def qualify_match(match: Dict[str, Any], now_warsaw: Optional[datetime] = None) -> bool:
    """Apply all shared filters to a single match.
    Returns True if the match passes all gates.
    Also sets match['channel_skip_reasons'] list."""
    if now_warsaw is None:
        now_warsaw = datetime.now(_WARSAW_TZ).replace(tzinfo=None)

    reasons: List[str] = []
    warnings: List[str] = []
    sport = match.get("sport", "football")

    # Gate 0: must have base qualification
    if not match.get("qualifies"):
        reasons.append("base_qualification_failed")

    # Gate 1: odds must be above threshold (missing odds → pass)
    if not _passes_odds_filter(sport, match):
        reasons.append("odds_below_threshold")

    # Gate 2: fan vote consensus
    fv_passes, fv_dominant, fv_threshold, fv_reason = _fan_vote_diagnostics(sport, match)
    if not fv_passes:
        # Konkretny powód z wartością (np. "fan_vote_below_threshold:62/65"),
        # żeby logi gate jasno mówiły "ile zabrakło" zamiast tylko "below_threshold".
        reasons.append(fv_reason or "fan_vote_below_threshold")
    elif fv_reason in ("fan_vote_missing", "fan_vote_unparseable"):
        # Brak danych SofaScore nie blokuje kanału, ale chcemy go widzieć
        # w warnings — to częsta i nieoczywista przyczyna pustej sekcji
        # SofaScore Fan Vote w mailu.
        warnings.append(fv_reason)
    # Wzbogać rekord o stałe pola diagnostyczne (czytane przez mail/Telegram).
    match["fan_vote_dominant"] = fv_dominant
    match["fan_vote_threshold"] = fv_threshold

    # Gate 3: future match only
    if not _is_future_match(match, now_warsaw):
        reasons.append("match_already_started")

    # Gate 4: baseball requires starter pitcher data
    # Soft-fail by default: record the missing data as a warning so the match
    # can still flow to channels (email/Telegram) while we finish the pitcher
    # scraper. Flip BASEBALL_PITCHER_REQUIRED to True once data is reliable.
    if sport == "baseball":
        if not match.get("pitcher_home") or not match.get("pitcher_away"):
            if BASEBALL_PITCHER_REQUIRED:
                reasons.append("baseball_missing_pitcher")
            else:
                warnings.append("baseball_missing_pitcher")

    match["channel_skip_reasons"] = reasons
    match["channel_skip_reasons_warnings"] = warnings
    qualifies = len(reasons) == 0
    match["channel_qualifies"] = qualifies
    return qualifies


def apply_qualification_gate(
    rows: List[Dict[str, Any]],
    date: str = "",
    now_warsaw: Optional[datetime] = None,
) -> int:
    """Apply unified qualification gate to all rows.
    Returns count of channel-qualifying matches."""
    if now_warsaw is None:
        now_warsaw = datetime.now(_WARSAW_TZ).replace(tzinfo=None)

    count = 0
    sport_stats: Dict[str, Dict[str, int]] = {}
    reason_counts: Dict[str, int] = {}
    warning_counts: Dict[str, int] = {}

    for row in rows:
        sport = row.get("sport", "football")
        stats = sport_stats.setdefault(sport, {"total": 0, "qualified": 0})
        stats["total"] += 1

        if qualify_match(row, now_warsaw):
            count += 1
            stats["qualified"] += 1
        else:
            for reason in row.get("channel_skip_reasons", []):
                # Grupuj dynamiczne powody (np. "fan_vote_below_threshold:62/65")
                # po prefiksie sprzed ":" — chcemy widzieć "ilu meczów odpadło
                # przez fan-vote", nie listę unikalnych par dominant/threshold.
                key = reason.split(":", 1)[0] if isinstance(reason, str) else str(reason)
                reason_counts[key] = reason_counts.get(key, 0) + 1

        for warn in row.get("channel_skip_reasons_warnings", []) or []:
            key = warn.split(":", 1)[0] if isinstance(warn, str) else str(warn)
            warning_counts[key] = warning_counts.get(key, 0) + 1

    # ── Per-sport breakdown ──
    for sport, stats in sorted(sport_stats.items()):
        q = stats["qualified"]
        t = stats["total"]
        tag = "✅" if q > 0 else "⚠️"
        print(f"   {tag} {sport}: {q}/{t} channel-qualified")

    if reason_counts:
        parts = [f"{r}={c}" for r, c in sorted(reason_counts.items())]
        print(f"   📋 Rejection reasons: {', '.join(parts)}")

    if warning_counts:
        parts = [f"{r}={c}" for r, c in sorted(warning_counts.items())]
        print(f"   ⚠️  Soft warnings (non-blocking): {', '.join(parts)}")

    return count
