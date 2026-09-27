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
