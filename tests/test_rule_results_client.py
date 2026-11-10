"""E144 s3 C2: `client.rule_results` and `ophiolite rules show|run`. `show` against a fixture server with frozen answers
(failed, passed, not-applicable, null, lines null, 404), literals by hand; `run` on this computer from the s1 LAS
fixture named .csv equals the snapshot's oracle, and runs with no configuration file and no network. The server's side
is the Platform's test_rule_results_read.py, whose GR_LINES the local words below repeat."""
import json
import shutil
import socket
from importlib.resources import files

import pytest

from ophiolite import Client, Credential, cli, rule_results
from ophiolite.data_rules import engine
from ophiolite.testing import fixture_server

REVISION = 'b' * 64
RUN = files('ophiolite').joinpath('contracts/rules/v1/fixtures/run')
GR_BLOCK = engine.parse(RUN.joinpath('1.3.0', 'las-gr.expected.json').read_bytes())
GR_LINES = [
    {'rule': 'depth-increasing/1', 'state': 'passed', 'sentence': 'Depth moves one way: passed.'},
    {'rule': 'gr-range/1', 'state': 'failed', 'sentence': 'Gamma ray within its plausible range: 4 rows have a gamma ray outside 0 gAPI to 4000 gAPI, the first at depth 1002.5.'},
    {'rule': 'null-sentinel/1', 'state': 'failed', 'sentence': 'No unnamed null values: 1 rows hold a common null value the header does not name as NULL, the first at depth 1003.5.'},
    {'rule': 'unit-known/1', 'state': 'passed', 'sentence': 'Curve units known to their quantity: passed.'}]
GR_TEXT = '''Checked by 4 rules: 2 passed, 2 failed, 0 did not apply.
Depth moves one way: passed.
Gamma ray within its plausible range: 4 rows have a gamma ray outside 0 gAPI to 4000 gAPI, the first at depth 1002.5.
No unnamed null values: 1 rows hold a common null value the header does not name as NULL, the first at depth 1003.5.
Curve units known to their quantity: passed.
'''


def result(rule, state, reason=None):
    return {'rule': rule, 'state': state, 'count': 0, 'examples': [], 'parameters': {}, 'reason': reason, 'context': None}


def block(*results):
    return {'schema': 'ophiolite.rule-results/1', 'kind': 'well-tops-csv/1', 'registry_version': '1.3.0', 'results': list(results)}


ANSWERS = {
    'failed': {'results': GR_BLOCK, 'lines': GR_LINES},
    'passed': {'results': block(result('tops-unique/1', 'passed')),
               'lines': [{'rule': 'tops-unique/1', 'state': 'passed', 'sentence': 'Each top named once: passed.'}]},
    'not-applicable': {'results': block(result('top-on-path/1', 'not-applicable', 'no-context'), result('tops-unique/1', 'passed')),
                       'lines': [{'rule': 'top-on-path/1', 'state': 'not-applicable', 'sentence': "Each top on the wellbore's path: did not apply; it needs other data in the project."},
                                 {'rule': 'tops-unique/1', 'state': 'passed', 'sentence': 'Each top named once: passed.'}]},
    'null': {'results': None, 'lines': None},
    'unworded': {'results': block(result('tops-unique/1', 'passed')), 'lines': None},
}
SHOWN = {
    'failed': GR_TEXT,
    'passed': 'Checked by 1 rule: 1 passed, 0 failed, 0 did not apply.\nEach top named once: passed.\n',
    'not-applicable': "Checked by 2 rules: 1 passed, 0 failed, 1 did not apply.\nEach top on the wellbore's path: did not apply; it needs other data in the project.\nEach top named once: passed.\n",
    'null': 'No rule results for this version: it landed before rules ran.\n',
    'unworded': 'Checked by 1 rule: 1 passed, 0 failed, 0 did not apply.\nThese results cannot be shown in words; see Technical details.\n',
}


def test_the_client_names_the_exact_version():
    class Fake(rule_results.RuleResultsClient):
        sent = []

        def _post(self, area, operation, body, retry=False):
            self.sent.append((area, operation, body, retry))
            return {}
    Fake().rule_results('r1', REVISION)
    assert Fake.sent == [('rule-results', 'get', {'asset_id': 'r1', 'revision': REVISION}, True)] and issubclass(Client, rule_results.RuleResultsClient)


