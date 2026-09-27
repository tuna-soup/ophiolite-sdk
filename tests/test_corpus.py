"""E14 corpus rules: group keys, split/1 assignments against literal expectations and the written
specification, and fraction validation."""
import hashlib
import pytest
from ophiolite.corpus import assign, group_key, _fractions
from ophiolite.errors import Refused


def test_group_keys_are_namespaced_and_normalized():
    assert group_key('  well  7 ') == 'las-well:WELL 7' and group_key('Well 7') == 'las-well:WELL 7'
    assert group_key(None) is None and group_key('   ') is None
    assert group_key('ignored', 'north   block') == 'group:north block'
    with pytest.raises(Refused): group_key('x', '  ')


def test_split_assignments_match_literals_and_the_specification():
    literal = {('las-well:SYNTHETIC', 0): 'train', ('las-well:SYNTHETIC', 42): 'validation', ('las-well:WELL-7', 42): 'validation',
               ('group:north block', 42): 'train', ('las-well:A', 7): 'train'}
    for (key, seed), expected in literal.items():
        assert assign(key, seed, (0.8, 0.1, 0.1)) == expected
        point = int(hashlib.sha256(('%d\x00%s' % (seed, key)).encode()).hexdigest(), 16) / 2 ** 256  # the documented formula
        assert expected == ('train' if point < 0.8 else 'validation' if point < 0.9 else 'test')
    assert assign('las-well:SYNTHETIC', 42, (0.5, 0.5, 0.0)) == 'validation'
    assert {assign('las-well:W%d' % i, 3, (1 / 3, 1 / 3, 1 / 3)) for i in range(40)} == {'train', 'validation', 'test'}


@pytest.mark.parametrize('fractions', [(0.8, 0.1), (0.5, 0.5, 0.5), (1.2, -0.1, -0.1), 'abc'])
def test_fractions_must_be_three_shares_of_one(fractions):
    with pytest.raises(Refused): _fractions(fractions)
