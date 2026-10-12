"""E23b B7, in-process gateway lane: Petrel and OpendTect point exports looked at with `ophiolite inspect`, decided with a
reason and added with `ophiolite upload` (and `client.upload_runs`) against the real gateway routes. The journeys are the
browser's (the Workspace scientific intake, generate_scientific.py cases A-E) with literal results: what each field became
and why, the first points, the markers, roles and labels read; a changed companion, a strict and a lenient project, a
cancelled upload, a preview older than a day looked at again, a reading layout reused by name and one of another kind
refused naming it. The files are Platform's point-set 2 contract fixtures (see its NOTICE)."""
import json
import re

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, create  # noqa: F401 (fixture)
from test_layouts_live import command
from project_gateway.tests.test_recipe_uploads import PRIMARY, README, CRS
from project_gateway.tests.test_decision_sets import HORIZON
from ophiolite.errors import Refused
from ophiolite.recipes import Choices

PETREL, ODT = 'petrel-points-attributes/1', 'opendtect-horizon-ascii/1'
POSITIVE, UNIT, TIME, DATUM = ('Petrel exports these values positive up.', 'The interpretation note gives milliseconds.',
                               'The interpretation note says two-way time.', 'The datum is not known yet.')
DECIDE = ['--declare', PETREL + ':positive=up', '--why', PETREL + ':positive=' + POSITIVE, '--declare', PETREL + ':z_unit=ms', '--why', PETREL + ':z_unit=' + UNIT,
          '--declare', PETREL + ':z_meaning=time', '--why', PETREL + ':z_meaning=' + TIME, '--leave-unresolved', PETREL + ':vertical_datum', '--why', PETREL + ':vertical_datum=' + DATUM]
HEX = re.compile(r'[0-9a-f]{12,}')
EXPECTED_LOOK = ['pts/points.txt: Petrel points with attributes, 4 points', '  Coordinate system: EPSG:23031', '  Positive direction: needs a decision',
                 '  Vertical datum: needs a decision', '  Horizontal unit: m', '  Values: needs a decision', '  Vertical unit: needs a decision',
                 'Still needs a decision: Positive direction, Vertical datum, Values, Vertical unit.']
EXPECTED_DECIDED = ['pts/points.txt: Petrel points with attributes, 4 points', '  Coordinate system: EPSG:23031', "  Positive direction: up because '%s'" % POSITIVE,
                    '  Vertical datum: left unresolved', '  Horizontal unit: m', "  Values: time because '%s'" % TIME, "  Vertical unit: ms because '%s'" % UNIT, 'Ready to add.']
CRS_READ = ('crs', 'EPSG:23031', 'recipe', 'all observations agree: points.crsmeta.xml (059fd3ba9097, line 2)', 'decided')
XY_READ = ('xy_unit', 'm', 'recipe', 'all observations agree: points.txt (c3070963e516, line 2)', 'decided')
EXPECTED_A = [CRS_READ, ('positive', 'up', 'declaration', POSITIVE, 'decided'), ('vertical_datum', None, None, 'Left unresolved.', 'needs-decision'), XY_READ,
              ('z_meaning', 'time', 'declaration', TIME, 'decided'), ('z_unit', 'ms', 'declaration', UNIT, 'decided')]
EXPECTED_LAYOUT = [CRS_READ, ('positive', 'up', 'declaration', POSITIVE, 'decided'), ('vertical_datum', 'MSL', 'declaration', 'The survey report gives MSL.', 'decided'),
                   XY_READ, ('z_meaning', 'time', 'declaration', TIME, 'decided'), ('z_unit', 'ms', 'declaration', UNIT, 'decided')]


def folder(tmp_path, name, files):
    at = tmp_path / name
    for path, raw in files.items(): (at / path).parent.mkdir(parents=True, exist_ok=True); (at / path).write_bytes(raw)
    return at


