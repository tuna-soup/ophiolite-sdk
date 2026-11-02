"""E137 s0 C1 (strategy D-01..D-03, R1-6, R1-8, R1-9, R1-11): the SDK never leaves a kind out without a word.

A kind of an Open Subsurface Data record that this SDK cannot both read back (`starter_archive.READERS`) and land
(`starter.EXPORT_PROFILE`) is refused by its words: at the definition, before anything is extracted; in an export
document read back; in a report a build takes. Every sentence is a literal here."""
import hashlib
import json
import shutil

import pytest

from ophiolite import starter, starter_archive as sa, starter_kinds
from ophiolite.errors import Refused
from test_starter_export import ARCHIVE, SCHEMA, decisions, exported_once, made, refused, run, staged  # noqa: F401 (fixture)

LINES = 'A starter pack cannot hold 2D seismic lines yet: nothing wrote it.'


class Called(Exception):
    pass


@pytest.fixture
def spies(monkeypatch):
    """The extractor and the exporter replaced by spies that record their call and stop the export there."""
    calls = []
    def spy(name):
        def called(*args, **kw):
            calls.append(name)
            raise Called(name)
        return called
    monkeypatch.setattr(sa, 'extracted', spy('extracted'))
    monkeypatch.setattr(sa, 'exported', spy('exported'))
    return calls


def adding(kind, ids):
    def edit(d):
        d['contents'].append({'kind': kind, 'ids': ids})
        d['decisions'] += [{'topic': t, 'subject': x, 'value': v, 'source': 'data'} for x in ids
                           for t, v in {'crs': 'EPSG:32631', 'domain': 'time', 'units': 'ms', 'nulls': 'none'}.items()]
    return edit


def written(out):
    return sorted(str(p.relative_to(out)) for p in out.rglob('*')) if out.exists() else []


@pytest.mark.parametrize('kind, ids, sentence', [
    ('seismic-2d', ['Syn2D/L1'], LINES),
    ('faults', ['SynF'], 'A starter pack cannot hold faults yet: nothing wrote it.'),
    ('time-depth', ['SYN-A'], 'A starter pack cannot hold time-depth models yet: nothing wrote it.'),
])
def test_a_kind_without_a_writer_refuses_by_name_before_extraction(tmp_path, spies, monkeypatch, kind, ids, sentence):
    """R2-5: the supported kinds of the definition come first, the kind without a writer last. E137 s1 R2-5: 2D lines
    have a reader now; it is taken out here, so the missing-capability refusal keeps its regression. E137 s2 C3: so do
    faults, and E137 s3 C2 time-depth models."""
    monkeypatch.delitem(sa.READERS, kind)
    folder = made(tmp_path / 'definition', edit=adding(kind, ids))
    assert refused(run, folder, tmp_path / 'out') == sentence + ' Nothing was sent.'
    assert spies == [] and written(tmp_path / 'out') == []


@pytest.mark.parametrize('remove', ['READERS', 'EXPORT_PROFILE'])
def test_the_sdk_writes_a_kind_only_with_both_a_reader_and_a_profile(tmp_path, spies, monkeypatch, remove):
    """R1-6: with a stub kind in both tables the definition passes and the extractor is reached; taking the kind out
    of either table alone brings the refusal back, before extraction. E137 s2 C3: faults have both now; E137 s3 C2:
    so do time-depth models; the stub kind is surfaces."""
    monkeypatch.setitem(sa.READERS, 'surfaces', lambda path, f: None)
    monkeypatch.setitem(starter.EXPORT_PROFILE, 'surfaces', 'points-csv/1')
    monkeypatch.setattr(sa, 'VOLUME_KINDS', sa.VOLUME_KINDS + ('surfaces',))  # its decisions are a volume's, as `adding` gives
    folder = made(tmp_path / 'definition', edit=adding('surfaces', ['SynS']))
    with pytest.raises(Called):
        run(folder, tmp_path / 'out')
    assert spies == ['extracted']
    spies.clear()
    monkeypatch.delitem(getattr(sa if remove == 'READERS' else starter, remove), 'surfaces')
    assert refused(run, folder, tmp_path / 'out2') == 'A starter pack cannot hold surfaces yet: nothing wrote it. Nothing was sent.'
    assert spies == [] and written(tmp_path / 'out2') == []


def test_a_kind_outside_the_record_vocabulary_is_named(tmp_path, spies):
    folder = made(tmp_path / 'definition', edit=adding('seismic-3D', ['Syn3']))
    assert "contents names 'seismic-3D', which is not a kind of an Open Subsurface Data record" in refused(run, folder, tmp_path / 'out')
    assert spies == []


