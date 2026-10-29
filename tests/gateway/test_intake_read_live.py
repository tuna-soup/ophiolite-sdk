"""E107a C6, gateway lane: `ophiolite intake read` against the real upload and conversion routes of an in-process
gateway, signed in with access keys. tina registers a read procedure that reads her team's PDF reports into well tops
and a deviation survey, alice enables it; bob uploads a folder holding one such report, which waits as "Can be read on
your computer"; bob reads it here (asked once to trust tina's version) and both outputs land in the same upload. A kill
after the declaration, or after the first output, resumes the same command with the saved bytes: the procedure does
not run again and nothing lands twice."""
import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
try:
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
    from project_gateway.tests import real_credentials as platform_tests
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential, cli, intake, procedures
from ophiolite.errors import Incompatible, Unavailable
from ophiolite.procedures import NotRun

READERS = Path(platform_tests.__file__).resolve().parent / 'fixtures' / 'e55_readers'
TOPS = (READERS / 'well-tops-csv-1-well-tops.csv').read_bytes()
DEVIATION = (READERS / 'deviation-csv-1-deviation.csv').read_bytes()
PDF = b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Title (Groningen end of well report HON-GT-01) >>\nendobj\n' + b'0' * 400
READER = '''from ophiolite import procedure
from ophiolite.writers import WrittenOriginal

TOPS = %r
DEVIATION = %r


@procedure
def read(inputs, settings):
    report = inputs['report'][0]
    with open(report.path, 'rb') as handle: assert handle.read(5) == b'%%PDF-'
    with open(report.path + '.runs', 'a') as log: log.write(settings['well'] + '\\n')  # one line per run of this procedure
    return {'tops': WrittenOriginal(TOPS, 'well-tops-csv/1', {'depth_unit': 'm', 'depth_basis': 'same-as-log'}, 'tops.csv'),
            'deviation': WrittenOriginal(DEVIATION, 'deviation-csv/1', {'depth_unit': 'm', 'azimuth_reference': 'grid-north'}, 'deviation.csv')}
'''


def manifest(version=1, slot='report'):
    return {'schema': 'ophiolite.procedure/1', 'name': 'groningen-report', 'label': 'Groningen report reader', 'version': version,
            'version_label': 'Release %d' % version, 'step': 'read',
            'inputs': [{'slot': slot, 'label': 'Report', 'class': 'file',
                        'signature': {'extensions': ['.pdf'], 'head_patterns': ['^%PDF-', 'Groningen'], 'max_head_bytes': 65536}}],
            'outputs': [{'role': 'tops', 'label': 'Well tops', 'class': 'version', 'kind': 'well-tops-csv/1'},
                        {'role': 'deviation', 'label': 'Deviation survey', 'class': 'version', 'kind': 'deviation-csv/1'}],
            'settings': [{'key': 'well', 'label': 'Well name', 'type': 'string'}],
            'entry': 'reader:read'}


def bundle(tmp_path, version=1):
    folder = tmp_path / ('groningen-report-%d' % version)
    folder.mkdir()
    (folder / 'procedure.json').write_text(json.dumps(manifest(version), indent=2))
    (folder / 'reader.py').write_text(READER % (TOPS, DEVIATION))
    return folder


def sdk(world, person):
    return Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)


def sent(world):
    """Every request the clients send: (operation, body or upload header)."""
    log = []
    def record(request):
        operation = request.url.path.rsplit('/', 2)
        if operation[-2] not in ('upload-runs', 'procedures', 'capabilities'): return
        header = request.headers.get('x-ophiolite-upload')
        body = json.loads(base64.b64decode(header)) if header else (json.loads(request.content) if request.content else {})
        log.append((operation[-2] + '/' + operation[-1], body))
    world.c.event_hooks['request'].append(record)
    return log


@pytest.fixture
def setting(world, tmp_path):
    clients = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    v1 = clients['tina'].procedure_register(bundle(tmp_path))
    clients['alice'].procedure_enable(v1['digest'])
    (tmp_path / 'HON-GT-01').mkdir()
    (tmp_path / 'HON-GT-01/end of well report.pdf').write_bytes(PDF)
    report = clients['bob'].upload_runs.upload(tmp_path / 'HON-GT-01', attribution='NAM', audience=['alice'], rights_confirmed=True)
    return {**clients, 'digest': v1['digest'], 'report': report, 'file': tmp_path / 'HON-GT-01/end of well report.pdf', 'state': tmp_path / 'state',
            'cache': tmp_path / 'cache'}