def printed(capsys):
    """What the command printed after `ophiolite login` said the key was saved."""
    return [line for line in capsys.readouterr().out.splitlines() if not line.startswith('Project access key saved')]


def landed(alice, report):
    """The point set the report added, read back through the typed read."""
    item = next(i for i in report.items if i['role'] == 'primary' and i['state'] == 'added')
    return alice.read_data(item['asset_id'], item['revision'])


UPLOAD_REFUSED = 1
UPLOAD_REFUSED_SAID = EXPECTED_DECIDED[:3] + ['  Vertical datum: needs a decision'] + EXPECTED_DECIDED[4:7] + ['Still needs a decision: Vertical datum.']


def said(points):
    return [(d.field, d.selected, d.selected_by, d.reason, d.status) for d in points.decisions]


def test_the_command_line_looks_decides_with_reasons_and_adds_what_it_showed(keyed, tmp_path, monkeypatch, capsys):
    # mutation: --why not sent (the declaration lands with the legacy sentence); --leave-unresolved dropped (inspect stays 4);
    # the upload without the preview receipt (the start is refused); ids or digests in the default words
    alice = client(keyed, 'alice', 'delegate')
    pts = folder(tmp_path, 'pts', {'points.txt': PRIMARY, 'points.crsmeta.xml': CRS})
    key = create(keyed, 'write')['key']
    run = lambda *argv: command(keyed, tmp_path, monkeypatch, list(argv), key, False)
    assert run('inspect', str(pts)) == 4
    assert printed(capsys) == EXPECTED_LOOK
    assert run('inspect', str(pts), *DECIDE) == 0
    out = printed(capsys)
    assert out == EXPECTED_DECIDED and not HEX.search('\n'.join(out))
    assert run('inspect', str(pts), *DECIDE, '--details') == 0 and HEX.search('\n'.join(printed(capsys)))
    # an upload deciding some fields with one still open is refused before anything is sent, in the inspection's own words
    assert run('upload', str(pts), '--attribution', 'Synthetic', '--rights-confirmed', *DECIDE[:-4]) == UPLOAD_REFUSED
    assert capsys.readouterr().err.splitlines() == UPLOAD_REFUSED_SAID and alice.upload_runs.list() == []
    assert run('upload', str(pts), '--attribution', 'Synthetic', '--rights-confirmed', *DECIDE) == 0
    capsys.readouterr()
    report = alice.upload_runs.status(alice.upload_runs.list()[0]['run_id'])
    points = landed(alice, report)
    assert said(points) == EXPECTED_A
    printed_objects = repr(points) + ''.join(map(repr, points.decisions)) + repr(points.recipe)
    assert not HEX.search(printed_objects) and not [t for t in ('recipe-rule', 'declaration', 'needs-decision', 'vertical_datum', 'all observations') if t in printed_objects]
    assert [d.details()['selected_by'] for d in points.decisions] == ['recipe', 'declaration', None, 'recipe', 'declaration', 'declaration']




