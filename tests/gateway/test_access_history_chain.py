"""E67b C8: the SDK reads teams and the access history through the real chain.

The deployment is the Platform's real-credential one (`real_credentials.project` with the service-account schema,
`test_service_accounts.p`) plus this lane's team migration: browser sessions make steps 1-8 of the strategy's literal
list through the gateway routes (the native grant row is the native statement as written), and every SDK call uses a
real access key made through `access-keys/create`, resolved by native authentication over the real tables. Nothing is
patched. The credential refusals use the Platform's other real worlds: an application grant minted through the gateway
(`web`), a capability-2 grant approved through the gateway (`sessions`) and agent tokens registered through it (`web`).
Row 14 of the re-verification: every agent token, an administrator's or not, gets HISTORY_AGENT_REFUSED.
"""
import json
import os

import psycopg
import pytest

try:
    from project_gateway.tests.real_credentials import ORIGIN, project as credentials  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service as organizations_service  # noqa: F401 (fixture)
    from project_gateway.tests.test_service_accounts import p, made  # noqa: F401 (fixture)
    from project_gateway.tests.test_service_accounts_keys import key as account_key
    from project_gateway.tests.test_one_api_matrix import web  # noqa: F401 (fixture)
    from project_gateway.tests.test_retained_applications import shared, app  # noqa: F401 (fixture)
    from project_gateway.tests.test_assistants import sessions, assistant  # noqa: F401 (fixture)
    from project_gateway.tests.test_agents import register
    from project_gateway.tests.test_team_grants import bound, PRODUCTION_KEY
    from project_gateway.tests.test_teams import ORG_TEAMS, GRANT_SENTENCE, AGENT_SENTENCE
    from project_gateway.tests.test_access_history_sources import native_statements
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential, auth, cli
from ophiolite.account import Account
from ophiolite.errors import PermissionRefused

ADMINS_READ = 'Only an administrator of this project can read its access history.'
OWNERS_READ = "Only organisation owners can read a person's access history."
NAMES = {'alice': 'Alice', 'bob': 'Bob', 'carol': 'Carol', 'eve': 'Eve'}
P = {'id': 'p', 'name': 'Pilot'}


@pytest.fixture
def service(organizations_service):  # noqa: F811 (the HTTP worlds name test_organizations' fixture `service`)
    return organizations_service


def M(n):
    return '2026-10-01T09:%02d:00Z' % n


def E(n, kind, actor='alice', subject=None, project=True, role=None, frm=None, to=None, details=None, team=None, key=None):
    """One expected entry, every field literal (the rows are restamped to minute n in the order written)."""
    parts = {'actor': NAMES[actor]}
    if subject: parts['subject'] = NAMES[subject]
    if team: parts['team'] = team
    if project: parts['project'] = 'Pilot'
    if key: parts['key'] = key
    return {'id': 'ae:%d' % n, 'at': M(n), 'kind': kind, 'parts': parts,
            'actor': {'kind': 'person', 'id': actor, 'name_at_time': NAMES[actor]}, 'on_behalf_of': None, 'credential_kind': None,
            'through': None, 'subject': {'id': subject, 'name': NAMES[subject]} if subject else None, 'project': P if project else None,
            'from': frm, 'to': to, 'role': role, 'details': details or {}}


def session_post(p, person, path, body):
    r = p.c.post(path, json=body, headers=p.session(person))
    p.c.cookies.clear()
    assert r.status_code == 200, (path, r.text)
    return r.json()


def restamp(p):
    """Every access record at a fixed minute, in the order written (as the Platform's literal-list test does)."""
    with p.service.connect() as db:
        for n, row in enumerate(db.execute('SELECT id FROM ab_access_events ORDER BY id').fetchall(), 1):
            db.execute("UPDATE ab_access_events SET at=%s::timestamptz WHERE id=%s", (M(n), row['id']))
        db.execute("UPDATE ab_org_audit SET recorded_at='2026-10-01T08:00:00Z'::timestamptz + sequence * interval '1 minute'")  # before step 1


