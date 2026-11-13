"""E142 s2a, the two-project case through the real gateway (the Validation Record's missing test): one OpendTect export
built into project p and into a second project q, each from its own build folder (a folder is bound to one project).

The unit test `tests/test_surveys_client.py::test_one_export_placed_into_two_projects_is_two_commands_and_two_records`
proves the seeds and the journal against a stand-in; here the same export lands and is placed in two real projects of
the in-process gateway (`test_in_process_publish`'s `web`). The second project is this module's own fixture: the
project and alice's membership in the control database (as `web` writes p's), the platform's answer naming it, and
alice's access key for q by web's own access-key rule, so both clients sign in the same way (a key per project; the
gateway has no public operation that makes a project, and the survey operations refuse application grants). Every expected value is a literal counted by hand from the export
(test_starter_survey's ROLES). Each test names the mutation it catches. Synthetic data only."""
import pytest

from ophiolite import Client, Credential
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_starter_survey import IDENTITY, build, copy, events, expected, export_once, journal, landed, placed  # noqa: F401 (fixture)

pytest.importorskip('numpy')
pytest.importorskip('pyproj')
pytest.importorskip('lasio')

OTHER = 'q'
# the roles of the six landed files and the two wells' keys, counted by hand (one cube, one line, one horizon, three well files)
ROLES = ['cube', 'horizon', 'line', 'well', 'well', 'well']
WELL_KEYS = ['Syn_Survey/SYN-A', 'Syn_Survey/SYN-B']