def read(s, **options):
    options.setdefault('settings', ['well=HON-GT-01'])
    return intake.read(s['bob'], s['report'].run_id, s['file'], folder=s['state'], cache=s['cache'], **options)


def runs_of(s): return (s['file'].parent / (s['file'].name + '.runs')).read_text().split() if (s['file'].parent / (s['file'].name + '.runs')).exists() else []


def test_a_report_only_a_read_procedure_reads_waits_and_its_report_names_the_command(setting):
    report = setting['report']
    [row] = report.items
    assert (row['state'], report.counts['needs-procedure']) == ('needs-procedure', 1)
    assert [v['digest'] for v in row['procedures']] == [setting['digest']]
    assert report.rows()[0]['result'] == 'Can be read on your computer'
    assert "    To read it on this computer: ophiolite intake read %s 'end of well report.pdf'" % report.run_id in report.text().splitlines()


def test_bob_is_asked_once_and_both_outputs_land_in_the_same_upload(setting):
    asked = []
    result = read(setting, prompt=lambda q: asked.append(q['text']) or True)
    assert len(asked) == 1 and 'registered by tina' in asked[0] and setting['digest'] in asked[0]
    assert result['conversion']['state'] == 'complete' and result['resumed'] is False and runs_of(setting) == ['HON-GT-01']
    report = result['report']
    [row] = report.items
    assert row['state'] == 'converted' and report.counts['converted'] == 1 and 'needs-procedure' not in report.counts
    assert sorted((o['role'], o['outcome']) for o in row['outputs']) == [('deviation', 'added'), ('tops', 'added')]
    assert report.rows()[0]['result'] == 'Read on your computer' and report.ok
    saved = json.loads((Path(result['state']) / 'convert.json').read_text())
    assert saved['settings'] == {'well': 'HON-GT-01'} and saved['attempt'] == 'attempt-1' and saved['body']['procedure'] == {'digest': setting['digest']}
    assert saved['body']['settings'] == {'well': 'HON-GT-01'}  # E5: declared, so each output's read_by records it
    again = read(setting, prompt=lambda q: pytest.fail('asked twice'))  # the same file again: the stored conversion, nothing new
    assert (again['resumed'], again['conversion']['state'], runs_of(setting)) == (True, 'complete', ['HON-GT-01'])


def kill_at(client, monkeypatch, n):
    """The process dies at the n-th output it sends (0: right after the declaration answered)."""
    real, count = client._post_bytes, {'n': 0}
    def post_bytes(area, operation, raw, **options):
        if operation == 'convert-output':
            if count['n'] == n: raise KeyboardInterrupt('killed')
            count['n'] += 1
        return real(area, operation, raw, **options)
    monkeypatch.setattr(client, '_post_bytes', post_bytes)
    return lambda: monkeypatch.setattr(client, '_post_bytes', real)


@pytest.mark.parametrize('n', [0, 1])
def test_a_kill_after_the_declaration_or_the_first_output_resumes_without_running_again(setting, world, monkeypatch, n):
    alive = kill_at(setting['bob'], monkeypatch, n)
    with pytest.raises(KeyboardInterrupt): read(setting, yes=True)
    alive()
    saved = json.loads((setting['state'] / ('%s-0' % setting['report'].run_id) / 'convert.json').read_text())
    log = sent(world)
    result = read(setting, yes=True)
    assert result['resumed'] is True and runs_of(setting) == ['HON-GT-01']  # the procedure ran once
    declared = [b for op, b in log if op == 'upload-runs/convert']
    assert declared == [{**saved['body'], 'project_id': 'p'}]  # the same command and body
    outputs = [b['role'] for op, b in log if op == 'upload-runs/convert-output']
    assert len(outputs) == 2 - n  # only what the upload has not got yet
    [row] = result['report'].items
    assert row['state'] == 'converted' and sorted(o['role'] for o in row['outputs']) == ['deviation', 'tops']
    assert result['report'].view['outputs_added'] == 2


def original_of(s, person, output):
    c = s[person]
    return c._get(c.prefix + '/%s/revisions/%s/representations/provenance' % (output['asset_id'], output['revision']), 1 << 20)


