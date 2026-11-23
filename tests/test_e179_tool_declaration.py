"""E179 s1 C5: an outcome judged by a check tool, declared from the SDK and the command line. The catalogue and the
route answers are written by hand in the Platform's shapes (the gateway's test_e179_declare_tool proves the declaration
against the real route); the words are literals.

Mutations (break -> FAIL, restore -> PASS; recorded in the lane's logs/c5-mutations.txt):
a. the version filter dropped from `OutcomeClient.tool_declaration` -> test 1 (ambiguous, and the wrong digest);
b. the inputs taken from every manifest input, not the version ones -> test 1;
c. the --tool/--tolerance exclusion dropped -> test 2 sends a declaration."""
import contextlib
import io

import pytest

from ophiolite import cli
from ophiolite.errors import Refused
from ophiolite.outcomes import OutcomeClient

DIGEST = 'sha256:' + '1' * 64
OTHER = 'sha256:' + '2' * 64
MANIFEST = {'label': 'Residuals within the limit', 'inputs': [
    {'slot': 'residuals', 'class': 'result', 'kinds': ['well-residual/1']},
    {'slot': 'tops', 'class': 'version', 'kinds': ['well-tops-csv/1'], 'cardinality': 'one'},
    {'slot': 'grid', 'class': 'version', 'kinds': ['esri-ascii-grid/1', 'well-tops-csv/1'], 'cardinality': 'one'}]}
DECLARED = {'schema': 'ophiolite.outcome/1', 'label': 'Residuals within our limit', 'kind': 'well-residual/1',
            'rule': {'name': 'tool-check/1', 'tool': {'digest': DIGEST}, 'settings': {'limit': 5, 'note': 'tops only', 'scale': 0.5}},
            'inputs': ['esri-ascii-grid/1', 'well-tops-csv/1'], 'destination': {'procedure': 'tops-to-team-database', 'label': 'Team database'}}
WORDS = {'kind': 'residual results', 'rule': 'judged by Residuals within the limit version 1', 'destination': 'Team database'}


class Catalogue(OutcomeClient):
    """The catalogue lists `versions`; every request is kept, and `outcomes/declare` answers the declared outcome."""

    def __init__(self, versions):
        self.versions, self.sent = versions, []

    def procedure_list(self, name=None):
        self.sent.append(('procedures', 'list', name))
        return [v for v in self.versions if name is None or v['name'] == name]

    def procedure_get(self, digest):
        self.sent.append(('procedures', 'get', digest))
        return {'digest': digest, 'manifest': MANIFEST}

    def _post(self, area, operation, body, retry=False):
        self.sent.append((area, operation, body))
        return {'outcome_id': 'o1', 'label': body['declaration']['label'], 'state': 'enabled', 'version': 1, 'words': WORDS}


def listed(version, digest=DIGEST, name='residual-limit'):
    return {'digest': digest, 'name': name, 'version': version, 'label': MANIFEST['label']}


def run(client, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): payload = cli._outcomes(cli.parser().parse_args(['outcomes', 'declare', *argv]), client)
    return out.getvalue().strip(), payload


TOOL = ['--label', 'Residuals within our limit', '--tool', 'residual-limit', '--tool-version', '1', '--setting', 'limit=5',
        '--setting', 'note=tops only', '--setting', 'scale=0.5', '--procedure', 'tops-to-team-database', '--destination', 'Team database']


# --- 1: the SDK resolves the digest, and refuses before sending ------------------------------------------------------

def test_1_the_version_resolves_to_its_digest_and_the_inputs_the_tool_reads():
    client = Catalogue([listed(1), listed(2, OTHER)])
    assert client.tool_declaration('Residuals within our limit', 'residual-limit', 1, {'limit': 5, 'note': 'tops only', 'scale': 0.5},
                                   'tops-to-team-database', 'Team database') == DECLARED
    assert client.sent == [('procedures', 'list', 'residual-limit'), ('procedures', 'get', DIGEST)]


@pytest.mark.parametrize('versions, said', [
    ([listed(2, OTHER)], 'This project lists no version 1 of the tool "residual-limit".'),
    ([listed(1), listed(1, OTHER)], 'This project lists more than one version 1 of the tool "residual-limit"; declare it through the API by its digest.')])
def test_1_an_unknown_or_ambiguous_version_is_refused_before_anything_is_sent(versions, said):
    client = Catalogue(versions)
    with pytest.raises(Refused) as refused: client.tool_declaration('L', 'residual-limit', 1, {}, 'p', 'D')
    assert str(refused.value) == said
    assert client.sent == [('procedures', 'list', 'residual-limit')]


# --- 2: the command line ----------------------------------------------------------------------------------------------

def test_2_the_command_line_declares_the_tool_rule_with_typed_settings():
    client = Catalogue([listed(1)])
    text, payload = run(client, *TOOL)
    assert client.sent[-1] == ('outcomes', 'declare', {'command_id': client.sent[-1][2]['command_id'], 'declaration': DECLARED})
    assert text == 'Declared "Residuals within our limit" (enabled, version 1): residual results, judged by Residuals within the limit version 1; delivered to Team database.'


@pytest.mark.parametrize('extra, said', [
    (['--tolerance', '5'], 'Give --tool or --tolerance, not both.'),
    (['--setting', 'limit'], 'A setting is KEY=VALUE, such as limit=5.')])
def test_2_a_tool_declaration_that_contradicts_itself_is_refused_before_anything_is_sent(extra, said):
    client = Catalogue([listed(1)])
    with pytest.raises(Refused) as refused: run(client, *TOOL, *extra)
    assert (str(refused.value), client.sent) == (said, [])


@pytest.mark.parametrize('argv, said', [
    (['--tool', 'residual-limit'], '--tool needs --tool-version.'),
    (['--tool-version', '1'], 'Give --tolerance, or --tool with --tool-version (and --kind and --setting).'),
    ([], 'Give --tolerance, or --tool with --tool-version (and --kind and --setting).')])
def test_2_a_declaration_names_exactly_one_rule(argv, said):
    client = Catalogue([listed(1)])
    with pytest.raises(Refused) as refused:
        run(client, '--label', 'L', '--procedure', 'tops-to-team-database', '--destination', 'Team database', *argv)
    assert (str(refused.value), client.sent) == (said, [])
