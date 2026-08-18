"""
OddsSafari upcoming-odds pipeline — full card + price drops + Livesport form
===========================================================================

Why this exists next to ``oddssafari_dropping_pipeline.py``: the dropping-odds
table only lists *outcomes that moved*. It answers "what changed?" but it can
never answer "what is on tonight and who does the market favour?", because a
fixture nobody repriced simply is not there. The daily coupon
(``/coupons/full/sports/{id}``) carries the **whole** 1-X-2 card together with
``NumOfBookmakers`` per outcome, which is the consensus/liquidity signal.

So this pipeline joins the two sources and adds form:

    coupon (full card: 1/X/2 prices, bookmaker counts, kickoff)
        |
        +-- joined on OddsSafari EventID with the dropping-odds table
        |   (open -> current -> drop%, plus the best price on the market)
        |
        +-- filtered to fixtures that have NOT started yet, inside a
        |   rolling horizon (default: the next 12 hours)
        |
        +-- gated by exactly the same qualification rules as the sport
        |   scraper / dropping pipeline (per-sport odds ranges from
        |   SPORT_ODDS_RANGE via is_qualifying_row), plus a bookmaker-count
        |   floor and an optional "must have dropped" rule
        |
        +-- enriched with Livesport general form + H2H by reusing
            oddssafari_dropping_pipeline._enrich_row (same code path as the
            dropping pipeline, so any improvement there lands here too)

The join is exact, not fuzzy: the coupon's ``EventID`` and the dropping table's
``match_id`` are the same identifier (verified 2026-08-17 — 55 of the 88
dropping-odds fixtures for football were present in that day's coupon under the
same id). Fuzzy name matching is kept only as a fallback for rows whose id
could not be parsed out of the URL.

Designed to run **hourly**: prices and drops move through the day, and a
fixture's bookmaker count grows as the market forms.

Usage
-----
    python oddssafari_upcoming_pipeline.py --sport football --hours 12
    python oddssafari_upcoming_pipeline.py --sport football --dry-run
    python oddssafari_upcoming_pipeline.py --sport basketball --require-drop \
        --min-bookmakers 8 --max-enrich 15

Output
------
    outputs/oddssafari_upcoming_{date}_{sport}.json
        {"meta": {...}, "events": [ every fixture ], "qualified": [ subset ]}
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from oddssafari_coupons import (SITE_TZ, CouponOdds, _similarity, coupon_dates,
                               fetch_coupon_board)
from oddssafari_dropping_scraper import (DroppingOddsRow, collect_rows_via_http,
                                        is_enrichable_sport, is_qualifying_row,
                                        odds_range_for_sport)

logger = logging.getLogger(__name__)

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

OUTCOMES: Tuple[str, ...] = ("1", "X", "2")

# Defaults. The horizon is deliberately short: this pipeline runs hourly, and a
# price 12 hours out has not formed yet. The lead time keeps fixtures that are
# about to start (or already in play) out of the report — their odds are no
# longer actionable.
DEFAULT_HORIZON_HOURS = 12.0
DEFAULT_MIN_LEAD_MINUTES = 15
DEFAULT_MIN_BOOKMAKERS = 5

# How close the enriched team names must be to the coupon's before the form is
# trusted. Deliberately lenient — sources spell clubs differently ("Nykobing"
# vs "Nykobing FC") — but strict enough to catch a different fixture entirely.
_MIN_ORIENTATION_SIMILARITY = 0.55


# ---------------------------------------------------------------------------
# Merge model
# ---------------------------------------------------------------------------


@dataclass
class OutcomeMove:
    """How one outcome's price moved, as reported by the dropping-odds table."""

    outcome: str
    open_odds: Optional[float] = None
    current_odds: Optional[float] = None
    drop_pct: Optional[float] = None
    max_odds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "open_odds": self.open_odds,
            "current_odds": self.current_odds,
            "drop_pct": self.drop_pct,
            "max_odds": self.max_odds,
        }


@dataclass
class UpcomingFixture:
    """A coupon fixture, with whatever price movement we know about it."""

    coupon: CouponOdds
    sport: str
    moves: Dict[str, OutcomeMove] = field(default_factory=dict)
    match_id: Optional[str] = None
    join_source: str = "coupon_only"

    @property
    def home_team(self) -> str:
        return self.coupon.home_team

    @property
    def away_team(self) -> str:
        return self.coupon.away_team

    def kickoff_utc(self) -> Optional[datetime]:
        return self.coupon.kickoff_dt()

    def kickoff_local(self) -> Optional[datetime]:
        kickoff = self.kickoff_utc()
        return kickoff.astimezone(WARSAW_TZ) if kickoff else None

    def best_drop(self) -> Optional[OutcomeMove]:
        """The outcome whose price fell the most, when anything fell."""
        moved = [m for m in self.moves.values() if (m.drop_pct or 0) > 0]
        return max(moved, key=lambda m: m.drop_pct or 0.0) if moved else None

    def price(self, outcome: str) -> Optional[float]:
        """Current price for an outcome.

        The dropping table is the fresher of the two feeds — it is what the
        site repriced — so it wins when both carry the outcome.
        """
        move = self.moves.get(outcome)
        if move and move.current_odds:
            return move.current_odds
        return self.coupon.odds_for(outcome)

    def bookmakers_for(self, outcome: str) -> int:
        return int(self.coupon.bookmakers_by_outcome.get(outcome)
                   or self.coupon.bookmakers or 0)


