"""E119b slice 2 (C4 t1 to t5, t8): residuals at wells on E119a's analytic fixture, and binding before computing.

The trajectories, frames and surfaces are E119a's (`fixtures/well_geometry/`, closed forms in `closed_forms.py`); the
tops are literal CSV texts (TOPS below, written to a temporary file and read as the reference procedure reads its input;
kept here rather than as fixture files, which would each need a reviewed provenance row). A hand value is the top's measured depth minus the closed form's crossing.
Crossings come from E119a's merged `crossings`, as found (D8 as amended at e119as3). `prepare` binds against
`FakeProject` (test_reference_residual.py), which stands in for the Gateway's entity, read and inspect routes."""
import copy
import json
import math
import tempfile
from pathlib import Path

import pytest

from ophiolite import procedures, residuals, writers
from ophiolite.errors import Refused
from test_reference_residual import FRAME, FakeProject, VERTICAL, bore, member, rev

HERE = Path(__file__).parent / 'fixtures' / 'well_geometry'
CASES = {c['name']: c for c in json.loads((HERE / 'cases.json').read_text(encoding='utf-8'))['cases']}
GRID = 'grid-1', rev(2000)
TOPS = {'tops-vertical.csv': 'name,md\nNSB,1100\nDCC,1210\n',
        'tops-slant.csv': 'name,md\nDCC,1440\n',
        'tops-build.csv': 'name,md\nDCC,1195.5\n',
        'tops-fold.csv': 'name,md\nDCC,1190\nDCC,1150\n',
        'tops-twice.csv': 'name,md\nDCC,1300\nNSB,1200\nDCC,1250\nDCC,1250\n'}


def read_tops(name):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_text(TOPS[name], encoding='utf-8')
        return residuals.read_tops(path)


def grid(name):
    return json.loads((HERE / (name + '.json')).read_text(encoding='utf-8'))


def one(case, tops_file=None, tops=None, formation='DCC', trajectory=True, wellbore=bore(1), **kw):
    """The rows of one member through `compute`: CASE's trajectory and frame against its surface, the tops of
    TOPS_FILE (read as the reference procedure reads its input) or TOPS."""
    c = CASES[case]
    path = {'asset_id': 'path-1', 'revision': rev(1001)} if trajectory else None
    m = {'well': 'well-1', 'wellbore': wellbore, 'trajectory': path, 'frame': c['frame'] if trajectory else None}
    given = read_tops(tops_file) if tops_file else tops
    doc = residuals.compute([m], {wellbore: ({'asset_id': 'tops-1', 'revision': rev(1)}, given)} if given is not None else {},
                            {('path-1', rev(1001)): copy.deepcopy(c['trajectory'])}, grid(c['surface']), {'asset_id': 'grid-1', 'revision': rev(2000)},
                            formation, **kw)
    return doc


# ---------------------------------------------------------------- t1: hand values

@pytest.mark.parametrize('case, tops_file, top, crossing', [
    ('vertical, 30 m east of a node', 'tops-vertical.csv', 1210.0, 1202.6246599057777),
    ('slant 30 degrees, azimuth 60', 'tops-slant.csv', 1440.0, 1449.0273805222844),
    ('build 10 degrees per 30 m, azimuth 120', 'tops-build.csv', 1195.5, 1200.9535554759364),
])
def test_each_residual_is_within_a_micrometre_of_the_hand_value(case, tops_file, top, crossing):
    """C4 t1. Mutation (t6's): subtract the other way -> red."""
    doc = one(case, tops_file)
    assert len(doc['rows']) == 1
    row = doc['rows'][0]
    assert row['top']['md'] == top and row['reason'] is None and row['unit'] == 'm'
    assert abs(row['residual'] - (top - crossing)) <= 1e-6, (row['residual'], top - crossing)
    assert row['residual'] == row['top']['md'] - row['crossings'][row['used']]['md']


def test_the_tops_index_is_the_position_in_the_file():
    row = one('vertical, 30 m east of a node', 'tops-vertical.csv')['rows'][0]
    assert row['top'] == {'asset_id': 'tops-1', 'revision': rev(1), 'index': 1, 'md': 1210.0}
    assert row['trajectory'] == {'asset_id': 'path-1', 'revision': rev(1001)}


# ---------------------------------------------------------------- t2: the fold

