"""A row without a `sport` field must not silently become football.

The AiScore table-tennis result files carry no `sport` key at all — 0 of 126 rows
in one file, 0 of 135 in another — and `normalise_row` defaulted to football. Two
things followed: 64 table-tennis fixtures were filed under football, and table
tennis ended up with no rows of its own in the settled export, which is why the
sport making up 62% of the mail could not be measured at all.

The URL always says what the sport is, so it is used when the field is absent.
"""

import pytest

from export_settled import infer_sport, normalise_row

LIVESPORT = 'https://www.livesport.com/pl/mecz/{}/alpha-beta/?mid=x'
AISCORE = 'https://www.aiscore.com/{}/match-alpha-beta/abc123'


class TestDeclaredSportWins:
    def test_the_field_is_trusted_when_present(self):
        assert infer_sport({'sport': 'tennis'}) == 'tennis'

    def test_the_field_beats_a_contradicting_url(self):
        assert infer_sport({'sport': 'tennis',
                            'matchUrl': AISCORE.format('table-tennis')}) == 'tennis'

    def test_the_field_is_lowercased_and_trimmed(self):
        assert infer_sport({'sport': '  Table_Tennis '}) == 'table_tennis'

    def test_an_empty_field_falls_through_to_the_url(self):
        assert infer_sport({'sport': '',
                            'matchUrl': AISCORE.format('table-tennis')}) == 'table_tennis'


class TestUrlInference:
    @pytest.mark.parametrize('slug,expected', [
        ('table-tennis', 'table_tennis'),
        ('tenis', 'tennis'),
        ('pilka-nozna', 'football'),
        ('pilka-reczna', 'handball'),
        ('koszykowka', 'basketball'),
        ('siatkowka', 'volleyball'),
        ('hokej', 'hockey'),
        ('baseball', 'baseball'),
    ])
    def test_livesport_slugs(self, slug, expected):
        assert infer_sport({'matchUrl': LIVESPORT.format(slug)}) == expected

    def test_aiscore_table_tennis(self):
        assert infer_sport({'matchUrl': AISCORE.format('table-tennis')}) == \
            'table_tennis'

    def test_table_tennis_is_not_read_as_tennis(self):
        """'tennis' is a substring of 'table-tennis'; order matters."""
        for url in (AISCORE.format('table-tennis'),
                    LIVESPORT.format('table-tennis'),
                    LIVESPORT.format('tenis-stolowy')):
            assert infer_sport({'matchUrl': url}) == 'table_tennis'

    def test_handball_is_not_read_as_football(self):
        assert infer_sport({'matchUrl': LIVESPORT.format('pilka-reczna')}) == \
            'handball'

    def test_snake_case_url_is_handled(self):
        assert infer_sport({'match_url': AISCORE.format('table_tennis')}) == \
            'table_tennis'

    def test_uppercase_url_is_handled(self):
        assert infer_sport(
            {'matchUrl': AISCORE.format('table-tennis').upper()}) == 'table_tennis'


class TestFallback:
    def test_no_field_and_no_url_uses_the_default(self):
        assert infer_sport({}) == 'football'

    def test_an_unrecognised_url_uses_the_default(self):
        assert infer_sport({'matchUrl': 'https://example.test/x/y'}) == 'football'

    def test_the_default_is_overridable(self):
        assert infer_sport({}, default='unknown') == 'unknown'


class TestNormaliseRowUsesIt:
    def test_a_table_tennis_row_is_labelled_correctly(self):
        row = normalise_row({
            'homeTeam': 'Damian Bucko', 'awayTeam': 'Guzy Karol',
            'matchUrl': AISCORE.format('table-tennis'),
            'odds': {'home': 1.8, 'away': 2.0},
        })
        assert row['sport'] == 'table_tennis'

    def test_a_football_row_is_still_football(self):
        row = normalise_row({
            'homeTeam': 'Legia', 'awayTeam': 'Lech', 'sport': 'football',
            'matchUrl': LIVESPORT.format('pilka-nozna'),
        })
        assert row['sport'] == 'football'

    def test_the_real_mislabelled_url_is_fixed(self):
        """Taken verbatim from a row that had been filed as football."""
        row = normalise_row({
            'homeTeam': 'Daniel Hyza', 'awayTeam': 'Marek Kulisek',
            'matchUrl': ('https://www.aiscore.com/table-tennis/'
                         'match-daniel-hyza-marek-kulisek/edq08swvgglaekx'),
        })
        assert row['sport'] == 'table_tennis'
