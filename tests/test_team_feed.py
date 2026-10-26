"""Team history: name folding, index build, /api/teams shapes (design K6)."""
import functools
import gzip
import json
import os

import pytest

import team_feed
from tools import build_team_index as bti
from tools.team_names import fold, strip_country_tag


# ---------------------------------------------------------------------------
# Folding
# ---------------------------------------------------------------------------
def test_arsenal_and_arsenal_women_stay_apart():
    assert fold('Arsenal', 'football') == 'arsenal'
    assert fold('Arsenal W', 'football') == 'arsenal w'
    assert fold('Arsenal', 'football') != fold('Arsenal W', 'football')


@pytest.mark.parametrize('a,b', [
    ('Legia Warszawa II', 'Legia Warszawa'),
    ('Legia Warszawa U19', 'Legia Warszawa'),
    ('Legia Warszawa K', 'Legia Warszawa'),
    ('Real Madrid B', 'Real Madrid'),
    ('Al Hilal (SAU)', 'Al Hilal'),
])
def test_suffixes_name_a_different_team(a, b):
    assert fold(a, 'football') != fold(b, 'football')


@pytest.mark.parametrize('a,b', [
    ('Al-Hilal (SAU)', 'Al Hilal (Sau)'),
    ('Jagiellonia Białystok', 'Jagiellonia Bialystok'),
    ('Atlético  Madrid', 'atletico madrid'),
    ("Newell's Old Boys", 'Newell s Old Boys'),
])
def test_spelling_variants_fold_together(a, b):
    assert fold(a, 'football') == fold(b, 'football')


def test_women_markers_are_one_token():
    assert fold('Arsenal W', 'football') == fold('Arsenal K', 'football') == fold('Arsenal Women', 'football')
    assert fold('Arsenal K (ENG)', 'football') == 'arsenal w (eng)'
    assert fold('K', 'football') == 'k'


def test_player_alternative_reading():
    from tools.team_names import player_alternative
    assert fold('Hajek Miroslav', 'table_tennis') == 'miroslav h'
    assert player_alternative('Hajek Miroslav', 'table_tennis') == 'hajek m'
    assert player_alternative('Hajek M.', 'table_tennis') == ''
    assert player_alternative('Hajek Miroslav', 'football') == ''


def test_tennis_name_forms():
    assert fold('Djokovic N.', 'tennis') == 'djokovic n'
    assert fold('N. Djokovic', 'tennis') == 'djokovic n'
    assert fold('Novak Djokovic', 'tennis') == 'djokovic n'
    assert fold('F. A. Gomez', 'tennis') == fold('Gomez F. A.', 'tennis') == 'gomez f a'
    assert fold('N. Noha Akugue', 'tennis') == fold('Noha Akugue N.', 'tennis')
    # Team sports never reorder words.
    assert fold('N. Djokovic', 'football') == 'n djokovic'


def test_doubles_keep_both_players():
    assert fold('Djokovic N./Sinner J.', 'tennis') == 'djokovic n/sinner j'
    assert fold('N. Djokovic / J. Sinner', 'tennis') == 'djokovic n/sinner j'
    assert fold('Djokovic N./Sinner J.', 'tennis') != fold('Djokovic N.', 'tennis')


def test_strip_country_tag():
    assert strip_country_tag('legia warszawa (pol)') == 'legia warszawa'
    assert strip_country_tag('legia warszawa') == 'legia warszawa'


# ---------------------------------------------------------------------------
# Fixture index
# ---------------------------------------------------------------------------
STORE = [
    # date, sport, home, away, sh, sa, src
    ('2026-10-01', 'football', 'Legia Warszawa', 'Korona Kielce', 2, 0, 0),
    ('2026-10-05', 'football', 'Cracovia', 'Legia Warszawa', 1, 1, 0),
    ('2026-10-09', 'football', 'Legia Warszawa (POL)', 'Celje (SLO)', 1, 2, 0),
    ('2026-10-12', 'football', 'Legia Warszawa', 'Wisła Kraków', 3, 1, 0),
    ('2026-10-20', 'football', 'Lech Poznań', 'Legia Warszawa', 0, 2, 0),
    ('2026-10-20', 'football', 'Arsenal', 'Chelsea', 1, 0, 0),
    ('2026-10-21', 'football', 'Arsenal W', 'Chelsea W', 0, 3, 0),
    ('2026-10-22', 'tennis', 'Djokovic N.', 'Sinner J.', 2, 1, 0),
    ('2026-10-23', 'table_tennis', 'Hajek M.', 'Marek V.', 3, 1, 0),
]
SUPA = [
    # duplicate of a store game (reversed orientation) -> dropped
    ('2026-10-01', 'football', 'Korona Kielce', 'Legia Warszawa', 0, 2, 1),
    ('2026-09-28', 'football', 'Legia Warszawa', 'Piast Gliwice', 1, 1, 1),
]


