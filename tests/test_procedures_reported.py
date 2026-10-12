"""E106 C6, offline: the pieces of publishing a reported run that need no server. The command id of an output, the
method it is published with and the header that names the run are the server's rules, written out here as literals;
a "Same result" answer must name the earlier result it was compared with; the sentences are frozen."""
import hashlib

import pytest

from ophiolite import procedures
from ophiolite import publish as planning
from ophiolite.errors import VerificationFailed
from ophiolite.models.api import PublicationReceipt
from ophiolite.writers import WrittenOriginal

RUN = 'e' * 64
RAW = b'name,md\nTop Chalk,1003\n'
SHA = hashlib.sha256(RAW).hexdigest()
PROCEDURE = {'name': 'depth-shift', 'label': 'Shift tops by a fixed depth', 'version': 3, 'digest': 'd' * 64}
METHOD = procedures.method_of(PROCEDURE, {'shift': 2.5})
PARENT = {'asset_id': 'tops-a', 'revision': 'a' * 64}


def test_an_outputs_command_id_and_method_are_the_servers_rules():
    assert procedures.output_command(RUN, 'shifted') == hashlib.sha256(('e' * 64 + '/shifted').encode()).hexdigest()
    assert METHOD == {'name': 'Shift tops by a fixed depth', 'declared': True, 'library': 'depth-shift', 'version': '3', 'parameters': {'shift': 2.5},
                      'script_sha256': 'd' * 64}


def request():
    return planning.derive_request('p', WrittenOriginal(RAW, 'well-tops-csv/1', {'depth_unit': 'm', 'depth_basis': 'same-as-log'}), name='Chalk', from_=[PARENT],
                                   method=METHOD, command_id=procedures.output_command(RUN, 'shifted'), procedure={'id': RUN, 'role': 'shifted'})[0]


def receipt(asset, revision, outcome=None):
    return PublicationReceipt.model_validate({'asset_id': asset, 'revision': revision, 'revision_number': 1, 'profile': 'well-tops-csv/1',
                                              'derived_from': [{'authority': 'ophiolite:derived', 'key': 'tops-a', 'revision': 'a' * 64, 'profile': 'well-tops-csv/1'}], 'method': METHOD,
                                              'command_id': procedures.output_command(RUN, 'shifted'), 'outcome': outcome})


def test_the_header_names_the_run_and_role_and_nothing_else_changes():
    body = request()
    assert body['run'] == {'id': RUN, 'role': 'shifted'}
    plain = planning.derive_request('p', WrittenOriginal(RAW, 'well-tops-csv/1', {'depth_unit': 'm', 'depth_basis': 'same-as-log'}), name='Chalk', from_=[PARENT],
                                    method=METHOD, command_id=procedures.output_command(RUN, 'shifted'))[0]
    assert 'run' not in plain and {k: v for k, v in body.items() if k != 'run'} == plain


def test_a_same_result_answer_must_name_the_earlier_result_it_was_compared_with():
    body = request()
    earlier = {'asset_id': 'chalk-1', 'revision': 'b' * 64}
    same = {'outcome': 'same', 'sentence': 'Same result', 'earlier': earlier}
    assert planning.verify_run_output(body, receipt('chalk-1', 'b' * 64, same)).asset_id == 'chalk-1'
    with pytest.raises(VerificationFailed, match='another result'): planning.verify_run_output(body, receipt('chalk-2', 'b' * 64, same))
    with pytest.raises(VerificationFailed, match='another result'): planning.verify_run_output(body, receipt('chalk-1', 'b' * 64, {**same, 'earlier': None}))
    published = {'outcome': 'different', 'sentence': 'Different result: The values differ: 1 of 4', 'earlier': earlier}
    assert planning.verify_run_output(body, receipt('chalk-3', SHA, published)).asset_id == 'chalk-3'
    with pytest.raises(VerificationFailed, match='different file'): planning.verify_run_output(body, receipt('chalk-3', 'c' * 64, published))  # a new result is this file


def test_a_receipt_without_an_outcome_dumps_and_prints_as_before():
    plain = receipt('chalk-1', SHA)
    assert 'outcome' not in plain.model_dump() and 'outcome' not in repr(plain)
    assert receipt('chalk-1', SHA, {'outcome': 'no-earlier', 'sentence': 'No earlier result you can read to compare with', 'earlier': None}).model_dump()['outcome']['outcome'] == 'no-earlier'


@pytest.mark.parametrize('outcome, earlier, sentence', [
    (None, None, 'Published Chalk (Well tops (CSV)), made with Shift tops by a fixed depth version 3 on your computer.'),
    ('same', 'Chalk, version 1', 'Same result: Chalk, version 1. Nothing was published.'),
    ('same-earlier', None, 'Same result, earlier procedure version: Chalk. Nothing was published.'),
    ('not-compared', None, 'Not compared: Well tops (CSV) hold columns Ophiolite does not read; compare them yourself.: published Chalk (Well tops (CSV)) as a new private '
                           'result, made with Shift tops by a fixed depth version 3 on your computer.'),
])
def test_the_sentences_of_each_outcome(outcome, earlier, sentence):
    words = {'same': 'Same result', 'same-earlier': 'Same result, earlier procedure version',
             'not-compared': 'Not compared: Well tops (CSV) hold columns Ophiolite does not read; compare them yourself.'}
    given = {'outcome': {'outcome': outcome, 'sentence': words[outcome]}} if outcome else {}
    assert procedures._outcome_words(given, 'Chalk', 'well-tops-csv/1', {'procedure': PROCEDURE}, earlier)['sentence'] == sentence


def test_a_project_input_names_one_exact_version():
    assert procedures.PROJECT_INPUT.match('@chalk-1:' + 'b' * 64).groups() == ('chalk-1', 'b' * 64)
    for text in ('@chalk-1', '@chalk-1:', '@:abc', 'chalk-1:abc', '@a:b:c', '@a b:c'):
        assert procedures.PROJECT_INPUT.match(text) is None, text
