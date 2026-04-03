#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Result Store — Persistent storage for match results
=====================================================

Accumulates match results across multiple check_results.py runs.
Used by prediction_evaluator.py for backtesting.

File: outputs/result_store.json
Format: {match_url: {status, score_home, score_away, winner, checked_at, sport}}
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


STORE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'outputs', 'result_store.json'
)


class ResultStore:
    """Thread-safe persistent result store."""

    def __init__(self, path: str = STORE_PATH):
        self.path = path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if os.path.isfile(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)

    def add_result(self, match_url: str, result: Dict[str, Any],
                   sport: str = '', home_team: str = '', away_team: str = '',
                   date: str = '') -> bool:
        """Add or update a result. Returns True if new/updated."""
        if not match_url:
            return False

        existing = self._data.get(match_url)
        if existing and existing.get('status') == 'finished':
            return False  # Already have final result

        entry: Dict[str, Any] = {
            'status': result.get('status', 'unknown'),
            'score_home': result.get('score_home'),
            'score_away': result.get('score_away'),
            'winner': result.get('winner'),
            'checked_at': datetime.now().isoformat(),
            'sport': sport,
            'home_team': home_team,
            'away_team': away_team,
            'date': date,
        }

        self._data[match_url] = entry
        return True

    def get_result(self, match_url: str) -> Optional[Dict[str, Any]]:
        return self._data.get(match_url)

    def get_all_finished(self) -> Dict[str, Dict[str, Any]]:
        return {url: r for url, r in self._data.items()
                if r.get('status') == 'finished'}

    def stats(self) -> Dict[str, int]:
        total = len(self._data)
        finished = sum(1 for r in self._data.values() if r.get('status') == 'finished')
        pending = sum(1 for r in self._data.values() if r.get('status') in ('not_finished', 'no_score'))
        errors = sum(1 for r in self._data.values() if r.get('status') == 'error')
        return {'total': total, 'finished': finished, 'pending': pending, 'errors': errors}

    def __len__(self):
        return len(self._data)

    def __contains__(self, match_url: str):
        return match_url in self._data
