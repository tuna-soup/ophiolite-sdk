"""E127 s2 C1 (strategy rev 3, D2-D8): the fidelity document for a catalogue manifest uploaded from this computer.
Hand-written run views and a fake client; every refusal also asserts that no file was written. Values are literals; the
provenance digest is kept apart from the manifest's so that taking one for the other fails (F14), and the catalogue
summary's sample counts differ from the exact revision's so that taking the summary's fails (S7). The pinned schema is
outside the SDK tree (the public SDK's unit lane runs without it): validation under it, with formats checked, is C2's
(project_gateway/tests/test_catalogue_fidelity_e2e.py)."""
import copy
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from ophiolite import cli
from ophiolite.errors import PermissionRefused, Refused
from ophiolite.upload_runs import Report, UploadRuns

A, B = 'a' * 64, 'b' * 64  # the manifest's stated SHA-256 of well-a.las and well-b.las
SNAPSHOT = {'source_commit': '1' * 40, 'verification_commit': '2' * 40, 'built_at': '2026-10-23T12:00:00Z', 'records_digest': 'd' * 64}
LAS, TYPED = 'asset_connectors.las_reader/1', 'asset_connectors.typed_reader/1'
COUNTS = {'waiting': 0, 'reading': 0, 'added': 0, 'already_here': 0, 'needs_decision': 0, 'not_read': 0, 'not_supported': 0, 'cancelled': 0,
          'needs_procedure': 0, 'converting': 0, 'converted': 0}
WELL_A = {'sha256': A, 'name': 'well-a.las', 'result': 'converted',
          'output': {'kind': 'well-log', 'id': 'item-a', 'converter': 'asset_connectors.las_reader', 'version': '1'},
          'representative': [{'field': 'GR@1000.0', 'value': 45.1, 'unit': 'GAPI'}, {'field': 'RHOB@1000.0', 'value': 2.31, 'unit': 'G/CC'},
                             {'field': 'samples', 'value': 6, 'unit': None}]}
WELL_B = {'sha256': B, 'name': 'well-b.las', 'result': 'converted',
          'output': {'kind': 'well-log', 'id': 'item-b', 'converter': 'asset_connectors.las_reader', 'version': '1'},
          'representative': [{'field': 'GR@1500.0', 'value': 88.2, 'unit': 'GAPI'}, {'field': 'samples', 'value': 4, 'unit': None}]}


def manifest(assets=None, snapshot=SNAPSHOT, record='acme/two-wells', entries=None):
    assets = {'well-a.las': {'title': 'well-a.las', 'file:checksum': '1220' + A}, 'well-b.las': {'title': 'well-b.las', 'file:checksum': '1220' + B}} if assets is None else assets
    body = {'format': 'osd.manifest/3', 'entries': entries if entries is not None else [{'record_id': record, 'assets': assets}]}
    if snapshot is not None: body['metadata'] = {'catalog': snapshot}
    return body


def output(n, outcome, asset=None, sentence=None, ordinal=None):
    ordinal = ordinal or n
    return {'output': 'listed-%d' % ordinal, 'role': 'listed-%d' % ordinal, 'label': 'Listed file %d' % ordinal, 'kind': 'Well log (LAS)' if asset else '',
            'outcome': outcome, 'asset_id': asset, 'revision': 'r-' + asset if asset else None, 'line': None, 'sentence': sentence}


ADDED = [output(1, 'added', 'item-a'), output(2, 'added', 'item-b')]


def view(raw, outputs, rows=1):
    items = [{'path': 'catalogue/manifest.json' if n == 0 else 'catalogue/manifest-%d.json' % n, 'state': 'not-read', 'sentence': None, 'asset_id': None,
              'kind': '', 'role': 'primary', 'read': None, 'sha256': hashlib.sha256(raw).hexdigest(), 'outputs': copy.deepcopy(outputs)} for n in range(rows)]
    items.append({'path': 'catalogue/notes.txt', 'state': 'not-read', 'sentence': 'No reader.', 'asset_id': None, 'kind': '', 'role': 'primary',
                  'read': None, 'sha256': 'e' * 64, 'outputs': []})
    return {'run_id': 'f' * 64, 'state': 'closed', 'label': 'Finished', 'folder_name': 'catalogue', 'files': len(items), 'settings': {},
            'counts': dict(COUNTS), 'items': items}


