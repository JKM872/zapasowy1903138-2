"""Media resolver (design K7): host allowlist, no SofaScore, TTLs, Wikimedia
attribution, ESPN off by default, cache-only API pages."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import team_logo_resolver as tlr


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Empty in-memory cache, cache file in tmp, no real network."""
    cache: dict = {}
    monkeypatch.setattr(tlr, '_mem_cache', cache)
    monkeypatch.setattr(tlr, '_loaded', True)
    monkeypatch.setattr(tlr, '_CACHE_FILE', tmp_path / 'media_cache.json')
    monkeypatch.setattr(tlr, '_LEGACY_CACHE_FILE', tmp_path / 'team_logos_cache.json')
    monkeypatch.delenv('MEDIA_ALLOW_ESPN', raising=False)

    def _no_network(url, source):
        raise AssertionError(f'unexpected request {url}')

    monkeypatch.setattr(tlr, '_get_json', _no_network)
    return cache


def _responder(monkeypatch, routes):
    """_get_json stub: first route whose substring is in the URL answers."""
    calls = []

    def _get(url, source):
        calls.append(url)
        for needle, payload in routes:
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        return {}

    monkeypatch.setattr(tlr, '_get_json', _get)
    return calls


class TestAllowlist:
    @pytest.mark.parametrize('url', [
        'https://r2.thesportsdb.com/images/media/team/badge/x.png',
        'https://www.thesportsdb.com/images/x.png',
        'https://upload.wikimedia.org/wikipedia/commons/a/ab/X.jpg',
        'https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/256px-X.jpg',
    ])
    def test_allowed_hosts(self, url):
        assert tlr.allowed_media_url(url)

    @pytest.mark.parametrize('url', [
        'http://r2.thesportsdb.com/x.png',              # not https
        'https://img.sofascore.com/api/v1/team/1/image',
        'https://api.sofascore.app/api/v1/player/1/image',
        'https://evil.example.com/x.png',
        'https://r2.thesportsdb.com.evil.com/x.png',
        '', None, 'not a url',
    ])
    def test_rejected(self, url):
        assert not tlr.allowed_media_url(url)

    def test_media_from_url_drops_sofascore(self):
        assert tlr.media_from_url('https://img.sofascore.com/api/v1/team/1/image') is None

    def test_page_drops_a_sofascore_logo_from_the_match_file(self, monkeypatch):
        m = {'homeTeam': 'Arsenal', 'awayTeam': 'Chelsea', 'sport': 'football',
             'homeLogo': 'https://img.sofascore.com/api/v1/team/42/image', 'awayLogo': ''}
        tlr.media_for_page([m], live_budget=0)
        assert m['homeLogo'] == '' and m['homeMedia'] is None

    def test_a_cached_entry_on_a_bad_host_is_not_served(self, _isolated):
        _isolated[tlr.cache_key('Arsenal', 'football')] = {
            'url': 'https://img.sofascore.com/x.png', 'source': 'x', 'ts': int(time.time())}
        assert tlr.resolve_media('Arsenal', 'football', network='none') is None


class TestNoSofascore:
    def test_no_sofascore_host_anywhere_in_the_resolver(self):
        src = open(tlr.__file__, encoding='utf-8').read().lower()
        hosts = {h for h in __import__('re').findall(r'https://([a-z0-9.\-]+)', src)}
        assert not any('sofascore' in h for h in hosts)

    def test_committed_cache_has_no_sofascore_urls(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'outputs', 'media_cache.json')
        if not os.path.exists(path):
            pytest.skip('no committed media cache')
        data = json.load(open(path, encoding='utf-8'))
        for key, entry in data.items():
            url = entry.get('url')
            assert url is None or tlr.allowed_media_url(url), (key, url)


