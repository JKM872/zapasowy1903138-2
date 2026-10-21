"""Wspólny schemat formy (form_schema) we wszystkich workflow."""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import form_schema as fs  # noqa: E402
import recency  # noqa: E402

TODAY = date(2026, 10, 21)


def _dated(spec):
    """spec: [(date, result, event)]"""
    return [{'date': d, 'result': r, 'event': e} for d, r, e in spec]


def _row():
    home = _dated([('18.10.26', 'W', 'Ekstraklasa'), ('14.10.26', 'L', 'Puchar Polski'),
                   ('10.10.26', 'W', 'Club Friendly'), ('04.10.26', 'D', 'Ekstraklasa'),
                   ('27.09.26', 'W', 'Liga Konferencji (Conference League)')])
    away = _dated([('19.10.26', 'L', 'Bundesliga'), ('12.10.26', 'W', 'Towarzyskie klubowe'),
                   ('05.10.26', 'L', 'Bundesliga')])
    hh = _dated([('18.10.26', 'W', 'Ekstraklasa'), ('10.10.26', 'W', 'Club Friendly')])
    aa = _dated([('19.10.26', 'L', 'Bundesliga')])
    return {
        'home_team': 'Legia', 'away_team': 'Mainz', 'league': 'Ekstraklasa',
        'favorite': 'home',
        'home_form': [e['result'] for e in home], 'away_form': [e['result'] for e in away],
        'home_form_home': [e['result'] for e in hh], 'away_form_away': [e['result'] for e in aa],
        'home_form_dated': home, 'away_form_dated': away,
        'home_form_home_dated': hh, 'away_form_away_dated': aa,
    }


def test_cup_detection():
    for lbl in ('Puchar Polski', 'DFB Pokal', 'Coupe de France', 'Copa del Rey', 'Coppa Italia',
                'KNVB Beker', 'Türkiye Kupası'.replace('ı', 'i'), 'Liga Mistrzów (Champions League)',
                'Europa League', 'Conference League', 'Copa Libertadores',
                'Copa Sudamericana', 'AFC Champions League', 'CAF Confederation Cup', 'FA Cup'):
        assert fs.is_cup(lbl), lbl
    for lbl in ('Ekstraklasa', 'Premier League', 'Club Friendly', '', None, 'Occupy League'):
        assert not fs.is_cup(lbl), lbl
    assert 'cup' in fs.CUP_KEYWORDS and 'puchar' in fs.CUP_KEYWORDS


def test_friendlies_excluded_everywhere_and_cup_form():
    r = _row()
    recency.apply_season(r, TODAY)
    assert r['home_form_nf'] == ['W', 'L', 'D', 'W']
    assert r['away_form_nf'] == ['L', 'L']
    assert r['home_form_home_nf'] == ['W']
    assert r['away_form_away_nf'] == ['L']
    assert r['home_season_form'] == ['W', 'L', 'D', 'W']
    assert r['away_season_form'] == ['L', 'L']
    assert r['season_home_form'] == ['W']
    assert r['home_friendlies_excluded'] == 1 and r['away_friendlies_excluded'] == 1
    assert r['home_home_friendlies_excluded'] == 1
    assert r['friendlies_excluded'] == 3
    assert r['home_cup_form'] == ['L', 'W']
    assert r['home_cup_competitions'] == ['Puchar Polski', 'Liga Konferencji (Conference League)']
    assert r['away_cup_form'] == []
    assert 'Club Friendly' not in r['home_form_competitions']
    assert r['home_form_competitions'][0] == 'Ekstraklasa'
    # Surowe pola formy (scoring/progi) bez zmian.
    assert r['home_form'] == ['W', 'L', 'W', 'D', 'W']
    assert r['home_form_dated'][2]['event'] == 'Club Friendly'


def test_national_tagging_and_friendly_skip():
    r = {'home_team': 'Poland', 'away_team': 'Netherlands',
         'league': 'ŚWIAT: Mistrzostwa Świata - Kwalifikacje'}
    fs.tag_category(r)
    assert r['category'] == 'reprezentacje' and r['national_friendly'] is False
    f = {'home_team': 'Polska', 'away_team': 'Litwa', 'league': 'ŚWIAT: Mecze towarzyskie'}
    fs.tag_category(f)
    assert f['category'] == 'reprezentacje' and f['national_friendly'] is True
    nl = {'home_team': 'Spain', 'away_team': 'Portugal', 'league': 'EUROPA: Liga Narodów'}
    fs.tag_category(nl)
    assert nl['category'] == 'reprezentacje'
    club = {'home_team': 'Legia', 'away_team': 'Chelsea', 'league': 'EUROPA: Liga Konferencji'}
    fs.tag_category(club)
    assert 'category' not in club and club['national_friendly'] is False
    cwc = {'home_team': 'Real Madrid', 'away_team': 'Al Hilal', 'league': 'ŚWIAT: Club World Cup'}
    fs.tag_category(cwc)
    assert 'category' not in cwc


