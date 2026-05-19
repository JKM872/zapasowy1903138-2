"""
Telegram Results Report — daily accuracy summary
==================================================

Builds and sends a daily Telegram message showing how many tips
(qualifying predictions) hit vs missed in the last 24 hours.

Uses the same Bot API transport as telegram_notifier.py.

Configuration (env vars):
    TELEGRAM_BOT_TOKEN  — Bot API token from @BotFather
    TELEGRAM_CHAT_ID    — Target chat / user ID
    TELEGRAM_ENABLED    — "true" to enable sending (default: "false")
"""

from __future__ import annotations

import os
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------------
# Config (shared with telegram_notifier)
# ---------------------------------------------------------------------------

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

_API_BASE = "https://api.telegram.org/bot{token}"
_MAX_MSG_LEN = 4096
_TIMEOUT = 15

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


# ---------------------------------------------------------------------------
# Sport helpers
# ---------------------------------------------------------------------------

_SPORT_EMOJI: Dict[str, str] = {
    "football": "⚽",
    "basketball": "🏀",
    "volleyball": "🏐",
    "handball": "🤾",
    "hockey": "🏒",
    "tennis": "🎾",
}


def _emoji(sport: str) -> str:
    return _SPORT_EMOJI.get(sport, "🏅")


def _status_icon(status: str) -> str:
    return {"win": "✅", "loss": "❌", "push": "↩", "pending": "⏳"}.get(status, "❓")


# ---------------------------------------------------------------------------
# Low-level sender (mirrors telegram_notifier._send_message)
# ---------------------------------------------------------------------------

def _send_message(text: str, token: str = "", chat_id: str = "") -> bool:
    tok = token or _BOT_TOKEN
    cid = chat_id or _CHAT_ID
    if not tok or not cid:
        print("⚠️  Telegram Results: brak TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID")
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
                    print("✅ Telegram Results: wiadomość wysłana.")
                    return True
                print(f"⚠️  Telegram Results: HTTP {resp.status}")
                return False
        except urllib.error.HTTPError as exc:
            print(f"⚠️  Telegram Results: HTTP {exc.code} — {exc.reason}")
            return False
        except (urllib.error.URLError, OSError) as exc:
            if attempt == 0:
                print(f"⚠️  Telegram Results: retry po błędzie — {exc}")
                continue
            print(f"❌ Telegram Results: błąd połączenia — {exc}")
            return False
    return False


# ---------------------------------------------------------------------------
# Send-worthiness check
# ---------------------------------------------------------------------------

def _has_settled_matches(stats: Dict[str, Any]) -> bool:
    """True when at least one match has been settled (win, loss, or push)."""
    g = stats.get("global", {})
    if int(g.get("settled", 0) or 0) > 0:
        return True
    matches = stats.get("matches", [])
    return any(m.get("status") in {"win", "loss", "push"} for m in matches)


