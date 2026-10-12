"""E67a C6, gateway lane: `Account.projects()` and `ophiolite projects` against the real discovery route of an in-process
gateway on the organisation schema with the end-date migration, signed in with access keys made the way a person makes
them (a bearer that is not a key, a grant or a workload is not a discovery credential here). Bob's direct grant on p ends
(the stored instant comes back byte for byte), Vic's grant has no end (explicit None), and a project whose grant has
ended is not listed: its key discovers nothing and is refused with the sentence that says the access ended."""
import json
import os

import pytest
try:
    from project_gateway.tests.real_credentials import ORIGIN, project  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Credential, cli
from ophiolite.account import Account
from ophiolite.errors import PermissionRefused

ENDED, LIVE = '2000-01-01T00:00:00Z', '2999-01-01T00:00:00Z'


def end(p, person, at, project='p'):
    p.sql('UPDATE ab_members SET expires_at=%s WHERE project_id=%s AND user_id=%s', at, project, person)


def listed(p, key):
    with Account(ORIGIN, Credential.bearer(key), p.c) as account:
        return [(row['id'], row['access_ends_at']) for row in account.projects()]


def test_discovery_carries_when_access_ends_and_leaves_out_access_that_ended(project):
    project.sql("INSERT INTO ab_members(project_id,user_id,role,can_compute) VALUES('q','bob','member',true)")
    bob, vic, later = project.key('bob'), project.key('vic', scope='read'), project.key('bob', project='q')
    end(project, 'bob', LIVE); end(project, 'bob', ENDED, project='q')
    assert listed(project, bob) == [('p', LIVE)]  # Bob: the stored end, byte for byte
    assert listed(project, vic) == [('p', None)]  # Vic: undated, the key is there with None
    with pytest.raises(PermissionRefused) as refused: listed(project, later)  # q ended: never listed with a past date
    assert 'ended after 31 December 1999' in str(refused.value.server_message or refused.value), refused.value


def test_the_projects_command_prints_the_last_day_and_json_carries_the_instant(project, monkeypatch, capsys):
    key = project.key('bob'); end(project, 'bob', LIVE)
    monkeypatch.setattr('ophiolite.account.httpx.Client', lambda **k: project.c)
    monkeypatch.setattr(project.c, 'close', lambda: None)  # the fixture owns the client
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY', key)
    cli.main(['projects', '--url', ORIGIN])
    assert capsys.readouterr().out.splitlines() == ['Unnamed project - can edit, ends 31 Dec 2998']
    cli.main(['projects', '--url', ORIGIN, '--json'])
    assert [(r['id'], r['access_ends_at']) for r in json.loads(capsys.readouterr().out)['projects']] == [('p', LIVE)]
