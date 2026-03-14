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
import urllib.request
import urllib.error
import json
from datetime import datetime
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

_API_BASE = "https://api.telegram.org/bot{token}"
_MAX_MSG_LEN = 4096
_TIMEOUT = 15  # seconds


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
) -> str:
    """Build an HTML-formatted daily summary for Telegram."""
    lines: list[str] = []

    lines.append(f"<b>📊 Podsumowanie — {date}</b>")
    lines.append(f"Meczów: {len(rows)} | Kwalifikujących: {qualifying_count}")
    lines.append("")

    # Gather qualifying rows
    qual = [r for r in rows if r.get("qualifies")]

    # Group by sport
    sports: Dict[str, List[Dict[str, Any]]] = {}
    for r in qual:
        sp = r.get("sport", "football")
        sports.setdefault(sp, []).append(r)

    for sport, matches in sports.items():
        emoji = _sport_emoji(sport)
        lines.append(f"{emoji} <b>{sport.upper()}</b> ({len(matches)})")

        # Sort by composite confidence / scoring confidence descending
        matches.sort(
            key=lambda m: (
                m.get("ai_composite_confidence", 0)
                or m.get("scoring_confidence", 0)
                or 0
            ),
            reverse=True,
        )

        for m in matches[:10]:  # cap per sport
            home = m.get("home_team", "?")
            away = m.get("away_team", "?")
            pick = m.get("scoring_pick", m.get("forebet_prediction", ""))
            conf = m.get("ai_composite_confidence", m.get("scoring_confidence", 0))
            ho = m.get("home_odds", "")
            ao = m.get("away_odds", "")

            odds_str = ""
            if ho and ao:
                try:
                    odds_str = f" | {float(ho):.2f}/{float(ao):.2f}"
                except (ValueError, TypeError):
                    pass

            conf_str = f" ({conf:.0f}%)" if conf else ""
            pick_str = f" → <b>{pick}</b>" if pick else ""

            lines.append(f"  • {home} vs {away}{pick_str}{conf_str}{odds_str}")

        lines.append("")

    if not qual:
        lines.append("Brak kwalifikujących się meczów.")
        lines.append("")

    lines.append(f"<i>BigOne • {datetime.now().strftime('%H:%M')}</i>")
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
