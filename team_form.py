"""Recent form for a team or player, computed from settled results.

The scrapers hand us about five W/D/L letters and nothing else, and for many
fixtures not even that. Meanwhile the backfill left 109k settled matches in
``outputs/result_store.json`` carrying numeric scores — enough to work out, for
any competitor on any date, how their last ten went and how they went *at home*
versus *away* specifically.

The one rule that matters here: form for a match on date D uses only matches
strictly before D. Same-day fixtures are excluded too, because table-tennis
players appear two or three times in a day and a morning result would leak into
an afternoon prediction that was made before it happened.

    from team_form import FormProvider
    provider = FormProvider.from_store()
    provider.attach(match)      # fills home_form_overall, away_form_away, ...
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

# How many past matches count as "recent". Ten is what the user asked to see and
# is roughly where extra history stops helping: beyond that a competitor's form
# is really their strength, which is what the Elo rating is for.
FORM_WINDOW = 10

DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'outputs', 'result_store.json')


@dataclass(frozen=True)
class Appearance:
    """One past match from a single competitor's point of view."""

    date: str
    outcome: str          # 'W' / 'D' / 'L'
    at_home: bool
    scored: Optional[int]
    conceded: Optional[int]
    opponent: str
    sport: str

    @property
    def score_text(self) -> str:
        if self.scored is None or self.conceded is None:
            return ''
        return f'{self.scored}-{self.conceded}'