def test_keep_original_sends_the_original_before_the_outputs_and_keeps_it_beside_both(setting, world):
    log = sent(world)
    result = read(setting, yes=True, keep_original=True)
    assert result['conversion']['state'] == 'complete' and result['conversion']['keep_original'] is True and runs_of(setting) == ['HON-GT-01']
    ops = [op for op, _ in log if op.startswith('upload-runs/convert')]
    assert ops == ['upload-runs/convert', 'upload-runs/convert-original', 'upload-runs/convert-output', 'upload-runs/convert-output']
    [row] = result['report'].items
    assert row['state'] == 'converted' and len(row['outputs']) == 2
    for output in row['outputs']: assert original_of(setting, 'bob', output) == PDF  # byte-equal, to the person who read it
    with pytest.raises(Unavailable): original_of(setting, 'alice', row['outputs'][0])  # not shared with alice


@pytest.mark.parametrize('n', [0, 1])
def test_a_kill_after_the_original_was_staged_resumes_without_running_again_or_sending_twice(setting, world, monkeypatch, n):
    """C4: the original is staged, then the process dies (before any output, or after the first). The resume declares
    the same command, sends the original again (answered from the stage), and only the outputs not yet landed."""
    alive = kill_at(setting['bob'], monkeypatch, n)
    with pytest.raises(KeyboardInterrupt): read(setting, yes=True, keep_original=True)
    alive()
    log = sent(world)
    result = read(setting, yes=True, keep_original=True)
    assert result['resumed'] is True and runs_of(setting) == ['HON-GT-01']  # the procedure ran once
    ops = [op for op, _ in log if op.startswith('upload-runs/convert')]
    assert ops == ['upload-runs/convert', 'upload-runs/convert-original'] + ['upload-runs/convert-output'] * (2 - n)
    [row] = result['report'].items
    assert row['state'] == 'converted' and result['report'].view['outputs_added'] == 2
    for output in row['outputs']: assert original_of(setting, 'bob', output) == PDF
    with pytest.raises(NotRun) as caught: read(setting, yes=True)  # the same command, now without keeping: refused, nothing sent
    assert caught.value.code == 'keep-changed'


def test_another_file_with_the_same_signature_is_refused_with_and_without_keep_original(setting, world, tmp_path):
    other = tmp_path / 'other/end of well report.pdf'
    other.parent.mkdir()
    other.write_bytes(PDF.replace(b'0' * 400, b'1' * 400))
    log = sent(world)
    for keep in (False, True):
        with pytest.raises(NotRun) as caught:
            intake.read(setting['bob'], setting['report'].run_id, other, keep_original=keep, folder=setting['state'], cache=setting['cache'],
                        settings=['well=HON-GT-01'], yes=True)
        assert caught.value.code == 'other-file'
    assert str(caught.value) == ('Not read: end of well report.pdf on this computer is not the file chosen for this upload: its size or digest differs. '
                                 'Nothing ran and nothing was sent.')
    assert [op for op, _ in log if op not in ('upload-runs/status', 'capabilities/describe')] == [] and runs_of(setting) == []
    assert not setting['state'].exists()


def test_a_required_setting_missing_is_refused_before_anything_is_trusted_run_or_sent(setting, world):
    log = sent(world)
    with pytest.raises(NotRun) as caught: read(setting, settings=[], yes=True)
    assert (caught.value.code, str(caught.value)) == ('setting-missing', 'Not run: Well name needs a value.')
    assert [op for op, _ in log if op in ('procedures/trust', 'upload-runs/convert', 'upload-runs/convert-output')] == [] and runs_of(setting) == []


def test_a_withdrawn_version_is_refused_with_its_date(setting):
    setting['alice'].procedure_withdraw(setting['digest'])
    with pytest.raises(NotRun) as caught: read(setting, yes=True)
    assert caught.value.code == 'withdrawn' and str(caught.value) == 'Not run: this procedure was withdrawn on %s.' % procedures._day(setting['alice'].procedure_get(setting['digest'])['withdrawn_at'])
    assert runs_of(setting) == []


def test_the_command_line_reads_it_and_prints_what_became_of_it(setting, monkeypatch, capsys):
    monkeypatch.setenv('OPHIOLITE_INTAKE_STATE', str(setting['state']))
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(setting['cache']))
    args = cli.parser().parse_args(['intake', 'read', setting['report'].run_id, str(setting['file']), '--setting', 'well=HON-GT-01', '--yes', '--json'])
    cli._intake(args, setting['bob'])
    out = json.loads(capsys.readouterr().out)
    assert out['conversion']['state'] == 'complete' and out['report']['items'][0]['state'] == 'converted'
    assert out['sentence'].startswith('Read end of well report.pdf on this computer with Groningen report reader, version 1.')
    args = cli.parser().parse_args(['intake', 'read', setting['report'].run_id, str(setting['file'].parent / 'missing.pdf'), '--setting', 'well=x'])
    (setting['file'].parent / 'missing.pdf').write_bytes(b'%PDF-')
    with pytest.raises(SystemExit) as stopped: cli._intake(args, setting['bob'])
    assert stopped.value.code == cli.EXIT['refused'] and 'Not read: no file of this upload named missing.pdf' in capsys.readouterr().err


