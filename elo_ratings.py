"""Strength ratings learned from results, in chronological order.

The scraped history holds the same competitors over and over — one table-tennis
player appears in 167 of our fixtures, one pair met 31 times — and until the
backfill recovered 69k outcomes there was no way to learn anything from that.
This is the simplest thing that can: an Elo pool per sport, updated match by
match.

Why Elo before anything cleverer: it needs only the result, it has two
parameters instead of ten, and it cannot leak. Every prediction here is made
from ratings as they stood *before* that match was played, because the walk is
chronological — so a favourable number cannot be an artefact of hindsight, which
is the failure mode that made the earlier "81% accuracy on football" meaningless.

    from elo_ratings import EloModel
    model = EloModel(sport='table_tennis')
    report = model.walk_forward(rows)      # rows sorted by date internally
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Starting rating for a competitor nobody has seen yet.
BASE_RATING = 1500.0

# How fast a rating moves. Higher suits sports with few matches per competitor
# and volatile form; lower suits long seasons. Fitted per sport below rather
# than assumed.
DEFAULT_K = 24.0

# Rating points of home advantage, added to the home side when forming the
# expectation. Meaningless in tennis and table tennis, where "home" is just the
# order the fixture was listed in, so it is fitted and comes out near zero.
DEFAULT_HOME_ADVANTAGE = 40.0

DRAW_SPORTS = {'football', 'handball', 'hockey', 'rugby'}


def expected_score(rating: float, opponent: float,
                   home_advantage: float = 0.0) -> float:
    """Probability that *rating* beats *opponent*, before draws are considered."""
    return 1.0 / (1.0 + 10 ** ((opponent - rating - home_advantage) / 400.0))


@dataclass
class EloModel:
    """A rating pool for one sport."""

    sport: str = 'football'
    k: float = DEFAULT_K
    home_advantage: float = DEFAULT_HOME_ADVANTAGE
    draw_share: float = 0.0
    ratings: Dict[str, float] = field(default_factory=dict)
    played: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # ------------------------------------------------------------------
    def rating(self, name: str) -> float:
        return self.ratings.get(_key(name), BASE_RATING)

    def matches_played(self, name: str) -> int:
        return self.played[_key(name)]

    # ------------------------------------------------------------------
    def predict(self, home: str, away: str) -> Tuple[float, float, float]:
        """``(p_home, p_draw, p_away)`` from the ratings as they stand now."""
        p_home_raw = expected_score(self.rating(home), self.rating(away),
                                    self.home_advantage)

        if self.draw_share <= 0:
            return p_home_raw, 0.0, 1.0 - p_home_raw

        # Draws are taken out of the middle: the closer the two ratings, the
        # more of the draw share applies. Crude, but it keeps the triplet honest
        # without inventing a second model.
        closeness = 1.0 - abs(p_home_raw - 0.5) * 2.0
        p_draw = self.draw_share * closeness
        remaining = 1.0 - p_draw
        return p_home_raw * remaining, p_draw, (1.0 - p_home_raw) * remaining

    # ------------------------------------------------------------------
    def update(self, home: str, away: str, winner: str) -> None:
        """Move both ratings towards the result."""
        hk, ak = _key(home), _key(away)
        rh, ra = self.rating(home), self.rating(away)
        expected = expected_score(rh, ra, self.home_advantage)

        actual = {'home': 1.0, 'away': 0.0, 'draw': 0.5}.get(winner)
        if actual is None:
            return

        delta = self.k * (actual - expected)
        self.ratings[hk] = rh + delta
        self.ratings[ak] = ra - delta
        self.played[hk] += 1
        self.played[ak] += 1

    # ------------------------------------------------------------------
    def walk_forward(self, rows: Iterable[Dict[str, Any]],
                     min_played: int = 3) -> Dict[str, Any]:
        """Predict then learn, in date order. Returns scoring metrics.

        *min_played* excludes matches where either competitor is still unknown:
        a rating built from one game is noise, and scoring against it would
        flatter or damn the model for no reason. Those matches still train the
        ratings, they are just not counted.
        """
        ordered = sorted(rows, key=lambda r: (r.get('date') or '',
                                              r.get('home_team') or ''))
        scored = 0
        hits = 0
        brier_sum = 0.0
        logloss_sum = 0.0
        skipped_cold = 0

        for row in ordered:
            home = row.get('home_team') or ''
            away = row.get('away_team') or ''
            winner = row.get('winner')
            if not home or not away or winner not in ('home', 'away', 'draw'):
                continue

            warm = (self.matches_played(home) >= min_played
                    and self.matches_played(away) >= min_played)
            if warm:
                probs = self.predict(home, away)
                target = {'home': 0, 'draw': 1, 'away': 2}[winner]
                pick = max(range(3), key=lambda i: probs[i])
                hits += 1 if pick == target else 0
                brier_sum += sum((p - (1.0 if i == target else 0.0)) ** 2
                                 for i, p in enumerate(probs))
                logloss_sum += -math.log(max(1e-9, probs[target]))
                scored += 1
            else:
                skipped_cold += 1

            self.update(home, away, winner)

        return {
            'sport': self.sport,
            'k': self.k,
            'home_advantage': self.home_advantage,
            'draw_share': self.draw_share,
            'n_scored': scored,
            'n_cold': skipped_cold,
            'accuracy': (hits / scored) if scored else 0.0,
            'brier': (brier_sum / scored) if scored else float('nan'),
            'log_loss': (logloss_sum / scored) if scored else float('nan'),
            'competitors': len(self.ratings),
        }


def _key(name: str) -> str:
    return ' '.join(str(name or '').strip().lower().split())


def observed_draw_share(rows: Iterable[Dict[str, Any]]) -> float:
    """How often this sport actually draws — the draw model's only input."""
    total = draws = 0
    for row in rows:
        if row.get('winner') in ('home', 'away', 'draw'):
            total += 1
            draws += row['winner'] == 'draw'
    return (draws / total) if total else 0.0


