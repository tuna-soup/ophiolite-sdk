"""E129 sb C2: `ophiolite starter export` (strategy rev 3, section 5: A2-A6).

The survey archive is a zip of `Syn_Survey/` that the fake odbind of `ophiolite-opendtect/tests/fake_odbind` reads; the
real exporter (`ophiolite_opendtect.export`) runs on it in its own process, in this interpreter, as it runs in
OpendTect's. `conformance/fixtures/starter-archive/stub` stands in for it where the exporter must fail. Every expected
value is a literal: the WGS84 positions were computed once with the 6th-order Krueger series of Karney (2011), the
series GeographicLib's TransverseMercator uses (not pyproj), and written here at 9 decimals. It is a gateway module
because it reads the connector and the fixtures from the monorepo, above the SDK tree."""
import fcntl
import hashlib
import io
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from ophiolite import starter, starter_archive as sa
from ophiolite.errors import Refused

pytest.importorskip('numpy')
pytest.importorskip('pyproj')
pytest.importorskip('lasio')

ROOT = Path(__file__).resolve().parents[3]
FAKE, CONNECTOR = ROOT / 'ophiolite-opendtect/tests/fake_odbind', ROOT / 'ophiolite-opendtect/src'
STUB = ROOT / 'conformance/fixtures/starter-archive/stub'
SCHEMA = ROOT / 'conformance/fixtures/osd/starter.schema.json'
RID, PACK, ARCHIVE = 'ophiolite-synthetic/survey', 'ophiolite-synthetic/survey/starter', 'syn-survey.zip'
URL = 'https://data.example.org/synthetic/syn-survey.zip'
RUN = {'checked_at': '2026-10-29T00:00:00Z', 'tool_version': '0.9.0'}
APACHE = {'name': 'Apache License 2.0', 'spdx': 'Apache-2.0', 'url': 'https://www.apache.org/licenses/LICENSE-2.0', 'redistribution': 'allowed', 'attribution': 'required'}
CONTENTS = [{'kind': 'seismic-3d', 'ids': ['Syn', 'Syn2']}, {'kind': 'horizons', 'ids': ['Top']},
            {'kind': 'wellbore-paths', 'ids': ['SYN-A', 'SYN-B']}, {'kind': 'wellbore-logs', 'ids': ['SYN-A', 'SYN-B']}]
VOLUME = {'crs': 'EPSG:32631', 'domain': 'time', 'units': 'ms'}
WELL = {'crs': 'EPSG:32631', 'vertical-datum': 'SRD', 'depth-reference': 'SRD', 'depth-kind': 'MD', 'units': 'm', 'nulls': '-999.25', 'names': 'as in the survey'}
FILES = ['seismic/Syn.sgy', 'seismic/Syn2.sgy', 'horizons/Top.csv', 'wells/SYN-A-positions.csv', 'wells/SYN-A.las', 'wells/SYN-B-positions.csv']
# Krueger series (Karney 2011), EPSG:32631 -> WGS84, longitude first
RINGS = {'Syn': [[3.00000337, 0.000001131], [3.001351382, 0.000001131], [3.001351382, 0.001358228], [3.00000337, 0.001358228], [3.00000337, 0.000001131]],
         'Syn2': [[3.000452707, 0.000453497], [3.000902045, 0.000453497], [3.000902045, 0.000905862], [3.000452707, 0.000905862], [3.000452707, 0.000453497]]}
HEADS = {'SYN-A': [3.000090991, 0.000093866], 'SYN-B': [3.000674006, 0.000452366]}


def sha(raw): return hashlib.sha256(raw).hexdigest()


def zipped(members=None):
    """The survey archive: Syn_Survey/ with its .survey and .defs, fixed dates, in this order."""
    members = members if members is not None else [('Syn_Survey/', b''), ('Syn_Survey/.survey', b'Name: Syn_Survey\nSeismic Reference Datum: 0\n'),
                                                   ('Syn_Survey/.defs', b'Depth in feet: No\n')]
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, raw in members:
            info = zipfile.ZipInfo(name, (2026, 10, 29, 0, 0, 0))
            if name.endswith('/'): info.external_attr = 0o40755 << 16
            z.writestr(info, raw)
    return out.getvalue()


