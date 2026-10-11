"""E61 C7: the SQL Server and Oracle capability documents are carried byte for byte. SOURCE.json pins each copy to the
Platform snapshot it came from; the registry lists both with the OSDU statement; and, where the Connectors package is
installed, each copy is its source's bytes (an edited character fails here and in Integration's pre-dispatch)."""
import hashlib
import json
from pathlib import Path

import pytest

CONTRACTS = Path(__file__).resolve().parents[1] / 'ophiolite/contracts'
ENGINES = {'sqlserver-wells': 'SQL Server well headers and tables', 'oracle-wells': 'Oracle well headers and tables'}


def entry(name):
    registry = json.loads((CONTRACTS / 'registry.json').read_text())
    return next(d for d in registry['documents'] if d['id'] == 'ophiolite.connector-capability/%s/1' % name)


@pytest.mark.parametrize('name', sorted(ENGINES))
def test_each_engine_document_is_pinned_registered_and_the_connectors_bytes(name):
    path = 'connectors/v1/capabilities/%s.json' % name
    data = (CONTRACTS / path).read_bytes()
    assert json.loads((CONTRACTS / 'SOURCE.json').read_text())['files'][path] == hashlib.sha256(data).hexdigest()
    listed = entry(name)
    assert (listed['kind'], listed['path']) == ('capability', path)
    assert listed['title'].endswith('OSDU kind: none (a source connector)')
    document = json.loads(data)
    assert document['id'] == name and document['kind'] == 'source'
    assert document['display_name'] == ENGINES[name]
    connectors = pytest.importorskip('asset_connectors')
    from importlib.resources import files
    assert files(connectors).joinpath('capabilities', name + '.json').read_bytes() == data, name


def test_the_snapshot_names_the_registry_version_with_both_documents():
    assert json.loads((CONTRACTS / 'SOURCE.json').read_text())['registry_version'] == json.loads((CONTRACTS / 'registry.json').read_text())['version'] == '1.32.0'