class TestTTL:
    def test_values(self):
        assert tlr._CACHE_TTL == 30 * 24 * 3600
        assert tlr._NEGATIVE_TTL == 7 * 24 * 3600
        assert tlr._RATE_LIMIT_TTL == 3600

    @pytest.mark.parametrize('entry,age,fresh', [
        ({'url': 'https://r2.thesportsdb.com/a.png'}, 29 * 86400, True),
        ({'url': 'https://r2.thesportsdb.com/a.png'}, 31 * 86400, False),
        ({'url': None, 'miss': 'none'}, 6 * 86400, True),
        ({'url': None, 'miss': 'none'}, 8 * 86400, False),
        ({'url': None, 'miss': 'error'}, 6 * 86400, True),
        ({'url': None, 'miss': '429'}, 30 * 60, True),
        ({'url': None, 'miss': '429'}, 2 * 3600, False),
    ])
    def test_freshness(self, entry, age, fresh):
        now = time.time()
        assert tlr._fresh(dict(entry, ts=now - age), now) is fresh

    def test_a_fresh_miss_is_not_looked_up_again(self, _isolated):
        _isolated[tlr.cache_key('Nobody FC', 'football')] = {'url': None, 'miss': 'none', 'ts': int(time.time())}
        assert tlr.resolve_media('Nobody FC', 'football') is None   # _get_json would raise

    def test_429_is_cached_for_one_hour(self, monkeypatch, _isolated):
        _responder(monkeypatch, [('thesportsdb', tlr._RateLimited('thesportsdb'))])
        assert tlr.resolve_media('Arsenal', 'football') is None
        entry = _isolated[tlr.cache_key('Arsenal', 'football')]
        assert entry['miss'] == '429' and tlr._ttl(entry) == 3600

    def test_a_stale_hit_survives_a_failed_refresh(self, monkeypatch, _isolated):
        key = tlr.cache_key('Arsenal', 'football')
        _isolated[key] = {'url': 'https://r2.thesportsdb.com/a.png', 'source': 'thesportsdb',
                          'ts': int(time.time()) - 40 * 86400}
        _responder(monkeypatch, [('thesportsdb', RuntimeError('timeout'))])
        rec = tlr.resolve_media('Arsenal', 'football')
        assert rec and rec['url'] == 'https://r2.thesportsdb.com/a.png'


class TestTheSportsDB:
    def test_key_123_and_sport_filter(self, monkeypatch):
        calls = _responder(monkeypatch, [('searchteams.php', {'teams': [
            {'idTeam': '1', 'strSport': 'Basketball', 'strBadge': 'https://r2.thesportsdb.com/b.png'},
            {'idTeam': '2', 'strSport': 'Soccer', 'strBadge': 'https://r2.thesportsdb.com/s.png'},
        ]})])
        rec = tlr.resolve_media('Arsenal', 'football')
        assert rec['url'] == 'https://r2.thesportsdb.com/s.png'
        assert rec['source'] == 'thesportsdb'
        assert rec['attributionUrl'] == 'https://www.thesportsdb.com/team/2'
        assert '/json/123/' in calls[0] and '/json/3/' not in calls[0]

    def test_players_never_use_team_search(self, monkeypatch):
        calls = _responder(monkeypatch, [])
        tlr.resolve_media('Putincewa J.', 'tennis')
        assert not any('searchteams' in c for c in calls)

    def test_doubles_get_nothing(self):
        assert tlr.resolve_media('Nys H./Zielinski J.', 'tennis') is None


WD_SEARCH = {'query': {'search': [{'title': 'Q2429984'}]}}
WD_ENTITY = {'entities': {'Q2429984': {
    'labels': {'en': {'value': 'Yulia Putintseva'}, 'pl': {'value': 'Julija Putincewa'}},
    'claims': {'P18': [{'mainsnak': {'datavalue': {'value': 'Putintseva RG22.jpg'}}}]},
}}}
COMMONS = {'query': {'pages': {'1': {'imageinfo': [{
    'thumburl': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/06/P.jpg/256px-P.jpg?utm_source=x',
    'url': 'https://upload.wikimedia.org/wikipedia/commons/0/06/P.jpg',
    'descriptionurl': 'https://commons.wikimedia.org/wiki/File:Putintseva_RG22.jpg',
    'extmetadata': {
        'Artist': {'value': '<a href="https://www.flickr.com/people/x">si.robi</a>'},
        'LicenseShortName': {'value': 'CC BY-SA 2.0'},
    },
}]}}}}


