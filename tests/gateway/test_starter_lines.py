"""E137 s1 C3 (strategy D-3, D-4, R1-1, R2-1, R2-4, R2-10): a starter pack holds the 2D lines it names.

The real exporter runs on the fake odbind in its own process (as `test_starter_export` runs it); the SDK reads each
line back with its own D-2 parser, outlines it trace by trace, declares and lands it as `segy-line/1` through the
Connectors' intake (`test_starter_archive_pack.Intake`) and states "N of M" of its dataset in fidelity. Every expected
value is a literal: the fake's line `LINE` (trace numbers 101..105, source points 1.5, 2, absent, 3.5, 4, samples
trc / 4 + k / 8), and its WGS84 positions as pyproj 3 transforms them, written here at 9 decimals."""
import json
import os
import shutil
import struct

import pytest

from ophiolite import starter, starter_archive as sa
from ophiolite.errors import Refused
from test_starter_archive_pack import FIDELITY, build, project  # noqa: F401 (fixture)
from test_starter_export import APACHE, CONNECTOR, FAKE, made, run

segyio = pytest.importorskip('segyio')

CRS = 'EPSG:32631'
FIRST, LAST = [101, 500001.0, 100.0], [105, 500051.0, 125.0]
POSITIONS = [(101, 1.5, 500001.0, 100.0), (102, 2.0, 500013.5, 106.25), (103, None, 500026.0, 112.5), (104, 3.5, 500038.5, 118.75),
             (105, 4.0, 500051.0, 125.0)]
WGS84 = [[3.000008987, 0.000904731], [3.000121321, 0.000961277], [3.000233655, 0.001017823], [3.00034599, 0.001074369], [3.000458324, 0.001130914]]
SOURCE = 'ophiolite starter export: every trace position of the 2D line as its SEG-Y holds it (x and y to 0.01 m), pyproj to EPSG:4326'


def lined(d, ids=('Syn2D/L1', 'Other/L1')):
    d['contents'] += [{'kind': 'seismic-2d', 'ids': list(ids)}]
    d['decisions'] += [{'topic': t, 'subject': x, 'value': v, 'source': 'data'} for x in ids
                       for t, v in (('crs', CRS), ('domain', 'time'), ('units', 'ms'), ('nulls', 'non-finite refused'))]


@pytest.fixture(scope='module')
def lines_once(tmp_path_factory):
    """One real export of the synthetic survey with two lines (Syn2D/L1 of Syn2D's two, Other/L1 of Other's one)."""
    folder, out = made(tmp_path_factory.mktemp('definition'), edit=lined), tmp_path_factory.mktemp('out')
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
        report, export = run(folder, out)
    return folder, out, report, export


def staged(tmp_path, lines_once):
    folder, _, _, export = lines_once
    stage = tmp_path / 'stage'
    shutil.copytree(export / 'files', stage)
    (stage / 'outline.geojson').unlink()
    return stage, json.loads((stage / 'export.json').read_text()), sa.definition(folder / 'definition.json')


def refused(fn, *args, **kw):
    with pytest.raises(Refused) as caught: fn(*args, **kw)
    return str(caught.value)


def test_each_line_is_exported_read_back_and_outlined_trace_by_trace(lines_once):
    """Mutations: the outline from the report's ends only (two positions, not five); the line source dropped from the
    feature; `of` not carried into the report's files."""
    _, _, report, export = lines_once
    assert [(f['path'], f['kind'], f['object'], f.get('of')) for f in report['files'] if f['kind'] == 'seismic-2d'] == [
        ('seismic2d/Syn2D/L1.sgy', 'seismic-2d', 'Syn2D/L1', 2), ('seismic2d/Other/L1.sgy', 'seismic-2d', 'Other/L1', 1)]
    doc = json.loads((export / 'files/export.json').read_text())
    assert doc['lines'] == {'Syn2D/L1': {'dataset': 'Syn2D', 'line': 'L1', 'traces': 5, 'z': [100.0, 116.0, 4.0], 'first': FIRST, 'last': LAST, 'of': 2},
                            'Other/L1': {'dataset': 'Other', 'line': 'L1', 'traces': 5, 'z': [100.0, 116.0, 4.0], 'first': [301, 500001.0, 100.0],
                                         'last': [305, 500051.0, 125.0], 'of': 1}}
    features = [f for f in json.loads((export / 'files/outline.geojson').read_text())['features'] if f['properties']['kind'] == 'survey-2d']
    assert [(f['properties']['name'], f['geometry'], f['properties']['source'], f['properties']['feature_id']) for f in features] == [
        (name, {'type': 'LineString', 'coordinates': WGS84}, SOURCE, 'ophiolite-synthetic/survey#survey-2d/' + name) for name in ('Other/L1', 'Syn2D/L1')]
    assert sa.line_positions(export / 'files/seismic2d/Syn2D/L1.sgy', {'path': 'L1.sgy', 'object': 'Syn2D/L1'}) == POSITIONS


