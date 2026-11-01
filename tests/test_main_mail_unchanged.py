"""The main mails keep their previous content: no Fan Favourites section.

Commit 40ef1afa put a "🗳 Fan Favourites" table above the match cards of every
main mail (Forebet, Sports Scraper, Baseball, Table Tennis). The user wants the
SofaScore Fan Favourites in a separate mail and the existing mails unchanged, so
a row with a strong Fan Vote renders as its usual card and nothing more. The
card's own "🗳️ SofaScore Fan Vote" block is older than that section and stays.
"""

import email_notifier
from email_notifier import create_html_email

CARD_FAN_VOTE = '🗳️ SofaScore Fan Vote'


def fan_vote_row():
    return {
        'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'football',
        'match_url': 'https://example.test/match/1',
        'match_date': '2026-08-01', 'match_time': '18:00',
        'home_odds': 2.2, 'draw_odds': 3.40, 'away_odds': 3.20,
        'home_form_overall': list('WWLDWWLWDW'),
        'home_form_home': list('WWWLW'),
        'away_form_overall': list('LLDWLLDWLL'),
        'away_form_away': list('LLDWL'),
        'sofascore': {'home': 78, 'away': 22, 'votes': 178},
        'qualifies': True, 'focus_team': 'home',
        'scoring_pick': '1', 'scoring_prob': 58.0,
    }


def test_fan_vote_row_renders_only_its_card():
    html = create_html_email([fan_vote_row()], '2026-08-01')
    assert 'Znaleziono <strong>1</strong>' in html
    assert 'Alpha' in html and 'Beta' in html
    assert f'{CARD_FAN_VOTE} (178 głosów)' in html
    assert 'Fan Favourites' not in html
    # Every 🗳 left in the mail belongs to the card's Fan Vote block.
    assert '\U0001F5F3' not in html.replace(CARD_FAN_VOTE, '')


def test_section_helpers_are_gone():
    for name in ('select_fan_favourites', 'fan_favourites_thresholds',
                 '_render_fan_favourites_section'):
        assert not hasattr(email_notifier, name), name
