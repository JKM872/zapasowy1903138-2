"""League tier heuristic (moved from the data-audit baseline script).

T1 = top leagues by name, T3 = youth/women/reserves/ITF/Challenger/low divisions
(league or team names), T2 = any other named league, T? = no league.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

TOP1 = re.compile(
    r"premier league|laliga|la liga|bundesliga|serie a|ligue 1|eredivisie|champions league"
    r"|europa league|nba|nhl|khl|euroleague|shl|liiga|extraliga|atp|wta|grand slam|mlb|npb|kbo"
    r"|super league|liga portugal|ekstraklasa|del\b|acb|vtb|plusliga|ehf|nfl", re.I)
LOW = re.compile(
    r"\bU\d\d\b|women|\bW\b|\bII\b|reserve|youth|junior|itf|challenger|amateur|regional|\bB\b"
    r"|division 3|4\.|5\.", re.I)
TIERS = ('T1', 'T2', 'T3', 'T?')


def tier(m: Dict[str, Any], sport: Optional[str] = None) -> str:
    """Tier of a match record (keys league, country, homeTeam, awayTeam)."""
    lg = " ".join(str(x) for x in (m.get("league"), m.get("country")) if x)
    names = f"{m.get('homeTeam')} {m.get('awayTeam')}"
    if LOW.search(lg) or LOW.search(names):
        return "T3"
    if not lg.strip():
        return "T?"
    return "T1" if TOP1.search(lg) else "T2"
