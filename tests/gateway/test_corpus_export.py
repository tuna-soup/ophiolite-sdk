"""E14 corpus export against the in-process gateway: refused without AI use (nothing written),
exact bundle plus manifest when permitted, splits grouped by well and reproducible, tampering
detected; E18 export needs no AI-use permission."""
import json
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401
from ophiolite.corpus import verify, assign
from ophiolite.errors import PermissionRefused, VerificationFailed, Refused
from project_gateway.tests.test_applications import LAS


def uploaded(web, alice, tmp_path, name, audience=('bob', 'viewer'), well='SYNTHETIC'):
    folder = alice.work_folder(tmp_path / ('upload-' + name))
    upload = folder.upload_las(LAS.replace('SYNTHETIC', well).encode(), name=name, attribution='Synthetic fixture', audience=list(audience), rights_confirmed=True)
    alice.share_upload(upload.asset_id, list(audience), expected_generation=1) if hasattr(alice, 'share_upload') else \
        alice._post('las-uploads', 'share', {'asset_id': upload.asset_id, 'audience': list(audience), 'expected_generation': 1})
    return upload


def test_corpus_needs_ai_use_and_is_exact_and_reproducible(web, tmp_path):
    alice, bob, viewer = client(web, 'alice', 'delegate'), client(web, 'bob', 'delegate'), client(web, 'viewer', 'delegate')
    first = uploaded(web, alice, tmp_path, 'first')
    second = uploaded(web, alice, tmp_path, 'second')          # the same well: one group
    third = uploaded(web, alice, tmp_path, 'third', well='WELL-7')
    chosen = [(u.asset_id, u.revision, ['GR']) for u in (first, second, third)]
    with pytest.raises(PermissionRefused): bob.export_corpus(chosen, tmp_path / 'refused', purpose='training')
    assert not (tmp_path / 'refused').exists()
    for u in (first, second, third):
        alice.grant_ai_use(u.asset_id, {'bob': ['training']}, expected_generation=0)
    summary = bob.export_corpus(chosen, tmp_path / 'corpus', purpose='training', seed=42)
    assert summary['items'] == 3 and summary['samples'] == 9 and summary['purpose'] == 'training'
    manifest = json.loads((tmp_path / 'corpus' / 'corpus.json').read_text())
    entries = manifest['selection']
    assert [(e['asset_id'], e['revision'], e['curves'], e['group']) for e in entries] == [
        (first.asset_id, first.revision, ['GR'], 'las-well:SYNTHETIC'), (second.asset_id, second.revision, ['GR'], 'las-well:SYNTHETIC'),
        (third.asset_id, third.revision, ['GR'], 'las-well:WELL-7')]
    assert entries[0]['split'] == entries[1]['split'] == 'validation' and entries[2]['split'] == 'validation'  # literal split/1, seed 42
    assert manifest['transformations'] == [] and manifest['restrictions']['purpose'] == 'training' and manifest['mlflow']['digest']
    rows = [json.loads(line) for line in (tmp_path / 'corpus' / 'samples.jsonl').read_text().splitlines()]
    assert rows[1][manifest['columns'].index('value')] is None and rows[0][manifest['columns'].index('value')] == 0  # missing is null, zero stays zero
    assert {r[manifest['columns'].index('unit')] for r in rows} == {'gAPI'} and {r[manifest['columns'].index('depth_unit')] for r in rows} == {'M'}
    # Reordering the selection keeps each well's split.
    again = bob.export_corpus(list(reversed(chosen)), tmp_path / 'again', purpose='training', seed=42)
    assert again['by_split'] == summary['by_split']
    # Tampering: a changed sample and a changed split are both detected.
    samples = tmp_path / 'corpus' / 'samples.jsonl'; original = samples.read_bytes()
    assert b',30.0]' in original or b',30]' in original
    samples.write_bytes(original.replace(b',30.0]', b',31.0]').replace(b',30]', b',31]'))
    with pytest.raises(VerificationFailed): verify(tmp_path / 'corpus')
    samples.write_bytes(original)
    edited = dict(manifest); edited['selection'] = [dict(entries[0], split='test')] + entries[1:]
    (tmp_path / 'corpus' / 'corpus.json').write_text(json.dumps(edited))
    with pytest.raises(VerificationFailed): verify(tmp_path / 'corpus')
    # Other purposes stay refused; ordinary export needs no AI-use permission.
    with pytest.raises(PermissionRefused): bob.export_corpus(chosen[:1], tmp_path / 'embed', purpose='embedding')
    assert viewer.export([(first.asset_id, first.revision, ['GR'])], tmp_path / 'bundle').assets[0].revision == first.revision


def test_items_without_a_well_need_a_named_group(web, tmp_path):
    alice = client(web, 'alice', 'delegate')
    nameless = uploaded(web, alice, tmp_path, 'nameless', well='')
    chosen = [(nameless.asset_id, nameless.revision, ['GR'])]
    with pytest.raises(Refused): alice.export_corpus(chosen, tmp_path / 'c1', purpose='evaluation')
    done = alice.export_corpus(chosen, tmp_path / 'c2', purpose='evaluation', groups={nameless.asset_id: 'north block'})
    assert json.loads((tmp_path / 'c2' / 'corpus.json').read_text())['selection'][0]['group'] == 'group:north block' and done['items'] == 1
