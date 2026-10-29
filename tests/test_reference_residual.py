"""E119b slice 2 (C4 t6, t7): the shipped reference procedure *Residual at wells*, run as a person runs it.

Self-contained, so it runs from an installed wheel in a folder outside the checkout (the lane's Validation Record names
the run): `ophiolite.residuals.reference_path()` is packaged; the procedure validates, packs, registers in a project's
catalogue (`FakeProject`, a stand-in for the Gateway's procedure, entity and read routes), and runs through
`procedure_run` on project versions bound by `residuals.prepare`; its output reads back as a residual result whose rows
are the hand values. `FakeProject` is also what `test_residuals.py` binds against (`from test_reference_residual import`)."""
import base64
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ophiolite import procedures, residuals, writers
from ophiolite.errors import Refused
from ophiolite.models import invariants as rules
from ophiolite.typed import GridSurface, Trajectory, WellSet, WellTops
from ophiolite.well_sets import WellSets

EXT = {'well-set/1': '.json', 'well-tops-csv/1': '.csv', 'deviation-csv/1': '.csv', 'esri-ascii-grid/1': '.asc'}
DECLARED = {'well-tops-csv/1': ('depth_unit', 'depth_basis', 'depth_datum'), 'deviation-csv/1': ('depth_unit', 'azimuth_reference', 'depth_datum'),
            'esri-ascii-grid/1': ('crs', 'xy_unit', 'z_meaning', 'z_unit', 'positive', 'vertical_datum'), 'well-set/1': ()}


def bore(n): return 'wellbore-%032x' % n
def well(n): return 'well-%032x' % n
def rev(n): return '%064x' % n


FRAME = {'crs': 'EPSG:23031', 'wellhead': {'x': 600050.0, 'y': 5900050.0}, 'depth_reference': {'name': 'KB', 'elevation': 0.0, 'datum': 'NAP'},
         'north': {'survey_basis': 'grid:EPSG:23031', 'rotation_deg': 0}, 'tie_in': None, 'source': 'by hand'}
