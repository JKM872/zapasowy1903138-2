"""Decides whether a finished workflow run deserves a failure e-mail."""
from __future__ import annotations
import datetime as dt
import os
import sys
MIN_RUN_S = 120  # a pending run cancelled by a concurrency group never ran
def _ts(v: str) -> dt.datetime:
    return dt.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
def should_alert(conclusion: str, started_at: str, updated_at: str) -> bool:
    if conclusion in ('failure', 'timed_out'):
        return True
    if conclusion == 'cancelled':
        try:
            return (_ts(updated_at) - _ts(started_at)).total_seconds() >= MIN_RUN_S
        except (TypeError, ValueError):
            return False
    return False
if __name__ == '__main__':
    e = os.environ
    print('true' if should_alert(e.get('WF_CONCLUSION', ''), e.get('WF_STARTED', ''),
                                 e.get('WF_UPDATED', '')) else 'false')
    sys.exit(0)
