"""E109 slice 0 (S0.4): the SDK side of the send-procedure contract. `procedures validate` names the destination and
the delivery (C1 test 7, a literal); running a send procedure locally is still `later-release`; the delivery payload
is the packaged contract's, closed, with the same fixtures as the server; `ophiolite deliver --set-aside` (slice 2)
refuses in words, reading and writing nothing; the journey case list (deliver_cases.py) is well formed. Delivering
itself is slice 1's (test_deliver.py, gateway/test_deliver_journey.py)."""
import json
from pathlib import Path

import pydantic
import pytest

import ophiolite
from ophiolite import cli, procedures
from ophiolite.models import delivery
from deliver_cases import CASES, SLICES

PACKAGE = Path(ophiolite.__file__).resolve().parent
FIXTURES = PACKAGE / 'contracts/procedures/v1/fixtures'
EXPECTED = json.loads((FIXTURES / 'expected.json').read_text())
VALID = EXPECTED['deliveries']['valid']
SENTENCE = "Delivering to a team's system is not available on this deployment yet."


def folder_with(tmp_path, name, raw, members):
    folder = tmp_path / name
    for member in members:
        target = folder / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw if member == 'procedure.json' else b'')
    return folder


def cli_run(capsys, argv):
    with pytest.raises(SystemExit) as stop: cli.main(argv)
    captured = capsys.readouterr()
    return stop.value.code, captured.out, captured.err


def send_folder(tmp_path, name='send-to-system'):
    raw = (FIXTURES / 'valid' / f'{name}.json').read_bytes()
    return folder_with(tmp_path, name, raw, EXPECTED['members']['send-to-system'])


# ---------------------------------------------------------------- C1 test 7: what validate says

def test_procedures_validate_names_the_destination_and_the_delivery(tmp_path, capsys):
    folder = send_folder(tmp_path)
    answer = cli.main(['procedures', 'validate', str(folder)])
    assert capsys.readouterr().out == 'Valid: Tops to team DB, version 1. It reads Well tops (CSV) and Team tops database and makes a delivery.\n'
    assert (answer['valid'], answer['rules_version'], answer['name'], answer['version']) == (True, '1.3.0', 'tops-to-team-db', 1)


@pytest.mark.parametrize('name', ['send-two-systems', 'reconcile-bad-entry'])
def test_a_send_with_two_systems_or_a_bad_reconcile_is_refused_in_words(tmp_path, capsys, name):
    case = EXPECTED['cases'][name]
    folder = folder_with(tmp_path, name, (FIXTURES / 'invalid' / f'{name}.json').read_bytes(), EXPECTED['members'][case['base']])
    code, out, err = cli_run(capsys, ['procedures', 'validate', str(folder)])
    assert (code, out) == (cli.EXIT['refused'], case['sentence'] + '\n')


def test_running_a_send_procedure_locally_is_still_a_later_release(tmp_path):
    folder = send_folder(tmp_path)
    with pytest.raises(procedures.NotRun) as error: procedures.run(folder, tmp_path / 'out')
    assert (error.value.code, str(error.value)) == ('later-release', 'Not run: running a send procedure comes with a later release.')
    assert not (tmp_path / 'out').exists()


# ---------------------------------------------------------------- the payload: the packaged contract's, closed

def test_the_delivery_payload_is_the_contract_s_and_closed():
    assert delivery.CONTRACT == PACKAGE / 'contracts/procedures/v1/delivery.py'
    assert (delivery.contract().SCHEMA, delivery.contract().STATES, delivery.PROFILE, delivery.KIND) == (
        'ophiolite.delivery/1', ('confirmed', 'not-sent', 'unknown'), 'procedure-delivery/1', 'delivery.reported')
    assert delivery.verdict(VALID) == {'valid': True, 'rules_version': '1.3.0'}
    assert delivery.Delivery.model_validate(VALID).model_dump() == VALID
    for name, case in EXPECTED['deliveries']['cases'].items():
        raw = json.loads((FIXTURES / 'invalid' / f'{name}.json').read_text())
        assert {k: delivery.verdict(raw)[k] for k in ('valid', 'code', 'field', 'sentence')} == {'valid': False, **case}, name
        with pytest.raises(pydantic.ValidationError) as error: delivery.Delivery.model_validate(raw)
        assert case['sentence'] in str(error.value), name
    for change in ({'items': 1000001}, {'items': True}, {'items': 2.5}, {'items': '3'}, {'state': 'refused'}, {'delivery_id': 'x'}):
        with pytest.raises(pydantic.ValidationError): delivery.Delivery.model_validate({**VALID, **change})
    with pytest.raises(pydantic.ValidationError): delivery.Delivery.model_validate({k: v for k, v in VALID.items() if k != 'items'})


def test_the_report_is_closed_and_names_no_configuration():
    body = {'project_id': 'p', 'event_id': 'delivery-report-0000000001',
            'refs': [{'project_id': 'p', 'asset_id': 'tops', 'revision': 'a' * 64}],
            'procedure': {'digest': 'b' * 64, 'label': 'Tops to team DB', 'version': 1},
            'destination': 'Team tops database', 'delivery': VALID}
    assert delivery.DeliveryObservation.model_validate(body).model_dump()['profile'] == 'procedure-delivery/1'
    for extra in ({'configuration': {'host': 'db'}}, {'reason': 'x'}, {'profile': 'procedure-delivery/2'}, {'refs': []}):
        with pytest.raises(pydantic.ValidationError): delivery.DeliveryObservation.model_validate({**body, **extra})


# ---------------------------------------------------------------- the stub: refused in words, nothing written

def test_deliver_passes_set_aside_to_the_client_and_reads_nothing_itself(tmp_path, capsys, monkeypatch):
    # Slice 2: `--set-aside` is the client's (test_deliver.py: the outcome stays unknown in the project, this folder is
    # cleared); the command only passes it on, and no configuration file is read for it.
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'team-db.json').write_text('{"host": "db.example", "database": "team", "schema": "team"}')
    before = sorted(p.name for p in tmp_path.rglob('*'))
    seen = {}
    class Client:
        def deliver(self, name, **given):
            seen.update(given, name=name)
            return {'sentence': 'Set aside.', 'delivery_id': 'd', 'state': 'unknown', 'items': 0, 'destination': 'Team tops database', 'reported': True}
    args = cli.parser().parse_args(['deliver', 'Tops to team DB', '--system', 'db=team-db.json', '--item', 'tops=Tops@3', '--set-aside'])
    assert cli._deliver(args, Client())['state'] == 'unknown' and capsys.readouterr().out == 'Set aside.\n'
    assert (seen['name'], seen['set_aside'], seen['wait']) == ('Tops to team DB', True, 0)
    assert sorted(p.name for p in tmp_path.rglob('*')) == before  # no .ophiolite-held, no pending entry written by the command
    assert procedures.SENTENCES['not-available-yet'] == SENTENCE != procedures.SENTENCES['later-release']  # slice 0's code stays defined
    assert 'set-aside-later' not in procedures.SENTENCES


# ---------------------------------------------------------------- the journey case list (6-7): a smoke check only

def test_the_case_list_names_a_slice_for_every_case_and_a_test_for_every_merged_one():
    ids = [case[1] for case in CASES]
    assert len(ids) == len(set(ids)) and {case[0] for case in CASES} == set(SLICES)
    here = Path(__file__).parent
    for slice_, name, words, test in CASES:
        assert words and (test is not None) == (slice_ <= 2), name  # slices 0 to 2 are proved; 3 names its tests when it lands
        if test:
            module, function = test.split('::')
            assert ('def %s(' % function) in (here / module).read_text(), test
