"""E106 C6, gateway lane: a run of a catalogue version on exact project versions, published from the SDK and the
command line against the real routes of an in-process gateway (charter rows 5, 11, 15, 18, 22). tina registers
depth-shift and alice enables it; bob runs it on his tops (`@tops-a:<revision>`) and publishes. The report's command
id is saved in the run folder before anything is sent, and every output is published under a command id derived
from the run, so a publish stopped anywhere resumes: one run, each output once."""
import contextlib
import io
import json
import os
import shutil
from pathlib import Path
from urllib.parse import quote

import pytest
try:
    from project_gateway.tests.procedure_world import rows
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
import ophiolite
from ophiolite import Client, Credential, cli, procedures
from ophiolite.client import PROFILES
from ophiolite.procedures import NotRun

BUNDLE = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures/bundles/depth-shift'
TWO_ROLES = '''
@procedure
def shift_both(inputs, settings):
    made = shift(inputs, settings)['shifted']
    return {'shifted': made, 'moved': made}
'''


def sdk(world, person):
    return Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c)


def bundle(tmp_path, version=1, two=False):
    folder = tmp_path / ('depth-shift-%d%s' % (version, '-two' if two else ''))
    shutil.copytree(BUNDLE, folder, ignore=shutil.ignore_patterns('__pycache__'))
    manifest = json.loads((folder / 'procedure.json').read_text())
    manifest['version'] = version
    if two:
        manifest['outputs'].append({'role': 'moved', 'label': 'Moved tops', 'class': 'version', 'kind': 'well-tops-csv/1'})
        manifest['entry'] = 'procedure:shift_both'
        (folder / 'procedure.py').write_text((folder / 'procedure.py').read_text() + TWO_ROLES)
    (folder / 'procedure.json').write_text(json.dumps(manifest, indent=2))
    return folder


TOPS = b'name,md\nTop Chalk,1000.5\nBase Chalk,1200\n'
DECLARED = {'depth_unit': 'm', 'depth_basis': 'same-as-log'}


def upload(client, raw=TOPS, command='tops-a'):
    """One tops version as an upload keeps it (shared with alice and tina)."""
    receipt = client.upload_data(raw, profile='well-tops-csv/1', name='Chalk tops', attribution='Synthetic', audience=['alice', 'tina'], rights_confirmed=True,
                                 declared=DECLARED, filename='tops.csv', command_id=command)
    return {'asset_id': receipt.asset_id, 'revision': receipt.revision}