def setup(tmp_path, body=None, outputs=ADDED, rows=1):
    """The folder `catalogue` holding manifest.json (BODY), and the closed run that read it with OUTPUTS."""
    folder = tmp_path / 'catalogue'; folder.mkdir(parents=True)
    raw = json.dumps(manifest() if body is None else body).encode()
    (folder / 'manifest.json').write_bytes(raw)
    return folder, Report(view(raw, outputs, rows)), tmp_path / 'out.json'


class Fake:
    """The reads the document needs, each at an exact revision: the catalogue summary (current revision, curve names and
    a count that differs from the revision's), a curve's description and samples, a typed read, provenance."""
    def __init__(self, content=None, curves=None, typed=None, record=True, current=None, refuse=()):
        self.content = {'item-a': A, 'item-b': B, **(content or {})}
        self.curves = curves if curves is not None else {
            'item-a': [('GR', [999.5, 1000.0, 1000.5], [None, 45.1, 46.0], 'GAPI'), ('RHOB', [999.5, 1000.0, 1000.5], [None, 2.31, 2.3], 'G/CC')],
            'item-b': [('GR', [1500.0], [88.2], 'GAPI'), ('NPHI', [1500.0], [None], 'V/V'), ('EMPTY', [], [], '')]}
        self.typed, self.record, self.current, self.refuse, self.asked = typed or {}, record, current or {}, refuse, []
        self.counts = {'item-a': 6, 'item-b': 4}

    def assets(self):
        for asset in sorted(set(self.curves) | set(self.typed)):
            yield {'asset_id': asset, 'revision': self.current.get(asset, 'r-' + asset), 'curves': [c[0] for c in self.curves.get(asset, [])],
                   'sample_count': 999}

    def provenance(self, asset, revision):
        self.asked.append(('provenance', asset, revision))
        if asset in self.refuse: raise PermissionRefused('You may not read this item.')
        return NS(record={'content': {'content_sha256': self.content[asset]}} if self.record else None)

    def describe(self, asset, revision, curve):
        self.asked.append(('describe', asset, revision))
        return NS(interpretation=NS(reader=LAS), scientific=NS(sample_count=self.counts[asset]))

    def read(self, asset, revision, curves):
        self.asked.append(('read', asset, revision))
        return NS(curves=[NS(curve=c, axis=axis, values=values, unit=unit) for c, axis, values, unit in self.curves[asset] if c in curves])

    def read_data(self, asset, revision):
        self.asked.append(('read_data', asset, revision))
        kind, reader = self.typed[asset]
        return NS(type=kind, descriptor=NS(interpretation=NS(reader=reader)))


def write(tmp_path, fake=None, **given):
    folder, report, out = setup(tmp_path, **given)
    assert UploadRuns(fake or Fake()).fidelity(report, folder, out) == out
    return json.loads(out.read_text())


def refused(tmp_path, match, fake=None, source=None, destination=None, **given):
    folder, report, out = setup(tmp_path, **given)
    with pytest.raises(Refused, match=match): UploadRuns(fake or Fake()).fidelity(report, source or folder, destination or out)
    assert not out.exists() and sorted(p.name for p in folder.iterdir()) == ['manifest.json']


def test_two_added_wells_give_the_document_with_literal_values(tmp_path):
    folder, report, out = setup(tmp_path)
    fake = Fake()
    UploadRuns(fake).fidelity(report, folder, out)
    assert json.loads(out.read_text()) == {'format': 'osd.fidelity/1', 'catalog': SNAPSHOT, 'record': 'acme/two-wells', 'inputs': [WELL_A, WELL_B]}
    assert out.read_text() == json.dumps(json.loads(out.read_text()), indent=2, ensure_ascii=False) + '\n'
    assert {revision for _, asset, revision in fake.asked} == {'r-item-a', 'r-item-b'}  # every read at the output's revision