def decisions(volume=VOLUME, well=WELL, step='0.15'):
    rows = [{'topic': t, 'subject': x, 'value': v, 'source': 'data'} for x in ('Syn', 'Syn2', 'Top') for t, v in dict(volume, nulls=None).items()]
    for r in rows:
        if r['topic'] == 'nulls': r['value'] = sa.NULLS['horizons' if r['subject'] == 'Top' else 'seismic-3d']
    rows += [{'topic': t, 'subject': w, 'value': v, 'source': 'data'} for w in ('SYN-A', 'SYN-B') for t, v in well.items()]
    return rows + [{'topic': 'units', 'subject': ARCHIVE, 'value': step, 'source': 'chosen', 'note': 'the log step in metres'}]


def made(folder, edit=None, raw=None):
    """A definition folder: the archive, the definition, the catalogue record, its verification."""
    raw = zipped() if raw is None else raw
    (folder / 'inputs').mkdir(parents=True, exist_ok=True)
    (folder / 'inputs' / ARCHIVE).write_bytes(raw)
    archive = {'name': ARCHIVE, 'sha256': sha(raw)}
    defn = {'format': starter.DEFINITION, 'id': PACK, 'record_id': RID, 'title': 'A synthetic survey', 'summary': 'Two cubes, a horizon and two wells.',
            'built_at': '2026-10-29T00:00:00Z', 'recipe': {'id': 'ophiolite.starter/b', 'repository': 'https://github.com/ophiolite-labs/arraybridge', 'commit': 'b' * 40},
            'inputs': [{'name': ARCHIVE, 'file': 'inputs/' + ARCHIVE, 'sha256': archive['sha256'], 'bytes': len(raw),
                        'held': {'as': 'verified', 'verifier_run': dict(RUN), 'path': 'data/' + ARCHIVE},
                        'archive': {'survey': 'Syn_Survey', 'log_step': 0.15,
                                    'outline_input': {'name': 'survey-archive', 'url': URL, 'sha256': sa.outline_sums(archive)}}}],
            'contents': json.loads(json.dumps(CONTENTS)), 'decisions': decisions(), 'targets': ['opendtect']}  # E129 sc D6: an archive pack's one target
    if edit: edit(defn)
    (folder / 'definition.json').write_text(json.dumps(defn))
    (folder / 'records.json').write_text(json.dumps({'catalog': {'source_commit': None, 'verification_commit': None, 'built_at': '2026-10-29T00:00:00Z', 'records_digest': 'd' * 64},
                                                     'records': [{'id': RID, 'title': 'A synthetic survey', 'licence': dict(APACHE),
                                                                  'inputs': [{'name': 'survey-archive', 'url': URL}]}]}))
    (folder / 'verification').mkdir(exist_ok=True)
    (folder / 'verification' / 'ophiolite-synthetic__survey.json').write_text(json.dumps(
        {'record_id': RID, **RUN, 'level': 2, 'checks': [], 'files': [{'path': 'data/' + ARCHIVE, 'bytes': len(raw), 'sha256': sha(raw)}]}))
    (folder / 'custody').mkdir(exist_ok=True)
    return folder


def run(folder, out, **kw):
    kw = {'python': sys.executable, **kw}
    return sa.export(folder / 'definition.json', out, catalogue=folder / 'records.json', verification=folder / 'verification', custody=folder / 'custody', **kw)


def refused(fn, *args, **kw):
    with pytest.raises(Refused) as caught: fn(*args, **kw)
    return str(caught.value)


def tree(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(Path(path).rglob('*')) if p.is_file()}


@pytest.fixture
def real(monkeypatch):
    """The real exporter on the fake odbind, in its own process."""
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
    monkeypatch.delenv('FAKE_ODBIND_VARIANT', raising=False)
    monkeypatch.delenv('STUB_EXPORT', raising=False)
    return monkeypatch


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setenv('PYTHONPATH', str(STUB))
    def mode(m): monkeypatch.setenv('STUB_EXPORT', m)
    return mode


@pytest.fixture(scope='module')
def exported_once(tmp_path_factory):
    """One real export: (definition folder, OUT, report, export folder, export.json)."""
    folder, out = made(tmp_path_factory.mktemp('definition')), tmp_path_factory.mktemp('out')
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
        report, export = run(folder, out)
    return folder, out, report, export


