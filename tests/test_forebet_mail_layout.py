"""Forebet mail layout: home/away sections, break-even line, Grade C label.

Layout only — every match passed in must come out as a card, in the same
order inside its section.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email_notifier import (_CARDS_END, _CARDS_START, break_even_text,  # noqa: E402
                            create_html_email, grade_c_label)


def m(home, away, pick, grade='B', sport='football', time='18:00', odds=(1.6, 3.4, 5.0)):
    return {'home_team': home, 'away_team': away, 'sport': sport, 'match_time': time,
            'scoring_pick': pick, 'prediction_grade': grade,
            'home_odds': odds[0], 'draw_odds': odds[1], 'away_odds': odds[2],
            'home_form_overall': ['W', 'W', 'L'], 'home_form_home': ['W', 'D'],
            'away_form_overall': ['L', 'D'], 'away_form_away': ['L', 'L']}


MATCHES = [
    m('H1', 'A1', '2', 'C', time='12:00'),
    m('H2', 'A2', '1', 'B', time='13:00'),
    m('H3', 'A3', 'X', 'C', time='14:00'),
    m('H4', 'A4', '1', 'C', time='15:00'),
    m('H5', 'A5', '2', 'B', time='16:00'),
]


def _cards(html):
    body = html[html.find(_CARDS_START):html.find(_CARDS_END)]
    return re.findall(r'(H\d) <span style="color: #999; font-size: 16px;">vs</span> (A\d)', body)


def test_break_even_for_160_is_625():
    assert '62.5%' in break_even_text(1.60)
    assert break_even_text(None) == '' and break_even_text(1.0) == ''
    html = create_html_email([m('H', 'A', '1', odds=(1.6, 3.4, 5.0))], '2026-11-12', forebet_layout=True)
    assert 'kurs 1.60 → potrzeba 62.5%' in html


def test_sections_hold_exactly_the_same_picks_in_the_same_order():
    before = create_html_email(MATCHES, '2026-11-12')
    after = create_html_email(MATCHES, '2026-11-12', forebet_layout=True)
    assert sorted(_cards(after)) == sorted(_cards(before))
    assert len(_cards(after)) == len(MATCHES)
    assert _cards(after) == [('H2', 'A2'), ('H4', 'A4'), ('H1', 'A1'), ('H5', 'A5'), ('H3', 'A3')]
    heads = re.findall(r'class="side-section"[^>]*>([^<]*)<', after)
    assert heads == ['🏠 Typy na gospodarzy (2)', '✈️ Typy na gości (2)', '🤝 Typy na remis (1)']


def test_grade_c_badge_on_every_c_pick_and_none_removed():
    html = create_html_email(MATCHES, '2026-11-12', forebet_layout=True)
    assert html.count('class="grade-c-badge"') == 3
    assert html.count('Grade C – historycznie stratny') == 3
    assert len(_cards(html)) == len(MATCHES)


def test_grade_c_label_neutral_where_c_was_not_losing():
    assert grade_c_label('football') == 'Grade C – historycznie stratny'
    assert grade_c_label('hockey') == 'Grade C – niższa pewność'


def test_other_mails_unchanged():
    html = create_html_email(MATCHES, '2026-11-12')
    assert 'grade-c-badge' not in html and 'side-section' not in html and 'Próg opłacalności' not in html


def test_venue_form_shown_and_missing_data_renders_cleanly():
    html = create_html_email([m('H', 'A', '1')], '2026-11-12', forebet_layout=True)
    assert '🏠 U siebie:' in html and '✈️ Na wyjeździe:' in html
    bare = {'home_team': 'H', 'away_team': 'A', 'sport': 'football', 'scoring_pick': '1'}
    html = create_html_email([bare], '2026-11-12', forebet_layout=True)
    assert '🏠 U siebie:' not in html and 'Próg opłacalności' not in html and 'None' not in _cards_body(html)


def _cards_body(html):
    return html[html.find(_CARDS_START):html.find(_CARDS_END)]