def test_pairing_is_by_order_never_by_title(tmp_path):
    """Two assets with the same title, and a whitespace title: names are the asset keys, in listed order."""
    assets = {'well-a.las': {'title': 'Same', 'file:checksum': '1220' + A}, 'well-b.las': {'title': '  ', 'file:checksum': '1220' + B}}
    assert [(i['name'], i['output']['id']) for i in write(tmp_path, body=manifest(assets))['inputs']] == [('well-a.las', 'item-a'), ('well-b.las', 'item-b')]


@pytest.mark.parametrize('outputs', [ADDED[:1], ADDED + [output(3, 'added', 'item-b')], [ADDED[0], output(2, 'added', 'item-b', ordinal=3)],
                                     [ADDED[0], output(2, 'added', 'item-b', ordinal=1)]], ids=['missing', 'extra', 'gap', 'repeated'])
def test_ordinals_must_be_exactly_one_to_n(tmp_path, outputs):
    refused(tmp_path, r"^This upload's files do not match the files catalogue/manifest\.json lists\. No fidelity document was written\.$", outputs=outputs)


@pytest.mark.parametrize('entries', [
    [{'record_id': 'acme/two-wells', 'assets': {'well-a.las': {}}}, {'record_id': 'acme/other', 'assets': {'well-b.las': {}}}],
    [{'record_id': 'acme/two-wells', 'assets': {'well-a.las': {}}}, {'record_id': 'acme/two-wells', 'assets': {'well-b.las': {}}}],
    [{'assets': {'well-a.las': {}, 'well-b.las': {}}}], [{'record_id': 'Acme/Two Wells', 'assets': {'well-a.las': {}, 'well-b.las': {}}}], []],
    ids=['two-records', 'two-entries-one-record', 'no-record', 'malformed-record', 'no-entry'])
def test_one_manifest_is_one_entry_for_one_record(tmp_path, entries):
    refused(tmp_path, r'^This manifest does not name one catalogue record', body=manifest(entries=entries))


def test_an_entry_whose_files_cannot_be_read_is_refused(tmp_path):
    refused(tmp_path, 'do not match the files', body=manifest(entries=[{'record_id': 'acme/two-wells', 'assets': ['well-a.las']}]))


def test_the_manifest_must_be_the_bytes_the_upload_read(tmp_path):
    folder, report, out = setup(tmp_path)
    (folder / 'manifest.json').write_text(json.dumps(manifest()) + ' ')
    with pytest.raises(Refused, match=r'^catalogue/manifest\.json is not the file this upload read'): UploadRuns(Fake()).fidelity(report, folder, out)
    (folder / 'manifest.json').unlink(); (folder / 'notes.txt').write_text('kept')
    with pytest.raises(Refused, match='is not the file this upload read'): UploadRuns(Fake()).fidelity(report, folder, out)
    assert not out.exists()


def test_an_address_several_manifests_and_no_manifest_are_refused(tmp_path):
    refused(tmp_path / '1', r'^A fidelity document is written for a manifest uploaded from this computer', source='https://example.org/manifest.json')
    refused(tmp_path / '2', r'^This upload read 2 catalogue manifests; a fidelity document is for one', rows=2)
    folder, report, out = setup(tmp_path / '3')
    report.items[0]['outputs'] = []
    with pytest.raises(Refused, match='^This upload read no catalogue manifest'): UploadRuns(Fake()).fidelity(report, folder, out)
    assert not out.exists()


def test_results_map_with_the_stated_digest_and_a_reason_of_at_most_300_characters(tmp_path):
    long = 'x' * 400
    doc = write(tmp_path, outputs=[output(1, 'not-landed', sentence=long), output(2, 'cancelled')])
    assert doc['inputs'] == [{'sha256': A, 'name': 'well-a.las', 'result': 'failed', 'reason': 'x' * 300},
                             {'sha256': B, 'name': 'well-b.las', 'result': 'skipped'}]
    assert write(tmp_path / '2', outputs=[ADDED[0], output(2, 'expired')])['inputs'][1] == {'sha256': B, 'name': 'well-b.las', 'result': 'skipped'}
    assert write(tmp_path / '3', outputs=[output(1, 'already-here', 'item-a'), ADDED[1]])['inputs'] == [WELL_A, WELL_B]


