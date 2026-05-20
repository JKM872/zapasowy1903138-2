"""
Dropping Odds Email Notifier
=============================

Sends an HTML email with all qualifying dropping-odds events for today.
Shows:
  - All matches in the odds range (1.35 - 2.20)
  - Form of both teams (overall + venue-specific)
  - How much the odds dropped (open → current, drop %)
  - Forebet prediction (if available)
  - SofaScore Fan Vote (if available)
  - Scoring engine pick + EV (if available)
  - Current odds from Livesport/Pinnacle

Designed to run after oddssafari_dropping_pipeline.py in GitHub Actions.
"""

from __future__ import annotations

import json
import math
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _format_form(form_list: Any) -> str:
    """Convert form list ['W','L','D'] to emoji string."""
    if not form_list:
        return "—"
    if isinstance(form_list, str):
        import ast
        try:
            form_list = ast.literal_eval(form_list)
        except (ValueError, SyntaxError):
            # Try splitting
            form_list = [c for c in form_list if c.upper() in "WDL"]
    if not isinstance(form_list, list):
        return "—"
    
    icons = {"W": "W✅", "D": "D🟡", "L": "L❌"}
    return " ".join(icons.get(str(r).upper()[:1], str(r)) for r in form_list[:5])


def _pick_form(enrichment: Dict[str, Any], side: str) -> List[Any]:
    """Pick the best available form list for the given side ('home' or 'away').

    Tries multiple field names because livesport_h2h_scraper writes the form
    under different keys depending on the path it took (full advanced form,
    fallback, tennis-specific). Returns the first non-empty list it finds.
    """
    candidates = (
        f"{side}_form",
        f"{side}_form_overall",
        f"{side}_form_home" if side == "home" else f"{side}_form_away",
    )
    for key in candidates:
        val = enrichment.get(key)
        if val:
            if isinstance(val, str):
                # CSV round-trip leaves this as a stringified list
                import ast
                try:
                    parsed = ast.literal_eval(val)
                    if parsed:
                        return parsed
                except (ValueError, SyntaxError):
                    continue
            elif isinstance(val, list) and len(val) > 0:
                return val
    return []


def _passes_recent_form_filter(
    event: Dict[str, Any],
    min_wins: int = 1,
    window: int = 3,
) -> tuple:
    """Dropping-odds-specific qualification: the focused team must have
    at least `min_wins` wins in their last `window` form matches.
    
    Rules:
    - If form data is missing → auto-qualify (don't penalize scraper gaps)
    - If no H2H data → auto-qualify (dropping odds doesn't require H2H)
    - Focus team must have at least 1 win in last 3 matches
    
    Returns (passes, reason).
    """
    enrichment = event.get("enrichment") or {}
    focus = event.get("focus_team") or "home"
    
    # No enrichment at all (resolve_failed) → pass through
    # We still want to show these in the email with whatever OddsSafari data we have
    if not enrichment:
        return True, "no_enrichment_passthrough"
    
    # Pick the form for the focused side
    if focus == "away":
        form = _pick_form(enrichment, "away")
    else:
        form = _pick_form(enrichment, "home")
    
    if not form:
        # No form data available → auto-qualify (don't penalize)
        return True, "no_form_data_passthrough"
    
    # Normalize to first letters W/D/L
    recent = []
    for r in list(form)[:window]:
        s = str(r).strip().upper()[:1]
        if s in ("W", "D", "L"):
            recent.append(s)
    
    if not recent:
        return True, "no_form_data_passthrough"
    
    wins = sum(1 for r in recent if r == "W")
    if wins >= min_wins:
        return True, None
    return False, f"only_{wins}_wins_in_last_{len(recent)}"


def _outcome_label(outcome: str) -> str:
    """Human-readable outcome label."""
    labels = {"1": "Gospodarze (1)", "2": "Goście (2)", "X": "Remis (X)"}
    return labels.get(str(outcome).strip(), str(outcome))


