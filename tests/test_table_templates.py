"""E91 C4: table templates and the NLOG start sample through the SDK and the CLI. A template is a file: its bytes arrive
as the deployment sent them (an Excel workbook is never decoded as text); the CLI sends the coordinate system and the
depth reference it is given; a refusal keeps the deployment's sentence; the sample is stepped to the end."""
import json

import httpx
import pytest

from ophiolite import Client, Credential, cli
from ophiolite.errors import Refused

# A workbook's first bytes (a zip) and bytes that are not UTF-8: decoding either as text or JSON fails or changes them
WORKBOOK = b'PK\x03\x04\x14\x00\x06\x00\x08\x00\xff\xfe\x00[Content_Types].xml\x00\x80\x81'
REFUSED = {'error': 'Choose what the depths are measured from: KB, GL, MSL, or not known.', 'code': 'needs-reference',
           'message': 'Choose what the depths are measured from: KB, GL, MSL, or not known.', 'request_id': 'r-1'}


def served(answers):
    """A client whose deployment answers `area/operation` from `answers` (a list is answered in order); the bodies sent are kept."""
    sent = []
    def handler(request):
        key = '/'.join(request.url.path.rstrip('/').split('/')[-2:])
        sent.append((key, json.loads(request.content)))
        answer = answers[key]
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, httpx.Response): return answer
        return httpx.Response(200, json=answer)
    return Client('https://ophiolite.example', 'p', Credential.bearer('oph_key_alice'), http=httpx.Client(transport=httpx.MockTransport(handler))), sent


def test_a_workbook_arrives_as_the_deployment_sent_it(tmp_path):
    # mutation: decode the answer (answer_bytes ignored in _post_bytes): the workbook is refused as malformed or changed
    client, sent = served({'templates/xlsx': httpx.Response(200, content=WORKBOOK, headers={'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})})
    made = client.template('wells', 'xlsx', length='ft', crs='EPSG:28992', reference='GL')
    assert (made.bytes, made.filename) == (WORKBOOK, 'wells-template.xlsx')
    assert sent == [('templates/xlsx', {'project_id': 'p', 'target': 'wells', 'length': 'ft', 'crs': 'EPSG:28992', 'reference': 'GL'})]
    assert made.save(tmp_path / 'w.xlsx').read_bytes() == WORKBOOK


def test_a_refusal_keeps_the_deployments_sentence():
    # mutation: drop said() around the template call (the transport's generic words reach the person)
    client, _ = served({'templates/csv': httpx.Response(400, json=REFUSED, headers={'X-Request-Id': 'r-1'})})
    with pytest.raises(Refused) as refused: client.template('wells', crs='EPSG:28992')
    assert str(refused.value) == 'Choose what the depths are measured from: KB, GL, MSL, or not known.'


def test_an_unknown_format_is_refused_before_anything_is_sent():
    client, sent = served({})
    with pytest.raises(Refused, match='^Choose the format csv or xlsx.$'): client.template('wells', 'ods')
    assert sent == []


def test_the_cli_sends_the_coordinate_system_and_the_reference_it_is_given(tmp_path, capsys):
    # mutation: drop --crs (or --reference) from the request body: the deployment would refuse or state another reference
    client, sent = served({'templates/csv': httpx.Response(200, content=b'Well name,X (EPSG:28992)\n# example\n')})
    args = cli.parser().parse_args(['template', 'wells', '--crs', 'EPSG:28992', '--reference', 'unknown', '--length', 'ft', '--output', str(tmp_path / 'w.csv')])
    cli._templates(args, client)
    assert sent == [('templates/csv', {'project_id': 'p', 'target': 'wells', 'length': 'ft', 'crs': 'EPSG:28992', 'reference': 'unknown'})]
    assert (tmp_path / 'w.csv').read_bytes() == b'Well name,X (EPSG:28992)\n# example\n'
    assert capsys.readouterr().out == 'Wrote %s (35 bytes).\n' % (tmp_path / 'w.csv')


def test_the_template_list_is_served_in_its_shape():
    rows = [{'target': 'wells', 'display_name': 'Wells', 'lengths': ['m', 'ft'], 'needs_crs': True, 'formats': ['csv', 'xlsx'], 'references': ['KB', 'GL', 'MSL', 'unknown']}]
    client, _ = served({'templates/list': [{'templates': rows}, {'templates': [{'display_name': 'no target'}]}]})
    assert client.templates() == rows
    with pytest.raises(Exception, match='documented shape'): client.templates()


STARTED = {'run_id': 'run-1', 'log': {'path': 'hon-gt-01-gamma-ray-excerpt.las', 'state': 'added', 'sentence': 'Added'},
           'wells_import': 'imp-1', 'wells': {'id': 'imp-1', 'state': 'importing', 'counts': {'created': 0}},
           'statement': 'Depth is along the hole (MD); its reference is not known.'}


def test_the_sample_is_stepped_to_the_end_with_the_same_command(capsys):
    # mutation: return after the start (no step): the wells stay 'importing' and the CLI exits with conflict
    steps = [{'id': 'imp-1', 'state': 'importing', 'counts': {'created': 1000}}, {'id': 'imp-1', 'state': 'complete', 'counts': {'created': 2222, 'skipped': 0}}]
    client, sent = served({'upload-runs/sample': STARTED, 'table-imports/step': steps})
    args = cli.parser().parse_args(['sample', 'start', '--command-id', 'press-1'])
    answer = cli._templates(args, client)
    assert sent == [('upload-runs/sample', {'project_id': 'p', 'command_id': 'press-1'}),
                    ('table-imports/step', {'project_id': 'p', 'id': 'imp-1'}), ('table-imports/step', {'project_id': 'p', 'id': 'imp-1'})]
    assert (answer['run_id'], answer['wells']['state'], answer['wells']['counts']['created']) == ('run-1', 'complete', 2222)
    out = capsys.readouterr()
    assert out.out == 'Depth is along the hole (MD); its reference is not known.\nLog hon-gt-01-gamma-ray-excerpt.las: Added\nWells: complete, 2222 added.\n'
    assert 'Adding the sample... 0 wells so far.' in out.err and 'Adding the sample... 1000 wells so far.' in out.err


def test_a_sample_that_does_not_complete_exits_with_conflict():
    client, _ = served({'upload-runs/sample': STARTED, 'table-imports/step': [{'id': 'imp-1', 'state': 'failed', 'counts': {'created': 0}}]})
    with pytest.raises(SystemExit) as stopped: cli._templates(cli.parser().parse_args(['sample', 'start', '--json']), client)
    assert stopped.value.code == cli.EXIT['conflict']