def staged(tmp_path, exported_once):
    """A copy of the real export's files, as the exporter left them (without the outline the SDK adds)."""
    folder, _, report, export = exported_once
    stage = tmp_path / 'stage'
    shutil.copytree(export / 'files', stage)
    (stage / 'outline.geojson').unlink()
    return stage, json.loads((stage / 'export.json').read_text()), sa.definition(folder / 'definition.json')


# --- A2, A4: the real exporter, read back, outline and publication -------------------------------------------------

def test_the_real_exporter_feeds_read_back_and_publication(exported_once):
    folder, out, report, export = exported_once
    assert json.loads((out / 'derived.json').read_text()) == {'export': 'exports/' + export.name}
    assert json.loads((export / 'derived.json').read_text()) == report
    assert [f['path'] for f in report['files']] == FILES and [d['path'] for d in report['derived']] == FILES  # E129 sc C1: the outline is not derived
    assert (export / 'files/outline.geojson').is_file()
    archive = sha((folder / 'inputs' / ARCHIVE).read_bytes())
    assert report['archive'] == {'name': ARCHIVE, 'sha256': archive} and {d['from'] for d in report['derived']} == {archive}
    for d in report['derived']: assert (d['sha256'], d['bytes']) == (sha((export / 'files' / d['path']).read_bytes()), len((export / 'files' / d['path']).read_bytes()))
    assert [(d['path'], d['bytes']) for d in report['derived'][:2]] == [('seismic/Syn.sgy', 3600 + 16 * (240 + 4 * 5)), ('seismic/Syn2.sgy', 3600 + 4 * (240 + 4 * 5))]
    assert (export / 'files/horizons/Top.csv').read_text().splitlines()[:2] == ['x,y,z,inline,crossline', '500000.38,0.12,105.0,10,20']
    assert len((export / 'files/horizons/Top.csv').read_text().splitlines()) == 17  # the header and all 16 nodes, one with an empty z
    assert (export / 'files/wells/SYN-B-positions.csv').read_text() == 'md,x,y,tvdss\n0.0,500075.0,50.0,-10.0\n50.0,500075.0,50.0,40.0\n100.0,500076.5,51.25,89.75\n'
    assert report['not_read'] == [{'kind': 'wellbore-logs', 'name': 'SYN-B', 'reason': report['not_read'][0]['reason']}]
    assert (report['record_id'], report['definition'], report['outline']) == (RID, sha((folder / 'definition.json').read_bytes()), 'outline.geojson')
    assert not (export / 'work').exists()


def test_derived_items_validate_against_the_pinned_starter_schema(exported_once):
    import jsonschema
    schema = json.loads(SCHEMA.read_text())
    items = {'$defs': schema['$defs'], **schema['properties']['derived']}
    jsonschema.validate(exported_once[2]['derived'], items)
    assert all(len(d['how']) <= 300 for d in exported_once[2]['derived'])


def test_the_outline_is_two_polygons_and_two_points_at_the_literal_positions(exported_once):
    from pyproj import Transformer
    _, _, _, export = exported_once
    o = json.loads((export / 'files/outline.geojson').read_text())
    assert [round(v, 9) for v in Transformer.from_crs('EPSG:32631', 'EPSG:4326', always_xy=True).transform(500000, 0)] == [3.0, 0.0]  # at 9 decimals
    assert (o['type'], o['licence']) == ('FeatureCollection', 'Apache-2.0')
    assert o['inputs'] == {'survey-archive': {'url': URL, 'sha256': sa.outline_sums({'name': ARCHIVE, 'sha256': sha((exported_once[0] / 'inputs' / ARCHIVE).read_bytes())})}}
    polygons = {f['properties']['name']: f['geometry'] for f in o['features'] if f['properties']['kind'] == 'survey-3d'}
    points = {f['properties']['name']: f['geometry'] for f in o['features'] if f['properties']['kind'] == 'wellbore'}
    assert {n: g['coordinates'] for n, g in polygons.items()} == {n: [r] for n, r in RINGS.items()} and {g['type'] for g in polygons.values()} == {'Polygon'}
    assert {n: g['coordinates'] for n, g in points.items()} == HEADS and {g['type'] for g in points.values()} == {'Point'}
    for ring in RINGS.values():  # closed, perimeter order (not a bow tie): the signed area of the ring has one sign at every corner
        assert ring[0] == ring[-1]
        turns = [(b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) for a, b, c in zip(ring, ring[1:], ring[2:] + ring[1:2])]
        assert all(t > 0 for t in turns)
    for f in o['features']:
        p = f['properties']
        assert p == {'record_id': RID, 'kind': p['kind'], 'name': p['name'], 'approximate': False, 'source': sa.SOURCE,
                     'feature_id': '%s#%s/%s' % (RID, p['kind'], p['name']), 'input': 'survey-archive'}