@pytest.fixture
def show(tmp_path, monkeypatch, capsys):
    """show(asset, *flags) -> (exit code, stdout, stderr, bodies sent) of `ophiolite rules show ITEM` against frozen answers;
    the asset id names which answer, and 'gone' answers 404."""
    sent = []

    def handler(method, path, raw, headers):
        body = json.loads(raw)
        sent.append((path.rsplit('/', 2)[-2:], body))
        if body['asset_id'] == 'gone':
            return 404, {'error': {'code': 'not-found', 'message': 'not found'}}
        return 200, {'asset_id': body['asset_id'], 'revision': body['revision'], **ANSWERS[body['asset_id']]}
    monkeypatch.setattr(Credential, 'from_file', lambda path: Credential.bearer('oph_api_alice'))
    monkeypatch.setattr(Client, 'result_version', lambda self, text: (text.removesuffix('@2'), REVISION))
    with fixture_server(handler) as server:
        config = tmp_path / 'configuration.json'
        config.write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': server.url, 'project': 'p'}))

        def call(asset, *flags):
            sent.clear()
            try: code = cli.entrypoint(['rules', 'show', asset + '@2', '--configuration', str(config), *flags]) or 0
            except SystemExit as stopped: code = stopped.code
            out = capsys.readouterr()
            return code, out.out, out.err, list(sent)
        yield call


@pytest.mark.parametrize('asset', list(SHOWN))
def test_show_prints_the_summary_and_the_servers_lines(show, asset):
    """Mutations: a state counted under the wrong table entry (passed as failed) -> passed, not-applicable, unworded red
    (and the offline tops run); the item sent as named instead of resolved -> every case red."""
    code, out, err, sent = show(asset)
    assert (code, out, err) == (0, SHOWN[asset], '')
    assert sent == [(['rule-results', 'get'], {'project_id': 'p', 'asset_id': asset, 'revision': REVISION})]


def test_show_json_prints_the_answer_as_received(show):
    code, out, _, _ = show('failed', '--json')
    assert (code, json.loads(out)) == (0, {'asset_id': 'failed', 'revision': REVISION, **ANSWERS['failed']})


def test_show_of_a_version_you_cannot_read_is_not_found(show):
    code, out, err, _ = show('gone')
    assert (code, out, err) == (4, '', 'The requested application data is unavailable or not permitted.\n')


def gr_as_csv(tmp_path):
    path = tmp_path / 'gr.csv'
    shutil.copyfile(str(RUN.joinpath('las-gr.las')), path)
    return path


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """No configuration file in the working folder and no socket can be opened."""
    def refused(*args, **kwargs): raise AssertionError('rules run opened a socket')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(socket, 'socket', refused)
    monkeypatch.setattr(socket, 'create_connection', refused)


def test_run_on_a_las_file_named_csv_equals_the_oracle(tmp_path, offline, capsys):
    """Mutations: --kind taken from the file's extension -> a csv kind, red; `run` dispatched after `_load()` and the
    configuration -> no configuration file, red."""
    cli.main(['rules', 'run', str(gr_as_csv(tmp_path)), '--kind', 'las2/1', '--json'])
    assert capsys.readouterr().out.rstrip('\n').encode() == engine.canonical(GR_BLOCK)
    cli.main(['rules', 'run', str(gr_as_csv(tmp_path)), '--kind', 'las2/1'])
    assert capsys.readouterr().out == GR_TEXT


def test_run_words_each_state_as_the_server_does(tmp_path, offline, capsys):
    """A tops file: one failed line and the offline rule's reason. Mutation: a reason word from the wrong table entry
    -> red."""
    cli.main(['rules', 'run', str(RUN.joinpath('tops.csv')), '--kind', 'well-tops-csv/1', '--declared', '{"depth_unit": "m"}'])
    assert capsys.readouterr().out == ("Checked by 2 rules: 0 passed, 1 failed, 1 did not apply.\n"
                                       "Each top on the wellbore's path: did not apply; it runs only on the server.\n"
                                       "Each top named once: 3 tops repeat an earlier top's name, the first at row 3.\n")


@pytest.mark.parametrize('reason,said', [('no-column', 'it needs a column this file does not have'), ('no-context', 'it needs other data in the project'),
                                         ('offline', 'it runs only on the server'), (None, None)])
def test_each_reason_has_its_own_words(reason, said):
    rule = {'title': 'A rule'}
    assert rule_results.sentence(rule, result('x/1', 'not-applicable', reason)) == ('A rule: did not apply; %s.' % said if said else 'A rule: did not apply.')


def test_run_refuses_declarations_that_are_not_an_object(tmp_path, offline, capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.entrypoint(['rules', 'run', str(gr_as_csv(tmp_path)), '--kind', 'las2/1', '--declared', '[1]'])
    assert (stopped.value.code, capsys.readouterr().err) == (1, '--declared takes a JSON object, such as {"depth_unit": "m"}.\n')