@pytest.fixture
def oracle(p):
    """Steps 1-8 of the literal list, by browser sessions through the gateway; then Alice's own key (row 11)."""
    p.sql(ORG_TEAMS); p.sql(PRODUCTION_KEY)
    p.sql("UPDATE ab_projects SET name='Pilot' WHERE id='p'")
    p.sql("INSERT INTO ab_users(id,name) VALUES('eve','Eve') ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name")
    p.sql("INSERT INTO ab_org_members VALUES('o','eve','member') ON CONFLICT DO NOTHING")
    with p.service.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM ab_access_events').fetchone()['n'] == 0  # the numbering below starts at 1
    team = session_post(p, 'alice', '/api/v1/organizations/team-create', {'organization_id': 'o', 'name': 'Geology'})['id']       # 1
    for person in ('bob', 'eve'):                                                                                                 # 2
        session_post(p, 'alice', '/api/v1/organizations/team-member', {'organization_id': 'o', 'team_id': team, 'user_id': person, 'present': True})
    for role in ('viewer', 'member'):                                                                                             # 3, 4
        session_post(p, 'alice', '/api/v1/projects/p/access/team-grant', {'project_id': 'p', 'team_id': team, 'role': role, 'can_compute': False})
    member = next(s for s in native_statements() if "'project-member'" in s)                                                      # 5
    with p.service.connect() as db:
        db.execute("INSERT INTO ab_members(project_id,user_id,role,can_compute) VALUES('p','carol','member',true)")
        db.execute(member, ('alice', 'p', 'carol', False, 'member', True, False))
    for day in ('2026-12-31', '2027-03-31'):                                                                                      # 5, 6
        session_post(p, 'alice', '/api/v1/projects/p/access/end-date', {'project_id': 'p', 'user_id': 'carol', 'ends_on': day})
    session_post(p, 'bob', '/api/v1/access-keys/create', {'project_id': 'p', 'label': 'Nightly', 'scope': 'read', 'days': 30})  # 7
    session_post(p, 'alice', '/api/v1/organizations/team-member', {'organization_id': 'o', 'team_id': team, 'user_id': 'bob', 'present': False})  # 8
    p.reader = session_post(p, 'alice', '/api/v1/access-keys/create', {'project_id': 'p', 'label': 'Reader', 'scope': 'read', 'days': 30})['key']
    restamp(p)
    p.team = team
    return p


def expected_p(team):
    users = [{'id': 'bob', 'name': 'Bob'}, {'id': 'eve', 'name': 'Eve'}]
    return [
        E(11, 'key_created', subject='alice', key='Reader', details={'label': 'Reader'}),
        E(10, 'team_member_removed', subject='bob', project=False, team='Geology', details={'team_id': team, 'projects': [P], 'project_count': 1}),
        E(9, 'key_created', actor='bob', subject='bob', key='Nightly', details={'label': 'Nightly'}),
        E(8, 'access_end_changed', subject='carol', frm='2027-01-01T00:00:00Z', to='2027-04-01T00:00:00Z'),
        E(7, 'access_end_set', subject='carol', to='2027-01-01T00:00:00Z'),
        E(6, 'grant_set', subject='carol', role='member', details={'can_compute': True}),
        E(5, 'team_grant_set', role='member', frm='viewer', to='member', team='Geology', details={'team_id': team, 'can_compute': False, 'users': users}),
        E(4, 'team_grant_set', role='viewer', to='viewer', team='Geology', details={'team_id': team, 'can_compute': False, 'users': users}),
    ]


def keyed(p, key):
    return Client(ORIGIN, 'p', Credential.bearer(key), p.c)


def account(c, key):
    return Account(ORIGIN, Credential.bearer(key), c)


# --- the readers, with real keys ------------------------------------------------------------------------------------