def test_segyio_reads_the_line_the_sdk_read_back(lines_once):
    """A reader that did not write it: trace numbers, source points, x and y, the sampling and every sample."""
    path = lines_once[3] / 'files/seismic2d/Syn2D/L1.sgy'
    with segyio.open(str(path), ignore_geometry=True) as f:
        h = [f.header[n] for n in range(f.tracecount)]
        assert [t[segyio.TraceField.TRACE_SEQUENCE_LINE] for t in h] == [1, 2, 3, 4, 5]
        assert [t[segyio.TraceField.CDP] for t in h]  # byte 21 == [101, 102, 103, 104, 105]
        assert [(t[segyio.TraceField.CDP_X], t[segyio.TraceField.CDP_Y], t[segyio.TraceField.SourceGroupScalar]) for t in h] == [
            (50000100, 10000, -100), (50001350, 10625, -100), (50002600, 11250, -100), (50003850, 11875, -100), (50005100, 12500, -100)]
        assert [(t[segyio.TraceField.CROSSLINE_3D], t[segyio.TraceField.INLINE_3D]) for t in h] == [(101, 0), (102, 0), (103, 0), (104, 0), (105, 0)]
        assert [(t[197], t[201]) for t in h] == [(15, -10), (2, 1), (0, 0), (35, -10), (4, 1)]  # bytes 197 and 201: source point, its scalar
        assert (f.samples.tolist(), f.bin[segyio.BinField.Format]) == ([100.0, 104.0, 108.0, 112.0, 116.0], 5)
        assert [f.trace[n].tolist() for n in range(5)] == [[t / 4 + k / 8 for k in range(5)] for t in (101, 102, 103, 104, 105)]


def sample_at(trace, k):
    return 3600 + trace * (240 + 20) + 240 + 4 * k


@pytest.mark.parametrize('case, reason', [
    ('sample', 'its values differ from those odbind gave (digest of the expected representation)'),
    ('x', 'its values differ from those odbind gave (digest of the expected representation)'),
    ('dropped', 'its axes are {"traces": 4, "z": [100, 4000, 5]}, not {"traces": 5, "z": [100, 4000, 5]}'),
    ('report-x', 'the line report in export.json is not its own'),
    ('report-of', 'the line report in export.json is not its own'),
    ('report-z', 'the line report in export.json is not its own'),
])
def test_read_back_refuses_a_line_that_is_not_what_the_export_states(tmp_path, lines_once, case, reason):
    """D-3: a corrupted sample, x shifted by 0.01 m, a trace dropped, the report's last x, `of` or Z changed; each
    refused naming the file. The file stays well-formed SEG-Y in each case."""
    stage, doc, defn = staged(tmp_path, lines_once)
    sa.read_back(stage, doc, defn)  # unchanged, it passes
    path = stage / 'seismic2d/Syn2D/L1.sgy'
    raw = bytearray(path.read_bytes())
    if case == 'sample': raw[sample_at(2, 3):sample_at(2, 3) + 4] = struct.pack('>f', 26.25)
    if case == 'x': raw[3600 + 260 * 2 + 180:3600 + 260 * 2 + 184] = struct.pack('>i', 50002601)
    if case == 'dropped': del raw[-260:]
    path.write_bytes(bytes(raw))
    if case == 'report-x': doc['lines']['Syn2D/L1']['last'][1] = 500051.01
    if case == 'report-of': doc['lines']['Syn2D/L1']['of'] = 0
    if case == 'report-z': doc['lines']['Syn2D/L1']['z'][2] = 2.0
    assert refused(sa.read_back, stage, doc, defn) == 'seismic2d/Syn2D/L1.sgy does not hold what export.json states: %s. Nothing was sent.' % reason


