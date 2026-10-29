"""E112 s1, s1p: every listed step x kind pair has a working start that runs its own tests (strategy, s1 revision 2;
s1p revision 2).

The oracles sit outside the generator (3-M7, 2-M5): the made and later sets, the manifests, the values each start
must make from an input and the declarations it records are literals here; outputs are read back with Connectors'
own readers (S1-R2), which the SDK unit lane puts on `sys.path`. Sends run through `deliver` with test_deliver's
in-memory project (S1-R4); checks through `procedures.run` with project versions (S1-R5)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ophiolite
from ophiolite import procedure_templates as templates, procedures, writers
from ophiolite.procedures import DeliveryAttempt, LocalSystem
from test_deliver import Project, deliver

READ = ('points', 'mesh', 'grid', 'las', 'well-location', 'wavelet', 'well-tops', 'deviation', 'fault-sticks', 'model-section', 'time-depth')
SENT = READ + ('seismic-section', 'residual')
PROCESSED = READ + ('seismic-section',)
MADE = frozenset([('read', w) for w in READ] + [('source', w) for w in READ] + [('send', w) for w in SENT]
                 + [('check', 'well-tops'), ('check', 'deviation')] + [('process', w) for w in PROCESSED])
NAMES = {'points': 'Point set (CSV)', 'mesh': 'Triangulated surface (text)', 'grid': 'Horizon grid (ESRI ASCII)', 'well-tops': 'Well tops (CSV)',
         'deviation': 'Deviation survey (CSV)', 'fault-sticks': 'Fault sticks (OpendTect)', 'las': 'LAS 2.0 well log file',
         'well-location': 'Well location (JSON)', 'wavelet': 'Wavelet (text)', 'model-section': 'Rock model section (text)',
         'seismic-section': 'Seismic section (text)', 'time-depth': 'Time-depth table (CSV)', 'residual': 'Residual result (JSON)'}
PROFILES = {'points': 'points-csv/1', 'mesh': 'mesh-text/1', 'grid': 'esri-ascii-grid/1', 'well-tops': 'well-tops-csv/1', 'deviation': 'deviation-csv/1',
            'fault-sticks': 'opendtect-faultsticks/1', 'las': 'las2/1', 'well-location': 'well-location/1', 'wavelet': 'wavelet-text/1',
            'model-section': 'model-section-text/1', 'seismic-section': 'seismic-section-text/1', 'time-depth': 'time-depth-csv/1',
            'residual': 'well-residual/1'}
LABELS = {'read': 'Read {}', 'source': 'Read {} from a system', 'process': 'Make {}', 'send': 'Send {}', 'check': 'Check {}'}
# (slot, class) per step, the output roles and classes: the shape each start's manifest has (3-M7)
SHAPES = {'read': ([('file', 'file')], [('data', 'version')]), 'source': ([('system', 'system')], [('data', 'version')]),
          'process': ([('data', 'version')], [('data', 'version')]),
          'send': ([('data', 'version'), ('destination', 'system')], [('delivery', 'delivery')]),
          'check': ([('data', 'version'), ('reference', 'reference')], [('comparison', 'comparison')])}


def named(word):
    name = NAMES[word]
    return name if name[1:2].isupper() else name[0].lower() + name[1:]


def made_pairs():
    return frozenset((step, templates.word(profile)) for step, profile in templates.made())


def test_the_made_starts_are_these_49_every_listed_pair():
    assert len(MADE) == 49 and made_pairs() == MADE
    assert {(s, templates.word(p)) for s, p in templates.listed()} == MADE and not hasattr(templates, 'READER_LATER')


@pytest.mark.parametrize('step,word', sorted(MADE))
def test_every_start_validates_has_its_step_s_shape_and_passes_its_own_tests(tmp_path, step, word):
    folder = tmp_path / f'{step}-{word}'
    verdict = templates.make(folder, step, word)
    assert verdict['valid'], verdict
    manifest = json.loads((folder / 'procedure.json').read_text())
    inputs, outputs = SHAPES[step]
    assert manifest['step'] == step and manifest['label'] == LABELS[step].format(named(word)) and manifest['name'] == f'{step}-{word}'
    assert [(i['slot'], i['class']) for i in manifest['inputs']] == inputs and [(o['role'], o['class']) for o in manifest['outputs']] == outputs
    assert all(i['kinds'] == [PROFILES[word]] for i in manifest['inputs'] if 'kinds' in i)
    assert all(o['kind'] == PROFILES[word] for o in manifest['outputs'] if o['class'] == 'version')
    assert manifest['requires'] == []  # E112 s4: visible and empty; the guide says what goes in it
    assert ('reconcile' in manifest) == (step == 'send') and json.loads((folder / 'template.json').read_text()) == {
        'step': step, 'kind': PROFILES[word], 'pairs_rules_version': templates.pairs()['rules_version'], 'sdk_version': ophiolite.__version__}
    code = (folder / 'procedure.py').read_text()
    assert 'NotImplementedError' not in code
    own = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests'], cwd=folder, capture_output=True, text=True,
                         env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=300)
    assert own.returncode == 0 and ' passed' in own.stdout and 'failed' not in own.stdout, own.stdout + own.stderr


def test_a_label_given_is_kept_and_an_existing_folder_or_a_refused_pair_is_refused(tmp_path):
    assert templates.make(tmp_path / 'mine', 'read', 'well-tops-csv/1', 'Read our tops')['valid']
    assert json.loads((tmp_path / 'mine/procedure.json').read_text())['label'] == 'Read our tops'
    with pytest.raises(procedures.NotRun) as refused: templates.make(tmp_path / 'mine', 'read', 'las')
    assert refused.value.code == 'destination-exists'
    for step, kind in (('process', 'residual'), ('check', 'mesh'), ('read', 'nothing')):
        with pytest.raises(ValueError): templates.make(tmp_path / 'later', step, kind)
        assert not (tmp_path / 'later').exists()


# ---------------------------------------------------------------- read and source: two inputs, read back by Connectors

SECOND = {  # a second input per kind: other values and, where a kind has them, other declarations (3-M3, 3-M4)
    'points': {'points': [[1.0, 2.0], [3.5, 4.5]], 'crs': 'EPSG:4326', 'xy_unit': 'deg', 'z_unit': 'unknown', 'z_meaning': 'unknown',
               'positive': 'unknown', 'vertical_datum': 'unknown'},
    'mesh': {'vertices': [[0.0, 0.0, 10.0], [1.0, 0.0, 11.0], [0.0, 1.0, 12.0]], 'triangles': [[0, 1, 2]], 'crs': 'unknown', 'xy_unit': 'ft',
             'z_unit': 'ft', 'z_meaning': 'elevation', 'positive': 'up', 'vertical_datum': 'unknown'},
    'grid': {'values': [[7.0, None], [9.5, 10.0]], 'ncols': 2, 'nrows': 2, 'x_origin': 1012.5, 'y_origin': -50.0, 'cell_size': 10.0, 'registration': 'center',
             'nodata': -1.0, 'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'ms', 'z_meaning': 'time', 'positive': 'down', 'vertical_datum': 'unknown'},
    'well-tops': {'tops': [{'name': 'Base Chalk', 'md': 5012.0}], 'depth_unit': 'ft', 'depth_basis': 'unknown'},
    'deviation': {'stations': [{'md': 0.0, 'inclination': 0.0, 'azimuth': None}, {'md': 820.0, 'inclination': 3.25, 'azimuth': 359.5}],
                  'depth_unit': 'ft', 'azimuth_reference': 'true-north', 'depth_datum': 'unknown'},
    'fault-sticks': {'sticks': [{'index': 4, 'points': [[1.0, 1.0, 900.0], [2.0, 2.0, 950.0]]}], 'crs': 'unknown', 'xy_unit': 'm', 'z_unit': 'm',
                     'z_meaning': 'depth', 'positive': 'down', 'vertical_datum': 'unknown'},
    'las': {'depth': [3000.0, 3000.25], 'curves': {'NPHI': ['V/V', [0.31, None]]}, 'depth_unit': 'ft', 'well': 'OTHER-2'},
    'well-location': {'x': 4.5, 'y': 52.25, 'crs': 'OGC:CRS84', 'elevation_reference': 'MSL'},
    'wavelet': {'wavelet': [0.0, 1.0, 0.0], 'kind': 'ricker', 'frequency_hz': 25.0, 'dt': 0.004, 't0': -0.004, 'polarity': 'unknown'},
    'model-section': {'model': [{'index': 3, 'name': 'Salt', 'vp': 4500.0, 'density': 2160.0}], 'grid': [[3, 3]], 'domain': 'time', 'first_sample': 0.5,
                      'sample_interval': 0.004, 'horizontal': 'trace-number', 'horizontal_first': 101.0, 'horizontal_step': 1.0},
    'time-depth': {'pairs': [[100.0, 0.08], [200.0, 0.15]], 'depth_type': 'md', 'depth_unit': 'ft', 'time_kind': 'one-way', 'time_unit': 'ms'},
}


def values(word, raw, declared):
    """What Connectors' reader reads from a written file, in the shape of the writer's arguments."""
    if word == 'las':
        from asset_connectors.las_reader import read_las
        las = read_las(raw)
        number = lambda v: None if v != v else float(v)
        return {'depth': [float(d) for d in las.index], 'curves': {c.mnemonic: [c.unit, [number(v) for v in las[c.mnemonic]]] for c in las.curves[1:]},
                'well': las.well['WELL'].value, 'depth_unit': las.curves[0].unit}
    from asset_connectors.typed_reader import read_typed
    context, data, _ = read_typed(PROFILES[word], raw, declared)
    if word in ('points', 'mesh'):
        found = {'points' if word == 'points' else 'vertices': [p[:2] if word == 'points' and not context['z_provided'] else p for p in data['points' if word == 'points' else 'vertices']]}
        if word == 'mesh': found['triangles'] = data['triangles']
        if data.get('attributes'): found['attributes'] = {a['name']: a['values'] for a in data['attributes']}
        return found
    if word == 'grid':
        return {'values': data['values'], 'ncols': context['ncols'], 'nrows': context['nrows'], 'cell_size': context['cell_size'],
                'registration': context['registration'], 'first_center': [context['x_first_center'], context['y_first_center']]}
    if word == 'well-tops': return {'tops': [{k: v for k, v in t.items() if v is not None} for t in data['tops']]}
    if word == 'deviation': return {'stations': [{k: v for k, v in s.items() if k != 'tvd'} for s in data['stations']]}
    if word == 'fault-sticks': return {'sticks': [{'index': s['index'], 'points': [[p['x'], p['y'], p['z']] for p in s['points']]} for s in data['sticks']]}
    if word == 'well-location': return {'x': data['x'], 'y': data['y'], 'crs': context['crs'], 'elevation_reference': context['elevation_reference']}
    if word == 'wavelet': return {'wavelet': data['samples']}
    if word == 'model-section': return {'model': data['rocks'], 'grid': data['grid']}
    return {'pairs': [[d, t] + ([v] if v is not None else []) for d, t, v in zip(data['depth'], data['time'], data.get('velocity') or [None] * len(data['depth']))]}


def expected(word, given):
    """The same shape, from the arguments the input file holds (the oracle: no writer, no template)."""
    given = json.loads(json.dumps(given))
    if word == 'grid':
        half = 0 if given['registration'] == 'center' else given['cell_size'] / 2
        north = given['y_origin'] + half + (given['nrows'] - 1) * given['cell_size']
        return {'values': [v for row in given['values'] for v in row], 'ncols': given['ncols'], 'nrows': given['nrows'], 'cell_size': given['cell_size'],
                'registration': given['registration'], 'first_center': [given['x_origin'] + half, north]}
    keep = {'points': ('points', 'attributes'), 'mesh': ('vertices', 'triangles', 'attributes'), 'las': ('depth', 'curves', 'well', 'depth_unit'),
            'well-tops': ('tops',), 'deviation': ('stations',), 'fault-sticks': ('sticks',), 'well-location': ('x', 'y', 'crs', 'elevation_reference'),
            'wavelet': ('wavelet',), 'model-section': ('model', 'grid'), 'time-depth': ('pairs',)}[word]
    found = {k: given[k] for k in keep if k in given}
    if word == 'well-tops': found['tops'] = [{k: v for k, v in t.items() if v not in (None, '')} for t in found['tops']]
    if word == 'time-depth': found['pairs'] = [[x for x in p if x is not None] for p in found['pairs']]
    return found


DECLARED = {  # what run.json records beside each output, by input (sample, second): literals (3-M2)
    'points': ({'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'elevation', 'positive': 'up', 'vertical_datum': 'NAP'},
               {'crs': 'EPSG:4326', 'xy_unit': 'deg'}),
    'mesh': ({'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down', 'vertical_datum': 'NAP'},
             {'xy_unit': 'ft', 'z_unit': 'ft', 'z_meaning': 'elevation', 'positive': 'up'}),
    'grid': ({'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down', 'vertical_datum': 'NAP'},
             {'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'ms', 'z_meaning': 'time', 'positive': 'down'}),
    'well-tops': ({'depth_unit': 'm', 'depth_basis': 'same-as-log'}, {'depth_unit': 'ft'}),
    'deviation': ({'depth_unit': 'm', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'},
                  {'depth_unit': 'ft', 'azimuth_reference': 'true-north'}),
    'fault-sticks': ({'crs': 'EPSG:28992', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down', 'vertical_datum': 'NAP'},
                     {'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down'}),
    'las': ({}, {}), 'well-location': ({}, {}), 'wavelet': ({}, {}), 'model-section': ({}, {}),
    'time-depth': ({'depth_type': 'tvdss', 'depth_unit': 'm', 'time_kind': 'two-way', 'time_unit': 's'},
                   {'depth_type': 'md', 'depth_unit': 'ft', 'time_kind': 'one-way', 'time_unit': 'ms'}),
}


def copied(folder, tmp_path):
    return shutil.copytree(folder, tmp_path / 'copy', ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))


@pytest.mark.parametrize('word', READ)
@pytest.mark.parametrize('step', ['read', 'source'])
def test_read_and_source_starts_make_what_their_input_holds(tmp_path, step, word):
    folder = tmp_path / 'start'
    templates.make(folder, step, word)
    sample = json.loads((templates.SAMPLES / f'{word}.json').read_text())
    for number, given in enumerate((sample, SECOND[word])):
        where = tmp_path / f'input-{number}'
        where.mkdir()
        (where / 'sample.json').write_text(json.dumps(given))
        if step == 'read': ran = procedures.run(folder, tmp_path / f'out-{number}', {'file': [where / 'sample.json']})
        else:
            (tmp_path / f'system-{number}.json').write_text(json.dumps({'folder': str(where)}))
            ran = procedures.run(folder, tmp_path / f'out-{number}', systems={'system': tmp_path / f'system-{number}.json'})
        made = ran['run']['outputs']['data']
        assert made['profile'] == PROFILES[word] and made['declared'] == DECLARED[word][number]
        raw = (tmp_path / f'out-{number}' / made['file']).read_bytes()
        assert values(word, raw, made['declared']) == expected(word, given), (word, number)


# ---------------------------------------------------------------- process: a second input, read back by Connectors (s1p D5)

# Per kind, a second input that the writer would not write as it is (header case, CRLF, other number spellings), with
# other values and declarations than the sample, and an explicit "unknown" where a kind declares (1-M2, 1-M3).
FOREIGN = {
    'points': ('p.csv', b'X,Y,Z,Phi\r\n1.50,2,-3e2,0.25\r\n4,5,,\r\n',
               {'crs': 'EPSG:4326', 'xy_unit': 'deg', 'z_unit': 'unknown', 'z_meaning': 'elevation', 'positive': 'up', 'vertical_datum': 'unknown'}),
    'mesh': ('m.mesh', b'# ophiolite-mesh 1\nattributes phi\nvertices\n0 0 10.0 0.1\n1.0 0 - -\n0 1 12 0.30\ntriangles\n2 0 1\n',
             {'crs': 'unknown', 'xy_unit': 'ft', 'z_unit': 'ft', 'z_meaning': 'elevation', 'positive': 'up'}),
    'grid': ('g.asc', b'NCOLS 2\r\nNROWS 2\r\nXLLCENTER 1012.50\r\nYLLCENTER -50\r\nCELLSIZE 10.0\r\nNODATA_VALUE -1\r\n7.0 -1\r\n9.5 10\r\n',
             {'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'ms', 'z_meaning': 'time', 'positive': 'down', 'vertical_datum': 'unknown'}),
    'well-tops': ('t.csv', b'Name , MD,Source\r\nBase Chalk,5012.0,picks 2025\r\nNL,1.65e3,\r\n', {'depth_unit': 'ft', 'depth_basis': 'unknown'}),
    'deviation': ('d.csv', b'MD,Inclination,Azimuth,TVD\r\n0,0,,0\r\n820.0,3.250,359.5,819.5\r\n',
                  {'depth_unit': 'ft', 'azimuth_reference': 'true-north', 'depth_datum': 'unknown'}),
    'fault-sticks': ('f.txt', b'1 1 900 4\n2 2 950.0 4\n5.5 6 1000 2\n5.5 6.5 1100 2\n',
                     {'crs': 'unknown', 'xy_unit': 'ft', 'z_unit': 'ft', 'z_meaning': 'depth', 'positive': 'down'}),
    'las': ('l.las', b'~V\nVERS. 2.0 : LAS\nWRAP. NO : rows\n~W\nSTRT.FT 3000.0 : start\nSTOP.FT 3000.25 : stop\nSTEP.FT 0.25 : step\n'
                     b'NULL. -999 : missing\nWELL. OTHER-2 : well\n~C\nDEPT.FT : depth\nNPHI.V/V : NPHI\n~O\n Processed by hand.\n~A\n3000 0.31\n3000.25 -999\n', {}),
    'well-location': ('w.json', b'{"y": 52.25, "x": 4.50, "crs": "OGC:CRS84", "elevation_reference": "MSL"}', {}),
    'wavelet': ('v.txt', b'# ophiolite-wavelet 1\nkind ricker\nfrequency_hz 25.0\ndt 0.0040\nt0 -0.004\npolarity unknown\nsamples\n0\n1.0\n0\n', {}),
    'model-section': ('ms.txt', b'# ophiolite-model-section 1\ndomain time\nfirst_sample 0.50\nsample_interval 0.004\nsamples 1\ntraces 2\n'
                                b'horizontal trace-number\nhorizontal_first 101\nhorizontal_step 1.0\nrocks\n3 4500.0 2160 Salt\ngrid\n3 3\n', {}),
    'seismic-section': ('ss.txt', b'# ophiolite-seismic-section 1\ndomain depth\nfirst_sample 0\nsample_interval 5.0\nsamples 2\ntraces 2\n'
                                  b'horizontal distance\nhorizontal_first 10\nhorizontal_step 12.50\norigin synthetic\npolarity impedance-increase-negative\n'
                                  b'grid\n1.0 2\n3 -4.50\n', {}),
    'time-depth': ('td.csv', b'Depth,Time\r\n100,0.080\r\n200.0,0.15\r\n',
                   {'depth_type': 'md', 'depth_unit': 'ft', 'time_kind': 'one-way', 'time_unit': 'ms', 'datum': 'KB', 'seismic_reference_elevation': '12.50'}),
}
# What each start makes of it, written by hand from the input above: run.json's declared (no "unknown"; the elevation in
# the writer's spelling, 1-F1), the Connectors context keys that carry it, and the Connectors data (or LAS read).
MADE_FROM = {
    'points': ({'crs': 'EPSG:4326', 'xy_unit': 'deg', 'z_meaning': 'elevation', 'positive': 'up'}, {'z_provided': True},
               {'points': [[1.5, 2.0, -300.0], [4.0, 5.0, None]], 'attributes': [{'name': 'Phi', 'values': [0.25, None]}]}),
    'mesh': ({'xy_unit': 'ft', 'z_unit': 'ft', 'z_meaning': 'elevation', 'positive': 'up'}, {},
             {'vertices': [[0.0, 0.0, 10.0], [1.0, 0.0, None], [0.0, 1.0, 12.0]], 'triangles': [[2, 0, 1]], 'attributes': [{'name': 'phi', 'values': [0.1, None, 0.3]}]}),
    'grid': ({'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'ms', 'z_meaning': 'time', 'positive': 'down'},
             {'registration': 'center', 'ncols': 2, 'nrows': 2, 'cell_size': 10.0, 'x_first_center': 1012.5, 'y_first_center': -40.0},
             {'values': [7.0, None, 9.5, 10.0], 'nodata_value': -1.0}),
    'well-tops': ({'depth_unit': 'ft'}, {},
                  {'tops': [{'name': 'Base Chalk', 'md': 5012.0, 'tvd': None, 'source': 'picks 2025'}, {'name': 'NL', 'md': 1650.0, 'tvd': None, 'source': None}]}),
    'deviation': ({'depth_unit': 'ft', 'azimuth_reference': 'true-north'}, {'tvd_provided': True},
                  {'stations': [{'md': 0.0, 'inclination': 0.0, 'azimuth': None, 'tvd': 0.0}, {'md': 820.0, 'inclination': 3.25, 'azimuth': 359.5, 'tvd': 819.5}]}),
    'fault-sticks': ({'xy_unit': 'ft', 'z_unit': 'ft', 'z_meaning': 'depth', 'positive': 'down'}, {},
                     {'sticks': [{'index': 4, 'points': [{'x': 1.0, 'y': 1.0, 'z': 900.0}, {'x': 2.0, 'y': 2.0, 'z': 950.0}]},
                                 {'index': 2, 'points': [{'x': 5.5, 'y': 6.0, 'z': 1000.0}, {'x': 5.5, 'y': 6.5, 'z': 1100.0}]}]}),
    'las': ({}, {}, {'well': 'OTHER-2', 'null': -999.0, 'curves': [('DEPT', 'FT'), ('NPHI', 'V/V')], 'data': [[3000.0, 0.31], [3000.25, None]],
                     'other': 'Processed by hand.'}),
    'well-location': ({}, {'crs': 'OGC:CRS84', 'elevation_reference': 'MSL'}, {'x': 4.5, 'y': 52.25}),
    'wavelet': ({}, {'kind': 'ricker', 'frequency_hz': 25.0, 'corners_hz': None, 'dt': 0.004, 't0': -0.004, 'polarity': 'unknown'}, {'samples': [0.0, 1.0, 0.0]}),
    'model-section': ({}, {'domain': 'time', 'first_sample': 0.5, 'sample_interval': 0.004, 'horizontal': 'trace-number', 'horizontal_first': 101.0,
                           'horizontal_step': 1.0}, {'rocks': [{'index': 3, 'name': 'Salt', 'vp': 4500.0, 'density': 2160.0}], 'grid': [[3, 3]]}),
    'seismic-section': ({}, {'domain': 'depth', 'first_sample': 0.0, 'sample_interval': 5.0, 'horizontal': 'distance', 'horizontal_first': 10.0,
                             'horizontal_step': 12.5, 'origin': 'synthetic', 'polarity': 'impedance-increase-negative'}, {'grid': [[1.0, 2.0], [3.0, -4.5]]}),
    'time-depth': ({'depth_type': 'md', 'depth_unit': 'ft', 'time_kind': 'one-way', 'time_unit': 'ms', 'datum': 'KB', 'seismic_reference_elevation': '12.5'},
                   {'datum': 'KB', 'seismic_reference_elevation': 12.5, 'velocity_provided': False}, {'depth': [100.0, 200.0], 'time': [0.08, 0.15], 'velocity': None}),
}


def processed(tmp_path, word, name, raw, declared):
    """Run the process start for `word` on one input; (run.json's output record, the output's bytes)."""
    folder = tmp_path / 'start'
    if not folder.exists(): templates.make(folder, 'process', word)
    where = tmp_path / f'input-{len(list(tmp_path.iterdir()))}'
    where.mkdir()
    (where / name).write_bytes(raw)
    (where / 'declared.json').write_text(json.dumps(declared))
    out = tmp_path / f'out-{where.name}'
    made = procedures.run(folder, out, {'data': [where / name]}, kinds={'data': PROFILES[word]}, declared={'data': str(where / 'declared.json')})['run']['outputs']['data']
    return made, (out / made['file']).read_bytes()


def read_back(word, raw, declared, keys):
    """The output as Connectors' own readers see it (S1-R2): the context keys asked for, and the data."""
    if word == 'las':
        from asset_connectors.las_reader import read_las
        las = read_las(raw)
        return {}, {'well': las.well['WELL'].value, 'null': float(las.well['NULL'].value), 'curves': [(c.mnemonic, c.unit) for c in las.curves],
                    'data': [[None if v != v else float(v) for v in row] for row in las.data.tolist()], 'other': las.other.strip()}
    from asset_connectors.typed_reader import read_typed
    context, data, _ = read_typed(PROFILES[word], raw, declared)
    return {k: context[k] for k in keys}, data