def test_an_administrators_key_reads_the_literal_project_history_on_every_page_with_its_filters(oracle):
    client = keyed(oracle, oracle.reader)
    expected = expected_p(oracle.team)
    assert client.access_history() == expected
    assert client.access_history(limit=1) == expected  # eight pages, each followed by its cursor
    assert client.access_history(kinds=['access_end_set', 'access_end_changed']) == [expected[3], expected[4]]
    assert client.access_history(since=M(7), until=M(10)) == [expected[2], expected[3], expected[4]]
    assert client.access_history(person='carol', limit=1) == [expected[3], expected[4], expected[5]]


def test_the_owners_key_reads_bobs_person_history_rows_2_3_4_7_8(oracle):
    """Rows 2, 3, 4, 7 and 8, and the world's own earlier organisation row: Alice made Bob an owner of o
    (`test_access_foundations.access`, organisation audit row 2)."""
    by_id = {e['id']: e for e in expected_p(oracle.team)}
    added = E(2, 'team_member_added', subject='bob', project=False, team='Geology', details={'team_id': oracle.team, 'projects': [], 'project_count': 0})
    owner_row = {**E(0, 'role_changed', subject='bob', project=False, role='owner'), 'id': 'oa:2', 'at': '2026-10-01T08:02:00Z'}
    with account(oracle.c, oracle.reader) as owner:
        bob = owner.person_history('o', 'bob')
        assert bob == [by_id['ae:10'], by_id['ae:9'], by_id['ae:5'], by_id['ae:4'], added, owner_row]
        assert owner.person_history('o', 'bob', limit=1) == bob
        assert owner.person_history('o', 'bob', kinds=['key_created'], since=M(9)) == [by_id['ae:9']]


def test_teams_by_the_owners_key_and_the_projects_teams_by_the_administrators_key(oracle):
    with account(oracle.c, oracle.reader) as owner:
        teams = owner.teams('o')
        assert {'id': oracle.team, 'name': 'Geology', 'members': 1, 'projects': 1, 'adoptable': False} in teams
        detail = owner.team('o', oracle.team)
        assert (detail['name'], detail['members']) == ('Geology', [{'user_id': 'eve', 'name': 'Eve'}])
    listed = keyed(oracle, oracle.reader).access_teams()
    assert {'id': oracle.team, 'name': 'Geology', 'role': 'member', 'can_compute': False, 'stranded': False} in listed


def test_export_writes_the_gateways_bytes_and_no_credential(oracle, tmp_path):
    client = keyed(oracle, oracle.reader)
    for fmt in ('csv', 'jsonl'):
        written = client.export_access_history(fmt, tmp_path / ('history.' + fmt))
        oracle.c.cookies.clear()
        direct = oracle.c.post('/api/v1/projects/p/access/history', json={'project_id': 'p', 'format': fmt},
                               headers={'Authorization': 'Bearer ' + oracle.reader})
        assert direct.status_code == 200 and written.read_bytes() == direct.content
        assert oracle.reader not in written.read_text()
    assert [json.loads(line) for line in (tmp_path / 'history.jsonl').read_text().splitlines()] == expected_p(oracle.team)
    with account(oracle.c, oracle.reader) as owner:
        out = owner.export_person_history('o', 'bob', 'csv', tmp_path / 'bob.csv')
    direct = oracle.c.post('/api/v1/organizations/person-history', json={'organization_id': 'o', 'user_id': 'bob', 'format': 'csv'},
                           headers={'Authorization': 'Bearer ' + oracle.reader})
    assert out.read_bytes() == direct.content and out.read_text().count('\n') == 7  # the header and Bob's six rows


# --- credentials through the real resolver -------------------------------------------------------------------------

def refused(call):
    with pytest.raises(PermissionRefused) as caught: call()
    return caught.value.code, caught.value.message


def test_a_viewers_key_a_service_accounts_key_and_a_non_owners_key_are_refused_with_the_gateways_words(oracle):
    vic = oracle.key('vic', 'read')
    machine = account_key(oracle, made(oracle, name='Nightly import', scope='write')['id'], 'write')['key']
    for key in (vic, machine):
        assert refused(lambda: keyed(oracle, key).access_history()) == ('PERMISSION_DENIED', ADMINS_READ)
    with account(oracle.c, vic) as other:
        assert refused(lambda: other.person_history('o', 'bob')) == ('PERMISSION_DENIED', OWNERS_READ)