def test_a_well_head_moved_one_metre_moves_its_point(tmp_path, exported_once):
    stage, doc, defn = staged(tmp_path, exported_once)
    doc['wells']['SYN-B']['x'] += 1
    lic = {'spdx': 'Apache-2.0', 'name': APACHE['name']}
    moved = {f['properties']['name']: f['geometry']['coordinates'] for f in sa.outline(defn, doc, lic)['features']}
    assert moved['SYN-B'] != HEADS['SYN-B'] and moved['SYN-A'] == HEADS['SYN-A']


# --- A3: mutations, each refused naming its file ---------------------------------------------------------------------

def poke(path, offset, fmt, value):
    raw = bytearray(path.read_bytes()); raw[offset:offset + __import__('struct').calcsize(fmt)] = __import__('struct').pack(fmt, value); path.write_bytes(bytes(raw))


def text(path, old, new, count=1):
    body = path.read_text()
    assert old in body
    path.write_text(body.replace(old, new, count))


def rows(path, edit):
    lines = path.read_text().splitlines(); edit(lines); path.write_text(''.join(l + '\n' for l in lines))


T1 = 3600 + 260  # the second trace of Syn.sgy
MUTATIONS = {
    'sample': ('seismic/Syn.sgy', lambda p: poke(p, T1 + 240, '>f', 999.0)),
    'crossline': ('seismic/Syn.sgy', lambda p: poke(p, T1 + 192, '>i', 99)),
    'scalar': ('seismic/Syn.sgy', lambda p: poke(p, 3600 + 70, '>h', -10)),
    'interval': ('seismic/Syn2.sgy', lambda p: poke(p, 3200 + 16, '>H', 3000)),
    'delay': ('seismic/Syn.sgy', lambda p: poke(p, T1 + 108, '>h', 101)),
    'x-truncated': ('seismic/Syn.sgy', lambda p: poke(p, 3600 + 180, '>i', 50000037)),
    'las-unit': ('wells/SYN-A.las', lambda p: text(p, 'GR.API', 'GR.GAPI')),
    'las-step': ('wells/SYN-A.las', lambda p: text(p, 'STEP.M 0.15', 'STEP.M 0.16')),
    # E129 sc C1: the horizon is points-csv/1 (line 0 the header; inline is column 3, z column 2)
    'horizon-inline': ('horizons/Top.csv', lambda p: rows(p, lambda ls: ls.__setitem__(1, ','.join(ls[1].split(',')[:3] + ['11'] + ls[1].split(',')[4:])))),
    'horizon-mask': ('horizons/Top.csv', lambda p: rows(p, lambda ls: ls.__setitem__(6, ','.join(ls[6].split(',')[:2] + [''] + ls[6].split(',')[3:])))),
    'horizon-row-dropped': ('horizons/Top.csv', lambda p: rows(p, lambda ls: ls.pop(5))),
    'horizon-header': ('horizons/Top.csv', lambda p: text(p, 'x,y,z,inline,crossline', 'X Y Inline Crossline Z')),
    'station-dropped': ('wells/SYN-A-positions.csv', lambda p: rows(p, lambda ls: ls.pop())),
}


@pytest.mark.parametrize('mutation', sorted(MUTATIONS))
def test_a_changed_file_is_refused_naming_it(tmp_path, exported_once, mutation):
    stage, doc, defn = staged(tmp_path, exported_once)
    assert sa.read_back(stage, doc, defn) is None
    path, mutate = MUTATIONS[mutation]
    mutate(stage / path)
    assert path in refused(sa.read_back, stage, doc, defn)


