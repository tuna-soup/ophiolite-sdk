"""E19 (ADR 0016 §1a): every retained revision carries a manifest; its digest is the same for every
reader at every time, and the offline reader recomputes it and ties it to the bytes in a bundle."""
import hashlib
import json
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401
from ophiolite.bundle import open_bundle
from ophiolite.errors import VerificationFailed


def published(web):
    alice = client(web, 'alice', 'delegate')
    binding = alice.configure(release_id=web.r['id'], curve='GR', name='Manifest', runners=['alice'], command_id='m-cfg', publication_profile='curve-edits/1')
    run = alice.start(binding, application_version='sdk-manifest/1', parameters={}, command_id='m-run'); run.input()
    first = alice.publish(run, changes=[{'index': 0, 'value': 4}])
    return alice, first.output_reference.key, first.output_reference.revision, first


def test_the_manifest_digest_is_the_same_for_every_reader_and_verified_offline(web, tmp_path):
    alice, key, revision, first = published(web)
    bundle = alice.export([(key, revision, ['GR'])], tmp_path / 'bundle')
    descriptor = bundle.assets[0].curves['GR'].wire_descriptor
    digest = descriptor['manifest']['digest']
    assert len(digest) == 64 and [e['predicate'] for e in descriptor['manifest']['lineage']] == ['derived-from']
    alice.share(first, read=['bob'], expected_generation=alice.grants(first).generation)
    bob = client(web, 'bob', 'delegate')
    later = bob.export([(key, revision, ['GR'])], tmp_path / 'bob')
    assert later.assets[0].curves['GR'].wire_descriptor['manifest']['digest'] == digest  # another person, another time
    assert open_bundle(tmp_path / 'bundle').assets[0].revision == revision  # verified offline


def reseal(folder, relative, raw):
    """Change one file and every checksum that names it, as an editor of an unsigned folder could."""
    (folder / relative).write_bytes(raw)
    manifest = json.loads((folder / 'manifest.json').read_text())
    for entry in manifest['assets']:
        for item in entry['files']:
            if item['path'] == relative: item['sha256'], item['bytes'] = hashlib.sha256(raw).hexdigest(), len(raw)
    (folder / 'manifest.json').write_text(json.dumps(manifest))


def test_changed_values_with_consistent_checksums_are_refused_by_the_manifest(web, tmp_path):
    alice, key, revision, first = published(web)
    folder = alice.export([(key, revision, ['GR'])], tmp_path / 'bundle').path
    files = {item['role']: item['path'] for item in json.loads((folder / 'manifest.json').read_text())['assets'][0]['files']}
    curve = (folder / files['normalized']).read_bytes().replace(b'"values":[4', b'"values":[5')
    reseal(folder, files['normalized'], curve)
    descriptor = json.loads((folder / files['descriptor']).read_text())
    for rep in descriptor['representations']:
        if rep['kind'] == 'normalized': rep['sha256'], rep['bytes'] = hashlib.sha256(curve).hexdigest(), len(curve)
    reseal(folder, files['descriptor'], json.dumps(descriptor).encode())  # the descriptor now agrees with the changed curve...
    with pytest.raises(VerificationFailed, match='manifest'):  # ...but not with the revision's manifest
        open_bundle(folder)