@pytest.fixture
def setting(world, tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    people = {person: sdk(world, person) for person in ('alice', 'bob', 'tina')}
    people['tops'] = upload(people['bob'])
    return people


def enable(setting, tmp_path, **options):
    v = setting['tina'].procedure_register(bundle(tmp_path, **options))
    setting['alice'].procedure_enable(v['digest'])
    return v


def ran(setting, tmp_path, out='out', version=None):
    tops = setting['tops']
    return setting['bob'].procedure_run('depth-shift', tmp_path / out, {'tops': ['@%s:%s' % (tops['asset_id'], tops['revision'])]}, version=version,
                                        settings=['shift=2.5', 'mode=subtract', 'note=run_7f3a_b9'], yes=True)


def runs(world):
    return rows(world, 'SELECT count(*) FROM procedure_runs')[0][0]


def published(world):
    return rows(world, "SELECT count(*) FROM retained_assets WHERE kind='derived'")[0][0]


def described(client, receipt):
    path = client.prefix + '/' + quote(receipt['asset_id'], safe='') + '/revisions/' + quote(receipt['revision'], safe='')
    return client._json(path + '?' + PROFILES[1:], 256 * 1024)


def test_a_run_on_a_project_version_publishes_once_with_a_4_record_the_sdk_verifies(world, setting, tmp_path):
    v1 = enable(setting, tmp_path)
    done = ran(setting, tmp_path)
    record = json.loads((tmp_path / 'out/run.json').read_text())
    [used] = record['inputs']['tops']
    assert (used['asset_id'], used['revision'], used['kind'], used['declared']) == (setting['tops']['asset_id'], setting['tops']['revision'], 'well-tops-csv/1', DECLARED)
    assert done['run']['procedure']['digest'] == v1['digest']
    answer = setting['bob'].procedure_publish(tmp_path / 'out', name='Shifted chalk')
    [output] = answer['outputs']
    assert answer['sentence'] == 'Published Shifted chalk (Well tops (CSV)), made with Shift tops by a fixed depth version 1 on your computer.'
    assert (output['role'], output['outcome'], answer['run']['state']) == ('shifted', 'published', 'complete')
    assert (runs(world), published(world)) == (1, 1)
    document = described(setting['bob'], output['receipt'])
    record = document['manifest']['derivation_record']
    assert (document['manifest']['schema'], record['schema'], record['kind']) == ('ophiolite.revision-manifest/4', 'ophiolite.derivation/2', 'reported')
    assert (record['procedure']['digest'], record['procedure']['run_id'], record['script_sha256']) == (v1['digest'], answer['run']['run_id'], v1['digest'])
    data = setting['bob'].read_data(output['receipt']['asset_id'], output['receipt']['revision'])  # the SDK verifies the /4 manifest on the way
    assert data is not None
    again = setting['bob'].procedure_publish(tmp_path / 'out')  # publishing again answers the same, publishes nothing
    assert again['outputs'][0]['receipt'] == output['receipt'] and (runs(world), published(world)) == (1, 1)


def test_a_publish_stopped_before_or_after_the_report_resumes_with_one_run(world, setting, tmp_path, monkeypatch):
    enable(setting, tmp_path)
    ran(setting, tmp_path)
    def stop(state): raise KeyboardInterrupt  # stopped after publish.json was saved, before the report was sent
    monkeypatch.setattr(procedures, 'before_report', stop)
    with pytest.raises(KeyboardInterrupt): setting['bob'].procedure_publish(tmp_path / 'out')
    saved = json.loads((tmp_path / 'out/publish.json').read_text())['command_id']
    assert runs(world) == 0
    monkeypatch.setattr(procedures, 'before_report', lambda state: None)
    real = procedures.ProcedureClient._run_output
    def lost(self, *args): raise KeyboardInterrupt  # the report was kept; its answer never arrived
    monkeypatch.setattr(procedures.ProcedureClient, '_run_output', lost)
    with pytest.raises(KeyboardInterrupt): setting['bob'].procedure_publish(tmp_path / 'out')
    assert (runs(world), published(world)) == (1, 0)
    monkeypatch.setattr(procedures.ProcedureClient, '_run_output', real)
    answer = setting['bob'].procedure_publish(tmp_path / 'out')
    assert (runs(world), published(world)) == (1, 1)
    assert json.loads((tmp_path / 'out/publish.json').read_text())['command_id'] == saved
    assert rows(world, 'SELECT command_id FROM procedure_runs')[0][0] == saved and answer['run']['state'] == 'complete'


def test_a_publish_stopped_after_the_first_output_publishes_the_second_once(world, setting, tmp_path, monkeypatch):
    enable(setting, tmp_path, two=True)
    ran(setting, tmp_path)
    real, seen = procedures.ProcedureClient._run_output, []
    def first_only(self, raw, profile, declared, name, parents, method, run_id, role):
        if seen: raise KeyboardInterrupt
        seen.append(role)
        return real(self, raw, profile, declared, name, parents, method, run_id, role)
    monkeypatch.setattr(procedures.ProcedureClient, '_run_output', first_only)
    with pytest.raises(KeyboardInterrupt): setting['bob'].procedure_publish(tmp_path / 'out', name='Chalk')
    assert (runs(world), published(world)) == (1, 1)
    monkeypatch.setattr(procedures.ProcedureClient, '_run_output', real)
    answer = setting['bob'].procedure_publish(tmp_path / 'out')
    assert (runs(world), published(world)) == (1, 2)
    assert [(o['role'], o['outcome']) for o in answer['outputs']] == [('shifted', 'published'), ('moved', 'published')]
    assert answer['sentence'].splitlines()[1] == 'Published Chalk: moved (Well tops (CSV)), made with Shift tops by a fixed depth version 1 on your computer.'


def test_a_local_file_input_or_a_changed_output_is_not_published(world, setting, tmp_path):
    enable(setting, tmp_path)
    (tmp_path / 'tops.csv').write_text('name,md\nTop Chalk,1000.5\n')
    (tmp_path / 'tops.json').write_text(json.dumps(DECLARED))
    setting['bob'].procedure_run('depth-shift', tmp_path / 'local', {'tops': [tmp_path / 'tops.csv']}, kinds={'tops': 'well-tops-csv/1'},
                                 declared={'tops': tmp_path / 'tops.json'}, yes=True)
    with pytest.raises(NotRun) as caught: setting['bob'].procedure_publish(tmp_path / 'local')
    assert caught.value.code == 'local-inputs' and not (tmp_path / 'local/publish.json').exists()
    ran(setting, tmp_path)
    shifted = tmp_path / 'out/shifted.csv'
    shifted.write_bytes(shifted.read_bytes() + b'Extra,1\n')
    with pytest.raises(NotRun) as caught: setting['bob'].procedure_publish(tmp_path / 'out')
    assert caught.value.code == 'output-changed' and (runs(world), published(world)) == (0, 0)
    with pytest.raises(NotRun) as caught: setting['bob'].procedure_publish(tmp_path / 'nothing')
    assert caught.value.code == 'not-a-run'


def test_a_malformed_project_input_runs_nothing(world, setting, tmp_path):
    enable(setting, tmp_path)
    with pytest.raises(NotRun) as caught:
        setting['bob'].procedure_run('depth-shift', tmp_path / 'out', {'tops': ['@' + setting['tops']['asset_id']]}, yes=True)
    assert caught.value.code == 'project-input-format' and not (tmp_path / 'out').exists()


def command(client, *argv):
    out, err, code = io.StringIO(), io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: cli._catalogue(cli.parser().parse_args(['procedures', *map(str, argv)]), client)
        except SystemExit as stop: code = stop.code or 0
    return code, out.getvalue().strip(), err.getvalue().strip()


def test_the_command_line_publishes_in_words_and_json_carries_the_identifiers(world, setting, tmp_path):
    v1 = enable(setting, tmp_path)
    tops = setting['tops']
    code, text, err = command(setting['bob'], 'run', '--from-project', 'depth-shift', '--output', tmp_path / 'out', '--input', 'tops=@%s:%s' % (tops['asset_id'], tops['revision']),
                              '--setting', 'shift=2.5', '--yes')
    assert code == 0, err
    code, text, err = command(setting['bob'], 'publish', tmp_path / 'out', '--name', 'Shifted chalk', '--json')
    assert code == 0, err
    answer = json.loads(text)
    [output] = answer['outputs']
    assert answer['run']['procedure']['digest'] == v1['digest'] and output['receipt']['command_id'] and output['receipt']['asset_id']
    assert len(answer['run']['run_id']) == 64
    code, text, _ = command(setting['bob'], 'publish', tmp_path / 'out')
    assert (code, text) == (0, 'Published Shifted chalk (Well tops (CSV)), made with Shift tops by a fixed depth version 1 on your computer.')
    assert published(world) == 1


def test_inputs_read_with_other_declarations_than_the_project_keeps_are_not_published(world, setting, tmp_path):
    enable(setting, tmp_path)
    ran(setting, tmp_path)
    path = tmp_path / 'out/run.json'
    record = json.loads(path.read_text())
    record['inputs']['tops'][0]['declared']['depth_unit'] = 'ft'  # as if the copy had been read as feet
    path.write_text(json.dumps(record))
    with pytest.raises(NotRun) as caught: setting['bob'].procedure_publish(tmp_path / 'out')
    assert caught.value.code == 'inputs-differ' and published(world) == 0
