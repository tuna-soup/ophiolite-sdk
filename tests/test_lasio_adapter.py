"""E126a acceptance 2, 3 and 5: a project's log as a reconstructed `lasio.LASFile`, a lasio-built file back as exact
bytes or a `WrittenOriginal`; WELL only from a well linked to this exact revision that you may read; lasio optional."""
import math
import os
import subprocess
from contextlib import contextmanager

import lasio
import numpy as np
import zipfile
from pathlib import Path
import pytest
from ophiolite import Client, Credential, las_header
from ophiolite.errors import AxisMismatch, Busy, Refused, ValidationFailed, VerificationFailed
from ophiolite.lasio import curves_from_lasio, lasio_bytes, to_lasio
from ophiolite.testing import synthetic_server
from ophiolite.windows import CurveWindow

REVISION = 'd899416c42214983308a6feec77a5f94e6d391665dd228d91957393b37caf56b'  # sha256 of the packaged original.las


def plain(values):
    return [None if math.isnan(v) else float(v) for v in values]


@contextmanager
def synthetic(**answers):
    """The synthetic server, with `answers` {route suffix: (status, body)} replacing its own answer to that POST."""
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        inner = server.handler
        def handler(method, path, body, headers):
            hit = next((answer for suffix, answer in answers.items() if method == 'POST' and path.split('?')[0].endswith(suffix)), None)
            return hit if hit is not None else inner(method, path, body, headers)
        server.handler = handler
        asset = next(iter(alice.assets()))
        yield alice, alice.read(asset['asset_id'], asset['revision'], ['GR'])


def associated(*entities, revision=REVISION):
    return 200, {'items': [{'asset_id': 'curve-a', 'revision': revision, 'profile': 'las2/1', 'name': 'Synthetic gamma ray',
                            'association': {'assertion_id': f'a{i}', 'predicate': 'of-entity', 'evidence': {}, 'asserted_by': 'alice',
                                            'asserted_at': '2026-10-21T00:00:00Z'}, 'entity': entity} for i, entity in enumerate(entities)],
                 'next_cursor': None}


WELL1 = {'entity_id': 'well-synthetic-1', 'kind': 'well', 'name': 'Synthetic well 1'}
WELL2 = {'entity_id': 'well-synthetic-2', 'kind': 'well', 'name': 'Synthetic well 2'}
BORE = {'entity_id': 'wellbore-synthetic-1', 'kind': 'wellbore', 'name': 'Synthetic well 1 main'}


def test_the_synthetic_log_as_a_reconstructed_las_file():
    with synthetic() as (_, data):
        las = to_lasio(data)
    assert [(c.mnemonic, c.unit) for c in las.curves] == [('DEPT', 'M'), ('GR', 'gAPI')]
    assert list(las.index) == [100.0, 101.0, 102.0, 103.0, 104.0] and plain(las['GR']) == [0.0, 10.0, None, 30.0, 40.0]
    assert las.df()['GR'].isna().sum() == 1 and float(las.well['NULL'].value) == -999.25
    assert las.other == f'Project p\nAsset curve-a\nRevision {REVISION}'
    assert las.well['WELL'].value == 'Synthetic well 1'  # linked through its wellbore; never the header's SYNTHETIC-M1
    assert all(las.well[k].value == '' for k in ('COMP', 'FLD', 'LOC', 'PROV', 'CNTY', 'STAT', 'CTRY', 'SRVC', 'DATE', 'UWI', 'API'))
    assert [c.descr for c in las.curves] == ['', ''] and len(las.params) == 0


@pytest.mark.parametrize('answers,well,expected', [
    ({'/entities/associations': associated()}, None, ''),  # no linked entity
    ({'/entities/associations': associated()}, 'A', 'A'),
    ({'/entities/associations': associated(BORE)}, 'A', 'Synthetic well 1'),  # a linked readable well wins
    ({'/entities/associations': associated(BORE), '/entities/get': (403, {'error': 'Not yours.'})}, None, ''),  # restricted
    ({'/entities/associations': associated(BORE), '/entities/get': (404, {'error': 'No such well or wellbore.'})}, None, ''),
    ({'/entities/associations': associated(WELL2, revision='an-earlier-revision')}, None, ''),  # another revision's well
    ({'/entities/associations': associated(BORE, WELL1)}, None, 'Synthetic well 1'),  # two links, one well
    ({'/entities/associations': associated(WELL1, WELL2)}, 'A', 'A'),  # two wells: never a guess
])
def test_well_only_from_one_readable_well_linked_to_this_revision(answers, well, expected):
    with synthetic(**answers) as (_, data):
        assert to_lasio(data, well=well).well['WELL'].value == expected


def test_a_busy_service_is_not_read_as_no_well():
    with synthetic(**{'/entities/associations': associated(BORE), '/entities/get': (503, {'error': 'Service is busy.'})}) as (_, data):
        with pytest.raises(Busy): to_lasio(data, well='A')