@pytest.fixture()
def index_dir(tmp_path):
    settled = tmp_path / 'forebet_settled.json'
    settled.write_text(json.dumps({
        '2026-10-20|football|Lech Poznan|Legia': {'status': 'settled', 'score': '0-2', 'winner': 'away'},
    }), encoding='utf-8')
    games, stats = bti.merge(STORE, SUPA)
    assert stats == {'store': 9, 'supabase': 1, 'duplicate': 1}
    per, aliases = bti.build(games, str(settled))
    out = tmp_path / 'team_index'
    bti.write(per, aliases, str(out), str(tmp_path / 'team_aliases.json'))
    team_feed.clear_cache()
    yield tmp_path
    team_feed.clear_cache()


def _top(*picks):
    return lambda: {'days': [{'date': p['date'], 'picks': [p]} for p in picks]}


PICKS = _top(
    {'date': '2026-10-20', 'sport': 'football', 'match': 'Lech Poznan vs Legia', 'pick': 'Legia',
     'odds': 2.1, 'odds2': None, 'status': 'won', 'result': {'status': 'won'}},
    {'date': '2026-10-12', 'sport': 'football', 'match': 'Legia Warszawa vs Wisla Krakow',
     'pick': 'Legia Warszawa', 'odds': 1.5, 'odds2': None, 'status': 'lost', 'result': {'status': 'lost'}},
    {'date': '2026-10-13', 'sport': 'football', 'match': 'Legia Warszawa vs X',
     'status': 'withdrawn', 'withdrawKind': 'availability', 'selectionLocked': True,
     'result': {'status': 'withdrawn'}},
    {'date': '2026-10-20', 'sport': 'football', 'match': 'Arsenal vs Chelsea', 'pick': 'Arsenal',
     'odds': 1.4, 'status': 'won', 'result': {'status': 'won'}},
    {'date': '2026-10-20', 'sport': 'basketball', 'match': 'Legia vs Anwil', 'pick': 'Legia',
     'odds': 1.9, 'status': 'won', 'result': {'status': 'won'}},
)


def _get(d, name, sport='football', limit=None, top=PICKS):
    return team_feed.get_team(name, sport, limit, index_dir=str(d / 'team_index'),
                              aliases_path=str(d / 'team_aliases.json'), top_loader=top)


def test_index_files_and_aliases(index_dir):
    with gzip.open(index_dir / 'team_index' / 'football.json.gz', 'rt', encoding='utf-8') as fh:
        idx = json.load(fh)
    assert idx['teams']['legia warszawa'] == ['Legia Warszawa', 'Legia Warszawa (POL)']
    assert 'legia warszawa (pol)' not in idx['teams']
    al = json.loads((index_dir / 'team_aliases.json').read_text(encoding='utf-8'))['aliases']
    assert al['football|legia warszawa (pol)'] == 'legia warszawa'
    assert al['football|legia'] == 'legia warszawa'          # Forebet pair via score + other side
    assert 'football|celje (slo)' not in al                    # no untagged base -> kept as is


def test_unchanged_index_is_not_rewritten(index_dir):
    path = index_dir / 'team_index' / 'football.json.gz'
    before = path.read_bytes()
    games, _ = bti.merge(STORE, SUPA)
    per, aliases = bti.build(games, None)
    bti.write(per, aliases, str(index_dir / 'team_index'), str(index_dir / 'other_aliases.json'))
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# get_team shapes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('name,sport,limit,msg', [
    ('', 'football', None, 'name is required'),
    ('   ', 'football', None, 'name is required'),
    ('x' * 81, 'football', None, 'at most 80'),
    ('Legia', None, None, 'sport is required'),
    ('Legia', 'curling', None, 'sport must be one of'),
    ('Legia', 'football', '0', 'limit'),
    ('Legia', 'football', '51', 'limit'),
    ('Legia', 'football', 'ten', 'limit'),
    ('---', 'football', None, 'no letters'),
])
def test_bad_input_is_400(index_dir, name, sport, limit, msg):
    status, body = _get(index_dir, name, sport, limit)
    assert status == 400
    assert set(body) == {'error'} and msg in body['error']


def test_unknown_team_is_404_with_suggestions(index_dir):
    status, body = _get(index_dir, 'Legia Warszaw')
    assert status == 404
    assert body['error'] == 'team not found'
    assert body['suggestions'][0] == 'Legia Warszawa'
    assert len(body['suggestions']) <= 5
    status, body = _get(index_dir, 'Zzzz Unknown FC')
    assert status == 404 and body['suggestions'] == []


def test_200_shape_record_and_aliases(index_dir):
    status, body = _get(index_dir, 'Legia Warszawa')
    assert status == 200
    assert set(body) == {'team', 'sport', 'aliases', 'games', 'last', 'form', 'home', 'away',
                         'ourPicks', 'sources'}
    assert body['team'] == 'Legia Warszawa' and body['sport'] == 'football'
    assert body['aliases'] == ['Legia Warszawa (POL)']
    assert body['games'] == 6
    # Newest first; score from the team's side.
    assert body['last'][0] == {'date': '2026-10-20', 'opponent': 'Lech Poznań', 'venue': 'away',
                               'score': '2-0', 'result': 'W'}
    assert [g['date'] for g in body['last']] == ['2026-10-20', '2026-10-12', '2026-10-09',
                                                 '2026-10-05', '2026-10-01', '2026-09-28']
    assert body['form'] == 'WWLDW'
    # home: 10-01 W, 10-09 L, 10-12 W, 09-28 D ; away: 10-05 D, 10-20 W
    assert body['home'] == {'w': 2, 'd': 1, 'l': 1}
    assert body['away'] == {'w': 1, 'd': 1, 'l': 0}
    assert body['sources'] == ['result_store', 'supabase']


