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
    return {"win": "✅", "loss": "❌", "pending": "⏳"}.get(status, "❓")


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
    lines.append(f"📊 <b>FormRadar — Raport Skuteczności</b>")
    lines.append(f"📅 {date_display} (ostatnie 24h)")
    lines.append("")

    total = g.get("total", 0)

    if total == 0:
        lines.append("Brak typów w ostatnich 24 godzinach.")
        lines.append("")
        lines.append("⚠️ Typuj odpowiedzialnie")
        return "\n".join(lines)

    # ── Global KPIs ─────────────────────────────────────────
    win = g.get("win", 0)
    loss = g.get("loss", 0)
    pending = g.get("pending", 0)
    settled = g.get("settled", 0)
    win_rate = g.get("win_rate", 0.0)

    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"📋 <b>Podsumowanie</b>")
    lines.append(f"  Typów łącznie: <b>{total}</b>")
    lines.append(f"  ✅ Trafionych: <b>{win}</b>")
    lines.append(f"  ❌ Nietrafionych: <b>{loss}</b>")
    if pending:
        lines.append(f"  ⏳ Oczekujących: <b>{pending}</b>")
    lines.append("")
    if settled > 0:
        lines.append(f"  📈 Skuteczność (settled): <b>{win_rate:.1f}%</b> ({win}/{settled})")
    else:
        lines.append(f"  📈 Skuteczność: <i>brak rozliczonych</i>")
    lines.append("")

    # ── Per-sport breakdown ─────────────────────────────────
    if len(per_sport) > 1:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("📊 <b>Według sportu</b>")
        for sport in sorted(per_sport.keys()):
            sp = per_sport[sport]
            sp_settled = sp["win"] + sp["loss"]
            rate_str = f'{sp["win_rate"]:.0f}%' if sp_settled > 0 else "–"
            lines.append(
                f"  {_emoji(sport)} {sport.capitalize()}: "
                f'{sp["win"]}✅ {sp["loss"]}❌ '
                + (f'{sp["pending"]}⏳ ' if sp["pending"] else "")
                + f"| {rate_str}"
            )
        lines.append("")

    # ── Match-by-match list ─────────────────────────────────
    settled_matches = [m for m in matches if m["status"] != "pending"]
    pending_matches = [m for m in matches if m["status"] == "pending"]

    if settled_matches:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("🏟 <b>Rozliczone mecze</b>")
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
        lines.append("⏳ <b>Oczekujące</b>")
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
    lines.append("⚠️ Typuj odpowiedzialnie")

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
    Silently skips when TELEGRAM_ENABLED is not 'true'.
    """
    if not _ENABLED:
        print("ℹ️  Telegram Results: wyłączony (TELEGRAM_ENABLED != true)")
        return False

    text = build_daily_results_summary(stats, report_date)
    return _send_message(text, token=token, chat_id=chat_id)