def test_read_back_refuses_a_file_of_a_kind_it_cannot_read(tmp_path, exported_once, monkeypatch):
    """R1-11, R2-5: an otherwise valid export document, its supported files first and one 2D line file last; no reader
    is called before the refusal."""
    stage, doc, defn = staged(tmp_path, exported_once)
    read = []
    for k in list(sa.READERS): monkeypatch.setitem(sa.READERS, k, lambda path, f: read.append(path))
    monkeypatch.delitem(sa.READERS, 'seismic-2d')  # E137 s1 R2-5: the line reader exists; this keeps the refusal's regression
    doc['files'].append({'path': 'seismic2d/Syn2D/L1.sgy', 'kind': 'seismic-2d', 'object': 'Syn2D/L1', 'axes': {}, 'digest': '0' * 64})
    assert refused(sa.read_back, stage, doc, defn) == LINES + ' Nothing was sent.'
    assert read == []


def test_a_build_refuses_a_report_file_of_a_kind_it_cannot_land(exported_once, monkeypatch):
    """R1-11, R2-5: an otherwise valid report whose supported files come first and one surface file last (E137 s2
    C3: faults land now; E137 s3 C2: time-depth models too); nothing is hashed before the refusal."""
    folder, out, report, export = exported_once
    hashed = []
    monkeypatch.setattr(sa, 'digest_of', lambda p: hashed.append(p))
    report = json.loads(json.dumps(report))
    report['files'].append({'path': 'surfaces/SynS.csv', 'kind': 'surfaces', 'object': 'SynS'})
    report['derived'].append({'path': 'surfaces/SynS.csv', 'sha256': '0' * 64, 'bytes': 0, 'from': report['archive']['sha256'], 'how': 'synthetic'})
    assert refused(starter.inventory, report, export, report['archive'], out) == 'A starter pack cannot hold surfaces yet: nothing wrote it. No pack document was written.'
    assert hashed == []


def test_the_catalogue_is_the_record_vocabulary_in_words():
    """R1-8: the 24 keys are the pinned OSD enum; every kind has words; the new kinds' words are the charter's; what
    the SDK lands is each kind's catalogue profile; the four labels of today are unchanged (R1-4)."""
    schema = json.loads(SCHEMA.read_text())
    assert [k.key for k in starter_kinds.CATALOGUE] == schema['$defs']['kind']['enum']
    assert all(k.words and k.label for k in starter_kinds.CATALOGUE)
    assert [(starter_kinds.BY_KEY[k].label, starter_kinds.BY_KEY[k].words) for k in ('seismic-2d', 'faults', 'time-depth')] == [
        ('2D seismic line', '2D seismic lines'), ('fault', 'faults'), ('time-depth model', 'time-depth models')]
    assert {k: starter_kinds.BY_KEY[k].profile for k in starter.EXPORT_PROFILE} == starter.EXPORT_PROFILE
    assert [starter_kinds.label(k) for k in ('seismic-3d', 'horizons', 'wellbore-logs', 'wellbore-paths')] == ['seismic cube', 'horizon', 'log', 'well path']
    assert starter_kinds.label('seismic-3D') == 'object of a kind this version does not know'


# --- C5 (strategy D-04, D-08, R1-15, R2-3, R2-8): the 2D line identity and the skeleton the slices fill ----------------

def lines(ids):
    def edit(d):
        d['contents'].append({'kind': 'seismic-2d', 'ids': ids})
        d['decisions'] += [{'topic': t, 'subject': x, 'value': v, 'source': 'data'} for x in ids for t, v in {'crs': 'EPSG:32631', 'domain': 'time'}.items()]
    return edit


def test_a_line_is_its_dataset_and_its_line_in_one_path_each():
    """C5 test 1. Mutation: the path built from the line alone (both ids give `seismic2d/L1.sgy`)."""
    assert starter_kinds.line_paths(['Syn2D/L1', 'Other/L1']) == {'Syn2D/L1': 'seismic2d/Syn2D/L1.sgy', 'Other/L1': 'seismic2d/Other/L1.sgy'}
    assert [starter_kinds.depth(k) for k in ('seismic-2d', 'seismic-3d', 'faults')] == [3, 2, 2]


