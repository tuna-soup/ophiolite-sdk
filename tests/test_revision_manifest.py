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
    refused(lambda c: c['manifest'].__setitem__('schema', 'ophiolite.revision-manifest/3'))  # relabelled: /3 carries a derivation record
    refused(lambda c: c['manifest'].__setitem__('schema', 'ophiolite.revision-manifest/4'))  # a schema this reader does not know
    refused(lambda c: c['derivation']['method'].__setitem__('name', 'Something else'))  # the descriptor's copy
    refused(lambda c: c.pop('derivation'))  # a /2 manifest's method must be declared


def test_an_unknown_manifest_schema_keeps_its_exact_message(fixture):
    """F3: the invariant's wording for a schema it does not know is unchanged ('Unknown revision manifest'), tested on
    the invariant directly, apart from the public model (which refuses the shape first)."""
    from ophiolite.models import invariants
    d, raw, _ = fixture('derived'); d = with_method(d)
    d['manifest']['schema'] = 'ophiolite.revision-manifest/4'  # E94: /3 is known now
    normalized = next(r for r in d['representations'] if r['kind'] == 'normalized')
    with pytest.raises(Exception, match='^Unknown revision manifest'): invariants.manifest(d, {'sha256': d['manifest']['artifact']['sha256'], 'bytes': d['manifest']['artifact']['bytes']}, normalized)


def utf8(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def making(record):
    """The derivation digest, written out here from the contract's words, not imported from the library."""
    return hashlib.sha256(utf8({'implementation': {'id': record['implementation']['id'], 'version': record['implementation']['version']},
                                'script_sha256': record['script_sha256'], 'parameters': record['parameters'],
                                'inputs': sorted([i['slot'], i['commitment']] for i in record['inputs']),
                                'outputs': sorted(o['role'] for o in record['outputs'])}).encode()).hexdigest()


def with_record(d):
    """E94: a /3 manifest is the /2 one plus `derivation_record`; `digest` covers the record, `digest_v2` is the /2 view's."""
    d = with_method(d); m = d['manifest']
    named = [e for e in m['lineage'] if e.get('predicate') == 'derived-from']
    record = {'schema': 'ophiolite.derivation/1', 'kind': 'executed',
              'implementation': {'id': 'ophiolite.gamma-offset', 'version': '1', 'version_label': 'version 1'},
              'display': {'method': 'Gamma-ray offset', 'parameters': [{'key': 'offset', 'label': 'Offset', 'unit': 'gAPI'}]},
              'parameters': {'schema': 'ophiolite.parameters/1', 'request': {'type': 'object', 'entries': [{'key': 'offset', 'value': {'type': 'integer', 'value': '2'}}]}, 'resolved': {'type': 'object', 'entries': []}},
              'script_sha256': None, 'release': {'number': '2026.10.65', 'digest': 'a' * 64},
              'inputs': [{'slot': 'gamma', 'commitment': named[0]['commitment']}], 'outputs': [{'role': 'result', 'digest': m['artifact']['sha256']}],
              'execution_id': 'exec-1', 'request_id': None}
    record['derivation_digest'] = making(record)
    body = {'asset_id': d['asset_id'], 'revision': d['revision'], 'artifact': m['artifact'], 'representations': sorted(m['representations'], key=lambda r: r['id']),
            'lineage': sorted(e['commitment'] for e in m['lineage']), 'method': m['method']}
    d['manifest'] = {**m, 'schema': 'ophiolite.revision-manifest/3', 'digest_v2': m['digest'],
                     'digest': hashlib.sha256(utf8({**body, 'schema': 'ophiolite.revision-manifest/3', 'derivation_record': record}).encode()).hexdigest(),
                     'derivation_record': record}
    assert m['digest'] == hashlib.sha256(utf8({**body, 'schema': 'ophiolite.revision-manifest/2'}).encode()).hexdigest()  # ASCII: both encodings agree
    return d


def test_a_3_manifest_is_recomputed_with_its_derivation_record(fixture):
    d, raw, _ = fixture('derived'); d = with_record(d)
    assert validate.pair(d, raw)
    def refused(edit, message):
        c = copy.deepcopy(d); edit(c)
        with pytest.raises(VerificationFailed, match=message): validate.pair(c, raw)
    # only the derivation record changes: the top-level derivation.method and both stored digests stay as they were
    refused(lambda c: c['manifest']['derivation_record']['parameters']['request']['entries'][0]['value'].__setitem__('value', '3'), 'derivation digest')
    refused(lambda c: c['manifest']['derivation_record'].__setitem__('execution_id', 'exec-2'), 'manifest digest')  # outside the making, inside the manifest
    refused(lambda c: c['manifest']['derivation_record']['inputs'][0].__setitem__('commitment', '7' * 64), 'derivation digest|lineage commitment')
    refused(lambda c: c['manifest']['derivation_record']['inputs'].__setitem__(0, {'slot': 'gamma', 'commitment': 'f' * 64}), 'lineage commitment')
    refused(lambda c: c['manifest'].__setitem__('digest_v2', '0' * 64), '/2 view digest')
    refused(lambda c: c['manifest'].pop('derivation_record'), 'declared contract')  # the /3 model requires it
    refused(lambda c: c['derivation'].__setitem__('method', {**c['derivation']['method'], 'name': 'Something else'}), 'declared derivation method')  # a copy: the fixture shares one dict


def test_the_2_view_of_a_3_manifest_passes_the_older_checks_unchanged(fixture):
    """What a reader that does not declare /3 is served: schema /2, `digest_v2`, no record; the top-level derivation stays."""
    d, raw, _ = fixture('derived'); d = with_record(d); m = d['manifest']
    view = copy.deepcopy(d)
    view['manifest'] = {'schema': 'ophiolite.revision-manifest/2', 'digest': m['digest_v2'], **{k: m[k] for k in ('artifact', 'representations', 'lineage', 'method')}}
    assert view['derivation'] == {'method': m['method']} and validate.pair(view, raw)
