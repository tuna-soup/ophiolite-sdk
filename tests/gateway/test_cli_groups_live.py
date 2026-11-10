"""E163 s1 C2, in-process gateway lane: four journeys in the old spelling and the grouped one, through cli.entrypoint
against the real routes. Each answers what the test states, and both spellings answer the same."""
import json

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_well_sources import imported, ORIGIN  # noqa: F401 (fixture)
from test_procedure_requires import LABEL, shift_folder, tops
from ophiolite import Client, cli

SHIFTED = b'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """run(web, *argv) -> (exit code, stdout, stderr), signed in as alice with read and write."""
    cli._load()
    (tmp_path / 'configuration.json').write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', 'oph_api_alice:read,write')
    def call(web, *argv, configured=True):
        if web is not None: monkeypatch.setattr(cli, 'Client', lambda url, project, credential: Client(url, project, credential, web.c))
        capsys.readouterr()
        try: cli.entrypoint([*argv] + (['--configuration', str(tmp_path / 'configuration.json')] if configured else []))
        except SystemExit as stop: code = stop.code
        else: code = 0
        said = capsys.readouterr()
        return code, said.out.replace(str(tmp_path), '<tmp>'), said.err
    return call


def test_data_wells_list_answers_as_wells_list(imported, run):
    old, new = run(imported.web, 'wells', 'list', '--json'), run(imported.web, 'data', 'wells', 'list', '--json')
    assert old == new and old[0] == 0 and old[2] == ''
    assert sorted(w['name'] for w in json.loads(old[1])['wells']) == ['North 1', 'North 2', 'Unlocated']


def test_exchange_export_and_bundle_check_answer_as_export_and_bundle_check(web, run, tmp_path):
    from project_gateway.tests.test_applications import LAS
    upload = client(web, 'alice', 'delegate').upload_las(LAS.encode(), name='Groups input', attribution='Original synthetic fixture',
                                                        audience=['alice'], rights_confirmed=True)
    made = {}
    for label, words in (('old', ('export',)), ('new', ('exchange', 'export'))):
        said = run(web, *words, '--asset', upload.asset_id, '--revision', upload.revision, '--curve', 'GR', '--output', str(tmp_path / label))
        files = sorted(p.relative_to(tmp_path / label).as_posix() for p in (tmp_path / label).rglob('*') if p.is_file())
        made[label] = (said[0], said[1].replace('<tmp>/' + label, '<bundle>'), said[2], files)
    assert made['old'] == made['new'] and made['old'][:3] == (
        0, 'Exported 1 exact revision(s) to <bundle> - check it offline with: ophiolite exchange bundle check <bundle>\n', '')  # E163 s1b moved the sentence
    assert made['old'][3] == ['assets/0/curve-GR.json', 'assets/0/descriptor-GR.json', 'assets/0/original.las', 'manifest.json']
    assert (tmp_path / 'old/assets/0/original.las').read_bytes() == (tmp_path / 'new/assets/0/original.las').read_bytes() == LAS.encode()
    checked = [run(None, *words, str(tmp_path / label), configured=False) for label, words in (('old', ('bundle', 'check')), ('new', ('exchange', 'bundle', 'check')))]
    assert checked[0][0] == 0 and checked[0][1].replace('<tmp>/old', '<bundle>') == checked[1][1].replace('<tmp>/new', '<bundle>') == (
        'Bundle verified: 1 exact revisions, 1 curves, 0 other data. Checksums show integrity, not authorship.\n')


def test_tools_run_answers_as_procedures_run(run, tmp_path):
    folder = shift_folder(tmp_path, [])
    path, declared = tops(tmp_path)
    made = {}
    for words in (('procedures',), ('tools',)):
        out = tmp_path / words[0] / 'out'; out.parent.mkdir()
        said = run(None, *words, 'run', str(folder), '--output', str(out), '--input', f'tops={path}', '--kind', 'tops=well-tops-csv/1',
                   '--declared', f'tops={declared}', '--setting', 'shift=2.5', configured=False)
        made[words] = (said[0], said[1], (out / 'shifted.csv').read_bytes())
    assert made[('procedures',)] == made[('tools',)]
    assert made[('tools',)][0] == 0 and made[('tools',)][1].startswith('Ran %s' % LABEL) and made[('tools',)][2] == SHIFTED