class TestWikimedia:
    def test_photo_with_attribution_fields(self, monkeypatch):
        calls = _responder(monkeypatch, [('list=search', WD_SEARCH), ('wbgetentities', WD_ENTITY),
                                         ('commons.wikimedia.org', COMMONS)])
        rec = tlr.resolve_media('Putincewa J.', 'tennis')
        assert rec == {
            'url': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/06/P.jpg/256px-P.jpg',
            'source': 'wikimedia',
            'license': 'CC BY-SA 2.0',
            'author': 'si.robi',
            'attributionUrl': 'https://commons.wikimedia.org/wiki/File:Putintseva_RG22.jpg',
        }
        assert 'P106%3DQ10833314' in calls[0] or 'P106=Q10833314' in calls[0]

    def test_wrong_initial_gives_no_photo(self, monkeypatch):
        _responder(monkeypatch, [('list=search', WD_SEARCH), ('wbgetentities', WD_ENTITY),
                                 ('commons.wikimedia.org', COMMONS)])
        assert tlr.resolve_media('Putincewa A.', 'tennis') is None

    def test_a_retired_namesake_gets_no_photo(self, monkeypatch):
        old = json.loads(json.dumps(WD_ENTITY))
        old['entities']['Q2429984']['claims']['P569'] = [
            {'mainsnak': {'datavalue': {'value': {'time': '+1932-09-18T00:00:00Z'}}}}]
        _responder(monkeypatch, [('list=search', WD_SEARCH), ('wbgetentities', old),
                                 ('commons.wikimedia.org', COMMONS)])
        assert tlr.resolve_media('Putincewa J.', 'tennis') is None

    def test_non_free_file_is_refused(self, monkeypatch):
        nonfree = json.loads(json.dumps(COMMONS))
        nonfree['query']['pages']['1']['imageinfo'][0]['extmetadata']['LicenseShortName'] = {'value': 'Fair use'}
        _responder(monkeypatch, [('list=search', WD_SEARCH), ('wbgetentities', WD_ENTITY),
                                 ('commons.wikimedia.org', nonfree)])
        assert tlr.resolve_media('Putincewa J.', 'tennis') is None

    def test_photos_are_never_looked_up_at_request_time(self, _isolated):
        m = {'homeTeam': 'Putincewa J.', 'awayTeam': 'Swiatek I.', 'sport': 'tennis'}
        tlr.media_for_page([m])                           # _get_json would raise
        assert m['homeMedia'] is None and m['homeLogo'] == ''

    def test_cached_photo_is_served_with_attribution(self, _isolated):
        _isolated[tlr.cache_key('Putincewa J.', 'tennis')] = {
            'url': 'https://upload.wikimedia.org/x.jpg', 'source': 'wikimedia', 'license': 'CC BY 4.0',
            'author': 'A. Author', 'attributionUrl': 'https://commons.wikimedia.org/wiki/File:X.jpg',
            'ts': int(time.time())}
        m = {'homeTeam': 'J. Putincewa', 'awayTeam': '', 'sport': 'tennis'}
        tlr.media_for_page([m])
        assert m['homeLogo'] == 'https://upload.wikimedia.org/x.jpg'
        assert m['homeMedia']['author'] == 'A. Author' and m['homeMedia']['license'] == 'CC BY 4.0'


ESPN_TEAMS = {'sports': [{'leagues': [{'teams': [{'team': {
    'displayName': 'Vancouver Canucks', 'logos': [{'href': 'https://a.espncdn.com/i/teamlogos/nhl/500/van.png'}]}}]}]}]}