@pytest.fixture
def two(web, service, monkeypatch):  # noqa: F811
    """(alice in p, alice in q): q made with alice as a member, alice signed in to each with an access key for that
    project (the survey operations take a session or an access key, never an application grant)."""
    from project_gateway.automation import Automation
    permissions = web.permissions
    projects = lambda t: [{'id': x, **permissions[t]} for x in ('p', OTHER)] if t in permissions else []
    with service.connect() as db:
        db.execute('INSERT INTO ab_projects(id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING', (OTHER, 'Second'))
        db.execute('INSERT INTO ab_members(project_id,user_id,role,can_compute) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                   (OTHER, 'alice', permissions['alice']['role'], permissions['alice']['can_compute']))
    monkeypatch.setattr(service, 'account', lambda token: {'user_id': token, 'projects': projects(token)})
    prior = web.a.sources.platform
    monkeypatch.setattr(web.a.sources, 'platform', lambda m, body, t: (
        {'members': [{'user_id': 'alice'}]} if m == 'ListProjectMembers' and (body or {}).get('project_id') == OTHER
        else {'user_id': t, 'projects': projects(t)} if m == 'ListProjects' else prior(m, body, t)))
    key = Automation.authorize  # web's stand-in: oph_api_<persona>:<scopes> is a key for p only

    def authorize(self, token, project, scope):  # alice's key for q, by the same rule (the scope list is the ceiling)
        name, _, scopes = token.removeprefix('oph_api_').partition(':')
        if project != OTHER: return key(self, token, project, scope)
        if name != 'alice' or scope not in scopes.split(','): raise PermissionError('Automation scope denied')
        return name, OTHER, scopes.split(',')
    monkeypatch.setattr(Automation, 'authorize', authorize)
    second = Client('https://workspace.example', OTHER, Credential.bearer('oph_api_alice:read,write'), web.c)
    return client(web, 'alice', 'delegate'), second


def keys(c):
    return sorted((w.document.get('identity') or {}).get('key') for w in c.wells() if (w.document.get('identity') or {}).get('authority') == IDENTITY['authority'])


def snapshot(c):
    """Everything a rerun could add to one project: its surveys with revision and history, its wells, its assets."""
    return ([(s['survey_id'], s['revision'], tuple(events(c, s['survey_id']))) for s in c.surveys()], keys(c),
            sorted((a['asset_id'], a['revision']) for a in c.assets()))


def test_one_export_into_two_projects_is_one_survey_each_two_commands_and_two_records(export_once, tmp_path, two):
    """Mutations (place_survey): the create's command id from the export alone, the project and the body out of its seed
    (one id in both projects: the gateway refuses q's create as a reused command id, so the build into q raises); the
    placement record not keyed by project (`state['project']` not written: the record-per-project line fails). The
    project alone out of the seed is not observable here: the body hashed into the seed names each project's own
    asset ids, so the two ids still differ (the unit test, with one journal's assets, catches that one)."""
    folder, export = copy(export_once, tmp_path)
    alice, other = two
    build(alice, folder, export, pack='pack-p')
    build(other, folder, export, pack='pack-q')
    (first,), (second,) = list(alice.surveys()), list(other.surveys())  # one survey per project
    assert first['identity'] == second['identity'] == IDENTITY and first['survey_id'] != second['survey_id']
    records = {name: journal(folder, name)['survey'] for name in ('pack-p', 'pack-q')}
    assert [r['project'] for r in records.values()] == ['p', OTHER]  # two placement records, one per project
    assert [r['placed']['survey_id'] for r in records.values()] == [first['survey_id'], second['survey_id']]
    assert [(r['placed']['revision'], r['placed']['identity'], r['pending']) for r in records.values()] == [(1, {'authority': 'opendtect:lab-7', 'key': 'Syn_Survey'}, None)] * 2
    ids = [r['placed']['command_id'] for r in records.values()]
    assert len(set(ids)) == 2 and all(len(i) == 32 for i in ids)  # two distinct command ids, one per project
    assert events(alice, first['survey_id']) == events(other, second['survey_id']) == [('create', 1)]
    assert landed(folder, 'pack-p') != landed(folder, 'pack-q')  # each project holds its own six files
    assert len(landed(folder, 'pack-p')) == len(landed(folder, 'pack-q')) == 6


def test_each_projects_survey_holds_its_own_members_and_wells_by_identity(export_once, tmp_path, two):
    """Mutation (place_survey): a well file's member placed without its well (role `other`, no entity: the members line
    fails in p). The project out of the wells import's seed is not observable here: q's import still makes q's wells."""
    folder, export = copy(export_once, tmp_path)
    alice, other = two
    build(alice, folder, export, pack='pack-p')
    build(other, folder, export, pack='pack-q')
    for c, pack in ((alice, 'pack-p'), (other, 'pack-q')):
        (survey,) = list(c.surveys())
        members, relations = placed(c, survey['survey_id'])
        assert (members, relations) == expected(c, folder, pack)
        assert sorted(m[0] for m in members) == ROLES and len(relations) == 3 and keys(c) == WELL_KEYS
    wells = [{w.entity_id for w in c.wells() if (w.document.get('identity') or {}).get('authority') == IDENTITY['authority']} for c in two]
    assert len(wells[0]) == len(wells[1]) == 2 and not wells[0] & wells[1]


def test_a_rerun_into_either_project_adds_nothing(export_once, tmp_path, two):
    """Mutations (place_survey): the placement record not keyed by project (the rerun's record line fails); a rerun that
    neither finds the project's survey by identity nor repeats its command id (a new create per run: the new folder's
    build into q is refused, its identity taken). Either guard alone keeps the rerun empty: without the find the same
    create body repeats the same id; with an id per run the find restates identical lists, no revision."""
    folder, export = copy(export_once, tmp_path)
    alice, other = two
    build(alice, folder, export, pack='pack-p')
    build(other, folder, export, pack='pack-q')
    before = [snapshot(alice), snapshot(other)]
    ids = [journal(folder, n)['survey']['placed']['command_id'] for n in ('pack-p', 'pack-q')]
    build(other, folder, export, pack='pack-q')  # the same folder again
    build(alice, folder, export, pack='pack-p')
    build(other, folder, export, pack='again-q')  # a new folder into q: the same lists, so no revision
    assert [snapshot(alice), snapshot(other)] == before
    assert [len(s[0]) for s in before] == [1, 1] and [s[0][0][1:] for s in before] == [(1, (('create', 1),))] * 2
    assert [journal(folder, n)['survey']['placed']['command_id'] for n in ('pack-p', 'pack-q')] == ids
    again = journal(folder, 'again-q')['survey']
    assert (again['project'], again['placed']['survey_id'], again['placed']['revision']) == (OTHER, before[1][0][0][0], 1)