def should_send_daily_results_summary(stats: Dict[str, Any]) -> bool:
    """Return True only when there are tips AND at least one is settled."""
    g = stats.get("global", {})
    total = int(g.get("total", 0) or 0)
    return total > 0 and _has_settled_matches(stats)


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_daily_results_summary(
    stats: Dict[str, Any],
    report_date: str | None = None,
) -> str:
    """
    Build a human-readable Telegram message from stats returned by
    SupabaseManager.get_telegram_daily_stats().

    Sections:
      1. Header with date
      2. Global KPIs (total / win / loss / pending / win_rate)
      3. Per-sport breakdown
      4. Match-by-match results (settled first, then pending)
      5. Footer
    """
    now = datetime.now(_WARSAW_TZ)
    if report_date:
        try:
            d = datetime.strptime(report_date, "%Y-%m-%d")
            date_display = d.strftime("%d.%m.%Y")
        except ValueError:
            date_display = report_date
    else:
        date_display = now.strftime("%d.%m.%Y")

    g = stats.get("global", {})
    per_sport = stats.get("per_sport", {})
    matches = stats.get("matches", [])

    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────
    lines.append(f"📊 <b>FormRadar — Daily Results</b>")
    lines.append(f"📅 {date_display}")
    lines.append("🏅 Grade A · Draw No Bet")
    lines.append("")

    total = g.get("total", 0)

    if total == 0:
        lines.append("No Grade A picks were sent today.")
        lines.append("")
        lines.append("⚠️ Bet responsibly")
        return "\n".join(lines)

    # ── Global KPIs ─────────────────────────────────────────
    win = g.get("win", 0)
    loss = g.get("loss", 0)
    push = g.get("push", 0)
    pending = g.get("pending", 0)
    settled = g.get("settled", 0)
    win_rate = g.get("win_rate", 0.0)

    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"📋 <b>Summary</b>")
    lines.append(f"  Total tips: <b>{total}</b>")
    lines.append(f"  ✅ Won: <b>{win}</b>")
    lines.append(f"  ❌ Lost: <b>{loss}</b>")
    if push:
        lines.append(f"  ↩ Push (DNB / draw): <b>{push}</b>")
    if pending:
        lines.append(f"  ⏳ Pending: <b>{pending}</b>")
    lines.append("")
    decided = win + loss
    if decided > 0:
        lines.append(f"  📈 Win rate (DNB): <b>{win_rate:.1f}%</b> ({win}/{decided})")
    elif push > 0:
        lines.append(f"  📈 Win rate: <i>only pushes so far</i>")
    else:
        lines.append(f"  📈 Win rate: <i>no settled picks yet</i>")
    lines.append("")

    # ── Per-sport breakdown ─────────────────────────────────
    if len(per_sport) > 1:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("📊 <b>By sport</b>")
        for sport in sorted(per_sport.keys()):
            sp = per_sport[sport]
            sp_decided = sp.get("win", 0) + sp.get("loss", 0)
            rate_str = f'{sp.get("win_rate", 0.0):.0f}%' if sp_decided > 0 else "–"
            push_str = f' {sp.get("push", 0)}↩' if sp.get("push") else ""
            pending_str = f' {sp.get("pending", 0)}⏳' if sp.get("pending") else ""
            lines.append(
                f"  {_emoji(sport)} {sport.capitalize()}: "
                f'{sp.get("win", 0)}✅ {sp.get("loss", 0)}❌'
                f'{push_str}{pending_str} | {rate_str}'
            )
        lines.append("")

    # ── Match-by-match list ─────────────────────────────────
    settled_matches = [m for m in matches if m["status"] != "pending"]
    pending_matches = [m for m in matches if m["status"] == "pending"]

    if settled_matches:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("🏟 <b>Settled matches</b>")
        for m in settled_matches[:15]:
            icon = _status_icon(m["status"])
            score = ""
            if m.get("home_score") is not None and m.get("away_score") is not None:
                score = f' ({m["home_score"]}:{m["away_score"]})'
            pick_str = f' [{m["pick"]}]' if m.get("pick") else ""
            odds_str = f' @{m["odds"]:.2f}' if m.get("odds") else ""
            lines.append(
                f"  {icon} {m['home_team']} vs {m['away_team']}"
                f"{score}{pick_str}{odds_str}"
            )
        lines.append("")

    if pending_matches:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("⏳ <b>Pending</b>")
        for m in pending_matches[:10]:
            pick_str = f' [{m["pick"]}]' if m.get("pick") else ""
            odds_str = f' @{m["odds"]:.2f}' if m.get("odds") else ""
            time_str = f' 🕐{m["match_time"]}' if m.get("match_time") else ""
            lines.append(
                f"  ⏳ {m['home_team']} vs {m['away_team']}"
                f"{time_str}{pick_str}{odds_str}"
            )
        lines.append("")

    # ── Footer ──────────────────────────────────────────────
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("ℹ️ DNB = Draw No Bet · push = stake refunded on draw")
    lines.append("⚠️ Bet responsibly")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_daily_results_summary(
    stats: Dict[str, Any],
    report_date: str | None = None,
    *,
    token: str = "",
    chat_id: str = "",
) -> bool:
    """
    Build and send the daily results summary to Telegram.

    Returns True on success, False on any error (never raises).
    Silently skips when TELEGRAM_ENABLED is not 'true' or there are
    no settled matches.
    """
    if not _ENABLED:
        print("ℹ️  Telegram Results: disabled (TELEGRAM_ENABLED != true)")
        return False

    if not should_send_daily_results_summary(stats):
        print("ℹ️  Telegram Results: no settled matches yet — skipping report")
        return False

    text = build_daily_results_summary(stats, report_date)
    return _send_message(text, token=token, chat_id=chat_id)