class TestEspn:
    def test_off_by_default(self, monkeypatch):
        calls = _responder(monkeypatch, [('site.api.espn.com', ESPN_TEAMS)])
        assert not tlr.espn_allowed()
        assert tlr._espn_team('Vancouver Canucks', 'hockey', 'NHL') is None
        assert not tlr.allowed_media_url('https://a.espncdn.com/i/teamlogos/nhl/500/van.png')
        tlr.resolve_media('Vancouver Canucks', 'hockey', league='NHL')
        assert not any('espn' in c for c in calls)

    def test_opt_in(self, monkeypatch):
        monkeypatch.setenv('MEDIA_ALLOW_ESPN', '1')
        _responder(monkeypatch, [('site.api.espn.com', ESPN_TEAMS)])
        rec = tlr._espn_team('Vancouver Canucks', 'hockey', 'NHL')
        assert rec['url'] == 'https://a.espncdn.com/i/teamlogos/nhl/500/van.png' and rec['source'] == 'espn'


class TestPageAndCacheFile:
    def test_at_most_three_live_lookups(self, monkeypatch):
        calls = _responder(monkeypatch, [('searchteams.php', {'teams': None})])
        page = [{'homeTeam': f'Club{i}x', 'awayTeam': f'Club{i}y', 'sport': 'football'} for i in range(5)]
        tlr.media_for_page(page)
        looked_up = {c.split('t=')[1] for c in calls}
        assert len(looked_up) == 3
        assert all('homeMedia' in m and 'awayMedia' in m for m in page)

    def test_request_time_lookups_do_not_write_the_file(self, monkeypatch, tmp_path):
        _responder(monkeypatch, [('searchteams.php', {'teams': [
            {'idTeam': '9', 'strSport': 'Soccer', 'strBadge': 'https://r2.thesportsdb.com/a.png'}]})])
        m = {'homeTeam': 'Arsenal', 'awayTeam': 'Chelsea', 'sport': 'football'}
        tlr.media_for_page([m])
        assert m['homeLogo'] == 'https://r2.thesportsdb.com/a.png'
        assert m['homeMedia']['source'] == 'thesportsdb'
        assert not (tmp_path / 'media_cache.json').exists()

    def test_save_and_reload(self, monkeypatch, tmp_path, _isolated):
        _isolated['football|logo|arsenal'] = {'url': 'https://r2.thesportsdb.com/a.png', 'source': 'thesportsdb',
                                              'ts': int(time.time())}
        tlr.save_media_cache()
        data = json.load(open(tmp_path / 'media_cache.json', encoding='utf-8'))
        assert data['football|logo|arsenal']['url'] == 'https://r2.thesportsdb.com/a.png'

    def test_legacy_cache_is_migrated(self, tmp_path, _isolated):
        (tmp_path / 'team_logos_cache.json').write_text(json.dumps({
            'yomiuri giants': {'url': 'https://r2.thesportsdb.com/y.png', 'ts': 1},
            'bad': {'url': 'https://img.sofascore.com/x.png', 'ts': 1}}), encoding='utf-8')
        assert tlr.migrate_legacy_cache() == 1
        rec = tlr.resolve_media('Yomiuri Giants', 'baseball', network='none')
        assert rec['url'] == 'https://r2.thesportsdb.com/y.png'

    def test_competitors_qualifying_first(self, tmp_path):
        (tmp_path / 'matches_2026-10-26_hockey_forebet.json').write_text(json.dumps({
            'sport': 'hockey', 'matches': [
                {'homeTeam': 'B Team', 'awayTeam': 'C Team', 'qualifies': False},
                {'homeTeam': 'Z Team', 'awayTeam': 'B Team', 'qualifies': True, 'league': 'NHL'}]}),
            encoding='utf-8')
        out = tlr.competitors(['2026-10-26'], tmp_path)
        assert [c[0] for c in out[:2]] == ['B Team', 'Z Team'] and out[0][3] is True
        assert [c[0] for c in out] == ['B Team', 'Z Team', 'C Team']
