#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📊 COMPARE MODES — Porównanie skuteczności home-focus vs away-focus

Wczytuje manifesty i podsumowania wyników za podany zakres dat,
dzieli mecze na kohorty (home / away / łącznie) i generuje raport.

Użycie:
  python compare_modes.py --from 2026-03-01 --to 2026-03-21
  python compare_modes.py --from 2026-03-01  # do dziś
"""

import argparse
import glob
import json
import math
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple


# ─── Data loading ────────────────────────────────────────────────────────

def _dates_in_range(start: str, end: str) -> List[str]:
    """Return list of YYYY-MM-DD strings from *start* to *end* inclusive."""
    d = datetime.strptime(start, '%Y-%m-%d')
    d_end = datetime.strptime(end, '%Y-%m-%d')
    dates: List[str] = []
    while d <= d_end:
        dates.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    return dates


def load_summaries(start: str, end: str) -> List[Dict[str, Any]]:
    """Load all results_summary JSON files for date range.

    Each file's ``matches`` list is flattened into a single list.
    """
    all_matches: List[Dict[str, Any]] = []
    for date in _dates_in_range(start, end):
        path = f'outputs/results_summary_{date}.json'
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for m in data.get('matches', []):
                m.setdefault('date', date)
                all_matches.append(m)
        except (json.JSONDecodeError, OSError):
            pass
    return all_matches


def load_manifests_range(start: str, end: str) -> List[Dict[str, Any]]:
    """Load manifest files for all dates in range (if no summaries yet)."""
    all_matches: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for date in _dates_in_range(start, end):
        for fpath in sorted(glob.glob(f'outputs/mailed_manifest_{date}*.json')):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for m in data:
                    url = m.get('match_url', '')
                    if url and url not in seen:
                        m.setdefault('date', date)
                        all_matches.append(m)
                        seen.add(url)
            except (json.JSONDecodeError, OSError):
                pass
    return all_matches


# ─── Cohort splitting ────────────────────────────────────────────────────

def split_by_focus(matches: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Split matches into cohorts by focus_team (home / away)."""
    cohorts: Dict[str, List[Dict[str, Any]]] = {'home': [], 'away': []}
    for m in matches:
        ft = (m.get('focus_team') or 'home').lower()
        cohorts.setdefault(ft, []).append(m)
    return cohorts


# ─── Cohort statistics ───────────────────────────────────────────────────

