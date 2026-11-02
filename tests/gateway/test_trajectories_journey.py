"""E134 s1 C4 (B5), gateway lane: `ophiolite trajectories export` as an external client, a separate process over HTTP
to an in-process gateway that captures by consent. E133's approved test text is injected (R2-14; the deployment
default stays a draft); Alice allows training through the consent route; she runs `ophiolite.shale-volume` twice, four
hours apart, with typed picks 35 and 150 gAPI; the export writes a folder `load` accepts with two episodes whose
shale-volume rows carry the two literal parameters, and no asset, project or person id of the fixture appears in its
bytes (a revision is its content's digest, which the folder carries as `sha256` by design). Synthetic rows only (B4);
the destination is under tmp_path."""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from project_gateway import record
    from project_gateway.tests.test_capture_startup import BY_CONSENT, world, post  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_consent_service import TEST_TEXTS
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
    from project_gateway.tests.test_retained_applications import shared, app  # noqa: F401 (fixtures)
    from project_gateway.tests.test_one_api_matrix import Caller
    from project_gateway.tests.test_calculations import las, publish
    from project_gateway.tests.test_publications import uploaded
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import trajectories
from ophiolite.testing import fixture_server

HOURS = timedelta(hours=4, seconds=1)
LINE = 'Exported %d episodes of your own work to %s (%d with values).'
SECRET, NAME = 'vps-reserve-TEST', 'Alice'  # s2: planted in verdict reasons; the values scans drop both (a secret; a member's name)


class Clock(datetime):
    """record.py's clock: the real instant plus a shift the test moves."""
    shift = timedelta(0)
    @classmethod
    def now(cls, tz=None): return datetime.now(tz) + cls.shift


