"""E142 s2a C3 (strategy D-P, D-W, §6 acceptance 7): `ophiolite starter build --export` places the export's survey.

The export is the real one (`ophiolite_opendtect.export` on the fake odbind, in its own process, as
test_starter_export runs it) of `Syn_Survey` with one cube (Syn), one 2D line (Syn2D/L1: SEG-Y like the cube, another
role, §0a M7), the horizon Top and the wells SYN-A (path and log) and SYN-B (path only), exported with a fixed
`--instance`. The build lands every file into the real gateway (in process) and places one survey: identity
`opendtect:<instance>`/`Syn_Survey`, a member per landed file by kind, the wells made by identity and every well file
associated, and the relations the export states (each well file in the one cube). Every expected member and edge is a
literal counted by hand. Each test names the mutation it catches. A gateway module: it reads the connector and the
fixtures from the monorepo, above the SDK tree."""
import json
import os
import shutil

import pytest

from ophiolite import starter
from ophiolite.errors import Refused
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_starter_archive_pack import another, current
from test_starter_export import CONNECTOR, FAKE, made, run
from test_starter_lines import CRS, lined

pytest.importorskip('numpy')
pytest.importorskip('pyproj')
pytest.importorskip('lasio')

INSTANCE = 'lab-7'
IDENTITY = {'authority': 'opendtect:lab-7', 'key': 'Syn_Survey', 'provisional': False}
# path -> role, counted by hand from the contents below (one cube, so each well file is in it)
ROLES = {'seismic/Syn.sgy': 'cube', 'seismic2d/Syn2D/L1.sgy': 'line', 'horizons/Top.csv': 'horizon',
         'wells/SYN-A-positions.csv': 'well', 'wells/SYN-A.las': 'well', 'wells/SYN-B-positions.csv': 'well'}
WELL_OF = {'wells/SYN-A-positions.csv': 'SYN-A', 'wells/SYN-A.las': 'SYN-A', 'wells/SYN-B-positions.csv': 'SYN-B'}


def one_cube(d):
    """The survey's contents with one cube (Syn) and one 2D line; Syn2's decisions go with it."""
    d['contents'][0]['ids'] = ['Syn']
    d['decisions'] = [x for x in d['decisions'] if x['subject'] != 'Syn2']
    lined(d, ids=('Syn2D/L1',))


def exported(folder, out, instance=INSTANCE, variant=None):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        if variant: mp.setenv('FAKE_ODBIND_VARIANT', variant)
        else: mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
        return run(folder, out, **({'instance': instance} if instance is not None else {}))


@pytest.fixture(scope='module')
def export_once(tmp_path_factory):
    folder = made(tmp_path_factory.mktemp('definition'), edit=one_cube)
    out = tmp_path_factory.mktemp('export')
    exported(folder, out)
    return folder, out


def copy(export_once, tmp_path):
    folder, out = export_once
    shutil.copytree(folder, tmp_path / 'definition'); shutil.copytree(out, tmp_path / 'export')
    return tmp_path / 'definition', tmp_path / 'export'


def build(c, folder, export, pack='pack', restate=False):
    return starter.build(c, folder / 'definition.json', folder / pack, catalogue=folder / 'records.json', verification=folder / 'verification',
                         custody=folder / 'custody', export=export, place=True, restate=restate)


def journal(folder, pack='pack'):
    return json.loads((folder / pack / 'landing.json').read_text())


def refused(fn, *args, **kw):
    with pytest.raises(Refused) as caught: fn(*args, **kw)
    return str(caught.value)


def landed(folder, pack='pack'):
    return {n: (e['asset_id'], e['revision']) for n, e in journal(folder, pack)['inputs'].items()}


def expected(c, folder, pack='pack'):
    """(members, relations) the build must have placed, from the hand-counted ROLES and the wells by identity."""
    at = landed(folder, pack)
    wells = {(w.document.get('identity') or {}).get('key'): w.entity_id for w in c.wells()}
    members = sorted(((ROLES[n], *at[n], wells['Syn_Survey/' + WELL_OF[n]] if n in WELL_OF else None) for n in ROLES), key=lambda m: m[1:3])
    cube = at['seismic/Syn.sgy']
    relations = sorted(('well-in', *at[n], *cube) for n in WELL_OF)
    return members, relations