@dataclass
class FormProvider:
    """Chronological index of appearances, keyed by sport *and* competitor.

    The sport belongs in the key. "ŁKS Łódź" is a football club and a basketball
    club, and keying on the name alone gave the football side a form built partly
    from basketball games — the smoke test showed 87-96 and 88-69 sitting in a
    football team's last three results. Any city with one name across several
    sports has the same problem.
    """

    by_team: Dict[str, List[Appearance]] = field(default_factory=lambda: defaultdict(list))
    # name -> {sports it appears in}, used to resolve a lookup that arrives
    # without a sport without falling back into the collision above.
    sports_by_name: Dict[str, set] = field(default_factory=lambda: defaultdict(set))

    # ------------------------------------------------------------------
    @classmethod
    def from_store(cls, path: str = DEFAULT_STORE) -> 'FormProvider':
        """Build from the result store. Missing or broken file yields an empty
        provider rather than an exception — form is an enhancement, and losing
        it must never take the pipeline down."""
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return cls()
        return cls.from_rows(raw.values())

    @classmethod
    def from_rows(cls, rows: Iterable[Dict[str, Any]]) -> 'FormProvider':
        provider = cls()
        for res in rows:
            provider.add(res)
        provider.sort()
        return provider

    # ------------------------------------------------------------------
    def add(self, res: Dict[str, Any]) -> bool:
        """Record one settled match as two appearances. Returns True if used."""
        if res.get('status') != 'finished':
            return False
        winner = res.get('winner')
        if winner not in ('home', 'away', 'draw'):
            return False
        home = res.get('home_team')
        away = res.get('away_team')
        date = res.get('date')
        if not (home and away and date):
            return False

        sh = _as_int(res.get('score_home'))
        sa = _as_int(res.get('score_away'))
        sport = (res.get('sport') or '').lower()

        home_outcome = {'home': 'W', 'away': 'L', 'draw': 'D'}[winner]
        away_outcome = {'home': 'L', 'away': 'W', 'draw': 'D'}[winner]

        self.by_team[_index_key(sport, home)].append(Appearance(
            date=date, outcome=home_outcome, at_home=True, scored=sh,
            conceded=sa, opponent=str(away), sport=sport))
        self.by_team[_index_key(sport, away)].append(Appearance(
            date=date, outcome=away_outcome, at_home=False, scored=sa,
            conceded=sh, opponent=str(home), sport=sport))
        self.sports_by_name[_key(home)].add(sport)
        self.sports_by_name[_key(away)].add(sport)
        return True

    def sort(self) -> None:
        """Newest first, which is the order every consumer expects."""
        for appearances in self.by_team.values():
            appearances.sort(key=lambda a: a.date, reverse=True)

    # ------------------------------------------------------------------
    def _entries(self, team: str, sport: Optional[str]) -> List[Appearance]:
        """Appearances for this competitor in this sport.

        Without a sport we resolve the name only when it is unambiguous. Guessing
        would reintroduce the cross-sport mix-up the key exists to prevent, and a
        team with no form is a far smaller error than a team with someone else's.
        """
        if sport:
            return self.by_team.get(_index_key(sport, team), [])
        candidates = self.sports_by_name.get(_key(team), set())
        if len(candidates) == 1:
            return self.by_team.get(
                _index_key(next(iter(candidates)), team), [])
        return []

    def appearances(self, team: str, before: Optional[str] = None,
                    venue: Optional[str] = None,
                    window: int = FORM_WINDOW,
                    sport: Optional[str] = None) -> List[Appearance]:
        """Last *window* appearances, newest first, strictly before *before*.

        *venue* of ``'home'`` or ``'away'`` restricts to that side. Passing no
        *before* date returns the whole history, which is only safe for display
        of already-played matches — never for scoring a future fixture.
        """
        out: List[Appearance] = []
        for app in self._entries(team, sport):
            if before and app.date >= before:
                continue
            if venue == 'home' and not app.at_home:
                continue
            if venue == 'away' and app.at_home:
                continue
            out.append(app)
            if len(out) >= window:
                break
        return out

    def form(self, team: str, before: Optional[str] = None,
             venue: Optional[str] = None,
             window: int = FORM_WINDOW,
             sport: Optional[str] = None) -> List[str]:
        """W/D/L letters, newest first — the shape the engine already reads."""
        return [a.outcome for a in
                self.appearances(team, before, venue, window, sport)]

    def played(self, team: str, before: Optional[str] = None,
               sport: Optional[str] = None) -> int:
        return len(self.appearances(team, before, window=10 ** 9, sport=sport))

    # ------------------------------------------------------------------
    def attach(self, match: Dict[str, Any], window: int = FORM_WINDOW,
               overwrite: bool = False,
               min_history: int = 0,
               set_form_fields: bool = True) -> Dict[str, Any]:
        """Fill the form fields the engine and the email already consume.

        By default a value the scraper already supplied is left alone: the
        scraper saw the competition's own form table, which may include matches
        our store never scraped. Store-derived form fills the gaps, which is
        where most of the gain is — many fixtures arrive with no form at all.
        """
        home = match.get('home_team') or ''
        away = match.get('away_team') or ''
        before = match.get('match_date') or match.get('date') or None
        sport = (match.get('sport') or '').lower() or None

        # A competitor we have barely scraped has a store history that is a thin,
        # unrepresentative slice of what they actually played, and form built
        # from it is confidently wrong rather than merely absent. Measured on
        # settled rows that carry real prices: filling gaps without this gate
        # made basketball worse (Brier 0.3716 -> 0.3767), hockey worse
        # (0.4661 -> 0.4709) and volleyball worse (0.3088 -> 0.3131).
        thin = set()
        if min_history > 0:
            for team in (home, away):
                if team and self.played(team, before, sport) < min_history:
                    thin.add(team)

        pairs = (
            ('home_form_overall', home, None),
            ('home_form_home', home, 'home'),
            ('away_form_overall', away, None),
            ('away_form_away', away, 'away'),
        )
        for field_name, team, venue in pairs:
            if not set_form_fields:
                # Display only: the recent-match list below still gets written,
                # but nothing the scoring engine reads is touched. Measured on
                # rows carrying real prices, feeding store form to the engine
                # lowered ROI in both sports with a credible sample — tennis
                # -6.7% -> -8.2% over 3494 matches, basketball +12.2% -> +8.2%
                # over 832 — so it earns a place in the card, not in the pick.
                break
            if not team or team in thin:
                continue
            if not overwrite and _has_form(match.get(field_name)):
                continue
            letters = self.form(team, before=before, venue=venue,
                                window=window, sport=sport)
            if letters:
                match[field_name] = letters

        # Kept separate from the W/D/L fields so the email can show real
        # scorelines and so a reader can tell store-derived form from whatever
        # the scraper reported.
        home_recent = self.appearances(home, before, None, window,
                                       sport) if home else []
        away_recent = self.appearances(away, before, None, window,
                                       sport) if away else []
        if home_recent:
            match['home_recent_matches'] = [_as_dict(a) for a in home_recent]
        if away_recent:
            match['away_recent_matches'] = [_as_dict(a) for a in away_recent]
        return match


# ---------------------------------------------------------------------------

def _as_dict(app: Appearance) -> Dict[str, Any]:
    return {'date': app.date, 'outcome': app.outcome, 'at_home': app.at_home,
            'score': app.score_text, 'opponent': app.opponent}


def _as_int(val: Any) -> Optional[int]:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _has_form(val: Any) -> bool:
    if isinstance(val, list):
        return any(str(x).upper()[:1] in ('W', 'D', 'L') for x in val)
    if isinstance(val, str):
        return any(c in 'WDLwdl' for c in val)
    return False


def _key(name: str) -> str:
    return ' '.join(str(name or '').strip().lower().split())


def _index_key(sport: str, name: str) -> str:
    return f'{(sport or "").lower()}|{_key(name)}'


__all__ = ['FORM_WINDOW', 'Appearance', 'FormProvider']
