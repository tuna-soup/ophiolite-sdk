"""E165 s2 (C5): a reported result's frozen `procedure.verification` block travels in a portable bundle unchanged, the
bundle's manifest check covers it, an import leaves the lineage behind (D5), and the released SDK 2026.11.4 reads a
descriptor that carries the block (D6): the block is an extra key it keeps and never reads.

The /4 manifest digest is written out here from the contract's words (the test_revision_manifest construction), never
taken from `invariants`. The released reader is a verbatim extract of that release (tests/frozen/sdk_release_2026_11_4),
loaded under names no installed module has, after its digest is checked."""
import copy
import hashlib
import json
import types
from functools import lru_cache
from pathlib import Path

import pytest
from conftest import FIX
from test_revision_manifest import utf8, with_reported

from ophiolite import bundle, validate
from ophiolite.errors import VerificationFailed

FROZEN = Path(__file__).with_name('frozen') / 'sdk_release_2026_11_4'
DIGESTS = {'generated.py.txt': 'eb8fb61dc614696c14c1bc99b36036741768bbc07e178e60cc8909ee6686da96',
           'invariants.py.txt': 'b1a2b6b7d6beb32c2406b4f32e6912fd1df141aeddc4c5410537d9adeeca7469'}  # sha256 of each extract
BLOCK = {'state': 'verified', 'id': 'verification-' + '3f0c' * 8, 'by': {'kind': 'person', 'id': 'bob', 'name_at_time': 'Bob'},
         'at': 1793836800.25, 'reference_label': 'Depth shifting of well tops',
         'line': 'Verified by Bob against Depth shifting of well tops on 5 November 2026'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def with_block(d, block=BLOCK):
    """A /4 manifest whose reported record's procedure carries BLOCK, the manifest digest recomputed here."""
    d = with_reported(copy.deepcopy(d)); m = d['manifest']
    m['derivation_record']['procedure']['verification'] = copy.deepcopy(block)
    body = {'schema': m['schema'], 'asset_id': d['asset_id'], 'revision': d['revision'], 'artifact': m['artifact'],
            'representations': sorted(m['representations'], key=lambda r: r['id']), 'lineage': sorted(e['commitment'] for e in m['lineage']),
            'method': m['method'], 'derivation_record': m['derivation_record']}
    m['digest'] = hashlib.sha256(utf8(body).encode()).hexdigest()
    return d


class Read:
    """The shape Client.read returns for the derived fixture, with the given descriptor."""
    def __init__(self, descriptor):
        self.artifact = (FIX / 'derived.las').read_bytes()
        self._wire_descriptors = [descriptor]
        self._wire_curves = [json.loads((FIX / 'derived-curve.json').read_bytes())]
        self._wire_curve_bytes = [(FIX / 'derived-curve.json').read_bytes()]


@pytest.fixture
def written(tmp_path):
    d = with_block(json.loads((FIX / 'derived.json').read_text()))
    opened = bundle.write_bundle(tmp_path / 'bundle', [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, Read(d))])
    [asset] = opened.assets
    path = next(f['path'] for f in asset.entry['files'] if f['role'] == 'descriptor')
    return d, opened, path


def test_a_bundle_keeps_the_block_and_its_manifest_check_covers_it(written):
    """Acceptance 8: written and opened, the block is the same canonical bytes and the pair verifies; one changed
    character of the block, with the file's size and checksum made right again, is the manifest digest's refusal."""
    d, opened, path = written
    root = Path(opened.path)
    descriptor = json.loads((root / path).read_bytes())
    assert canonical(descriptor['manifest']['derivation_record']['procedure']['verification']) == canonical(BLOCK)
    assert descriptor['manifest']['digest'] == d['manifest']['digest']
    assert validate.pair(descriptor, (FIX / 'derived-curve.json').read_bytes())
    reopened = bundle.open_bundle(root)
    assert reopened.assets[0].revision == d['revision']

    descriptor['manifest']['derivation_record']['procedure']['verification']['reference_label'] = 'Depth shifting of well topz'
    raw = json.dumps(descriptor).encode(); (root / path).write_bytes(raw)
    manifest = json.loads((root / 'manifest.json').read_text())
    for f in manifest['assets'][0]['files']:
        if f['path'] == path: f['bytes'], f['sha256'] = len(raw), hashlib.sha256(raw).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(VerificationFailed, match='revision manifest digest'):
        bundle.open_bundle(root)


def test_an_import_plan_names_no_derivation(written):
    """D5: an import uploads the original and its declarations; the lineage, the record and its block stay behind."""
    _, opened, _ = written
    [step] = bundle.import_plan(opened, {})
    text = json.dumps({k: v for k, v in step.items() if k != 'original'})
    assert step['state'] == 'ready' and 'derivation' not in text and 'verification' not in text and 'procedure' not in text, text


def _load(name, file):
    raw = (FROZEN / file).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == DIGESTS[file], file + ' is not the frozen extract'
    module = types.ModuleType(name)
    module.__package__, module.__file__ = 'ophiolite.models', str(FROZEN / file)
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)  # compiled here: nothing is written beside the extracts
    return module


@lru_cache(maxsize=1)
def released():
    """(generated, invariants): the released 2026.11.4 models and manifest check."""
    import ophiolite.models  # noqa: F401 (the package its relative import names)
    return (_load('ophiolite.models._release_2026_11_4_generated', 'generated.py.txt'),
            _load('ophiolite.models._release_2026_11_4_invariants', 'invariants.py.txt'))


def test_the_released_reader_keeps_the_block_unread_and_passes_the_manifest_check():
    """D6: SDK 2026.11.4 validates the record (the block is an extra key it keeps, with no field that reads it) and its
    manifest check passes over the dump, as its validate.pair does."""
    generated, invariants = released()
    d = with_block(json.loads((FIX / 'derived.json').read_text()))
    assert 'verification' not in generated.DerivationProcedure.model_fields
    record = generated.DerivationRecordV2.model_validate(d['manifest']['derivation_record']).model_dump(by_alias=True)
    assert canonical(record['procedure']['verification']) == canonical(BLOCK)
    value = {**d, 'manifest': {**d['manifest'], 'derivation_record': record}}
    artifact = next(r for r in d['representations'] if r['kind'] != 'normalized')
    normalized = next(r for r in d['representations'] if r['kind'] == 'normalized')
    assert invariants.manifest(value, artifact, normalized) is None
