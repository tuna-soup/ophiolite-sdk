"""E180 s2 C5: the SDK's reference-case and reference-run methods and `ophiolite tools reference-cases`,
`tools reference-run` and `tools verify --reference-run`. The route answers are written by hand in the shapes of the
Platform's operation models (the Platform's test_reference_runs and test_reference_verification prove the routes).

The default output is words (R1-17): labels, counts, people's names and the server's sentences; no run id, digest or
other 64-hex string, which only `--json` prints. A version with a case set and no run says so (D8). A refusal is the
server's sentence.

Mutations, each red here: the run id printed in `reference-run list`; the not-run line dropped; `reference_run` sent
as kind witnessed; `supersedes` not read from the current version."""
import contextlib
import copy
import io
import json
import re

import httpx
import pytest

from ophiolite import application_transport, cli
from test_procedures_verify import Recorded, VERSION, DIGEST, refusal

RUN = '7c' * 32
AT = 1795219200.0  # 21 November 2026 00:00 UTC
PERSON = {'kind': 'person', 'id': 'anna', 'name_at_time': 'Anna'}
COUNTS = {'cases': 3, 'passed': 2, 'failed': 0, 'not_counted': 1}
RECORD = {'schema': 'ophiolite.reference-run/1', 'run_id': RUN, 'project': 'p',
          'tool': {'name': 'depth-shift', 'digest': DIGEST, 'version_number': 3, 'label': 'Shift tops by a fixed depth'},
          'cases': {'version': 2, 'least': 2}, 'started_by': PERSON, 'started_at': AT, 'finished_at': AT + 60,
          'box': {'image': 'sha256:' + 'd' * 64, 'runtime': 'r', 'limits': {}, 'network': 'none'},
          'results': [{'case': 'c1', 'outcome': 'passed', 'reason': None, 'job': 'j1', 'comparison': None, 'output': None},
                      {'case': 'c2', 'outcome': 'not_counted', 'reason': 'no-longer-accepted', 'job': None, 'comparison': None, 'output': None},
                      {'case': 'c3', 'outcome': 'passed', 'reason': None, 'job': 'j3', 'comparison': None, 'output': None}],
          'counts': COUNTS}
ENTRY = {'run_id': RUN, 'digest': DIGEST, 'cases_version': 2, 'state': 'finished', 'record': RECORD}
LISTED = {'run_id': RUN, 'digest': DIGEST, 'version_number': 3, 'cases_version': 2, 'state': 'finished', 'counts': COUNTS,
          'started_by': PERSON, 'started_at': AT}
CASE = {'case': 'c1', 'label': 'Well A', 'inputs': [], 'settings': {}, 'compare': {},
        'accepted': {'asset_id': 'tops-a', 'revision': 'r1', 'verdict_id': 'verdict-' + 'e' * 32, 'author': PERSON},
        'still_accepted': True, 'rejections': 1, 'versions_run': 2}
SET = {'tool': 'depth-shift', 'version': 2, 'state': 'active', 'kind': 'well-tops/1', 'least': 2, 'by': PERSON, 'at': AT, 'versions': [1, 2],
       'cases': [CASE, {'case': 'c2', 'restricted': True}]}
HEX = re.compile(r'[0-9a-f]{64}')


def client(**answers):
    return Recorded({'list': {'versions': [VERSION]}, 'start': {**ENTRY, 'state': 'queued', 'record': None}, 'get': lambda body: copy.deepcopy(
        ENTRY if 'run_id' in body else SET), 'declare': {**SET, 'version': 3}, 'withdraw': {**SET, 'version': 3, 'state': 'withdrawn', 'cases': []},
        'verify': {'record': {}, 'verification': {'line': 'Verified'}},
        **answers})


def run(c, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): payload = cli._catalogue(cli.parser().parse_args(['tools', *argv]), c)
    return out.getvalue().strip(), payload


def test_the_methods_send_exactly_the_requests():
    c = client(list=lambda body: {'entries': [LISTED], 'next': None} if body.get('limit') else {'versions': [VERSION]},
               accepted={'entries': [], 'next': None})
    c.reference_cases_declare('depth-shift', 'well-tops/1', [{'case': 'c1'}], supersedes=2, least=1, command_id='d-1')
    c.reference_cases_withdraw('depth-shift', 3, command_id='w-1')
    c.reference_cases_get('depth-shift'); c.reference_cases_get('depth-shift', 1)
    c.accepted_results('well-tops/1', limit=10, cursor='k')
    c.reference_run_start(DIGEST, command_id='s-1'); c.reference_run_get(RUN); c.reference_run_list(tool='depth-shift', digest=DIGEST)
    c.procedure_verify(DIGEST, reference_run=RUN, command_id='v-1')
    assert [(a, o, b) for a, o, b, _ in c.calls] == [
        ('reference-cases', 'declare', {'command_id': 'd-1', 'tool': 'depth-shift', 'supersedes': 2, 'kind': 'well-tops/1', 'least': 1, 'cases': [{'case': 'c1'}]}),
        ('reference-cases', 'withdraw', {'command_id': 'w-1', 'tool': 'depth-shift', 'supersedes': 3}),
        ('reference-cases', 'get', {'tool': 'depth-shift'}), ('reference-cases', 'get', {'tool': 'depth-shift', 'version': 1}),
        ('verdicts', 'accepted', {'kind': 'well-tops/1', 'limit': 10, 'cursor': 'k'}),
        ('reference-runs', 'start', {'command_id': 's-1', 'digest': DIGEST}), ('reference-runs', 'get', {'run_id': RUN}),
        ('reference-runs', 'list', {'limit': 50, 'tool': 'depth-shift', 'digest': DIGEST}),
        ('procedures', 'verify', {'command_id': 'v-1', 'digest': DIGEST, 'kind': 'reference-cases', 'reference': {'run_id': RUN}})]
    c.reference_run_start(DIGEST); c.reference_run_start(DIGEST)
    assert c.calls[-1][2]['command_id'] != c.calls[-2][2]['command_id'] and all(call[3] for call in c.calls)