@pytest.mark.parametrize('word', PROCESSED)
def test_process_starts_make_what_their_input_holds(tmp_path, word):
    made, raw = processed(tmp_path, word, *FOREIGN[word])
    declared, context, data = MADE_FROM[word]
    assert made['profile'] == PROFILES[word] and made['declared'] == declared
    assert read_back(word, raw, made['declared'], context) == (context, data)


@pytest.mark.parametrize('word', ['well-tops', 'deviation', 'time-depth'])
def test_a_process_start_writes_with_its_writer(tmp_path, word):
    name, raw, declared = FOREIGN[word]
    made, out = processed(tmp_path, word, name, raw, declared)
    assert out != raw and read_back(word, out, made['declared'], MADE_FROM[word][1]) == MADE_FROM[word][1:]


LAS = (b'~V\nVERS. 2.0 : LAS\nWRAP. NO : rows\n~W\nSTRT.M 100 : start\nSTOP.M 100.5 : stop\nSTEP.M 0.5 : step\nNULL. -999.25 : missing\n'
       b'WELL. W-1 : well\n%s~C\nDEPT.M : depth\nGR.GAPI : GR\n%s~A\n100 45\n100.5 50\n')


def las(well=b'', curves=b'', **swap):
    raw = LAS % (well, curves)
    for old, new in swap.values(): raw = raw.replace(old, new)
    return raw


