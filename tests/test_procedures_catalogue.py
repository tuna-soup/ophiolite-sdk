"""E105b C5, offline: `run(expected_digest=)` runs only exactly that version, and a catalogue refusal keeps the
server's sentence and its closed reason (the transport reads `procedure-refused`)."""
import httpx
import pytest

from ophiolite import application_transport, procedures
from ophiolite.errors import IntegrityConflict, Refused
from tests.test_procedures_run import SHIFTED, depth_shift, refused, run_shift

DEPTH_SHIFT = procedures.digest(procedures.CONTRACT.parent / 'fixtures/bundles/depth-shift')


def test_an_expected_digest_runs_exactly_that_version_and_nothing_else(tmp_path):
    folder = depth_shift(tmp_path)
    assert procedures.digest(folder) == DEPTH_SHIFT
    run_shift(tmp_path, folder, expected_digest=DEPTH_SHIFT)
    assert (tmp_path / 'out/shifted.csv').read_bytes() == SHIFTED
    error = refused('changed-before-run', lambda: run_shift(tmp_path, folder, output='other', expected_digest='0' * 64))
    assert str(error) == "Not run: the procedure's files changed after they were checked; nothing ran. Run it again."
    assert error.details == {'expected': '0' * 64, 'found': DEPTH_SHIFT} and not (tmp_path / 'other').exists()


def answer(status, body):
    return httpx.Response(status, json=body, request=httpx.Request('POST', 'https://example.test/x'))


def test_a_catalogue_refusal_keeps_the_servers_sentence_reason_rule_and_path():
    sentence = 'A version with this number is already registered in this project; register a higher version.'
    with pytest.raises(IntegrityConflict) as caught:
        application_transport.status(answer(409, {'code': 'procedure-refused', 'reason': 'version-not-higher', 'message': sentence, 'error': sentence}), 'register')
    assert str(caught.value) == sentence and caught.value.details == {'reason': 'version-not-higher'} and caught.value.code == 'procedure-refused'
    with pytest.raises(Refused) as caught:
        application_transport.status(answer(400, {'code': 'procedure-refused', 'reason': 'invalid', 'rule': 'label-snake', 'path': '/settings/0/label',
                                                  'message': 'A label is words.'}), 'register')
    assert (str(caught.value), caught.value.details) == ('A label is words.', {'reason': 'invalid', 'rule': 'label-snake', 'path': '/settings/0/label'})
    with pytest.raises(IntegrityConflict) as caught:  # another code: its reason is not read
        application_transport.status(answer(409, {'code': 'conflict', 'reason': 'version-not-higher', 'message': 'Other.'}), 'register')
    assert caught.value.details == {} and str(caught.value) == 'The request conflicts with the stored result.'