def fit(rows: List[Dict[str, Any]], sport: str,
        k_grid: Optional[List[float]] = None,
        ha_grid: Optional[List[float]] = None,
        min_played: int = 3) -> Tuple['EloModel', Dict[str, Any]]:
    """Choose K and home advantage by walking the training rows.

    Both are picked on log-loss over the same chronological walk that will be
    used to judge the model, so nothing is selected using a match the ratings
    had not yet seen.
    """
    if k_grid is None:
        # Reaches well past any sensible K on purpose: if the choice lands on
        # the last entry the grid was too narrow and the "optimum" is an
        # artefact of where we stopped looking, which is how the temperature
        # experiment fooled us.
        k_grid = [8.0, 12.0, 16.0, 20.0, 24.0, 32.0, 40.0, 56.0, 72.0, 96.0,
                  128.0, 160.0]
    if ha_grid is None:
        ha_grid = ([0.0, 20.0, 40.0, 60.0, 80.0] if sport in DRAW_SPORTS
                   else [0.0, 15.0, 30.0])

    draw_share = observed_draw_share(rows) if sport in DRAW_SPORTS else 0.0

    best_model: Optional[EloModel] = None
    best_report: Dict[str, Any] = {}
    for k in k_grid:
        for ha in ha_grid:
            model = EloModel(sport=sport, k=k, home_advantage=ha,
                             draw_share=draw_share)
            report = model.walk_forward(rows, min_played=min_played)
            if not report['n_scored']:
                continue
            if (not best_report
                    or report['log_loss'] < best_report['log_loss']):
                best_model, best_report = model, report

    return (best_model or EloModel(sport=sport, draw_share=draw_share),
            best_report)


__all__ = [
    'BASE_RATING', 'DEFAULT_K', 'DEFAULT_HOME_ADVANTAGE', 'DRAW_SPORTS',
    'EloModel', 'expected_score', 'fit', 'observed_draw_share',
]