def test_a_curve_set_read_offline_has_no_link_and_takes_the_given_well():
    with synthetic() as (_, data):
        del data._client
        assert to_lasio(data).well['WELL'].value == '' and to_lasio(data, well='A').well['WELL'].value == 'A'


def test_refusals_of_to_lasio():
    from test_scientific import view
    data, _ = view(); data.curves[1].axis[0] = 99  # GR and RHOB on different axes
    with pytest.raises(AxisMismatch): to_lasio(data)
    with pytest.raises(Refused, match='display'): to_lasio(object.__new__(CurveWindow))
    with synthetic() as (_, data):
        data.curves[0].values[0] = -999.25
        with pytest.raises(ValidationFailed, match='Curve GR has a real value equal to the null marker -999.25; it would read back as missing.'): to_lasio(data)


def test_two_value_curves_keep_their_order_units_and_null_positions():
    from test_scientific import view
    data, _ = view(); data.curves.reverse(); data.descriptors.reverse()  # RHOB first, then GR
    data.curves[0].values[2], data.curves[0].values[4] = 2.2, None  # RHOB missing at 104, GR at 102
    las = to_lasio(data)
    assert [(c.mnemonic, c.unit) for c in las.curves] == [('DEPT', 'M'), ('RHOB', 'g/cm3'), ('GR', 'gAPI')]
    assert plain(las['RHOB']) == [2.0, 2.1, 2.2, 2.3, None] and plain(las['GR']) == [0.0, 10.0, None, 30.0, 40.0]
    assert las.well['WELL'].value == '' and las.other.startswith('Project synthetic-project\n')


def two_curves(null=-999.25):
    las = lasio.LASFile()
    las.append_curve('DEPT', np.array([1.0, 2.0, 3.0]), unit='M')
    las.append_curve('GR', np.array([0.1 + 0.2, np.nan, 1e-7]), unit='gAPI')
    las.append_curve('RHOB', np.array([2.5, 2.6, 2.65]), unit='g/cm3')
    las.well['NULL'].value = null
    return las


def test_lasio_bytes_are_exact_and_read_by_the_sdk_header_reader():
    raw = lasio_bytes(two_curves())
    assert [(c.mnemonic, c.unit) for c in las_header.curves(raw)] == [('DEPT', 'M'), ('GR', 'gAPI'), ('RHOB', 'g/cm3')]
    back = lasio.read(raw.decode())
    assert plain(back['GR']) == [0.30000000000000004, None, 1e-07] and plain(back['RHOB']) == [2.5, 2.6, 2.65]
    las = two_curves(); las['GR'][0] = -999.25
    with pytest.raises(ValidationFailed, match='Curve GR has a real value equal to the null marker -999.25'): lasio_bytes(las)
    for null in ('none', math.inf):
        with pytest.raises(ValidationFailed, match="Declare the file's NULL value as a finite number"): lasio_bytes(two_curves(null))


def test_curves_from_lasio_reads_back_with_null_as_missing():
    written = curves_from_lasio(lasio.read(lasio_bytes(two_curves()).decode()))
    assert written.profile == 'las2/1'
    back = lasio.read(written.bytes.decode())
    assert list(back.index) == [1.0, 2.0, 3.0] and plain(back['GR']) == [0.30000000000000004, None, 1e-07] and plain(back['RHOB']) == [2.5, 2.6, 2.65]
    assert [(c.mnemonic, c.unit) for c in back.curves] == [('DEPT', 'M'), ('GR', 'gAPI'), ('RHOB', 'g/cm3')]


def test_a_notebook_built_file_holding_its_own_null_value_writes_it_as_missing():
    las = two_curves(null=-999); las['RHOB'][1] = -999  # the sentinel itself, as a notebook writes it
    rows = curves_from_lasio(las).bytes.decode().split('~ASCII\n')[1].splitlines()
    assert rows == ['1 0.30000000000000004 2.5', '2 -999.25 -999.25', '3 1e-07 2.65']


def test_the_depth_unit_is_declared_never_inferred_or_converted():
    las = two_curves(); las.curves[0].unit = ''
    with pytest.raises(ValidationFailed, match="Declare the depth unit: the file's DEPT curve has none; nothing is inferred."): curves_from_lasio(las)
    assert 'DEPT.FT : depth' in curves_from_lasio(las, depth_unit='FT').bytes.decode()
    with pytest.raises(ValidationFailed, match="The file's depth unit 'M' differs from depth_unit='FT'; nothing is converted."):
        curves_from_lasio(two_curves(), depth_unit='FT')


