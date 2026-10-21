"""Reader for the dropping-odds archive, shaped for the web UI.

``outputs/oddssafari_dropping_<date>_<sport>.json`` holds, per run, every event
OddsSafari listed plus the subset that qualified. The website never touched this
archive — ``api_server`` reads only ``results/`` — so 1 099 qualified price moves
with form and head-to-head attached were invisible to readers while feeding only
the e-mails.

Kept separate from ``api_server`` so the parsing is testable without a Flask
request, and because the file layout changed once already: a run writes
``{'meta': ..., 'events': [...], 'qualified': [...]}``, and an older shape put a
bare list at the top level.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional

OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs')
_FILE_RE = re.compile(r'oddssafari_dropping_(\d{4}-\d{2}-\d{2})(?:_([a-z_]+))?\.json$')


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, list):
        # Older runs wrote a bare list and carried no meta.
        return {'meta': {}, 'events': data, 'qualified': data}
    return data if isinstance(data, dict) else None


def available_dates(outputs_dir: str = OUTPUTS_DIR) -> List[str]:
    """Dates that have at least one dropping-odds file, newest first."""
    dates = set()
    for path in glob.glob(os.path.join(outputs_dir, 'oddssafari_dropping_*.json')):
        match = _FILE_RE.search(os.path.basename(path))
        if match:
            dates.add(match.group(1))
    return sorted(dates, reverse=True)


def _normalise(event: Dict[str, Any], generated_at: str) -> Dict[str, Any]:
    """One qualified event in the shape the UI consumes."""
    enrichment = event.get('enrichment') if isinstance(event.get('enrichment'), dict) else {}

    def _num(value: Any) -> Optional[float]:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return None if out != out else out  # drop NaN

    return {
        'matchId': event.get('match_id'),
        'sport': event.get('sport') or 'unknown',
        'league': event.get('league') or enrichment.get('league') or '',
        'homeTeam': event.get('home_team') or '',
        'awayTeam': event.get('away_team') or '',
        'eventDate': event.get('event_date') or '',
        'eventTime': event.get('event_time') or enrichment.get('match_time') or '',
        'matchUrl': event.get('match_url') or '',
        'livesportUrl': event.get('livesport_url') or '',

        # The move itself. `outcome` is the side the price fell on.
        'outcome': event.get('dropped_outcome') or event.get('outcome') or '',
        'focusTeam': event.get('focus_team') or '',
        'openOdds': _num(event.get('open_odds')),
        'currentOdds': _num(event.get('current_odds')),
        'maxOdds': _num(event.get('max_odds')),
        'dropPct': _num(event.get('drop_pct')),

        # Analysis already attached by the pipeline. Present on 593 of 1 099
        # qualified events, so every field here can legitimately be absent.
        'homeForm': enrichment.get('home_form_overall') or enrichment.get('home_form') or [],
        'awayForm': enrichment.get('away_form_overall') or enrichment.get('away_form') or [],
        'h2hCount': enrichment.get('h2h_count'),
        'h2hHomeWins': enrichment.get('home_wins_in_h2h_last5'),
        'h2hAwayWins': enrichment.get('away_wins_in_h2h_last5'),
        'h2hWinRate': _num(enrichment.get('win_rate')),
        'lastH2hDate': enrichment.get('last_h2h_date') or '',
        'lastH2hScore': enrichment.get('last_h2h_score') or '',
        'formAdvantage': bool(enrichment.get('form_advantage')),
        'favorite': enrichment.get('favorite') or '',
        'advancedScore': _num(enrichment.get('advanced_score')),
        'forebetPrediction': enrichment.get('forebet_prediction') or '',
        'forebetProbability': _num(enrichment.get('forebet_probability')),

        'enrichmentStatus': event.get('enrichment_status') or '',
        'scrapedAt': generated_at,
    }


_OUTCOME_TO_SIDE = {'1': 'home', '2': 'away', 'X': 'draw', 'x': 'draw'}


def _attach_verdicts(events: List[Dict[str, Any]], model: Optional[Dict[str, Any]]) -> None:
    """Add the advisor's verdict to each event, in place.

    The model is rebuilt daily from settled history by dropping_odds_advisor.
    Without it every event says "no data" rather than inventing a verdict.
    """
    try:
        from dropping_odds_advisor import verdict_for
    except Exception:
        verdict_for = None

    for event in events:
        side = _OUTCOME_TO_SIDE.get(str(event.get('outcome') or ''))
        verdict = verdict_for(model, event['sport'], side) if (verdict_for and model and side) else None
        if not verdict:
            event['verdict'] = {'verdict': 'za_malo_danych',
                                'reason': 'brak modelu historycznego', 'n': 0}
            continue
        event['verdict'] = {
            'verdict': verdict.get('verdict'),
            'reason': verdict.get('reason'),
            'segment': verdict.get('segment'),
            'n': verdict.get('n'),
            'hitRate': verdict.get('hitRate'),
            'roi': verdict.get('roi'),
            'roiRealistic': verdict.get('roiRealistic'),
        }


def load_dropping_odds(date: Optional[str] = None,
                       sport: Optional[str] = None,
                       outputs_dir: str = OUTPUTS_DIR) -> Dict[str, Any]:
    """Qualified price moves for a date, newest scrape of each event winning.

    The workflow runs three times a day, so the same event appears in several
    files. Keyed by match id and outcome, the latest scrape replaces earlier
    ones — otherwise the board would show one event three times with three
    different prices.
    """
    dates = available_dates(outputs_dir)
    target = date or (dates[0] if dates else None)
    if not target:
        return {'date': None, 'events': [], 'sportCounts': {}, 'availableDates': []}

    pattern = os.path.join(outputs_dir, f'oddssafari_dropping_{target}*.json')
    by_key: Dict[str, Dict[str, Any]] = {}

    for path in sorted(glob.glob(pattern)):
        payload = _read(path)
        if not payload:
            continue
        generated_at = str((payload.get('meta') or {}).get('generated_at') or '')
        for event in (payload.get('qualified') or []):
            if not isinstance(event, dict):
                continue
            normalised = _normalise(event, generated_at)
            if sport and sport != 'all' and normalised['sport'] != sport:
                continue
            key = f"{normalised['matchId']}|{normalised['outcome']}"
            previous = by_key.get(key)
            # Later scrape wins; when neither carries a timestamp the file order
            # decides, which is already oldest-first.
            if previous is None or generated_at >= str(previous.get('scrapedAt') or ''):
                by_key[key] = normalised

    events = sorted(
        by_key.values(),
        # Biggest move first: that is the only reason to look at this board.
        key=lambda e: (-(e['dropPct'] or 0), e['eventTime'] or ''),
    )

    sport_counts: Dict[str, int] = {}
    for event in events:
        sport_counts[event['sport']] = sport_counts.get(event['sport'], 0) + 1

    try:
        from dropping_odds_advisor import load_model
        model = load_model(os.path.join(outputs_dir, 'dropping_odds_model.json'))
    except Exception:
        model = None
    _attach_verdicts(events, model)

    return {
        'model': {
            'settled': model.get('settled'),
            'dateRange': model.get('dateRange'),
            'generatedAt': model.get('generatedAt'),
        } if model else None,
        'date': target,
        'events': events,
        'sportCounts': sport_counts,
        'availableDates': dates[:30],
    }


def summarise(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Headline numbers for the board: how many moves, and how large."""
    drops = [e['dropPct'] for e in events if e.get('dropPct') is not None]
    if not drops:
        return {'count': 0, 'medianDrop': None, 'maxDrop': None, 'bigMoves': 0}
    ordered = sorted(drops)
    middle = len(ordered) // 2
    median = (ordered[middle] if len(ordered) % 2
              else (ordered[middle - 1] + ordered[middle]) / 2)
    return {
        'count': len(drops),
        'medianDrop': round(median, 1),
        'maxDrop': round(max(drops), 1),
        # 20% is where the distribution thins out: 802 of 1 099 archived moves
        # sit in 10-20%, 263 in 20-35%, 34 above.
        'bigMoves': sum(1 for d in drops if d >= 20),
    }