def both(c, credential):
    """The project read and the person read with one credential."""
    return [refused(lambda: Client(ORIGIN, 'p', credential, c).access_history()),
            refused(lambda: Account(ORIGIN, credential, c).person_history('o', 'alice'))]


def test_a_saved_sign_ins_application_grant_is_refused_in_the_resolver(web, service):
    bound(service)
    grant = Credential.bearer('provider-alice', grant=web.grants['alice'])  # what a saved sign-in sends: bearer plus the grant
    assert both(web.c, grant) == [('HISTORY_GRANT_REFUSED', GRANT_SENTENCE)] * 2


def test_a_capability_2_grant_is_refused_by_the_gate(sessions, service):
    bound(service); assistant(sessions)
    assert both(sessions.c, Credential.bearer('provider-alice@a')) == [('HISTORY_GRANT_REFUSED', GRANT_SENTENCE)] * 2


def test_every_agent_token_is_refused_with_the_agent_code(web, service):
    """Row 14: an administrator's agent and the agent of a person who administers nothing get the same refusal."""
    bound(service)
    with service.connect() as db:
        assert db.execute("SELECT count(*) AS n FROM ab_project_administrators WHERE user_id='bob'").fetchone()['n'] == 0
    for person in ('alice', 'bob'):
        agent = Credential.bearer(register(web, person)['credential'])
        assert both(web.c, agent) == [('HISTORY_AGENT_REFUSED', AGENT_SENTENCE)] * 2, person


# --- the command line ------------------------------------------------------------------------------------------------

def test_the_access_history_and_teams_commands(oracle, tmp_path, monkeypatch, capsys):
    folder = tmp_path / 'private'; folder.mkdir(mode=0o700)
    credential = folder / 'sdk.json'
    auth.key_login(ORIGIN, 'p', oracle.reader, path=credential, label='Reader', scope='read')
    config = tmp_path / 'configuration.json'
    config.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': ORIGIN, 'project': 'p'}))
    for target in ('ophiolite.client.httpx.Client', 'ophiolite.account.httpx.Client'):
        monkeypatch.setattr(target, lambda **k: oracle.c)
    monkeypatch.setattr(oracle.c, 'close', lambda: None)  # the fixture owns the client
    common = ['--configuration', str(config), '--credentials', str(credential)]
    expected = keyed(oracle, oracle.reader).access_history()
    cli.main(['access-history', '--project', '--json', *common])
    assert json.loads(capsys.readouterr().out) == {'entries': expected}
    cli.main(['access-history', '--person', 'bob', '--organization', 'o', '--kind', 'key_created', '--json', *common])
    assert [e['id'] for e in json.loads(capsys.readouterr().out)['entries']] == ['ae:9']
    out = tmp_path / 'history.csv'
    cli.main(['access-history', '--project', '--export', 'csv', '--out', str(out), *common])
    printed = capsys.readouterr()
    oracle.c.cookies.clear()
    direct = oracle.c.post('/api/v1/projects/p/access/history', json={'project_id': 'p', 'format': 'csv'}, headers={'Authorization': 'Bearer ' + oracle.reader})
    assert out.read_bytes() == direct.content
    assert oracle.reader not in printed.out + printed.err and str(out) in printed.out
    cli.main(['access-history', '--project', *common])
    words = capsys.readouterr().out.splitlines()
    assert len(words) == 8 and words[0].startswith(M(11)) and 'key_created' in words[0]
    cli.main(['teams', '--organization', 'o', '--json', *common])
    assert oracle.team in [t['id'] for t in json.loads(capsys.readouterr().out)['teams']]
    cli.main(['teams', '--json', *common])
    assert oracle.team in [t['id'] for t in json.loads(capsys.readouterr().out)['teams']]
