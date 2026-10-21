"""Reading the dropping-odds archive for the web UI.

The workflow runs three times a day, so one event lands in several files with a
different price each time. Showing all of them would put the same match on the
board three times at three prices, so the newest scrape has to win.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dropping_odds_feed as feed


def write(tmp_path, date, sport, events, generated_at, qualified=None):
    payload = {
        'meta': {'generated_at': generated_at, 'target_date': date},
        'events': events,
        'qualified': qualified if qualified is not None else events,
    }
    path = tmp_path / f'oddssafari_dropping_{date}_{sport}.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def event(match_id=1, outcome='1', drop=20.0, current=1.93, open_odds=3.09,
          home='VfB Lubeck', away='HSC Hannover', sport='football', **extra):
    row = {
        'match_id': match_id, 'sport': sport, 'league': 'Regionalliga',
        'home_team': home, 'away_team': away,
        'event_date': '12/09', 'event_time': '12:00',
        'match_url': 'https://oddssafari.test/m/1',
        'outcome': outcome, 'dropped_outcome': outcome, 'focus_team': 'home',
        'open_odds': open_odds, 'current_odds': current, 'max_odds': 1.95,
        'drop_pct': drop, 'qualifies': True,
    }
    row.update(extra)
    return row


class TestLoading:
    def test_qualified_events_are_returned(self, tmp_path):
        write(tmp_path, '2026-09-12', 'football', [event()], '2026-09-12T09:00:00+02:00')
        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert out['date'] == '2026-09-12'
        assert len(out['events']) == 1
        assert out['events'][0]['homeTeam'] == 'VfB Lubeck'

    def test_only_qualified_are_shown(self, tmp_path):
        """`events` holds the whole card; the board shows the qualified subset."""
        write(tmp_path, '2026-09-12', 'football',
              [event(match_id=1), event(match_id=2)],
              '2026-09-12T09:00:00+02:00',
              qualified=[event(match_id=1)])
        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert [e['matchId'] for e in out['events']] == [1]

    def test_the_latest_scrape_of_an_event_wins(self, tmp_path):
        write(tmp_path, '2026-09-12', 'football',
              [event(current=2.10, drop=12.0)], '2026-09-12T09:00:00+02:00')
        write(tmp_path, '2026-09-12', 'tennis',
              [event(current=1.70, drop=31.0)], '2026-09-12T15:00:00+02:00')

        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert len(out['events']) == 1, 'the same event must not appear twice'
        assert out['events'][0]['currentOdds'] == pytest.approx(1.70)
        assert out['events'][0]['dropPct'] == pytest.approx(31.0)

    def test_two_outcomes_of_one_match_are_both_kept(self, tmp_path):
        """A price can fall on either side; those are different observations."""
        write(tmp_path, '2026-09-12', 'football',
              [event(match_id=7, outcome='1'), event(match_id=7, outcome='2')],
              '2026-09-12T09:00:00+02:00')
        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert len(out['events']) == 2

    def test_biggest_move_comes_first(self, tmp_path):
        write(tmp_path, '2026-09-12', 'football',
              [event(match_id=1, drop=12.0), event(match_id=2, drop=45.0)],
              '2026-09-12T09:00:00+02:00')
        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert [e['dropPct'] for e in out['events']] == [45.0, 12.0]

    def test_sport_filter(self, tmp_path):
        write(tmp_path, '2026-09-12', 'mixed',
              [event(match_id=1, sport='football'), event(match_id=2, sport='tennis')],
              '2026-09-12T09:00:00+02:00')
        out = feed.load_dropping_odds(sport='tennis', outputs_dir=str(tmp_path))
        assert [e['sport'] for e in out['events']] == ['tennis']

    def test_sport_counts_are_reported(self, tmp_path):
        write(tmp_path, '2026-09-12', 'mixed',
              [event(match_id=1, sport='football'), event(match_id=2, sport='football'),
               event(match_id=3, sport='tennis')],
              '2026-09-12T09:00:00+02:00')
        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert out['sportCounts'] == {'football': 2, 'tennis': 1}

    def test_an_empty_directory_is_not_an_error(self, tmp_path):
        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert out == {'date': None, 'events': [], 'sportCounts': {},
                       'availableDates': []}

    def test_a_corrupt_file_is_skipped(self, tmp_path):
        (tmp_path / 'oddssafari_dropping_2026-09-12_football.json').write_text(
            '{not json', encoding='utf-8')
        write(tmp_path, '2026-09-11', 'tennis', [event()], '2026-09-11T09:00:00+02:00')
        out = feed.load_dropping_odds(date='2026-09-11', outputs_dir=str(tmp_path))
        assert len(out['events']) == 1

    def test_the_older_bare_list_shape_still_loads(self, tmp_path):
        path = tmp_path / 'oddssafari_dropping_2026-09-12_football.json'
        path.write_text(json.dumps([event()]), encoding='utf-8')
        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert len(out['events']) == 1


class TestAttachedAnalysis:
    def test_form_and_h2h_travel_with_the_event(self, tmp_path):
        write(tmp_path, '2026-09-12', 'football', [event(enrichment={
            'home_form_overall': ['W', 'L', 'W'],
            'away_form_overall': ['L', 'L', 'W'],
            'h2h_count': 10, 'home_wins_in_h2h_last5': 3,
            'away_wins_in_h2h_last5': 7, 'win_rate': 0.7,
            'last_h2h_score': '2-1', 'advanced_score': 61.5,
        })], '2026-09-12T09:00:00+02:00')

        e = feed.load_dropping_odds(outputs_dir=str(tmp_path))['events'][0]
        assert e['homeForm'] == ['W', 'L', 'W']
        assert e['h2hCount'] == 10
        assert e['h2hWinRate'] == pytest.approx(0.7)
        assert e['lastH2hScore'] == '2-1'
        assert e['advancedScore'] == pytest.approx(61.5)

    def test_missing_analysis_is_absent_not_invented(self, tmp_path):
        """Only 593 of 1 099 archived events carry enrichment."""
        write(tmp_path, '2026-09-12', 'football', [event()], '2026-09-12T09:00:00+02:00')
        e = feed.load_dropping_odds(outputs_dir=str(tmp_path))['events'][0]
        assert e['homeForm'] == []
        assert e['h2hCount'] is None
        assert e['advancedScore'] is None


class TestSummary:
    def test_headline_numbers(self, tmp_path):
        events = [{'dropPct': 12.0}, {'dropPct': 25.0}, {'dropPct': 40.0}]
        out = feed.summarise(events)
        assert out['count'] == 3
        assert out['medianDrop'] == pytest.approx(25.0)
        assert out['maxDrop'] == pytest.approx(40.0)
        assert out['bigMoves'] == 2

    def test_no_events_gives_no_figures(self):
        assert feed.summarise([])['medianDrop'] is None


class TestVerdicts:
    def test_events_carry_the_model_verdict(self, tmp_path):
        write(tmp_path, '2026-09-12', 'hockey',
              [event(sport='hockey', outcome='1')], '2026-09-12T09:00:00+02:00')
        (tmp_path / 'dropping_odds_model.json').write_text(json.dumps({
            'settled': 349, 'dateRange': {'from': 'a', 'to': 'b'},
            'segments': {'hockey|home': {'verdict': 'warto', 'reason': 'x',
                                         'n': 199, 'roi': 21.0, 'roiRealistic': 14.9}},
        }), encoding='utf-8')

        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        v = out['events'][0]['verdict']
        assert v['verdict'] == 'warto'
        assert v['n'] == 199
        assert out['model']['settled'] == 349

    def test_without_a_model_nothing_is_invented(self, tmp_path):
        write(tmp_path, '2026-09-12', 'hockey',
              [event(sport='hockey', outcome='1')], '2026-09-12T09:00:00+02:00')
        out = feed.load_dropping_odds(outputs_dir=str(tmp_path))
        assert out['events'][0]['verdict']['verdict'] == 'za_malo_danych'
        assert out['model'] is None
