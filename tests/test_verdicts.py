"""E132 s0, offline: what the SDK sends to record and list verdicts. Literals by hand; the HTTP side is the Platform's
test_verdict_stub.py. Mutation: treat UNSET as None (always send `supersedes`) -> the omitted-body case is red."""
from unittest.mock import ANY

import pytest

from ophiolite import cli, verdicts
from ophiolite.errors import Busy, Refused

REVISION = 'b' * 64


class Fake(verdicts.VerdictClient):
    def __init__(self):
        self.sent = []

    def _post(self, area, operation, body, retry=False):
        self.sent.append((area, operation, body, retry))
        return {}


def test_a_verdict_sends_only_what_the_caller_gave():
    fake = Fake()
    fake.record_verdict('r1', REVISION, 'accepted', command_id='c1')
    assert fake.sent == [('verdicts', 'record', {'asset_id': 'r1', 'revision': REVISION, 'verdict': 'accepted', 'command_id': 'c1'}, True)]


def test_supersedes_left_out_null_and_an_id_are_three_bodies():
    fake = Fake()
    fake.record_verdict('r1', REVISION, 'accepted', command_id='c1')
    fake.record_verdict('r1', REVISION, 'accepted', supersedes=None, command_id='c2')
    fake.record_verdict('r1', REVISION, 'accepted', supersedes='verdict-' + '0' * 32, command_id='c3')
    bodies = [body for _, _, body, _ in fake.sent]
    assert 'supersedes' not in bodies[0]
    assert bodies[1]['supersedes'] is None
    assert bodies[2]['supersedes'] == 'verdict-' + '0' * 32


def test_a_rejection_carries_its_reason_verbatim_and_what_it_was_judged_against():
    fake = Fake()
    fake.record_verdict('r1', REVISION, 'rejected', reason='  tops differ\nfrom the published log ',
                        against=verdicts.against_outcome('o1', 2), command_id='c1')
    fake.record_verdict('r1', REVISION, 'accepted', against=verdicts.against_check('c' * 64), command_id='c2')
    assert fake.sent[0][2] == {'asset_id': 'r1', 'revision': REVISION, 'verdict': 'rejected', 'command_id': 'c1',
                               'reason': '  tops differ\nfrom the published log ', 'against': {'kind': 'outcome', 'outcome_id': 'o1', 'version': 2}}
    assert fake.sent[1][2]['against'] == {'kind': 'check', 'key': 'c' * 64}


def test_each_call_has_its_own_command_id_unless_given():
    fake = Fake()
    fake.record_verdict('r1', REVISION, 'accepted')
    fake.record_verdict('r1', REVISION, 'accepted')
    first, second = (body['command_id'] for _, _, body, _ in fake.sent)
    assert first != second and first.startswith('verdict-')


def test_the_list_names_the_exact_version():
    fake = Fake()
    fake.verdicts('r1', REVISION)
    assert fake.sent == [('verdicts', 'list', {'asset_id': 'r1', 'revision': REVISION}, True)]


# --- the command line: `ophiolite verdicts record|list ITEM`, resolved by result_version -------------------------------

class Resolving(Fake):
    """result_version as `outcomes states` uses it; an item it cannot resolve keeps its refusal."""
    def result_version(self, text):
        if text != 'Residuals DCC@2': raise Refused('This project has no item named "%s".' % text)
        return 'r1', REVISION

    def outcome_named(self, label):
        if label != 'Tops within 5 m': raise Refused('This project has no outcome named "%s".' % label)
        return {'outcome_id': 'o1'}

    def _post(self, area, operation, body, retry=False):
        super()._post(area, operation, body, retry)
        return {'verdicts': []} if operation == 'list' else {'line': 'Accepted by Anna, 30 October 2026'}


def command(*argv):
    fake = Resolving()
    cli._verdicts(cli.parser().parse_args(['verdicts', *argv]), fake)
    return fake.sent


def test_the_command_sends_the_resolved_version_and_only_what_was_named(capsys):
    assert command('record', 'Residuals DCC@2', 'accepted') == [('verdicts', 'record', {'asset_id': 'r1', 'revision': REVISION, 'verdict': 'accepted',
                                                                                          'command_id': ANY}, True)]
    assert capsys.readouterr().out == 'Accepted by Anna, 30 October 2026\n'
    body = command('record', 'Residuals DCC@2', 'rejected', '--reason', 'tops differ', '--against-outcome', 'Tops within 5 m@1', '--expect-first')[0][2]
    assert (body['reason'], body['against'], body['supersedes']) == ('tops differ', {'kind': 'outcome', 'outcome_id': 'o1', 'version': 1}, None)
    body = command('record', 'Residuals DCC@2', 'accepted', '--against-check', 'c' * 64, '--supersedes', 'verdict-' + '2' * 32)[0][2]
    assert (body['against'], body['supersedes']) == ({'kind': 'check', 'key': 'c' * 64}, 'verdict-' + '2' * 32)
    assert command('list', 'Residuals DCC@2') == [('verdicts', 'list', {'asset_id': 'r1', 'revision': REVISION}, True)]
    assert capsys.readouterr().out.endswith('No verdicts on this version yet.\n')


class Unavailable503(Resolving):
    def _post(self, area, operation, body, retry=False):
        raise Busy('The service is busy.', '', status=503, code='UNAVAILABLE', server_message=self.said)


@pytest.mark.parametrize('said,printed', [('Recording verdicts is not available on this deployment yet.', 'Recording verdicts is not available on this deployment yet.'),
                                          (None, 'The service is busy.')], ids=['server-sentence', 'no-sentence'])
def test_a_503_prints_the_servers_own_sentence_with_the_busy_exit_code(said, printed):
    """Mutation: drop the rewrap in `_verdicts` -> the generic busy sentence -> the first case is red."""
    fake = Unavailable503()
    fake.said = said
    for argv in (('record', 'Residuals DCC@2', 'accepted'), ('list', 'Residuals DCC@2')):
        with pytest.raises(Busy) as caught:
            cli._verdicts(cli.parser().parse_args(['verdicts', *argv]), fake)
        assert (caught.value.message, cli.exit_code(caught.value)) == (printed, cli.EXIT['busy'])


@pytest.mark.parametrize('argv', [('record', 'Unknown', 'accepted'), ('list', 'Unknown'),
                                  ('record', 'Residuals DCC@2', 'accepted', '--against-outcome', 'Tops within 9 m@1'),
                                  ('record', 'Residuals DCC@2', 'accepted', '--against-outcome', 'Tops within 5 m')])
def test_an_unresolved_item_or_outcome_keeps_its_refusal_and_sends_nothing(argv):
    fake = Resolving()
    with pytest.raises(Refused):
        cli._verdicts(cli.parser().parse_args(['verdicts', *argv]), fake)
    assert fake.sent == []