def test_las_mnemonics_keep_their_case(tmp_path):
    """lasio upper-cases mnemonics unless told otherwise (found on the live run, where odbind's names are mixed case)."""
    path = tmp_path / 'w.las'
    path.write_text('~Version\n VERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0\n WRAP.   NO : ONE LINE PER DEPTH STEP\n~Well\n'
                    ' STRT.M 10.0 : first depth\n STOP.M 10.5 : last depth\n STEP.M 0.5 : depth step\n NULL. -999.25 : null value\n WELL. W : well\n'
                    '~Curve\n DEPT.M : measured depth\n Gamma_Ray.API : Gamma Ray\n~ASCII\n10.0 -999.25\n10.5 61.0\n')
    axes, _ = sa.read_las(path, {'path': 'wells/W.las', 'kind': 'wellbore-logs', 'object': 'W', 'axes': None})
    assert axes == {'md': [10.0, 10.5, 2], 'step': 0.5, 'curves': [['Gamma_Ray', 'API']]}


def test_export_json_must_list_exactly_the_files_written(tmp_path, exported_once):
    stage, doc, defn = staged(tmp_path, exported_once)
    (stage / 'seismic/more.sgy').write_bytes(b'')
    assert refused(sa.read_back, stage, doc, defn) == 'The export wrote files that export.json does not list, or lists files it did not write.' + sa.NOTHING
    (stage / 'seismic/more.sgy').unlink()
    doc['not_read'] = []
    assert refused(sa.read_back, stage, doc, defn) == 'The export says nothing of wellbore-logs SYN-B.' + sa.NOTHING
    doc = json.loads((stage / 'export.json').read_text())
    doc['cubes']['Syn2']['inline'] = [12, 16, 2]
    assert 'the cube ranges or corners in export.json are not its own' in refused(sa.read_back, stage, doc, defn)


# --- A5: publication and recovery -------------------------------------------------------------------------------------

def published(tmp_path, exported_once, stub):
    """A first export through the stub (copying the real export's files): (definition folder, OUT, pointer, first folder's tree)."""
    stage, _, _ = staged(tmp_path, exported_once)
    folder, out = made(tmp_path / 'definition'), tmp_path / 'out'
    stub('copy:' + str(stage))
    _, first = run(folder, out)
    return folder, out, (out / 'derived.json').read_bytes(), first, tree(first)


def unchanged(out, pointer, first, files):
    assert (out / 'derived.json').read_bytes() == pointer and tree(first) == files


def test_a_second_export_replaces_the_pointer_and_leaves_the_first_folder(tmp_path, exported_once, stub):
    folder, out, pointer, first, files = published(tmp_path, exported_once, stub)
    made(folder, edit=lambda d: d.update(title='The synthetic survey again'))
    report, second = run(folder, out)
    assert second != first and json.loads((out / 'derived.json').read_text()) == {'export': 'exports/' + second.name}
    assert tree(first) == files and report['definition'] == sha((folder / 'definition.json').read_bytes())


@pytest.mark.parametrize('mode, timeout, sentence', [
    ('refuse', sa.TIMEOUT, 'The export stopped: The cube Syn has 2 components; the export writes one.'),
    ('die', sa.TIMEOUT, 'The export stopped: (no message).'),
    ('sleep', 2, 'The export did not finish within 2 seconds.'),
    ('malformed', sa.TIMEOUT, 'The export wrote no export.json of its form (ophiolite.opendtect-export/1).'),
], ids=['refuse', 'die', 'timeout', 'malformed'])
def test_an_exporter_that_fails_leaves_the_previous_export(tmp_path, exported_once, stub, mode, timeout, sentence):
    folder, out, pointer, first, files = published(tmp_path, exported_once, stub)
    stub(mode)
    assert refused(run, folder, out, timeout=timeout) == sentence + sa.NOTHING
    unchanged(out, pointer, first, files)


def test_an_unlisted_file_from_the_exporter_is_refused(tmp_path, exported_once, stub):
    folder, out, pointer, first, files = published(tmp_path, exported_once, stub)
    stub('extra:' + str(tmp_path / 'stage'))
    assert refused(run, folder, out) == 'The export wrote files that export.json does not list, or lists files it did not write.' + sa.NOTHING
    unchanged(out, pointer, first, files)


