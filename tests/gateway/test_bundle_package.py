"""E23c C4: a recipe-read package exported through the in-process gateway with Client.export and opened offline.

The package is the Platform's Petrel reader fixture (synthetic, in the shape of the ConSeil 2026 horizon points; its README
states Z on line 2). The real ConSeil excerpt is Integration data under its rights record and is checked there (C5); SDK tests
read no Integration file. Bob's export is compared with Alice's by projection (values, package block, interpretation file,
decisions), not bytes: the descriptors differ in `authorization.evaluated_for`, which is asserted (V15)."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web, shared, app, service  # noqa: F401 (fixtures)
    from project_gateway.tests.upload_compat import FIXTURES as READERS
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential, bundle, bundle_package, cli
from ophiolite.bundle import open_bundle
from ophiolite.errors import IntegrityConflict, PermissionRefused, Unavailable, VerificationFailed
from ophiolite.models import invariants

PRIMARY = (READERS / 'petrel-points-attributes-1-points.txt').read_bytes()
README = (READERS / 'petrel-points-attributes-1-README.txt').read_bytes()
CRS = (READERS / 'petrel-points-attributes-1-points.crsmeta.xml').read_bytes()


def client(web, persona):
    return Client('https://workspace.example', 'p', Credential.bearer('oph_api_' + persona + ':read,write'), web.c)


@pytest.fixture
def package(web, tmp_path):
    """Alice uploads the Petrel export with its README and CRS file; Bob is given read."""
    folder = tmp_path / 'pts'; folder.mkdir()
    for name, raw in (('points.txt', PRIMARY), ('README.txt', README), ('points.crsmeta.xml', CRS)): (folder / name).write_bytes(raw)
    alice = client(web, 'alice')
    report = alice.upload(folder, attribution='Synthetic', rights_confirmed=True, audience=['bob'])
    primary = next(i for i in report.items if i['role'] == 'primary')
    assert report.ok and primary['state'] == 'added'
    asset, revision = primary['asset_id'], primary['revision']
    share(alice, asset, revision, ['bob'])
    return alice, client(web, 'bob'), asset, revision


def share(alice, asset, revision, read):
    target = {'asset_id': asset, 'revision': revision, 'authority': 'ophiolite:uploaded'}
    alice.share(target, read=read, expected_generation=alice.grants(target).generation)


def projection(opened):
    [a] = opened.assets
    return {'values': a.data.to_frame().to_dict('list'), 'package': opened.manifest['assets'][0]['package'], 'interpretation': a.package.interpretation,
            'decisions': a.package.decisions, 'companions': a.package.companions, 'original': a.original}


def test_alice_and_bob_export_the_same_package_and_others_are_refused(web, package, tmp_path):
    alice, bob, asset, revision = package
    mine = alice.export([(asset, revision, None)], tmp_path / 'alice'); theirs = bob.export([(asset, revision, None)], tmp_path / 'bob')
    assert mine.manifest['bundle_version'] == '2.10.0' and projection(open_bundle(mine.path)) == projection(open_bundle(theirs.path))
    descriptor = lambda o: json.loads((o.path / 'assets/0/descriptor.json').read_text())
    assert (descriptor(mine)['authorization']['evaluated_for'], descriptor(theirs)['authorization']['evaluated_for']) == ('alice', 'bob')  # differ, and that is all
    [a] = open_bundle(theirs.path).assets
    assert a.package.companions == {'README.txt': README, 'points.crsmeta.xml': CRS} and a.original == PRIMARY
    z = next(d for d in a.package.decisions if d['field'] == 'z_meaning')
    assert (z['selected'], z['observations'][0]['member'], z['observations'][0]['locator']) == ('time', 'README.txt', 'line 2')
    for persona in ('outsider', 'viewer'):  # Eve: a project member without a grant to it; Charlie: a project viewer without one
        with pytest.raises((Unavailable, PermissionRefused)): client(web, persona).export([(asset, revision, None)], tmp_path / persona)
        assert not (tmp_path / persona).exists() and not list(tmp_path.glob('.' + persona + '.staging-*'))


def test_a_grant_revoked_between_the_data_and_the_package_fails_the_export(web, package, tmp_path, monkeypatch):
    alice, bob, asset, revision = package
    original, seen = bob._get, []
    def revoke_after_the_data(path, limit, **kw):
        raw = original(path, limit, **kw)
        if path.endswith('/representations/data') and not seen:  # the test hook: after the data read succeeds, before any package row
            seen.append(path); share(alice, asset, revision, [])
        return raw
    monkeypatch.setattr(bob, '_get', revoke_after_the_data)
    with pytest.raises((Unavailable, PermissionRefused)): bob.export([(asset, revision, None)], tmp_path / 'bob')
    assert seen and not (tmp_path / 'bob').exists() and not list(tmp_path.glob('.bob.staging-*'))


def rewrite_selected(root, *, manifest_digest):
    """One selected value changed in data.json and interpretation.json with every checksum, listing and block recomputed; with
    `manifest_digest` the descriptor's revision manifest digest is recomputed too (a fully consistent rewrite)."""
    a = root / 'assets/0'
    descriptor = json.loads((a / 'descriptor.json').read_text()); data = json.loads((a / 'data.json').read_bytes()); interpretation = json.loads((a / 'interpretation.json').read_bytes())
    for record in (next(d for d in data['context']['fidelity']['decisions'] if d['field'] == 'positive'), next(d for d in interpretation['decisions'] if d['field'] == 'positive'),
                   next(d for d in descriptor['scientific']['fidelity']['decisions'] if d['field'] == 'positive')):
        record['selected'] = 'down'
        for o in record['observations']: o['value'] = 'down'
    data['context']['positive'] = descriptor['scientific']['positive'] = 'down'
    raw_data, raw_interp = json.dumps(data).encode(), json.dumps(interpretation).encode()
    (a / 'data.json').write_bytes(raw_data); (a / 'interpretation.json').write_bytes(raw_interp)
    normalized = next(r for r in descriptor['representations'] if r['kind'] == 'normalized'); normalized.update(sha256=hashlib.sha256(raw_data).hexdigest(), bytes=len(raw_data))
    listing = {r['id']: r for r in descriptor['manifest']['representations']}
    listing[normalized['id']].update(sha256=normalized['sha256'], bytes=normalized['bytes'])
    listing['interpretation'].update(sha256=hashlib.sha256(raw_interp).hexdigest(), bytes=len(raw_interp))
    if manifest_digest:
        m = descriptor['manifest']
        body = {'schema': m['schema'], 'asset_id': descriptor['asset_id'], 'revision': descriptor['revision'], 'artifact': {'sha256': m['artifact']['sha256'], 'bytes': m['artifact']['bytes']},
                'representations': sorted(({'id': r['id'], 'sha256': r['sha256'], 'bytes': r['bytes']} for r in m['representations']), key=lambda r: r['id']),
                'lineage': sorted(e['commitment'] for e in m['lineage'])}
        if 'method' in m: body['method'] = m['method']
        m['digest'] = hashlib.sha256(bundle_package.canonical(body).encode()).hexdigest()
    (a / 'descriptor.json').write_text(json.dumps(descriptor, indent=2) + '\n')
    manifest = json.loads((root / 'manifest.json').read_text())
    for f in manifest['assets'][0]['files']:
        raw = (root / f['path']).read_bytes(); f.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return root


