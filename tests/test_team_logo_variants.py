"""Badge lookups have to try more than the literal Polish name.

Measured over 2 280 looked-up names, only 78 (3.4%) resolved. The misses were
concentrated: tennis 100%, football 99.8%, hockey 100%. Three causes, all fixable
without a new data source — translated country names, women's/youth suffixes, and
glued punctuation. A live probe recovered 15 of 16 previously-missing names.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import team_logo_resolver as tlr


class TestNameVariants:
    def test_the_original_is_tried_first(self):
        assert tlr._name_variants('Arsenal')[0] == 'Arsenal'

    def test_a_polish_country_gets_its_english_name(self):
        assert 'Mexico' in tlr._name_variants('Meksyk')

    def test_diacritics_are_handled(self):
        assert 'Italy' in tlr._name_variants('Włochy')

    def test_glued_punctuation_is_spaced(self):
        assert 'St. Louis Cardinals' in tlr._name_variants('St.Louis Cardinals')

    def test_a_womens_side_falls_back_to_the_base_side(self):
        variants = tlr._name_variants('Atlanta Dream K')
        assert 'Atlanta Dream' in variants

    def test_a_youth_womens_side_reaches_the_country(self):
        """'Polska U18 K' has to end up at 'Poland'."""
        assert 'Poland' in tlr._name_variants('Polska U18 K')

    def test_no_duplicates(self):
        variants = tlr._name_variants('Panama')
        assert len(variants) == len({v.lower() for v in variants})

    def test_a_short_name_is_not_eaten_by_suffix_stripping(self):
        """Stripping must not turn a real name into a fragment."""
        assert tlr._name_variants('AIK')[0] == 'AIK'
        assert 'ai' not in [v.lower() for v in tlr._name_variants('AIK')]


class TestSideSuffix:
    @pytest.mark.parametrize('name,expected', [
        ('atlanta dream k', 'atlanta dream'),
        ('polska u18 k', 'polska'),
        ('meksyk k', 'meksyk'),
        ('shirak 2', 'shirak'),
    ])
    def test_variants_are_reduced_to_the_base(self, name, expected):
        assert tlr._strip_side_suffix(name) == expected

    def test_a_plain_name_is_left_alone(self):
        assert tlr._strip_side_suffix('arsenal') is None


class TestIndividualSports:
    """Competitors are people; the badge index only holds teams."""

    @pytest.mark.parametrize('sport', ['tennis', 'table_tennis', 'Table-Tennis'])
    def test_no_lookup_is_attempted(self, sport, monkeypatch):
        def _fail(*a, **k):
            raise AssertionError('a request was made for an individual sport')

        monkeypatch.setattr(tlr, '_query_badge', _fail)
        assert tlr.get_logo_url('Putincewa J.', sport) is None

    def test_team_sports_still_resolve(self, monkeypatch):
        monkeypatch.setattr(tlr, '_query_badge', lambda term: 'https://badge.test/a.png')
        monkeypatch.setattr(tlr, '_load_file_cache', lambda: {})
        monkeypatch.setattr(tlr, '_save_file_cache', lambda: None)
        assert tlr.get_logo_url('Arsenal', 'football') == 'https://badge.test/a.png'


class TestVariantOrderIsTriedUntilAHit:
    def test_the_first_matching_variant_wins(self, monkeypatch):
        tried = []

        def _query(term):
            tried.append(term)
            return 'https://badge.test/mx.png' if term == 'Mexico' else None

        monkeypatch.setattr(tlr, '_query_badge', _query)
        monkeypatch.setattr(tlr, '_load_file_cache', lambda: {})
        monkeypatch.setattr(tlr, '_save_file_cache', lambda: None)

        assert tlr.get_logo_url('Meksyk', 'football') == 'https://badge.test/mx.png'
        assert tried == ['Meksyk', 'Mexico'], 'the literal name is tried first'

    def test_lookup_stops_once_a_badge_is_found(self, monkeypatch):
        tried = []

        def _query(term):
            tried.append(term)
            return 'https://badge.test/first.png'

        monkeypatch.setattr(tlr, '_query_badge', _query)
        monkeypatch.setattr(tlr, '_load_file_cache', lambda: {})
        monkeypatch.setattr(tlr, '_save_file_cache', lambda: None)

        tlr.get_logo_url('Polska U18 K', 'football')
        assert len(tried) == 1, 'no extra requests after a hit'
