"""E173 s0 C2 (D3): the closed list of type words, checked against the profile registry the SDK ships. A source profile
added to the registry fails here until someone places it under a word (or, named by name only, in NO_WORD)."""
import json
from pathlib import Path

import pytest

from ophiolite import exchange

REGISTRY = Path(exchange.__file__).resolve().parent / 'contracts/registry.json'


def sources():
    return {p['id'] for p in json.loads(REGISTRY.read_text())['profiles'] if p['kind'] == 'source'}


def test_every_source_profile_has_exactly_one_word_or_none_by_name():
    """Mutation: a registry source profile without a word (or a profile under two words) -> listed here."""
    placed = [p for profiles in exchange.TYPE_WORDS.values() for p in profiles]
    assert sorted(p for p in set(placed) if placed.count(p) > 1) == []
    assert sorted(sources() - set(placed) - set(exchange.NO_WORD)) == []
    assert exchange.NO_WORD == ('native-external/1',)


def test_no_profile_is_both_worded_and_unworded_and_every_listed_profile_is_registered():
    placed = {p for profiles in exchange.TYPE_WORDS.values() for p in profiles}
    assert placed & set(exchange.NO_WORD) == set()
    assert sorted((placed | set(exchange.NO_WORD)) - sources()) == []


def test_the_words_name_the_profiles_they_should():
    """Mutation: the "horizon" and "point set" profiles swapped -> the literals differ."""
    words = exchange.TYPE_WORDS
    assert set(words['horizon']) == {'esri-ascii-grid/1', 'zmap-plus-grid/1', 'cps3-ascii-grid/1', 'irap-ascii-grid/1',
                                     'opendtect-horizon-ascii/1', 'petrel-horizon-ilxl/1'}
    assert 'points-csv/1' in words['point set'] and 'points-csv/1' not in words['horizon']  # the OpendTect connector's horizon (Q3, open)
    assert 'las2/1' in words['well log']
    assert exchange.type_word('esri-ascii-grid/1') == 'horizon' and exchange.type_word('points-csv/1') == 'point set'
    assert exchange.type_word('native-external/1') is None and exchange.type_word(None) is None


@pytest.mark.parametrize('word', ['horizons', 'Horizon', 'esri-ascii-grid/1', '', None])
def test_an_unknown_word_is_refused_by_the_lookup(word):
    with pytest.raises(exchange.NotValid) as caught: exchange.type_profiles(word)
    assert caught.value.outcome == 'not-valid' and 'is not a type this version knows' in str(caught.value)
    assert exchange.type_profiles('horizon') == exchange.TYPE_WORDS['horizon']