def writes(writer, what):
    return f'This start writes with ophiolite.writers.{writer}, which {what}; change the start to say what to keep.'


TOPS_D = {'depth_unit': 'm', 'depth_basis': 'same-as-log'}
REFUSED = [  # one refused part per input (1-M5), each row of the D2 table, with its sentence written out
    ('well-tops', b'name,md,lithology\nNU,1,sand\n', TOPS_D, writes('write_tops', "has no place for the column 'lithology'")),
    ('well-tops', b'name,md\nNU,1\n', {**TOPS_D, 'depth_datum': 'KB'}, writes('write_tops', 'has no place for a depth datum')),
    ('well-tops', b'name,md,tvd\nNU,1,\n', TOPS_D, writes('write_tops', 'writes no tvd column when every tvd cell is empty')),
    ('well-tops', b'name,md,source\nNU,1,\n', TOPS_D, writes('write_tops', 'writes no source column when every source cell is empty')),
    ('deviation', b'md,inclination,azimuth,tvd\n0,0,0,\n', {'depth_unit': 'm', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'},
     writes('write_survey', 'writes no tvd column when every tvd cell is empty')),
    ('time-depth', b'depth,time,velocity\n1,0.1,\n2,0.2,\n', {'depth_type': 'md', 'depth_unit': 'm', 'time_kind': 'one-way', 'time_unit': 's'},
     writes('write_time_depth', 'writes no velocity column when every velocity cell is empty')),
    ('fault-sticks', b'1 2 3 0 0\n1 2 4 0 1\n', {}, writes('write_sticks', 'has no place for a node field')),
    ('grid', b'ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\n5\n', {},
     'This start writes with ophiolite.writers.write_grid, which always writes a NODATA value, and this grid has none; change the start to say what to keep.'),
    ('seismic-section', b'# ophiolite-seismic-section 1\ndomain time\nfirst_sample 0\nsample_interval 0.004\nsamples 1\ntraces 1\nhorizontal trace-number\n'
                        b'horizontal_first 1\nhorizontal_step 1\ngrid\n0.5\n', {}, writes('write_seismic_section', 'always writes a polarity line, and this section has none')),
    ('seismic-section', b'# ophiolite-seismic-section 1\ndomain time\nfirst_sample 0\nsample_interval 0.004\nsamples 1\ntraces 1\nhorizontal trace-number\n'
                        b'horizontal_first 1\nhorizontal_step 1\norigin not-stated\npolarity unknown\ngrid\n0.5\n', {},
     writes('write_seismic_section', "has no place for the line 'origin not-stated'")),
    ('las', las(curves=b'GR.GAPI : GR\n', data=(b'100 45\n100.5 50\n', b'100 45 46\n100.5 50 51\n')), {}, writes('write_curves', "has no place for a second ~Curve line named 'GR'")),
    ('las', las(well=b'WELL. W-2 : well\n'), {}, writes('write_curves', "has no place for a second ~Well line named 'WELL'")),
    ('las', las(well=b'COMP. Ophiolite : company\n'), {}, writes('write_curves', "has no place for the ~Well line 'COMP'")),
    ('las', las(well=b'~P\nRMF.OHMM 0.5 : mud filtrate\n'), {}, writes('write_curves', 'has no place for ~Parameter lines')),
    ('las', las(api=(b'GR.GAPI : GR', b'GR.GAPI 45 310 01 00 : GR')), {}, writes('write_curves', "has no place for the API code of the curve 'GR'")),
    ('las', las(text=(b'GR.GAPI : GR', b'GR.GAPI : gamma ray')), {}, writes('write_curves', "writes its own description of the curve 'GR', not 'gamma ray'")),
    ('las', las(text=(b'STRT.M 100 : start', b'STRT.M 100 : START DEPTH')), {}, writes('write_curves', "writes its own description of the ~Well line 'STRT', not 'START DEPTH'")),
    ('las', las(unit=(b'STOP.M', b'STOP.FT')), {}, writes('write_curves', "writes the ~Well line 'STOP' with the unit 'M', not 'FT'")),
    ('las', las(index=(b'DEPT.M : depth', b'DEPTH.M : depth')), {}, writes('write_curves', "always names the index curve DEPT, and this file names it 'DEPTH'")),
    ('las', las(drop=(b'WELL. W-1 : well\n', b'')), {}, writes('write_curves', 'always writes a WELL line, and this file has none')),
    ('las', las(null=(b'NULL. -999.25', b'NULL. none')), {}, writes('write_curves', "writes a number as the NULL value, not 'none'")),
]


@pytest.mark.parametrize('word,raw,declared,sentence', REFUSED)
def test_a_process_start_refuses_what_its_writer_cannot_write(tmp_path, word, raw, declared, sentence):
    with pytest.raises(procedures.NotRun) as refused: processed(tmp_path, word, 'input', raw, declared)
    assert (refused.value.code, refused.value.details['type'], refused.value.details['message']) == ('raised', 'ValueError', sentence)
    assert not list(tmp_path.glob('out-*'))


def test_an_other_line_the_writer_cannot_write_as_a_note_is_the_writer_s_own_refusal(tmp_path):
    raw = las(other=(b'~A\n', b'~O\n# kept by the reader, refused as a note by write_curves\n~A\n'))
    with pytest.raises(procedures.NotRun) as refused: processed(tmp_path, 'las', 'input', raw, {})
    assert (refused.value.code, refused.value.details['type']) == ('raised', 'ValidationFailed')


# ---------------------------------------------------------------- send: deliver to a folder, recovery (3-D3, 3-M6)

REV_A, REV_B = 'c' * 64, 'd' * 64


class Kinds(Project):
    """test_deliver's project, holding versions of any kind: their bytes, profile and declarations (3-F3)."""
    def __init__(self, root, word):
        super().__init__(root)
        self.word, self.items = word, {}
        sample = json.loads((templates.SAMPLES / f'{word}.json').read_text())
        self.written = {REV_A: templates._written(PROFILES[word], sample)}
        if word == 'well-tops': self.written[REV_B] = writers.write_tops([{'name': 'XX', 'md': 1.5}], depth_unit='m', depth_basis='unknown')
        for asset, rev in (('sample-a', REV_A), ('sample-b', REV_B)):
            if rev in self.written: self.add_item(asset, 'Sample' if rev == REV_A else 'Other', [(rev, '')])

    def read_data(self, asset, revision):
        from types import SimpleNamespace
        self.reads.append((asset, revision))
        written = self.written[revision]
        return SimpleNamespace(original=written.bytes, _wire_data_bytes=b'{}', type=self.word,
                               _wire_descriptor={'profile': written.profile, 'scientific': written.declared, 'history': {'number': 1}})


@pytest.fixture
def sending(tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    monkeypatch.chdir(tmp_path)

    def open_(word):
        w = Kinds(tmp_path, word)
        w.folder = tmp_path / 'procedures' / f'send-{word}'
        templates.make(w.folder, 'send', word)
        w.digest = w.register(w.folder)
        w.dest = tmp_path / 'team-folder'
        w.dest.mkdir()
        w.config = tmp_path / 'dest.json'
        w.config.write_text(json.dumps({'folder': str(w.dest)}))
        w.work = tmp_path / '.ophiolite-held'
        return w
    return open_


def sent(w, items=('data=Sample@1',)):
    return deliver(w, items=list(items), name=f'send-{w.word}', systems={'destination': str(w.config)})


def at_destination(w):
    return {str(p.relative_to(w.dest)): p.read_bytes() for p in sorted(w.dest.rglob('*')) if p.is_file()}


@pytest.mark.parametrize('word', SENT)
def test_every_send_start_delivers_exactly_the_version_and_its_id(sending, word):
    w = sending(word)
    answer = sent(w)
    assert (answer['state'], answer['items']) == ('confirmed', 1), answer
    ident, found = answer['delivery_id'], at_destination(w)
    record = found.pop(f'{ident}/delivery.json')
    assert json.loads(record) == {'id': ident, 'items': 1} and list(found.values()) == [w.written[REV_A].bytes]
    assert [Path(k).parent.name for k in found] == [ident] and Path(next(iter(found))).name.startswith('0-')  # deliver's file name, numbered


def test_a_send_of_two_versions_delivers_both_in_one_folder(sending):
    w = sending('well-tops')
    answer = sent(w, ('data=Sample@1', 'data=Other@1'))
    assert (answer['state'], answer['items']) == ('confirmed', 2)
    found = at_destination(w)
    assert json.loads(found.pop(f"{answer['delivery_id']}/delivery.json")) == {'id': answer['delivery_id'], 'items': 2}
    assert sorted(Path(k).name[:2] for k in found) == ['0-', '1-'] and sorted(found.values()) == sorted([w.written[REV_A].bytes, w.written[REV_B].bytes])


def module_of(folder):
    import importlib.util
    spec = importlib.util.spec_from_file_location('start_under_test', folder / 'procedure.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_parent_stopped_after_the_rename_is_reconciled_to_delivered_without_a_second_send(sending, monkeypatch):
    w = sending('deviation')

    class Stopped(Exception): pass

    def stop(process, folder):
        process.wait()
        raise Stopped()
    monkeypatch.setattr(procedures, '_launched', stop)
    with pytest.raises(Stopped): sent(w)
    monkeypatch.setattr(procedures, '_launched', lambda process, folder: None)
    before = at_destination(w)
    again = sent(w)
    assert (again['state'], again['items']) == ('confirmed', 1) and at_destination(w) == before and len(before) == 2


def test_reconcile_withdraws_an_attempt_stopped_before_its_rename_and_answers_the_same_again(tmp_path):
    templates.make(tmp_path / 'start', 'send', 'well-tops')
    start, system = module_of(tmp_path / 'start'), LocalSystem({'folder': str(tmp_path / 'dest')})
    (tmp_path / 'dest').mkdir()
    attempt = DeliveryAttempt('delivery-9', system)
    (tmp_path / 'dest/.delivery-9.partial').mkdir()
    (tmp_path / 'dest/.delivery-9.partial/0-tops.csv').write_text('name,md\nNU,1\n')  # stopped before its rename: never a delivery
    assert [start.reconcile(attempt) for _ in range(2)] == [ophiolite.not_delivered()] * 2
    version = procedures.LocalVersion(str(tmp_path / 'start/data/tops.csv'), 'well-tops-csv/1', {})
    assert start.main({'data': [version]}, {}, attempt) == ophiolite.refused('This delivery was withdrawn at the destination.')
    assert sorted(p.name for p in (tmp_path / 'dest/delivery-9').iterdir()) == ['WITHDRAWN']
    done = DeliveryAttempt('delivery-10', system)
    assert start.main({'data': [version]}, {}, done) == ophiolite.delivered(items=1)
    assert [start.reconcile(done) for _ in range(2)] == [ophiolite.delivered(items=1)] * 2
    (tmp_path / 'dest/delivery-10/delivery.json').write_text(json.dumps({'id': 'delivery-other', 'items': 1}))
    assert start.reconcile(done) == ophiolite.unknown()  # a folder that is not this delivery's says nothing
    shutil.rmtree(tmp_path / 'dest')
    assert start.main({'data': [version]}, {}, DeliveryAttempt('delivery-11', system)) == ophiolite.refused('The destination folder does not exist.')


# ---------------------------------------------------------------- check: tolerance below, at and above; unmatched; units (3-M5)

def checked(tmp_path, word, data, reference, settings=('tolerance=0.5',), units=('m', 'm')):
    folder = tmp_path / f'check-{word}'
    if not folder.exists(): templates.make(folder, 'check', word)
    paths = []
    for name, values_, unit in (('data', data, units[0]), ('reference', reference, units[1])):
        if word == 'well-tops': written = writers.write_tops(values_, depth_unit=unit, depth_basis='same-as-log')
        else: written = writers.write_survey(values_, depth_unit=unit, azimuth_reference='grid-north', depth_datum='KB')
        path = tmp_path / f'{name}-{len(list(tmp_path.iterdir()))}.csv'
        path.write_bytes(written.bytes)
        paths.append(procedures.ProjectInput(str(path), PROFILES[word], written.declared, f'{name}-item', ('a' if name == 'data' else 'b') * 64))
    out = tmp_path / f'out-{len(list(tmp_path.iterdir()))}'
    report = procedures.run(folder, out, {'data': [paths[0]], 'reference': [paths[1]]}, settings=list(settings))['report']
    return report['outcome'], report.get('counts')


TOPS = [{'name': 'NU', 'md': 1203.5}, {'name': 'NL', 'md': 1650.25}]


def tops(nu):
    return [{'name': 'NU', 'md': nu}, {'name': 'NL', 'md': 1650.25}]


def test_the_tops_check_uses_its_tolerance_below_at_and_above(tmp_path):
    assert checked(tmp_path, 'well-tops', TOPS, tops(1203.9)) == ('passed', {'compared': 2, 'differed': 0})
    assert checked(tmp_path, 'well-tops', TOPS, tops(1204.0)) == ('passed', {'compared': 2, 'differed': 0})  # at the tolerance still matches
    assert checked(tmp_path, 'well-tops', TOPS, tops(1204.1)) == ('differed', {'compared': 2, 'differed': 1})
    assert checked(tmp_path, 'well-tops', TOPS, tops(1204.1), settings=()) == ('passed', {'compared': 2, 'differed': 0})  # default 1.0
    assert checked(tmp_path, 'well-tops', TOPS, TOPS + [{'name': 'NM', 'md': 1421.0}]) == ('differed', {'compared': 3, 'differed': 1})
    assert checked(tmp_path, 'well-tops', TOPS + [{'name': 'NM', 'md': 1421.0}], TOPS) == ('differed', {'compared': 3, 'differed': 1})
    assert checked(tmp_path, 'well-tops', TOPS, TOPS, units=('m', 'ft')) == ('not_compared', None)


def stations(inclination, azimuth=45.0):
    return [{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0}, {'md': 500.0, 'inclination': inclination, 'azimuth': azimuth}]


def test_the_survey_check_uses_its_tolerance_wraps_azimuths_and_counts_missing_angles(tmp_path):
    word, mine = 'deviation', stations(12.5)
    assert checked(tmp_path, word, mine, stations(12.9)) == ('passed', {'compared': 2, 'differed': 0})
    assert checked(tmp_path, word, mine, stations(13.0)) == ('passed', {'compared': 2, 'differed': 0})
    assert checked(tmp_path, word, mine, stations(13.1)) == ('differed', {'compared': 2, 'differed': 1})
    assert checked(tmp_path, word, stations(12.5, 359.8), stations(12.5, 0.2)) == ('passed', {'compared': 2, 'differed': 0})  # 0.4 degrees apart
    assert checked(tmp_path, word, mine, stations(None)) == ('differed', {'compared': 2, 'differed': 1})
    assert checked(tmp_path, word, mine, mine + [{'md': 900.0, 'inclination': 20.0, 'azimuth': 50.0}]) == ('differed', {'compared': 3, 'differed': 1})
    assert checked(tmp_path, word, mine, mine, units=('m', 'ft')) == ('not_compared', None)