def test_a_lasio_result_publishes_and_reads_back():
    with synthetic() as (alice, data):
        las = to_lasio(data); las['GR'] = las['GR'] * 2
        receipt = alice.publish_derived(curves_from_lasio(las), name='Doubled', from_=[('curve-a', REVISION)], method={'name': 'double'}, command_id='e126a-lasio')
        frame, meta = alice.read(receipt.asset_id, receipt.revision, ['GR']).to_frame()
    assert plain(frame['GR']) == [0.0, 20.0, None, 60.0, 80.0] and list(frame.index) == [100.0, 101.0, 102.0, 103.0, 104.0]
    assert meta.curves['GR'].unit == 'gAPI' and meta.axis.unit == 'M'


def test_the_base_wheel_imports_without_lasio_and_refuses_the_call(tmp_path):
    python = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    assert python, 'Provide the base-only installed-wheel interpreter'
    script = r'''
import importlib.util
assert importlib.util.find_spec('lasio') is None and importlib.util.find_spec('pandas') is None
import ophiolite, ophiolite.exchange, ophiolite.frames, ophiolite.lasio
from ophiolite.errors import MissingExtra
for call in (lambda: ophiolite.lasio.to_lasio(None), lambda: ophiolite.lasio.lasio_bytes(None), lambda: ophiolite.lasio.curves_from_lasio(None)):
    try: call()
    except MissingExtra as error: assert "pip install 'ophiolite[lasio]'" in str(error), error
    else: raise AssertionError('lasio missing, call accepted')
'''
    result = subprocess.run([python, '-I', '-c', script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_same_null_valued_sample_is_missing_on_ingest_and_refused_on_write():
    las = two_curves(null=-999); las['RHOB'][1] = -999
    assert curves_from_lasio(las).bytes.decode().splitlines()[-2] == '2 -999.25 -999.25'
    with pytest.raises(ValidationFailed, match='Curve RHOB has a real value equal to the null marker -999'): lasio_bytes(las)


@pytest.mark.parametrize('where', ['DEPT', 'GR'])
def test_a_sample_a_float_cannot_hold_is_refused_by_both_writers(where):
    las = two_curves()
    for curve in las.curves:
        if curve.mnemonic == where: curve.data = np.array([1, 2, 9007199254740993], dtype='int64')
    for write in (lasio_bytes, curves_from_lasio):
        with pytest.raises(ValidationFailed, match=f'9007199254740993 in {where} cannot be written exactly; nothing is rounded.'): write(las)
    if np.dtype(np.longdouble).itemsize > 8:
        las = two_curves(); las.curves[2].data = np.array([2.5, 2.6, 2.65], dtype=np.longdouble) + np.longdouble('1e-19')
        for write in (lasio_bytes, curves_from_lasio):
            with pytest.raises(ValidationFailed, match='Curve RHOB is wider than a 64-bit float'): write(las)


def test_a_header_the_sdk_reads_differently_returns_nothing(monkeypatch):
    monkeypatch.setattr(las_header, 'curves', lambda raw: [las_header.CurveHeader('DEPT', 'M', ''), las_header.CurveHeader('GR', 'API', '')])
    with pytest.raises(VerificationFailed, match='lasio wrote a header the SDK reads differently; nothing was returned.'): lasio_bytes(two_curves())


def test_the_wheel_declares_the_lasio_extra():
    dist = os.environ.get('OPHIOLITE_TEST_DIST')
    assert dist, 'Set OPHIOLITE_TEST_DIST to the folder holding the built wheel'
    [wheel] = Path(dist).glob('ophiolite-*.whl')
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))).decode()
    assert 'Provides-Extra: lasio' in metadata.splitlines() and 'Requires-Dist: lasio>=0.32; extra == "lasio"' in metadata.splitlines()


@pytest.mark.parametrize('where', ['DEPT', 'GR'])
def test_a_large_integer_a_float_holds_exactly_is_admitted_by_both_writers(where):
    las = two_curves()
    for curve in las.curves:
        if curve.mnemonic == where: curve.data = np.array([1, 2, 9007199254740994], dtype='int64')
    assert lasio.read(lasio_bytes(las).decode())[where][2] == 9007199254740994.0
    assert curves_from_lasio(las).bytes.decode().splitlines()[-1].split()[0 if where == 'DEPT' else 1] == '9007199254740994'


@pytest.mark.parametrize('where,value,sentence', [('DEPT', np.nan, 'Depth cannot be missing.'), ('DEPT', np.inf, None), ('GR', np.inf, None), ('GR', -np.inf, None)])
def test_missing_depths_and_infinite_samples_are_refused_by_both_writers(where, value, sentence):
    las = two_curves()
    for curve in las.curves:
        if curve.mnemonic == where: curve.data = np.array([1.0, value, 3.0])
    with pytest.raises(ValidationFailed, match=sentence or f'Curve {where} must be finite; write a missing sample as NaN.'): lasio_bytes(las)
    with pytest.raises(ValidationFailed, match=sentence or 'must be finite'): curves_from_lasio(las)