def placed(c, survey_id, revision=None):
    s = c.survey(survey_id, revision)
    return (sorted(((m.role, m.asset_id, m.revision, m.entity.id if m.entity else None) for m in s.members), key=lambda m: m[1:3]),
            sorted((r.predicate, r.subject.asset_id, r.subject.revision, r.object.asset_id, r.object.revision) for r in s.relations))


def test_the_build_places_one_survey_by_identity_with_a_member_per_file_and_the_wells_by_identity(export_once, tmp_path, web):  # noqa: F811
    """Mutations: the role table keyed by profile instead of kind (the 2D line placed as a cube); wells made under
    another authority or key (the members' entities differ)."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    build(alice, folder, export)
    state = journal(folder)['survey']
    (survey,) = list(alice.surveys())
    assert survey['identity'] == IDENTITY and state['placed']['survey_id'] == survey['survey_id'] and state['placed']['revision'] == 1
    assert state['pending'] is None and state['loose'] == [] and state['said'] == []
    members, relations = expected(alice, folder)
    assert placed(alice, survey['survey_id']) == (members, relations)
    assert sorted(m[0] for m in members) == ['cube', 'horizon', 'line', 'well', 'well', 'well'] and len(relations) == 3
    keys = sorted((w.document.get('identity') or {}).get('key') for w in alice.wells() if (w.document.get('identity') or {}).get('authority') == 'opendtect:lab-7')
    assert keys == ['Syn_Survey/SYN-A', 'Syn_Survey/SYN-B']
    for n, well in WELL_OF.items():  # every well file associated with its well once (D-W)
        entity = next(w.entity_id for w in alice.wells() if (w.document.get('identity') or {}).get('key') == 'Syn_Survey/' + well)
        assert [(i['asset_id'], i['revision']) for i in alice.data(entity)].count(landed(folder)[n]) == 1


def newer(export):
    """A newer export of the same survey in another export folder: Top's depths 1 ms deeper, SYN-A's log gone."""
    def change(target, report):
        top = target / 'files/horizons/Top.csv'
        head, *rows = top.read_text().splitlines()
        deeper = lambda i, v: repr(float(v) + 1.0) if i == 2 and v else v  # an undefined node (empty z) stays undefined
        top.write_text('\n'.join([head] + [','.join(deeper(i, v) for i, v in enumerate(r.split(','))) for r in rows]) + '\n')
        d = next(d for d in report['derived'] if d['path'] == 'horizons/Top.csv')
        d['sha256'], d['bytes'] = sa_digest(top)
        (target / 'files/wells/SYN-A.las').unlink()
        report['derived'] = [d for d in report['derived'] if d['path'] != 'wells/SYN-A.las']
        report['files'] = [f for f in report['files'] if f['path'] != 'wells/SYN-A.las']
    return another(export, 'newer', change)


def sa_digest(path):
    from ophiolite import starter_archive
    return starter_archive.digest_of(path)


def events(c, survey_id):
    return [(e['kind'], e['revision']) for e in c.survey_history(survey_id)]


def test_a_reimport_restates_only_the_change_and_an_identical_build_makes_no_revision(export_once, tmp_path, web):  # noqa: F811
    """Mutations: the reimport as close-all-open-all (the restate's event names every member); identical lists making a
    revision (a third build moves the survey to revision 3)."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    build(alice, folder, export)
    first = landed(folder)
    (survey,) = list(alice.surveys())
    newer(export)
    build(alice, folder, export, pack='again')
    second = landed(folder, 'again')
    state = journal(folder, 'again')['survey']
    assert state['placed']['survey_id'] == survey['survey_id'] and state['placed']['revision'] == 2
    assert [s['survey_id'] for s in alice.surveys()] == [survey['survey_id']]
    assert second['horizons/Top.csv'] != first['horizons/Top.csv'] and 'wells/SYN-A.las' not in second
    assert {n: k for n, k in second.items() if n != 'horizons/Top.csv'} == {n: k for n, k in first.items() if n not in ('horizons/Top.csv', 'wells/SYN-A.las')}
    restated = next(e for e in alice.survey_history(survey['survey_id']) if e['kind'] == 'restate')
    assert sorted((m['asset_id'], m['revision']) for m in restated['before']['members']) == sorted([first['horizons/Top.csv'], first['wells/SYN-A.las']])
    assert [(m['asset_id'], m['revision']) for m in restated['after']['members']] == [second['horizons/Top.csv']]
    assert [(r['subject']['asset_id'], r['subject']['revision']) for r in restated['before']['relations']] == [first['wells/SYN-A.las']]
    members, relations = placed(alice, survey['survey_id'])
    assert [m[1:3] for m in members] == sorted(second.values()) and len(relations) == 2
    build(alice, folder, export, pack='third')  # the same export again, a third folder: the same lists
    assert journal(folder, 'third')['survey']['placed']['revision'] == 2 and alice.survey(survey['survey_id']).revision == 2
    assert events(alice, survey['survey_id']) == [('restate', 2), ('create', 1)]


def test_a_file_already_in_the_project_is_left_loose_and_linked_by_the_person(export_once, tmp_path, web):  # noqa: F811
    """The horizon's same bytes were added to the project by hand before the build, so the build lands it already-here.
    Mutation: the already-here filter removed (the horizon placed as a member by the build alone); link stored as add."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    top = current(export) / 'files/horizons/Top.csv'
    declared = starter.declarations(json.loads((current(export) / 'derived.json').read_text())['survey'], {'horizons'})['horizons']
    alice.upload(top, declare={'points-csv/1': declared}, attribution='Synthetic test', audience=['alice', 'bob'], rights_confirmed=True)
    build(alice, folder, export)
    state = journal(folder)['survey']
    top_key = landed(folder)['horizons/Top.csv']
    assert journal(folder)['inputs']['horizons/Top.csv']['landed_as'] == 'already-here'
    assert state['loose'] == [{'name': 'horizons/Top.csv', 'asset_id': top_key[0], 'revision': top_key[1], 'sentence': starter.LOOSE}]
    sid = state['placed']['survey_id']
    members, _ = placed(alice, sid)
    assert top_key not in [m[1:3] for m in members] and len(members) == 5
    alice.link_survey_members(sid, 1, [{'role': 'horizon', 'asset_id': top_key[0], 'revision': top_key[1]}])
    assert top_key in [m[1:3] for m in placed(alice, sid)[0]] and events(alice, sid) == [('link', 2), ('create', 1)]


def test_the_instance_names_the_survey_and_the_default_is_the_installations_kept_id(export_once, tmp_path, web, config_home):  # noqa: F811
    """`--instance lab-7` and the installation's own id (kept under this test's XDG_CONFIG_HOME) give two surveys of one
    container. Mutation: the identity not taken from the export's facts (both builds would name one survey)."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    build(alice, folder, export)
    exported(folder, export, instance=None)
    kept = (config_home / 'ophiolite/opendtect-instance').read_text().strip()
    build(alice, folder, export, pack='default')
    assert sorted((s['identity']['authority'], s['identity']['key']) for s in alice.surveys()) == sorted(
        [('opendtect:lab-7', 'Syn_Survey'), ('opendtect:' + kept, 'Syn_Survey')])
    # the second build's files were already in the project (the first build landed the same bytes): loose, not acquired
    assert sorted(x['name'] for x in journal(folder, 'default')['survey']['loose']) == sorted(ROLES)