def test_edits_read_as_the_browser_reads_them(web, tmp_path):
    # mutation: a change sent without its evidence line; the OpendTect separator ignored; a label mapping not applied
    alice = client(web, 'alice', 'delegate')
    runs = alice.upload_runs
    full = folder(tmp_path, 'full', {'points.txt': PRIMARY, 'README.txt': README, 'points.crsmeta.xml': CRS})
    edits = Choices(changes={PETREL: [{'setting': 'missing-marker', 'target': 'file', 'to': ['-1234.5'], 'reason': 'Z of -1234.5 marks no value here.'},
                                      {'setting': 'attribute-kind', 'target': 'TWT auto', 'to': 'text', 'reason': 'TWT is a label in this export.'}]})
    seen = runs.inspected(runs.open(full), edits)['full/points.txt']
    assert (seen.answer['reading']['parsing']['missing'], [(c['source'], c['role'], c['kind']) for c in seen.answer['reading']['columns']]) == (
        ['-1234.5'], [('X', 'x', 'number'), ('Y', 'y', 'number'), ('Z', 'z', 'number'), ('TWT auto', 'attribute', 'text'), ('KIDTAG,Name', 'attribute', 'text'),
                      ('KIDTAG,Data type', 'attribute', 'category'), ('FLOAT,PointsNr', 'attribute', 'number')])
    renamed = folder(tmp_path, 'renamed', {'points.txt': PRIMARY.replace(b'TWT auto', b'TWT_auto'), 'README.txt': README, 'points.crsmeta.xml': CRS})
    mapped = Choices(changes={PETREL: [{'setting': 'label-map', 'target': 'TWT auto', 'to': 'TWT_auto', 'reason': 'The export spells it with an underscore.'}]})
    assert runs.inspected(runs.open(renamed), mapped)['renamed/points.txt'].ready
    with pytest.raises(Refused) as e: runs.inspected(runs.open(renamed), Choices(every=True), ready=False)
    assert str(e.value) == ("The recipe expects the column 'TWT auto', which the file does not have. The file has the column 'TWT_auto', which the recipe "
                            "does not describe. No repair was applied.")  # without the mapping: the reading's sentence, not the transport's
    tabbed = folder(tmp_path, 'odt', {'horizon.xyz': HORIZON.replace(b' ', b'\t')})
    tab = Choices(changes={ODT: [{'setting': 'delimiter', 'target': 'file', 'to': 'tab', 'reason': 'The file separates values with tabs.'}]})
    assert runs.inspected(runs.open(tabbed), tab, ready=False)['odt/horizon.xyz'].answer['preview'][0] == [605123.5, 6078901.25, 1.234]
    role = Choices(changes={ODT: [{'setting': 'column-role', 'target': '#3', 'to': 'attribute', 'reason': 'Z is a pick quality here.'}]})
    with pytest.raises(Refused) as e: runs.inspected(runs.open(tabbed), role, ready=False)
    assert str(e.value) == 'This kind of file has no attributes.'



def test_a_companion_changed_strict_and_lenient_cancel_and_an_old_preview(web, tmp_path, monkeypatch):
    # mutation: the upload re-using an earlier inspection (the changed README's set is not the one added); the preview-again
    # start not looked at again; a strict project's open field added
    from project_gateway import recipe_receipts
    from project_gateway.tests.test_intake_defaults_reach import settle
    from ophiolite import recipes
    alice = client(web, 'alice', 'delegate')
    runs = alice.upload_runs
    pts = folder(tmp_path, 'pts', {'points.txt': PRIMARY, 'README.txt': README, 'points.crsmeta.xml': CRS})
    left = Choices(leave={PETREL: ['vertical_datum']}, why={PETREL: {'vertical_datum': DATUM}})
    before = runs.inspected(runs.open(pts), left, ready=False)['pts/points.txt']
    (pts / 'README.txt').write_bytes(README + b'Checked again on 12 October.\n')
    settle(web.a, require_complete_context=True)
    strict = runs.upload(pts, attribution='Synthetic', rights_confirmed=True, scientific=left)
    item = next(i for i in strict.items if i['role'] == 'primary')
    assert item['state'] == 'needs-decision' and item['scientific_decisions'] != before.staged_set
    datum = Choices(select={PETREL: {'vertical_datum': 'NAP (EPSG:5709)'}}, why={PETREL: {'vertical_datum': 'The README states NAP.'}})
    decided = runs.upload(pts, attribution='Synthetic', rights_confirmed=True, scientific=datum)  # other decisions: not the waiting upload resumed
    assert decided.run_id != strict.run_id and [i['state'] for i in decided.items if i['role'] == 'primary'] == ['added']
    runs.cancel(strict.run_id)
    pts = folder(tmp_path, 'again', {'points.txt': PRIMARY + b'\n', 'README.txt': README, 'points.crsmeta.xml': CRS})
    settle(web.a, require_complete_context=False)
    issued, real = [], recipes.Scientific.preview
    def first_expired(self, profile, staged, raw):
        monkeypatch.setattr(recipe_receipts, 'VALIDITY', -1 if not issued else 86400)
        issued.append(staged); return real(self, profile, staged, raw)
    monkeypatch.setattr(recipes.Scientific, 'preview', first_expired)
    added = runs.upload(pts, attribution='Synthetic', rights_confirmed=True, scientific=left)
    assert [i['state'] for i in added.items if i['role'] == 'primary'] == ['added'] and len(issued) == 2
    assert [d for d in landed(alice, added).decisions if d.field == 'vertical_datum'][0].status == 'needs-decision'