@dataclass
class Candidate:
    """The outcome this pipeline puts forward as the win candidate."""

    outcome: str
    odds: Optional[float]
    bookmakers: int
    drop_pct: Optional[float] = None
    open_odds: Optional[float] = None
    max_odds: Optional[float] = None
    basis: str = "favourite"          # "drop" | "favourite"
    is_market_favourite: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "odds": self.odds,
            "bookmakers": self.bookmakers,
            "drop_pct": self.drop_pct,
            "open_odds": self.open_odds,
            "max_odds": self.max_odds,
            "basis": self.basis,
            "is_market_favourite": self.is_market_favourite,
        }


# ---------------------------------------------------------------------------
# Joining the two feeds (pure — no network)
# ---------------------------------------------------------------------------


def _normalise_name(name: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    stop = {"fc", "sc", "cf", "ac", "the"}
    return " ".join(w for w in text.split() if w not in stop)


def _fixture_key(home: str, away: str) -> str:
    return f"{_normalise_name(home)}|{_normalise_name(away)}"


def index_drops(rows: List[DroppingOddsRow],
                ) -> Tuple[Dict[str, Dict[str, OutcomeMove]],
                           Dict[str, Dict[str, OutcomeMove]]]:
    """Index dropping-odds rows by match id and, as a fallback, by team names.

    One fixture contributes one row per moved outcome, so both indexes map a
    fixture to ``{outcome: OutcomeMove}``. When the same outcome appears twice
    (paging overlap), the bigger drop is kept.
    """
    by_id: Dict[str, Dict[str, OutcomeMove]] = {}
    by_name: Dict[str, Dict[str, OutcomeMove]] = {}

    for row in rows:
        outcome = (row.outcome or "").upper()
        if outcome not in OUTCOMES:
            continue
        move = OutcomeMove(
            outcome=outcome,
            open_odds=row.open_odds,
            current_odds=row.current_odds,
            drop_pct=row.drop_pct,
            max_odds=row.max_odds,
        )
        targets = []
        if row.match_id:
            targets.append(by_id.setdefault(str(row.match_id), {}))
        targets.append(by_name.setdefault(
            _fixture_key(row.home_team, row.away_team), {}))
        for bucket in targets:
            existing = bucket.get(outcome)
            if existing is None or (move.drop_pct or 0) > (existing.drop_pct or 0):
                bucket[outcome] = move

    return by_id, by_name


def merge_board_with_drops(board: List[CouponOdds],
                           drop_rows: List[DroppingOddsRow],
                           sport: str) -> List[UpcomingFixture]:
    """Attach price movement to every fixture on the coupon card."""
    by_id, by_name = index_drops(drop_rows)

    fixtures: List[UpcomingFixture] = []
    for entry in board:
        match_id = str(entry.event_id) if entry.event_id else None
        moves = by_id.get(match_id or "", None)
        join_source = "event_id"
        if moves is None:
            moves = by_name.get(_fixture_key(entry.home_team, entry.away_team))
            join_source = "team_names" if moves else "coupon_only"
        fixtures.append(UpcomingFixture(
            coupon=entry,
            sport=sport,
            moves=dict(moves or {}),
            match_id=match_id,
            join_source=join_source,
        ))
    return fixtures


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def pick_candidate(fixture: UpcomingFixture,
                   *,
                   min_odds: Optional[float] = None,
                   max_odds: Optional[float] = None) -> Optional[Candidate]:
    """Choose the outcome to put forward for *fixture*.

    Two signals, in priority order:

    1. **Money moved.** A falling price means bookmakers took bets on that
       outcome and shortened it — the strongest public signal of who is now
       expected to win. The biggest drop that still sits inside the qualifying
       odds range wins.
    2. **Market favourite.** With no movement to go on, the shortest price is
       the market's candidate.

    Note on bookmaker counts: they are *not* a winner signal on their own — the
    same fixture shows the same count on every outcome most of the time. What
    they measure is how well-formed the price is, so they are used as a gate and
    as a score component, not to choose the side.
    """
    low, high = odds_range_for_sport(fixture.sport)
    low = low if min_odds is None else min_odds
    high = high if max_odds is None else max_odds

    priced = {o: fixture.price(o) for o in OUTCOMES}
    priced = {o: p for o, p in priced.items() if p}
    if not priced:
        return None

    favourite = min(priced, key=lambda o: priced[o])

    def build(outcome: str, basis: str) -> Candidate:
        move = fixture.moves.get(outcome)
        return Candidate(
            outcome=outcome,
            odds=fixture.price(outcome),
            bookmakers=fixture.bookmakers_for(outcome),
            drop_pct=move.drop_pct if move else None,
            open_odds=move.open_odds if move else None,
            max_odds=move.max_odds if move else None,
            basis=basis,
            is_market_favourite=(outcome == favourite),
        )

    dropped = [
        (m.drop_pct or 0.0, o) for o, m in fixture.moves.items()
        if (m.drop_pct or 0) > 0 and priced.get(o)
        and low <= (priced[o] or 0) <= high
    ]
    if dropped:
        return build(max(dropped)[1], "drop")

    return build(favourite, "favourite")


def to_dropping_row(fixture: UpcomingFixture,
                    candidate: Candidate) -> DroppingOddsRow:
    """Express a fixture as a :class:`DroppingOddsRow`.

    This is what lets the existing qualification gate and the existing Livesport
    enrichment be reused verbatim instead of reimplemented.
    """
    kickoff = fixture.kickoff_local()
    return DroppingOddsRow(
        league=fixture.coupon.league,
        match_url=fixture.coupon.match_url,
        match_id=fixture.match_id,
        sport_slug=fixture.sport,
        sport=fixture.sport,
        home_team=fixture.home_team,
        away_team=fixture.away_team,
        event_date=kickoff.strftime("%Y-%m-%d") if kickoff else None,
        event_time=kickoff.strftime("%H:%M") if kickoff else None,
        outcome=candidate.outcome,
        open_odds=candidate.open_odds,
        current_odds=candidate.odds,
        drop_pct=candidate.drop_pct,
        max_odds=candidate.max_odds,
    )


# ---------------------------------------------------------------------------
# Filters — the same gate as the sport scraper / dropping pipeline, plus the
# two rules this pipeline adds (kickoff window, bookmaker consensus).
# ---------------------------------------------------------------------------


def _minutes_of_day(value: str) -> Optional[int]:
    """Parse ``"HH:MM"`` into minutes since local midnight."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        hours, _, minutes = text.partition(":")
        return int(hours) * 60 + int(minutes or 0)
    except ValueError:
        return None


def in_local_time_window(kickoff_local: Optional[datetime],
                         from_hm: str = "",
                         until_hm: str = "") -> bool:
    """Is the local kick-off time inside a time-of-day window?

    Used to cut the day into blocks ("fixtures before 15:00" / "after 15:00")
    so one digest can cover each, instead of mailing the same card all day.

    The window wraps past midnight when *from* is later than *until*, which is
    what an evening block needs: South American fixtures routinely kick off at
    01:00 or 02:00 local and belong to the evening digest, not the morning one.
    """
    start, end = _minutes_of_day(from_hm), _minutes_of_day(until_hm)
    if start is None and end is None:
        return True
    if kickoff_local is None:
        return False
    minutes = kickoff_local.hour * 60 + kickoff_local.minute

    if start is None:
        return minutes <= (end or 0)
    if end is None:
        return minutes >= start
    if start <= end:
        return start <= minutes <= end
    return minutes >= start or minutes <= end


def kickoff_window_reason(fixture: UpcomingFixture,
                          *,
                          now: datetime,
                          horizon_hours: float,
                          min_lead_minutes: int,
                          kickoff_from: str = "",
                          kickoff_until: str = "") -> Optional[str]:
    """``None`` when the fixture is upcoming and actionable, else the reason."""
    kickoff = fixture.kickoff_utc()
    if kickoff is None:
        return "missing_kickoff"
    minutes = (kickoff - now).total_seconds() / 60.0
    if minutes < min_lead_minutes:
        return "started_or_too_soon"
    if minutes > horizon_hours * 60.0:
        return "beyond_horizon"
    if not in_local_time_window(fixture.kickoff_local(), kickoff_from,
                                kickoff_until):
        return "outside_time_window"
    return None


def qualify(fixture: UpcomingFixture,
            candidate: Optional[Candidate],
            *,
            now: datetime,
            horizon_hours: float = DEFAULT_HORIZON_HOURS,
            min_lead_minutes: int = DEFAULT_MIN_LEAD_MINUTES,
            min_bookmakers: int = DEFAULT_MIN_BOOKMAKERS,
            min_drop: float = 0.0,
            require_drop: bool = False,
            min_odds: Optional[float] = None,
            max_odds: Optional[float] = None,
            strict_sports: bool = False,
            kickoff_from: str = "",
            kickoff_until: str = "") -> Tuple[bool, Optional[str]]:
    """Return ``(qualifies, skip_reason)`` for a merged fixture."""
    if candidate is None or not candidate.odds:
        return False, "missing_current_odds"

    window = kickoff_window_reason(
        fixture, now=now, horizon_hours=horizon_hours,
        min_lead_minutes=min_lead_minutes,
        kickoff_from=kickoff_from,
        kickoff_until=kickoff_until,
    )
    if window:
        return False, window

    # Delegate the odds range / sport support / team-name checks to the shared
    # gate so this pipeline cannot drift from the dropping pipeline's rules.
    row = to_dropping_row(fixture, candidate)
    ok, reason = is_qualifying_row(row, min_odds=min_odds, max_odds=max_odds)
    if not ok:
        # The coupon carries sports the form stack cannot enrich (Am. Football,
        # darts, cricket, MMA, boxing map to None in SPORT_SLUG_TO_INTERNAL).
        # The dropping pipeline drops them, because form is its whole point.
        # Here the odds analysis alone is still worth reporting, so they are
        # kept and flagged instead — use --strict-sports for the old behaviour.
        if reason != "unsupported_sport" or strict_sports:
            return False, reason

    if candidate.bookmakers < min_bookmakers:
        return False, "too_few_bookmakers"

    drop = candidate.drop_pct or 0.0
    if require_drop and drop <= 0:
        return False, "no_price_drop"
    if drop < min_drop:
        return False, "drop_below_threshold"

    return True, None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _form_wins(form: Any) -> int:
    """Count wins in a form value, accepting lists and 'W-W-L' strings."""
    if isinstance(form, (list, tuple)):
        tokens = [str(t).strip().upper() for t in form]
    elif isinstance(form, str):
        tokens = [t.strip().upper() for t in re.split(r"[-,\s]+", form) if t.strip()]
    else:
        return 0
    return sum(1 for t in tokens[:5] if t.startswith("W"))


def verify_form_orientation(fixture: UpcomingFixture,
                           enrichment: Optional[Dict[str, Any]]) -> str:
    """Check that enriched form actually belongs to this fixture's two sides.

    Necessary because the SofaScore fallback resolves events by team name and
    can return a *reversed* fixture, or one from another season entirely —
    observed 2026-08-17, where "General Caballero JLM vs Tacuary" resolved to
    "Tacuary vs General Caballero (JLM)" from 2024-07-20. Attributing that
    form to the wrong side would silently corrupt the pick, since the score
    awards up to 25 points for the focus team's form.

    Returns ``'ok'``, ``'swapped'`` (teams are reversed — read the other side)
    or ``'unverified'`` (no confident match; form must not be scored).
    """
    if not enrichment:
        return 'unverified'
    got_home = str(enrichment.get("home_team") or "")
    got_away = str(enrichment.get("away_team") or "")
    if not got_home or not got_away:
        return 'unverified'

    straight = (_similarity(fixture.home_team, got_home)
                + _similarity(fixture.away_team, got_away)) / 2.0
    reversed_ = (_similarity(fixture.home_team, got_away)
                 + _similarity(fixture.away_team, got_home)) / 2.0

    if max(straight, reversed_) < _MIN_ORIENTATION_SIMILARITY:
        return 'unverified'
    return 'ok' if straight >= reversed_ else 'swapped'


def score_candidate(fixture: UpcomingFixture,
                    candidate: Candidate,
                    enrichment: Optional[Dict[str, Any]] = None,
                    orientation: str = 'ok',
                    ) -> Tuple[float, Dict[str, float]]:
    """Score a candidate 0–100 from independent, inspectable components.

    - ``drop`` (0–30): how far the price fell. Money moving is the signal the
      dropping-odds feed exists for.
    - ``consensus`` (0–20): how many bookmakers price the outcome. A price 16
      books agree on is worth more than one quoted by 3.
    - ``favourite`` (0–15): the outcome is also the shortest price on the card.
    - ``value`` (0–10): how much better the best available price is than the
      current one — headroom against the market average.
    - ``form`` (0–25): wins in the focus team's general form (last 5) from
      Livesport. Zero when the fixture was not enriched.
    """
    breakdown: Dict[str, float] = {}

    drop = candidate.drop_pct or 0.0
    breakdown["drop"] = round(min(30.0, drop), 1)

    breakdown["consensus"] = round(min(20.0, candidate.bookmakers / 16.0 * 20.0), 1)

    breakdown["favourite"] = 15.0 if candidate.is_market_favourite else 0.0

    value = 0.0
    if candidate.max_odds and candidate.odds:
        value = max(0.0, (candidate.max_odds - candidate.odds) / candidate.odds)
    breakdown["value"] = round(min(10.0, value * 100.0), 1)

    form_points = 0.0
    # 'unverified' means we could not confirm the form belongs to these two
    # teams, so it must not move the score at all.
    if enrichment and orientation in ('ok', 'swapped'):
        want_away = candidate.outcome == "2"
        if orientation == 'swapped':
            want_away = not want_away
        if want_away:
            form = (enrichment.get("away_form_overall")
                    or enrichment.get("away_form"))
        else:
            form = (enrichment.get("home_form_overall")
                    or enrichment.get("home_form"))
        form_points = _form_wins(form) * 5.0
    breakdown["form"] = round(min(25.0, form_points), 1)

    return round(sum(breakdown.values()), 1), breakdown


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_fixture(fixture: UpcomingFixture,
                      candidate: Optional[Candidate],
                      *,
                      qualifies: bool,
                      skip_reason: Optional[str],
                      now: datetime,
                      enrichment: Optional[Dict[str, Any]] = None,
                      predict: bool = True,
                      ) -> Dict[str, Any]:
    kickoff_utc = fixture.kickoff_utc()
    kickoff_local = fixture.kickoff_local()
    minutes = (
        round((kickoff_utc - now).total_seconds() / 60.0)
        if kickoff_utc else None
    )

    event: Dict[str, Any] = {
        "match_id": fixture.match_id,
        "match_url": fixture.coupon.match_url,
        "sport": fixture.sport,
        "sport_slug": fixture.sport,
        "league": fixture.coupon.league,
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "kickoff_utc": kickoff_utc.strftime("%Y-%m-%d %H:%M") if kickoff_utc else None,
        "kickoff_local": (kickoff_local.strftime("%Y-%m-%d %H:%M")
                          if kickoff_local else None),
        "minutes_to_kickoff": minutes,
        # Local date/time, matching the dropping pipeline's field names so the
        # reporting layer can read either JSON.
        "event_date": kickoff_local.strftime("%Y-%m-%d") if kickoff_local else None,
        "event_time": kickoff_local.strftime("%H:%M") if kickoff_local else None,
        "home_odds": fixture.price("1"),
        "draw_odds": fixture.price("X"),
        "away_odds": fixture.price("2"),
        "bookmakers": fixture.coupon.bookmakers,
        "bookmakers_by_outcome": dict(fixture.coupon.bookmakers_by_outcome),
        "moves": {o: m.to_dict() for o, m in sorted(fixture.moves.items())},
        "has_drop": bool(fixture.best_drop()),
        "join_source": fixture.join_source,
        "qualifies": qualifies,
        "skip_reason": skip_reason,
    }

    if candidate is not None:
        event["candidate"] = candidate.to_dict()
        # Field names shared with the dropping pipeline's schema.
        event["outcome"] = candidate.outcome
        event["dropped_outcome"] = candidate.outcome
        event["open_odds"] = candidate.open_odds
        event["current_odds"] = candidate.odds
        event["drop_pct"] = candidate.drop_pct
        event["max_odds"] = candidate.max_odds
        event["focus_team"] = {"1": "home", "X": "draw", "2": "away"}[candidate.outcome]
        event["away_team_focus"] = candidate.outcome == "2"

    if enrichment is not None:
        event["enrichment_status"] = enrichment.get("status")
        event["livesport_url"] = enrichment.get("livesport_url")
        event["livesport_confidence"] = enrichment.get("livesport_confidence")
        event["enrichment"] = enrichment.get("enrichment")
        event["enrichment_error"] = enrichment.get("error")

    if candidate is not None:
        info = (enrichment or {}).get("enrichment") if enrichment else None
        orientation = verify_form_orientation(fixture, info) if info else 'ok'
        if info:
            event["form_orientation"] = orientation
        score, breakdown = score_candidate(fixture, candidate, info,
                                           orientation=orientation)
        event["score"] = score
        event["score_breakdown"] = breakdown

        # The market score above ranks the *signal*; the prediction stack below
        # is the actual model. They are kept separate so a disagreement stays
        # visible instead of being averaged away.
        if predict and qualifies and info and orientation != 'unverified':
            prediction = run_prediction(event, candidate)
            if prediction:
                event["prediction"] = prediction

    return event


def run_prediction(event: Dict[str, Any],
                   candidate: Optional[Candidate] = None,
                   ) -> Optional[Dict[str, Any]]:
    """Run the repo's prediction stack on an enriched event.

    Reuses the chain the dropping-odds mail already uses, rather than inventing
    a parallel model:

        event_to_match_row  ->  _build_scoring_input
                            ->  football/tennis/baseball scoring engine
                                (calibrated probabilities, EV, edge, Kelly)
                            ->  prediction_data_contract (grade, data quality)
        generate_ai_prediction  ->  consensus, risk flags, factor weights,
                                    verdict, arguments for/against

    One real gain over the dropping path: that one can only hand the engine the
    single price that moved, so the other outcomes stay unpriced. The coupon
    carries the full 1-X-2 line, so the engine gets a complete market and its
    EV/edge are computed against all outcomes.

    Returns ``None`` when the event has no team data to reason about — the
    engines would otherwise produce a confident-looking pick from odds and
    priors alone.
    """
    prepared = dict(event)
    # The scoring input reads odds out of ``enrichment``; the coupon keeps them
    # at the top level, so mirror them across without overwriting a book price.
    enriched = dict(event.get("enrichment") or {})
    for key in ("home_odds", "draw_odds", "away_odds"):
        if not enriched.get(key) and event.get(key):
            enriched[key] = event[key]
    prepared["enrichment"] = enriched

    try:
        from dropping_odds_email import event_to_match_row
        row = event_to_match_row(prepared)
    except Exception as exc:
        logger.debug("Scoring engine unavailable: %s", exc)
        return None

    if row.get("no_analysis_data") or not row.get("scoring_pick"):
        return None

    out: Dict[str, Any] = {
        "pick": row.get("scoring_pick"),
        "probability": row.get("scoring_prob"),
        "ev": row.get("scoring_ev"),
        "edge": row.get("scoring_edge"),
        "confidence": row.get("scoring_confidence"),
        "prob_1": row.get("scoring_prob_1"),
        "prob_X": row.get("scoring_prob_x"),
        "prob_2": row.get("scoring_prob_2"),
        "grade": row.get("prediction_grade"),
        "data_quality": row.get("data_quality"),
    }

    try:
        from ai_prediction_engine import generate_ai_prediction
        ai = generate_ai_prediction(row).to_dict()
    except Exception as exc:
        logger.debug("AI prediction layer unavailable: %s", exc)
        ai = None

    if ai:
        out["ai"] = {
            "pick": ai.get("pick"),
            "pick_label": ai.get("pickLabel"),
            "confidence": ai.get("compositeConfidence"),
            "confidence_tier": ai.get("confidenceTier"),
            "consensus": ai.get("consensus"),
            "value_rating": ai.get("valueRating"),
            "risk": ai.get("risk"),
            "data_quality": ai.get("dataQuality"),
            "data_quality_label": ai.get("dataQualityLabel"),
            "arguments_for": ai.get("keyArgumentsFor"),
            "arguments_against": ai.get("keyArgumentsAgainst"),
            "verdict": ai.get("verdict"),
            "short_verdict": ai.get("shortVerdict"),
            "do_not_bet_reasons": ai.get("doNotBetReasons"),
            "factors": ai.get("factors"),
        }

    # Whether the model backs the side the market money went to. Disagreement is
    # the interesting case and must not be buried.
    if candidate is not None:
        model_pick = str((ai or {}).get("pick") or out.get("pick") or "").upper()
        if model_pick in OUTCOMES:
            out["agrees_with_market"] = model_pick == candidate.outcome
            out["market_pick"] = candidate.outcome
    return out


def _write_output(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape the OddsSafari full coupon for upcoming fixtures, join it "
            "with the dropping-odds table, filter with the sport pipeline's "
            "rules and enrich with Livesport form."
        )
    )
    parser.add_argument("--sport", default="football",
                        help="Internal sport name (football, basketball, tennis, "
                             "hockey, handball, volleyball, baseball, rugby, "
                             "esports). Default: football.")
    parser.add_argument("--hours", type=float, default=DEFAULT_HORIZON_HOURS,
                        help=f"How far ahead to look, in hours "
                             f"(default {DEFAULT_HORIZON_HOURS:g}).")
    parser.add_argument("--kickoff-from", default="",
                        help="Keep only fixtures kicking off at or after this "
                             "local time (HH:MM). Combined with --kickoff-until "
                             "it splits the day into digest blocks; a later "
                             "--kickoff-from than --kickoff-until wraps past "
                             "midnight, e.g. 15:00-04:00 for the evening block.")
    parser.add_argument("--kickoff-until", default="",
                        help="Keep only fixtures kicking off at or before this "
                             "local time (HH:MM), e.g. 15:00 for the morning "
                             "block.")
    parser.add_argument("--min-lead", type=int, default=DEFAULT_MIN_LEAD_MINUTES,
                        help="Skip fixtures starting sooner than this many "
                             f"minutes (default {DEFAULT_MIN_LEAD_MINUTES}).")
    parser.add_argument("--min-bookmakers", type=int,
                        default=DEFAULT_MIN_BOOKMAKERS,
                        help="Minimum bookmakers pricing the candidate outcome "
                             f"(default {DEFAULT_MIN_BOOKMAKERS}).")
    parser.add_argument("--min-drop", type=float, default=0.0,
                        help="Minimum price drop %% on the candidate (default 0 "
                             "= drops are scored, not required).")
    parser.add_argument("--require-drop", action="store_true",
                        help="Keep only fixtures whose candidate price fell.")
    parser.add_argument("--no-prediction", dest="predict", action="store_false",
                        help="Skip the scoring engine / AI prediction layer and "
                             "report the market signal only.")
    parser.add_argument("--strict-sports", action="store_true",
                        help="Drop sports the form stack cannot enrich "
                             "(am. football, darts, cricket, mma, boxing) "
                             "instead of reporting them odds-only.")
    parser.add_argument("--min-odds", type=float, default=None,
                        help="Override the lower bound of qualifying odds. Omit "
                             "to use the per-sport range (football 1.80, "
                             "handball/hockey 1.60, others 1.35).")
    parser.add_argument("--max-odds", type=float, default=None,
                        help="Override the upper bound (per-sport: 2.50).")
    parser.add_argument("--days", type=int, default=None,
                        help="Coupon calendar days to request. Derived from "
                             "--hours when omitted, so a longer horizon cannot "
                             "silently look past the end of the card (sparse "
                             "sports like boxing need several days).")
    parser.add_argument("--max-pages", type=int, default=20,
                        help="Max dropping-odds pages per sport (default 20).")
    parser.add_argument("--max-enrich", type=int, default=25,
                        help="Cap on fixtures given the costly Livesport form/H2H "
                             "enrichment, best-scoring first (0 = all).")
    parser.add_argument("--max-rows", type=int, default=0,
                        help="Optional cap on fixtures processed (0 = no cap).")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="Run Chrome headless (default).")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Show the browser window (for debugging).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip the Livesport enrichment phase entirely.")
    parser.add_argument("--no-forebet", dest="use_forebet", action="store_false",
                        help="Disable Forebet enrichment inside process_match.")
    parser.add_argument("--no-sofascore", dest="use_sofascore",
                        action="store_false",
                        help="Disable SofaScore fan-vote enrichment.")
    parser.add_argument("--output", default="",
                        help="Override the output JSON path.")
    parser.set_defaults(use_forebet=True, use_sofascore=True, predict=True)
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

    sport = (args.sport or "football").strip().lower()
    # The coupon is addressed by calendar day, the filter by hours ahead. Cover
    # enough days for the whole horizon, plus one for the horizon spilling past
    # midnight. Without this, --hours 48 could only ever see two days of card.
    days = args.days
    if days is None:
        days = int(math.ceil(args.hours / 24.0)) + 1
    now_utc = datetime.now(SITE_TZ)
    now_local = now_utc.astimezone(WARSAW_TZ)
    run_date = now_local.strftime("%Y-%m-%d")
    output_path = (args.output
                   or f"outputs/oddssafari_upcoming_{run_date}_{sport}.json")

    low, high = odds_range_for_sport(sport)
    if args.min_odds is not None:
        low = args.min_odds
    if args.max_odds is not None:
        high = args.max_odds

    print("=" * 70)
    print("OddsSafari Upcoming Odds Pipeline (coupon + drops + form)")
    print("=" * 70)
    print(f"  Now:                {now_local:%Y-%m-%d %H:%M} Europe/Warsaw")
    print(f"  Sport:              {sport}")
    print(f"  Horizon:            next {args.hours:g}h "
          f"(min lead {args.min_lead} min)")
    if args.kickoff_from or args.kickoff_until:
        print(f"  Kickoff window:     "
              f"{args.kickoff_from or '--'}–{args.kickoff_until or '--'} lokalnie")
    print(f"  Qualifying odds:    [{low:.2f}, {high:.2f}]"
          f"{'' if args.min_odds is None and args.max_odds is None else ' (override)'}")
    print(f"  Min bookmakers:     {args.min_bookmakers}")
    print(f"  Drop rule:          "
          f"{'required' if args.require_drop else f'>= {args.min_drop:g}% (scored)'}")
    print(f"  Enrichment cap:     {args.max_enrich or 'none (all qualifying)'}")
    print(f"  Output:             {output_path}")
    print(f"  Mode:               {'DRY-RUN' if args.dry_run else 'FULL'}")
    print("=" * 70)

    if not is_enrichable_sport(sport):
        logger.warning("Sport '%s' has no enrichment path — odds only", sport)

    run_started = time.time()

    # Only the Livesport enrichment needs a browser, and most hourly runs have
    # little to enrich, so it is started lazily.
    driver_holder: Dict[str, Any] = {"driver": None}

    def _get_driver():
        if driver_holder["driver"] is None:
            from livesport_h2h_scraper import start_driver
            print("🌐 Startuję przeglądarkę (Livesport enrichment)...")
            driver_holder["driver"] = start_driver(headless=args.headless)
        return driver_holder["driver"]

    try:
        wanted_dates = coupon_dates(days, now=now_utc)
        print(f"📅 Kupon: {', '.join(wanted_dates)}")
        board = fetch_coupon_board(sport, dates=wanted_dates)
        print(f"🎟️  Kupon: {len(board)} wydarzeń z kursami")

        drop_rows = collect_rows_via_http(
            sport=sport, max_pages_per_sport=args.max_pages)
        print(f"📉 Dropping odds: {len(drop_rows)} zmian kursów")

        fixtures = merge_board_with_drops(board, drop_rows, sport)
        joined = sum(1 for f in fixtures if f.moves)
        print(f"🔗 Połączono: {joined}/{len(fixtures)} wydarzeń ma dane o spadkach")

        if args.max_rows:
            fixtures = fixtures[: args.max_rows]

        # Evaluate everything first, then spend the enrichment budget on the
        # best-scoring fixtures — form is the expensive part.
        evaluated: List[Tuple[UpcomingFixture, Optional[Candidate], bool,
                              Optional[str], float]] = []
        for fixture in fixtures:
            candidate = pick_candidate(
                fixture, min_odds=args.min_odds, max_odds=args.max_odds)
            qualifies, skip_reason = qualify(
                fixture, candidate,
                now=now_utc,
                horizon_hours=args.hours,
                min_lead_minutes=args.min_lead,
                min_bookmakers=args.min_bookmakers,
                min_drop=args.min_drop,
                require_drop=args.require_drop,
                min_odds=args.min_odds,
                max_odds=args.max_odds,
                strict_sports=args.strict_sports,
                kickoff_from=args.kickoff_from,
                kickoff_until=args.kickoff_until,
            )
            pre_score = (
                score_candidate(fixture, candidate)[0] if candidate else 0.0
            )
            evaluated.append((fixture, candidate, qualifies, skip_reason, pre_score))

        order = sorted(
            range(len(evaluated)),
            key=lambda i: (evaluated[i][2], evaluated[i][4]),
            reverse=True,
        )

        enrich_budget = args.max_enrich if args.max_enrich > 0 else None
        enriched_count = 0
        browser_unavailable: Optional[str] = None
        enrichments: Dict[int, Dict[str, Any]] = {}
        enrichment_counts: Dict[str, int] = {}

        # No form stack exists for these sports, so there is nothing to start a
        # browser for — they are reported on odds, drops and bookmakers alone.
        form_available = is_enrichable_sport(sport)
        if not form_available and not args.dry_run:
            print(f"ℹ️  Sport '{sport}' nie ma źródła formy — raport tylko na "
                  f"kursach, spadkach i liczbie bukmacherów")
            for idx, (_f, cand, quals, _r, _s) in enumerate(evaluated):
                if quals and cand is not None:
                    enrichments[idx] = {
                        "status": "unsupported_sport_odds_only",
                        "livesport_url": None,
                        "livesport_confidence": 0.0,
                        "enrichment": None,
                        "error": None,
                    }
                    enrichment_counts["unsupported_sport_odds_only"] = (
                        enrichment_counts.get("unsupported_sport_odds_only", 0) + 1)

        if not args.dry_run and form_available:
            from oddssafari_dropping_pipeline import \
                _enrich_row as enrich_with_livesport

            for position, idx in enumerate(order, 1):
                fixture, candidate, qualifies, _reason, _score = evaluated[idx]
                if not qualifies or candidate is None:
                    continue
                if enrich_budget is not None and enriched_count >= enrich_budget:
                    enrichments[idx] = {
                        "status": "skipped_enrich_budget",
                        "livesport_url": None,
                        "livesport_confidence": 0.0,
                        "enrichment": None,
                        "error": None,
                    }
                    enrichment_counts["skipped_enrich_budget"] = (
                        enrichment_counts.get("skipped_enrich_budget", 0) + 1)
                    continue

                enriched_count += 1
                kickoff_local = fixture.kickoff_local()
                # Livesport day pages are local, so a 23:00 UTC fixture must be
                # looked up under tomorrow's Warsaw date.
                lookup_date = (kickoff_local or now_local).strftime("%Y-%m-%d")
                print(f"[{enriched_count}] forma: {fixture.home_team} vs "
                      f"{fixture.away_team} ({kickoff_local:%H:%M} lok., "
                      f"pick={candidate.outcome} @ {candidate.odds}, "
                      f"{candidate.bookmakers} bk"
                      f"{f', -{candidate.drop_pct:g}%' if candidate.drop_pct else ''})")

                if browser_unavailable:
                    enrichments[idx] = {
                        "status": "browser_unavailable",
                        "livesport_url": None,
                        "livesport_confidence": 0.0,
                        "enrichment": None,
                        "error": browser_unavailable,
                    }
                else:
                    try:
                        enrichments[idx] = enrich_with_livesport(
                            _get_driver(),
                            to_dropping_row(fixture, candidate),
                            date=lookup_date,
                            use_forebet=args.use_forebet,
                            use_sofascore=args.use_sofascore,
                        )
                    except Exception as exc:
                        # The odds are already collected and worth reporting;
                        # a browser failure must not sink the run.
                        browser_unavailable = f"{type(exc).__name__}: {exc}"
                        logger.error("Enrichment unavailable, continuing "
                                     "without form: %s", browser_unavailable)
                        enrichments[idx] = {
                            "status": "browser_unavailable",
                            "livesport_url": None,
                            "livesport_confidence": 0.0,
                            "enrichment": None,
                            "error": browser_unavailable,
                        }
                status = enrichments[idx].get("status") or "resolve_failed"
                enrichment_counts[status] = enrichment_counts.get(status, 0) + 1

        events: List[Dict[str, Any]] = []
        qualified: List[Dict[str, Any]] = []
        reason_counts: Dict[str, int] = {}
        orientation_counts: Dict[str, int] = {}
        prediction_counts: Dict[str, int] = {}

        for idx, (fixture, candidate, qualifies, skip_reason, _pre) in enumerate(
                evaluated):
            event = serialize_fixture(
                fixture, candidate,
                qualifies=qualifies,
                skip_reason=skip_reason,
                now=now_utc,
                enrichment=enrichments.get(idx),
                predict=args.predict,
            )
            events.append(event)
            orientation = event.get("form_orientation")
            if orientation:
                orientation_counts[orientation] = (
                    orientation_counts.get(orientation, 0) + 1)
            pred = event.get("prediction")
            if pred:
                prediction_counts["scored"] = prediction_counts.get("scored", 0) + 1
                if pred.get("agrees_with_market") is True:
                    prediction_counts["agrees_with_market"] = (
                        prediction_counts.get("agrees_with_market", 0) + 1)
                elif pred.get("agrees_with_market") is False:
                    prediction_counts["disagrees_with_market"] = (
                        prediction_counts.get("disagrees_with_market", 0) + 1)
                grade = pred.get("grade")
                if grade:
                    prediction_counts[f"grade_{grade}"] = (
                        prediction_counts.get(f"grade_{grade}", 0) + 1)
            if qualifies:
                qualified.append(event)
            else:
                key = skip_reason or "unknown"
                reason_counts[key] = reason_counts.get(key, 0) + 1

        qualified.sort(key=lambda e: e.get("score") or 0.0, reverse=True)

        payload = {
            "meta": {
                "generated_at": now_local.isoformat(),
                "generated_at_utc": now_utc.isoformat(),
                "target_date": run_date,
                "sport": sport,
                "source": "oddssafari_coupon+dropping_odds",
                "coupon_dates": wanted_dates,
                "filter": {
                    "min_odds": low,
                    "max_odds": high,
                    "per_sport_range": args.min_odds is None and args.max_odds is None,
                    "horizon_hours": args.hours,
                    "min_lead_minutes": args.min_lead,
                    "kickoff_from": args.kickoff_from,
                    "kickoff_until": args.kickoff_until,
                    "min_bookmakers": args.min_bookmakers,
                    "min_drop_pct": args.min_drop,
                    "require_drop": bool(args.require_drop),
                },
                "totals": {
                    "coupon_fixtures": len(board),
                    "dropping_rows": len(drop_rows),
                    "joined_with_drops": joined,
                    "events": len(events),
                    "qualified": len(qualified),
                },
                "enrichment_status_counts": enrichment_counts,
                # 'unverified' here means the form source returned a fixture we
                # could not tie back to these two teams, so its form was not
                # scored. A high count points at the upstream matcher.
                "form_orientation_counts": orientation_counts,
                "prediction_counts": prediction_counts,
                "skip_reason_counts": reason_counts,
                "elapsed_seconds": round(time.time() - run_started, 1),
                "dry_run": bool(args.dry_run),
            },
            "events": events,
            "qualified": qualified,
        }

        _write_output(output_path, payload)

        print("=" * 70)
        print(f"Kupon:         {len(board)} wydarzeń")
        print(f"Spadki:        {len(drop_rows)} wierszy ({joined} dopasowanych)")
        print(f"Kwalifikuje:   {len(qualified)}")
        if enrichment_counts:
            print(f"Enrichment:    {enrichment_counts}")
        if reason_counts:
            print(f"Odrzucone:     {reason_counts}")
        if prediction_counts:
            print(f"Model:         {prediction_counts}")
        for event in qualified[:10]:
            candidate = event.get("candidate") or {}
            print(f"  {event.get('score'):>5} | {event.get('kickoff_local')} | "
                  f"{event.get('home_team')} vs {event.get('away_team')} | "
                  f"rynek {candidate.get('outcome')} @ {candidate.get('odds')} | "
                  f"{candidate.get('bookmakers')} bk | "
                  f"drop {candidate.get('drop_pct') or 0}%")
            pred = event.get("prediction")
            if pred:
                agree = pred.get("agrees_with_market")
                mark = "=" if agree else ("≠" if agree is False else "?")
                print(f"        model {mark} {pred.get('pick')} "
                      f"({pred.get('probability')}%, EV {pred.get('ev')}, "
                      f"grade {pred.get('grade')}) "
                      f"{(pred.get('ai') or {}).get('short_verdict') or ''}")
        print(f"Zapisano:      {output_path}")
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