def test_an_older_connector_gives_a_provisional_survey_and_a_rebuild_a_second_one(export_once, tmp_path, web):  # noqa: F811
    """An export without `instance` (a connector before s2): a provisional survey, its well files `other` (no well is made
    under a provisional authority), said in the build's report; a rebuild in another folder is a second provisional
    survey, stated. Mutation: an export without `instance` placed under an identity (the rebuild would restate it)."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    def older(target, report):
        for k in ('instance', 'container'): report['survey'].pop(k)
    another(export, 'older', older)
    build(alice, folder, export, pack='older-1'); build(alice, folder, export, pack='older-2')
    provisional = [s for s in alice.surveys() if s['identity'].get('provisional')]
    assert len(provisional) == 2 and len(list(alice.surveys())) == 2
    assert not [w for w in alice.wells() if str((w.document.get('identity') or {}).get('authority')).startswith('opendtect:')]
    first = journal(folder, 'older-1')['survey']['said']
    assert first == ['%s: %s' % (n, starter.NO_WELL) for n in ROLES if n in WELL_OF] + [starter.OLDER_CONNECTOR]
    assert sorted(m.role for m in alice.survey(provisional[0]['survey_id']).members) == ['cube', 'horizon', 'line', 'other', 'other', 'other']


def test_a_withdrawn_survey_holding_the_identity_refuses_and_nothing_is_landed_twice(export_once, tmp_path, web):  # noqa: F811
    """Mutation: a taken identity answered by placing a second survey (or a provisional one) instead of refusing."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    build(alice, folder, export)
    sid = journal(folder)['survey']['placed']['survey_id']
    alice.withdraw_survey(sid, 1)
    assert refused(build, alice, folder, export, pack='after') == starter.WITHDRAWN
    assert landed(folder, 'after') == landed(folder) and list(alice.surveys()) == []
    assert journal(folder, 'after')['survey']['pending'] is None and journal(folder, 'after')['survey']['placed'] is None