def test_a_reading_layout_is_reused_by_name_and_one_of_another_kind_is_refused_naming_it(keyed, tmp_path, monkeypatch, capsys):
    # mutation: --layout ignored for a point export (the default reading lands); the kind check dropped
    from ophiolite.models.api import LayoutViewAnswer
    alice = client(keyed, 'alice', 'delegate')
    columns = ['X', 'Y', 'Z', 'TWT auto', 'KIDTAG,Name', 'KIDTAG,Data type', 'FLOAT,PointsNr']
    roles = {'X': 'x', 'Y': 'y', 'Z': 'z'}
    doc = {'layout_kind': 'import-recipe', 'target': PETREL, 'name': 'ConSeil points', 'columns': columns, 'reading': {},
           'mapping': {'columns': [{'source': c, 'role': roles.get(c, 'attribute'), 'kind': 'text' if c.startswith('KIDTAG') else 'number'} for c in columns], 'parsing': {'missing': []}, 'labels': {}},
           'declarations': {'positive': {'value': 'up', 'reason': POSITIVE}, 'vertical_datum': {'value': 'MSL', 'reason': 'The survey report gives MSL.'},
                            'z_meaning': {'value': 'time', 'reason': TIME}, 'z_unit': {'value': 'ms', 'reason': UNIT}}}
    alice.layouts()._call('save', {'command_id': 'keep-reading', 'layout': doc}, LayoutViewAnswer)
    alice.layouts().save('well-tops', 'Tubbergen tops', ['Well Name', 'Top', 'MD (m)', 'TVD (m)'], {'well': 'Well Name', 'name': 'Top', 'md': 'MD (m)', 'tvd': 'TVD (m)'})
    pts = folder(tmp_path, 'pts', {'points.txt': PRIMARY, 'points.crsmeta.xml': CRS})
    key = create(keyed, 'write')['key']
    run = lambda *argv: command(keyed, tmp_path, monkeypatch, list(argv), key, False)
    assert run('layouts', 'list') == 0
    assert 'ConSeil points · Reading layout: Petrel points with attributes · 7: X, Y, Z and 4 more' in capsys.readouterr().out
    assert run('upload', str(pts), '--attribution', 'Synthetic', '--rights-confirmed', '--layout', 'Tubbergen tops') == 1
    assert capsys.readouterr().err.strip().endswith('The layout "Tubbergen tops" is a table layout (Well tops); it does not read Petrel points with attributes.')
    assert run('upload', str(pts), '--attribution', 'Synthetic', '--rights-confirmed', '--layout', 'ConSeil points') == 0
    capsys.readouterr()
    points = landed(alice, alice.upload_runs.status(alice.upload_runs.list()[0]['run_id']))
    assert said(points) == EXPECTED_LAYOUT
    one = folder(tmp_path, 'one', {'points.txt': PRIMARY + b'\n'}) / 'points.txt'  # one .txt file is a point export here, not a table
    assert run('upload', str(one), '--attribution', 'Synthetic', '--rights-confirmed', '--layout', 'ConSeil points', '--declare', PETREL + ':crs=EPSG:23031',
               '--why', PETREL + ':crs=The export was made in ED50.') == 0
    assert printed(capsys)[0] == 'points.txt - 1 files - Finished. 1 Added, 0 Already here, 0 Needs your decision, 0 Not read, 0 Not supported'

