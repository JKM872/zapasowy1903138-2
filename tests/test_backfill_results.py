"""Recovering the outcomes of matches we already scraped.

164k fixtures were scraped with their pre-match features; 149k carry a link
with a match id, and their outcomes were never stored â€” result_store held 261
results, 0.2% of the history. Supabase cannot help: its actual_result was '1'
for every row it returned.

The trap here is orientation. The first version of this tool oriented the score
by the team slugs in the Livesport URL, which looks sensible and is wrong: on 40
independently resolved matches, taking the feed as-is agreed 24/24 while the
slug-based orientation disagreed 15/16. A mirrored result is perfectly plausible
and completely wrong, which is why the tool ships with a validation gate.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (HERE, os.path.join(HERE, 'tools')):
    if path not in sys.path:
        sys.path.insert(0, path)

import backfill_results as bf  # noqa: E402

# The feed is a flat KEYĂ·VALUE stream, 'Â¬' between fields and '~' between blocks.
FEED = ('AC\xf71st Quarter\xacIG\xf720\xacIH\xf718\xac~'
        'AC\xf72nd Quarter\xacIG\xf715\xacIH\xf719\xac~'
        'AC\xf73rd Quarter\xacIG\xf722\xacIH\xf717\xac~'
        'AC\xf74th Quarter\xacIG\xf724\xacIH\xf722\xac~')

SET_FEED = ('AC\xf71st Set\xacIG\xf76\xacIH\xf74\xac~'
            'AC\xf72nd Set\xacIG\xf73\xacIH\xf76\xac~'
            'AC\xf73rd Set\xacIG\xf76\xacIH\xf72\xac~')


class TestParseFeed:
    def test_reads_every_period(self):
        assert bf.parse_feed_periods(FEED) == [(20, 18), (15, 19), (22, 17),
                                               (24, 22)]

    def test_blocks_without_scores_are_skipped(self):
        noisy = FEED + 'MIT\xf7REF\xacMIV\xf7Pizarro E. P.\xac~'
        assert len(bf.parse_feed_periods(noisy)) == 4

    @pytest.mark.parametrize('body', ['', '0', None, 'garbage'])
    def test_unusable_bodies_yield_nothing(self, body):
        assert bf.parse_feed_periods(body) == []

    def test_non_numeric_scores_are_ignored(self):
        assert bf.parse_feed_periods('AC\xf71st\xacIG\xf7-\xacIH\xf7-\xac~') == []


class TestFinalScore:
    def test_point_sports_sum_the_periods(self):
        periods = bf.parse_feed_periods(FEED)
        assert bf.final_score(periods, 'basketball') == (81, 76)

    def test_set_sports_count_sets_not_points(self):
        """3-1 in sets can still be fewer points overall."""
        periods = bf.parse_feed_periods(SET_FEED)

        assert bf.final_score(periods, 'tennis') == (2, 1)
        assert bf.final_score(periods, 'table_tennis') == (2, 1)
        assert bf.final_score(periods, 'volleyball') == (2, 1)

    def test_football_sums_goals(self):
        periods = [(1, 0), (1, 2)]
        assert bf.final_score(periods, 'football') == (2, 2)

    def test_no_periods_means_no_score(self):
        assert bf.final_score([], 'football') is None


class TestOutcome:
    @pytest.mark.parametrize('home,away,sport,expected', [
        (2, 1, 'football', 'home'),
        (1, 2, 'football', 'away'),
        (2, 2, 'football', 'draw'),
        (3, 1, 'table_tennis', 'home'),
        (1, 3, 'tennis', 'away'),
    ])
    def test_mapping(self, home, away, sport, expected):
        assert bf.outcome_from_scores(home, away, sport) == expected

    def test_a_level_score_in_a_set_sport_is_not_a_result(self):
        """Sets always produce a winner, so 2-2 means the parse is incomplete."""
        assert bf.outcome_from_scores(2, 2, 'table_tennis') is None


class TestLinkParsing:
    def test_livesport_mid(self):
        url = ('https://www.livesport.com/pl/mecz/koszykowka/'
               'fenerbahce-rDhoZR1l/partizan-GAiz1YL6/?mid=KGJzqHxf')
        assert bf.livesport_mid(url) == 'KGJzqHxf'

    def test_missing_mid(self):
        assert bf.livesport_mid('https://www.livesport.com/pl/mecz/tenis/AB/') is None

    def test_sofascore_event_id(self):
        assert bf.sofascore_event_id(
            'https://www.sofascore.com/football/match/14025188') == '14025188'

    def test_team_slugs_are_cleaned_of_ids(self):
        url = ('https://www.livesport.com/pl/mecz/koszykowka/'
               'fenerbahce-rDhoZR1l/partizan-GAiz1YL6/?mid=X')
        assert bf.livesport_team_slugs(url) == ('fenerbahce', 'partizan')


class TestOrientation:
    def test_matching_order_is_forward(self):
        assert bf.orient('Alpha FC', 'Beta FC', 'Alpha FC', 'Beta FC') is True

    def test_reversed_order_is_detected(self):
        assert bf.orient('Alpha FC', 'Beta FC', 'Beta FC', 'Alpha FC') is False

    def test_unrecognisable_pairing_refuses_to_guess(self):
        """Better an unlabelled match than a result given to the wrong side."""
        assert bf.orient('Alpha', 'Beta', 'Gamma', 'Delta') is None


class TestShape:
    ROW = {'sport': 'football', 'home': 'Alpha', 'away': 'Beta'}

    def test_forward_keeps_the_order(self):
        out = bf._shape({'first': 2, 'second': 1, 'source': 's'}, self.ROW, True)

        assert (out['score_home'], out['score_away']) == (2, 1)
        assert out['winner'] == 'home'
        assert out['orientation_flipped'] is False

    def test_reverse_mirrors_the_score(self):
        out = bf._shape({'first': 2, 'second': 1, 'source': 's'}, self.ROW, False)

        assert (out['score_home'], out['score_away']) == (1, 2)
        assert out['winner'] == 'away'
        assert out['orientation_flipped'] is True

    def test_undecidable_set_score_is_dropped(self):
        row = dict(self.ROW, sport='table_tennis')
        assert bf._shape({'first': 2, 'second': 2, 'source': 's'}, row, True) is None


class TestLivesportPathTakesTheFeedAsIs:
    def test_no_slug_orientation_is_applied(self, monkeypatch):
        """Measured: feed as-is agreed 24/24, slug orientation 15/16 wrong."""
        monkeypatch.setattr(bf, 'fetch_livesport',
                            lambda mid, sport: {'first': 102, 'second': 93,
                                                'source': 'livesport_feed'})
        # URL lists the teams the other way round from the row on purpose.
        row = {'url': ('https://www.livesport.com/pl/mecz/koszykowka/'
                       'blackwater-bossing-bT2/phoenix-fuelmasters-jm3/?mid=X'),
               'sport': 'basketball', 'date': '2026-07-29',
               'home': 'Phoenix Fuelmasters', 'away': 'Blackwater Bossing'}

        got = bf.resolve(row)

        assert got['score_home'] == 102, 'the feed already holds the real order'
        assert got['winner'] == 'home'
        assert got['orientation_flipped'] is False

    def test_sofascore_path_still_orients_by_name(self, monkeypatch):
        """There we do have names, so they are used."""
        monkeypatch.setattr(bf, 'fetch_sofascore',
                            lambda eid: {'first': 3, 'second': 0,
                                         'first_name': 'Beta',
                                         'second_name': 'Alpha',
                                         'source': 'sofascore_event'})
        row = {'url': 'https://www.sofascore.com/football/match/14025188',
               'sport': 'football', 'date': '', 'home': 'Alpha', 'away': 'Beta'}

        got = bf.resolve(row)

        assert (got['score_home'], got['score_away']) == (0, 3)
        assert got['winner'] == 'away'

    def test_unresolvable_link_returns_nothing(self):
        row = {'url': 'https://example.com/whatever', 'sport': 'football',
               'date': '', 'home': 'A', 'away': 'B'}
        assert bf.resolve(row) is None


class TestShardsAndMerge:
    """Parallel jobs cannot share one file, so each writes its own shard."""

    def _shard(self, tmp_path, name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding='utf-8')
        return str(path)

    def test_merge_folds_shards_into_the_store(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        shard = self._shard(tmp_path, 'football.json', {
            'https://x/1': {'status': 'finished', 'score_home': 2,
                            'score_away': 1, 'winner': 'home',
                            'sport': 'football', 'home_team': 'A',
                            'away_team': 'B', 'date': '2026-03-01'},
        })

        assert bf.merge_shards([shard], store_path='outputs/result_store.json') == 0

        store = json.load(open('outputs/result_store.json', encoding='utf-8'))
        assert store['https://x/1']['winner'] == 'home'
        assert store['https://x/1']['sport'] == 'football'

    def test_merge_does_not_overwrite_a_settled_result(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        existing = {'https://x/1': {'status': 'finished', 'winner': 'away',
                                    'score_home': 0, 'score_away': 3}}
        with open('outputs/result_store.json', 'w', encoding='utf-8') as fh:
            json.dump(existing, fh)

        shard = self._shard(tmp_path, 's.json', {
            'https://x/1': {'status': 'finished', 'winner': 'home',
                            'score_home': 9, 'score_away': 0},
        })
        bf.merge_shards([shard], store_path='outputs/result_store.json')

        store = json.load(open('outputs/result_store.json', encoding='utf-8'))
        assert store['https://x/1']['winner'] == 'away', 'settled stays settled'

    def test_merge_survives_a_broken_shard(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        bad = tmp_path / 'bad.json'
        bad.write_text('{not json', encoding='utf-8')

        assert bf.merge_shards([str(bad)], store_path='outputs/result_store.json') == 0
        assert 'pomijam' in capsys.readouterr().out

    def test_known_urls_covers_store_and_shard(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        with open('outputs/result_store.json', 'w', encoding='utf-8') as fh:
            json.dump({'https://in-store': {'status': 'finished'}}, fh)
        shard = self._shard(tmp_path, 'sh.json', {'https://in-shard': {}})

        known = bf._known_urls(shard, store_path='outputs/result_store.json')

        assert 'https://in-store' in known, 'nightly settlement is not re-fetched'
        assert 'https://in-shard' in known, 'a resumed run skips its own work'

    def test_known_urls_without_a_shard(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        with open('outputs/result_store.json', 'w', encoding='utf-8') as fh:
            json.dump({'https://a': {}}, fh)

        assert bf._known_urls('', store_path='outputs/result_store.json') == {'https://a'}


class TestSurvivesAHostileEnvironment:
    """The first CI run died on its first SofaScore link after 173 matches.

    ``sofascore_scraper`` failed at import time on a runner without selenium,
    because a type annotation referenced ``webdriver.Chrome`` unquoted. A
    NameError is not an ImportError, so the guard around the import did not
    catch it and the whole 63k-match job ended with exit code 1.
    """

    def test_sofascore_falls_back_when_the_scraper_module_explodes(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def hostile(name, *args, **kwargs):
            if name == 'sofascore_scraper':
                raise NameError("name 'webdriver' is not defined")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, '__import__', hostile)

        class Resp:
            status_code = 200

            @staticmethod
            def json():
                return {'event': {'status': {'type': 'finished'},
                                  'homeTeam': {'name': 'Alpha'},
                                  'awayTeam': {'name': 'Beta'},
                                  'homeScore': {'current': 2},
                                  'awayScore': {'current': 1}}}

        monkeypatch.setattr(bf, '_get', lambda url, headers, timeout=20: Resp())

        got = bf.fetch_sofascore('123456')

        assert got is not None, 'a heavy optional module must not be a hard dependency'
        assert (got['first'], got['second']) == (2, 1)

    def test_a_failing_fixture_does_not_end_the_run(self, monkeypatch, tmp_path,
                                                   capsys):
        """Hours of banked work must not be lost to one bad row."""
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')

        calls = {'n': 0}

        def flaky(row):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('boom')
            return {'status': 'finished', 'score_home': 1, 'score_away': 0,
                    'winner': 'home', 'source': 'test',
                    'orientation_flipped': False}

        monkeypatch.setattr(bf, 'resolve', flaky)
        monkeypatch.setattr(bf, 'iter_history', lambda month, sport: [
            {'url': f'https://x/{i}', 'sport': 'football', 'date': '2026-03-01',
             'home': 'A', 'away': 'B'} for i in range(3)])
        monkeypatch.setattr(sys, 'argv', [
            'backfill_results.py', '--delay', '0',
            '--store', 'outputs/shard.json'])
        # Isolate from the committed store, which is what the tool consults to
        # avoid re-fetching. An earlier version of this test wrote its fake URL
        # into the real one.
        monkeypatch.setattr(bf, '_known_urls', lambda *a, **kw: set())

        assert bf.main() == 0
        out = capsys.readouterr().out
        assert 'RuntimeError' in out
        assert 'ok=2' in out, 'the run continued past the failure'

    def test_no_unquoted_webdriver_annotations_remain(self):
        """The landmine any importer of the scraper would step on.

        Only parameter annotations matter — an annotation is evaluated when the
        function is defined, so it breaks the import itself. Prose mentioning
        webdriver in a comment is fine.
        """
        import re

        source = open(os.path.join(HERE, 'sofascore_scraper.py'),
                      encoding='utf-8').read()
        assert not re.search(r'^\s*\w+:\s*webdriver\.', source, re.MULTILINE)
        assert not re.search(r'\(\s*\w+:\s*webdriver\.', source)