def test_a_process_killed_before_the_pointer_moves_leaves_the_old_pointer(tmp_path, exported_once, stub):
    folder, out, pointer, first, files = published(tmp_path, exported_once, stub)
    made(folder, edit=lambda d: d.update(title='Killed before the pointer'))
    code = ('import os, signal, sys\nfrom pathlib import Path\nfrom ophiolite import starter_archive as sa\n'
            'out, f, real = Path(sys.argv[2]), Path(sys.argv[1]), sa.replaced\n'
            'def replaced(p, raw):\n    if Path(p) == out / "derived.json": os.kill(os.getpid(), signal.SIGKILL)\n    real(p, raw)\n'
            'sa.replaced = replaced\n'
            'sa.export(f / "definition.json", out, catalogue=f / "records.json", verification=f / "verification", custody=f / "custody", python=sys.executable)\n')
    done = subprocess.run([sys.executable, '-c', code, str(folder), str(out)], capture_output=True, text=True, timeout=600)
    assert done.returncode == -signal.SIGKILL, done.stderr
    unchanged(out, pointer, first, files)
    assert len(list((out / 'exports').iterdir())) == 2 and not (out / '.derived.json.writing').exists()


def test_a_held_lock_refuses(tmp_path, exported_once, stub):
    folder, out, pointer, first, files = published(tmp_path, exported_once, stub)
    with open(out / '.lock', 'a+') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert refused(run, folder, out) == 'Another export holds %s; wait for it to finish.' % (out / '.lock') + sa.NOTHING
    unchanged(out, pointer, first, files)


def test_only_stale_unpublished_folders_are_removed(tmp_path, exported_once, stub):
    folder, out, pointer, first, files = published(tmp_path, exported_once, stub)
    old, recent = out / 'exports/20261027T000000Z-1', out / 'exports/20261029T000000Z-9'
    for p in (old, recent): (p / 'files').mkdir(parents=True)
    day = time.time() - 25 * 3600
    for p in (old, first): os.utime(p, (day, day))
    run(folder, out)
    assert not old.exists() and recent.exists() and tree(first) == files


@pytest.mark.parametrize('case, sentence', [
    ('interpreter', 'The OpendTect connector interpreter /nonexistent/python cannot be started.'),
    ('digest', 'syn-survey.zip is not the file the definition names: its SHA-256 differs.'),
    ('evidence', 'input syn-survey.zip: no verification of ophiolite-synthetic/survey.'),
    ('outline-name', 'outline_input other-input is not an input of record ophiolite-synthetic/survey.'),
    ('outline-url', 'outline_input url https://data.example.org/other.zip is not the url record ophiolite-synthetic/survey states for survey-archive.'),
    ('outline-digest', 'outline_input sha256 is not the archive fetched as input survey-archive.'),
])
def test_missing_or_unbound_evidence_is_refused_before_the_exporter(tmp_path, exported_once, stub, case, sentence):
    folder, out, pointer, first, files = published(tmp_path, exported_once, stub)
    outline = lambda **k: (lambda d: d['inputs'][0]['archive']['outline_input'].update(k))
    kw = {}
    if case == 'interpreter': kw['python'] = '/nonexistent/python'
    if case == 'digest': (folder / 'inputs' / ARCHIVE).write_bytes(zipped()[:-1] + b'\1')
    if case == 'evidence': (folder / 'verification' / 'ophiolite-synthetic__survey.json').unlink()
    if case == 'outline-name': made(folder, edit=outline(name='other-input'))
    if case == 'outline-url': made(folder, edit=outline(url='https://data.example.org/other.zip'))
    if case == 'outline-digest': made(folder, edit=outline(sha256='0' * 64))
    stub('sleep')  # never reached
    assert refused(run, folder, out, **kw) == sentence + sa.NOTHING
    unchanged(out, pointer, first, files)


def member(name, raw=b'', mode=None):
    info = zipfile.ZipInfo('x', (2026, 10, 29, 0, 0, 0)); info.filename = name
    if mode is not None: info.external_attr = mode << 16
    return info, raw


