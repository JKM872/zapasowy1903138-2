"""
Telegram Notifier — daily summary of qualifying matches
========================================================

Sends a single Telegram message after a successful email notification.
Gated by TELEGRAM_ENABLED env var (default: false).

Configuration (env vars):
    TELEGRAM_BOT_TOKEN  — Bot API token from @BotFather
    TELEGRAM_CHAT_ID    — Target chat / user ID
    TELEGRAM_ENABLED    — "true" to enable sending (default: "false")
"""

from __future__ import annotations

import os
import re
import urllib.request
import urllib.error
import json
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

_API_BASE = "https://api.telegram.org/bot{token}"
_MAX_MSG_LEN = 4096
_TIMEOUT = 15  # seconds

# Per-sport minimum odds thresholds (mirrored from email_notifier)
_SPORT_MIN_ODDS: Dict[str, float] = {
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
_SPORT_MIN_ODDS_FALLBACK = 1.35

# SofaScore fan vote thresholds (dominant vote %)
# NOTE: tennis intentionally falls back to the 80% default here (the primary
# tennis fan-vote gate runs earlier in scrape_and_notify). table_tennis gets
# its own softer threshold because the table-tennis pipeline relies on this
# value as its display-side gate.
_FAN_VOTE_THRESHOLDS: Dict[str, float] = {
    "football": 65.0,
    "table_tennis": 55.0,
    "table-tennis": 55.0,
}
_FAN_VOTE_DEFAULT_THRESHOLD = 80.0

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


# ---------------------------------------------------------------------------
# Low-level sender
# ---------------------------------------------------------------------------

def _send_message(text: str, token: str = "", chat_id: str = "") -> bool:
    """Send a single Telegram message via Bot API (urllib, no extra deps)."""
    tok = token or _BOT_TOKEN
    cid = chat_id or _CHAT_ID
    if not tok or not cid:
        print("⚠️  Telegram: brak TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID")
        return False

    url = f"{_API_BASE.format(token=tok)}/sendMessage"
    payload = json.dumps({
        "chat_id": cid,
        "text": text[:_MAX_MSG_LEN],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                if resp.status == 200:
                    print("✅ Telegram: wiadomość wysłana.")
                    return True
                print(f"⚠️  Telegram: HTTP {resp.status}")
                return False
        except urllib.error.HTTPError as exc:
            print(f"⚠️  Telegram: HTTP {exc.code} — {exc.reason}")
            return False
        except (urllib.error.URLError, OSError) as exc:
            if attempt == 0:
                print(f"⚠️  Telegram: retry po błędzie — {exc}")
                continue
            print(f"❌ Telegram: błąd połączenia — {exc}")
            return False
    return False


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def _passes_odds_filter(sport: str, home_odds: Any, away_odds: Any) -> bool:
    """Both odds must be >= sport threshold. Missing odds → pass."""
    if not home_odds or not away_odds:
        return True
    try:
        ho, ao = float(home_odds), float(away_odds)
    except (ValueError, TypeError):
        return True
    threshold = _SPORT_MIN_ODDS.get(sport, _SPORT_MIN_ODDS_FALLBACK)
    return ho >= threshold and ao >= threshold


def _passes_fan_vote_filter(sport: str, match: Dict[str, Any]) -> bool:
    """Dominant SofaScore fan vote must meet threshold. No data → pass."""
    h = match.get("sofascore_home_win_prob")
    d = match.get("sofascore_draw_prob")
    a = match.get("sofascore_away_win_prob")
    probs = [p for p in (h, d, a) if p is not None]
    if not probs:
        return True
    try:
        dominant = max(float(p) for p in probs)
    except (ValueError, TypeError):
        return True
    threshold = _FAN_VOTE_THRESHOLDS.get(sport, _FAN_VOTE_DEFAULT_THRESHOLD)
    return dominant >= threshold


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _parse_match_time(match_time_str: Any) -> datetime | None:
    """Parse 'DD.MM.YYYY HH:MM' \u2192 naive datetime, or None."""
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

    Only filters same-day matches whose start time is earlier than *now_warsaw*.
    Different-date matches and rows without parseable match_time are kept.
    """
    parsed = _parse_match_time(match.get("match_time"))
    if parsed is None:
        return True
    if parsed.date() != now_warsaw.date():
        return True
    return parsed.hour * 60 + parsed.minute > now_warsaw.hour * 60 + now_warsaw.minute


def _canonical_pick(match: Dict[str, Any]) -> str:
    """Return '1', 'X', '2' or '' for the recommended pick.

    Falls back to ``focus_team`` when neither ``scoring_pick`` nor
    ``forebet_prediction`` is set (edge case where Forebet failed but the
    form-advantage focus is still known).
    """
    raw = (match.get("scoring_pick") or match.get("forebet_prediction") or "").strip().upper()
    if raw in ("1", "H", "1X"):
        return "1"
    if raw in ("2", "A", "X2"):
        return "2"
    if raw == "X":
        return "X"
    focus = (match.get("focus_team") or "").strip().lower()
    if focus == "home":
        return "1"
    if focus == "away":
        return "2"
    return ""


def _pick_odds(match: Dict[str, Any]) -> str:
    """Return formatted odds value for the recommended pick, or ''."""
    pick = _canonical_pick(match)
    ho = match.get("home_odds")
    ao = match.get("away_odds")
    do = match.get("draw_odds")
    odds_val = None
    if pick == "1":
        odds_val = ho
    elif pick == "2":
        odds_val = ao
    elif pick == "X":
        odds_val = do
    if odds_val is None:
        odds_val = ho
    if odds_val:
        try:
            return f"{float(odds_val):.2f}"
        except (ValueError, TypeError):
            pass
    return ""


def _describe_pick(match: Dict[str, Any]) -> str:
    """Human-readable 'what to bet' line, e.g. 'Home win (1) — Arsenal'.

    Returns an empty string when no pick can be inferred — callers skip the
    Bet line in that case so the template never prints a half-empty entry.
    """
    pick = _canonical_pick(match)
    home = (match.get("home_team") or "").strip()
    away = (match.get("away_team") or "").strip()
    sport = (match.get("sport") or "").lower()
    _is_player_sport = sport in ("tennis", "table_tennis", "table-tennis")

    if pick == "1":
        label = "Player 1 to win (1)" if _is_player_sport else "Home win (1)"
        side = home
    elif pick == "2":
        label = "Player 2 to win (2)" if _is_player_sport else "Away win (2)"
        side = away
    elif pick == "X":
        return "Draw (X)"
    else:
        return ""

    return f"{label} \u2014 {side}" if side else label


def _forebet_line(match: Dict[str, Any]) -> str:
    """Labeled Forebet line, e.g. 'Forebet: pick 1 at 65%'. Returns '' when missing."""
    pred = (match.get("forebet_prediction") or "").strip()
    prob = match.get("forebet_probability")
    if not pred or prob is None:
        return ""
    try:
        return f"Forebet: pick {pred} at {float(prob):.0f}%"
    except (ValueError, TypeError):
        return ""


def _sofascore_fan_vote_line(match: Dict[str, Any]) -> str:
    """Labeled SofaScore fan-vote line with the leading outcome.

    Example: ``'SofaScore fan vote: 83% on 1'`` (where 1/X/2 follows the
    outcome with the highest share).

    Gdy nie ma żadnych liczb, ale scraper jawnie zaznaczył próbę
    (``sofascore_found=False`` lub ``sofascore_skip_reason``), zwracamy
    krótką diagnostyczną linijkę typu ``'SofaScore fan vote: brak danych
    (not_found)'`` zamiast pustego stringu — żeby użytkownik od razu
    widział, że źródło było sprawdzane, a nie wycięte.
    """
    probs = {
        "1": match.get("sofascore_home_win_prob"),
        "X": match.get("sofascore_draw_prob"),
        "2": match.get("sofascore_away_win_prob"),
    }
    numeric: Dict[str, float] = {}
    for key, val in probs.items():
        if val is None:
            continue
        try:
            numeric[key] = float(val)
        except (ValueError, TypeError):
            continue
    if numeric:
        leading = max(numeric, key=lambda k: numeric[k])
        return f"SofaScore fan vote: {numeric[leading]:.0f}% on {leading}"

    # Brak liczb — sprawdź czy scraper coś próbował.
    found_raw = match.get("sofascore_found")
    skip_reason = match.get("sofascore_skip_reason")
    tried = False
    if isinstance(found_raw, bool):
        tried = found_raw is False
    elif isinstance(found_raw, str):
        tried = found_raw.strip().lower() in ("false", "0", "no")
    if not tried and skip_reason:
        tried = True
    if not tried:
        return ""

    reason_label = ""
    if skip_reason:
        reason_label = f" ({str(skip_reason).split(':', 1)[0]})"
    return f"SofaScore fan vote: brak danych{reason_label}"


# ---------------------------------------------------------------------------
# Qualification helper
# ---------------------------------------------------------------------------

def _get_qualifying_rows(
    rows: List[Dict[str, Any]],
    now_warsaw: datetime,
) -> List[Dict[str, Any]]:
    """Return rows that pass all Telegram channel filters."""
    if any(r.get("channel_qualifies") is not None for r in rows):
        return [r for r in rows if r.get("channel_qualifies")]

    qual = [r for r in rows if r.get("qualifies")]
    qual = [
        r for r in qual
        if _passes_odds_filter(
            r.get("sport", "football"), r.get("home_odds"), r.get("away_odds")
        )
    ]
    qual = [r for r in qual if _passes_fan_vote_filter(r.get("sport", "football"), r)]
    qual = [r for r in qual if _is_future_match(r, now_warsaw)]
    return qual


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _sport_emoji(sport: str) -> str:
    return {
        "football": "⚽",
        "basketball": "🏀",
        "volleyball": "🏐",
        "handball": "🤾",
        "hockey": "🏒",
        "tennis": "🎾",
        "table_tennis": "🏓",
        "table-tennis": "🏓",
    }.get(sport, "🏅")


_PREMIUM_GRADES = frozenset({"A"})
_TOP_N = 10
_SIMILAR_VALUE_EPSILON = 0.5  # below this gap, treat as a tie


def _model_score(match: Dict[str, Any]) -> float:
    """Primary ranking key — uses our own scoring engine output.
    
    Prefers scoring_confidence (from FootballScoringEngine), then falls back
    to ai_composite_confidence (legacy AI prediction engine). Returns 0.0
    when neither is set so unscored picks land at the bottom.
    """
    raw = match.get("scoring_confidence")
    if raw is None:
        raw = match.get("ai_composite_confidence")
    try:
        val = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        val = 0.0
    return val


def _model_ev(match: Dict[str, Any]) -> float:
    """Secondary ranking key — model EV (positive = edge over market)."""
    raw = match.get("scoring_ev")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _model_pick_odds(match: Dict[str, Any]) -> float:
    """Tertiary ranking key — odds for the model's pick (lower = stronger fav)."""
    pick = (match.get("scoring_pick") or "").upper()
    if pick == "1":
        odds = match.get("home_odds")
    elif pick == "2":
        odds = match.get("away_odds")
    elif pick == "X":
        odds = match.get("draw_odds")
    else:
        odds = match.get("home_odds") or match.get("away_odds")
    try:
        return float(odds) if odds else 999.0
    except (TypeError, ValueError):
        return 999.0


def _rank_picks_with_tiebreak(matches: List[Dict[str, Any]],
                               top_n: int = _TOP_N,
                               epsilon: float = _SIMILAR_VALUE_EPSILON,
                               ) -> List[Dict[str, Any]]:
    """Rank by model confidence. When two picks are within `epsilon` confidence
    points, tie-break on EV (higher better), then on odds (lower better).
    
    Implements user-requested 'reset countdown for similar values': similar
    confidences don't lock in arbitrary order — secondary metrics decide.
    """
    if not matches:
        return []
    
    def _bucket(m: Dict[str, Any]) -> int:
        # Bucket confidences in `epsilon`-wide bins; everything in same bin
        # is considered tied and sorted by EV/odds within.
        return -int(_model_score(m) / epsilon)
    
    sorted_matches = sorted(
        matches,
        key=lambda m: (
            _bucket(m),                # primary: confidence bucket (desc)
            -_model_ev(m),             # tie-break 1: EV (desc)
            _model_pick_odds(m),       # tie-break 2: odds (asc — favorites first)
            -_model_score(m),          # tie-break 3: raw confidence within bucket
        ),
    )
    return sorted_matches[:top_n]


def _build_summary(
    rows: List[Dict[str, Any]],
    qualifying_count: int,
    date: str,
    *,
    _now: datetime | None = None,
) -> str:
    """Build FormRadar-style daily summary for Telegram (Grade A only, top 10)."""
    now_warsaw = _now or datetime.now(_WARSAW_TZ).replace(tzinfo=None)

    lines: list[str] = []

    # Header — date in DD.MM.YYYY
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        date_display = d.strftime("%d.%m.%Y")
    except ValueError:
        date_display = date

    lines.append(f"🟢 <b>FormRadar — Top {_TOP_N} Picks</b> | {date_display}")
    lines.append("")

    # Filter: only Grade A, then rank globally (not per-sport) by our model
    qual = _get_qualifying_rows(rows, now_warsaw)
    qual = [r for r in qual if (r.get("prediction_grade") or "F") in _PREMIUM_GRADES]
    
    # Rank by model confidence with tie-breaking, cap at top N
    top_picks = _rank_picks_with_tiebreak(qual, top_n=_TOP_N)
    
    if not top_picks:
        lines.append("ℹ️ No Grade A picks today.")
        return "\n".join(lines)

    total_signals = 0
    for rank, m in enumerate(top_picks, 1):
        total_signals += 1
        sport = m.get("sport", "football")
        emoji = _sport_emoji(sport)
        home = m.get("home_team", "?")
        away = m.get("away_team", "?")

        lines.append(f"<b>#{rank}</b> {emoji} <b>{home}</b> vs <b>{away}</b>")

        league = (m.get("league") or "").strip()
        if league:
            lines.append(f"🏆 {league}")

        parsed_time = _parse_match_time(m.get("match_time"))
        if parsed_time:
            lines.append(f"🕐 Kick-off: {parsed_time.strftime('%H:%M')}")

        bet_text = _describe_pick(m)
        if bet_text:
            lines.append(f"🎯 <b>Bet:</b> {bet_text}")

        odds_str = _pick_odds(m)
        if odds_str:
            lines.append(f"💰 Odds: {odds_str}")

        conf_val = _model_score(m)
        if conf_val > 0:
            lines.append(f"📊 Model confidence: {conf_val:.0f}%")

        ev_val = _model_ev(m)
        if ev_val > 0:
            lines.append(f"💎 Value: positive EV ({ev_val:+.2f})")

        forebet = _forebet_line(m)
        if forebet:
            lines.append(f"🧮 {forebet}")

        fan_vote = _sofascore_fan_vote_line(m)
        if fan_vote:
            lines.append(f"👥 {fan_vote}")

        explanation: Dict[str, Any] = m.get("explanation") or {}
        factors: List[str] = explanation.get("primary_factors", [])
        risks: List[str] = [
            r for r in explanation.get("risk_factors", [])
            if r != "Fatigue risk: high"
        ]
        if factors:
            lines.append(f"✅ Why: {' · '.join(factors[:3])}")
        if risks:
            lines.append(f"⚠️ Risks: {' · '.join(risks[:2])}")

        grade = m.get("prediction_grade", "")
        if grade:
            lines.append(f"🏅 Grade: {grade}")

        lines.append("")

    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"📈 Top signals today: {total_signals}/{_TOP_N}")
    lines.append("🏅 Only Grade A picks · ranked by own model")
    lines.append("ℹ️ EV = expected value (positive = edge vs. market odds)")
    lines.append("⚠️ Bet responsibly")
    return "\n".join(lines)


# Keep in sync with email_notifier._MANIFEST_FIELDS so that check_results.py
# can evaluate matches from either channel with the same logic.
_MANIFEST_FIELDS = [
    "match_url", "match_date", "match_time", "sport", "league",
    "home_team", "away_team", "home_odds", "draw_odds", "away_odds",
    "win_rate", "h2h_count", "home_wins_in_h2h_last5", "away_wins_in_h2h_last5",
    "form_advantage", "forebet_prediction", "forebet_probability",
    "gemini_prediction", "gemini_recommendation", "gemini_confidence",
    "scoring_pick", "scoring_prob", "scoring_ev", "scoring_edge",
    "qualifies", "focus_team",
    # Tennis-specific: favorite drives _predicted_winner in check_results
    "favorite",
    "prediction_grade",
]


def _save_telegram_manifest(
    qual: List[Dict[str, Any]],
    date: str,
) -> None:
    """Save a JSON manifest of matches sent to Telegram (for follow-up report).

    The payload mirrors the e-mail manifest: the top level is a dict with
    metadata plus a ``matches`` list that contains every field check_results.py
    needs to grade the pick (``match_url``, odds, ``focus_team``, ``favorite``
    for tennis, etc.). Stored under ``outputs/telegram_manifest_{date}.json``.
    """
    import math as _math
    import os as _os
    import json as _json

    records: List[Dict[str, Any]] = []
    for m in qual:
        rec: Dict[str, Any] = {}
        for field in _MANIFEST_FIELDS:
            val = m.get(field)
            if isinstance(val, float):
                try:
                    if _math.isnan(val):
                        val = None
                except (TypeError, ValueError):
                    pass
            rec[field] = val
        records.append(rec)

    manifest: Dict[str, Any] = {
        "date": date,
        "sent_at": datetime.now(_WARSAW_TZ).isoformat(),
        "count": len(records),
        "matches": records,
    }

    out_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "outputs")
    _os.makedirs(out_dir, exist_ok=True)
    path = _os.path.join(out_dir, f"telegram_manifest_{date}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(manifest, f, ensure_ascii=False, indent=2, default=str)
        print(f"📋 Telegram manifest saved: {path} ({len(qual)} matches)")
    except OSError as exc:
        print(f"⚠️  Cannot save telegram manifest: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_telegram_summary(
    rows: List[Dict[str, Any]],
    qualifying_count: int,
    date: str,
    *,
    token: str = "",
    chat_id: str = "",
) -> bool:
    """
    Send a daily qualifying-match summary to Telegram (Grade A only, top 10).

    Returns True on success, False on any error (never raises).
    Silently skips when TELEGRAM_ENABLED is not 'true', credentials
    are missing, or there are no Grade A qualifying matches.
    
    Behavior:
    - Filters to prediction_grade == 'A' only
    - Ranks by own model (scoring_confidence) with tie-breaking on EV/odds
    - Caps at top 10 picks across all sports (single global leaderboard)
    """
    if not _ENABLED:
        print("ℹ️  Telegram: disabled (TELEGRAM_ENABLED != true)")
        return False

    now_warsaw = datetime.now(_WARSAW_TZ).replace(tzinfo=None)
    qual = _get_qualifying_rows(rows, now_warsaw)
    if not qual:
        print("ℹ️  Telegram: no qualifying matches — skipping summary")
        return False

    # Only send Grade A picks on Telegram (top 10 globally, ranked by own model)
    premium = [r for r in qual if (r.get("prediction_grade") or "F") in _PREMIUM_GRADES]
    rest_count = len(qual) - len(premium)
    print(f"📊 Telegram tier split: {len(premium)} Grade A, {rest_count} other (hidden)")

    if not premium:
        print("ℹ️  Telegram: no Grade A picks today — skipping summary")
        return False
    
    # Limit to top 10 by own model with tie-break (matches what _build_summary shows)
    premium = _rank_picks_with_tiebreak(premium, top_n=_TOP_N)
    print(f"   📌 Capped to top {len(premium)}/{_TOP_N} by model confidence")

    text = _build_summary(rows, qualifying_count, date, _now=now_warsaw)
    ok = _send_message(text, token=token, chat_id=chat_id)
    if ok:
        _save_telegram_manifest(premium, date)
    return ok
