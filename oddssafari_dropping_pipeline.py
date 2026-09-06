"""End-to-end OddsSafari dropping-odds pipeline.

Flow::

    OddsSafari  ->  every sport, every row  ->  audit JSON (events)
                                    |
                                    +->  qualifies (current odds in range
                                         and sport supported)
                                                |
                                                +->  resolve Livesport URL
                                                       |
                                                       +->  process_match /
                                                            process_match_tennis
                                                            (Forebet, SofaScore,
                                                             H2H + form)

Output::

    outputs/oddssafari_dropping_{date}.json
        {
          "meta": {...},
          "events": [ ... every row with qualifies + skip_reason ],
          "qualified": [ ... enriched subset ]
        }

The script intentionally reuses
:func:`livesport_h2h_scraper.process_match` / ``process_match_tennis`` instead
of reimplementing H2H logic — this keeps parity with the main pipeline and
ensures any future improvement to ``process_match`` is picked up here too.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from oddssafari_dropping_scraper import (
    DroppingOddsRow,
    collect_dropping_odds_rows,
    collect_rows_via_http,
    is_qualifying_row,
    odds_range_for_sport,
    uses_sofascore_only_enrichment,
)


logger = logging.getLogger(__name__)


WARSAW_TZ = ZoneInfo("Europe/Warsaw")


# ---------------------------------------------------------------------------
# Livesport URL resolver (shared pattern with forebet_first_scraper)
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    return " ".join(name.split())


def _token_overlap(a: str, b: str) -> int:
    """Count significant tokens shared by two already-normalised names.

    Tokens shorter than four characters are ignored so club prefixes and
    connectives ('cd', 'fc', 'de', 'gks') do not create spurious matches.
    """
    if not a or not b:
        return 0
    ta = {t for t in a.split() if len(t) >= 4}
    tb = {t for t in b.split() if len(t) >= 4}
    return len(ta & tb)


def _fuzzy_word_in_slug(word: str, slug: str) -> bool:
    """Check if a word appears in the slug, allowing minor differences.
    
    Handles common transliteration issues:
    - 'kh' vs 'ch', 'ou' vs 'u', doubled letters, etc.
    - Prefix matching (word[:4] in slug) for long words
    """
    if word in slug:
        return True
    # Prefix match for words >= 5 chars (catches transliteration diffs)
    if len(word) >= 5 and word[:4] in slug:
        return True
    # Try without common suffixes
    for suffix in ("fc", "sc", "fk", "sk", "club"):
        stripped = word.rstrip(suffix) if word.endswith(suffix) else word
        if stripped and len(stripped) >= 3 and stripped in slug:
            return True
    return False


def resolve_livesport_match_url(
    driver,
    *,
    home_team: str,
    away_team: str,
    sport: str,
    date: str,
    max_candidates: int = 150,
) -> Tuple[Optional[str], float]:
    """Return (best_url, confidence) for a match on Livesport.

    Uses :func:`livesport_h2h_scraper.get_match_links_from_day` to enumerate
    the day's URLs, then scores each candidate by how many significant words
    from the two team names appear in the slug.
    
    Improved matching:
    - Uses words >= 3 chars (not 4) to catch short team names
    - Fuzzy matching handles transliteration differences
    - Falls back to single-word match if strict matching fails
    - Confidence reflects match quality
    """
    try:
        from livesport_h2h_scraper import get_match_links_from_day
    except ImportError as exc:  # pragma: no cover
        logger.error("livesport_h2h_scraper unavailable: %s", exc)
        return None, 0.0

    try:
        urls = get_match_links_from_day(
            driver, date, sports=[sport], leagues=None
        ) or []
    except Exception as exc:  # pragma: no cover
        logger.warning("get_match_links_from_day failed for %s: %s", sport, exc)
        return None, 0.0

    if not urls:
        return None, 0.0

    # Use words >= 3 chars (was 4 — too strict for names like "Goa", "VPS")
    home_words = [w for w in _normalize(home_team).split() if len(w) >= 3]
    away_words = [w for w in _normalize(away_team).split() if len(w) >= 3]
    
    # If no significant words, try all words >= 2 chars
    if not home_words:
        home_words = [w for w in _normalize(home_team).split() if len(w) >= 2]
    if not away_words:
        away_words = [w for w in _normalize(away_team).split() if len(w) >= 2]
    
    total_words = max(1, len(home_words) + len(away_words))

    best_url: Optional[str] = None
    best_score = 0

    for candidate in urls[:max_candidates]:
        slug = candidate.lower()
        home_hits = sum(1 for w in home_words if _fuzzy_word_in_slug(w, slug))
        away_hits = sum(1 for w in away_words if _fuzzy_word_in_slug(w, slug))
        # Require at least one hit from each side
        if home_hits == 0 or away_hits == 0:
            continue
        score = home_hits + away_hits
        if score > best_score:
            best_score = score
            best_url = candidate

    # If strict matching failed, try a looser approach:
    # accept if the longest word from each team appears in the same URL
    if not best_url and home_words and away_words:
        longest_home = max(home_words, key=len) if home_words else ""
        longest_away = max(away_words, key=len) if away_words else ""
        if len(longest_home) >= 4 and len(longest_away) >= 4:
            for candidate in urls[:max_candidates]:
                slug = candidate.lower()
                if longest_home in slug and longest_away in slug:
                    best_url = candidate
                    best_score = 2
                    break

    confidence = min(1.0, best_score / total_words)
    return best_url, confidence


# ---------------------------------------------------------------------------
# Enrichment via process_match / process_match_tennis
# ---------------------------------------------------------------------------


def _focus_team_from_outcome(outcome: str) -> Tuple[Optional[str], bool]:
    """Map the dropped outcome to (focus_team, away_team_focus).

    - ``1`` -> ``home`` focus, ``away_team_focus=False``
    - ``2`` -> ``away`` focus, ``away_team_focus=True``
    - ``X`` -> draw, no focus (returns ``('draw', False)``; process_match is
      still invoked so we capture H2H/form data for the audit).
    """
    outcome = (outcome or "").upper().strip()
    if outcome == "1":
        return "home", False
    if outcome == "2":
        return "away", True
    if outcome == "X":
        return "draw", False
    return None, False


def _enrich_row_via_sofascore(row: DroppingOddsRow) -> Dict[str, Any]:
    """Enrich a row using the SofaScore API only (no Livesport, no browser).

    Used for sports Livesport does not cover — currently e-sports. SofaScore
    does not list e-sports in ``/sport/{slug}/scheduled-events``, so we locate
    the event by walking a team's schedule, then pull H2H and recent form.
    """
    result: Dict[str, Any] = {
        "status": "resolve_failed",
        "livesport_url": None,
        "livesport_confidence": 0.0,
        "focus_team": None,
        "away_team_focus": False,
        "enrichment": None,
        "error": None,
    }

    focus_team, away_focus = _focus_team_from_outcome(row.outcome)
    result["focus_team"] = focus_team
    result["away_team_focus"] = away_focus

    try:
        from sofascore_scraper import (
            find_event_via_team_schedule,
            get_event_h2h,
            get_team_recent_form,
            SOFASCORE_SPORT_SLUGS,
        )
    except ImportError as exc:
        result["error"] = f"sofascore unavailable: {exc}"
        return result

    sport = row.sport or "esports"
    slug = SOFASCORE_SPORT_SLUGS.get(sport, sport)

    try:
        found = find_event_via_team_schedule(row.home_team, row.away_team, slug)
    except Exception as exc:
        result["status"] = "process_match_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    if not found:
        result["error"] = "sofascore_event_not_found"
        return result

    enrichment: Dict[str, Any] = {
        "home_team": found.get("home_name") or row.home_team,
        "away_team": found.get("away_name") or row.away_team,
        "sport": sport,
        "league": found.get("tournament") or row.league,
        "match_time": row.event_time,
        "home_odds": row.current_odds if row.outcome == "1" else None,
        "away_odds": row.current_odds if row.outcome == "2" else None,
        "sofascore_event_id": found.get("event_id"),
        "form_source": "sofascore_api",
    }

    # Recent form for both sides (newest first).
    for side, key in (("home", "home_team_id"), ("away", "away_team_id")):
        team_id = found.get(key)
        if not team_id:
            continue
        try:
            form = get_team_recent_form(
                team_id, enrichment.get(f"{side}_team", ""), limit=5,
                allow_draws=_sport_has_draws(sport),
            )
        except Exception:
            form = []
        if form:
            enrichment[f"{side}_form"] = form
            enrichment[f"{side}_form_overall"] = form

    # Head-to-head record.
    try:
        h2h = get_event_h2h(found.get("event_id"))
    except Exception:
        h2h = None
    if h2h:
        total = h2h.get("total") or 0
        enrichment["h2h_count"] = total
        enrichment["home_wins_in_h2h_last5"] = h2h.get("home_wins")
        enrichment["away_wins_in_h2h_last5"] = h2h.get("away_wins")
        if total:
            focus_wins = (
                h2h.get("away_wins") if focus_team == "away" else h2h.get("home_wins")
            )
            # Stored as a 0-1 fraction: the email renders it as `win_rate*100`,
            # matching what Livesport writes. Percent here showed "9000%".
            enrichment["win_rate"] = round((focus_wins or 0) / total, 3)

    home_f = enrichment.get("home_form") or []
    away_f = enrichment.get("away_form") or []
    if home_f and away_f:
        enrichment["form_advantage"] = (
            home_f.count("W") > away_f.count("W")
            if focus_team != "away"
            else away_f.count("W") > home_f.count("W")
        )

    result["status"] = "enriched"
    result["enrichment"] = enrichment
    print(f"   🎮 SofaScore: H={home_f} | A={away_f} | H2H={enrichment.get('h2h_count', 0)}")
    return result


def _apply_venue_form(
    enrichment: Dict[str, Any],
    driver,
    url: str,
) -> bool:
    """Fetch home-form-at-home / away-form-away the same way the main pipeline does.

    The main sport-scraper pipeline gets venue form from ``extract_advanced_team_form``,
    which walks the dedicated LiveSport H2H sub-pages (``/h2h/ogolem/`` and
    ``/h2h/u-siebie/``). Dropping odds used to call this only when the *overall*
    form was missing, so whenever the match page happened to render overall
    badges the venue form was never fetched at all — that is why only general
    form showed up in the mail.

    This runs unconditionally for non-tennis sports and fills overall form only
    where it is still missing. Mutates *enrichment*; returns True if venue form
    was obtained.
    """
    try:
        from livesport_h2h_scraper import extract_advanced_team_form
    except ImportError as exc:
        logger.debug("extract_advanced_team_form unavailable: %s", exc)
        return False

    try:
        form_data = extract_advanced_team_form(url, driver) or {}
    except Exception as exc:
        logger.debug("extract_advanced_team_form failed for %s: %s", url, exc)
        return False

    home_venue = form_data.get("home_form_home") or []
    away_venue = form_data.get("away_form_away") or []
    home_overall = form_data.get("home_form_overall") or []
    away_overall = form_data.get("away_form_overall") or []

    if home_venue:
        enrichment["home_form_home"] = home_venue
    if away_venue:
        enrichment["away_form_away"] = away_venue

    # Overall form: only fill gaps, never overwrite what process_match found.
    if home_overall and not (
        enrichment.get("home_form") or enrichment.get("home_form_overall")
    ):
        enrichment["home_form"] = home_overall
        enrichment["home_form_overall"] = home_overall
    if away_overall and not (
        enrichment.get("away_form") or enrichment.get("away_form_overall")
    ):
        enrichment["away_form"] = away_overall
        enrichment["away_form_overall"] = away_overall

    if home_venue or away_venue:
        enrichment["venue_form_source"] = "livesport_h2h_pages"
        if "form_advantage" in form_data:
            enrichment.setdefault("form_advantage", form_data.get("form_advantage"))
        if "away_advantage" in form_data:
            enrichment.setdefault("away_advantage", form_data.get("away_advantage"))
        print(f"   🏠 Forma u siebie: {home_venue} | 🛫 na wyjeździe: {away_venue}")
        return True

    return False


def _summarize_h2h(
    enrichment: Dict[str, Any],
    h2h_rows: List[Dict[str, Any]],
    *,
    home_team: str,
    away_team: str,
    focus_team: Optional[str],
) -> None:
    """Derive H2H counts and last-meeting fields from parsed H2H rows.

    Mirrors what ``process_match`` puts in its output dict so the mail layer
    sees the same shape regardless of which path produced the data.
    """
    if not h2h_rows:
        return

    rows = h2h_rows[:5]
    home_norm = _normalize(home_team or "")
    away_norm = _normalize(away_team or "")

    home_wins = away_wins = draws = 0
    for entry in rows:
        score = str(entry.get("score", ""))
        m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score)
        if not m:
            continue
        gh, ga = int(m.group(1)), int(m.group(2))
        r_home = _normalize(str(entry.get("home", "")))
        r_away = _normalize(str(entry.get("away", "")))

        # Work out which side of the H2H row is which fixture team. Scoring both
        # orientations beats substring matching: sources spell names differently
        # ('Espanol Osorno' vs 'CD Español de Osorno'), and it avoids the
        # single-shared-word trap ('Manchester United' vs 'Manchester City').
        straight = _token_overlap(r_home, home_norm) + _token_overlap(r_away, away_norm)
        flipped = _token_overlap(r_home, away_norm) + _token_overlap(r_away, home_norm)
        if straight == 0 and flipped == 0:
            continue

        if gh == ga:
            draws += 1
            continue

        row_home_won = gh > ga
        if straight >= flipped:
            # Row home == fixture home.
            fixture_home_won = row_home_won
        else:
            fixture_home_won = not row_home_won

        if fixture_home_won:
            home_wins += 1
        else:
            away_wins += 1

    total = home_wins + away_wins + draws
    if not total:
        return

    enrichment["h2h_last5"] = rows
    enrichment["h2h_count"] = total
    enrichment["home_wins_in_h2h_last5"] = home_wins
    enrichment["away_wins_in_h2h_last5"] = away_wins
    enrichment["draws_in_h2h_last5"] = draws
    enrichment.setdefault("h2h_source", "livesport_h2h_page")

    if not enrichment.get("win_rate"):
        focus_wins = away_wins if focus_team == "away" else home_wins
        enrichment["win_rate"] = round(focus_wins / total, 3)

    first = rows[0]
    enrichment.setdefault("last_h2h_date", first.get("date"))
    enrichment.setdefault("last_h2h_score", first.get("score"))
    enrichment.setdefault("last_h2h_home", first.get("home"))
    enrichment.setdefault("last_h2h_away", first.get("away"))


def _fetch_direct_h2h(
    enrichment: Dict[str, Any],
    driver,
    url: str,
    *,
    home_team: str,
    away_team: str,
    focus_team: Optional[str],
) -> bool:
    """Fetch the direct head-to-head table when process_match returned none.

    Navigates straight to ``/h2h/ogolem/`` — the same trick the main pipeline
    uses — instead of relying on the H2H tab click, which fails silently in
    headless CI.
    """
    try:
        from bs4 import BeautifulSoup

        from livesport_h2h_scraper import (
            build_h2h_overall_url,
            is_livesport_error_page,
            parse_h2h_from_soup,
        )
    except ImportError as exc:
        logger.debug("direct H2H helpers unavailable: %s", exc)
        return False

    h2h_url = build_h2h_overall_url(url)
    if not h2h_url:
        return False

    try:
        print("   ⚔️ Pobieram bezpośredni H2H...")
        driver.get(h2h_url)
        time.sleep(3.0)
        page = driver.page_source
        if is_livesport_error_page(page):
            return False
        soup = BeautifulSoup(page, "html.parser")
        rows = parse_h2h_from_soup(soup, home_team or "") or []
    except Exception as exc:
        logger.debug("direct H2H fetch failed for %s: %s", h2h_url, exc)
        return False

    if not rows:
        return False

    before = enrichment.get("h2h_count")
    _summarize_h2h(
        enrichment,
        rows,
        home_team=home_team,
        away_team=away_team,
        focus_team=focus_team,
    )
    if enrichment.get("h2h_last5"):
        print(f"   ✅ H2H bezpośredni: {len(enrichment['h2h_last5'])} spotkań")
        return enrichment.get("h2h_count") != before
    return False


def _apply_tennis_form_aliases(enrichment: Dict[str, Any]) -> None:
    """Map tennis player-form fields onto the generic form keys.

    ``process_match_tennis`` reports form as ``form_a``/``form_b`` and the
    venue analogue as ``surface_form_a``/``surface_form_b``. The mail layer
    reads the generic ``home_form``/``away_form`` names, so alias them here.
    Tennis has no home/away venue split, hence no ``*_form_home`` mapping.
    """
    for generic, tennis_key in (("home", "form_a"), ("away", "form_b")):
        val = enrichment.get(tennis_key) or []
        if val and not (
            enrichment.get(f"{generic}_form") or enrichment.get(f"{generic}_form_overall")
        ):
            enrichment[f"{generic}_form"] = val
            enrichment[f"{generic}_form_overall"] = val
            enrichment.setdefault("form_source", "livesport_tennis")


def _enrich_row(
    driver,
    row: DroppingOddsRow,
    *,
    date: str,
    use_forebet: bool = True,
    use_sofascore: bool = True,
) -> Dict[str, Any]:
    """Run the costly Livesport enrichment for one qualifying row.
    
    For dropping odds, we ALWAYS want form data regardless of H2H
    qualification. If process_match didn't extract form (because the
    match didn't pass H2H ≥60%), we call extract_advanced_team_form
    directly as a fallback.
    """
    result: Dict[str, Any] = {
        "status": "resolve_failed",
        "livesport_url": None,
        "livesport_confidence": 0.0,
        "focus_team": None,
        "away_team_focus": False,
        "enrichment": None,
        "error": None,
    }

    focus_team, away_focus = _focus_team_from_outcome(row.outcome)
    result["focus_team"] = focus_team
    result["away_team_focus"] = away_focus

    sport = row.sport or "football"

    url, confidence = resolve_livesport_match_url(
        driver,
        home_team=row.home_team,
        away_team=row.away_team,
        sport=sport,
        date=date,
    )
    result["livesport_url"] = url
    result["livesport_confidence"] = round(confidence, 3)

    if not url:
        # Livesport could not match the fixture (common for South American and
        # Australian leagues). Fall back to SofaScore rather than reporting the
        # event with no form at all.
        fallback: Dict[str, Any] = {}
        if _fill_form_from_sofascore(
            fallback,
            home_team=row.home_team,
            away_team=row.away_team,
            sport=sport,
            focus_team=focus_team,
            date=date,
        ):
            fallback.setdefault("home_team", row.home_team)
            fallback.setdefault("away_team", row.away_team)
            fallback.setdefault("sport", sport)
            fallback.setdefault("league", row.league)
            fallback.setdefault("match_time", row.event_time)
            # Livesport gave us nothing, so this is the only chance at venue
            # form and the H2H list for this fixture.
            if sport != "tennis":
                _fill_venue_and_h2h_from_sofascore(
                    fallback,
                    home_team=row.home_team,
                    away_team=row.away_team,
                    sport=sport,
                    focus_team=focus_team,
                    date=date,
                )
            # Fan Vote i Forebet też nie zależą od Livesportu.
            _fill_votes_and_forebet(
                fallback,
                driver,
                home_team=row.home_team,
                away_team=row.away_team,
                sport=sport,
                date=date,
                use_forebet=use_forebet,
                use_sofascore=use_sofascore,
            )
            result["status"] = "enriched_sofascore_only"
            result["enrichment"] = fallback
            print(
                f"   🔁 Livesport nie znalazł meczu — SofaScore: "
                f"H={fallback.get('home_form')} | A={fallback.get('away_form')}"
            )
        return result

    try:
        if sport == "tennis":
            from livesport_h2h_scraper import process_match_tennis

            info = process_match_tennis(url, driver)
        else:
            from livesport_h2h_scraper import process_match

            info = process_match(
                url,
                driver,
                away_team_focus=away_focus,
                use_forebet=use_forebet,
                use_sofascore=use_sofascore,
                sport=sport,
            )
    except Exception as exc:
        result["status"] = "process_match_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("process_match failed for %s", url)
        return result

    result["status"] = "enriched"
    result["enrichment"] = _compact_enrichment(info)
    
    # DROPPING ODDS FORM EXTRACTION: Multi-strategy approach
    # process_match's form extraction often fails for sports other than basketball.
    # We try 3 strategies in order: (1) advanced H2H pages, (2) re-parse match
    # page directly, (3) derive from h2h_last5 results.
    enrichment = result["enrichment"]
    resolved_home = enrichment.get("home_team") or row.home_team
    resolved_away = enrichment.get("away_team") or row.away_team

    if sport == "tennis":
        # Tennis: expose player form under the generic keys, and make sure the
        # direct H2H table is present (surface form is the venue analogue and
        # already comes out of process_match_tennis).
        _apply_tennis_form_aliases(enrichment)
        if not enrichment.get("h2h_last5"):
            _fetch_direct_h2h(
                enrichment,
                driver,
                url,
                home_team=resolved_home,
                away_team=resolved_away,
                focus_team=focus_team,
            )
    else:
        # Venue form (u siebie / na wyjeździe) — ALWAYS, matching the main
        # pipeline. Running this only as a fallback meant it was skipped
        # whenever overall form happened to be present.
        print("   📊 Forma szczegółowa (ogólna + u siebie / na wyjeździe)...")
        _apply_venue_form(enrichment, driver, url)

        # Direct H2H table, if process_match's tab click came back empty.
        if not enrichment.get("h2h_last5"):
            _fetch_direct_h2h(
                enrichment,
                driver,
                url,
                home_team=resolved_home,
                away_team=resolved_away,
                focus_team=focus_team,
            )

        existing_home = enrichment.get("home_form_overall") or enrichment.get("home_form") or []
        existing_away = enrichment.get("away_form_overall") or enrichment.get("away_form") or []

        # Strategy 2: Re-parse the match page directly for form badges in team header
        if not (existing_home and existing_away):
            try:
                from livesport_h2h_scraper import extract_team_form
                from bs4 import BeautifulSoup
                print(f"   📊 Strategy 2: forma z nagłówka meczu...")
                # Navigate to the bare match URL (not H2H sub-page)
                match_base = url.split("?")[0].rstrip("/")
                if match_base.endswith("/h2h") or "/h2h/" in match_base:
                    match_base = match_base.split("/h2h")[0]
                if not match_base.endswith("/szczegoly"):
                    match_base = match_base + "/"
                driver.get(match_base)
                time.sleep(3.0)
                soup = BeautifulSoup(driver.page_source, "html.parser")
                home_team = info.get("home_team", "") if info else row.home_team
                away_team = info.get("away_team", "") if info else row.away_team
                if not existing_home:
                    s2_home = extract_team_form(soup, driver, "home", home_team)
                    if s2_home:
                        enrichment["home_form"] = s2_home
                        enrichment["home_form_overall"] = s2_home
                        existing_home = s2_home
                if not existing_away:
                    s2_away = extract_team_form(soup, driver, "away", away_team)
                    if s2_away:
                        enrichment["away_form"] = s2_away
                        enrichment["away_form_overall"] = s2_away
                        existing_away = s2_away
                if existing_home or existing_away:
                    print(f"   ✅ Strategy 2: H={existing_home} | A={existing_away}")
            except Exception as exc:
                logger.debug("Match-page form re-parse failed: %s", exc)
    
    # Backfill H2H aggregates when the per-meeting list exists but the counts
    # do not (process_match only fills them on the qualifying path).
    if enrichment.get("h2h_last5") and not enrichment.get("h2h_count"):
        _summarize_h2h(
            enrichment,
            enrichment["h2h_last5"],
            home_team=resolved_home,
            away_team=resolved_away,
            focus_team=focus_team,
        )

    # Strategy 3: Derive form from h2h_last5 results (always works if H2H exists)
    final_home_form = enrichment.get("home_form_overall") or enrichment.get("home_form") or []
    final_away_form = enrichment.get("away_form_overall") or enrichment.get("away_form") or []
    if not (final_home_form and final_away_form):
        h2h_last5 = enrichment.get("h2h_last5") or (info.get("h2h_last5") if info else None) or []
        if h2h_last5:
            home_team = enrichment.get("home_team") or row.home_team
            away_team = enrichment.get("away_team") or row.away_team
            home_form_h2h, away_form_h2h = _derive_form_from_h2h(
                h2h_last5, home_team, away_team
            )
            if home_form_h2h and not final_home_form:
                enrichment["home_form"] = home_form_h2h
                enrichment["home_form_overall"] = home_form_h2h
                enrichment["form_source"] = "h2h_derived"
            if away_form_h2h and not final_away_form:
                enrichment["away_form"] = away_form_h2h
                enrichment["away_form_overall"] = away_form_h2h
                enrichment["form_source"] = "h2h_derived"
            if home_form_h2h or away_form_h2h:
                print(f"   📊 Strategy 3 (H2H-derived): H={home_form_h2h} | A={away_form_h2h}")
    
    # Strategy 4: SofaScore API — independent of Livesport's DOM, so it also
    # covers the cases where Livesport renders no form badges at all. Fills
    # missing sides only, and adds H2H when Livesport gave none.
    final_home = enrichment.get("home_form_overall") or enrichment.get("home_form") or []
    final_away = enrichment.get("away_form_overall") or enrichment.get("away_form") or []
    if not (final_home and final_away):
        filled = _fill_form_from_sofascore(
            enrichment,
            home_team=enrichment.get("home_team") or row.home_team,
            away_team=enrichment.get("away_team") or row.away_team,
            sport=sport,
            focus_team=focus_team,
            date=date,
        )
        if filled:
            final_home = enrichment.get("home_form") or final_home
            final_away = enrichment.get("away_form") or final_away
            print(f"   ✅ Strategy 4 (SofaScore): H={final_home} | A={final_away}")

    if not (final_home or final_away):
        print(f"   ⚠️ Wszystkie 4 strategie zawiodły — brak formy")

    # Strategy 5: venue form + per-meeting H2H from SofaScore. Deliberately
    # independent of whether overall form was found, because Livesport commonly
    # returns overall form while leaving the venue sub-pages and H2H table
    # empty. Tennis is excluded: its venue analogue is surface form, which
    # process_match_tennis already provides.
    if sport != "tennis":
        _fill_venue_and_h2h_from_sofascore(
            enrichment,
            home_team=enrichment.get("home_team") or row.home_team,
            away_team=enrichment.get("away_team") or row.away_team,
            sport=sport,
            focus_team=focus_team,
            date=date,
        )

    # Strategy 6: Fan Vote (API) + Forebet. Independent of the Livesport path,
    # which is where they were previously stuck.
    _fill_votes_and_forebet(
        enrichment,
        driver,
        home_team=enrichment.get("home_team") or row.home_team,
        away_team=enrichment.get("away_team") or row.away_team,
        sport=sport,
        date=date,
        use_forebet=use_forebet,
        use_sofascore=use_sofascore,
    )

    return result


def _sport_has_draws(sport: Optional[str]) -> bool:
    """True for sports where a draw is a possible result.

    Matters for form strings: in draw-capable sports a tie must be recorded as
    'D' rather than dropped, otherwise the "last 5" window silently reaches
    further back than it claims.
    """
    return (sport or "").lower() in {"football", "handball", "hockey", "rugby"}


def _fill_form_from_sofascore(
    enrichment: Dict[str, Any],
    *,
    home_team: str,
    away_team: str,
    sport: str,
    focus_team: Optional[str] = None,
    date: Optional[str] = None,
) -> bool:
    """Fill missing form (and H2H) in *enrichment* from the SofaScore API.

    Mutates *enrichment* in place. Returns True when anything was added.
    """
    try:
        from sofascore_scraper import (
            SOFASCORE_SPORT_SLUGS,
            find_event_via_team_schedule,
            get_event_h2h,
            get_team_recent_form,
            search_event_via_api,
        )
    except ImportError as exc:
        logger.debug("SofaScore form fallback unavailable: %s", exc)
        return False

    slug = SOFASCORE_SPORT_SLUGS.get(sport, sport)

    # The schedule walk also gives us both team IDs, which the plain event
    # search does not — and team IDs are what the form endpoint needs.
    try:
        found = find_event_via_team_schedule(
            home_team, away_team, slug, date_str=date
        )
    except Exception as exc:
        logger.debug("SofaScore schedule lookup failed: %s", exc)
        found = None

    if not found:
        # Last resort: resolve just the event ID for the H2H numbers.
        try:
            event_id = search_event_via_api(home_team, away_team, sport)
        except Exception:
            event_id = None
        if not event_id:
            return False
        found = {"event_id": event_id, "home_team_id": None, "away_team_id": None}

    changed = False

    for side, id_key in (("home", "home_team_id"), ("away", "away_team_id")):
        if enrichment.get(f"{side}_form") or enrichment.get(f"{side}_form_overall"):
            continue
        team_id = found.get(id_key)
        if not team_id:
            continue
        try:
            form = get_team_recent_form(
                team_id, "", limit=5, allow_draws=_sport_has_draws(sport)
            )
        except Exception:
            form = []
        if form:
            enrichment[f"{side}_form"] = form
            enrichment[f"{side}_form_overall"] = form
            enrichment["form_source"] = "sofascore_api"
            changed = True

    if not enrichment.get("h2h_count"):
        try:
            h2h = get_event_h2h(found.get("event_id"))
        except Exception:
            h2h = None
        if h2h and h2h.get("total"):
            total = h2h["total"]
            enrichment["h2h_count"] = total
            enrichment["home_wins_in_h2h_last5"] = h2h.get("home_wins")
            enrichment["away_wins_in_h2h_last5"] = h2h.get("away_wins")
            enrichment["h2h_source"] = "sofascore_api"
            if not enrichment.get("win_rate"):
                focus_wins = (
                    h2h.get("away_wins") if focus_team == "away"
                    else h2h.get("home_wins")
                )
                # 0-1 fraction; the email multiplies by 100.
                enrichment["win_rate"] = round((focus_wins or 0) / total, 3)
            changed = True

    if found.get("event_id"):
        enrichment.setdefault("sofascore_event_id", found["event_id"])
    # Cache the team IDs so the venue/H2H fill does not repeat this lookup.
    if found.get("home_team_id"):
        enrichment.setdefault("sofascore_home_team_id", found["home_team_id"])
    if found.get("away_team_id"):
        enrichment.setdefault("sofascore_away_team_id", found["away_team_id"])

    return changed


def _fill_venue_and_h2h_from_sofascore(
    enrichment: Dict[str, Any],
    *,
    home_team: str,
    away_team: str,
    sport: str,
    focus_team: Optional[str] = None,
    date: Optional[str] = None,
) -> bool:
    """Fill venue form and the per-meeting H2H list from SofaScore.

    Runs regardless of whether overall form is already present, because those
    are separate gaps: Livesport frequently yields overall form while the venue
    sub-pages and the H2H table come back empty, and for the ~half of fixtures
    Livesport cannot match by name there is no Livesport data at all. SofaScore
    covers both from team IDs, which is what makes per-event parity possible.

    Mutates *enrichment*; returns True when anything was added.
    """
    needs_venue = not (
        enrichment.get("home_form_home") and enrichment.get("away_form_away")
    )
    needs_h2h = not enrichment.get("h2h_last5")
    if not (needs_venue or needs_h2h):
        return False

    try:
        from sofascore_scraper import (
            SOFASCORE_SPORT_SLUGS,
            find_event_via_team_schedule,
            get_event_team_ids,
            get_h2h_matches,
            get_team_venue_form,
            search_event_via_api,
        )
    except ImportError as exc:
        logger.debug("SofaScore venue/H2H fill unavailable: %s", exc)
        return False

    # Reuse whatever an earlier SofaScore step already resolved for this event.
    home_id = enrichment.get("sofascore_home_team_id")
    away_id = enrichment.get("sofascore_away_team_id")
    event_id = enrichment.get("sofascore_event_id")

    slug = SOFASCORE_SPORT_SLUGS.get(sport, sport)
    if not (home_id and away_id):
        try:
            found = find_event_via_team_schedule(
                home_team, away_team, slug, date_str=date
            )
        except Exception as exc:
            logger.debug("SofaScore schedule lookup failed: %s", exc)
            found = None
        if found:
            home_id = home_id or found.get("home_team_id")
            away_id = away_id or found.get("away_team_id")
            event_id = event_id or found.get("event_id")

    if not event_id:
        try:
            event_id = search_event_via_api(home_team, away_team, sport)
        except Exception:
            event_id = None

    # Team IDs are what the venue/H2H endpoints need; the plain event search
    # does not return them, so resolve them from the event when missing.
    if (not home_id or not away_id) and event_id:
        try:
            ids = get_event_team_ids(event_id)
        except Exception:
            ids = None
        if ids:
            home_id = home_id or ids.get("home_team_id")
            away_id = away_id or ids.get("away_team_id")

    if not home_id and not away_id:
        return False

    if event_id:
        enrichment.setdefault("sofascore_event_id", event_id)
    if home_id:
        enrichment.setdefault("sofascore_home_team_id", home_id)
    if away_id:
        enrichment.setdefault("sofascore_away_team_id", away_id)

    changed = False
    allow_draws = _sport_has_draws(sport)

    if needs_venue:
        if not enrichment.get("home_form_home") and home_id:
            try:
                hv = get_team_venue_form(
                    home_id, "home", limit=5, allow_draws=allow_draws
                )
            except Exception:
                hv = []
            if hv:
                enrichment["home_form_home"] = hv
                changed = True
        if not enrichment.get("away_form_away") and away_id:
            try:
                av = get_team_venue_form(
                    away_id, "away", limit=5, allow_draws=allow_draws
                )
            except Exception:
                av = []
            if av:
                enrichment["away_form_away"] = av
                changed = True
        if changed:
            enrichment["venue_form_source"] = "sofascore_api"
            print(
                f"   🏠 SofaScore venue: u siebie={enrichment.get('home_form_home')}"
                f" | wyjazd={enrichment.get('away_form_away')}"
            )

    if needs_h2h and home_id and away_id:
        try:
            rows = get_h2h_matches(home_id, away_id, limit=5)
        except Exception:
            rows = []
        if rows:
            _summarize_h2h(
                enrichment,
                rows,
                home_team=home_team,
                away_team=away_team,
                focus_team=focus_team,
            )
            enrichment["h2h_source"] = "sofascore_api"
            print(f"   ⚔️ SofaScore H2H: {len(rows)} spotkań")
            changed = True

    return changed


def _fill_votes_and_forebet(
    enrichment: Dict[str, Any],
    driver,
    *,
    home_team: str,
    away_team: str,
    sport: str,
    date: Optional[str] = None,
    use_forebet: bool = True,
    use_sofascore: bool = True,
) -> bool:
    """Fill SofaScore Fan Vote and the Forebet prediction.

    Both already run inside ``process_match``, but only on the Livesport path
    and only when its earlier steps succeed — measured coverage on 2026-08-10
    was 7 of 40 events for Fan Vote and 0 for Forebet. Running them as an
    independent step covers the SofaScore-only events too.

    Fan Vote goes through the API endpoint (``/event/{id}/votes``), so it needs
    no browser; it only requires the event ID that the earlier SofaScore steps
    already resolved. Forebet needs the page, so it reuses *driver*.

    Mutates *enrichment*; returns True when anything was added.
    """
    changed = False

    if use_sofascore and enrichment.get("sofascore_total_votes") is None:
        event_id = enrichment.get("sofascore_event_id")
        if event_id:
            try:
                from sofascore_scraper import get_votes_via_api

                votes = get_votes_via_api(int(event_id))
            except Exception as exc:
                logger.debug("Fan Vote lookup failed: %s", exc)
                votes = None
            if votes:
                enrichment.update(votes)
                changed = True
                print(
                    f"   🗳️ Fan Vote: {votes.get('sofascore_home_win_prob')}%"
                    f" / {votes.get('sofascore_draw_prob')}%"
                    f" / {votes.get('sofascore_away_win_prob')}%"
                    f" ({votes.get('sofascore_total_votes')} głosów)"
                )

    if use_forebet and not enrichment.get("forebet_prediction") and driver is not None:
        try:
            from forebet_scraper import search_forebet_prediction

            fb = search_forebet_prediction(
                home_team,
                away_team,
                match_date=date or "",
                driver=driver,
                sport=sport,
                # Forebet wymaga trybu widocznego — tak samo jak w głównym
                # pipeline; w CI obsługuje to xvfb (use_xvfb auto-detect).
                headless=False,
            )
        except Exception as exc:
            logger.debug("Forebet lookup failed: %s", exc)
            fb = None

        # Główny pipeline bramkuje na 'success' — bez tego częściowy wynik
        # trafiałby do maila jako pełna predykcja.
        if isinstance(fb, dict) and fb.get("success"):
            for key in (
                "prediction", "probability", "exact_score", "over_under",
                "btts", "avg_goals", "home_prob", "draw_prob", "away_prob",
            ):
                val = fb.get(key)
                if val is not None:
                    enrichment[f"forebet_{key}"] = val
            changed = True
            print(
                f"   🔮 Forebet: {fb.get('prediction')}"
                f" ({fb.get('probability')}%)"
            )

    return changed


def _derive_form_from_h2h(
    h2h: List[Dict[str, Any]],
    home_team: str,
    away_team: str,
) -> Tuple[List[str], List[str]]:
    """Derive W/D/L form lists for both teams from H2H results.
    
    For each H2H entry we determine if the home/away team won, drew, or lost
    by parsing the score (e.g., "2:1") and matching team names.
    """
    home_form: List[str] = []
    away_form: List[str] = []
    
    home_norm = _normalize(home_team or "")
    away_norm = _normalize(away_team or "")
    
    for entry in h2h[:5]:
        score = str(entry.get("score", ""))
        m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score)
        if not m:
            continue
        gh = int(m.group(1))
        ga = int(m.group(2))
        
        h2h_home = _normalize(str(entry.get("home", "")))
        h2h_away = _normalize(str(entry.get("away", "")))
        
        # Determine result for home_team (today's home)
        if home_norm and (home_norm in h2h_home or h2h_home in home_norm):
            # Today's home was the home team in this H2H
            if gh > ga:
                home_form.append("W")
            elif gh < ga:
                home_form.append("L")
            else:
                home_form.append("D")
        elif home_norm and (home_norm in h2h_away or h2h_away in home_norm):
            # Today's home was the away team in this H2H
            if ga > gh:
                home_form.append("W")
            elif ga < gh:
                home_form.append("L")
            else:
                home_form.append("D")
        
        # Determine result for away_team (today's away)
        if away_norm and (away_norm in h2h_away or h2h_away in away_norm):
            if ga > gh:
                away_form.append("W")
            elif ga < gh:
                away_form.append("L")
            else:
                away_form.append("D")
        elif away_norm and (away_norm in h2h_home or h2h_home in away_norm):
            if gh > ga:
                away_form.append("W")
            elif gh < ga:
                away_form.append("L")
            else:
                away_form.append("D")
    
    return home_form, away_form


_KEEP_KEYS = (
    "home_team", "away_team", "match_time", "sport", "league",
    "h2h_count", "home_wins_in_h2h_last5", "away_wins_in_h2h_last5",
    "win_rate", "qualifies", "home_form", "away_form",
    "home_form_overall", "away_form_overall",
    "home_form_home", "away_form_away",
    "home_odds", "draw_odds", "away_odds",
    "forebet_prediction", "forebet_probability",
    "forebet_over_under", "forebet_btts",
    "forebet_exact_score", "forebet_avg_goals",
    "forebet_home_prob", "forebet_draw_prob", "forebet_away_prob",
    "sofascore_btts_yes", "sofascore_btts_no",
    "sofascore_home_win_prob", "sofascore_draw_prob", "sofascore_away_win_prob",
    "sofascore_total_votes",
    "favorite", "advanced_score", "tennis_skip_reason",
    "h2h_last5", "last_h2h_date", "last_h2h_score",
    "last_h2h_home", "last_h2h_away",
    "draws_in_h2h_last5",
    "form_advantage", "away_advantage", "form_source",
    "venue_form_source", "h2h_source",
    "sofascore_event_id", "sofascore_home_team_id", "sofascore_away_team_id",
    # Tennis: the venue-form analogue is surface form, so these must survive
    # into the JSON for the mail/scoring layer to be able to show it.
    "surface", "surface_form_a", "surface_form_b",
    "surface_stats_a", "surface_stats_b",
    "form_a", "form_b",
    "tennis_data_warnings", "tennis_phase_path",
    "ranking_a", "ranking_b",
)


def _compact_enrichment(info: Dict[str, Any]) -> Dict[str, Any]:
    """Return only the fields used downstream, dropping heavy Selenium refs."""
    if not isinstance(info, dict):
        return {}
    compact: Dict[str, Any] = {}
    for key in _KEEP_KEYS:
        if key in info:
            compact[key] = info[key]
    return compact


# ---------------------------------------------------------------------------
# Output serialization
# ---------------------------------------------------------------------------


def _serialize_event(
    row: DroppingOddsRow,
    *,
    qualifies: bool,
    skip_reason: Optional[str],
    enrichment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event = row.to_dict()
    event["qualifies"] = qualifies
    event["skip_reason"] = skip_reason
    focus_team, away_focus = _focus_team_from_outcome(row.outcome)
    event["dropped_outcome"] = row.outcome
    event["focus_team"] = focus_team
    event["away_team_focus"] = away_focus
    if enrichment is not None:
        event["enrichment_status"] = enrichment.get("status")
        event["livesport_url"] = enrichment.get("livesport_url")
        event["livesport_confidence"] = enrichment.get("livesport_confidence")
        event["enrichment"] = enrichment.get("enrichment")
        event["enrichment_error"] = enrichment.get("error")
    return event


def _write_output(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape OddsSafari dropping odds across every sport, then enrich "
            "qualifying rows with Livesport (H2H + form) + Forebet + SofaScore."
        )
    )
    parser.add_argument("--date", help="Date for Livesport lookup (YYYY-MM-DD); "
                                       "defaults to today in Europe/Warsaw.")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="Run Chrome headless (default).")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Show the browser window (for debugging).")
    parser.add_argument("--min-odds", type=float, default=None,
                        help="Override the lower bound of qualifying current odds. "
                             "Omit to use the per-sport range (football 1.80, "
                             "handball/hockey 1.60, others 1.35).")
    parser.add_argument("--max-odds", type=float, default=None,
                        help="Override the upper bound of qualifying current odds. "
                             "Omit to use the per-sport range (2.50 everywhere).")
    parser.add_argument("--max-enrich", type=int, default=0,
                        help="Cap on how many events get the costly form/H2H "
                             "enrichment. Events are enriched biggest-drop-first; "
                             "the rest still appear in the report without form. "
                             "0 = enrich everything.")
    parser.add_argument("--max-rows", type=int, default=0,
                        help="Optional cap on rows processed end-to-end (0 = no cap).")
    parser.add_argument("--max-pages", type=int, default=20,
                        help="Deprecated / no-op: OddsSafari paginates in the "
                             "browser and ships every row in one response, so "
                             "all pages are always collected.")
    parser.add_argument("--sport-ids", default="",
                        help="Comma-separated OddsSafari sport IDs; empty = auto.")
    parser.add_argument("--sport", default="",
                        help="Filter to one internal sport (football, basketball, "
                             "tennis, hockey, handball, volleyball, baseball, rugby). "
                             "Auto-selects the matching OddsSafari sport IDs and "
                             "filters rows to that sport. Empty = all sports.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip the Livesport enrichment phase entirely.")
    parser.add_argument("--selenium-fallback", dest="selenium_fallback",
                        action="store_true", default=True,
                        help="Retry OddsSafari collection with Selenium when "
                             "the HTTP path returns no rows (default).")
    parser.add_argument("--no-selenium-fallback", dest="selenium_fallback",
                        action="store_false",
                        help="Never fall back to Selenium for OddsSafari.")
    parser.add_argument("--no-forebet", dest="use_forebet", action="store_false",
                        help="Disable Forebet enrichment inside process_match.")
    parser.add_argument("--no-sofascore", dest="use_sofascore", action="store_false",
                        help="Disable SofaScore fan-vote enrichment.")
    parser.add_argument("--output", default="",
                        help="Override output JSON path (default: outputs/oddssafari_dropping_{date}.json).")
    parser.set_defaults(use_forebet=True, use_sofascore=True)
    return parser.parse_args(argv)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(argv: Optional[List[str]] = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    target_date = args.date or datetime.now(WARSAW_TZ).strftime("%Y-%m-%d")
    sport_filter = (args.sport or "").strip().lower() or None
    suffix = f"_{sport_filter}" if sport_filter else ""
    output_path = (
        args.output
        or f"outputs/oddssafari_dropping_{target_date}{suffix}.json"
    )

    print("=" * 70)
    print("OddsSafari Dropping Odds Pipeline")
    print("=" * 70)
    print(f"  Date (Livesport):   {target_date}")
    if args.min_odds is None and args.max_odds is None:
        _rng = odds_range_for_sport(sport_filter) if sport_filter else None
        range_label = (
            f"[{_rng[0]:.2f}, {_rng[1]:.2f}] (per-sport)" if _rng
            else "per-sport ranges"
        )
    else:
        _lo = f"{args.min_odds:.2f}" if args.min_odds is not None else "per-sport"
        _hi = f"{args.max_odds:.2f}" if args.max_odds is not None else "per-sport"
        range_label = f"[{_lo}, {_hi}] (override)"
    print(f"  Qualifying range:   {range_label}")
    print(f"  Enrichment cap:     {args.max_enrich or 'none (all qualifying)'}")
    print(f"  Sport filter:       {sport_filter or 'ALL'}")
    print(f"  Output:             {output_path}")
    print(f"  Mode:               {'DRY-RUN' if args.dry_run else 'FULL'}")
    print("=" * 70)

    run_started = time.time()

    # The browser is expensive and only the Livesport enrichment needs it, so
    # it is started lazily on first use. OddsSafari itself is server-rendered
    # and scraped over plain HTTP.
    driver_holder: Dict[str, Any] = {"driver": None}

    def _get_driver():
        if driver_holder["driver"] is None:
            from livesport_h2h_scraper import start_driver
            print("🌐 Startuję przeglądarkę (Livesport enrichment)...")
            driver_holder["driver"] = start_driver(headless=args.headless)
        return driver_holder["driver"]

    try:
        sport_ids = [s.strip() for s in args.sport_ids.split(",") if s.strip()]

        # OddsSafari renumbered its sport tabs (they are multiples of 10 now),
        # so a stale hardcoded ID silently returned zero rows. Collection over
        # HTTP discovers the right page ID by content when --sport is given.
        rows = collect_rows_via_http(
            sport=sport_filter,
            sport_page_ids=sport_ids or None,
            max_pages_per_sport=args.max_pages,
        )

        if not rows and args.selenium_fallback:
            logger.warning("HTTP collection returned 0 rows — trying Selenium")
            rows = collect_dropping_odds_rows(
                _get_driver(),
                sport_page_ids=sport_ids or None,
                max_pages_per_sport=args.max_pages,
            )

        # Post-filter rows by sport when --sport is provided. The OddsSafari
        # page IDs sometimes contain other sports (especially "all"), and
        # we want a clean per-sport JSON for the email pipeline.
        # NOTE: If sport field is None (slug parsing failed), we keep the row
        # when we explicitly targeted that sport's page ID — the page itself
        # is sport-specific so the row belongs to that sport.
        if sport_filter:
            before = len(rows)
            rows = [
                r for r in rows
                if (r.sport or "").lower() == sport_filter
                or r.sport is None  # slug parsing failed, but page is sport-specific
            ]
            # Also set the sport field for rows where it was None
            for r in rows:
                if r.sport is None:
                    r.sport = sport_filter
            logger.info(
                "Sport filter '%s' kept %d/%d rows", sport_filter, len(rows), before
            )

        if args.max_rows:
            rows = rows[: args.max_rows]
        logger.info("OddsSafari returned %d rows in total", len(rows))

        # Enrich biggest drops first so that, when --max-enrich caps the work,
        # the events that carry the most signal are the ones with form data.
        rows.sort(key=lambda r: (r.drop_pct or 0.0), reverse=True)
        enrich_budget = args.max_enrich if args.max_enrich and args.max_enrich > 0 else None
        enriched_so_far = 0
        # Set to an error string once the browser proves unusable, so we stop
        # retrying it for every remaining row.
        browser_unavailable: Optional[str] = None

        events: List[Dict[str, Any]] = []
        qualified: List[Dict[str, Any]] = []
        reason_counts: Dict[str, int] = {}
        enrichment_counts: Dict[str, int] = {
            "enriched": 0, "resolve_failed": 0, "process_match_error": 0,
        }

        for idx, row in enumerate(rows, 1):
            qualifies, skip_reason = is_qualifying_row(
                row, min_odds=args.min_odds, max_odds=args.max_odds
            )
            enrichment: Optional[Dict[str, Any]] = None

            budget_left = enrich_budget is None or enriched_so_far < enrich_budget

            if qualifies and not args.dry_run and not budget_left:
                # Still reported, just without form/H2H.
                enrichment = {
                    "status": "skipped_enrich_budget",
                    "livesport_url": None,
                    "livesport_confidence": 0.0,
                    "enrichment": None,
                    "error": None,
                }
                enrichment_counts["skipped_enrich_budget"] = (
                    enrichment_counts.get("skipped_enrich_budget", 0) + 1
                )
            elif qualifies and not args.dry_run:
                enriched_so_far += 1
                print(
                    f"[{idx}/{len(rows)}] enrich {row.home_team} vs "
                    f"{row.away_team} ({row.sport_slug}, outcome={row.outcome}, "
                    f"current={row.current_odds})"
                )
                if uses_sofascore_only_enrichment(row.sport):
                    # e-sports: Livesport has no section for it, so form and
                    # H2H come straight from the SofaScore API.
                    enrichment = _enrich_row_via_sofascore(row)
                elif browser_unavailable:
                    enrichment = {
                        "status": "browser_unavailable",
                        "livesport_url": None,
                        "livesport_confidence": 0.0,
                        "enrichment": None,
                        "error": browser_unavailable,
                    }
                else:
                    # A browser failure must not sink the whole run: the
                    # OddsSafari rows are already collected and still worth
                    # reporting without form data.
                    try:
                        enrichment = _enrich_row(
                            _get_driver(), row,
                            date=target_date,
                            use_forebet=args.use_forebet,
                            use_sofascore=args.use_sofascore,
                        )
                    except Exception as exc:
                        browser_unavailable = f"{type(exc).__name__}: {exc}"
                        logger.error(
                            "Browser/enrichment unavailable, continuing without "
                            "form data: %s", browser_unavailable,
                        )
                        enrichment = {
                            "status": "browser_unavailable",
                            "livesport_url": None,
                            "livesport_confidence": 0.0,
                            "enrichment": None,
                            "error": browser_unavailable,
                        }
                status = enrichment.get("status") or "resolve_failed"
                enrichment_counts[status] = enrichment_counts.get(status, 0) + 1

            event = _serialize_event(
                row,
                qualifies=qualifies,
                skip_reason=skip_reason,
                enrichment=enrichment,
            )
            events.append(event)

            if qualifies:
                qualified.append(event)
            else:
                reason_counts[skip_reason or "unknown"] = (
                    reason_counts.get(skip_reason or "unknown", 0) + 1
                )

        payload = {
            "meta": {
                "generated_at": datetime.now(WARSAW_TZ).isoformat(),
                "target_date": target_date,
                "filter": {
                    # Report the range that was actually applied so the email
                    # header matches reality (per-sport unless overridden).
                    "min_odds": (
                        args.min_odds if args.min_odds is not None
                        else odds_range_for_sport(sport_filter)[0]
                    ),
                    "max_odds": (
                        args.max_odds if args.max_odds is not None
                        else odds_range_for_sport(sport_filter)[1]
                    ),
                    "per_sport_range": args.min_odds is None and args.max_odds is None,
                },
                "totals": {
                    "events": len(events),
                    "qualified": len(qualified),
                },
                "enrichment_status_counts": enrichment_counts,
                "skip_reason_counts": reason_counts,
                "elapsed_seconds": round(time.time() - run_started, 1),
                "dry_run": bool(args.dry_run),
            },
            "events": events,
            "qualified": qualified,
        }

        _write_output(output_path, payload)
        print("=" * 70)
        print(f"Total events:  {len(events)}")
        print(f"Qualified:     {len(qualified)}")
        if enrichment_counts:
            print(f"Enrichment:    {enrichment_counts}")
        if reason_counts:
            print(f"Skip reasons:  {reason_counts}")
        print(f"Saved:         {output_path}")
        print("=" * 70)
        return 0
    finally:
        if driver_holder["driver"] is not None:
            try:
                driver_holder["driver"].quit()
            except Exception:  # pragma: no cover
                pass


if __name__ == "__main__":
    sys.exit(main())
