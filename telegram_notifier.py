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
}
_SPORT_MIN_ODDS_FALLBACK = 1.35

# SofaScore fan vote thresholds (dominant vote %)
_FAN_VOTE_THRESHOLDS: Dict[str, float] = {"football": 65.0}
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


def _pick_odds(match: Dict[str, Any]) -> str:
    """Return formatted odds value for the recommended pick, or ''."""
    pick = (match.get("scoring_pick") or match.get("forebet_prediction") or "").strip().upper()
    ho = match.get("home_odds")
    ao = match.get("away_odds")
    do = match.get("draw_odds")
    odds_val = None
    if pick in ("1", "H", "1X"):
        odds_val = ho
    elif pick in ("2", "A", "X2"):
        odds_val = ao
    elif pick == "X" and do:
        odds_val = do
    elif ho:
        odds_val = ho
    if odds_val:
        try:
            return f"{float(odds_val):.2f}"
        except (ValueError, TypeError):
            pass
    return ""


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
    }.get(sport, "🏅")


def _build_summary(
    rows: List[Dict[str, Any]],
    qualifying_count: int,
    date: str,
    *,
    _now: datetime | None = None,
) -> str:
    """Build FormRadar-style daily summary for Telegram."""
    now_warsaw = _now or datetime.now(_WARSAW_TZ).replace(tzinfo=None)

    lines: list[str] = []

    # Header — date in DD.MM.YYYY
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        date_display = d.strftime("%d.%m.%Y")
    except ValueError:
        date_display = date

    lines.append(f"🟢 <b>FormRadar</b> | {date_display}")
    lines.append("")

    # Filter pipeline
    qual = [r for r in rows if r.get("qualifies")]
    qual = [r for r in qual if _passes_odds_filter(r.get("sport", "football"), r.get("home_odds"), r.get("away_odds"))]
    qual = [r for r in qual if _passes_fan_vote_filter(r.get("sport", "football"), r)]
    qual = [r for r in qual if _is_future_match(r, now_warsaw)]

    # Group by sport
    sports: Dict[str, List[Dict[str, Any]]] = {}
    for r in qual:
        sp = r.get("sport", "football")
        sports.setdefault(sp, []).append(r)

    total_signals = 0

    for sport, matches in sports.items():
        emoji = _sport_emoji(sport)
        lines.append(f"{emoji} <b>{sport.upper()}</b>")
        lines.append("━━━━━━━━━━━━━━━")

        # Sort by confidence descending
        matches.sort(
            key=lambda m: (
                m.get("ai_composite_confidence", 0)
                or m.get("scoring_confidence", 0)
                or 0
            ),
            reverse=True,
        )

        for m in matches[:10]:  # cap per sport
            total_signals += 1
            home = m.get("home_team", "?")
            away = m.get("away_team", "?")

            lines.append(f"🏠 {home} vs {away}")

            # Match time
            parsed_time = _parse_match_time(m.get("match_time"))
            if parsed_time:
                lines.append(f"🕐 {parsed_time.strftime('%H:%M')}")

            # Form advantage (confidence %)
            conf = m.get("ai_composite_confidence") or m.get("scoring_confidence") or 0
            try:
                conf_val = float(conf)
                if conf_val > 0:
                    lines.append(f"📊 Przewaga formy: {conf_val:.0f}%")
            except (ValueError, TypeError):
                pass

            # Odds for recommended pick
            odds_str = _pick_odds(m)
            if odds_str:
                lines.append(f"💰 Kurs: {odds_str}")

            # Premium extras — compact single line
            extras: list[str] = []
            ev = m.get("scoring_ev")
            try:
                if ev is not None and float(ev) > 0:
                    extras.append("💰VALUE")
            except (ValueError, TypeError):
                pass

            fb_pred = m.get("forebet_prediction", "")
            fb_prob = m.get("forebet_probability")
            if fb_pred and fb_prob:
                try:
                    extras.append(f"Forebet: {fb_pred} {float(fb_prob):.0f}%")
                except (ValueError, TypeError):
                    pass

            fv_probs = [m.get("sofascore_home_win_prob"), m.get("sofascore_draw_prob"), m.get("sofascore_away_win_prob")]
            fv_vals = [p for p in fv_probs if p is not None]
            if fv_vals:
                try:
                    extras.append(f"👥{max(float(p) for p in fv_vals):.0f}%")
                except (ValueError, TypeError):
                    pass

            if extras:
                lines.append(f"📌 {' | '.join(extras)}")

            lines.append("")  # blank line between matches

    if not qual:
        lines.append("Brak kwalifikujących się meczów.")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"📈 Sygnałów dziś: {total_signals}")
    lines.append("⚠️ Typuj odpowiedzialnie")
    return "\n".join(lines)


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
    Send a daily qualifying-match summary to Telegram.

    Returns True on success, False on any error (never raises).
    Silently skips when TELEGRAM_ENABLED is not 'true' or credentials
    are missing.
    """
    if not _ENABLED:
        print("ℹ️  Telegram: wyłączony (TELEGRAM_ENABLED != true)")
        return False

    text = _build_summary(rows, qualifying_count, date)
    return _send_message(text, token=token, chat_id=chat_id)
