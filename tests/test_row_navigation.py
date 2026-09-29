"""E29: an of-entity association may name one row of a table of wells; navigation, bundles and the
generated clients carry the row, and a whole-revision association is unchanged."""
import pytest
from ophiolite.bundle import SCHEMA_2, _check_graph
from ophiolite.errors import VerificationFailed
from ophiolite.navigation import Navigation, PREDICATES


def test_of_entity_names_a_row_only_when_given():
    sent = []
    class Stub(Navigation):
        def _associate(self, *args): sent.append(args)
    Stub().of_entity('t', 'r' * 64, 'well-1', row='NLW-19')
    Stub().of_entity('t', 'r' * 64, 'well-1')
    assert sent[0][1] == {'kind': 'revision', 'asset_id': 't', 'revision': 'r' * 64, 'row': 'NLW-19'}
    assert sent[1][1] == {'kind': 'revision', 'asset_id': 't', 'revision': 'r' * 64}
    assert PREDICATES['of-entity']['row_scoped'] is True and PREDICATES['part-of']['row_scoped'] is False


def graph(relationships):
    manifest = {'schema': SCHEMA_2, 'entities': [{'entity_id': 'w1', 'kind': 'well', 'name': 'N-1', 'identity': {'provisional': True}},
                                                 {'entity_id': 'w2', 'kind': 'well', 'name': 'N-2', 'identity': {'provisional': True}}],
                'relationships': relationships}
    return _check_graph(manifest, [{'asset_id': 't', 'revision': 'r'}])


def test_a_bundle_carries_two_rows_of_one_table_to_two_wells():
    edge = lambda row, well: {'predicate': 'of-entity', 'subject': {'kind': 'revision', 'asset_id': 't', 'revision': 'r', 'row': row}, 'object': {'kind': 'well', 'entity_id': well}, 'evidence': None}
    entities, _ = graph([edge('A', 'w1'), edge('B', 'w2')])
    assert [e.rows() for e in entities] == [[('t', 'r', 'A')], [('t', 'r', 'B')]] and entities[0].revisions() == [('t', 'r')]  # the tuple API is unchanged
    with pytest.raises(VerificationFailed, match='row'): graph([edge('', 'w1')])  # an empty row is no row