def _drop_badge_color(drop_pct: float) -> str:
    """Color for the drop percentage badge."""
    if drop_pct >= 15:
        return "#d32f2f"  # dark red - big drop
    if drop_pct >= 10:
        return "#f44336"  # red
    if drop_pct >= 5:
        return "#ff9800"  # orange
    return "#4caf50"  # green - small drop


# ---------------------------------------------------------------------------
# Scoring engine integration
# ---------------------------------------------------------------------------

def _run_scoring_engine(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run FootballScoringEngine on enriched event data. Returns scored dict or None."""
    try:
        from football_scoring_engine import FootballScoringEngine
        engine = FootballScoringEngine()
        
        enrichment = event.get("enrichment") or {}
        match_data = {
            "home_team": event.get("home_team", ""),
            "away_team": event.get("away_team", ""),
            "sport": event.get("sport", "football"),
            "focus_team": event.get("focus_team", "home"),
            "home_form": enrichment.get("home_form", []),
            "away_form": enrichment.get("away_form", []),
            "home_odds": enrichment.get("home_odds"),
            "draw_odds": enrichment.get("draw_odds"),
            "away_odds": enrichment.get("away_odds"),
            "forebet_prediction": enrichment.get("forebet_prediction"),
            "forebet_probability": enrichment.get("forebet_probability"),
            "sofascore_home_win_prob": enrichment.get("sofascore_home_win_prob"),
            "sofascore_draw_prob": enrichment.get("sofascore_draw_prob"),
            "sofascore_away_win_prob": enrichment.get("sofascore_away_win_prob"),
            "h2h_count": enrichment.get("h2h_count", 0),
            "win_rate": enrichment.get("win_rate", 0),
        }
        
        scored = engine.score_match(match_data)
        return scored.to_dict()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

def _build_match_card(event: Dict[str, Any], index: int) -> str:
    """Build one match card HTML block."""
    home = event.get("home_team", "?")
    away = event.get("away_team", "?")
    league = event.get("league", "")
    sport = event.get("sport", "football")
    outcome = event.get("dropped_outcome") or event.get("outcome", "")
    
    open_odds = _safe_float(event.get("open_odds"))
    current_odds = _safe_float(event.get("current_odds"))
    drop_pct = _safe_float(event.get("drop_pct"))
    
    # Calculate drop if not provided
    if drop_pct == 0 and open_odds > 0 and current_odds > 0:
        drop_pct = ((open_odds - current_odds) / open_odds) * 100
    
    enrichment = event.get("enrichment") or {}
    enrichment_status = event.get("enrichment_status", "")
    
    # Form data — try multiple field names so we always show something
    home_form = _pick_form(enrichment, "home")
    away_form = _pick_form(enrichment, "away")
    home_form_venue = enrichment.get("home_form_home") or []
    away_form_venue = enrichment.get("away_form_away") or []
    
    # Odds from Livesport
    home_odds = _safe_float(enrichment.get("home_odds"))
    draw_odds = _safe_float(enrichment.get("draw_odds"))
    away_odds = _safe_float(enrichment.get("away_odds"))
    
    # Forebet
    fb_pred = enrichment.get("forebet_prediction")
    fb_prob = _safe_float(enrichment.get("forebet_probability"))
    fb_ou = enrichment.get("forebet_over_under")
    fb_btts = enrichment.get("forebet_btts")
    
    # SofaScore
    ss_home = enrichment.get("sofascore_home_win_prob")
    ss_draw = enrichment.get("sofascore_draw_prob")
    ss_away = enrichment.get("sofascore_away_win_prob")
    ss_votes = enrichment.get("sofascore_total_votes")
    
    # H2H
    h2h_count = enrichment.get("h2h_count", 0)
    win_rate = _safe_float(enrichment.get("win_rate"))
    
    # Scoring engine
    scoring = event.get("scoring")
    
    # Event time
    event_time = event.get("event_time", "")
    
    # Drop badge
    drop_color = _drop_badge_color(drop_pct)
    
    html = f'''
    <div style="background: #ffffff; border-radius: 12px; margin: 16px 0; padding: 0; box-shadow: 0 2px 12px rgba(0,0,0,0.08); overflow: hidden; border-left: 4px solid {drop_color};">
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #1a237e 0%, #283593 100%); padding: 14px 18px; color: white;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="font-size: 11px; color: rgba(255,255,255,0.7);">#{index} | {league}</span>
                    <div style="font-size: 18px; font-weight: 700; margin-top: 4px;">{home} vs {away}</div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 11px; color: rgba(255,255,255,0.7);">{event_time or ""}</div>
                    <div style="background: {drop_color}; padding: 4px 10px; border-radius: 12px; font-size: 13px; font-weight: 700; margin-top: 4px;">
                        ↓ {drop_pct:.1f}%
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Body -->
        <div style="padding: 16px 18px;">
            <!-- Odds drop info -->
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding: 10px; background: #f5f5f5; border-radius: 8px;">
                <div>
                    <div style="font-size: 11px; color: #666;">Spadek kursu na: <strong>{_outcome_label(outcome)}</strong></div>
                    <div style="font-size: 15px; margin-top: 4px;">
                        <span style="color: #999; text-decoration: line-through;">{open_odds:.2f}</span>
                        <span style="margin: 0 8px;">→</span>
                        <span style="color: {drop_color}; font-weight: 700;">{current_odds:.2f}</span>
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 11px; color: #666;">Sport</div>
                    <div style="font-size: 13px; font-weight: 600;">{sport}</div>
                </div>
            </div>
    '''
    
    # Form section — always show, even with placeholders
    home_form_str = _format_form(home_form)
    away_form_str = _format_form(away_form)
    home_venue_str = _format_form(home_form_venue) if home_form_venue else None
    away_venue_str = _format_form(away_form_venue) if away_form_venue else None
    
    venue_html = ""
    if home_venue_str:
        venue_html += f'''
                <div style="margin-top: 4px; padding-left: 8px; border-left: 2px solid #ddd;">
                    <span style="font-size: 11px; color: #888;">u siebie:</span>
                    <span style="font-size: 12px;">{home_venue_str}</span>
                </div>
        '''
    if away_venue_str:
        venue_html += f'''
                <div style="margin-top: 4px; padding-left: 8px; border-left: 2px solid #ddd;">
                    <span style="font-size: 11px; color: #888;">na wyjeździe:</span>
                    <span style="font-size: 12px;">{away_venue_str}</span>
                </div>
        '''
    
    html += f'''
            <div style="margin-bottom: 14px; padding: 10px; background: #fafafa; border-radius: 8px;">
                <div style="font-size: 11px; color: #666; margin-bottom: 6px;">📊 Forma drużyn (ostatnie 5)</div>
                <div style="margin-bottom: 4px;">
                    <span style="font-size: 12px; color: #333; font-weight: 600;">{home}:</span>
                    <span style="font-size: 12px;">{home_form_str}</span>
                </div>
                <div>
                    <span style="font-size: 12px; color: #333; font-weight: 600;">{away}:</span>
                    <span style="font-size: 12px;">{away_form_str}</span>
                </div>
                {venue_html}
            </div>
    '''
    
    # H2H section
    if h2h_count and h2h_count > 0:
        last_date = enrichment.get("last_h2h_date") or ""
        last_score = enrichment.get("last_h2h_score") or ""
        last_home = enrichment.get("last_h2h_home") or ""
        last_away = enrichment.get("last_h2h_away") or ""
        last_line = ""
        if last_date or last_score:
            parts = []
            if last_home and last_away and last_score:
                parts.append(f"{last_home} {last_score} {last_away}")
            elif last_score:
                parts.append(last_score)
            if last_date:
                parts.append(f"({last_date})")
            last_line = f'<div style="font-size: 11px; color: #666; margin-top: 4px;">Ostatni mecz: {" ".join(parts)}</div>'
        html += f'''
            <div style="margin-bottom: 14px; padding: 10px; background: #e8f5e9; border-radius: 8px;">
                <div style="font-size: 11px; color: #666; margin-bottom: 4px;">⚔️ H2H (ostatnie {h2h_count} meczów)</div>
                <div style="font-size: 14px; font-weight: 600;">Win rate: {win_rate*100:.0f}%</div>
                {last_line}
            </div>
        '''
    
    # Livesport odds
    if home_odds > 0 or away_odds > 0:
        h_str = f"{home_odds:.2f}" if home_odds > 0 else "—"
        d_str = f"{draw_odds:.2f}" if draw_odds > 0 else "—"
        a_str = f"{away_odds:.2f}" if away_odds > 0 else "—"
        html += f'''
            <div style="margin-bottom: 14px; padding: 10px; background: #fff3e0; border-radius: 8px;">
                <div style="font-size: 11px; color: #666; margin-bottom: 6px;">💰 Kursy (Pinnacle)</div>
                <div style="display: flex; justify-content: space-around; text-align: center;">
                    <div><div style="font-size: 16px; font-weight: 700;">{h_str}</div><div style="font-size: 10px; color: #888;">1</div></div>
                    <div><div style="font-size: 16px; font-weight: 700;">{d_str}</div><div style="font-size: 10px; color: #888;">X</div></div>
                    <div><div style="font-size: 16px; font-weight: 700;">{a_str}</div><div style="font-size: 10px; color: #888;">2</div></div>
                </div>
            </div>
        '''
    
    # Forebet section
    if fb_pred and fb_prob > 0:
        extras = []
        if fb_ou:
            extras.append(f"O/U: {fb_ou}")
        if fb_btts:
            extras.append(f"BTTS: {fb_btts}")
        extras_str = f' | <span style="color: #666;">{" | ".join(extras)}</span>' if extras else ""
        html += f'''
            <div style="margin-bottom: 14px; padding: 10px; background: linear-gradient(135deg, #FF9800, #FF5722); border-radius: 8px; color: white;">
                <div style="font-size: 11px; color: rgba(255,255,255,0.8);">🎯 Forebet</div>
                <div style="font-size: 16px; font-weight: 700; margin-top: 4px;">
                    {fb_pred} ({fb_prob:.0f}%){extras_str}
                </div>
            </div>
        '''
    
    # SofaScore Fan Vote
    if ss_home is not None or ss_away is not None:
        ss_h = _safe_float(ss_home)
        ss_d = _safe_float(ss_draw)
        ss_a = _safe_float(ss_away)
        votes_str = f" ({int(ss_votes)} głosów)" if ss_votes else ""
        html += f'''
            <div style="margin-bottom: 14px; padding: 10px; background: #e3f2fd; border-radius: 8px;">
                <div style="font-size: 11px; color: #666; margin-bottom: 6px;">🗳️ SofaScore Fan Vote{votes_str}</div>
                <div style="display: flex; justify-content: space-around; text-align: center;">
                    <div><div style="font-size: 14px; font-weight: 700; color: #1565c0;">{ss_h:.0f}%</div><div style="font-size: 10px;">1</div></div>
                    <div><div style="font-size: 14px; font-weight: 700; color: #666;">{ss_d:.0f}%</div><div style="font-size: 10px;">X</div></div>
                    <div><div style="font-size: 14px; font-weight: 700; color: #c62828;">{ss_a:.0f}%</div><div style="font-size: 10px;">2</div></div>
                </div>
            </div>
        '''
    
    # Scoring engine result
    if scoring:
        pick = scoring.get("best_pick", "")
        ev = _safe_float(scoring.get("ev"))
        edge = _safe_float(scoring.get("edge"))
        confidence = _safe_float(scoring.get("confidence"))
        prob_1 = _safe_float(scoring.get("prob_1")) * 100
        prob_x = _safe_float(scoring.get("prob_X")) * 100
        prob_2 = _safe_float(scoring.get("prob_2")) * 100
        
        ev_color = "#4caf50" if ev > 0 else "#f44336"
        html += f'''
            <div style="margin-bottom: 14px; padding: 10px; background: linear-gradient(135deg, #1b5e20 0%, #2e7d32 100%); border-radius: 8px; color: white;">
                <div style="font-size: 11px; color: rgba(255,255,255,0.7);">🧠 Algorytm (Scoring Engine)</div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                    <div>
                        <div style="font-size: 18px; font-weight: 700;">Pick: {pick}</div>
                        <div style="font-size: 11px; color: rgba(255,255,255,0.8);">P: {prob_1:.0f}% / {prob_x:.0f}% / {prob_2:.0f}%</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 14px; font-weight: 700; color: {"#ffd740" if ev > 0 else "#ff8a80"};">EV: {ev:+.3f}</div>
                        <div style="font-size: 11px; color: rgba(255,255,255,0.8);">Edge: {edge:+.1f}% | Conf: {confidence:.0f}</div>
                    </div>
                </div>
            </div>
        '''
    
    # No enrichment warning
    if enrichment_status and enrichment_status != "enriched":
        html += f'''
            <div style="padding: 8px 10px; background: #fff9c4; border-radius: 6px; font-size: 11px; color: #f57f17;">
                ⚠️ Brak pełnych danych ({enrichment_status})
            </div>
        '''
    
    html += '''
        </div>
    </div>
    '''
    return html


def _build_skipped_card(event: Dict[str, Any], index: int) -> str:
    """Compact card for events rejected by the recent-form filter."""
    home = event.get("home_team", "?")
    away = event.get("away_team", "?")
    league = event.get("league", "")
    outcome = event.get("dropped_outcome") or event.get("outcome", "")
    current_odds = _safe_float(event.get("current_odds"))
    drop_pct = _safe_float(event.get("drop_pct"))
    open_odds = _safe_float(event.get("open_odds"))
    if drop_pct == 0 and open_odds > 0 and current_odds > 0:
        drop_pct = ((open_odds - current_odds) / open_odds) * 100
    
    enrichment = event.get("enrichment") or {}
    home_form_str = _format_form(_pick_form(enrichment, "home"))
    away_form_str = _format_form(_pick_form(enrichment, "away"))
    
    skip_reason = event.get("recent_form_skip_reason", "")
    
    return f'''
    <div style="background: #ffffff; border-radius: 10px; padding: 12px 14px; margin: 8px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.05); opacity: 0.85; border-left: 3px solid #bdbdbd;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="flex: 1;">
                <div style="font-size: 10px; color: #999;">#{index} | {league}</div>
                <div style="font-size: 14px; font-weight: 600; color: #555;">{home} vs {away}</div>
                <div style="font-size: 11px; color: #777; margin-top: 4px;">
                    <span style="color: #333;">{home}:</span> {home_form_str}
                </div>
                <div style="font-size: 11px; color: #777;">
                    <span style="color: #333;">{away}:</span> {away_form_str}
                </div>
            </div>
            <div style="text-align: right; min-width: 90px;">
                <div style="font-size: 11px; color: #666;">{_outcome_label(outcome)}</div>
                <div style="font-size: 14px; font-weight: 700; color: #555;">{current_odds:.2f} <span style="font-size: 10px; color: #999;">↓{drop_pct:.0f}%</span></div>
                <div style="font-size: 9px; color: #aaa; margin-top: 2px;">{skip_reason}</div>
            </div>
        </div>
    </div>
    '''


def build_dropping_odds_email_html(
    events: List[Dict[str, Any]],
    meta: Dict[str, Any],
    date: str,
    sport: Optional[str] = None,
    skipped_events: Optional[List[Dict[str, Any]]] = None,
    total_events: Optional[int] = None,
) -> str:
    """Build the full HTML email body."""
    
    skipped_events = skipped_events or []
    if total_events is None:
        total_events = meta.get("totals", {}).get("events", len(events))
    qualified_count = len(events)
    skipped_count = len(skipped_events)
    min_odds = meta.get("filter", {}).get("min_odds", 1.35)
    max_odds = meta.get("filter", {}).get("max_odds", 2.20)
    
    sport_emoji = {
        "football": "⚽", "basketball": "🏀", "tennis": "🎾",
        "hockey": "🏒", "handball": "🤾", "volleyball": "🏐",
        "baseball": "⚾", "rugby": "🏉",
    }
    sport_label = ""
    if sport:
        emoji = sport_emoji.get(sport.lower(), "🏆")
        sport_label = f" {emoji} {sport.upper()}"
    
    # Sort by drop_pct descending (biggest drops first)
    events_sorted = sorted(events, key=lambda e: _safe_float(e.get("drop_pct")), reverse=True)
    skipped_sorted = sorted(skipped_events, key=lambda e: _safe_float(e.get("drop_pct")), reverse=True)
    
    # Build qualifying match cards
    cards_html = ""
    for i, event in enumerate(events_sorted, 1):
        cards_html += _build_match_card(event, i)
    
    # If empty, show a friendly placeholder
    if not events_sorted:
        cards_html = '''
        <div style="background: #fff3e0; border-radius: 12px; padding: 24px; text-align: center; margin: 16px 0;">
            <div style="font-size: 40px; margin-bottom: 12px;">😴</div>
            <div style="font-size: 16px; font-weight: 700; color: #e65100;">Brak okazji w tym sporcie dziś</div>
            <div style="font-size: 12px; color: #888; margin-top: 8px;">
                Pipeline przeszedł, ale żaden mecz nie spełnił wszystkich kryteriów
                (zakres kursów + min. 1 wygrana w ostatnich 3 meczach focus drużyny).
            </div>
        </div>
        '''
    
    # Build skipped section (matches that were qualified by the OddsSafari
    # filter but rejected by the recent-form filter — still useful to see)
    skipped_html = ""
    if skipped_sorted:
        skipped_cards = ""
        for i, event in enumerate(skipped_sorted, 1):
            skipped_cards += _build_skipped_card(event, i)
        skipped_html = f'''
        <div style="margin-top: 24px;">
            <div style="background: #fafafa; border-radius: 10px; padding: 12px 16px; margin-bottom: 12px;">
                <div style="font-size: 14px; font-weight: 700; color: #555;">
                    ⏭️ Odrzucone przez filtr formy ({len(skipped_sorted)})
                </div>
                <div style="font-size: 11px; color: #888; margin-top: 4px;">
                    Te mecze przeszły zakres kursów, ale focus drużyna nie wygrała żadnego z ostatnich 3 meczów.
                </div>
            </div>
            {skipped_cards}
        </div>
        '''
    
    now = datetime.now(WARSAW_TZ).strftime("%H:%M")
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background: #f0f2f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    <div style="max-width: 640px; margin: 0 auto; padding: 20px;">
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #0d47a1 0%, #1565c0 50%, #1976d2 100%); border-radius: 16px; padding: 24px; margin-bottom: 20px; text-align: center; color: white;">
            <div style="font-size: 28px; font-weight: 800; margin-bottom: 8px;">📉 Dropping Odds{sport_label}</div>
            <div style="font-size: 14px; color: rgba(255,255,255,0.85);">{date} | Wygenerowano o {now}</div>
            <div style="margin-top: 12px; display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
                <div style="background: rgba(255,255,255,0.15); padding: 8px 14px; border-radius: 8px;">
                    <div style="font-size: 22px; font-weight: 700;">{qualified_count}</div>
                    <div style="font-size: 10px; color: rgba(255,255,255,0.7);">Okazje</div>
                </div>
                <div style="background: rgba(255,255,255,0.15); padding: 8px 14px; border-radius: 8px;">
                    <div style="font-size: 22px; font-weight: 700;">{skipped_count}</div>
                    <div style="font-size: 10px; color: rgba(255,255,255,0.7);">Odrzucone (forma)</div>
                </div>
                <div style="background: rgba(255,255,255,0.15); padding: 8px 14px; border-radius: 8px;">
                    <div style="font-size: 22px; font-weight: 700;">{total_events}</div>
                    <div style="font-size: 10px; color: rgba(255,255,255,0.7);">Wszystkich</div>
                </div>
                <div style="background: rgba(255,255,255,0.15); padding: 8px 14px; border-radius: 8px;">
                    <div style="font-size: 22px; font-weight: 700;">{min_odds}-{max_odds}</div>
                    <div style="font-size: 10px; color: rgba(255,255,255,0.7);">Zakres</div>
                </div>
            </div>
        </div>
        
        <!-- Legend -->
        <div style="background: #ffffff; border-radius: 10px; padding: 12px 16px; margin-bottom: 16px; font-size: 11px; color: #666;">
            <strong>Legenda:</strong> 
            ↓% = spadek kursu od otwarcia | 
            W✅ = wygrana | D🟡 = remis | L❌ = przegrana |
            Sortowanie: od największego spadku
        </div>
        
        <!-- Match cards -->
        {cards_html}
        
        <!-- Skipped events -->
        {skipped_html}
        
        <!-- Footer -->
        <div style="text-align: center; padding: 20px; color: #999; font-size: 11px;">
            OddsSafari Dropping Odds Pipeline | Automatyczny email z GitHub Actions
        </div>
    </div>
</body>
</html>'''
    
    return html


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

SMTP_CONFIG = {
    "gmail": {"server": "smtp.gmail.com", "port": 587, "use_tls": True},
    "outlook": {"server": "smtp-mail.outlook.com", "port": 587, "use_tls": True},
    "yahoo": {"server": "smtp.mail.yahoo.com", "port": 587, "use_tls": True},
}


def send_dropping_odds_email(
    json_path: str,
    to_email: str,
    from_email: str,
    password: str,
    provider: str = "gmail",
    run_scoring: bool = True,
    sport: Optional[str] = None,
    send_empty: bool = True,
    min_recent_wins: int = 1,
    recent_window: int = 3,
) -> bool:
    """Load the pipeline JSON output and send the dropping odds email.
    
    Returns True on success, False on failure.
    """
    if not os.path.isfile(json_path):
        print(f"❌ Plik nie istnieje: {json_path}")
        # Not an error: per-sport job may have produced no JSON simply
        # because there were no rows in OddsSafari for that sport.
        return True
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    meta = data.get("meta", {})
    qualified_raw = data.get("qualified", [])
    all_events = data.get("events", [])
    
    # Apply additional dropping-odds-specific qualification:
    # the focused team (the one whose price dropped) must have at least
    # `min_recent_wins` wins in their last `recent_window` form matches.
    # Otherwise we still keep the event in the email but mark it as skipped.
    qualified: List[Dict[str, Any]] = []
    skipped_no_recent_win: List[Dict[str, Any]] = []
    for event in qualified_raw:
        passes, reason = _passes_recent_form_filter(event, min_recent_wins, recent_window)
        if passes:
            qualified.append(event)
        else:
            event["recent_form_skip_reason"] = reason
            skipped_no_recent_win.append(event)
    
    print(f"📊 Wynik filtru formy ({min_recent_wins}+ W w ostatnich {recent_window}):")
    print(f"   ✅ Przechodzą: {len(qualified)}")
    print(f"   ⏭️  Odrzucone (brak ostatniej wygranej): {len(skipped_no_recent_win)}")
    
    if not qualified and not skipped_no_recent_win:
        print("⚠️ Brak kwalifikujących się meczów dla tego sportu/dnia")
        if not send_empty:
            print("ℹ️  Pomijam wysyłkę email (--no-send-empty)")
            return True  # not an error, just nothing to send
        print("📧 Wysyłam pusty email statusowy...")
    
    # Run scoring engine on enriched events
    if run_scoring and qualified:
        scored_count = 0
        for event in qualified:
            if event.get("enrichment"):
                scoring_result = _run_scoring_engine(event)
                if scoring_result:
                    event["scoring"] = scoring_result
                    scored_count += 1
        print(f"   🧠 Scoring engine: {scored_count}/{len(qualified)} meczów ocenionych")
    
    # Build email
    date = meta.get("target_date", datetime.now(WARSAW_TZ).strftime("%Y-%m-%d"))
    html = build_dropping_odds_email_html(
        qualified, meta, date, sport=sport,
        skipped_events=skipped_no_recent_win,
        total_events=len(all_events),
    )
    
    sport_label = f" [{sport.upper()}]" if sport else ""
    min_odds = meta.get("filter", {}).get("min_odds", 1.35)
    max_odds = meta.get("filter", {}).get("max_odds", 2.20)
    if qualified:
        subject = f"📉 Dropping Odds{sport_label} — {date} | {len(qualified)} okazji ({min_odds}-{max_odds})"
    else:
        subject = f"📉 Dropping Odds{sport_label} — {date} | brak okazji (status)"
    
    # Send
    smtp_cfg = SMTP_CONFIG.get(provider, SMTP_CONFIG["gmail"])
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))
    
    try:
        server = smtplib.SMTP(smtp_cfg["server"], smtp_cfg["port"])
        server.ehlo()
        if smtp_cfg.get("use_tls"):
            server.starttls()
            server.ehlo()
        server.login(from_email, password)
        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        print(f"✅ Email wysłany do {to_email}")
        print(f"   Temat: {subject}")
        return True
    except Exception as e:
        print(f"❌ Błąd wysyłania email: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Send Dropping Odds email notification")
    parser.add_argument("json_path", help="Path to oddssafari_dropping_*.json output")
    parser.add_argument("--to", required=True, help="Recipient email")
    parser.add_argument("--from-email", required=True, help="Sender email")
    parser.add_argument("--password", required=True, help="Email password / app password")
    parser.add_argument("--provider", default="gmail", choices=["gmail", "outlook", "yahoo"])
    parser.add_argument("--no-scoring", action="store_true", help="Skip scoring engine")
    parser.add_argument("--sport", default=None, help="Sport label for the email subject/header")
    parser.add_argument("--send-empty", dest="send_empty", action="store_true", default=True,
                        help="Send a status email even when there are no qualifying matches (default)")
    parser.add_argument("--no-send-empty", dest="send_empty", action="store_false",
                        help="Skip sending email when there are no qualifying matches")
    parser.add_argument("--min-recent-wins", type=int, default=1,
                        help="Min wins in the last 3 form matches required for the focus team to qualify (default: 1).")
    parser.add_argument("--recent-window", type=int, default=3,
                        help="How many recent form matches to inspect for --min-recent-wins (default: 3).")
    
    args = parser.parse_args()
    
    success = send_dropping_odds_email(
        json_path=args.json_path,
        to_email=args.to,
        from_email=args.from_email,
        password=args.password,
        provider=args.provider,
        run_scoring=not args.no_scoring,
        sport=args.sport,
        send_empty=args.send_empty,
        min_recent_wins=args.min_recent_wins,
        recent_window=args.recent_window,
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