def test_the_fold_uses_the_nearer_crossing_and_the_shallower_on_a_tie():
    """C4 t2: two crossings (1140.169, 1208.932); each top uses the nearer; an exact tie uses the shallower."""
    doc = one('fold: a slant through a crest', 'tops-fold.csv')
    got = [(r['occurrence'], r['top']['index'], r['top']['md'], r['used']) for r in doc['rows']]
    assert got == [(1, 1, 1150.0, 0), (2, 0, 1190.0, 1)]
    a, b = (c['md'] for c in doc['rows'][0]['crossings'])
    assert abs(a - 1140.1691327885262) <= 0.01 and abs(b - 1208.9324823492286) <= 0.01
    tie = (a + b) / 2
    assert abs(tie - a) == abs(tie - b)  # an exact tie in floating point
    row = one('fold: a slant through a crest', tops=[{'name': 'DCC', 'md': tie}])['rows'][0]
    assert row['used'] == 0 and row['residual'] == tie - a


# ---------------------------------------------------------------- t3: occurrences

def test_two_tops_of_the_formation_are_numbered_in_md_order_ties_in_file_order():
    """C4 t3: tops-twice.csv holds DCC at 1300, 1250 and 1250 (file rows 0, 2, 3)."""
    doc = one('vertical, 30 m east of a node', 'tops-twice.csv')
    assert [(r['occurrence'], r['top']['index'], r['top']['md']) for r in doc['rows']] == [(1, 2, 1250.0), (2, 3, 1250.0), (3, 0, 1300.0)]
    assert all(r['used'] == 0 for r in doc['rows'])


def test_a_wellbore_whose_rows_are_all_reasons_is_counted_once():
    above = one('wholly above', 'tops-twice.csv', wellbore=bore(2))
    assert [r['reason'] for r in above['rows']] == ['ends-above'] * 3
    computed = one('vertical, 30 m east of a node', 'tops-vertical.csv')
    doc = {**computed, 'rows': computed['rows'] + above['rows']}
    s = residuals.summary(doc)
    assert (s['count'], s['computed'], s['not_computed'], s['members'], s['members_not_computed']) == (4, 1, 3, 2, 1)


# ---------------------------------------------------------------- t4: reason rows

SENTENCES = {
    'grazing': 'Not computed: the path comes within 0.01 m of the surface from {a} m to {b} m, and no crossing is proven.',
    'along-surface': 'Not computed: the path runs within 0.01 m of the surface from {a} m to {b} m, and no crossing is proven.',
    'uncertain': 'Not computed: a crossing is possible between {a} m and {b} m but could not be proven.',
    'no-surface-data': 'Not computed: the surface has no data where the path would cross it.',
    'ends-above': 'Not computed: the path ends above the surface.',
    'starts-below': 'Not computed: the path starts below the surface.',
    'no-trajectory': 'Not computed: this wellbore has no trajectory in the selection.',
    'no-top': 'Not computed: this wellbore has no top of the chosen formation.',
    'many-crossings': 'Not computed: the path crosses the surface more than 64 times between {a} m and {b} m.',
}