def test_limit_and_alias_lookup(index_dir):
    status, body = _get(index_dir, 'Legia Warszawa (POL)', limit='2')
    assert status == 200 and body['team'] == 'Legia Warszawa'
    assert len(body['last']) == 2 and body['games'] == 6 and len(body['form']) == 5
    status, body = _get(index_dir, 'legia', limit='1')            # Forebet spelling
    assert status == 200 and body['team'] == 'Legia Warszawa'


def test_arsenal_women_is_a_different_team(index_dir):
    _, men = _get(index_dir, 'Arsenal')
    _, women = _get(index_dir, 'Arsenal W')
    assert men['team'] == 'Arsenal' and women['team'] == 'Arsenal W'
    assert men['last'][0]['opponent'] == 'Chelsea' and women['last'][0]['opponent'] == 'Chelsea W'
    assert men['ourPicks']['n'] == 1 and women['ourPicks']['n'] == 0


def test_tennis_forms_resolve_to_one_player(index_dir):
    for name in ('Djokovic N.', 'N. Djokovic', 'Novak Djokovic'):
        status, body = _get(index_dir, name, 'tennis')
        assert status == 200 and body['team'] == 'Djokovic N.'
        assert body['last'][0]['opponent'] == 'Sinner J.' and body['last'][0]['result'] == 'W'


def test_full_name_surname_first_falls_back(index_dir):
    status, body = _get(index_dir, 'Hajek Miroslav', 'table_tennis')
    assert status == 200 and body['team'] == 'Hajek M.' and body['form'] == 'W'


def test_our_picks(index_dir):
    _, body = _get(index_dir, 'Legia Warszawa')
    op = body['ourPicks']
    # Forebet "Legia" (alias) and "Legia Warszawa" match; basketball Legia does not.
    assert op['n'] == 2 and op['won'] == 1
    assert op['roi'] == pytest.approx(5.0)         # flat 1u: (2.1 - 2) / 2
    assert [p['status'] for p in op['picks']] == ['won', 'withdrawn', 'lost']
    locked = op['picks'][1]
    assert locked['pick'] is None and locked['odds'] is None


def test_our_picks_failure_keeps_history(index_dir):
    def boom():
        raise RuntimeError('feed down')
    status, body = _get(index_dir, 'Arsenal', top=boom)
    assert status == 200 and body['ourPicks'] == {'n': 0, 'won': 0, 'roi': None, 'picks': []}


def test_cache_serves_within_ttl(index_dir):
    calls = []

    def top():
        calls.append(1)
        return {'days': []}
    kw = dict(index_dir=str(index_dir / 'team_index'), aliases_path=str(index_dir / 'team_aliases.json'),
              top_loader=top)
    team_feed.get_team('Arsenal', 'football', None, now=1000.0, **kw)
    team_feed.get_team('Arsenal', 'football', None, now=1000.0 + 599, **kw)
    assert len(calls) == 1
    team_feed.get_team('Arsenal', 'football', None, now=1000.0 + 601, **kw)
    assert len(calls) == 2


def test_missing_index_is_404(tmp_path):
    team_feed.clear_cache()
    status, body = team_feed.get_team('Arsenal', 'football', index_dir=str(tmp_path),
                                      aliases_path=str(tmp_path / 'none.json'), top_loader=_top())
    assert status == 404 and body == {'error': 'team not found', 'suggestions': []}


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
def test_route_status_and_cache_header(client, index_dir, monkeypatch):
    real = team_feed.get_team
    monkeypatch.setattr(team_feed, 'get_team', functools.partial(
        real, index_dir=str(index_dir / 'team_index'),
        aliases_path=str(index_dir / 'team_aliases.json'), top_loader=PICKS))
    r = client.get('/api/teams/Legia%20Warszawa?sport=football&limit=3')
    assert r.status_code == 200
    assert r.headers['Cache-Control'] == 'public, max-age=600'
    assert r.get_json()['team'] == 'Legia Warszawa' and len(r.get_json()['last']) == 3
    r = client.get('/api/teams/Legia?sport=curling')
    assert r.status_code == 400 and 'error' in r.get_json()
    r = client.get('/api/teams/?sport=football')
    assert r.status_code == 400 and r.get_json() == {'error': 'name is required'}
    r = client.get('/api/teams/Nobody%20FC?sport=football')
    assert r.status_code == 404 and r.get_json()['error'] == 'team not found'
    r = client.get('/api/teams/Djokovic%20N./Sinner%20J.?sport=tennis')
    assert r.status_code == 404                     # doubles name reaches the handler intact