def native_keys(a, service):
    """test_access_key_chain's `keyed`, before the gateway is made: the access-key tables, and a native key resolved the
    way native authentication does (the credential row by hash, unrevoked, unexpired, enabled person)."""
    from project_gateway import access_keys
    migrations = Path(access_keys.__file__).resolve().parents[2] / 'tools/migrations'
    with service.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS ab_project_access_blocks(project_id text NOT NULL REFERENCES ab_projects(id),
            user_id text NOT NULL REFERENCES ab_users(id), actor text NOT NULL REFERENCES ab_users(id), created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(project_id,user_id))''')
        db.execute((migrations / '20260929-access-keys.sql').read_text())

    def owner(token):
        if not token.startswith('oph_native_key_'): return token
        with service.connect() as db:
            row = db.execute('''SELECT c.user_id FROM ab_credentials c JOIN ab_users u ON u.id=c.user_id
                WHERE c.token_hash=%s AND NOT c.revoked AND c.expires_at>now() AND u.enabled''', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row: raise PermissionError('native authentication failed')
        return row['user_id']
    account, platform = service.account, a.sources.platform
    service.account = lambda token: account(owner(token))
    a.sources.platform = lambda method, body, token: platform(method, body, owner(token))


@pytest.fixture
def journey(world, shared, service, tmp_path, monkeypatch, request):
    """test_capture_startup's by-consent public demonstration (no identity provider, bob disabled), E133's approved test
    text injected; alice allows training through the consent route and makes an access key the way a person does.
    Parametrized `off`: the same gateway with capture off (no consent to give)."""
    native_keys(shared[0], service)
    off = getattr(request, 'param', None) == 'off'
    w = world(**({} if off else BY_CONSENT))
    w.app.state.consent.texts = TEST_TEXTS
    monkeypatch.setattr(record, 'datetime', Clock)
    monkeypatch.setattr(Clock, 'shift', timedelta(0))
    with w.client() as c:
        if not off:
            granted = post(w, c, '/api/v1/consent/grant', {'purpose': 'training', 'text_version': 1, 'extras': [], 'command_id': 'g-1'})
            assert granted.status_code == 200, granted.text
        made = post(w, c, '/api/v1/access-keys/create', {'project_id': 'p', 'label': 'Trajectories', 'scope': 'read', 'days': 30})
        assert made.status_code == 200, made.text
        writing = post(w, c, '/api/v1/access-keys/create', {'project_id': 'p', 'label': 'Self-grants', 'scope': 'write', 'days': 30})
        assert writing.status_code == 200, writing.text
        c.cookies.clear()
        w.c, w.bodies, w.grants = c, [], {}
        pages = SimpleNamespace(limit=None, between=None, seen=0, bodies=[])  # s2: a smaller page, and a change between pages; s3: the bodies sent

        def handler(method, path, raw, headers):
            headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
            paging = path.endswith('/activity/trajectories')
            if paging: pages.bodies.append(json.loads(raw))
            if paging and pages.limit: raw = json.dumps({**json.loads(raw), 'limit': pages.limit}).encode()
            response = c.request(method, path, content=raw, headers=headers)
            if paging:
                pages.seen += 1
                if pages.seen == 1 and pages.between: pages.between()
            return response.status_code, response.content

        with fixture_server(handler) as server:
            for project in ('other', 'p'):
                (tmp_path / ('configuration-%s.json' % project)).write_text(json.dumps({'schema': 'ophiolite.read-configuration/1', 'url': server.url, 'project': project}))

            def cli(token, *argv, project='other'):  # the export names its project by --scope; the self-grant by the configuration
                env = {**os.environ, 'OPHIOLITE_ACCESS_KEY': token}
                done = subprocess.run([sys.executable, '-m', 'ophiolite.cli', *argv, '--configuration', str(tmp_path / ('configuration-%s.json' % project)),
                                       '--credentials', str(tmp_path / 'not-saved.json')], capture_output=True, text=True, timeout=120, env=env,
                                      cwd=tmp_path)  # outside the source tree: the installed package answers
                return done.returncode, done.stdout.strip(), done.stderr.strip()

            def call(token, *argv): return cli(token, 'trajectories', 'export', *argv)
            call.w, call.key, call.cli, call.writer, call.pages, call.service = w, made.json()['key'], cli, writing.json()['key'], pages, service
            yield call


def made(w):
    """Alice's source and two shale-volume runs four hours apart (typed picks 35 and 150 gAPI): their receipts."""
    alice = Caller(w, 'session', 'alice')
    parent = uploaded(w, who='alice', audience=(), reuse=(), command='src', raw=las([(100, 20), (101, 90), (102, 160)]))
    picks = {'how': 'typed', 'clean': 35, 'shale': 150}
    first = publish(alice, parent, 'vsh-1', picks=picks)
    Clock.shift = HOURS
    second = publish(alice, parent, 'vsh-2', picks=picks, name='Shale volume again')
    return parent, first, second


def twice(w):
    """`made`, as the ids the folder must not hold."""
    return [r['asset_id'] for r in made(w)]  # a revision is its content digest: the folder's `sha256`


ARGS = ['--scope', 'project:p', '--purpose', 'training', '--mode', 'shape']


def test_b_alice_exports_her_two_runs_as_two_episodes_that_name_nothing(journey, tmp_path):
    """Mutations (logs/c4-journey-mutations.txt): the manifest given the raw project -> the scan finds it -> red; a ref
    given the literal asset_id -> the server's folder check refuses first -> red; typed picks not kept -> red."""
    ids = twice(journey.w)
    out = tmp_path / 'exports' / 'out'
    out.parent.mkdir()
    assert journey(journey.key, *ARGS, '--destination', str(out)) == (0, LINE % (2, out, 0), '')
    manifest, episodes = trajectories.load(out)
    assert (manifest.mode, manifest.capture, manifest.purpose, manifest.counts.episodes, len(episodes)) == ('shape', 'by-consent', 'training', 2, 2)
    runs = [[(p.key, p.value, p.unit) for p in r.parameters] for e in episodes for r in e.rows if r.operation == 'calculations/shale-volume']
    assert runs == [[('picks.clean', 35.0, 'gAPI'), ('picks.shale', 150.0, 'gAPI')]] * 2
    assert episodes[1].start - episodes[0].end >= 4 * 3600
    folder = b''.join(p.read_bytes() for p in sorted(out.iterdir()))
    assert [i for i in ids + ['alice', '"p"', 'tops'] if i.encode() in folder] == []
    assert sorted(p.name for p in out.parent.iterdir()) == ['out']


def test_c_an_existing_destination_and_a_refusal_write_nothing(journey, tmp_path):
    """The destination is refused before any call; a permission refusal (an outsider's project) exits 3 and leaves no
    folder. Mutation: the staging folder kept on a refusal -> a hidden sibling is left -> red."""
    here = tmp_path / 'exports'
    (here / 'there').mkdir(parents=True)
    made = journey.key
    assert journey(made, *ARGS, '--destination', str(here / 'there')) == (1, '', 'The destination exists; name a new folder.')
    code, out, err = journey(made, '--scope', 'project:nowhere', *ARGS[2:], '--destination', str(here / 'never'))
    assert (code, out) == (3, ''), (code, out, err)
    assert sorted(p.name for p in here.iterdir()) == ['there']


@pytest.mark.parametrize('journey', ['off'], indirect=True)
def test_c_with_capture_off_the_export_is_refused_and_writes_nothing(journey, tmp_path):
    """The server's refusal (capture-off) maps to its exit code and leaves no folder. Mutation: the staging folder kept
    on a refusal -> a hidden sibling is left -> red."""
    here = tmp_path / 'exports'
    here.mkdir()
    code, out, err = journey(journey.key, *ARGS, '--destination', str(here / 'out'))
    assert (code, out, sorted(p.name for p in here.iterdir())) == (4, '', []), (code, out, err)


# --- d, e: E134 s2 values (R1-2, R1-3, R1-14, R2-5) --------------------------------------------------------------------------

def granted(journey, receipt, *more):
    return journey.cli(journey.writer, 'ai-use', 'self-grant', receipt['asset_id'], '--purpose', 'training', *more, project='p')


def planted(journey):
    """`made`, alice's verdicts on both results with a secret and a member's name in the reasons, and her self-grants for
    training on the upload and both results through the CLI (a write key of hers)."""
    parent, first, second = made(journey.w)
    alice = Caller(journey.w, 'session', 'alice')
    for target, command, reason in ((first, 'v-1', 'The header held ' + SECRET), (second, 'v-2', NAME + ' moved the shale pick')):
        alice.ok('verdicts', 'record', {'asset_id': target['asset_id'], 'revision': target['revision'], 'verdict': 'rejected', 'reason': reason,
                                        'command_id': command})
    for receipt in (parent, first, second):
        assert granted(journey, receipt) == (0, 'Your own AI use of %s for training is granted (number 1).' % receipt['asset_id'], '')
    return parent, first, second


def test_d_alice_self_grants_and_exports_values_without_the_planted_text(journey, tmp_path):
    """No `--mode` is auto (R1-3); two pages (limit 1) under one boundary. Both episodes are values, the reasons that hold
    the secret and the name are dropped and counted, and neither literal is in the folder's bytes. Withdrawing the first
    result's self-grant (forward only) makes its episode shape in the next export (R1-2: per item).
    Mutations (logs/c7-mutations.txt): the CLI default left at shape -> red; the names not given to the scans -> red."""
    parent, first, second = planted(journey)
    journey.pages.limit = 1
    out = tmp_path / 'exports' / 'out'
    out.parent.mkdir()
    assert journey(journey.key, '--scope', 'project:p', '--purpose', 'training', '--destination', str(out)) == (0, LINE % (2, out, 2), '')
    manifest, episodes = trajectories.load(out)
    assert (manifest.mode, manifest.counts.values, manifest.counts.shape, manifest.counts.scrubbed_fields, [e.mode for e in episodes]) == (
        'auto', 2, 0, 2, ['values', 'values'])
    runs = [[o.asset_id for o in r.outputs] for e in episodes for r in e.rows if r.operation == 'calculations/shale-volume']
    assert (runs, journey.pages.seen) == ([[first['asset_id']], [second['asset_id']]], 2)
    folder = b''.join(p.read_bytes() for p in sorted(out.iterdir()))
    assert [i for i in (SECRET, NAME) if i.encode() in folder] == []
    assert granted(journey, first, '--withdraw') == (0, 'Your own AI use of %s for training is withdrawn (number 2).' % first['asset_id'], '')
    again = tmp_path / 'exports' / 'again'
    assert journey(journey.key, '--scope', 'project:p', '--purpose', 'training', '--destination', str(again)) == (0, LINE % (2, again, 1), '')
    assert [e.mode for e in trajectories.load(again)[1]] == ['shape', 'values']


def test_e_a_member_renamed_between_pages_aborts_and_leaves_nothing(journey, tmp_path):
    """R2-5, R1-14: only `ab_users.name` changes between the two pages; the names set is in the reconstruction digest, so
    the SDK refuses the continuation (exit 4) and removes its staging folder. Mutation: the names left out of the
    reconstruction -> the export completes -> red. The control is test_d: the same two pages with no rename succeed."""
    planted(journey)
    journey.pages.limit = 1

    def rename():
        with journey.service.connect() as db: db.execute("UPDATE ab_users SET name='Alice Example' WHERE id='alice'")
    journey.pages.between = rename
    here = tmp_path / 'exports'
    here.mkdir()
    code, out, err = journey(journey.key, '--scope', 'project:p', '--purpose', 'training', '--destination', str(here / 'out'))
    assert (code, out, err, sorted(p.name for p in here.iterdir()), journey.pages.seen) == (
        4, '', 'The record changed while exporting; export again.', [], 2)


# --- s3: an export repeats under its until (D2), withdrawals (D3), until=0 (R2-9) --------------------------------------------

def rows_after(w, seq):
    """The operations of the record's rows above `seq`, in order."""
    journal = w.app.state.attempts.journal
    return [(json.loads(b)['kind'], json.loads(b)['data'].get('operation')) for (b,) in journal.db.execute('SELECT body FROM activity_events WHERE seq>? ORDER BY seq', (seq,)).fetchall()]


def highest(w): return w.app.state.attempts.journal.db.execute('SELECT coalesce(max(seq),0) FROM activity_events').fetchone()[0]


def export_to(journey, out, *more):
    out.parent.mkdir(exist_ok=True)
    code, line, err = journey(journey.key, '--scope', 'project:p', '--purpose', 'training', '--destination', str(out), *more)
    assert code == 0, (code, line, err)
    return json.loads((out / 'trajectories.json').read_text())


def same_but(a, b):
    """The keys whose values differ between two manifests."""
    return {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}


def test_s3_j_the_same_until_gives_the_same_folder(journey, tmp_path):
    """D2 (R1-11, R1-12, R2-4): nothing is written between the exports but their own rows; the repeat under the first
    manifest's `until` has the same manifest bytes but `exported_at`, the same episodes.jsonl and, in this one pyarrow
    environment, the same episodes.parquet. A third export without `--until` has the same lines; its manifest differs in
    exactly `until` and `exported_at`. Mutation: the SDK drops `--until` -> the second manifest's `until` moves -> red."""
    import re
    planted(journey)
    here = tmp_path / 'exports'
    first = export_to(journey, here / 'one')
    before = highest(journey.w)
    second = export_to(journey, here / 'two', '--until', str(first['until']))
    third = export_to(journey, here / 'three')
    assert rows_after(journey.w, before) == [('action', 'activity/trajectories')] * 2  # the exports' own rows only (D3 of s1: never exported)
    stamp = lambda out: re.sub(rb'"exported_at":[^,}]+', b'"exported_at":0', (out / 'trajectories.json').read_bytes())
    assert stamp(here / 'one') == stamp(here / 'two') and same_but(first, second) <= {'exported_at'}
    for name in ('episodes.jsonl', 'episodes.parquet'):
        assert (here / 'one' / name).read_bytes() == (here / 'two' / name).read_bytes(), name
    assert (here / 'three' / 'episodes.jsonl').read_bytes() == (here / 'one' / 'episodes.jsonl').read_bytes()
    assert (same_but(first, third), first['counts']['values']) == ({'until', 'exported_at'}, 2)


def test_s3_k_a_self_grant_withdrawal_lowers_exactly_its_episode(journey, tmp_path):
    """D3 (R1-3): the first result's self-grant withdrawn between two exports under one `until`: exactly episode 1 (literal)
    goes from values to shape; the manifests differ in exactly `counts` and `exported_at` (stop rule 5)."""
    parent, first, second = planted(journey)
    here = tmp_path / 'exports'
    a = export_to(journey, here / 'a')
    assert granted(journey, first, '--withdraw')[0] == 0
    b = export_to(journey, here / 'b', '--until', str(a['until']))
    modes = lambda out: [e.mode for e in trajectories.load(out)[1]]
    assert (modes(here / 'a'), modes(here / 'b')) == (['values', 'values'], ['shape', 'values'])
    assert same_but(a, b) == {'counts', 'exported_at'}
    assert (a['counts']['values'], b['counts']['values'], b['counts']['shape']) == (2, 1, 1)


# after the withdrawal: the third run's derived asset (no record: `skipped`) and its action (no consent); the exports'
# own rows are never exported (s1 D3)
AFTER_WITHDRAWAL, NO_CONSENT = [('asset.derived', None), ('action', 'calculations/shale-volume')], 1


def test_s3_l_a_consent_withdrawal_is_forward_only(journey, tmp_path, monkeypatch):
    """D3: E133's withdrawal, then one more run. Under the first `until` the folder is the same but `exported_at`; a fresh
    export has the same episodes and counts the rows after the withdrawal (listed here by hand) in `no_consent`. The
    record's clock runs `HOURS` ahead in this fixture (`Clock`), so the withdrawal is placed on the same timeline: after
    the second run's instant (the first export's cutoff), before the third run's."""
    import time
    from project_gateway import consent_service
    parent, _, _ = made(journey.w)
    here = tmp_path / 'exports'
    a = export_to(journey, here / 'a')
    w = journey.w
    monkeypatch.setattr(consent_service, 'now', lambda: time.time() + HOURS.total_seconds() + 60)
    withdrawn = post(w, w.c, '/api/v1/consent/withdraw', {'purpose': 'training', 'command_id': 'w-1'})
    assert withdrawn.status_code == 200, withdrawn.text
    w.c.cookies.clear()
    mark = highest(w)
    Clock.shift = HOURS * 2
    alice = Caller(w, 'session', 'alice')
    publish(alice, parent, 'vsh-3', picks={'how': 'typed', 'clean': 35, 'shale': 150}, name='Shale volume a third time')
    after = rows_after(w, mark)
    b = export_to(journey, here / 'b', '--until', str(a['until']))
    c = export_to(journey, here / 'c')
    assert same_but(a, b) == {'exported_at'} and (here / 'a' / 'episodes.jsonl').read_bytes() == (here / 'b' / 'episodes.jsonl').read_bytes()
    assert (here / 'c' / 'episodes.jsonl').read_bytes() == (here / 'a' / 'episodes.jsonl').read_bytes()
    assert after == AFTER_WITHDRAWAL
    assert c['counts']['no_consent'] - a['counts']['no_consent'] == NO_CONSENT


def test_s3_q_until_zero_is_sent_and_exports_nothing(journey, tmp_path):
    """R2-9: `--until 0` reaches the first body as 0 and the folder is empty. M9: the SDK forwards `until` only when truthy
    -> the body lacks it and the export holds both runs -> red."""
    made(journey.w)
    found = export_to(journey, tmp_path / 'exports' / 'zero', '--until', '0')
    assert (journey.pages.bodies[0].get('until'), found['until'], found['counts']['episodes']) == (0, 0, 0)
    assert (tmp_path / 'exports' / 'zero' / 'episodes.jsonl').read_bytes() == b''