SURVEY_CONTEXT = {'type': 'trajectory', 'depth_unit': 'm', 'angle_unit': 'deg', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'}
VERTICAL = [{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None}, {'md': 2000.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None}]
FLAT = {'context': {'type': 'regular-grid-surface', 'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down',
                    'vertical_datum': 'NAP', 'registration': 'center', 'row_order': 'north-to-south', 'ncols': 3, 'nrows': 3, 'cell_size': 100.0,
                    'x_first_center': 599950.0, 'y_first_center': 5900150.0, 'missing_count': 0}, 'values': [1000.0] * 9}


def grid_original(grid):
    c = grid['context']
    return writers.write_grid(grid['values'], ncols=c['ncols'], nrows=c['nrows'], x_origin=c['x_first_center'],
                              y_origin=c['y_first_center'] - (c['nrows'] - 1) * c['cell_size'], cell_size=c['cell_size'], registration='center',
                              crs=c['crs'], xy_unit=c['xy_unit'], z_unit=c['z_unit'], z_meaning=c['z_meaning'], positive=c['positive'],
                              vertical_datum=c['vertical_datum']).bytes


class FakeProject(procedures.ProcedureClient):
    """The routes `residuals.prepare`, `well_sets` and the procedure catalogue call, over versions held in memory.
    `links` are association items as the Gateway lists them (only those the person may read), `page` items a page."""
    project = 'project-1'

    def __init__(self, page=100):
        self.versions, self.links, self.page, self.calls, self.inspect_refusal, self.catalogue = {}, [], page, [], None, {}
        self.well_sets = WellSets(self)

    # -- versions
    def add(self, asset, revision, profile, typed, raw, context=None):
        self.versions[(asset, revision)] = (profile, typed, raw, context or {})
        return {'asset_id': asset, 'revision': revision}

    def add_tops(self, n, tops, depth_unit='m', depth_datum='KB'):
        context = {'type': 'well-tops', 'depth_unit': depth_unit, 'depth_basis': 'unknown', **({'depth_datum': depth_datum} if depth_datum is not None else {})}
        raw = writers.write_tops(tops, depth_unit='unknown', depth_basis='unknown').bytes
        return self.add('tops-%d' % n, rev(n), 'well-tops-csv/1', WellTops({}, {'context': context, 'tops': [dict(t, tvd=None, source=None) for t in tops]}, None), raw, context)

    def add_survey(self, n, stations=VERTICAL, **context):
        context = {**SURVEY_CONTEXT, **context}
        raw = writers.write_survey(stations, depth_unit='unknown', azimuth_reference='unknown', depth_datum='unknown').bytes
        return self.add('path-%d' % n, rev(1000 + n), 'deviation-csv/1', Trajectory({}, {'context': context, 'stations': copy.deepcopy(stations)}, None), raw, context)

    def add_grid(self, grid=FLAT):
        return self.add('grid-1', rev(2000), 'esri-ascii-grid/1', GridSurface({}, copy.deepcopy(grid), None), grid_original(grid), grid['context'])

    def add_set(self, members):
        doc = {'schema': 'ophiolite.well-set/1', 'label': 'Chalk wells', 'members': members}
        context = {'type': 'well-set', 'count': len(members), 'with_trajectory': sum(m['trajectory'] is not None for m in members)}
        raw = (json.dumps(doc, indent=2) + '\n').encode()
        return self.add('set-1', rev(3000), 'well-set/1', WellSet({}, {'context': context, **doc}, None), raw)

    def link(self, wellbore, version, *, row=None, name='Wellbore A'):
        item = {'asset_id': version['asset_id'], 'revision': version['revision'], 'profile': 'well-tops-csv/1', 'name': 'tops',
                'association': {'assertion_id': 'a%06d' % len(self.links), 'predicate': 'of-entity', **({'row': row} if row else {})},
                'entity': {'entity_id': wellbore, 'kind': 'wellbore', 'name': name}, **({'row': row} if row else {})}
        self.links.append(item)

    # -- routes
    def read_data(self, asset, revision):
        self.calls.append(('read', asset))
        return self.versions[(asset, revision)][1]

    def _entities(self, operation, body):
        assert operation == 'associations' and body['kind'] == 'wellbore' and body['profile'] == 'well-tops-csv/1'
        start = int(body.get('cursor') or 0)
        self.calls.append(('associations', start))
        end = start + self.page
        return {'items': self.links[start:end], 'next_cursor': str(end) if end < len(self.links) else None}

    def _check_member(self, body):  # E111 s4a (D-A2): bind's one member check, `las-uploads/check-member`
        assert set(body) == {'label', 'member'}, body
        self.calls.append(('inspect', 'las-uploads'))
        if self.inspect_refusal: raise self.inspect_refusal
        return {'checked': True}

    def _download_version(self, asset, revision, stem, profile=None, declared=None, wellbore=None):
        self.calls.append(('download', asset))
        profile, _, raw, context = self.versions[(asset, revision)]
        stem.parent.mkdir(parents=True, exist_ok=True)
        target = stem.with_suffix(EXT[profile])
        target.write_bytes(raw)
        return procedures.ProjectInput(str(target), profile, {k: context[k] for k in DECLARED[profile] if isinstance(context.get(k), str)}, asset, revision,
                                       wellbore)

    def _post(self, group, operation, body, retry=False):
        if (group, operation) == ('las-uploads', 'check-member'): return self._check_member(body)
        assert group == 'procedures'
        if operation == 'register':
            raw = base64.b64decode(body['archive'])
            assert hashlib.sha256(raw).hexdigest() == body['archive_sha256']
            verdict = procedures.contract().check_files(procedures.contract().read_archive(raw))
            m = verdict['manifest']
            self.catalogue[verdict['digest']] = (raw, {'name': m['name'], 'label': m['label'], 'version': m['version'], 'digest': verdict['digest'],
                                                       'state': 'private', 'trusted': False, 'mine': True, 'already': False})
            return self.catalogue[verdict['digest']][1]
        if operation == 'list': return {'versions': [v for _, v in self.catalogue.values() if v['name'] == body.get('name', v['name'])]}
        if operation == 'get': return self.catalogue[body['digest']][1]
        if operation == 'bundle':
            raw = self.catalogue[body['digest']][0]
            return {'archive': base64.b64encode(raw).decode(), 'archive_sha256': hashlib.sha256(raw).hexdigest()}
        raise AssertionError(operation)


def member(n, trajectory=None, frame=FRAME):
    return {'well': well(n), 'wellbore': bore(n), 'trajectory': trajectory, 'frame': dict(frame) if trajectory else None}


def three_members(client):
    """A cored wellbore (DCC at 1003.25 m), one without a trajectory (DCC at 1010 m) and one without a DCC top."""
    client.add_grid()
    a, c = client.add_survey(1), client.add_survey(3)
    members = [member(1, a), member(2), member(3, c)]
    client.link(bore(1), client.add_tops(1, [{'name': 'NSB', 'md': 900.0}, {'name': 'DCC', 'md': 1003.25}]))
    client.link(bore(2), client.add_tops(2, [{'name': 'DCC', 'md': 1010.0}]), name='Wellbore B')
    client.link(bore(3), client.add_tops(3, [{'name': 'NSB', 'md': 950.0}]), name='Wellbore C')
    return client.add_set(members), members


def test_the_reference_procedure_is_packaged_and_runs_from_the_catalogue(tmp_path, monkeypatch):
    """C4 t6. Mutations: subtract the other way (crossing - top) -> the residual is -3.25 -> red here and in t1; drop
    the package-data line of pyproject.toml -> the wheel has no reference folder -> red here (run from the wheel)."""
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    folder = residuals.reference_path()
    assert (folder / 'procedure.json').is_file() and (folder / 'entry.py').is_file()
    verdict = procedures.validate(folder)
    assert verdict['valid'], verdict
    assert procedures.contract().read_archive(procedures.pack(folder)).keys() == {'procedure.json', 'entry.py'}
    client = FakeProject()
    registered = client.procedure_register(folder)
    assert (registered['name'], registered['version'], registered['digest']) == ('residual-at-wells', 1, verdict['digest'])
    selection, _ = three_members(client)
    ran = residuals.run(client, 'residual-at-wells', tmp_path / 'out', '@%s:%s' % (selection['asset_id'], selection['revision']),
                        '@grid-1:' + rev(2000), 'DCC', version=1, yes=True)
    record = ran['run']
    assert record['outputs']['residuals']['profile'] == 'well-residual/1'
    assert record['settings'] == {'formation': 'DCC', 'display_unit': 'm'}
    assert [v['asset_id'] for v in record['inputs']['tops']] == ['tops-1', 'tops-2', 'tops-3']
    assert [v['asset_id'] for v in record['inputs']['trajectories']] == ['path-1', 'path-3']
    doc = json.loads((tmp_path / 'out' / record['outputs']['residuals']['file']).read_text(encoding='utf-8'))
    rules.well_residual(doc, residuals.summary(doc))  # the SDK's own rules for a residual result read it back
    assert doc['correspondence'] == {'formation': 'DCC'} and doc['surface'] == {'asset_id': 'grid-1', 'revision': rev(2000)}
    got = [(r['wellbore'], r['occurrence'], r['top'] and r['top']['index'], r['reason']) for r in doc['rows']]
    assert got == [(bore(1), 1, 1, None), (bore(2), 1, 0, 'no-trajectory'), (bore(3), 0, None, 'no-top')]
    first = doc['rows'][0]
    assert first['crossings'][first['used']]['md'] == pytest.approx(1000.0, abs=1e-9)
    assert first['residual'] == pytest.approx(3.25, abs=1e-6)
    assert first['trajectory'] == {'asset_id': 'path-1', 'revision': rev(1001)} and doc['rows'][1]['trajectory'] is None
    assert residuals.summary(doc)['members_not_computed'] == 2
    assert not list(tmp_path.glob('ophiolite-residuals-*'))


def test_the_command_runs_the_residual_procedure_and_says_so(tmp_path, monkeypatch, capsys):
    """`ophiolite residuals run NAME --selection --surface --formation --output`: the same run as t6 through the command.
    Mutation: the handler passes the surface as the selection -> the binding refuses -> red."""
    from ophiolite import cli
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    client = FakeProject()
    client.procedure_register(residuals.reference_path())
    selection, _ = three_members(client)
    args = cli.parser().parse_args(['residuals', 'run', 'residual-at-wells', '--selection', '@%s:%s' % (selection['asset_id'], selection['revision']),
                                    '--surface', '@grid-1:' + rev(2000), '--formation', 'DCC', '--output', str(tmp_path / 'out'), '--version', '1', '--yes'])
    assert (args.display_unit, args.version, args.yes) == ('m', 1, True)
    ran = cli._residuals(args, client)
    assert ran['ran'] and ran['run']['settings'] == {'formation': 'DCC', 'display_unit': 'm'}
    assert capsys.readouterr().out == ran['sentence'] + '\n'
    with pytest.raises(SystemExit):
        cli.parser().parse_args(['residuals', 'run', 'residual-at-wells', '--selection', '@a:b', '--surface', '@c:d', '--formation', 'DCC',
                                 '--output', str(tmp_path / 'x'), '--display-unit', 'km'])


def test_the_settings_are_formation_and_display_unit_only(tmp_path):
    """C4 t7: the reference reads two settings; a third is refused when it is validated (C2's residual_procedure rule)."""
    manifest = json.loads((residuals.reference_path() / 'procedure.json').read_text(encoding='utf-8'))
    assert [s['key'] for s in manifest['settings']] == list(residuals.SETTINGS) == ['formation', 'display_unit']
    copy_ = tmp_path / 'third'
    shutil.copytree(residuals.reference_path(), copy_)
    manifest['settings'].append({'key': 'chord', 'label': 'Chord length', 'type': 'number', 'unit': 'm', 'default': 1})
    (copy_ / 'procedure.json').write_text(json.dumps(manifest), encoding='utf-8')
    verdict = procedures.validate(copy_)
    assert not verdict['valid'] and verdict['field'].startswith('/settings'), verdict


def test_a_refused_bind_runs_nothing(tmp_path):
    client = FakeProject()
    selection, _ = three_members(client)
    client.inspect_refusal = Refused('The trajectory version was withdrawn.', details={'reason': 'well-set:withdrawn'})
    with pytest.raises(Refused, match='^Member 1: The trajectory version was withdrawn.$'):
        residuals.prepare(client, selection, {'asset_id': 'grid-1', 'revision': rev(2000)}, 'DCC')
    assert not any(c[0] == 'download' for c in client.calls)