def test_the_revision_manifest_digest_catches_a_consistent_rewrite_and_a_full_rewrite_is_said_to_be_unconfirmed(web, package, tmp_path, monkeypatch, capsys):
    alice, bob, asset, revision = package
    exported = bob.export([(asset, revision, None)], tmp_path / 'bob')
    assert json.loads((exported.path / 'assets/0/descriptor.json').read_text())['manifest'] is not None  # stop rule 5: the gateway attaches it
    root = rewrite_selected(exported.path, manifest_digest=False)
    with pytest.raises(VerificationFailed, match='The revision manifest digest does not match its contents'): open_bundle(root)
    with monkeypatch.context() as m:  # the control: with that one guard disabled the same bundle opens
        m.setattr(invariants, 'manifest', lambda value, raw, normalized: None)
        assert open_bundle(root).assets[0].data.context['positive'] == 'down'
    full = rewrite_selected(bob.export([(asset, revision, None)], tmp_path / 'again').path, manifest_digest=True)
    assert open_bundle(full).assets[0].data.context['positive'] == 'down'  # D5: undetectable without a digest from a trusted party
    cli.main(['bundle', 'show', str(full)]); shown = capsys.readouterr().out
    assert 'The original revision cannot be independently confirmed.' in shown and 'Z increases downwards; read from line 2 of the README.' in shown


def test_a_companion_changed_on_the_server_fails_the_export_with_nothing_written(web, package, tmp_path):
    alice, bob, asset, revision = package
    db = web.a.journal.db
    with db: db.execute("UPDATE representations SET sha256=? WHERE id='companion:README.txt'", ('f' * 64,))
    with pytest.raises(IntegrityConflict) as conflict: bob.export([(asset, revision, None)], tmp_path / 'bob')
    assert str(conflict.value).startswith('Stored data failed an integrity check.')
    assert not (tmp_path / 'bob').exists() and not list(tmp_path.glob('.bob.staging-*'))


def test_an_export_without_a_package_is_as_before(web, package, tmp_path):
    from project_gateway.tests.test_one_api_matrix import Caller  # noqa: F401 (the same gateway)
    alice = client(web, 'alice')
    las = '~Version\nVERS. 2.0 : LAS\nWRAP. NO : rows\n~Well\nSTRT.M 100 : start\nSTOP.M 101 : stop\nSTEP.M 1 : step\nNULL. -999.25 : missing\nWELL. SDK : fixture\n~Curve\nDEPT.M : depth\nGR.gAPI : gamma\n~ASCII\n100 1\n101 2\n'
    log = alice.upload_data(las.encode(), profile='las2/1', name='Plain', attribution='Synthetic', audience=['bob'], rights_confirmed=True, command_id='c4-plain')
    sent = []; web.c.event_hooks['request'].append(lambda r: sent.append(r.url.path))
    opened = alice.export([(log.asset_id, log.revision, ['GR'])], tmp_path / 'plain')
    assert opened.manifest['bundle_version'] == '1.10.0' and not [p for p in sent if '/representations/package' in p or '/representations/companion' in p]
