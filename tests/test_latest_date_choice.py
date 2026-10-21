"""Which day the board opens on when the visitor picks none.

Production showed 2026-03-10 in October. Two causes stacked: the Supabase date
query had no ORDER BY and PostgREST caps an unbounded select at 1 000 rows, so
"latest" came from the oldest thousand predictions; and the API preferred that
date over the files the scrapers write every day.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_server


class _Query:
    def __init__(self, log):
        self.log = log

    def select(self, *_):
        return self

    def order(self, column, desc=False):
        self.log.append(('order', column, desc))
        return self

    def limit(self, n):
        self.log.append(('limit', n))
        return self

    def execute(self):
        class R:
            data = [{'match_date': '2026-10-20'}, {'match_date': '2026-10-19'}]
        return R()


def test_dates_are_sorted_newest_first_on_the_server():
    from supabase_manager import SupabaseManager

    log = []
    mgr = SupabaseManager.__new__(SupabaseManager)
    mgr.client = type('C', (), {'table': lambda self, _: _Query(log)})()

    assert mgr.get_available_dates()[0] == '2026-10-20'
    assert ('order', 'match_date', True) in log, 'without ORDER BY the 1000-row cap hides new days'


def test_latest_local_date_reads_filenames(tmp_path, monkeypatch):
    for name in ('matches_2026-03-10_football.json', 'matches_2026-10-21_tennis.json',
                 'notes.json'):
        (tmp_path / name).write_text('{}', encoding='utf-8')
    monkeypatch.setattr(api_server, 'RESULTS_DIR', str(tmp_path))
    assert api_server._latest_local_date() == '2026-10-21'


def test_a_stale_database_does_not_pin_the_board(tmp_path, monkeypatch):
    (tmp_path / 'matches_2026-10-21_football.json').write_text(
        '{"matches": []}', encoding='utf-8')
    monkeypatch.setattr(api_server, 'RESULTS_DIR', str(tmp_path))

    asked = {}

    class StaleDb:
        def get_available_dates(self):
            return ['2026-03-10']

        def get_predictions(self, date=None, sport=None):
            asked['date'] = date
            return []

    monkeypatch.setattr(api_server, 'supabase', StaleDb())
    monkeypatch.setattr(api_server, 'SUPABASE_AVAILABLE', True)

    api_server.app.config['TESTING'] = True
    api_server.app.test_client().get('/api/matches')
    assert asked.get('date') != '2026-03-10', 'files on disk are newer than the database'
