#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export settled predictions for backtesting
===========================================

The backtest and calibration tools need rows that carry both the pre-match
features *and* the final outcome as ``actual_result`` ('1' / 'X' / '2').
Nothing in the repo produced such a file, which is why the real-data backtest
could never run:

* ``results/*.json``            pre-match predictions only, camelCase keys
* ``outputs/result_store.json`` outcomes only, keyed by match_url
* Supabase ``predictions``      features + ``actual_result`` (needs credentials)

This script builds the missing artefact from either source:

``--source supabase``  read settled rows straight from the predictions table
``--source local``     join ``results/*.json`` (features) with
                       ``outputs/result_store.json`` (outcomes) on match_url

It also translates the camelCase used by ``results/*.json`` into the
snake_case the engines expect, so the export is directly consumable:

    python export_settled.py --source local
    python calibrate_weights.py --real outputs/settled_football.json --optimise

Usage
-----
    python export_settled.py --source supabase --days 90
    python export_settled.py --source local --sport football
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUTCOMES = ('1', 'X', '2')
DEFAULT_OUT = 'outputs/settled_{sport}.json'


# ---------------------------------------------------------------------------
# Key translation
# ---------------------------------------------------------------------------

def _first(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ''):
            return d[k]
    return default


def normalise_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a ``results/*.json`` match into engine (snake_case) shape."""
    odds = raw.get('odds') or {}
    forebet = raw.get('forebet') or {}
    sofa = raw.get('sofascore') or {}
    h2h = raw.get('h2h') or {}
    gemini = raw.get('gemini') or {}

    row: Dict[str, Any] = {
        'home_team': _first(raw, 'home_team', 'homeTeam', default=''),
        'away_team': _first(raw, 'away_team', 'awayTeam', default=''),
        'sport': (_first(raw, 'sport', default='football') or 'football').lower(),
        'league': _first(raw, 'league', default=''),
        'match_date': _first(raw, 'match_date', 'date', default=''),
        'match_url': _first(raw, 'match_url', 'matchUrl', default=''),
        'focus_team': _first(raw, 'focus_team', 'focusTeam', default='home'),

        # Form
        'home_form': _first(raw, 'home_form', 'homeForm', default=[]),
        'away_form': _first(raw, 'away_form', 'awayForm', default=[]),
        'home_form_home': _first(raw, 'home_form_home', 'homeFormHome', default=[]),
        'away_form_away': _first(raw, 'away_form_away', 'awayFormAway', default=[]),
        'form_advantage': _first(raw, 'form_advantage', 'formAdvantage', default=False),

        # Odds
        'home_odds': _first(raw, 'home_odds', default=odds.get('home')),
        'draw_odds': _first(raw, 'draw_odds', default=odds.get('draw')),
        'away_odds': _first(raw, 'away_odds', default=odds.get('away')),

        # Forebet
        'forebet_prediction': _first(raw, 'forebet_prediction',
                                     default=forebet.get('prediction')),
        'forebet_probability': _first(raw, 'forebet_probability',
                                      default=forebet.get('probability')),
        'forebet_exact_score': _first(raw, 'forebet_exact_score',
                                      default=forebet.get('exactScore')),

        # SofaScore
        'sofascore_home_win_prob': _first(raw, 'sofascore_home_win_prob',
                                          default=sofa.get('home')),
        'sofascore_draw_prob': _first(raw, 'sofascore_draw_prob',
                                      default=sofa.get('draw')),
        'sofascore_away_win_prob': _first(raw, 'sofascore_away_win_prob',
                                          default=sofa.get('away')),
        'sofascore_total_votes': _first(raw, 'sofascore_total_votes',
                                        default=sofa.get('votes')),

        # AI analysis. The pick token is what the engine reads; without it the
        # calibrator saw zero AI coverage even on rows the AI had answered,
        # because prose alone cannot be turned into a 1/X/2 probability.
        'gemini_prediction': _first(raw, 'gemini_prediction',
                                    default=gemini.get('prediction')),
        'gemini_pick': _first(raw, 'gemini_pick', 'ai_pick',
                              default=gemini.get('pick')),
        'gemini_confidence': _first(raw, 'gemini_confidence',
                                    default=gemini.get('confidence')),
        'gemini_recommendation': _first(raw, 'gemini_recommendation',
                                        default=gemini.get('recommendation')),
        'ai_provider': _first(raw, 'ai_provider',
                              default=gemini.get('ai_provider')),

        # H2H aggregates (the raw match list is not kept in results/*.json)
        'h2h_last5': _first(raw, 'h2h_last5', default=[]),
        'home_wins_in_h2h_last5': _first(raw, 'home_wins_in_h2h_last5',
                                         default=h2h.get('home')),
        'away_wins_in_h2h_last5': _first(raw, 'away_wins_in_h2h_last5',
                                         default=h2h.get('away')),
        'h2h_count': _first(raw, 'h2h_count', default=h2h.get('total')),
        'win_rate': _first(raw, 'win_rate', default=h2h.get('winRate')),

        # Contract blocks
        'availability': _first(raw, 'availability', default={}),
        'data_quality': _first(raw, 'data_quality', 'dataQuality', default={}),
    }

    # Tennis inputs live in a nested, camelCase `tennis` block that this
    # function never unpacked, so ranking (engine weight 0.11) and surface form
    # (0.12) were invisible to every measurement — a coverage report read 0% and
    # that was indistinguishable from "the scraper never collects them". It does:
    # real rows carry rankingA=127 / rankingB=68 and populated surfaceFormA.
    # Every earlier tennis number was therefore produced by re-scoring rows with
    # almost a quarter of the weight budget missing.
    tennis = raw.get('tennis') or {}
    if isinstance(tennis, dict):
        for src, dst in (
            ('rankingA', 'ranking_a'),
            ('rankingB', 'ranking_b'),
            ('surface', 'surface'),
            ('surfaceFormA', 'surface_form_a'),
            ('surfaceFormB', 'surface_form_b'),
            ('lastMatchA', 'last_match_a'),
            ('lastMatchB', 'last_match_b'),
            ('lastH2H', 'last_h2h'),
            ('probA', 'tennis_prob_a'),
            ('probB', 'tennis_prob_b'),
            ('skipReason', 'tennis_skip_reason'),
        ):
            if src in tennis:
                row[dst] = tennis[src]

        # The engine reads flat `last_match_*_date` / `_result`; the scraper
        # nests them. Unpack so fatigue has something to work with.
        for side in ('a', 'b'):
            block = tennis.get(f'lastMatch{side.upper()}')
            if isinstance(block, dict):
                for src, dst in (('date', 'date'), ('result', 'result'),
                                 ('score', 'score'), ('opponent', 'opponent')):
                    if src in block:
                        row[f'last_match_{side}_{dst}'] = block[src]

    # What the pipeline actually published. Recomputing it from the row is
    # possible, but keeping the recorded values lets a report compare what we
    # claimed at the time against what the current engine would claim now.
    scoring = raw.get('scoring') or {}
    if isinstance(scoring, dict):
        for src, dst in (('pick', 'scoring_pick'), ('prob', 'scoring_prob'),
                         ('ev', 'scoring_ev'), ('edge', 'scoring_edge'),
                         ('kelly', 'scoring_kelly'),
                         ('confidence', 'scoring_confidence')):
            if src in scoring:
                row[dst] = scoring[src]

    for src, dst in (('predictionGrade', 'prediction_grade'),
                     ('prediction_grade', 'prediction_grade'),
                     ('advancedScore', 'advanced_score'),
                     ('advanced_score', 'advanced_score'),
                     ('favorite', 'favorite'),
                     ('qualifies', 'qualifies'),
                     ('time', 'match_time'),
                     ('match_time', 'match_time')):
        if src in raw and raw[src] is not None:
            row[dst] = raw[src]

    # Flat snake_case variants win when present — rows coming straight from the
    # pipeline (not from results/*.json) already use them.
    for key in (
        'ranking_a', 'ranking_b', 'ranking_info',
        'form_a', 'form_b',
        'surface_form_a', 'surface_form_b', 'surface_form_is_proxy',
        'surface_stats_a', 'surface_stats_b',
        'last_match_a_date', 'last_match_a_result', 'last_match_a_score',
        'last_match_b_date', 'last_match_b_result', 'last_match_b_score',
        'tennis_phase_path',
    ):
        if raw.get(key) not in (None, '', [], {}):
            row[key] = raw[key]

    return row


def outcome_from_scores(home: Any, away: Any) -> Optional[str]:
    """Map a final score to '1' / 'X' / '2'."""
    try:
        h, a = int(home), int(away)
    except (TypeError, ValueError):
        return None
    if h > a:
        return '1'
    if h < a:
        return '2'
    return 'X'


def labels_are_usable(rows: List[Dict[str, Any]],
                      min_share: float = 0.02) -> Tuple[bool, str]:
    """Whether the exported outcomes carry a real spread.

    Same bar the calibrator applies, enforced at the source so a corrupt table
    never becomes a training set. Kept here rather than imported so the export
    stays runnable on its own.
    """
    dist: Dict[str, int] = {}
    for row in rows:
        key = str(row.get('actual_result') or '').strip().upper()
        if key in OUTCOMES:
            dist[key] = dist.get(key, 0) + 1

    total = sum(dist.values())
    if total == 0:
        return False, 'brak poprawnych etykiet wyników'
    if len(dist) < 2:
        only = next(iter(dist))
        return False, (f"tylko jedna klasa wyników: '{only}' w {total} "
                       f'wierszach')
    top = max(dist.values()) / total
    if top > 1.0 - min_share:
        return False, (f'rozkład zdegenerowany: {dist} '
                       f'(dominująca klasa {100 * top:.1f}%)')
    return True, f'rozkład wyników: {dist}'


def outcome_from_winner(winner: Any) -> Optional[str]:
    mapping = {'home': '1', 'draw': 'X', 'away': '2'}
    return mapping.get(str(winner or '').strip().lower())


# ---------------------------------------------------------------------------
# Local join: results/*.json  +  outputs/result_store.json
# ---------------------------------------------------------------------------

def load_result_store(path: str = 'outputs/result_store.json') -> Dict[str, Dict[str, Any]]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}
    return {url: r for url, r in data.items() if r.get('status') == 'finished'}


def iter_result_files(sport: Optional[str]) -> Iterable[str]:
    for path in sorted(glob.glob('results/matches_*.json')):
        if sport and sport != 'all' and f'_{sport}' not in os.path.basename(path):
            continue
        yield path


def export_local(sport: Optional[str]) -> List[Dict[str, Any]]:
    """Join pre-match features with scraped outcomes on match_url."""
    store = load_result_store()
    if not store:
        print('outputs/result_store.json is missing or has no finished results.')
        print('It is populated by check_results.py after matches settle.')
        return []

    print(f'result_store: {len(store)} finished matches available')

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for path in iter_result_files(sport):
        try:
            with open(path, 'r', encoding='utf-8-sig') as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        matches = data.get('matches', []) if isinstance(data, dict) else data
        for raw in matches or []:
            url = _first(raw, 'match_url', 'matchUrl', default='')
            if not url or url in seen:
                continue
            res = store.get(url)
            if not res:
                continue
            actual = (outcome_from_scores(res.get('score_home'), res.get('score_away'))
                      or outcome_from_winner(res.get('winner')))
            if actual not in OUTCOMES:
                continue
            row = normalise_row(raw)
            row['actual_result'] = actual
            row['final_score'] = f"{res.get('score_home')}-{res.get('score_away')}"
            out.append(row)
            seen.add(url)

    return out


# ---------------------------------------------------------------------------
# Supabase source
# ---------------------------------------------------------------------------

def export_supabase(days: int, sport: Optional[str]) -> List[Dict[str, Any]]:
    """Read settled rows from the Supabase predictions table."""
    try:
        from supabase_manager import SupabaseManager
    except ImportError as exc:
        print(f'supabase_manager unavailable: {exc}')
        return []

    try:
        mgr = SupabaseManager()
    except Exception as exc:
        print(f'Cannot connect to Supabase: {exc}')
        print('Set SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) and retry.')
        return []

    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    try:
        query = (mgr.client.table('predictions').select('*')
                 .gte('match_date', cutoff)
                 .not_.is_('actual_result', 'null'))
        if sport and sport != 'all':
            query = query.eq('sport', sport)
        resp = query.execute()
        rows = resp.data or []
    except Exception as exc:
        print(f'Supabase query failed: {exc}')
        return []

    out: List[Dict[str, Any]] = []
    for r in rows:
        actual = str(r.get('actual_result') or '').strip().upper()
        if actual not in OUTCOMES:
            continue
        # The table stores odds under forebet_* column names.
        row = normalise_row({
            **r,
            'home_odds': r.get('forebet_home_odds'),
            'draw_odds': r.get('forebet_draw_odds'),
            'away_odds': r.get('forebet_away_odds'),
            'home_form': r.get('livesport_home_form') or [],
            'away_form': r.get('livesport_away_form') or [],
            'home_wins_in_h2h_last5': r.get('livesport_h2h_home_wins'),
            'away_wins_in_h2h_last5': r.get('livesport_h2h_away_wins'),
            'win_rate': r.get('livesport_win_rate'),
        })
        row['actual_result'] = actual
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description='Export settled predictions for backtesting')
    ap.add_argument('--source', choices=['local', 'supabase'], default='local')
    ap.add_argument('--sport', default='football',
                    help="Sport filter, or 'all'")
    ap.add_argument('--days', type=int, default=180,
                    help='Lookback window for --source supabase')
    ap.add_argument('--output', default='',
                    help='Output path (default outputs/settled_<sport>.json)')
    args = ap.parse_args()

    if args.source == 'supabase':
        rows = export_supabase(args.days, args.sport)
    else:
        rows = export_local(args.sport)

    if not rows:
        print('\nNothing exported — no settled matches found.')
        print('Reminder: results/*.json holds pre-match predictions only;')
        print('outcomes come from check_results.py (result_store) or Supabase.')
        return 1

    # Refuse to hand on a label set that carries no information. Supabase
    # returned 1000 rows whose actual_result was '1' for every match across
    # seven sports; the split was printed and went unnoticed, and the model was
    # calibrated against a constant. Failing here lets the backtest fall through
    # to --source local, which is built from freshly scraped outcomes.
    ok, reason = labels_are_usable(rows)
    if not ok:
        print(f'\nOdmawiam eksportu — {reason}')
        print('  Etykiety wynikowe z tego źródła są niewiarygodne, a model')
        print('  dopasowany do nich wygląda dobrze i nie przewiduje niczego.')
        if args.source == 'supabase':
            print('  Spróbuj --source local (wyniki z check_results).')
        return 1

    out_path = args.output or DEFAULT_OUT.format(sport=args.sport)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)

    dist: Dict[str, int] = {}
    for r in rows:
        dist[r['actual_result']] = dist.get(r['actual_result'], 0) + 1
    with_odds = sum(1 for r in rows if r.get('home_odds'))

    print(f'\nExported {len(rows)} settled rows -> {out_path}')
    print(f'  outcome split: ' + ', '.join(f'{k}={dist.get(k, 0)}' for k in OUTCOMES))
    print(f'  rows with odds: {with_odds}/{len(rows)}'
          + ('  (needed for ROI/market baseline)' if with_odds < len(rows) else ''))
    print(f'\nNext: python calibrate_weights.py --real {out_path} --optimise')
    return 0


if __name__ == '__main__':
    sys.exit(main())
