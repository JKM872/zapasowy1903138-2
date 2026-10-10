import livesport_bulk_odds as lb

ODDS = "SA÷1¬~AA÷ev1¬AY÷1¬ODA÷165¬XA÷1.42¬YA÷1.4¬MG÷0¬XB÷4.5¬YB÷4¬MG÷0¬XC÷7.1¬YC÷7¬MG÷0¬~AA÷ev2¬ODA÷165¬XA÷2¬~"
LIST = "SA÷1¬~ZA÷ANGLIA¬~AA÷ev1¬AD÷1791631800¬AE÷Arsenal¬AF÷Leeds¬~AA÷ev2¬AD÷1791631800¬AE÷Foo¬AF÷Bar¬~"


def test_parse_and_lookup(monkeypatch):
    lb._CACHE.clear()
    lb._LOOKUP_CACHE.clear()
    monkeypatch.setattr(lb, '_get', lambda feed: ODDS if feed.startswith('fo_') else LIST)
    rows = lb.day_index('football', 0)
    assert len(rows) == 1  # ev2 bez kursu na gościa — pominięty
    assert rows[0]['prices'] == {'home': 1.42, 'draw': 4.5, 'away': 7.1}
    o = lb.lookup('Leeds United', 'Arsenal', 'football', None)
    assert (o['home_odds'], o['away_odds']) == (7.1, 1.42)  # względem naszych stron
    assert lb.lookup('Nobody', 'Else', 'football', None) is None