@pytest.mark.parametrize('ids, sentence', [
    (['L1'], "The 2D line 'L1' is not named as its dataset and its line, <dataset>/<line>; a starter pack cannot name it yet."),
    (['Syn2D/'], "The 2D line 'Syn2D/' is not named as its dataset and its line, <dataset>/<line>; a starter pack cannot name it yet."),
    (['a/b/c'], "The 2D dataset or line name 'a/b/c' holds a /; a starter pack cannot name it yet."),
    (['A/L 1', 'A/L_1'], 'The 2D lines “A/L 1” and “A/L_1” would be written to one file name.'),
    (['D 1/L', 'D_1/L'], 'The 2D lines “D 1/L” and “D_1/L” would be written to one file name.'),
    (['D 1/L', 'D_1/M'], 'The 2D lines “D 1/L” and “D_1/M” would be written to one file name.'),
    (['A/l1', 'A/L1'], 'The 2D lines “A/l1” and “A/L1” would be written to one file name.'),
    (['d/L', 'D/L'], 'The 2D lines “d/L” and “D/L” would be written to one file name.'),
], ids=['no-dataset', 'no-line', 'slash', 'space', 'dataset-space', 'two-datasets-one-folder', 'line-case', 'dataset-case'])
def test_a_line_id_not_of_its_form_or_sharing_a_file_refuses_before_extraction(tmp_path, spies, ids, sentence):
    """C5 tests 1-2 (R1-15, R2-8), before the writer check: the definition names the identities, nothing is extracted.
    Mutations: the dataset map dropped (`two-datasets-one-folder` passes: two datasets in one folder); stems compared
    with their case (`line-case`, `dataset-case` pass)."""
    folder = made(tmp_path / 'definition', edit=lines(ids))
    assert refused(run, folder, tmp_path / 'out') == sentence + ' Nothing was sent.'
    assert spies == [] and written(tmp_path / 'out') == []


def line_file(stage, path='seismic2d/Syn2D/L1.sgy', oid='Syn2D/L1'):
    raw = b'a synthetic stand-in for a 2D line file\n'
    (stage / path).parent.mkdir(parents=True, exist_ok=True)
    (stage / path).write_bytes(raw)
    return {'path': path, 'kind': 'seismic-2d', 'object': oid, 'axes': {}, 'digest': hashlib.sha256(raw).hexdigest()}


STUB_READ = lambda path, f: ({}, hashlib.sha256(path.read_bytes()).hexdigest())  # noqa: E731


def tables():  # ophiolite-opendtect/tests/test_starter_kinds.py's skeleton keeps a copy (the SDK never imports the connector)
    """The test-scoped tables (R2-3) with a stub reader and the catalogue profiles of the two new kinds."""
    return {'readers': {**sa.READERS, 'seismic-2d': STUB_READ, 'faults': STUB_READ},
            'export_profile': {**starter.EXPORT_PROFILE, 'seismic-2d': 'segy-line/1', 'faults': 'opendtect-faultsticks/1'}}


def test_read_back_takes_a_line_at_three_segments_and_a_cube_only_at_two(tmp_path, exported_once):
    """C5 test 3. Mutation: accept any depth (the cube under `seismic/x/` is read)."""
    stage, doc, defn = staged(tmp_path, exported_once)
    doc['files'].append(line_file(stage))
    defn['contents'].append({'kind': 'seismic-2d', 'ids': ['Syn2D/L1'], 'count': 1})
    sa.read_back(stage, doc, defn, **tables())
    (stage / 'seismic/x').mkdir()
    (stage / 'seismic/Syn.sgy').rename(stage / 'seismic/x/Syn.sgy')
    next(f for f in doc['files'] if f['path'] == 'seismic/Syn.sgy')['path'] = 'seismic/x/Syn.sgy'
    assert refused(sa.read_back, stage, doc, defn, **tables()) == "The export wrote 'seismic/x/Syn.sgy', not a file of its own folders. Nothing was sent."


def test_a_build_takes_a_line_at_three_segments_and_a_cube_only_at_two(tmp_path, exported_once):
    """C5 test 3, the build's inventory. Mutation: accept any depth (the cube under `seismic/x/` is taken)."""
    _, out, report, export = exported_once
    folder = tmp_path / 'export'
    shutil.copytree(export, folder)
    report = json.loads(json.dumps(report))
    f = line_file(folder / 'files')
    report['files'].append({k: f[k] for k in ('path', 'kind', 'object')})
    report['derived'].append({'path': f['path'], 'sha256': f['digest'], 'bytes': (folder / 'files' / f['path']).stat().st_size,
                              'from': report['archive']['sha256'], 'how': 'synthetic'})
    taken = starter.inventory(report, folder, report['archive'], out, **tables())
    assert [(d['path'], d['kind'], d['object']) for d in taken][-1] == ('seismic2d/Syn2D/L1.sgy', 'seismic-2d', 'Syn2D/L1')
    moved = json.loads(json.dumps(report))
    for rows in (moved['files'], moved['derived']):
        next(r for r in rows if r['path'] == 'seismic/Syn.sgy')['path'] = 'seismic/x/Syn.sgy'
    (folder / 'files/seismic/x').mkdir()
    (folder / 'files/seismic/Syn.sgy').rename(folder / 'files/seismic/x/Syn.sgy')
    assert refused(starter.inventory, moved, folder, report['archive'], out, **tables()) == starter.NOT_THE_EXPORT % out
