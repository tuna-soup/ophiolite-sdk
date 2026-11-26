"""E191 s1 C4 (D-11), gateway lane: `client.figures` and `publish_derived(figures=)` against the in-process gateway, and
`ophiolite results figures` as an external client (a separate process over HTTP, an access key made the way a person
makes one). The SDK decides nothing: a file that is not a figure is refused by the server with its reason, and a
refused figure sent with a version is named by its label while the version stands (Q2). A retry of the same
`publish_derived` call answers the stored figures and adds none (F16). The command line's words name labels, types,
sizes and people, never an id or a digest.

Mutations (break -> RED): the figure command id drawn at random -> the retry adds two more; a refusal undoing or
hiding the version -> the receipt case; `read` typing the bytes itself -> the PDF's type; ids in the words -> the
CLI case."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from test_in_process_publish import web, shared, app, service, client, LAS_TEXT, UNKNOWN  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401 (fixture)
from test_exchange import key
from ophiolite.testing import fixture_server

from project_gateway import attachments

FILES = Path(attachments.__file__).resolve().parents[2] / 'contracts/assets/v1/fixtures/attachments'
EXPECTED = json.loads((FILES / 'expected.json').read_text())['files']
METHOD = {'name': 'scipy.spatial.Delaunay', 'library': 'scipy', 'version': '1.14.1'}


def raw(name):
    return (FILES / 'files' / name).read_bytes()


def published(alice, command, figures=None):
    from ophiolite.typed import PointSet
    source = alice.upload_data(LAS_TEXT.encode(), profile='las2/1', name='Figure source', attribution='Synthetic', audience=[],
                               rights_confirmed=True, command_id='fig-src')
    points = PointSet.write([(0, 0, 3), (10, 5, None)], attributes={'phi': [0.1, None]}, **UNKNOWN)
    return alice.publish_derived(points, name='Figure points', from_=[source], method=METHOD, command_id=command, figures=figures)


def test_the_figure_client_attaches_lists_reads_and_withdraws_and_the_server_refuses(web, tmp_path):
    alice = client(web, 'alice', 'delegate')
    receipt = published(alice, 'fig-derive')
    version = {'asset_id': receipt.asset_id, 'revision': receipt.revision}
    (tmp_path / 'crossplot.png').write_bytes(raw('figure.png'))
    png = alice.figures.attach(version, tmp_path / 'crossplot.png', label='Crossplot')
    pdf = alice.figures.attach((receipt.asset_id, receipt.revision), raw('report.pdf'), label='Report', command_id='fig-pdf')
    assert (png['file_name'], png['sha256'], pdf['file_name'], pdf['media_type']) == ('crossplot.png', EXPECTED['figure.png']['sha256'], None, 'application/pdf')
    assert alice.figures.attach(version, raw('report.pdf'), label='Report', command_id='fig-pdf') == pdf  # the same command
    assert [f['label'] for f in alice.figures.list(version)['attachments']] == ['Report', 'Crossplot']
    assert alice.figures.read(pdf['attachment_id']) == (raw('report.pdf'), 'application/pdf')
    with pytest.raises(Exception) as refused:
        alice.figures.attach(version, raw('polyglot.png'), label='Twice')
    assert attachments.sentence('two-types') in str(refused.value)
    gone = alice.figures.withdraw(png['attachment_id'], reason='A corrected crossplot follows.')
    assert (gone['state'], gone['withdrawal']['reason']) == ('withdrawn', 'A corrected crossplot follows.')
    with pytest.raises(Exception, match='withdrawn'):
        alice.figures.read(png['attachment_id'])


def test_figures_sent_with_a_version_name_a_refused_one_by_its_label_and_a_retry_adds_none(web):
    alice = client(web, 'alice', 'delegate')
    figures = [{'label': 'Crossplot', 'file': raw('figure.png'), 'file_name': 'crossplot.png'}, {'label': 'Drawing', 'file': raw('drawing.svg')}]
    receipt = published(alice, 'fig-derive-2', figures)
    sent = receipt.model_dump(mode='json')['figures']
    assert [f['label'] for f in sent] == ['Crossplot', 'Drawing'] and sent[0]['sha256'] == EXPECTED['figure.png']['sha256']
    assert sent[1] == {'label': 'Drawing', 'refused': sent[1]['refused']} and attachments.sentence('not-a-figure') in sent[1]['refused']
    assert receipt.figures_line == 'The version stands; this figure was not attached: Drawing (%s).' % sent[1]['refused']
    version = {'asset_id': receipt.asset_id, 'revision': receipt.revision}  # the version stands: its figure lists below
    again = published(alice, 'fig-derive-2', figures)
    assert again.model_dump(mode='json')['figures'][0] == sent[0]
    assert [f['attachment_id'] for f in alice.figures.list(version)['attachments']] == [sent[0]['attachment_id']]


# --- the command line ----------------------------------------------------------------------------------------------------

@pytest.fixture
def cli(keyed, tmp_path):
    web = keyed

    def handler(method, path, body, headers):
        headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
        response = web.c.request(method, path, content=body, headers=headers)
        return response.status_code, response.content

    with fixture_server(handler) as server:
        config = tmp_path / 'configuration.json'
        config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': server.url, 'project': 'p'}))
        made = key(web, 'alice')

        def call(*words):
            env = {**os.environ, 'OPHIOLITE_ACCESS_KEY': made['key']}
            done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', 'results', 'figures', *words, '--configuration', str(config),
                                   '--credentials', str(tmp_path / 'not-saved.json')], capture_output=True, text=True, timeout=120, env=env, cwd=tmp_path)
            return done.returncode, done.stdout.strip(), done.stderr.strip()
        call.web = web
        yield call


def words(result):
    code, out, err = result
    assert (code, err) == (0, ''), result
    assert not re.search(r'[0-9a-f]{32}', out), out
    return out


def test_results_figures_attach_list_get_and_withdraw_in_words(cli, tmp_path):
    alice = client(cli.web, 'alice', 'delegate')
    receipt = published(alice, 'fig-derive-cli')
    item = '@%s:%s' % (receipt.asset_id, receipt.revision)
    (tmp_path / 'crossplot.png').write_bytes(raw('figure.png'))
    assert words(cli('attach', item, str(tmp_path / 'crossplot.png'), '--label', 'Crossplot')).startswith('Attached Crossplot: PNG image, 39.2 KiB, added by alice on ')
    assert words(cli('attach', item, str(tmp_path / 'crossplot.png'), '--label', 'Crossplot')).startswith('Attached Crossplot: PNG image')
    listed = words(cli('list', item)).splitlines()
    assert len(listed) == 2 and all(line.startswith('Crossplot: PNG image, 39.2 KiB, added by alice on ') for line in listed)
    out = tmp_path / 'saved.png'
    got = words(cli('get', item, 'Crossplot', '--out', str(out))).splitlines()
    # the fixture proxy answers every file as application/octet-stream (ophiolite.testing); the type is the in-process case's
    assert got == ['2 figures carry this label; the newest was taken.', 'Saved 39.2 KiB (application/octet-stream) to %s.' % out]
    assert out.read_bytes() == raw('figure.png')
    gone = words(cli('withdraw', item, 'Crossplot', '--reason', 'A corrected crossplot follows.')).splitlines()
    assert gone[0] == '2 figures carry this label; the newest was taken.' and gone[1].endswith('; withdrawn by alice on %s: A corrected crossplot follows.' % gone[1].split(' on ')[1][:10])
    code, _, err = cli('get', item, 'Crossplot', '--out', str(tmp_path / 'again.png'))
    assert code != 0 and 'withdrawn' in err and not (tmp_path / 'again.png').exists()
    shown = json.loads(cli('list', item, '--json')[1])
    assert [f['state'] for f in shown['attachments']] == ['withdrawn', 'current']