@pytest.mark.parametrize('checksum', [None, '1320' + A, '1220' + A[:-2], A], ids=['none', 'sha512-prefix', 'short', 'bare'])
def test_a_file_not_added_without_a_stated_sha256_is_refused(tmp_path, checksum):
    assets = {'well-a.las': {'file:checksum': checksum} if checksum else {}, 'well-b.las': {'file:checksum': '1220' + B}}
    refused(tmp_path, r'^well-a\.las was not added and the manifest states no SHA-256 for it', body=manifest(assets), outputs=[output(1, 'not-landed', sentence='No.'), ADDED[1]])


def test_a_run_still_reading_is_refused(tmp_path):
    refused(tmp_path, '^This upload is still reading the files', outputs=[output(1, 'planned'), ADDED[1]])


@pytest.mark.parametrize('snapshot', [None, {k: v for k, v in SNAPSHOT.items() if k != 'built_at'}, {**SNAPSHOT, 'built_at': 'yesterday'},
                                      {**SNAPSHOT, 'built_at': '2026-13-40T12:00:00Z'}, {**SNAPSHOT, 'records_digest': 'd' * 63},
                                      {**SNAPSHOT, 'source_commit': 'x' * 40}, {**SNAPSHOT, 'extra': 1}],
                         ids=['none', 'key-missing', 'not-a-time', 'no-such-day', 'short-digest', 'bad-commit', 'extra-key'])
def test_no_or_a_malformed_snapshot_is_refused(tmp_path, snapshot):
    refused(tmp_path, r'^This manifest has no catalogue snapshot, so no fidelity document can name one\.$', body=manifest(snapshot=snapshot))


def test_null_commits_are_a_snapshot(tmp_path):
    snapshot = {**SNAPSHOT, 'source_commit': None, 'verification_commit': None, 'built_at': '2026-10-23T14:00:00.5+02:00'}
    assert write(tmp_path, body=manifest(snapshot=snapshot))['catalog'] == snapshot


@pytest.mark.parametrize('fake', [Fake(record=False), Fake(refuse=('item-b',))], ids=['no-provenance-record', 'not-readable'])
def test_an_item_whose_provenance_cannot_be_read_is_refused(tmp_path, fake):
    refused(tmp_path, r'^What became of well-(a|b)\.las could not be read from this server\.', fake=fake)


def test_provenance_that_differs_from_the_stated_digest_is_refused(tmp_path):
    """F14: the document's sha256 is the landed bytes' (provenance), never the manifest's copied over."""
    refused(tmp_path, r'^well-b\.las was added with other bytes than the manifest states\.', fake=Fake(content={'item-b': 'c' * 64}))
    assets = {'well-a.las': {}, 'well-b.las': {'file:checksum': '1220' + B}}  # no stated digest: the provenance one is used
    assert write(tmp_path / '2', fake=Fake(content={'item-a': 'c' * 64}), body=manifest(assets))['inputs'][0]['sha256'] == 'c' * 64


def test_an_item_with_a_newer_version_is_refused(tmp_path):
    """S7: the output names revision r-item-a; the catalogue's current item is another revision with other curves."""
    fake = Fake(current={'item-a': 'r-newer'})
    refused(tmp_path, r'^well-a\.las has a newer version than the one this upload added', fake=fake)
    assert ('read', 'item-a', 'r-newer') not in fake.asked and ('describe', 'item-a', 'r-newer') not in fake.asked


def test_curve_values_skip_null_samples_and_empty_curves(tmp_path):
    """well-a's first sample of each curve is null (taken at the next depth); well-b's NPHI is all null and EMPTY has
    none: both are left out. The sample count is the revision's (6 and 4), not the summary's 999."""
    assert write(tmp_path)['inputs'] == [WELL_A, WELL_B]