class Lost(Exception):
    pass


def losing(monkeypatch, kinds):
    """The answer to the next survey command of KINDS is lost after the gateway committed it; the requests are kept."""
    from ophiolite.client import Client
    real, sent = Client._survey_command, []
    def command(self, kind, body, command_id):
        sent.append((kind, json.loads(json.dumps(body)), command_id))
        answer = real(self, kind, body, command_id)
        if kind in kinds and len([s for s in sent if s[0] in kinds]) == 1: raise Lost('the answer was lost')
        return answer
    monkeypatch.setattr(Client, '_survey_command', command)
    return sent


@pytest.mark.parametrize('kind', ['create', 'restate'])
def test_a_lost_answer_is_replayed_from_the_journalled_request_never_rebuilt(export_once, tmp_path, web, monkeypatch, kind):  # noqa: F811
    """Mutations: the command id regenerated per run; the pending request rebuilt from a fresh read (a lost create
    turned into a restate, a second revision)."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    pack = 'pack'
    if kind == 'restate':
        build(alice, folder, export); newer(export); pack = 'again'
    sent = losing(monkeypatch, {kind})
    with pytest.raises(Lost): build(alice, folder, export, pack=pack)
    pending = journal(folder, pack)['survey']['pending']
    assert pending == {'kind': kind, 'body': sent[0][1], 'command_id': sent[0][2]} and journal(folder, pack)['survey']['placed'] is None
    receipt = build(alice, folder, export, pack=pack) and journal(folder, pack)['survey']['placed']
    assert sent[-1] == sent[0] and len(sent) == 2
    (survey,) = list(alice.surveys())
    assert receipt['survey_id'] == survey['survey_id'] and receipt['command_id'] == sent[0][2] and alice.survey(survey['survey_id']).revision == (1 if kind == 'create' else 2)


def test_a_build_stopped_before_its_survey_command_was_journalled_makes_no_well_twice(export_once, tmp_path, web, monkeypatch):  # noqa: F811
    """The build stops after the wells were made and the create was committed, but before its pending line was kept
    (landing.json without it): the rerun finds the survey by identity, imports no well again and states the same lists
    (no revision). Mutation: the wells import sent again with the same command id (the gateway refuses it as an import
    changed since its review, now that the wells exist)."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    sent = losing(monkeypatch, {'create'})
    with pytest.raises(Lost): build(alice, folder, export)
    kept = journal(folder); kept['survey']['pending'] = None
    (folder / 'pack/landing.json').write_text(json.dumps(kept))
    wells = sorted(w.entity_id for w in alice.wells())
    build(alice, folder, export)
    (survey,) = list(alice.surveys())
    assert [s[0] for s in sent] == ['create', 'restate'] and survey['revision'] == 1 and sorted(w.entity_id for w in alice.wells()) == wells
    assert journal(folder)['survey']['placed'] == {**journal(folder)['survey']['placed'], 'survey_id': survey['survey_id'], 'revision': 1}