def exported(client, output, destination):
    return client.export([(output['asset_id'], output['revision'], None)], destination, groups=False, entities=False)


def test_a_kept_reading_travels_in_bundle_two_nine_and_back_as_recorded(setting, tmp_path):
    """C6b (B1-B3): bob exports what he read on his computer; the bundle is 2.9 with the original beside the reading.
    Alice imports it: her item keeps the original, says it was read "as recorded in the exporting project", and its
    re-export carries the same reading again (B2: never a new local reading); a repeat import is not a duplicate."""
    result = read(setting, yes=True, keep_original=True)
    [row] = result['report'].items
    output = next(o for o in row['outputs'] if o['role'] == 'tops')
    first = exported(setting['bob'], output, tmp_path / 'first')
    assert first.manifest['bundle_version'] == '2.10.0' and first.assets[0].provenance == PDF
    recorded = first.manifest['assets'][0]['read_by']
    assert recorded['original']['sha256'] == hashlib.sha256(PDF).hexdigest() and recorded['kept'] == recorded['original']['sha256']
    [step] = setting['alice'].import_bundle(first, audience=[], attribution='NAM', rights_confirmed=True)
    assert step['state'] == 'imported' and 'provenance' not in step
    mine = step['destination']
    assert original_of(setting, 'alice', mine) == PDF
    told = json.dumps(setting['alice'].story(mine['asset_id'], mine['revision']))
    assert 'as recorded in the exporting project' in told and 'The original file is kept.' in told
    again = exported(setting['alice'], mine, tmp_path / 'again')
    assert again.manifest['bundle_version'] == '2.10.0' and again.manifest['assets'][0]['read_by'] == recorded and again.assets[0].provenance == PDF
    [repeat] = setting['alice'].import_bundle(first, audience=[], attribution='NAM', rights_confirmed=True)
    assert repeat['destination'] == mine  # the stable command: the same item, the original not staged twice


def test_a_reading_without_its_original_exports_as_before(setting, tmp_path):
    result = read(setting, yes=True)
    [row] = result['report'].items
    output = next(o for o in row['outputs'] if o['role'] == 'tops')
    plain = exported(setting['bob'], output, tmp_path / 'plain')
    assert plain.manifest['bundle_version'] != '2.9.0' and plain.assets[0].provenance is None and 'read_by' not in plain.manifest['assets'][0]


def test_an_item_imported_before_without_its_original_is_refused_and_the_rest_continues(setting, tmp_path):
    """I1: imports never upgrade. The tops were imported before without the original (an earlier SDK); the import stages
    nothing for them, refuses them with the deployment's sentence and imports the deviation with its original."""
    from ophiolite import bundle as bundles
    from ophiolite.client import IMPORTED_WITHOUT
    [row] = read(setting, yes=True, keep_original=True)['report'].items
    both = setting['bob'].export([(o['asset_id'], o['revision'], None) for o in row['outputs']], tmp_path / 'both', groups=False, entities=False)
    plan = bundles.import_plan(both, {})
    tops = next(s for s in plan if both.assets[s['position']].type == 'well-tops')
    before = setting['alice'].upload_data(tops['original'], profile=tops['profile'], name=tops['name'], attribution='NAM', audience=[], rights_confirmed=True,
                                          declared=tops['declared'] or None, filename=tops['filename'], command_id=tops['command_id'],
                                          origin={k: v for k, v in tops['origin'].items() if k != 'read_by'})
    steps = setting['alice'].import_bundle(both, audience=[], attribution='NAM', rights_confirmed=True)
    refused = steps[tops['position']]
    assert (refused['state'], refused['reason']) == ('refused', IMPORTED_WITHOUT) and 'destination' not in refused
    with pytest.raises(Incompatible, match='Only a file read on a computer keeps its original'):  # unchanged: no reading, no original
        original_of(setting, 'alice', {'asset_id': before.asset_id, 'revision': before.revision})
    [other] = [s for s in steps if s['position'] != tops['position']]
    assert other['state'] == 'imported' and original_of(setting, 'alice', other['destination']) == PDF