def archive(tmp_path, members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for info, raw in members: z.writestr(info, raw)
    (tmp_path / 'a.zip').write_bytes(out.getvalue())
    (tmp_path / 'x').mkdir()
    return tmp_path / 'a.zip', tmp_path / 'x'


SURVEY = [member('Syn_Survey/.survey', b'Name: Syn_Survey\n')]


@pytest.mark.parametrize('members, sentence', [
    (SURVEY + [member('../x', b'1')], 'The archive member ../x is not a relative path inside the archive.'),
    (SURVEY + [member('/abs', b'1')], 'The archive member /abs is not a relative path inside the archive.'),
    (SURVEY + [member('Syn_Survey/link', b'/etc/passwd', 0o120777)], 'The archive member Syn_Survey/link is a link or a special file.'),
    (SURVEY + SURVEY, 'The archive member Syn_Survey/.survey appears twice.'),
    (SURVEY + [member('Syn_Survey/a'), member('Syn_Survey/b')], 'The archive has 3 members; at most 2 are read.'),
    ([member('Other/.survey', b'')], 'The archive holds no survey folder Syn_Survey.'),
], ids=['parent', 'absolute', 'symlink', 'duplicate', 'members', 'no-survey'])
def test_an_archive_outside_the_bounds_is_refused(tmp_path, monkeypatch, members, sentence):
    monkeypatch.setattr(sa, 'MEMBERS', 2)
    with pytest.warns(UserWarning) if 'twice' in sentence else __import__('contextlib').nullcontext():
        path, dest = archive(tmp_path, members)
    assert refused(sa.extracted, path, dest, 'Syn_Survey') == sentence + sa.NOTHING
    assert not any(dest.rglob('*'))


def test_an_unsafe_archive_leaves_the_previous_export(tmp_path, exported_once, stub):
    folder, out, pointer, first, files = published(tmp_path, exported_once, stub)
    path, _ = archive(tmp_path, SURVEY + [member('../x', b'1')])
    made(folder, raw=path.read_bytes())
    assert refused(run, folder, out) == 'The archive member ../x is not a relative path inside the archive.' + sa.NOTHING
    unchanged(out, pointer, first, files)


# --- A6: decisions ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('topic', ['crs', 'domain', 'units', 'nulls'])
def test_each_volume_topic_is_required(tmp_path, topic):
    folder = made(tmp_path, edit=lambda d: d.update(decisions=[r for r in d['decisions'] if (r['topic'], r['subject']) != (topic, 'Syn2')]))
    assert refused(sa.definition, folder / 'definition.json') == 'Decision %s for Syn2 (seismic-3d) is missing.' % topic + sa.NOTHING


@pytest.mark.parametrize('topic, subject, value, said', [
    ('crs', 'Syn', 'EPSG:23031', 'EPSG:32631'), ('domain', 'Top', 'depth', 'time'), ('units', 'Syn2', 's', 'ms'),
    ('nulls', 'Syn', 'undefined omitted', 'non-finite refused'), ('crs', 'SYN-A', 'EPSG:23031', 'EPSG:32631'), ('units', 'SYN-B', 'ft', 'm')])
def test_a_decision_the_survey_contradicts_is_refused(tmp_path, exported_once, stub, topic, subject, value, said):
    stage, _, _ = staged(tmp_path, exported_once)
    def edit(d):
        for r in d['decisions']:
            if (r['topic'], r['subject']) == (topic, subject): r['value'] = value
    folder = made(tmp_path / 'definition', edit=edit)
    stub('copy:' + str(stage))
    assert refused(run, folder, tmp_path / 'out') == 'Decision %s for %s is %s; the survey says %s.' % (topic, subject, value, said) + sa.NOTHING
    assert not (tmp_path / 'out' / 'derived.json').exists()


@pytest.mark.parametrize('step', [0, -1, float('nan'), 11, '0.15', True], ids=['zero', 'negative', 'nan', 'eleven', 'text', 'bool'])
def test_the_log_step_is_a_number_of_metres_up_to_ten(tmp_path, step):
    folder = made(tmp_path, edit=lambda d: d['inputs'][0]['archive'].update(log_step=step))
    assert refused(sa.definition, folder / 'definition.json') == 'The pack definition archive log_step must be a number of metres in (0, 10].' + sa.NOTHING


@pytest.mark.parametrize('value, source', [('0.2', 'chosen'), ('0.15', 'data')])
def test_the_units_decision_is_the_log_step_chosen(tmp_path, value, source):
    def edit(d):
        for r in d['decisions']:
            if r['subject'] == ARCHIVE: r.update(value=value, source=source)
    folder = made(tmp_path, edit=edit)
    assert refused(sa.definition, folder / 'definition.json') == 'Decision units for syn-survey.zip must be the log step, 0.15 m, chosen with its note.' + sa.NOTHING


def test_a_decision_on_the_archive_other_than_units_is_refused(tmp_path):
    folder = made(tmp_path, edit=lambda d: d['decisions'].append({'topic': 'crs', 'subject': ARCHIVE, 'value': 'EPSG:32631', 'source': 'data'}))
    assert refused(sa.definition, folder / 'definition.json') == 'Decision crs names the archive syn-survey.zip; only units (the log step) may.' + sa.NOTHING


def test_a_depth_survey_has_its_cubes_not_read(tmp_path, real):
    real.setenv('FAKE_ODBIND_VARIANT', 'depth')
    def edit(d):
        d['decisions'] = decisions(volume={'crs': 'EPSG:32631', 'domain': 'depth', 'units': 'm'})
        d['decisions'] += [{'topic': 'velocity', 'subject': x, 'value': 'none: the survey is in depth', 'source': 'data'} for x in ('Syn', 'Syn2', 'Top')]
    folder = made(tmp_path / 'definition', edit=edit)
    report, _ = run(folder, tmp_path / 'out')
    assert [f['path'] for f in report['files']] == ['horizons/Top.csv', 'wells/SYN-A-positions.csv', 'wells/SYN-A.las', 'wells/SYN-B-positions.csv']
    assert [(n['kind'], n['name']) for n in report['not_read']] == [('seismic-3d', 'Syn'), ('seismic-3d', 'Syn2'), ('wellbore-logs', 'SYN-B')]


def test_export_runs_offline_from_the_command_line(tmp_path, exported_once, stub, monkeypatch, capsys):
    from ophiolite import cli
    stage, _, _ = staged(tmp_path, exported_once)
    folder, out = made(tmp_path / 'definition'), tmp_path / 'out'
    stub('copy:' + str(stage))
    monkeypatch.setattr(cli, '_load', lambda: pytest.fail('export read the configuration'))
    monkeypatch.setenv(sa.ENV, sys.executable)
    cli.main(['starter', 'export', str(folder / 'definition.json'), '--out', str(out), '--catalogue', str(folder / 'records.json'),
              '--verification', str(folder / 'verification'), '--custody', str(folder / 'custody')])
    pointer = json.loads((out / 'derived.json').read_text())['export']
    assert capsys.readouterr().out == 'Exported %s in %s: 6 derived files, 1 objects not read; derived.json points to it.\n' % (RID, out / pointer)  # E129 sc C1: no outline


def test_build_refuses_the_export_definition_first(tmp_path):
    """E129 sc C1: build takes an archive definition only with --export (test_starter_archive_pack); without it, Sa's
    definition still refuses it first, now naming the flag."""
    folder = made(tmp_path)
    assert refused(starter.definition, folder / 'definition.json') == \
        'The pack definition has an archive input: run ophiolite starter export on it, then build with --export OUT.' + starter.NOTHING_SENT


def test_an_archive_definition_names_the_opendtect_target(tmp_path):
    """E129 sc D6: an archive pack's first target is OpendTect; (e) D4: the pack notebook may follow it; a wells pack keeps
    python (test_starter)."""
    sentence = ('The pack definition targets must be ["opendtect"], ["opendtect", "python"], ["opendtect", "resinsight"] or ["opendtect", "python", '
                '"resinsight"] for an archive in this version.' + sa.NOTHING)  # E129 (d) D3
    for targets in (['python'], ['python', 'opendtect'], ['opendtect', 'opendtect'], ['opendtect', 'python', 'python']):
        folder = made(tmp_path / '-'.join(targets), edit=lambda d: d.update(targets=targets))
        assert refused(sa.definition, folder / 'definition.json') == sentence, targets
    for targets in (['opendtect', 'python'], ['opendtect', 'resinsight'], ['opendtect', 'python', 'resinsight']):
        folder = made(tmp_path / ('accepted-' + '-'.join(targets)), edit=lambda d: d.update(targets=targets))
        assert sa.definition(folder / 'definition.json')['targets'] == targets