def _cohort_stats(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute accuracy, ROI and per-sport breakdown for one cohort.

    Works with both summary-style dicts (``outcome`` key) and
    manifest-style dicts (may lack ``outcome`` → treated as pending).
    """
    won = lost = draw = pending = errors = 0
    roi_total = 0.0
    roi_count = 0
    stake = 100
    by_sport: Dict[str, Dict[str, int]] = {}

    for m in matches:
        outcome = (m.get('outcome') or 'pending').lower()
        sport = (m.get('sport') or 'unknown').lower()

        if sport not in by_sport:
            by_sport[sport] = {'won': 0, 'lost': 0, 'draw': 0, 'pending': 0}
        sp = by_sport[sport]

        if outcome == 'won':
            won += 1
            sp['won'] += 1
        elif outcome == 'lost':
            lost += 1
            sp['lost'] += 1
        elif outcome == 'draw':
            draw += 1
            sp['draw'] += 1
        elif outcome == 'error':
            errors += 1
        else:
            pending += 1
            sp['pending'] += 1

        # ROI (only for decided matches with valid odds)
        if outcome in ('won', 'lost'):
            predicted = (m.get('predicted') or 'home').lower()
            odds_key = 'home_odds' if predicted == 'home' else 'away_odds'
            odds = m.get(odds_key)
            try:
                odds_f = float(odds)
                if math.isnan(odds_f):
                    continue
            except (TypeError, ValueError):
                continue
            if outcome == 'won':
                roi_total += odds_f * stake - stake
            else:
                roi_total -= stake
            roi_count += 1

    decided = won + lost
    accuracy = (won / decided * 100) if decided > 0 else 0.0
    roi_pct = (roi_total / (roi_count * stake) * 100) if roi_count > 0 else 0.0

    return {
        'total': len(matches),
        'won': won,
        'lost': lost,
        'draw': draw,
        'pending': pending,
        'errors': errors,
        'decided': decided,
        'accuracy': accuracy,
        'roi_pln': roi_total,
        'roi_pct': roi_pct,
        'by_sport': by_sport,
    }


# ─── Report rendering ────────────────────────────────────────────────────

SPORT_EMOJI = {
    'football': '⚽', 'basketball': '🏀', 'handball': '🤾',
    'volleyball': '🏐', 'tennis': '🎾', 'hockey': '🏒',
}


def render_report(
    home_stats: Dict[str, Any],
    away_stats: Dict[str, Any],
    combined_stats: Dict[str, Any],
    start: str,
    end: str,
) -> str:
    """Build a plain-text comparison report."""
    lines: List[str] = []
    sep = '═' * 70
    thin = '─' * 70

    lines.append(sep)
    lines.append(f'📊 HOME vs AWAY  —  {start} ➜ {end}')
    lines.append(sep)
    lines.append('')

    # Header row
    lines.append(f'{"":20s} {"HOME":>10s} {"AWAY":>10s} {"ŁĄCZNIE":>10s}')
    lines.append(thin)

    def _row(label: str, key: str, fmt: str = 'd') -> str:
        h = home_stats.get(key, 0)
        a = away_stats.get(key, 0)
        c = combined_stats.get(key, 0)
        if fmt == 'f':
            return f'{label:20s} {h:>10.1f} {a:>10.1f} {c:>10.1f}'
        if fmt == 'pct':
            return f'{label:20s} {h:>9.1f}% {a:>9.1f}% {c:>9.1f}%'
        if fmt == 'pln':
            return f'{label:20s} {h:>+10.0f} {a:>+10.0f} {c:>+10.0f}'
        return f'{label:20s} {h:>10d} {a:>10d} {c:>10d}'

    lines.append(_row('Mecze', 'total'))
    lines.append(_row('✅ Wygrane', 'won'))
    lines.append(_row('❌ Przegrane', 'lost'))
    lines.append(_row('🟡 Remisy', 'draw'))
    lines.append(_row('⏳ Pending', 'pending'))
    lines.append(thin)
    lines.append(_row('Zdecydowane', 'decided'))
    lines.append(_row('Trafność', 'accuracy', 'pct'))
    lines.append(_row('ROI %', 'roi_pct', 'pct'))
    lines.append(_row('ROI PLN', 'roi_pln', 'pln'))
    lines.append('')

    # Per-sport breakdown
    all_sports = sorted(
        set(list(home_stats['by_sport'].keys()) + list(away_stats['by_sport'].keys()))
    )
    if all_sports:
        lines.append(thin)
        lines.append('📈 PER SPORT')
        lines.append(thin)
        lines.append(
            f'{"Sport":16s} '
            f'{"H-Won":>6s} {"H-Lost":>7s} {"H-Acc":>6s}  '
            f'{"A-Won":>6s} {"A-Lost":>7s} {"A-Acc":>6s}'
        )
        for sport in all_sports:
            emoji = SPORT_EMOJI.get(sport, '🏆')
            hs = home_stats['by_sport'].get(sport, {})
            as_ = away_stats['by_sport'].get(sport, {})
            hw, hl = hs.get('won', 0), hs.get('lost', 0)
            aw, al = as_.get('won', 0), as_.get('lost', 0)
            hd = hw + hl
            ad = aw + al
            h_acc = (hw / hd * 100) if hd > 0 else 0
            a_acc = (aw / ad * 100) if ad > 0 else 0
            lines.append(
                f'{emoji} {sport:13s} '
                f'{hw:>6d} {hl:>7d} {h_acc:>5.0f}%  '
                f'{aw:>6d} {al:>7d} {a_acc:>5.0f}%'
            )
        lines.append('')

    lines.append(sep)
    return '\n'.join(lines)


# ─── Public API ───────────────────────────────────────────────────────────

def compare(start: str, end: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Run full comparison and return (home_stats, away_stats, combined_stats, report_text).

    Prefers results_summary files (settled outcomes). Falls back to raw manifests
    if summaries are absent (but then outcomes will be 'pending').
    """
    matches = load_summaries(start, end)
    source = 'summaries'
    if not matches:
        matches = load_manifests_range(start, end)
        source = 'manifests'
    if not matches:
        empty: Dict[str, Any] = _cohort_stats([])
        return empty, empty, empty, f'⚠️ Brak danych za okres {start} — {end}'

    print(f'📂 Źródło: {source}, wczytano {len(matches)} meczów')

    cohorts = split_by_focus(matches)
    home_stats = _cohort_stats(cohorts.get('home', []))
    away_stats = _cohort_stats(cohorts.get('away', []))
    combined_stats = _cohort_stats(matches)

    report = render_report(home_stats, away_stats, combined_stats, start, end)
    return home_stats, away_stats, combined_stats, report


# ─── CLI ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description='Porównanie home-focus vs away-focus')
    parser.add_argument('--from', dest='start', required=True, help='Data początkowa (YYYY-MM-DD)')
    parser.add_argument('--to', dest='end', default=None, help='Data końcowa (YYYY-MM-DD, domyślnie dziś)')
    args = parser.parse_args()

    end = args.end or datetime.now().strftime('%Y-%m-%d')
    _home, _away, _combined, report = compare(args.start, end)
    print(report)


if __name__ == '__main__':
    main()
