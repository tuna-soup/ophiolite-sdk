"""adhoc-e121-words (E121 O2, O4 and the depth-basis reason): a refused tolerance says the server's reason with both
units, a run whose --output folder has no parent folder is refused by name before anything runs, and a saved
comparison not compared for its depth basis reads the Platform's sentence."""
import pytest

from ophiolite import checks, cli
from ophiolite.errors import Refused
from test_cli_checks import Recorded, refusal

UNITS = 'The allowed difference is in ft; this result is compared in m, so state it in m.'


def test_a_refused_tolerance_says_the_servers_reason_with_both_units():
    client = Recorded({'compare': refusal(400, 'tolerance', UNITS)})
    with pytest.raises(Exception) as caught:
        client.check_compare('a1', 'r1', b'name,md\nDCC,1\n', tolerance={'kind': 'absolute', 'value': 0, 'unit': 'ft'})
    assert str(caught.value) == 'Not compared: the allowed difference is in ft; this result is compared in m, so state it in m.'
    assert checks.field(caught.value) == 'tolerance'
    client = Recorded({'compare': refusal(400, 'size', 'server words')})  # other fields keep this command's sentences
    with pytest.raises(Exception) as caught: client.check_compare('a1', 'r1', b'x')
    assert str(caught.value) == checks.COMPARE_REFUSED['size']


def test_a_record_not_compared_for_its_depth_basis_reads_the_platform_sentence():
    record = {'outcome': 'not_compared', 'reason': 'depth_basis_unknown', 'tolerance': None}
    assert checks.outcome_lines(record) == ["Only tops declared same-as-log, measured along the log's depths, are compared today."]
    assert checks.FILE_REASON['depth_basis_unknown'] == "Not compared: only tops declared same-as-log, measured along the log's depths, are compared today."


class Untouched:
    """A client any call on which fails the test: the refusal comes before the project is asked anything."""
    def __getattr__(self, name): pytest.fail('the client was asked %s' % name)


@pytest.mark.parametrize('argv, handler', [
    (['residuals', 'run', 'Residual at wells', '--selection', 'S', '--surface', 'G', '--formation', 'DCC', '--output', '{out}'],
     lambda args: cli._residuals(args, Untouched())),
    (['procedures', 'run', '--from-project', 'depth-shift', '--output', '{out}'], lambda args: cli._catalogue(args, Untouched())),
    (['procedures', 'again', 'a1', '--revision', 'r1', '--output', '{out}'], lambda args: cli._catalogue(args, Untouched())),
    (['procedures', 'run', '{folder}', '--output', '{out}'], cli._procedures),
], ids=['residuals', 'from-project', 'again', 'local'])
def test_an_output_in_a_missing_folder_is_refused_by_name_before_anything_runs(tmp_path, argv, handler):
    missing = tmp_path / 'runs'
    args = cli.parser().parse_args([w.format(out=missing / 'out', folder=tmp_path) for w in argv])
    with pytest.raises(Refused) as caught: handler(args)
    assert str(caught.value) == 'Not run: the folder %s for --output does not exist; create it first.' % missing
    assert not missing.exists()