def test_a_hand_edit_after_the_placement_is_kept_until_the_person_restates(export_once, tmp_path, web):  # noqa: F811
    """Mutation: the history check removed (the reimport restates over the person's removal without being asked)."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    build(alice, folder, export)
    sid = journal(folder)['survey']['placed']['survey_id']
    alice.rename_survey(sid, 1, 'Syn survey (renamed)')
    alice.remove_survey_members(sid, 2, [landed(folder)['wells/SYN-B-positions.csv']])  # a person's edit of the membership
    newer(export)
    said = refused(build, alice, folder, export, pack='again')
    assert said == starter.EDITED % ('Syn survey (renamed)', 3) and alice.survey(sid).revision == 3
    build(alice, folder, export, pack='again', restate=True)
    assert alice.survey(sid).revision == 4 and alice.survey(sid).name == 'Syn survey (renamed)'
    # the person's removal holds: SYN-B's path landed already-here and is no member now, so it stays loose (D-P 1)
    again = landed(folder, 'again')
    assert [m[1:3] for m in placed(alice, sid)[0]] == sorted(k for n, k in again.items() if n != 'wells/SYN-B-positions.csv')
    assert [x['name'] for x in journal(folder, 'again')['survey']['loose']] == ['wells/SYN-B-positions.csv']


def test_journey_row_7_one_survey_of_the_stated_members_a_reimport_restates_it_and_a_loose_item_waits_for_its_link(export_once, tmp_path, web):  # noqa: F811
    """E142 journeys row 7 (`tests/fixtures/surveys/journeys.json`), its three clauses in one walk: the build creates one
    survey of the hand-counted members and edges, with the horizon a person added before it left loose; a newer export
    restates that survey (no second one); the loose horizon is a member only once the person links it. Mutations: the
    reimport as a second create (two surveys); the already-here filter removed (the horizon a member before the link);
    link sent as add (the history's last event is `add`)."""
    folder, export = copy(export_once, tmp_path)
    alice = client(web, 'alice', 'delegate')
    top = current(export) / 'files/horizons/Top.csv'
    declared = starter.declarations(json.loads((current(export) / 'derived.json').read_text())['survey'], {'horizons'})['horizons']
    alice.upload(top, declare={'points-csv/1': declared}, attribution='Synthetic test', audience=['alice', 'bob'], rights_confirmed=True)
    build(alice, folder, export)
    sid, loose = journal(folder)['survey']['placed']['survey_id'], landed(folder)['horizons/Top.csv']
    members, relations = expected(alice, folder)
    assert placed(alice, sid) == ([m for m in members if m[1:3] != loose], relations) and len(relations) == 3
    assert [x['name'] for x in journal(folder)['survey']['loose']] == ['horizons/Top.csv']
    def without_log(target, report):  # a newer export of the same survey: SYN-A's log gone (Top unchanged: the person's copy holds its path)
        (target / 'files/wells/SYN-A.las').unlink()
        report['derived'] = [d for d in report['derived'] if d['path'] != 'wells/SYN-A.las']
        report['files'] = [f for f in report['files'] if f['path'] != 'wells/SYN-A.las']
    another(export, 'newer', without_log)
    build(alice, folder, export, pack='again')
    log = landed(folder)['wells/SYN-A.las']
    assert [s['survey_id'] for s in alice.surveys()] == [sid] and alice.survey(sid).revision == 2
    assert placed(alice, sid) == ([m for m in members if m[1:3] not in (loose, log)], [r for r in relations if r[1:3] != log])
    alice.link_survey_members(sid, 2, [{'role': 'horizon', 'asset_id': loose[0], 'revision': loose[1]}])
    assert loose in [m[1:3] for m in placed(alice, sid)[0]] and events(alice, sid) == [('link', 3), ('restate', 2), ('create', 1)]