def corrugated(end):
    """A 65-crossing fold: vertical to 1000 m, a quarter turn to horizontal by 1100 m, then north to END, under a
    surface whose rows alternate 5 m above and below the horizontal section (one crossing per 10 m row)."""
    stations = [{'md': 0.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None}, {'md': 1000.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None},
                {'md': 1100.0, 'inclination': 90.0, 'azimuth': 0.0, 'tvd': None}, {'md': float(end), 'inclination': 90.0, 'azimuth': 0.0, 'tvd': None}]
    trajectory = {'context': {'type': 'trajectory', 'depth_unit': 'm', 'angle_unit': 'deg', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'},
                  'stations': stations}
    frame = {**FRAME, 'wellhead': {'x': 600000.0, 'y': 5900000.0}}
    z = 1000 + 200 / math.pi
    values = [z + (5 if i % 2 else -5) for i in range(120) for _ in range(3)]
    surface = {'context': {'type': 'regular-grid-surface', 'crs': 'EPSG:23031', 'xy_unit': 'm', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down',
                           'vertical_datum': 'NAP', 'registration': 'center', 'row_order': 'north-to-south', 'ncols': 3, 'nrows': 120, 'cell_size': 10.0,
                           'x_first_center': 599990.0, 'y_first_center': 5901100.0, 'missing_count': 0}, 'values': values}
    m = {'well': 'well-1', 'wellbore': bore(1), 'trajectory': {'asset_id': 'path-1', 'revision': rev(1001)}, 'frame': frame}
    return residuals.compute([m], {bore(1): ({'asset_id': 'tops-1', 'revision': rev(1)}, [{'name': 'DCC', 'md': 1400.0}])},
                             {('path-1', rev(1001)): trajectory}, surface, {'asset_id': 'grid-1', 'revision': rev(2000)}, 'DCC')['rows'][0]


def reason_rows():
    t = [{'name': 'DCC', 'md': 1100.0}]
    out = {'grazing': one('near miss at 0.008 m', tops=t)['rows'][0], 'along-surface': one('parallel at 0.008 m over 3 m', tops=t)['rows'][0],
           'uncertain': one('vertical, 30 m east of a node', tops=t, max_eval=3)['rows'][0],
           'no-surface-data': one('path enters a hole', tops=t)['rows'][0], 'ends-above': one('wholly above', tops=t)['rows'][0],
           'starts-below': one('wholly below', tops=t)['rows'][0], 'no-trajectory': one('wholly above', tops=t, trajectory=False)['rows'][0],
           'no-top': one('vertical, 30 m east of a node', tops=[{'name': 'NSB', 'md': 1100.0}])['rows'][0], 'many-crossings': corrugated(1717)}
    return out


def test_every_reason_row_with_its_between_and_its_sentence():
    """C4 t4: one row per reason, each the literal key, `between` exactly for the four reasons that carry one (E119a's
    no-surface-data interval is dropped: the residual vocabulary's sentence names no depths), and its sentence.
    Mutation: drop one E119a reason's mapping in residuals.FROM_CROSSINGS -> its row cannot be made -> red."""
    rows = reason_rows()
    assert list(rows) == list(residuals.reasons()) == list(SENTENCES)
    for key, row in rows.items():
        assert row['reason'] == key and row['residual'] is None and row['used'] is None, key
        assert (row['between'] is not None) == (key in ('grazing', 'along-surface', 'uncertain', 'many-crossings')), key
        a, b = row['between'] or (None, None)
        expected = SENTENCES[key].format(a='%.2f' % a, b='%.2f' % b) if a is not None else SENTENCES[key]
        assert residuals.sentence(row) == expected, key
    assert rows['grazing']['between'] == pytest.approx([5.405934959349594, 5.4140650406504065], abs=0.001)
    assert rows['along-surface']['between'] == pytest.approx([3.9959349593495936, 7.004065040650406], abs=0.001)
    assert rows['uncertain']['between'] == [3.0, 2000]
    assert rows['no-surface-data']['crossings'] and rows['no-surface-data']['between'] is None
    assert rows['no-trajectory']['trajectory'] is None and rows['no-trajectory']['top']['md'] == 1100.0
    assert rows['no-top']['occurrence'] == 0 and rows['no-top']['top'] is None and rows['no-top']['trajectory'] is not None
    assert rows['many-crossings']['crossings'] == [] and 1000 < rows['many-crossings']['between'][0] < rows['many-crossings']['between'][1] < 1717
    assert residuals.sentence(rows['grazing']) == 'Not computed: the path comes within 0.01 m of the surface from 5.41 m to 5.41 m, and no crossing is proven.'


def test_64_crossings_are_listed_and_65_are_many():
    listed = corrugated(1707)
    assert len(listed['crossings']) == 64 and listed['residual'] is not None
    assert corrugated(1717)['reason'] == 'many-crossings'


def test_a_member_without_a_top_and_without_a_trajectory_is_one_no_top_row():
    rows = one('wholly above', tops=None, trajectory=False)['rows']
    assert [(r['occurrence'], r['reason'], r['trajectory']) for r in rows] == [(0, 'no-top', None)]


def test_the_document_is_written_as_utf8_json():
    doc = one('vertical, 30 m east of a node', 'tops-vertical.csv')
    written = writers.well_residual(doc)
    assert (written.profile, written.declared, written.filename) == ('well-residual/1', {}, 'residuals.json')
    assert json.loads(written.bytes) == doc
    with pytest.raises(Exception, match='finite'): writers.well_residual({**doc, 'rows': [{**doc['rows'][0], 'residual': math.nan}]})


# ---------------------------------------------------------------- t5: binding before computing

SURFACE = {'asset_id': 'grid-1', 'revision': rev(2000)}


def project(n=2, page=100, **tops):
    """N members, each with a vertical trajectory and DCC tops linked as a whole."""
    client = FakeProject(page=page)
    client.add_grid()
    members = []
    for i in range(1, n + 1):
        members.append(member(i, client.add_survey(i)))
        client.link(bore(i), client.add_tops(i, [{'name': 'DCC', 'md': 1003.0 + i}], **tops), name='Wellbore %s' % 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'[(i - 1) % 26])
    return client, members


def refused(client, members, formation='DCC'):
    selection = client.add_set(members)
    with pytest.raises(Refused) as caught:
        residuals.prepare(client, '@%s:%s' % (selection['asset_id'], selection['revision']), SURFACE, formation)
    assert not any(c[0] == 'download' for c in client.calls)  # nothing is computed or downloaded
    return str(caught.value)


def test_two_tops_linked_to_one_wellbore_the_second_on_a_later_page():
    """Mutation: stop at the first association page -> the later-page conflict runs -> red."""
    client, members = project(2, page=1)
    client.link(bore(1), client.add_tops(9, [{'name': 'DCC', 'md': 1004.0}]), name='Wellbore A')
    assert len(client.links) == 3
    assert refused(client, members) == 'Two tops sets are linked to Wellbore A; keep one link.'
    assert ('associations', 2) in client.calls


def test_no_top_named_the_formation():
    client, members = project(2)
    assert refused(client, members, 'Ommelanden') == 'No selected wellbore has a top named "Ommelanden".'


def test_the_no_top_sentence_names_the_formation_readably():
    """E119b s5 6-12: the sentence shows the formation's readable name, as the reason sentences do; a name that does not
    read as one gives the neutral words. Mutation: put the raw formation key back in the sentence -> red."""
    client, members = project(2)
    assert refused(client, members, 'Omme\x07landen') == 'No selected wellbore has a top named "Ommelanden".'
    assert refused(client, members, 'north_sea_group') == 'No selected wellbore has a top of the chosen formation.'


def test_no_member_with_a_trajectory():
    client, _ = project(1)
    assert refused(client, [member(1), member(2)]) == 'No selected wellbore has a trajectory, so there is nothing to intersect.'


def test_33_distinct_inputs_are_refused_and_32_run():
    client, members = project(15)
    client.link(bore(16), client.add_tops(16, [{'name': 'DCC', 'md': 1010.0}]), name='Wellbore P')
    assert refused(client, members + [member(16)]) == 'This selection needs 33 versions; a run takes at most 32.'
    client, members = project(15)
    selection = client.add_set(members)
    prepared = residuals.prepare(client, selection, SURFACE, 'DCC')
    try:
        assert sum(len(v) for v in prepared.inputs.values()) == 32
    finally:
        prepared.discard()


@pytest.mark.parametrize('datum, sentence', [
    (None, 'Member 1: its tops do not declare the depth datum they are measured from; declare it as the trajectory does (KB).'),
    ('unknown', 'Member 1: its tops do not declare the depth datum they are measured from; declare it as the trajectory does (KB).'),
    ('', 'Member 1: its tops do not declare the depth datum they are measured from; declare it as the trajectory does (KB).'),
])
def test_a_tops_datum_absent_or_unknown(datum, sentence):
    client, members = project(1, depth_datum=datum)
    assert refused(client, members) == sentence


def test_kelly_bushing_against_rotary_table():
    client = FakeProject()
    client.add_grid()
    frame = {**FRAME, 'depth_reference': {**FRAME['depth_reference'], 'name': 'rotary table'}}
    members = [member(1, client.add_survey(1, depth_datum='rotary table'), frame)]
    client.link(bore(1), client.add_tops(1, [{'name': 'DCC', 'md': 1004.0}], depth_datum='kelly bushing'))
    assert refused(client, members) == 'Member 1: its tops are measured from kelly bushing but its trajectory from rotary table; a residual needs one depth datum.'


def test_tops_not_in_metres():
    client, members = project(1, depth_unit='ft')
    assert refused(client, members) == 'Member 1: the depths of its tops are not in metres.'


def test_an_e119a_geometry_refusal_names_the_member():
    client = FakeProject()
    client.add_grid()
    members = [member(1, client.add_survey(1)), member(2, client.add_survey(2, azimuth_reference='magnetic-north'))]
    client.link(bore(1), client.add_tops(1, [{'name': 'DCC', 'md': 1004.0}]))
    assert refused(client, members) == 'Member 2: The survey is referenced to magnetic north; state it against true north or grid north.'


def accepted(client, members):
    selection = client.add_set(members)
    prepared = residuals.prepare(client, selection, SURFACE, 'DCC')
    prepared.discard()
    return prepared


def test_accepted_rotary_table_with_spaces_and_case():
    client = FakeProject()
    client.add_grid()
    frame = {**FRAME, 'depth_reference': {**FRAME['depth_reference'], 'name': 'rotary table'}}
    members = [member(1, client.add_survey(1, depth_datum='rotary table'), frame)]
    client.link(bore(1), client.add_tops(1, [{'name': 'DCC', 'md': 1004.0}], depth_datum=' Rotary Table '))
    prepared = accepted(client, members)
    assert prepared.settings == ['formation=DCC', 'display_unit=m']
    assert [(p.asset_id, p.wellbore) for p in prepared.inputs['tops']] == [('tops-1', bore(1))]


def test_a_row_only_link_is_ignored():
    client, members = project(1)
    client.link(bore(1), client.add_tops(9, [{'name': 'DCC', 'md': 1004.0}]), row='3')
    prepared = accepted(client, members)
    assert [p.asset_id for p in prepared.inputs['tops']] == ['tops-1']


def test_a_whole_file_link_as_the_gateway_sends_it_with_row_null_is_linked():
    """E119b s4 (stop A): the Gateway's association answer always carries `row`, null for a link to the whole file.
    Mutation: skip every item that has a `row` key (`'row' in item`) -> no top is linked -> refused -> red."""
    client, members = project(2)
    for item in client.links:
        item['row'] = None
        item['association']['row'] = None
    prepared = accepted(client, members)
    assert [p.asset_id for p in prepared.inputs['tops']] == ['tops-1', 'tops-2']


def test_a_link_on_a_tops_version_you_cannot_read_is_not_seen():
    """The Gateway omits an association whose revision the person cannot read (PG entities.associations); `prepare`
    has no other source of links, so a second, unreadable link neither refuses nor is named."""
    client, members = project(1)
    client.add_tops(9, [{'name': 'DCC', 'md': 1004.0}])  # linked to wellbore 1 for someone else; not listed to this person
    prepared = accepted(client, members)
    assert [p.asset_id for p in prepared.inputs['tops']] == ['tops-1'] and ('read', 'tops-9') not in client.calls


def test_the_inputs_are_the_four_slots_trajectories_in_member_order():
    client, members = project(3)
    members = [members[2], members[0], members[1]]
    prepared = accepted(client, members)
    assert list(prepared.inputs) == ['selection', 'tops', 'surface', 'trajectories']
    assert [p.asset_id for p in prepared.inputs['trajectories']] == ['path-3', 'path-1', 'path-2']
    assert [p.wellbore for p in prepared.inputs['tops']] == [bore(3), bore(1), bore(2)]


# ---------------------------------------------------------------- t8: the entry is told which version it reads

def probe(tmp_path):
    folder = tmp_path / 'probe'
    folder.mkdir()
    manifest = {'schema': 'ophiolite.procedure/1', 'name': 'probe', 'label': 'Print what the entry is given', 'version': 1, 'step': 'process',
                'inputs': [{'slot': 'tops', 'label': 'Tops', 'class': 'version', 'kinds': ['well-tops-csv/1'], 'cardinality': 'one'}],
                'outputs': [{'role': 'same', 'label': 'Same tops', 'class': 'version', 'kind': 'well-tops-csv/1'}], 'entry': 'probe:run'}
    (folder / 'procedure.json').write_text(json.dumps(manifest), encoding='utf-8')
    (folder / 'probe.py').write_text(
        'import dataclasses, json\nfrom ophiolite import procedure\nfrom ophiolite.writers import write_tops\n\n\n@procedure\ndef run(inputs, settings):\n'
        '    print(json.dumps(dataclasses.asdict(inputs["tops"][0]), sort_keys=True))\n'
        '    return {"same": write_tops([{"name": "DCC", "md": 1}], depth_unit="m", depth_basis="unknown")}\n', encoding='utf-8')
    tops = tmp_path / 'tops.csv'
    tops.write_text('name,md\nDCC,1\n', encoding='utf-8')
    return folder, tops


def test_a_local_file_run_names_no_version(tmp_path):
    """C4 t8: a local-file run of an existing procedure gives LocalVersion with asset_id, revision and wellbore None
    and is otherwise unchanged (the run.json record has no new field)."""
    folder, tops = probe(tmp_path)
    ran = procedures.run(folder, tmp_path / 'out', {'tops': [str(tops)]}, kinds={'tops': 'well-tops-csv/1'})
    given = json.loads((tmp_path / 'out' / 'log.txt').read_text(encoding='utf-8').splitlines()[0])
    assert given == {'path': str(tops.resolve()), 'kind': 'well-tops-csv/1', 'declared': {}, 'asset_id': None, 'revision': None, 'wellbore': None}
    assert set(ran['run']['inputs']['tops'][0]) == {'file', 'sha256', 'kind', 'declared'}


def test_a_project_input_names_its_version_and_wellbore(tmp_path):
    """The entry of a run on project versions is told each version's asset id and revision, and a residual run's tops
    their wellbore (procedures._encode). Mutation: encode a LocalVersion without them -> None in the child -> red."""
    folder, tops = probe(tmp_path)
    given = procedures.ProjectInput(str(tops), 'well-tops-csv/1', {'depth_unit': 'm'}, 'tops-1', rev(1), bore(1))
    procedures.run(folder, tmp_path / 'out', {'tops': [given]})
    told = json.loads((tmp_path / 'out' / 'log.txt').read_text(encoding='utf-8').splitlines()[0])
    assert told == {'path': str(tops.resolve()), 'kind': 'well-tops-csv/1', 'declared': {'depth_unit': 'm'}, 'asset_id': 'tops-1', 'revision': rev(1),
                    'wellbore': bore(1)}


def test_a_grid_exported_with_a_byte_order_mark_reads_as_without_one(tmp_path):
    """E119b s5 6-7. Mutation: read the grid as utf-8 -> the BOM sticks to `ncols` -> no header -> red."""
    from test_reference_residual import grid_original
    surface = grid('slope-5deg')
    (tmp_path / 's.asc').write_bytes(grid_original(surface))
    (tmp_path / 'bom.asc').write_bytes(b'\xef\xbb\xbf' + grid_original(surface))
    c = surface['context']
    declared = {k: c[k] for k in ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum')}
    assert residuals.read_grid(tmp_path / 'bom.asc', declared) == residuals.read_grid(tmp_path / 's.asc', declared)
    assert residuals.read_grid(tmp_path / 'bom.asc', declared)['values'] == surface['values']


def test_the_entry_refuses_files_that_name_no_version(tmp_path):
    with pytest.raises(Refused, match='project versions'):
        residuals.from_inputs({'selection': [procedures.LocalVersion(str(tmp_path / 'set.json'), 'well-set/1')]}, {'formation': 'DCC', 'display_unit': 'm'})


# ---------------------------------------------------------------- the entry's reading of its files

def test_the_entry_reads_its_files_as_the_readers_do(tmp_path):
    """A grid, a survey and tops written by `ophiolite.writers` read back to E119a's typed fixture values."""
    from test_reference_residual import grid_original
    surface = grid('slope-5deg')
    (tmp_path / 's.asc').write_bytes(grid_original(surface))
    c = surface['context']
    read = residuals.read_grid(tmp_path / 's.asc', {k: c[k] for k in ('crs', 'xy_unit', 'z_unit', 'z_meaning', 'positive', 'vertical_datum')})
    assert read['values'] == surface['values']
    assert {k: read['context'][k] for k in read['context']} == {k: c[k] for k in read['context']}
    case = CASES['build 10 degrees per 30 m, azimuth 120']
    (tmp_path / 't.csv').write_bytes(writers.write_survey(case['trajectory']['stations'], depth_unit='m', azimuth_reference='grid-north', depth_datum='KB').bytes)
    survey = residuals.read_survey(tmp_path / 't.csv', {'depth_unit': 'm', 'azimuth_reference': 'grid-north', 'depth_datum': 'KB'})
    assert survey['stations'] == case['trajectory']['stations']
    assert {k: survey['context'][k] for k in survey['context']} == {k: case['trajectory']['context'][k] for k in survey['context']}
    assert read_tops('tops-twice.csv') == [{'name': 'DCC', 'md': 1300.0}, {'name': 'NSB', 'md': 1200.0}, {'name': 'DCC', 'md': 1250.0},
                                                            {'name': 'DCC', 'md': 1250.0}]
    assert VERTICAL[0]['md'] == 0.0