def _email_match(**kw):
    r = _row()
    recency.apply_season(r, TODAY)
    r.update({'match_time': '18:00', 'match_url': 'https://x', 'sport': 'football',
              'home_odds': 1.8, 'away_odds': 4.0})
    r.update(kw)
    return r


def test_email_renders_form_block_and_national_section():
    import email_notifier as en
    club = _email_match()
    nat = _email_match(home_team='Poland', away_team='Netherlands',
                       league='ŚWIAT: Mistrzostwa Świata', match_time='20:45')
    fr = _email_match(home_team='Polska', away_team='Litwa',
                      league='ŚWIAT: Mecze towarzyskie', match_time='17:00')
    for m in (nat, fr):
        fs.tag_category(m)
    html = en.create_html_email([nat, fr, club], '2026-10-21')
    assert 'Ogólna WLDW / LL' in html
    assert 'U siebie W' in html and 'Na wyjeździe L' in html
    assert 'Puchary Legia: LW (Puchar Polski, Liga Konferencji (Conference League))' in html
    assert '>Sezon<' in html and '(4 / 2 m.)' in html
    assert '🏳️ Reprezentacje' in html
    assert html.index('Legia') < html.index('🏳️ Reprezentacje') < html.index('Netherlands')
    assert 'Litwa' not in html


def test_form_lines_from_csv_strings_and_json():
    b = fs.block_from_row({'home_form': "['W', 'D']", 'away_form': 'LLW',
                           'home_cup_form': '[]', 'home_season_form': None})
    lines = fs.form_lines(b)
    assert lines[1] == '  Ogólna WD / LLW'
    assert not any('Puchary' in ln or ln == 'Sezon' for ln in lines)
    j = fs.block_from_json({'home': list('WWWWW'), 'homeClean': list('WWWW'), 'away': list('LL'),
                            'homeCup': ['W'], 'homeCupCompetitions': ['FA Cup'],
                            'homeSeason': ['W'], 'awaySeason': [], 'homeSeasonMatches': 1,
                            'awaySeasonMatches': 0})
    txt = '\n'.join(fs.form_lines(j, 'A', 'B'))
    assert 'Ogólna WWWW / LL' in txt and 'Puchary A: W (FA Cup)' in txt
    assert '(1 / 0 m.)' in txt


def test_sports_row_has_season_fields():
    import livesport_h2h_scraper as ls
    r = _row()
    adv = {'home_form_overall_dated': r['home_form_dated'],
           'away_form_overall_dated': r['away_form_dated'],
           'home_form_home_dated': r['home_form_home_dated'],
           'away_form_away_dated': r['away_form_away_dated']}
    out = {k: r[k] for k in ('home_team', 'away_team', 'home_form', 'away_form',
                             'home_form_home', 'away_form_away')}
    ls._apply_season_flags(out, adv, False)
    for k in ('home_season_form', 'away_season_form', 'season_home_form', 'season_away_form',
              'home_season_match_count', 'away_season_match_count', 'early_season',
              'home_form_nf', 'home_cup_form', 'home_form_competitions', 'friendlies_excluded'):
        assert k in out, k
    assert 'favorite' not in out


def test_top_picks_skips_national_friendly_and_carries_block():
    from tools import top_picks as tp
    m = {'homeTeam': 'Poland', 'awayTeam': 'Malta', 'time': '20:45', 'league': 'x',
         'predictionGrade': 'A', 'qualifies': True,
         'forebet': {'homeProb': 70, 'awayProb': 10}, 'scoring': {'prob': 70},
         'odds': {'home': 1.6, 'away': 6.0},
         'form': {'home': list('WWWWD'), 'away': list('LLLDW'),
                  'homeAtHome': list('WWWDW'), 'awayAtAway': list('LLDLL')},
         'h2h': {'total': 0}, 'sofascore': {'found': False}, 'category': 'reprezentacje'}
    r = tp.evaluate(dict(m), 'football')
    if r is not None:
        assert r['category'] == 'reprezentacje' and 'Ogólna WWWWD / LLLDW' in r['formBlock']
    assert tp.evaluate(dict(m, nationalFriendly=True), 'football') is None


def test_ai_candidate_gets_form_block(tmp_path, monkeypatch):
    import json
    from tools import ai_analyst as aa
    (tmp_path / 'results').mkdir()
    (tmp_path / 'results' / 'matches_2026-10-21_football_forebet.json').write_text(json.dumps(
        {'matches': [{'homeTeam': 'A', 'awayTeam': 'B', 'category': 'reprezentacje',
                      'form': {'home': ['W'], 'away': ['L'], 'homeCup': ['W'],
                               'homeCupCompetitions': ['FA Cup']}}]}), encoding='utf-8')
    monkeypatch.setattr(aa, 'ROOT', str(tmp_path))
    c = aa.build_candidates('2026-10-21', [{'sport': 'football', 'match': 'A vs B',
                                            'pick': 'A'}], [])
    assert c[0]['data']['category'] == 'reprezentacje'
    assert any('Puchary A: W (FA Cup)' in ln for ln in c[0]['data']['formBlock'])
