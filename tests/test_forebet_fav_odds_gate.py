import forebet_pipeline as fp


def _row(fav, ho, ao, sport='football'):
    return {'sport': sport, 'favorite': fav, 'home_odds': ho, 'away_odds': ao,
            'scoring_prob': 60, 'scoring_sources': 3}


def _reasons(row):
    return fp.apply_qualification(row, 0, 2)['skip_reasons']


def test_fav_with_higher_odds_rejected():
    assert any(r.startswith('kurs_faworyta_') for r in _reasons(_row('home', 2.6, 1.5)))
    assert any(r.startswith('kurs_faworyta_') for r in _reasons(_row('away', 1.4, 2.9)))


def test_fav_with_lower_or_equal_odds_kept():
    assert not any(r.startswith('kurs_faworyta_') for r in _reasons(_row('home', 1.5, 2.6)))
    assert not any(r.startswith('kurs_faworyta_') for r in _reasons(_row('away', 1.9, 1.9)))
    assert not any(r.startswith('kurs_faworyta_') for r in _reasons(_row('home', None, 1.9)))


def test_margin_filter_off_by_default(monkeypatch):
    monkeypatch.delenv('FOREBET_MARGIN_FILTER', raising=False)
    # marża ~30% — dawniej odrzucona jako rynek egzotyczny
    assert not any(r.startswith('rynek_egzotyczny') for r in _reasons(_row('home', 1.3, 2.0)))
    monkeypatch.setenv('FOREBET_MARGIN_FILTER', '1')
    assert any(r.startswith('rynek_egzotyczny') for r in _reasons(_row('home', 1.3, 2.0)))