def test_the_words_name_versions_counts_and_people_and_never_an_id():
    c = client(list=lambda body: {'entries': [LISTED], 'next': None} if 'limit' in body else {'versions': [VERSION]})
    said = {argv: run(c, *argv)[0] for argv in (('reference-cases', 'show', 'depth-shift'), ('reference-run', 'start', 'depth-shift'),
                                               ('reference-run', 'show', RUN), ('reference-run', 'list', 'depth-shift'))}
    assert said == {
        ('reference-cases', 'show', 'depth-shift'): 'The cases of depth-shift, version 2, declared by Anna on 21 November 2026: 2 cases, at least 2 must pass.\n'
                                                     'Case c1 (Well A): still accepted; 1 other rejection; run by 2 versions.\n'
                                                     'Case c2: you cannot open every version it names.',
        ('reference-run', 'start', 'depth-shift'): 'Reference run of Shift tops by a fixed depth, version 3, on version 2 of its cases: waiting for a runner.',
        ('reference-run', 'show', RUN): 'Reference run of Shift tops by a fixed depth, version 3, started by Anna on 21 November 2026: 2 of 2 counted cases passed; 1 no longer accepted.\n'
                                        'Case c1: passed.\nCase c2: not counted: no longer accepted.\nCase c3: passed.',
        ('reference-run', 'list', 'depth-shift'): 'Version 3, started by Anna on 21 November 2026: 2 of 2 counted cases passed; 1 no longer accepted.'}
    assert not [text for text in said.values() if HEX.search(text)]  # mutation (the run id printed in list): RED
    out = io.StringIO()
    with contextlib.redirect_stdout(out): cli._catalogue(cli.parser().parse_args(['tools', 'reference-run', 'list', 'depth-shift', '--json']), c)
    assert json.loads(out.getvalue())['entries'][0]['run_id'] == RUN  # ids under --json only


def test_a_version_with_cases_and_no_run_says_so():
    """D8: `reference-runs/list {digest}` empty while the tool has a case set."""
    c = client(list=lambda body: {'entries': [], 'next': None} if 'limit' in body else {'versions': [VERSION]})
    assert run(c, 'reference-run', 'list', 'depth-shift', '--version', '3')[0] == 'Reference cases not run for this version'  # the frozen line (row 2)
    assert c.calls[-2][2] == {'limit': 200, 'tool': 'depth-shift', 'digest': DIGEST}
    unknown = refusal('set-unknown', 'No reference cases for this tool in this project.')
    unknown.status = 404
    c = client(list=lambda body: {'entries': [], 'next': None} if 'limit' in body else {'versions': [VERSION]}, get=unknown)
    assert run(c, 'reference-run', 'list', 'depth-shift', '--version', '3')[0] == 'No reference runs of depth-shift in this project.'


def test_declare_reads_the_current_version_it_supersedes(tmp_path):
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'case': 'c1'}]))
    c = client()
    text, _ = run(c, 'reference-cases', 'declare', 'depth-shift', '--cases', str(cases), '--kind', 'well-tops/1')
    assert text == 'Declared version 3 of the cases of depth-shift: 2 cases, at least 2 must pass.'
    assert c.calls[-1][2]['supersedes'] == 2 and c.calls[-1][2]['least'] is None  # mutation (supersedes not read): None
    unknown = refusal('set-unknown', 'No reference cases for this tool in this project.')
    unknown.status = 404
    c = client(get=unknown)
    run(c, 'reference-cases', 'declare', 'depth-shift', '--cases', str(cases), '--kind', 'well-tops/1', '--least', '1')
    assert (c.calls[-1][2]['supersedes'], c.calls[-1][2]['least']) == (None, 1)
    assert run(client(), 'reference-cases', 'withdraw', 'depth-shift')[0] == 'Withdrew the cases of depth-shift (version 3): nothing runs on them again.'


def test_verify_against_a_reference_run_and_its_refusal_is_the_servers_sentence():
    line = 'Verified by Anna against 2 of 3 reference cases run by Ophiolite on 21 November 2026'
    c = client(verify={'record': {}, 'verification': {'line': line}})
    assert run(c, 'verify', 'depth-shift', '--reference-run', RUN)[0] == line
    assert (c.calls[-1][2]['kind'], c.calls[-1][2]['reference']) == ('reference-cases', {'run_id': RUN})  # mutation (sent as witnessed): RED
    sentence = 'The reference run passed fewer cases than its set asks for.'
    with pytest.raises(Exception) as raised: run(client(verify=refusal('reference-below', sentence)), 'verify', 'depth-shift', '--reference-run', RUN)
    assert str(raised.value) == sentence
    sentence = 'Only a person starts a reference run.'
    with pytest.raises(Exception) as raised: run(client(start=refusal('permission', sentence)), 'reference-run', 'start', 'depth-shift')
    assert str(raised.value) == sentence