def test_a_typed_output_names_its_kind_and_reader(tmp_path):
    fake = Fake(typed={'item-t': ('well-tops', TYPED)}, content={'item-t': B})
    doc = write(tmp_path, fake=fake, outputs=[ADDED[0], output(2, 'added', 'item-t')])
    assert doc['inputs'][1] == {'sha256': B, 'name': 'well-b.las', 'result': 'converted',
                                'output': {'kind': 'well-tops', 'id': 'item-t', 'converter': 'asset_connectors.typed_reader', 'version': '1'}}
    assert ('read_data', 'item-t', 'r-item-t') in fake.asked


def test_the_destination_is_never_inside_what_was_uploaded(tmp_path):
    folder, report, out = setup(tmp_path)
    for destination in (folder / 'manifest.json', folder / 'fidelity.json', folder):
        with pytest.raises(Refused, match='^The fidelity document cannot be written inside what was uploaded'):
            UploadRuns(Fake()).fidelity(report, folder, destination)
    assert sorted(p.name for p in folder.iterdir()) == ['manifest.json'] and (folder / 'manifest.json').read_text() == json.dumps(manifest())


# the command

def run(tmp_path, *argv, fake=None, outputs=ADDED):
    folder, report, out = setup(tmp_path, outputs=outputs)
    fake = fake or Fake()
    fake.upload_runs = runs = UploadRuns(fake)
    runs.upload = lambda *a, **k: report
    args = cli.parser().parse_args(['upload', str(folder), '--attribution', 'Acme', '--rights-confirmed', *argv])
    return folder, out, lambda: cli._upload(args, fake)


def test_the_command_writes_the_report_then_the_document(tmp_path, capsys):
    folder, out, go = run(tmp_path, '--report', str(tmp_path / 'report.csv'), '--fidelity', str(tmp_path / 'out.json'))
    assert go().exit_code == 4  # the run's own exit is kept: notes.txt was not read (D7)
    assert json.loads(out.read_text())['inputs'] == [WELL_A, WELL_B] and (tmp_path / 'report.csv').exists()
    assert capsys.readouterr().out.rstrip().endswith('Fidelity document written to %s' % out)


def test_a_refusal_after_the_report_keeps_the_report_and_exits_1(tmp_path):
    folder, out, go = run(tmp_path, '--report', str(tmp_path / 'report.csv'), '--fidelity', str(tmp_path / 'out.json'), outputs=[output(1, 'planned'), ADDED[1]])
    with pytest.raises(Refused, match='still reading') as caught: go()
    assert cli.exit_code(caught.value) == cli.EXIT['refused'] == 1
    assert (tmp_path / 'report.csv').read_text().startswith('path,') and not out.exists()


@pytest.mark.parametrize('where', ['report', 'manifest', 'folder'])
def test_the_command_refuses_a_destination_that_would_overwrite_before_anything_is_sent(tmp_path, where):
    report = tmp_path / 'report.csv'
    destination = {'report': report, 'manifest': tmp_path / 'catalogue/manifest.json', 'folder': tmp_path / 'catalogue/out.json'}[where]
    folder, out, go = run(tmp_path, '--report', str(report), '--fidelity', str(destination))
    with pytest.raises(Refused, match='same file|inside what was uploaded'): go()
    assert not report.exists() and sorted(p.name for p in folder.iterdir()) == ['manifest.json']


def test_the_command_refuses_a_table_file_and_an_address(tmp_path):
    table = tmp_path / 'tops.csv'; table.write_text('well,top\n')
    for path, match in ((table, 'a table file has none'), ('https://example.org/manifest.json', 'uploaded from this computer')):
        args = cli.parser().parse_args(['upload', str(path), '--attribution', 'Acme', '--rights-confirmed', '--fidelity', str(tmp_path / 'out.json')])
        fake = NS(upload_runs=NS(upload=lambda *a, **k: pytest.fail('the upload ran')))
        with pytest.raises(Refused, match=match): cli._upload(args, fake)
    assert not (tmp_path / 'out.json').exists()


def test_fidelity_belongs_to_upload_only(capsys):
    with pytest.raises(SystemExit) as caught: cli.parser().parse_args(['import', 'table', 'x.csv', '--fidelity', 'out.json'])
    assert caught.value.code == 2 and '--fidelity' in capsys.readouterr().err
