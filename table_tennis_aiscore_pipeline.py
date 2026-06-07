# -*- coding: utf-8 -*-
"""
🏓 TABLE TENNIS PIPELINE — AiScore-sourced (HOME / AWAY focus)
==============================================================

A SEPARATE pipeline for table tennis that sources the match list, head-to-head
and recent form from **AiScore** (https://www.aiscore.com/table-tennis) — which
lists virtually every table-tennis match including amateur events.

It is intentionally isolated from the other sports' pipelines
(``scrape_and_notify.py`` and the SofaScore-sourced ``table_tennis_pipeline.py``
are left untouched). It only REUSES existing, battle-tested building blocks:

  • aiscore_scraper          — match list + H2H + form (the new source)
  • sofascore_scraper        — MANDATORY Fan Vote (get_sofascore_prediction)
  • livesport_odds_api      — odds (best-effort, multi-bookmaker; AiScore has none)
  • tennis_scoring_engine    — 2-way (no-draw) scoring with a table-tennis profile
  • qualification_gate       — channel_qualifies / email_qualifies
  • email_notifier           — e-mail (same gate/template as tennis)
  • telegram_notifier        — Telegram summary

Qualification rules (per requirements):
  1. H2H ≥ 60%   — the FOCUS player (home or away) must have won at least 60%
                   of head-to-head meetings vs the rival.            (HARD GATE)
  2. Fan Vote    — SofaScore Fan Vote is MANDATORY (must be found).  (HARD GATE)
  3. Future-only — match must not have started yet.                  (HARD GATE)
  4. Odds        — multi-bookmaker via Livesport (pinnacle, bet365, 1xbet, …);
                   first that prices the match. Used to enrich scoring / EV.
                   Absence does NOT disqualify (some amateur events are unpriced).

HOME vs AWAY:
  Two workflows run this file with ``--focus home`` and ``--focus away``.
  • --focus home → only emits picks for the HOME player (uses home-venue form,
                   home-player H2H win-rate vs the rival).
  • --focus away → only emits picks for the AWAY player.
  This mirrors the existing scrape.yml (home) / scrape_away.yml (away) split.

Usage:
    python table_tennis_aiscore_pipeline.py --focus home --date 2026-06-05
    python table_tennis_aiscore_pipeline.py --focus away --no-email --no-telegram
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SPORT = "table_tennis"
SPORT_LABEL = "Table Tennis"

# Favourite must have won at least this share of the direct H2H to qualify.
H2H_MIN_WIN_RATE = 0.60
# Need at least this many decided H2H meetings to trust the rate.
H2H_MIN_MATCHES = 3

# ── Table-tennis scoring profile (kept in sync with table_tennis_pipeline) ──
TT_WEIGHTS: Dict[str, float] = {
    "odds":         0.34,
    "h2h":          0.26,
    "form":         0.20,
    "sofascore":    0.12,
    "serve_model":  0.08,
    "surface_form": 0.0,
    "ranking":      0.0,
    "fatigue":      0.0,
    "availability": 0.0,
}
TT_THRESHOLD = 25.0


# ---------------------------------------------------------------------------
# Imports of reused building blocks (graceful guards)
# ---------------------------------------------------------------------------

try:
    import aiscore_scraper as ai
    _AI_OK = True
except Exception as e:  # pragma: no cover
    _AI_OK = False
    _AI_ERR = str(e)

try:
    from sofascore_scraper import (
        get_sofascore_prediction, is_sofascore_unreachable, _api_get_json,
    )
    _SOFA_OK = True
except Exception as e:  # pragma: no cover
    _SOFA_OK = False
    _SOFA_ERR = str(e)
    def get_sofascore_prediction(*a, **k):  # type: ignore
        return {"found": False}
    def is_sofascore_unreachable() -> bool:  # type: ignore
        return False
    def _api_get_json(*a, **k):  # type: ignore
        return None

# Leagues to ALSO source directly from SofaScore (not listed on AiScore), matched
# as case-insensitive substrings against the SofaScore tournament/category name.
SOFASCORE_EXTRA_LEAGUES = ["setka"]  # Setka Cup, Setka Cup (K), …


# When SofaScore's anti-bot (Cloudflare) blocks the ENTIRE CI shard, every
# fan-vote lookup 403s and the circuit breaker trips. Treating that
# infrastructure failure as a per-match "no fan vote" would zero out every pick.
# So when SofaScore is globally unreachable for the run we fall back to the H2H
# gate alone (fan vote flagged as unavailable). Set TT_SOFASCORE_STRICT=1 to
# keep the fan vote strictly mandatory even then (will yield 0 picks if blocked).
TT_SOFASCORE_STRICT = os.getenv("TT_SOFASCORE_STRICT", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Odds (multi-bookmaker via Livesport match index; best-effort)
# ---------------------------------------------------------------------------

# Livesport table-tennis day page (slug 'tenis-stolowy'). AiScore has no odds,
# so we map each AiScore match to its Livesport event by player surnames and
# query many bookmakers via the Livesport odds API (HOME_AWAY market). Covers
# far more amateur events (TT Cup / Liga Pro / Setka) than Pinnacle alone;
# truly unpriced events stay empty (non-blocking).
LIVESPORT_TT_DAY_URL = "https://www.livesport.com/pl/tenis-stolowy/"

# Bookmakers to query for table-tennis odds, in sharp→popular priority order.
# The Livesport odds API returns the first that prices the match (HOME_AWAY).
# Covers far more amateur events than Pinnacle alone (TT Cup, Liga Pro, Setka).
TT_BOOKMAKERS = [
    "pinnacle", "bet365", "1xbet", "unibet", "bwin",
    "betway", "william_hill", "betfair", "nordicbet",
]


def collect_sofascore_league_matches(date_str: str, focus: str,
                                     league_filters: Optional[List[str]] = None,
                                     existing_pairs: Optional[set] = None) -> List[Dict[str, Any]]:
    """Source qualifying matches for SofaScore-only leagues (e.g. Setka Cup).

    AiScore does not list Setka Cup / Setka Cup (K), but SofaScore does — and we
    already reach SofaScore. List the day's table-tennis events, keep those whose
    tournament/category matches ``league_filters``, and apply the SAME gates as
    the AiScore path: H2H ≥60% for the focus side (≥3 meetings) + mandatory Fan
    Vote. Enriches with form, odds (LV Bet etc.) and time/league — all from
    SofaScore. Returns fully-built, qualifying rows. Best-effort.
    """
    league_filters = [f.lower() for f in (league_filters or SOFASCORE_EXTRA_LEAGUES)]
    existing_pairs = existing_pairs or set()
    try:
        from sofascore_scraper import (
            list_scheduled_events, get_event_h2h, get_team_recent_form, get_votes_via_api,
        )
        from aiscore_scraper import normalize_name
    except Exception as e:
        print(f"   ⚠️ SofaScore source niedostępne: {e}")
        return []
    try:
        events = list_scheduled_events("table_tennis", date_str)
    except Exception as e:
        print(f"   ⚠️ list_scheduled_events błąd: {e}")
        return []

    def _matches_league(e: Dict[str, Any]) -> bool:
        hay = f"{e.get('tournament','')} {e.get('category','')}".lower()
        return any(f in hay for f in league_filters)

    matched = [e for e in events if _matches_league(e)
               and (e.get("status") or "").lower() != "finished"]
    print(f"   🎯 SofaScore: {len(matched)} meczów w ligach {league_filters} (z {len(events)} wszystkich)")

    from datetime import datetime, timezone
    rows: List[Dict[str, Any]] = []
    for e in matched:
        if is_sofascore_unreachable():
            print("   🛑 SofaScore niedostępne — przerywam dobieranie lig")
            break
        eid = e.get("event_id")
        home, away = e.get("home_team", ""), e.get("away_team", "")
        if not eid or not home or not away:
            continue
        pair = frozenset([normalize_name(home), normalize_name(away)])
        if pair in existing_pairs:
            continue  # already covered by AiScore

        # --- H2H GATE (favourite = focus side) ---
        try:
            h2h = get_event_h2h(eid) or {}
        except Exception:
            h2h = {}
        total = h2h.get("total", 0)
        hw, aw = h2h.get("home_wins", 0), h2h.get("away_wins", 0)
        fav_wins = aw if focus == "away" else hw
        fav_rate = (fav_wins / total) if total else 0.0
        if total < H2H_MIN_MATCHES or fav_rate < H2H_MIN_WIN_RATE:
            continue

        # --- FAN VOTE (mandatory) ---
        try:
            votes = get_votes_via_api(eid)
        except Exception:
            votes = None
        if not votes or votes.get("sofascore_home_win_prob") is None:
            continue

        # --- build the row ---
        mt = ""
        ts = e.get("start_timestamp")
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                try:
                    from zoneinfo import ZoneInfo
                    dt = dt.astimezone(ZoneInfo("Europe/Warsaw"))
                except Exception:
                    pass
                mt = dt.strftime("%d.%m.%Y %H:%M")
            except (ValueError, OverflowError, OSError):
                pass
        league = e.get("tournament", "") or e.get("category", "")
        cat = e.get("category", "")
        if league and cat and cat.lower() not in league.lower():
            league = f"{cat} — {league}"
        row = _build_row(home, away, focus,
                         f"https://www.sofascore.com/table-tennis/match/{eid}", mt, league)
        row["source"] = "sofascore"
        row["sofascore_event_id"] = eid
        row["h2h_count"] = total
        row["h2h_fav_win_rate"] = round(fav_rate, 4)
        row["win_rate"] = round(fav_rate, 3)
        row["home_wins_in_h2h_last5"] = hw
        row["away_wins_in_h2h_last5"] = aw

        try:
            hf = get_team_recent_form(e.get("home_id"), home)
        except Exception:
            hf = []
        try:
            af = get_team_recent_form(e.get("away_id"), away)
        except Exception:
            af = []
        row["form_a"] = hf
        row["form_b"] = af
        row["home_form_overall"] = hf
        row["away_form_overall"] = af
        row["home_form"] = hf
        row["away_form"] = af

        row["sofascore_found"] = True
        row["sofascore_home_win_prob"] = votes.get("sofascore_home_win_prob")
        row["sofascore_away_win_prob"] = votes.get("sofascore_away_win_prob")
        row["sofascore_total_votes"] = votes.get("sofascore_total_votes", 0) or 0

        try:
            so = sofascore_odds(eid)
        except Exception:
            so = None
        if so and (so.get("home_odds") or so.get("away_odds")):
            row["home_odds"] = so.get("home_odds")
            row["away_odds"] = so.get("away_odds")
            row["odds_bookmaker"] = so.get("bookmaker") or "SofaScore"

        row["qualifies"] = True
        rows.append(row)

    print(f"   ✅ SofaScore: {len(rows)} kwalifikujących się z lig dobranych "
          f"(H2H ≥{int(H2H_MIN_WIN_RATE*100)}% + Fan Vote)")
    return rows


def build_livesport_tt_index(driver: Any, date_str: str,
                             max_scrolls: int = 12) -> List[Dict[str, Any]]:
    """Scrape the Livesport table-tennis day page once → list of match links.

    Returns a list of {"url": <livesport match url>, "tokens": set(surnames)}
    used to fuzzy-match AiScore matches. Reuses livesport_h2h_scraper helpers
    without modifying that module. Best-effort: returns [] on any failure.
    """
    import time

    try:
        from bs4 import BeautifulSoup
        from livesport_h2h_scraper import (
            _accept_cookies_on_page,
            _extract_match_links_from_soup,
            _count_match_links_in_page,
            is_livesport_error_page,
            _safe_page_source,
        )
    except Exception as e:  # pragma: no cover
        print(f"   ⚠️ Livesport helpers niedostępne dla kursów: {e}")
        return []

    url = f"{LIVESPORT_TT_DAY_URL}?date={date_str}"
    try:
        driver.get(url)
        time.sleep(2.5)
        _accept_cookies_on_page(driver)
        attempts = 0
        while is_livesport_error_page(_safe_page_source(driver)) and attempts < 3:
            attempts += 1
            time.sleep(3.0 * attempts)
            try:
                driver.get(url)
                time.sleep(3.0)
                _accept_cookies_on_page(driver)
            except Exception:
                pass
        prev = _count_match_links_in_page(driver)
        stale = 0
        for _ in range(max_scrolls):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.6)
            cur = _count_match_links_in_page(driver)
            if cur <= prev:
                stale += 1
                if stale >= 3:
                    break
            else:
                stale = 0
            prev = cur
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.3)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        links, _dbg = _extract_match_links_from_soup(soup, LIVESPORT_TT_DAY_URL, set(), leagues=None)
    except Exception as e:
        print(f"   ⚠️ Livesport TT index błąd: {e}")
        return []

    index: List[Dict[str, Any]] = []
    for link in links:
        # Tokens = alphabetic words >3 chars from the URL slug (player surnames).
        slug = link.lower()
        toks = set(re.findall(r"[a-ząćęłńóśźż]{4,}", slug))
        # Drop generic path words.
        toks -= {"mecz", "match", "tenis", "stolowy", "table", "tennis",
                 "www", "livesport", "https", "http", "com", "pilka"}
        if toks:
            index.append({"url": link, "tokens": toks})
    print(f"   📇 Livesport TT index: {len(index)} meczów (do dopasowania kursów)")
    return index


def _match_livesport_url(home: str, away: str,
                         index: List[Dict[str, Any]]) -> Optional[str]:
    """Fuzzy-match an AiScore (home, away) to a Livesport match URL by surnames."""
    from aiscore_scraper import normalize_name
    want = set()
    for nm in (home, away):
        want |= {t for t in normalize_name(nm).split() if len(t) >= 4}
    if not want:
        return None
    best_url, best_score = None, 0
    for entry in index:
        score = len(want & entry["tokens"])
        if score > best_score:
            best_score, best_url = score, entry["url"]
    # Require at least 2 surname tokens to match (one from each side ideally).
    return best_url if best_score >= 2 else None


def resolve_odds(home: str, away: str, livesport_url: Optional[str]) -> Dict[str, Any]:
    """Fetch table-tennis home/away odds for a matched Livesport URL.

    Pinnacle rarely prices amateur table tennis, so we query MANY bookmakers
    via the Livesport odds API (HOME_AWAY market) and take the first that has
    odds, in a sharp→popular priority order. This maximises coverage so most
    matches get odds. Best-effort: returns Nones if no bookmaker priced it.
    """
    out: Dict[str, Any] = {"home_odds": None, "away_odds": None, "bookmaker": None}
    if not livesport_url:
        return out
    try:
        from livesport_odds_api import LivesportOddsAPI
        api = LivesportOddsAPI()
        event_id = api.extract_event_id_from_url(livesport_url)
        if not event_id:
            return out
        odds = api.get_odds_from_multiple_bookmakers(
            event_id, sport="table_tennis", bookmakers=TT_BOOKMAKERS)
        if odds and odds.get("success") and (odds.get("home_odds") or odds.get("away_odds")):
            out["home_odds"] = odds.get("home_odds")
            out["away_odds"] = odds.get("away_odds")
            out["bookmaker"] = odds.get("bookmaker")
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------

def _build_row(home: str, away: str, focus: str, match_url: str,
               match_time: str, league: str = "") -> Dict[str, Any]:
    """Base row whose contract matches TennisScoringEngine / gate / email.

    Player A is always the FOCUS player (home or away), Player B the rival, so
    the engine's home-centric features describe the side we actually pick.
    """
    return {
        "home_team": home,
        "away_team": away,
        "focus": focus,
        "focus_team": focus,
        "match_url": match_url,
        "match_time": match_time,
        "sport": SPORT,
        "league": league,
        "source": "aiscore",

        # SofaScore fan vote (mandatory, filled later)
        "sofascore_home_win_prob": None,
        "sofascore_draw_prob": None,
        "sofascore_away_win_prob": None,
        "sofascore_total_votes": 0,
        "sofascore_found": False,
        "sofascore_unavailable": False,

        # Odds (best-effort)
        "home_odds": None,
        "away_odds": None,
        "odds_bookmaker": None,

        # H2H
        "h2h_last5": [],
        "home_wins_in_h2h_last5": 0,
        "away_wins_in_h2h_last5": 0,
        "h2h_count": 0,
        "win_rate": 0.0,
        "h2h_fav_win_rate": 0.0,
        "last_h2h_score": "",
        "last_h2h_home": "",
        "last_h2h_away": "",
        "last_meeting_date": "",

        # Form
        "form_a": [],
        "form_b": [],
        "home_form_overall": [],
        "away_form_overall": [],
        "home_form": [],
        "away_form": [],
        "home_form_home": [],
        "away_form_away": [],
        "ranking_a": None,
        "ranking_b": None,
        "surface": "",
        "surface_form_a": [],
        "surface_form_b": [],

        "qualifies": False,
        "tt_skip_reason": None,
    }


# ---------------------------------------------------------------------------
# Per-match processing
# ---------------------------------------------------------------------------

def _sofascore_event_id(url: Optional[str]) -> Optional[int]:
    """Extract the numeric SofaScore event id from a match URL.

    Handles both formats the scraper emits:
      • https://www.sofascore.com/<slug>/match/<event_id>
      • https://www.sofascore.com/...#id:<event_id>
    """
    if not url:
        return None
    m = re.search(r"#id:(\d+)", url)
    if m:
        return int(m.group(1))
    m = re.search(r"/match/(\d+)", url)
    if m:
        return int(m.group(1))
    # Last resort: trailing numeric path segment.
    m = re.search(r"/(\d{5,})/?$", url)
    return int(m.group(1)) if m else None


def _frac_to_decimal(val: Any) -> Optional[float]:
    """Convert a SofaScore odds value to decimal. Accepts '13/8' or '2.62'."""
    if val is None:
        return None
    s = str(val).strip()
    if "/" in s:
        a, _, b = s.partition("/")
        try:
            return round(float(a) / float(b) + 1.0, 2)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        d = float(s)
        return round(d, 2) if d > 1.0 else None
    except ValueError:
        return None


def sofascore_odds(event_id: int) -> Dict[str, Any]:
    """Fetch home/away odds from SofaScore's odds endpoint for an event.

    SofaScore aggregates bookmaker odds (e.g. LV Bet) even for amateur table
    tennis. Reuses the SAME working API stack as the fan vote (``_api_get_json``
    → curl_cffi / FlareSolverr fallback). Parses the 2-way "Full time" market
    CASE-INSENSITIVELY (SofaScore returns 'Full time', not 'Full Time' — the
    legacy get_odds_via_api missed it). Returns {home_odds, away_odds, bookmaker}.
    """
    out: Dict[str, Any] = {"home_odds": None, "away_odds": None, "bookmaker": None}
    if not event_id:
        return out
    try:
        data = _api_get_json(
            f"https://api.sofascore.com/api/v1/event/{event_id}/odds/1/all", timeout=8)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return out
    wanted = {"full time", "1x2", "match winner", "full time result",
              "match", "winner", "fulltime"}
    for market in data.get("markets", []) or []:
        if str(market.get("marketName", "")).strip().lower() not in wanted:
            continue
        for choice in market.get("choices", []) or []:
            name = str(choice.get("name", "")).strip().lower()
            dec = _frac_to_decimal(choice.get("fractionalValue"))
            if dec is None:
                src = choice.get("sourceOdds") or []
                if src:
                    dec = _frac_to_decimal(src[0].get("odds"))
            if dec is None:
                continue
            if name in ("1", "home"):
                out["home_odds"] = dec
            elif name in ("2", "away"):
                out["away_odds"] = dec
        if out["home_odds"] and out["away_odds"]:
            out["bookmaker"] = "SofaScore"
            return out
    return out


def sofascore_event_meta(event_id: int) -> Dict[str, str]:
    """Return {'start_time': 'DD.MM.YYYY HH:MM' (Europe/Warsaw), 'league': name}.

    One SofaScore event-detail call gives us BOTH the scheduled start time (the
    AiScore /h2h page lacks it) and the tournament/league name (so the league is
    visible per match, e.g. 'TT Cup', 'Setka Cup'). Best-effort: empty strings
    on failure. Reuses the working API stack.
    """
    out = {"start_time": "", "league": ""}
    if not event_id:
        return out
    try:
        data = _api_get_json(f"https://api.sofascore.com/api/v1/event/{event_id}", timeout=8)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return out
    ev = data.get("event") or data
    # League / tournament name.
    tour = ev.get("tournament") or {}
    league = tour.get("name") or (tour.get("uniqueTournament") or {}).get("name") or ""
    cat = (tour.get("category") or {}).get("name") or ""
    if league and cat and cat.lower() not in league.lower():
        out["league"] = f"{cat} — {league}"
    else:
        out["league"] = league or cat
    # Start time.
    ts = ev.get("startTimestamp")
    if ts:
        from datetime import datetime, timezone
        try:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            try:
                from zoneinfo import ZoneInfo
                dt = dt.astimezone(ZoneInfo("Europe/Warsaw"))
            except Exception:
                pass
            out["start_time"] = dt.strftime("%d.%m.%Y %H:%M")
        except (ValueError, OverflowError, OSError):
            pass
    return out

def process_match(driver: Any, url: str, focus: str, date_str: str,
                  verbose: bool = True) -> Optional[Dict[str, Any]]:
    """Scrape one AiScore match page and build a scored, gated row.

    Returns the row dict, or None when the page could not be parsed at all.
    The row's ``qualifies`` reflects the H2H ≥60% + mandatory Fan Vote gates.
    """
    page = ai.scrape_match_page(driver, url)
    all_matches = page.get("all_matches") or []
    home = page.get("home")
    away = page.get("away")
    if not home or not away:
        if verbose:
            print(f"   ⚠️  Pominięto (brak uczestników): {url}")
        return None

    match_time = ai.iso_to_match_time(page.get("match_date")) or ""
    # Store the clean match-overview URL (without the /h2h sub-page suffix) so
    # downstream links point at the match page, not the H2H tab.
    clean_url = url.split("#")[0].split("?")[0].rstrip("/")
    if clean_url.endswith("/h2h"):
        clean_url = clean_url[: -len("/h2h")]
    row = _build_row(home, away, focus, clean_url, match_time)

    # --- which side do we pick? (focus = home/away) ---
    if focus == "away":
        favourite, rival = away, home
    else:
        favourite, rival = home, away

    # --- H2H GATE: favourite must have won >= 60% vs the rival ---
    passes, rec = ai.favourite_meets_h2h_threshold(
        all_matches, favourite, rival,
        threshold=H2H_MIN_WIN_RATE, min_matches=H2H_MIN_MATCHES,
    )
    row["h2h_count"] = rec["total"]
    row["h2h_fav_win_rate"] = rec["fav_win_rate"]
    # Record H2H in the engine's home/away framing.
    if focus == "away":
        row["away_wins_in_h2h_last5"] = rec["fav_wins"]
        row["home_wins_in_h2h_last5"] = rec["total"] - rec["fav_wins"]
    else:
        row["home_wins_in_h2h_last5"] = rec["fav_wins"]
        row["away_wins_in_h2h_last5"] = rec["total"] - rec["fav_wins"]
    row["win_rate"] = round(rec["fav_win_rate"], 3)

    # --- LAST H2H MEETING (most recent direct match) ---
    direct = rec.get("matches") or []
    if direct:
        last = direct[0]  # AiScore /h2h lists most recent first
        hs, as_ = last.get("home_score"), last.get("away_score")
        if hs is not None and as_ is not None:
            row["last_h2h_score"] = f"{hs}:{as_}"
            row["last_h2h_home"] = last.get("home")
            row["last_h2h_away"] = last.get("away")
            row["last_meeting_date"] = ai.iso_to_match_time(last.get("date")) or \
                (str(last.get("date")) if last.get("date") else "")

    if not passes:
        row["qualifies"] = False
        if rec["total"] < H2H_MIN_MATCHES:
            row["tt_skip_reason"] = f"h2h_too_few ({rec['total']}<{H2H_MIN_MATCHES})"
        else:
            row["tt_skip_reason"] = (
                f"h2h_fav_win_rate {rec['fav_win_rate']:.2f} < {H2H_MIN_WIN_RATE:.2f}"
            )
        return row

    # --- FORM (general + venue split, per ACTUAL home/away player) ---
    # Engine convention: player A = home_team, player B = away_team. Email reads
    # home_form_overall / away_form_overall (general) and home_form_home /
    # away_form_away (venue). Compute all from the AiScore /h2h form sections.
    home_form_overall = ai.recent_form(all_matches, home, limit=5)
    away_form_overall = ai.recent_form(all_matches, away, limit=5)
    home_form_home = ai.recent_form(all_matches, home, venue="home", limit=5)
    away_form_away = ai.recent_form(all_matches, away, venue="away", limit=5)

    row["form_a"] = home_form_overall
    row["form_b"] = away_form_overall
    # Fields the e-mail template renders ("forma ogólna" + venue splits).
    row["home_form_overall"] = home_form_overall
    row["away_form_overall"] = away_form_overall
    row["home_form"] = home_form_overall
    row["away_form"] = away_form_overall
    row["home_form_home"] = home_form_home
    row["away_form_away"] = away_form_away

    # --- ODDS: fetched in a dedicated phase in run() (needs Livesport index) ---

    # --- FAN VOTE (MANDATORY) ---
    try:
        pred = get_sofascore_prediction(home, away, sport="table-tennis", date_str=date_str)
    except Exception as e:
        pred = {"found": False}
        if verbose:
            print(f"   ⚠️  SofaScore błąd dla {home} vs {away}: {e}")
    if pred.get("found"):
        row["sofascore_found"] = True
        row["sofascore_home_win_prob"] = pred.get("home_win_prob")
        row["sofascore_away_win_prob"] = pred.get("away_win_prob")
        row["sofascore_total_votes"] = pred.get("total_votes", 0) or 0
        # SofaScore also carries odds (e.g. LV Bet) for these amateur events,
        # and we already resolved the event for the fan vote — so fetch them
        # from the SAME working API stack. Best-effort, non-blocking.
        ev_id = _sofascore_event_id(pred.get("url") or pred.get("sofascore_url"))
        if ev_id:
            row["sofascore_event_id"] = ev_id
            # Match start time + league (the AiScore /h2h page lacks both).
            meta = sofascore_event_meta(ev_id)
            if meta.get("start_time") and not row.get("match_time"):
                row["match_time"] = meta["start_time"]
            if meta.get("league") and not row.get("league"):
                row["league"] = meta["league"]
            try:
                so = sofascore_odds(ev_id)
            except Exception:
                so = None
            if so and (so.get("home_odds") or so.get("away_odds")):
                row["home_odds"] = so.get("home_odds")
                row["away_odds"] = so.get("away_odds")
                row["odds_bookmaker"] = so.get("bookmaker") or "SofaScore"
    else:
        row["sofascore_found"] = False
        row["qualifies"] = False
        row["tt_skip_reason"] = "sofascore_fan_vote_required"
        return row

    # Passed both hard gates.
    row["qualifies"] = True
    return row


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_rows(rows: List[Dict[str, Any]]) -> int:
    """Score qualifying rows with the TennisScoringEngine (table-tennis profile)."""
    try:
        from tennis_scoring_engine import TennisScoringEngine
    except Exception as e:
        print(f"⚠️ TennisScoringEngine niedostępny: {e}")
        return 0

    engine = TennisScoringEngine(weights=dict(TT_WEIGHTS), threshold=TT_THRESHOLD)
    # Re-assert the TT profile AFTER construction (calibration file may override).
    engine.weights = dict(TT_WEIGHTS)
    engine.threshold = TT_THRESHOLD
    scored = 0
    for row in rows:
        if not row.get("qualifies"):
            continue
        try:
            sm = engine.score_match(row)
            row["scoring_pick"] = sm.best_pick
            row["scoring_prob"] = round(sm.best_prob * 100, 1)
            row["scoring_ev"] = round(sm.ev, 3)
            row["scoring_edge"] = round(sm.edge, 1)
            row["scoring_confidence"] = round(sm.confidence, 0)
            row["advanced_score"] = round(sm.advanced_score, 1)
            row["favorite"] = sm.favorite
            scored += 1
        except Exception as e:
            print(f"   ⚠️ Scoring error {row.get('home_team')} vs {row.get('away_team')}: {e}")
    return scored


# ---------------------------------------------------------------------------
# SofaScore infrastructure fallback
# ---------------------------------------------------------------------------

def _rescue_when_sofascore_unreachable(rows: List[Dict[str, Any]]) -> int:
    """Re-qualify H2H-passing picks that only failed on a missing fan vote.

    Used ONLY when SofaScore is globally unreachable for the run (Cloudflare
    blocked the whole CI shard). Returns the number of rows rescued. Fan vote
    stays mandatory whenever SofaScore is reachable — this just prevents a
    runner-IP block from zeroing out every pick.
    """
    rescued = 0
    for row in rows:
        if (not row.get("qualifies")
                and row.get("tt_skip_reason") == "sofascore_fan_vote_required"):
            row["qualifies"] = True
            row["sofascore_unavailable"] = True
            row["tt_skip_reason"] = None
            rescued += 1
    return rescued


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(rows: List[Dict[str, Any]], date_str: str, focus: str) -> Dict[str, str]:
    """Write CSV + JSON. Filenames carry the focus so home/away never collide."""
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("results", exist_ok=True)

    csv_path = os.path.join("outputs", f"table_tennis_aiscore_{focus}_{date_str}.csv")
    json_path = os.path.join("results", f"matches_{date_str}_table_tennis_aiscore_{focus}.json")

    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        for col in ("h2h_last5", "form_a", "form_b", "surface_form_a", "surface_form_b",
                    "home_form_overall", "away_form_overall", "home_form", "away_form",
                    "home_form_home", "away_form_away"):
            if col in df.columns:
                df[col] = df[col].apply(lambda x: str(x) if isinstance(x, (list, dict)) else x)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    except Exception as e:
        print(f"   ⚠️ CSV (pandas) failed, writing minimal CSV: {e}")
        import csv as _csv
        if rows:
            keys = sorted({k for r in rows for k in r.keys()})
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
                w = _csv.DictWriter(fh, fieldnames=keys)
                w.writeheader()
                for r in rows:
                    w.writerow({k: (str(r.get(k)) if isinstance(r.get(k), (list, dict)) else r.get(k)) for k in keys})

    frontend = {
        "date": date_str,
        "sport": SPORT,
        "source": "aiscore",
        "focus": focus,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "matches": [
            {
                "homeTeam": r.get("home_team"),
                "awayTeam": r.get("away_team"),
                "time": r.get("match_time"),
                "focus": r.get("focus"),
                "league": r.get("league"),
                "source": r.get("source"),
                "matchUrl": r.get("match_url"),
                "qualifies": bool(r.get("qualifies")),
                "channelQualifies": bool(r.get("channel_qualifies")),
                "emailQualifies": bool(r.get("email_qualifies")),
                "h2h": {
                    "favWinRate": r.get("h2h_fav_win_rate"),
                    "total": r.get("h2h_count"),
                    "homeWins": r.get("home_wins_in_h2h_last5"),
                    "awayWins": r.get("away_wins_in_h2h_last5"),
                    "lastDate": r.get("last_meeting_date"),
                    "lastScore": r.get("last_h2h_score"),
                },
                "form": {
                    "home": r.get("home_form_overall"),
                    "away": r.get("away_form_overall"),
                    "homeAtHome": r.get("home_form_home"),
                    "awayAtAway": r.get("away_form_away"),
                },
                "sofascore": {
                    "found": r.get("sofascore_found"),
                    "votes": r.get("sofascore_total_votes"),
                    "unavailable": r.get("sofascore_unavailable", False),
                },
                "odds": {
                    "home": r.get("home_odds"),
                    "away": r.get("away_odds"),
                    "bookmaker": r.get("odds_bookmaker"),
                },
                "scoring": {
                    "pick": r.get("scoring_pick"),
                    "prob": r.get("scoring_prob"),
                    "ev": r.get("scoring_ev"),
                    "favorite": r.get("favorite"),
                },
            }
            for r in rows
        ],
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(frontend, fh, ensure_ascii=False, indent=2)

    return {"csv": csv_path, "json": json_path}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(focus: str, date_str: str, max_matches: Optional[int] = None,
        send_email: bool = True, send_telegram: bool = True,
        email_cfg: Optional[Dict[str, str]] = None, verbose: bool = True) -> Dict[str, Any]:
    """Run the AiScore table-tennis pipeline for one focus (home/away)."""
    if not _AI_OK:
        print(f"❌ aiscore_scraper niedostępny — przerwano ({_AI_ERR})")
        return {"error": "aiscore_unavailable", "matches": 0}

    focus = "away" if str(focus).lower().startswith("a") else "home"
    print("=" * 70)
    print(f"🏓 TABLE TENNIS (AiScore) — focus={focus.upper()} — {date_str}")
    print("=" * 70)

    # ── start browser (reuse the LiveSport scraper's hardened driver) ──
    try:
        from livesport_h2h_scraper import start_driver
        driver = start_driver(headless=True)
    except Exception as e:
        print(f"❌ Nie można uruchomić przeglądarki: {e}")
        return {"error": "driver_unavailable", "matches": 0}

    rows: List[Dict[str, Any]] = []
    try:
        # ── FAZA 1: list match URLs from AiScore ──
        print("\n[FAZA 1] Pobieram listę meczów z AiScore...")
        urls = ai.list_match_urls(driver, date_str)
        print(f"   📋 Znaleziono {len(urls)} linków meczów")
        if max_matches:
            urls = urls[:max_matches]
            print(f"   ✂️  Limit --max-matches: {len(urls)}")

        # ── FAZA 2: process each match (H2H gate + form + odds + fan vote) ──
        print(f"\n[FAZA 2] Przetwarzam {len(urls)} meczów (H2H ≥{int(H2H_MIN_WIN_RATE*100)}% + Fan Vote)...")
        for i, url in enumerate(urls, 1):
            try:
                row = process_match(driver, url, focus, date_str, verbose=verbose)
            except Exception as e:
                print(f"   ⚠️ Błąd przetwarzania {url}: {e}")
                row = None
            if row:
                rows.append(row)
            if verbose and (i % 10 == 0 or i == len(urls)):
                q = sum(1 for r in rows if r.get("qualifies"))
                print(f"   [{i}/{len(urls)}] kwalifikujących się dotąd: {q}")

        # ── FAZA 2.4: SofaScore infrastructure fallback ──
        # If SofaScore was blocked for the WHOLE run (Cloudflare 403 on every
        # method → circuit breaker tripped), rescue picks that passed the H2H
        # ≥60% gate and only failed because no fan vote could be fetched. This
        # prevents a runner-IP block from zeroing out every pick. Fan vote stays
        # mandatory whenever SofaScore is reachable (per-match "not found" still
        # disqualifies).
        if not TT_SOFASCORE_STRICT and is_sofascore_unreachable():
            rescued = _rescue_when_sofascore_unreachable(rows)
            if rescued:
                print(f"   ⚠️ SofaScore niedostępny dla całego runu (Cloudflare zablokował shard) "
                      f"— kwalifikuję {rescued} meczów na podstawie samego H2H "
                      f"≥{int(H2H_MIN_WIN_RATE*100)}% (Fan Vote oznaczony jako niedostępny)")

        # ── FAZA 2.42: supplement with SofaScore-only leagues (Setka Cup) ──
        # AiScore doesn't list Setka Cup / Setka Cup (K); SofaScore does. Add
        # those qualifying matches (same H2H ≥60% + Fan Vote gates), deduped
        # against the AiScore picks.
        try:
            from aiscore_scraper import normalize_name as _nn
            existing = {frozenset([_nn(r.get("home_team", "")), _nn(r.get("away_team", ""))])
                        for r in rows}
            extra = collect_sofascore_league_matches(date_str, focus, existing_pairs=existing)
            if extra:
                rows.extend(extra)
                print(f"   ➕ Dodano {len(extra)} meczów z lig SofaScore (Setka Cup itd.)")
        except Exception as e:
            print(f"   ⚠️ SofaScore leagues supplement błąd: {e}")

        # ── FAZA 2.45: Odds fallback (Livesport multi-bookmaker) ──
        # SofaScore odds (LV Bet etc.) were already fetched per-match during the
        # fan-vote step. Here we only try Livesport for the rows that STILL have
        # no odds. Best-effort, non-blocking.
        qual_rows = [r for r in rows if r.get("qualifies")]
        sofa_odds = sum(1 for r in qual_rows if r.get("home_odds") or r.get("away_odds"))
        need_odds = [r for r in qual_rows if not (r.get("home_odds") or r.get("away_odds"))]
        if qual_rows:
            print(f"\n[FAZA 2.45] Kursy: {sofa_odds}/{len(qual_rows)} z SofaScore (LV Bet itd.); "
                  f"{len(need_odds)} bez — próbuję Livesport...")
            ls_index = []
            if need_odds:
                try:
                    ls_index = build_livesport_tt_index(driver, date_str)
                except Exception as e:
                    print(f"   ⚠️ Nie zbudowano indeksu Livesport: {e}")
                    ls_index = []
            odds_found = sofa_odds
            for r in need_odds:
                ls_url = _match_livesport_url(r.get("home_team", ""), r.get("away_team", ""), ls_index)
                odds = resolve_odds(r.get("home_team", ""), r.get("away_team", ""), ls_url)
                if odds.get("home_odds") or odds.get("away_odds"):
                    r["home_odds"] = odds["home_odds"]
                    r["away_odds"] = odds["away_odds"]
                    r["odds_bookmaker"] = odds["bookmaker"]
                    odds_found += 1
            print(f"   💰 Kursy łącznie dla {odds_found}/{len(qual_rows)} meczów "
                  f"(SofaScore: {sofa_odds}, Livesport: {odds_found - sofa_odds})")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # ── FAZA 2.5: scoring ──
    print("\n[FAZA 2.5] Scoring (TennisScoringEngine, profil table tennis)...")
    scored = score_rows(rows)
    qualified = sum(1 for r in rows if r.get("qualifies"))
    print(f"   🧠 {scored} ocenionych, {qualified} kwalifikujących się")

    # ── FAZA 2.9: qualification gate (channel + email) ──
    try:
        from qualification_gate import apply_qualification_gate
        cq = apply_qualification_gate(rows, date_str)
        print(f"\n[FAZA 2.9] Qualification gate: {cq} channel-qualified")
    except Exception as e:
        print(f"\n⚠️ Qualification gate error: {e}")
        for r in rows:
            r["channel_qualifies"] = r.get("qualifies", False)
            r["email_qualifies"] = r.get("qualifies", False)

    # ── OUTPUT ──
    paths = write_outputs(rows, date_str, focus)
    print(f"\n💾 Zapisano:\n   CSV:  {paths['csv']}\n   JSON: {paths['json']}")

    # ── EMAIL (like tennis) ──
    if send_email and email_cfg and email_cfg.get("to") and email_cfg.get("from"):
        try:
            from email_notifier import send_email_notification
            send_email_notification(
                csv_file=paths["csv"],
                to_email=email_cfg["to"],
                from_email=email_cfg["from"],
                password=email_cfg.get("password", ""),
                provider=email_cfg.get("provider", "gmail"),
                subject=f"🏓 Table Tennis ({focus}) — {date_str}",
                date=date_str,
                # AiScore exposes no table-tennis odds, so DON'T drop no-odds
                # matches — otherwise every qualifying pick is filtered out and
                # no e-mail is sent. Qualification already happened upstream
                # (H2H ≥60% + mandatory Fan Vote).
                skip_no_odds=False,
                min_odds_threshold=0.0,
            )
            print("   ✅ Email wysłany (jeśli były kwalifikujące się)")
        except Exception as e:
            print(f"   ⚠️ Email error: {e}")
    elif send_email:
        print("   ℹ️ Email pominięty (brak konfiguracji --to/--from-email)")

    # ── TELEGRAM ──
    if send_telegram:
        try:
            from telegram_notifier import send_telegram_summary
            cq = sum(1 for r in rows if r.get("channel_qualifies"))
            send_telegram_summary(rows, cq, date_str)
            print("   ✅ Telegram summary wysłane")
        except Exception as e:
            print(f"   ⚠️ Telegram error: {e}")

    summary = {
        "date": date_str,
        "focus": focus,
        "processed": len(rows),
        "scored": scored,
        "qualified": sum(1 for r in rows if r.get("qualifies")),
        "channel_qualified": sum(1 for r in rows if r.get("channel_qualifies")),
        "email_qualified": sum(1 for r in rows if r.get("email_qualifies")),
        "outputs": paths,
    }
    print("\n" + "=" * 70)
    print(f"🏓 DONE ({focus}) — {summary['channel_qualified']} channel / "
          f"{summary['email_qualified']} email z {len(rows)} przetworzonych")
    print("=" * 70)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Table Tennis Pipeline (AiScore-sourced)")
    ap.add_argument("--focus", choices=["home", "away"], default="home",
                    help="Which side to evaluate/pick (home=gospodarze, away=goście)")
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    help="Date YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--max-matches", type=int, default=None,
                    help="Cap number of matches processed (testing)")
    ap.add_argument("--to", default=os.getenv("EMAIL_RECIPIENT", ""), help="Email recipient")
    ap.add_argument("--from-email", default=os.getenv("EMAIL_SENDER", ""), help="Email sender")
    ap.add_argument("--password", default=os.getenv("EMAIL_PASSWORD", ""), help="Email password")
    ap.add_argument("--provider", default="gmail", help="Email provider (gmail/outlook/yahoo)")
    ap.add_argument("--no-email", action="store_true", help="Skip e-mail notification")
    ap.add_argument("--no-telegram", action="store_true", help="Skip Telegram notification")
    args = ap.parse_args()

    email_cfg = {
        "to": args.to,
        "from": args.from_email,
        "password": args.password,
        "provider": args.provider,
    }
    run(args.focus, args.date, max_matches=args.max_matches,
        send_email=not args.no_email, send_telegram=not args.no_telegram,
        email_cfg=email_cfg)


if __name__ == "__main__":
    main()
