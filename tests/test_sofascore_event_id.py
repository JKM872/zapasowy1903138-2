import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_server import _sofa_event_id, normalize_match  # noqa: E402


def test_parses_trailing_id_from_nested_url():
    m = {'sofascore': {'url': 'https://www.sofascore.com/football/match/17031405'}}
    assert _sofa_event_id(m) == 17031405


def test_parses_slug_fragment_and_trailing_slash_and_query():
    assert _sofa_event_id({'sofascore_url': 'https://www.sofascore.com/a-b/xYz#id:12345'}) == 12345
    assert _sofa_event_id({'sofascore': {'url': 'https://www.sofascore.com/tennis/match/42/'}}) == 42
    assert _sofa_event_id({'sofascore': {'url': 'https://www.sofascore.com/football/match/77?tab=1'}}) == 77


def test_none_when_absent_or_garbage():
    assert _sofa_event_id({}) is None
    assert _sofa_event_id({'sofascore': None}) is None
    assert _sofa_event_id({'sofascore': {'url': ''}}) is None
    assert _sofa_event_id({'sofascore': {'url': 'https://example.com/match/123'}}) is None
    assert _sofa_event_id({'sofascore': 55}) is None


def test_normalize_match_exposes_field():
    out = normalize_match({'homeTeam': 'A', 'awayTeam': 'B',
                           'sofascore': {'url': 'https://www.sofascore.com/football/match/16439225'}})
    assert out['sofascoreEventId'] == 16439225
    assert normalize_match({'homeTeam': 'A', 'awayTeam': 'B'})['sofascoreEventId'] is None
