"""Best available price for a TOP pick (design K4).

``best_price(pick, day)`` asks every free odds source we already scrape and
returns the highest price that is comparable with the pick's own market:

* Pinnacle guest API – ``forebet_pipeline.pinnacle_odds`` over ``_pinnacle_index``,
* OddsSafari coupon board – ``oddssafari_coupons.fetch_coupon_board`` +
  ``find_coupon_match`` (quote over up to ~13 bookmakers; whether it is the best
  or an average quote is not confirmed, so it is labelled just "oddssafari"),
* Livesport bulk odds feed – ``livesport_bulk_odds.lookup``.

Every quote is converted with ``pricing.side_price`` (hockey/basketball/baseball
1X2 -> 2-way equivalent incl. OT) and must lie in 1.01–50. A quote more than
1.25× the median of the other quotes is ignored as a stale line. Each source is
fetched once per sport and process (the modules cache their boards); a failing
or slow source (5 s per HTTP request; its module import is not timed) is logged as a WARNING and skipped for the
rest of the run. Never raises.
"""
from __future__ import annotations

import importlib
import os
import statistics
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tools import pricing  # noqa: E402

MIN_QUOTE, MAX_QUOTE = 1.01, 50.0
OUTLIER_RATIO = 1.25
TIMEOUT_S = 5
# Budget per source call = 5 s per HTTP request it may need on a cold cache
# (Pinnacle: matchups + markets; OddsSafari: market probe + 2 dates; Livesport:
# odds + list feed for up to 3 days).
BUDGET_S = {'pinnacle': 2 * TIMEOUT_S, 'oddssafari': 3 * TIMEOUT_S, 'livesport': 6 * TIMEOUT_S}

_BOARDS: Dict[Tuple[str, str], list] = {}
_DEAD: set = set()                      # (source, sport) that failed in this run


def _warn(msg: str) -> None:
    print(f'WARNING best price: {msg}', file=sys.stderr, flush=True)


def _timed(fn: Callable[[], Any], budget: float) -> Any:
    box: Dict[str, Any] = {}

    def run() -> None:
        try:
            box['v'] = fn()
        except Exception as e:          # noqa: BLE001 – reported by the caller
            box['e'] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        raise TimeoutError(f'no answer within {budget:g} s')
    if 'e' in box:
        raise box['e']
    return box.get('v')


def _odds(home: Any, draw: Any, away: Any) -> Dict[str, Any]:
    return {'home': home, 'draw': draw, 'away': away}


def _pinnacle(home: str, away: str, sport: str, day: Optional[str]) -> Optional[Dict[str, Any]]:
    import forebet_pipeline as fp
    r = fp.pinnacle_odds(home, away, sport, day)
    return _odds(r.get('home_odds'), r.get('draw_odds'), r.get('away_odds')) if r else None


def _oddssafari(home: str, away: str, sport: str, day: Optional[str]) -> Optional[Dict[str, Any]]:
    import oddssafari_coupons as osc
    key = (sport, day or '')
    if key not in _BOARDS:
        dates = None
        if day:
            d0 = date.fromisoformat(day)
            dates = [d0.isoformat(), (d0 + timedelta(days=1)).isoformat()]
        _BOARDS[key] = osc.fetch_coupon_board(sport, dates=dates) or []
    row = osc.find_coupon_match(home, away, _BOARDS[key])
    if not row:
        return None
    out = _odds(row.home_odds, row.draw_odds, row.away_odds)
    out['books'] = int(row.bookmakers or 0)
    out['kickoff'] = row.kickoff or None
    return out


def _livesport(home: str, away: str, sport: str, day: Optional[str]) -> Optional[Dict[str, Any]]:
    import livesport_bulk_odds as lb
    r = lb.lookup(home, away, sport, day)
    return _odds(r.get('home_odds'), r.get('draw_odds'), r.get('away_odds')) if r else None


# name -> callable(home, away, sport, day) -> {'home','draw','away'[, 'books', 'kickoff']} | None
SOURCES: Dict[str, Callable[..., Optional[Dict[str, Any]]]] = {
    'pinnacle': _pinnacle, 'oddssafari': _oddssafari, 'livesport': _livesport,
}
# Module each built-in source imports. It is imported before the time budget
# starts: on a fresh Actions checkout forebet_pipeline compiles and imports for
# several seconds, which is not an HTTP wait and must not mark Pinnacle dead.
_MODULES: Dict[Callable[..., Any], str] = {
    _pinnacle: 'forebet_pipeline', _oddssafari: 'oddssafari_coupons',
    _livesport: 'livesport_bulk_odds',
}


def _side(pick: Dict[str, Any]) -> Tuple[str, str, str]:
    home, _, away = str(pick.get('match') or '').partition(' vs ')
    side = pick.get('side') or ('away' if pick.get('pick') == away and away else 'home')
    return home, away, side


def _comparable(a: Optional[str], b: Optional[str]) -> bool:
    """3-way (draw = loss) only compares with 3-way; 2way and 2way_equiv both include OT."""
    return (a == '3way') == (b == '3way')


def drop_outliers(quotes: Dict[str, float]) -> Dict[str, float]:
    """Drop quotes > OUTLIER_RATIO × median of the other quotes."""
    keep = {}
    for src, q in quotes.items():
        others = [v for s, v in quotes.items() if s != src]
        if others and q > OUTLIER_RATIO * statistics.median(others):
            _warn(f'{src} quote {q} ignored (>{OUTLIER_RATIO}x median of {sorted(others)})')
            continue
        keep[src] = q
    return keep


def best_price(pick: Dict[str, Any], day: Optional[str] = None) -> Dict[str, Any]:
    """{'bestOdds', 'bestOddsSource', 'bestOddsAt', 'booksCount', 'quotes', 'kickoff'}.

    ``bestOdds`` is None when no source answered with a usable quote; ``kickoff``
    is an explicit UTC kickoff from OddsSafari when it matched (else None).
    """
    sport = str(pick.get('sport') or '')
    home, away, side = _side(pick)
    market = pick.get('oddsMarket')
    quotes: Dict[str, float] = {}
    books: Dict[str, int] = {}
    kickoff = None
    for src, fn in SOURCES.items():
        if (src, sport) in _DEAD or not home or not away:
            continue
        try:
            if fn in _MODULES:
                importlib.import_module(_MODULES[fn])
            raw = _timed(lambda: fn(home, away, sport, day), BUDGET_S.get(src, TIMEOUT_S))
        except Exception as e:          # noqa: BLE001 – any source failure is skipped
            _DEAD.add((src, sport))
            _warn(f'{src} {sport} skipped ({type(e).__name__}: {str(e)[:80]})')
            continue
        if not raw:
            continue
        q, q_market = pricing.side_price(raw, sport, side)
        if q is None or not _comparable(market, q_market) or not MIN_QUOTE <= q <= MAX_QUOTE:
            continue
        quotes[src] = round(float(q), 3)
        books[src] = max(1, int(raw.get('books') or 1))
        if raw.get('kickoff') and not kickoff:
            kickoff = raw['kickoff']
    kept = drop_outliers(quotes)
    out: Dict[str, Any] = {'bestOdds': None, 'bestOddsSource': None, 'bestOddsAt': None,
                           'booksCount': 0, 'quotes': kept, 'kickoff': kickoff}
    if kept:
        src = max(kept, key=lambda s: kept[s])
        # OddsSafari reports how many bookmakers price the fixture; the others are one book.
        out.update(bestOdds=round(kept[src], 2), bestOddsSource=src,
                   bestOddsAt=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   booksCount=max(len(kept), max(books[s] for s in kept)))
    return out
