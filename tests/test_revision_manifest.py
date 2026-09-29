"""E19 (asset contract 1.8.0): the reader recomputes a revision manifest offline and refuses every
changed field; a hidden lineage entry is a bare commitment that still counts in the digest."""
import copy
import hashlib
import json
import pytest
from ophiolite import validate
from ophiolite.errors import VerificationFailed


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def with_manifest(d):
    d = copy.deepcopy(d)
    artifact = next(r for r in d['representations'] if r['kind'] != 'normalized'); served = next(r for r in d['representations'] if r['kind'] == 'normalized')
    reps = [{'id': served['id'], 'sha256': served['sha256'], 'bytes': served['bytes']}, {'id': 'curve:ZZZ', 'sha256': '5' * 64, 'bytes': 7}]
    lineage = []
    for parent in d['parents']:
        salt = '6' * 32
        lineage.append({'commitment': hashlib.sha256((salt + canonical(['derived-from', parent])).encode()).hexdigest(), 'predicate': 'derived-from', 'reference': parent, 'salt': salt})
    lineage.append({'commitment': '7' * 64})  # a hidden entry
    body = {'schema': 'ophiolite.revision-manifest/1', 'asset_id': d['asset_id'], 'revision': d['revision'], 'artifact': {'sha256': artifact['sha256'], 'bytes': artifact['bytes']},
            'representations': sorted(reps, key=lambda r: r['id']), 'lineage': sorted(e['commitment'] for e in lineage)}
    d['manifest'] = {'schema': 'ophiolite.revision-manifest/1', 'digest': hashlib.sha256(canonical(body).encode()).hexdigest(),
                     'artifact': body['artifact'], 'representations': reps, 'lineage': lineage}
    return d


def test_a_manifest_verifies_and_every_change_is_refused(fixture):
    d, raw, _ = fixture('derived'); d = with_manifest(d)
    assert d['parents'] and validate.pair(d, raw)
    def refused(edit):
        c = copy.deepcopy(d); edit(c)
        with pytest.raises(VerificationFailed): validate.pair(c, raw)
    refused(lambda c: c['manifest'].__setitem__('digest', '0' * 64))
    refused(lambda c: c['manifest']['representations'][1].__setitem__('bytes', 8))  # another curve of the revision
    refused(lambda c: c['manifest']['artifact'].__setitem__('bytes', 1))
    refused(lambda c: c['manifest']['lineage'].pop())  # dropping a hidden entry changes the digest
    refused(lambda c: c['manifest']['lineage'][0].__setitem__('salt', '8' * 32))
    refused(lambda c: c['manifest']['lineage'][0].pop('salt'))
    refused(lambda c: [c['manifest']['lineage'][0].pop(k) for k in ('predicate', 'reference', 'salt')])  # a named parent must be disclosed
    refused(lambda c: c['manifest']['representations'].pop(0))  # the served curve is not in the manifest


METHOD = {'name': 'Gamma-ray offset', 'declared': True, 'library': 'ophiolite-science', 'version': '0.4.0', 'parameters': {'offset': 2}, 'script_sha256': None}


def with_method(d, method=METHOD):
    """1.11.0 (E30a): a /2 manifest names the declared method, and its digest covers it."""
    d = with_manifest(d); m = d['manifest']
    body = {'schema': 'ophiolite.revision-manifest/2', 'asset_id': d['asset_id'], 'revision': d['revision'], 'artifact': m['artifact'],
            'representations': sorted(m['representations'], key=lambda r: r['id']), 'lineage': sorted(e['commitment'] for e in m['lineage']), 'method': method}
    d['manifest'] = {**m, 'schema': 'ophiolite.revision-manifest/2', 'digest': hashlib.sha256(canonical(body).encode()).hexdigest(), 'method': method}
    d['derivation'] = {'method': method}
    return d


def test_a_2_manifest_with_its_method_verifies_and_a_changed_method_is_refused(fixture):
    d, raw, _ = fixture('derived'); d = with_method(d)
    assert validate.pair(d, raw)
    def refused(edit, message=None):
        c = copy.deepcopy(d); edit(c)
        with pytest.raises(VerificationFailed, match=message): validate.pair(c, raw)
    refused(lambda c: c['manifest']['method']['parameters'].__setitem__('offset', 3), 'digest does not match')
    refused(lambda c: c['manifest'].pop('method'))  # a /2 manifest without its method
    refused(lambda c: c['manifest'].__setitem__('schema', 'ophiolite.revision-manifest/1'))  # relabelled: /1 carries no method
    refused(lambda c: c['manifest'].__setitem__('schema', 'ophiolite.revision-manifest/3'))  # a schema this reader does not know
    refused(lambda c: c['derivation']['method'].__setitem__('name', 'Something else'))  # the descriptor's copy
    refused(lambda c: c.pop('derivation'))  # a /2 manifest's method must be declared


def test_an_unknown_manifest_schema_keeps_its_exact_message(fixture):
    """F3: the invariant's wording for a schema it does not know is unchanged ('Unknown revision manifest'), tested on
    the invariant directly, apart from the public model (which refuses the shape first)."""
    from ophiolite.models import invariants
    d, raw, _ = fixture('derived'); d = with_method(d)
    d['manifest']['schema'] = 'ophiolite.revision-manifest/3'
    normalized = next(r for r in d['representations'] if r['kind'] == 'normalized')
    with pytest.raises(Exception, match='^Unknown revision manifest'): invariants.manifest(d, {'sha256': d['manifest']['artifact']['sha256'], 'bytes': d['manifest']['artifact']['bytes']}, normalized)
