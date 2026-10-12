"""E23b B7: the scientific options of `ophiolite inspect` and `ophiolite upload` offline: what a person says becomes the
staged decisions and changes the Platform keeps (`las-uploads/decision-set`, Integration strategy B2), each with its reason;
a reason is required only for a point export and refused client side above 120 characters; `--declare` of every other kind
travels exactly as before. Printed inspections are in words; `--details` and `details()` carry ids and enum values. The
journey against the real gateway is tests/gateway/test_recipes_live.py."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from ophiolite import cli, recipes
from ophiolite.errors import Refused
from ophiolite.layouts import columns_line, holds, list_lines, reading_lines

PETREL, ODT = 'petrel-points-attributes/1', 'opendtect-horizon-ascii/1'
OBS = 'a' * 64
ANSWER = {'sha256': 'b' * 64, 'profile': PETREL, 'context': {'count': 4}, 'preview': [[605123.5, 6078901.25, 1.234]], 'status': 'needs-decision',
          'unresolved': ['z_meaning'], 'preview_receipt': 'v1.receipt-token', 'reading': {'columns': [], 'parsing': {}, 'delimiter': False, 'attributes': True},
          'decisions': [
              {'field': 'crs', 'observations': [{'id': OBS, 'value': 'EPSG:23031', 'source': 'crs-metadata', 'role': 'crs-metadata', 'sufficient': True}],
               'selected': 'EPSG:23031', 'selected_by': 'recipe', 'reason': 'recipe-rule:crs-metadata', 'status': 'decided'},
              {'field': 'positive', 'observations': [], 'selected': 'up', 'selected_by': 'declaration', 'reason': 'Petrel exports these values positive up.', 'status': 'decided'},
              {'field': 'vertical_datum', 'observations': [], 'selected': None, 'selected_by': None, 'reason': '', 'status': 'needs-decision',
               'left_unresolved': 'e' + 'd' * 32},
              {'field': 'z_meaning', 'observations': [], 'selected': None, 'selected_by': None, 'reason': '', 'status': 'needs-decision'}]}


def args(*argv):
    return cli.parser().parse_args(['upload', 'pts', '--rights-confirmed', *argv])


def test_each_choice_becomes_a_staged_decision_with_its_reason_in_field_order():
    # mutation: a selection kept without its observation; a left field without its reason; fields out of order
    choices = cli._choices(args('--declare', PETREL + ':positive=up', '--why', PETREL + ':positive=Petrel exports these values positive up.',
                                '--select', PETREL + ':crs=EPSG:23031', '--why', PETREL + ':crs=The coordinate file of the export states ED50.',
                                '--leave-unresolved', PETREL + ':vertical_datum', '--why', PETREL + ':vertical_datum=The datum is not known yet.'))
    assert choices.given(PETREL) and not choices.given(ODT)
    assert choices.decisions(PETREL, {'decisions': ANSWER['decisions']}) == [
        {'kind': 'select-evidence', 'field': 'crs', 'observation': OBS, 'reason': 'The coordinate file of the export states ED50.'},
        {'kind': 'declare', 'field': 'positive', 'value': 'up', 'reason': 'Petrel exports these values positive up.'},
        {'kind': 'leave-unresolved', 'field': 'vertical_datum', 'reason': 'The datum is not known yet.'}]
    with pytest.raises(Refused) as e: choices.decisions(PETREL, {'decisions': [{**ANSWER['decisions'][0], 'observations': []}]})
    assert str(e.value) == 'The files state no Coordinate system of EPSG:23031.'


def test_a_point_export_needs_a_reason_and_a_long_one_is_refused_with_its_count():
    # mutation: the bound at 121; a declaration without --why sent with no reason
    with pytest.raises(Refused) as e: cli._choices(args('--declare', PETREL + ':positive=up')).decisions(PETREL)
    assert str(e.value) == recipes.SAY_WHY % (PETREL, 'positive')
    long = 'x' * 121
    with pytest.raises(Refused) as e: cli._choices(args('--declare', PETREL + ':positive=up', '--why', PETREL + ':positive=' + long)).decisions(PETREL)
    assert str(e.value) == 'A reason is at most 120 characters; this one has 121. Nothing was cut; shorten it. (Positive direction)'
    assert cli._choices(args('--declare', PETREL + ':positive=up', '--why', PETREL + ':positive=' + 'x' * 120)).decisions(PETREL)[0]['reason'] == 'x' * 120
    with pytest.raises(Refused) as e: cli._choices(args('--why', PETREL + ':z_unit=ms')).decisions(PETREL)
    assert str(e.value) == '--why %s:z_unit gives a reason for nothing you decided.' % PETREL
    with pytest.raises(Refused) as e: cli._choices(args('--why', 'esri-ascii-grid/1:crs=The grid header.'))
    assert str(e.value).startswith('--why, --select and --leave-unresolved are for Petrel and OpendTect point exports')


def test_other_kinds_declare_exactly_as_before_and_need_no_reason(monkeypatch):
    # mutation: --why made global (an ESRI grid's --declare refused without a reason) or the point-export filter widened
    sent = {}
    class Runs:
        def upload(self, path, **kw): sent.update(kw); raise SystemExit(0)
    client = SimpleNamespace(upload_runs=Runs())
    monkeypatch.setattr(cli, '_layout_upload', lambda a, c: None)
    with pytest.raises(SystemExit): cli._upload(args('--declare', 'esri-ascii-grid/1:crs=EPSG:28992', '--declare', 'segy/1:z_domain=time'), client)
    assert sent['declare'] == {'esri-ascii-grid/1': {'crs': 'EPSG:28992'}, 'segy/1': {'z_domain': 'time'}} and sent['scientific'] is None
    with pytest.raises(SystemExit): cli._upload(args('--declare', 'esri-ascii-grid/1:crs=EPSG:28992', '--declare', PETREL + ':positive=up', '--why', PETREL + ':positive=Up.'), client)
    assert sent['declare'] == {'esri-ascii-grid/1': {'crs': 'EPSG:28992'}} and sent['scientific'].declare == {PETREL: {'positive': 'up'}}


def test_a_config_file_is_an_unsaved_draft_attributed_to_the_line_it_names():
    # mutation: the evidence member not the primary's digest; the locator not the first line holding the text
    primary = b'# Petrel Points with attributes\nX Y Z "TWT_auto"\n1 2 -1234.5 3\n'
    changes = recipes.changes_of({'changes': [
        {'setting': 'label-map', 'target': 'TWT auto', 'to': 'TWT_auto', 'reason': 'The export spells it with an underscore.'},
        {'setting': 'missing-marker', 'target': 'file', 'to': ['-1234.5'], 'reason': 'Z of -1234.5 marks no value here.'},
        {'setting': 'delimiter', 'target': 'file', 'to': 'tab', 'reason': 'Tabs.', 'line': 7}]}, primary)
    member = hashlib.sha256(primary).hexdigest()
    assert [(c['setting'], c['evidence']) for c in changes] == [('label-map', {'member': member, 'locator': 'line 2'}), ('missing-marker', {'member': member, 'locator': 'line 3'}),
                                                                ('delimiter', {'member': member, 'locator': 'line 7'})]
    with pytest.raises(Refused) as e: recipes.changes_of({'changes': [{'setting': 'delimiter', 'target': 'file', 'to': 'tab', 'reason': ' '}]}, primary)
    assert str(e.value) == 'Say why, in a few words. (delimiter of file)'


def test_companions_travel_with_their_primary_as_the_workspace_groups_them():
    from ophiolite.upload_runs import readers
    paths = ['a/points.txt', 'a/points.crsmeta.xml', 'a/README.txt', 'b/horizon.xyz', 'b/README.txt', 'c/one.txt', 'c/two.txt', 'c/README.txt']
    assert recipes.companions(paths, readers()) == {'a/points.txt': [('a/README.txt', 'readme'), ('a/points.crsmeta.xml', 'crs-metadata')],
                                                    'b/horizon.xyz': [('b/README.txt', 'readme')]}  # c/README.txt: two primaries could take it


def test_an_inspection_prints_words_and_its_details_carry_the_particulars():
    # mutation: the reason of a field the recipe decided printed (a raw rule code); an open field said by its key
    seen = recipes.Inspection('pts/points.txt', PETREL, 'c' * 64, ANSWER)
    assert seen.lines() == ['pts/points.txt: Petrel points with attributes, 4 points', '  Coordinate system: EPSG:23031',
                            "  Positive direction: up because 'Petrel exports these values positive up.'",
                            '  Vertical datum: left unresolved', '  Values: needs a decision', 'Still needs a decision: Values.']
    printed = '\n'.join(seen.lines()) + repr(seen)
    assert not [t for t in (OBS, 'c' * 64, 'd' * 32, 'v1.receipt-token', 'recipe-rule', 'z_meaning', 'needs-decision', 'vertical_datum', 'declaration') if t in printed]
    assert not seen.ready and seen.pin() == {'scientific_decisions': 'c' * 64, 'preview_receipt': 'v1.receipt-token'}
    assert seen.details()['decisions'][0]['selected_by'] == 'recipe' and seen.details()['staged_set'] == 'c' * 64


READING = {'asset_id': 'layout-r', 'name': 'ConSeil points', 'target': PETREL, 'kind': 'import-recipe', 'state': 'active', 'by': 'header', 'version': 1, 'head_version': 1,
           'generation': 1, 'made_by': 'alice', 'made_at': 1760083200.0, 'last_used': None,
           'layout': {'mapping': {'columns': [{'source': 'X', 'role': 'x', 'kind': 'number'}, {'source': 'KIDTAG,Data type', 'role': 'attribute', 'kind': 'category'}]},
                      'declarations': {'positive': {'value': 'up', 'reason': 'Petrel exports these values positive up.'}, 'crs': {'value': 'EPSG:28992', 'reason': 'RD New.'}}},
           'declared_by': {'positive': {'actor': 'alice'}, 'crs': {'actor': 'bob', 'imported_by': 'bob'}}}


def test_a_reading_layout_is_listed_with_its_kind_and_shown_with_who_declared_each_value():
    # mutation: holds() without the kind (a reading layout said to hold "Points"); the importer said as the declarer
    who = {'alice': 'Anna de Vries', 'bob': 'Bram Jansen'}.get
    assert holds(READING) == 'Reading layout: Petrel points with attributes' and holds({**READING, 'kind': 'table-mapping', 'target': 'point-set'}) == 'Points'
    assert columns_line(READING) == '2: X, KIDTAG,Data type'
    assert list_lines([READING], {'alice': 'Anna de Vries'})[0].startswith('ConSeil points · Reading layout: Petrel points with attributes · 2: X, KIDTAG,Data type · Made by Anna de Vries')
    assert reading_lines(READING, who) == ['  X: X (easting), Number', '  KIDTAG,Data type: Attribute, Category', 'Coordinate system: EPSG:28992. Imported by Bram Jansen: RD New.',
                                           'Positive direction: up. Declared by Anna de Vries: Petrel exports these values positive up.']


def test_a_layout_of_another_kind_is_refused_naming_it():
    # mutation: the kind check dropped (a table layout's id sent as a reading layout)
    table = {**READING, 'name': 'Tubbergen tops', 'kind': 'table-mapping', 'target': 'well-tops'}
    for view, said in ((table, 'The layout "Tubbergen tops" is a table layout (Well tops); it does not read Horizon points (OpendTect).'),
                       (READING, 'The layout "ConSeil points" reads Petrel points with attributes; it does not read Horizon points (OpendTect).')):
        client = SimpleNamespace(layouts=lambda view=view: SimpleNamespace(find=lambda name: view))
        with pytest.raises(Refused) as e: recipes.Scientific(client).layout_pin(view['name'], ODT)
        assert str(e.value) == said
    assert recipes.Scientific(SimpleNamespace(layouts=lambda: SimpleNamespace(find=lambda name: READING))).layout_pin('ConSeil points', PETREL) == {'asset_id': 'layout-r', 'generation': 1}


def test_the_decision_set_route_is_an_sdk_operation():
    from ophiolite.publish import operation_path
    assert operation_path('p', 'las-uploads', 'decision-set') == '/api/v1/projects/p/las-uploads/decision-set'
    json.dumps(ANSWER)  # the recorded shape stays plain JSON


def test_a_table_is_not_held_back_by_a_reading_layout_with_the_same_columns(tmp_path):
    # mutation: the match filter dropped (a .csv whose header a reading layout also has would wait for a decision)
    table = tmp_path / 'points.csv'; table.write_bytes(b'X,Y,Z\n1,2,3\n')
    match = {'name': 'ConSeil points', 'kind': 'import-recipe'}
    client = SimpleNamespace(layouts=lambda: SimpleNamespace(list=lambda retired: [READING], match=lambda columns: [match]),
                             imports=SimpleNamespace(read=lambda path: {'columns': [{'name': 'X'}, {'name': 'Y'}, {'name': 'Z'}]}))
    assert cli._layout_upload(cli.parser().parse_args(['upload', str(table), '--rights-confirmed']), client) is None
