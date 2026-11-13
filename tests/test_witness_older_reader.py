"""E113 s0 (C1): a run Ophiolite made in the project's sandbox carries `procedure.witness` (`ophiolite.derivation/2`
1.2.0). The manifest check refuses a witness the published schema cannot judge (a step other than process, a finish
before the start, a moment that is not finite), a portable bundle keeps the block and its manifest check covers it, and
the released SDK 2026.11.4 reads a descriptor that carries the block: an extra key it keeps and never reads, which is
why the sandbox is a block and not a runner kind (its `Literal['person', 'agent']` refuses one).

The cases are written here by hand (the Platform's are in contracts/scientific/v1/fixtures/witness); the manifest
digest is written out from the contract's words (test_revision_manifest's `redigest`), never taken from `invariants`."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from conftest import FIX
from test_bundle_verification import Read, canonical, released
from test_revision_manifest import redigest, with_reported

from ophiolite import bundle, validate
from ophiolite.errors import VerificationFailed
from ophiolite.models import invariants

WITNESS = {'kind': 'sandbox', 'job': '3f0c2b1e-8d4a-4c6f-9b2e-1a7d5e9c0b44',
           'image': 'sha256:5d1e0c6a9b8f7e3d2c1b0a9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d', 'runtime': 'python-3.12',
           'limits': {'memory_mb': 256, 'seconds': 60, 'cpus': 1.0}, 'network': 'none',
           'started_at': 1793880000.0, 'finished_at': 1793880012.5}


def with_witness(d, witness=WITNESS, **procedure):
    """A /4 manifest whose reported record's procedure carries `witness` (and the given procedure edits), digests redone."""
    d = with_reported(copy.deepcopy(d))
    record = d['manifest']['derivation_record']
    record['procedure']['witness'] = copy.deepcopy(witness)
    record['procedure'].update(procedure)
    redigest(d)
    return d


def check(d):
    artifact = next(r for r in d['representations'] if r['kind'] != 'normalized')
    normalized = next(r for r in d['representations'] if r['kind'] == 'normalized')
    return invariants.manifest(d, artifact, normalized)


def derived():
    return json.loads((FIX / 'derived.json').read_text())


def test_a_witnessed_record_passes_the_manifest_check_and_equal_moments_are_allowed():
    assert check(with_witness(derived())) is None
    assert check(with_witness(derived(), {**WITNESS, 'finished_at': WITNESS['started_at']})) is None


SEMANTIC = {
    'a read step': ({}, {'step': 'read'}, 'Only a process step runs in the sandbox'),
    'finished before it started': ({'finished_at': 1793879999.0}, {}, 'finishes after it starts'),
}


@pytest.mark.parametrize('case', sorted(SEMANTIC))
def test_the_manifest_check_refuses_what_the_schema_cannot_state(case):
    edit, procedure, words = SEMANTIC[case]
    with pytest.raises(VerificationFailed, match=words):
        check(with_witness(derived(), {**WITNESS, **edit}, **procedure))


@pytest.mark.parametrize('moment', ['nan', 'inf', '-inf'])
def test_a_moment_that_is_not_finite_is_refused_before_any_digest(moment):
    """The digest cannot be written over NaN (allow_nan=False), so the block is set after `redigest`: the finite rule
    must refuse before the digest comparison would."""
    d = with_witness(derived())
    d['manifest']['derivation_record']['procedure']['witness']['started_at'] = float(moment)
    with pytest.raises(VerificationFailed, match='finite start and finish'):
        check(d)


def test_an_absent_witness_served_as_null_is_not_digested():
    """A model dump that fills `witness: None` (the generated SDK model from C4 on) recomputes to the stored digest."""
    d = with_reported(derived())
    d['manifest']['derivation_record']['procedure']['witness'] = None
    assert check(d) is None


def test_the_generated_models_dump_of_a_record_without_the_block_passes_the_manifest_check():
    """R9: the generated model fills both absent blocks with None; the strip keeps the stored digest true."""
    from ophiolite.models.generated import DerivationRecordV2
    d = with_reported(derived())
    record = DerivationRecordV2.model_validate(d['manifest']['derivation_record']).model_dump(by_alias=True)
    assert record['procedure']['witness'] is None and record['procedure']['verification'] is None
    assert check({**d, 'manifest': {**d['manifest'], 'derivation_record': record}}) is None
    witnessed = with_witness(derived())
    record = DerivationRecordV2.model_validate(witnessed['manifest']['derivation_record']).model_dump(by_alias=True, mode='json')
    assert record['procedure']['witness']['image'] == WITNESS['image']


@pytest.fixture
def written(tmp_path):
    d = with_witness(derived())
    opened = bundle.write_bundle(tmp_path / 'bundle', [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read(d))])
    [asset] = opened.assets
    path = next(f['path'] for f in asset.entry['files'] if f['role'] == 'descriptor')
    return d, opened, path


def test_a_bundle_keeps_the_witness_and_its_manifest_check_covers_it(written):
    """Charter acceptance 7 (export half): written and reopened, the block is the same canonical bytes and the pair
    verifies; a changed image digest, with the file's size and checksum made right again, is the manifest's refusal."""
    d, opened, path = written
    root = Path(opened.path)
    descriptor = json.loads((root / path).read_bytes())
    assert canonical(descriptor['manifest']['derivation_record']['procedure']['witness']) == canonical(WITNESS)
    assert validate.pair(descriptor, (FIX / 'derived-curve.json').read_bytes())
    assert bundle.open_bundle(root).assets[0].revision == d['revision']

    descriptor['manifest']['derivation_record']['procedure']['witness']['image'] = 'sha256:' + 'e' * 64
    raw = json.dumps(descriptor).encode(); (root / path).write_bytes(raw)
    manifest = json.loads((root / 'manifest.json').read_text())
    for f in manifest['assets'][0]['files']:
        if f['path'] == path: f['bytes'], f['sha256'] = len(raw), hashlib.sha256(raw).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(VerificationFailed, match='revision manifest digest'):
        bundle.open_bundle(root)


def test_the_released_reader_keeps_the_witness_unread_and_passes_the_manifest_check():
    generated, older = released()
    d = with_witness(derived())
    assert 'witness' not in generated.DerivationProcedure.model_fields
    record = generated.DerivationRecordV2.model_validate(d['manifest']['derivation_record']).model_dump(by_alias=True)
    assert canonical(record['procedure']['witness']) == canonical(WITNESS)
    value = {**d, 'manifest': {**d['manifest'], 'derivation_record': record}}
    artifact = next(r for r in d['representations'] if r['kind'] != 'normalized')
    normalized = next(r for r in d['representations'] if r['kind'] == 'normalized')
    assert older.manifest(value, artifact, normalized) is None


def test_the_released_reader_would_refuse_the_sandbox_as_a_runner_kind():
    """Design 2's reason for a block: a new runner kind is a record the released SDK cannot read."""
    from pydantic import ValidationError
    generated, _ = released()
    d = with_reported(derived())
    d['manifest']['derivation_record']['procedure']['runner'] = {'kind': 'sandbox', 'principal': 'bob', 'on_behalf_of': None}
    with pytest.raises(ValidationError):
        generated.DerivationRecordV2.model_validate(d['manifest']['derivation_record'])