@pytest.mark.parametrize('card, value, reason', [
    (5, 'C 6 OPHIOLITE 3D SEISMIC', 'card C6 is not the 2D line marker'),
    (7, 'C 8 LINE L2', 'cards C7 and C8 do not name Syn2D/L1'),
    (6, 'C 7 DATASET  Syn2D', 'cards C7 and C8 do not name Syn2D/L1'),
])
def test_read_back_takes_the_line_named_by_its_cards_only(tmp_path, lines_once, card, value, reason):
    """R2-4: the identity is C7 and C8 as written, compared with the file's object; a second space is another name."""
    stage, doc, defn = staged(tmp_path, lines_once)
    path = stage / 'seismic2d/Syn2D/L1.sgy'
    raw = bytearray(path.read_bytes())
    raw[80 * card:80 * (card + 1)] = value.ljust(80).encode('ascii')
    path.write_bytes(bytes(raw))
    assert refused(sa.read_back, stage, doc, defn) == 'seismic2d/Syn2D/L1.sgy is not the SEG-Y line the export writes: %s. Nothing was sent.' % reason


def test_a_one_trace_line_is_outlined_as_a_point(tmp_path, lines_once):
    """R2-10: a line of one trace has no LineString (GeoJSON wants two positions); its one position is a Point. A
    pack of lines only has an outline too."""
    stage, doc, defn = staged(tmp_path, lines_once)
    path = stage / 'seismic2d/Syn2D/L1.sgy'
    path.write_bytes(path.read_bytes()[:3600 + 260])
    lines_only = {**doc, 'cubes': {}, 'wells': {}, 'files': [f for f in doc['files'] if f['object'] == 'Syn2D/L1']}
    (feature,) = sa.outline(defn, lines_only, APACHE, stage)['features']
    assert (feature['geometry'], feature['properties']['kind']) == ({'type': 'Point', 'coordinates': WGS84[0]}, 'survey-2d')


def test_lines_are_landed_only_in_time_in_milliseconds(lines_once):
    """R1-1: the declarations and the agreement each refuse a survey in depth for lines, by name; cubes and horizons
    in depth keep landing."""
    survey = {'crs': CRS, 'zdomain': 'depth', 'zunit': 'm', 'xyunit': 'm'}
    assert starter.declarations(survey, {'seismic-3d'})['seismic-3d'] == {'crs': CRS, 'z_domain': 'depth'}
    assert refused(starter.declarations, survey, {'seismic-3d', 'seismic-2d'}) == (
        "The export's survey is in depth m; 2D lines are landed in time (ms) only in this version. No pack document was written.")
    assert starter.declarations({**survey, 'zdomain': 'twt', 'zunit': 'ms'}, {'seismic-2d'})['seismic-2d'] == {'crs': CRS, 'z_domain': 'time'}
    defn = sa.definition(lines_once[0] / 'definition.json')
    defn = {**defn, 'contents': [c for c in defn['contents'] if c['kind'] == 'seismic-2d']}  # the cubes' own refusal would come first
    assert refused(sa.agreed, defn, {'survey': survey}) == (
        "The export's survey is in depth m; 2D lines are landed in time (ms) only in this version. Nothing was sent.")


def test_a_line_is_landed_as_segy_line_and_states_its_share_of_the_dataset(tmp_path, project, monkeypatch):
    """D-4 (D84): the Connectors' intake takes each line as `segy-line/1` with the crs and Z domain of the survey; its
    fidelity row ends with "N of M" of its dataset. Syn2D/L2 and Other/L1 here: the fake intake keys a file by its
    name, and two `L1.sgy` would be one name to it. Mutations: N counted over the whole pack (2 of 2); M from the
    pack (1 of 1); the representative row dropped."""
    folder, out = made(tmp_path / 'definition', edit=lambda d: lined(d, ('Syn2D/L2', 'Other/L1'))), tmp_path / 'export'
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
    monkeypatch.delenv('FAKE_ODBIND_VARIANT', raising=False)
    run(folder, out)
    build(folder, out, project)
    landing = json.loads((folder / 'pack/landing.json').read_text())
    for path in ('seismic2d/Syn2D/L2.sgy', 'seismic2d/Other/L1.sgy'):
        assert (landing['inputs'][path]['profile'], landing['inputs'][path]['output']['kind']) == ('segy-line/1', 'seismic-2d')
        assert project.read[path.rsplit('/', 1)[1]][:2] == ('segy-line/1', {'crs': CRS, 'z_domain': 'time'})
    rows = {i['name']: i for i in json.loads((folder / 'pack' / FIDELITY).read_text())['inputs']}
    assert rows['seismic2d/Syn2D/L2.sgy']['representative'][-1] == {'field': 'lines of dataset Syn2D in this pack', 'unit': None, 'value': '1 of 2'}
    assert rows['seismic2d/Other/L1.sgy']['representative'][-1] == {'field': 'lines of dataset Other in this pack', 'unit': None, 'value': '1 of 1'}
