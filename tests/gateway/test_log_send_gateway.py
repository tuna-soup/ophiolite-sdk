"""E188 C3 (T3.1, T3.2): the next version of an uploaded LAS log, sent as the OpendTect connector's `send log` sends it,
on the in-process gateway, read back in E183's well log form.

The file sent is the exact text `ophiolite_opendtect.logs.log_las` writes for the charter's synthetic samples
(`ophiolite-opendtect/tests/test_log_send.py` asserts the same literal byte for byte; this suite does not import the
connector). Every value is SYNTHETIC; every expected value is typed here."""
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite.client import WellLogSet

FORM = 'ophiolite.well-log-curve/1'
WELL = 'SYNTHETIC-W1'
DECLARED = {'well': WELL, 'depth_kind': 'MD', 'depth_datum': 'KB'}
SOURCE = {'system': 'application:opendtect', 'instance': 'synthetic-survey', 'container': '100050.1', 'id': '100050.1/GR'}


def las(rows):
    return ('~Version Information\n VERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0\n WRAP.   NO  : ONE LINE PER DEPTH STEP\n'
            '~Well Information\n STRT.M  1000.0 : START DEPTH\n STOP.M  1001.5 : STOP DEPTH\n STEP.M  0.5 : STEP\n'
            ' NULL.   -999.25 : NULL VALUE\n WELL.   SYNTHETIC-W1 : WELL\n~Curve Information\n DEPT.M     : MEASURED DEPTH\n'
            ' GR.API     : GAMMA RAY\n~A\n' + rows).encode()


FIRST = las('1000.0 1.0\n1000.5 2.0\n1001.0 3.0\n1001.5 4.0\n')
SENT = las('1000.0 42.5\n1000.5 -999.25\n1001.0 0.0\n1001.5 1234.5677490234375\n')  # log_las's text, typed here


@pytest.fixture
def got(web, tmp_path):
    """Alice's upload (version 1, declared), got into two work folders; the first placed it as `<well>/GR`."""
    alice = client(web, 'alice', 'delegate')
    info = alice.upload_las(FIRST, curve_declaration=DECLARED, command_id='e188-first', name='GR', attribution='Synthetic',
                            audience=[], rights_confirmed=True)
    a, b = alice.exchange(tmp_path / 'a'), alice.exchange(tmp_path / 'b')
    for ex, out in ((a, 'pa'), (b, 'pb')):
        ex.check()
        ex.fetch(info.asset_id, output=tmp_path / out, curves=['GR']).confirm(applied_to='%s/GR' % WELL)
    return alice, a, b, info.asset_id


def send(ex, item):
    held = ex.held()[item]
    return ex.send(SENT, name='GR', profile='las2/1', how='From OpendTect, survey synthetic-survey', based_on=[item], of=item,
                   expected=held['revision'], rights_confirmed=True, curve_declaration=DECLARED, source=SOURCE)


def test_t3_1_the_next_version_reads_back_in_the_well_log_form_exactly(got):
    """Acceptance 1 and 5 (the notebook half). Mutation: C1's forwarding of the declaration removed in
    ClientTransport.publish -> version 2 has no declaration and the form read is refused (red)."""
    alice, a, _, item = got
    done = send(a, item)
    assert (done.outcome, done.sentence) == ('sent-version', 'Sent GR as version 2. Version 1 is kept.')
    entry = a.held()[item]
    assert (entry['number'], entry['applied_to']) == (2, '%s/GR' % WELL)
    log = alice.read(item, entry['revision'], ['GR'], form=FORM)
    assert isinstance(log, WellLogSet)
    curve = log.curves[0]
    assert (curve.well, curve.depth_kind, curve.depth_datum, curve.depth_unit, curve.unit) == (WELL, 'MD', 'KB', 'M', 'API')
    assert curve.depth == [1000.0, 1000.5, 1001.0, 1001.5]
    assert curve.values == [42.5, None, 0.0, 1234.5677490234375]
    plain = alice.read(item, entry['revision'], ['GR']).curves[0]
    assert list(plain.axis) == [1000.0, 1000.5, 1001.0, 1001.5]
    assert alice.provenance(item, entry['revision']).words.startswith('From opendtect, ')


def test_t3_2_a_second_folder_on_version_one_is_behind_and_is_refused(got):
    """Acceptance 2 (E171): the other folder's holding is one version behind; its own send of version 1's successor is
    the core's stale sentence."""
    alice, a, b, item = got
    send(a, item)
    rows = [r for r in alice.holders(item)['rows'] if r.get('state') == 'behind']
    assert [r['behind']['count'] for r in rows] == [1]
    with pytest.raises(Exception) as caught: send(b, item)
    assert getattr(caught.value, 'outcome', None) == 'newer-version-exists'
    assert str(caught.value).startswith('Version 2 was added by ')
