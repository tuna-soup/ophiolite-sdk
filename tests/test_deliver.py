"""E109 slice 1 (S1.2, C3 first journey): `deliver` runs a send procedure of the project's catalogue once, on this
computer, on exact versions, and reports what it said; a pending attempt is never launched again.

Offline: the project is an in-memory stand-in (`Project`) with the catalogue calls, the inventory, the version history,
exact reads and `ophiolite.testing.MemoryDeliveries` for the delivery record (the server's rules). The writer is a real
send procedure run in its own child process; it writes into a folder named by its system configuration and counts each
call in a counter file at its entry, before anything else (M4). Strategy C3 tests 1, 2, 5, 6, 8, 9, 10, 13, 14 and 15
(record side; the server's own refusals are the gateway journey's, tests/gateway/test_deliver_journey.py), the scaffold
run (4-10), a zero-system send (R5-8) and the never-relaunched attempt (R5-1). `--wait` is always 0 (6-10).

Slice 2 (S2.1, C3 recovery, D8): an unknown outcome is recorded and never sent again; `reconcile`, run from the pinned
copy with the same configuration once the writer's process group has finished, says confirmed, not sent (only through
its tombstone) or unknown; `--set-aside`. Strategy C3 tests 3, 4, 7, 9 (with reconcile), 11 and 13 (reconcile after
withdrawal). The tombstone against a real PostgreSQL (tests 12 and 12a) is tests/gateway/test_deliver_tops.py."""
import fcntl
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import ophiolite
from ophiolite import cli, procedures
from ophiolite.errors import PermissionRefused, Unavailable
from ophiolite.exchange import ClientTransport, Exchange
from ophiolite.testing import MemoryDeliveries

PACKAGE = Path(ophiolite.__file__).resolve().parent
FIXTURES = PACKAGE / 'contracts/procedures/v1/fixtures'
V1, V2 = 'name,md\nNU,0\nNM,220\nNL,240\n', 'name,md\nNU,0\nNM,221.5\nNL,241\nNS,300\n'
REV1, REV2 = '1' * 64, '2' * 64
DESTINATION = 'Team tops folder'
PLANTED = 'e109-planted-token-2c9d'
CODE = '''import os
from pathlib import Path

import ophiolite
from ophiolite import procedure


@procedure
def send(inputs, settings, delivery):
    counter = Path(os.environ['E109_COUNTER'])  # M4: counted at entry, before anything else
    counter.write_text(str(int(counter.read_text()) + 1 if counter.exists() else 1))
    mode = settings['mode']
    if mode == 'refuse': return ophiolite.refused('The team folder is closed today (%s).')
    if mode == 'malformed': return {'items': 3}
    if mode == 'boolean': return ophiolite.delivered(items=True)
    if mode == 'raise': raise RuntimeError('The connection was lost.')
    if mode == 'die': os._exit(9)
    target = Path(delivery.system.config['folder']) / delivery.id
    target.mkdir(parents=True)
    rows = 0
    for slot in sorted(k for k in inputs if k != 'dest'):
        for n, version in enumerate(inputs[slot]):
            text = Path(version.path).read_text()
            (target / ('%%s-%%d.csv' %% (slot, n))).write_text(text)
            rows += len(text.splitlines()) - 1
    if mode == 'commit_die': os._exit(9)  # killed after the destination holds the delivery
    return ophiolite.delivered(items=rows)
''' % PLANTED


def manifest(slots=('tops',), name='team/tops-folder', label='Tops to team folder', cardinality='one'):
    return {'schema': 'ophiolite.procedure/1', 'name': name, 'label': label, 'version': 1, 'step': 'send',
            'inputs': [{'slot': s, 'label': 'Tops to deliver' if s == 'tops' else 'Other tops', 'class': 'version', 'kinds': ['well-tops-csv/1'],
                        'cardinality': cardinality} for s in slots]
                      + [{'slot': 'dest', 'label': DESTINATION, 'class': 'system', 'config_keys': ['folder']}],
            'outputs': [{'role': 'delivery', 'label': 'Delivered tops', 'class': 'delivery'}],
            'settings': [{'key': 'mode', 'label': 'What the writer does', 'type': 'choice', 'default': 'deliver',
                          'choices': [{'value': v, 'label': v.replace('_', ' ')} for v in ('deliver', 'refuse', 'malformed', 'boolean', 'raise', 'die', 'commit_die')]},
                         {'key': 'note', 'label': 'A note', 'type': 'string', 'default': 'plain'}],
            'entry': 'procedure:send'}


# D8: what a later run asks the destination. The delivery's folder there is its commit; a `.withdrawn` file is the
# tombstone this reconcile writes before it says not delivered; absence alone is unknown (4-1). Counted at entry.
RECONCILE = '''

def reconcile(delivery):
    counter = Path(os.environ['E109_RECONCILED'])
    counter.write_text(str(int(counter.read_text()) + 1 if counter.exists() else 1))
    mode = os.environ.get('E109_RECONCILE', 'look')
    if mode == 'unknown': return ophiolite.unknown()
    if mode == 'malformed': return 'it is there'
    if mode == 'raise': raise RuntimeError('The team folder cannot be read.')
    target = Path(delivery.system.config['folder']) / delivery.id
    if target.is_dir(): return ophiolite.delivered(items=sum(len(p.read_text().splitlines()) - 1 for p in target.glob('*.csv')))
    if mode == 'tombstone':
        (target.parent / (delivery.id + '.withdrawn')).write_text('withdrawn')
        return ophiolite.not_delivered()
    return ophiolite.unknown()
'''


def folder_of(root, manifest_, code=CODE):
    folder = root / manifest_['name'].replace('/', '-')
    folder.mkdir(parents=True)
    (folder / 'procedure.json').write_text(json.dumps(manifest_, indent=2))
    (folder / 'procedure.py').write_text(code)
    assert procedures.validate(folder)['valid'], procedures.validate(folder)
    return folder


class Project(procedures.ProcedureClient):
    """Project p as `deliver` reads it: a catalogue, items with versions, and the delivery record."""
    project, url = 'p', 'https://ophiolite.test'

    def __init__(self, root):
        self.root, self.catalogue, self.items, self.reporter = root, {}, {}, 'anna-key'
        self.deliveries, self.posts, self.reads, self.unreadable, self.lose_response = MemoryDeliveries(), [], [], set(), 0
        self.add_item('tops-a', 'Tops', [(REV1, V1), (REV2, V2)])

    def add_item(self, asset, name, versions):
        self.items[asset] = {'name': name, 'versions': list(versions)}

    def register(self, folder, *, trusted=True, mine=False, state='enabled'):
        digest = procedures.digest(folder)
        m = procedures.manifest_of(folder)
        self.catalogue[digest] = {'digest': digest, 'name': m['name'], 'label': m['label'], 'version': m['version'], 'state': state, 'trusted': trusted,
                                  'mine': mine, 'withdrawn_at': 1760000000 if state == 'withdrawn' else None, 'added_by': 'Tina', 'added_at': 1760000000,
                                  'enabled_at': 1760000000, 'folder': folder}
        return digest

    # the catalogue
    def procedure_list(self, name=None):
        return [dict(v, state='enabled' if v['state'] == 'withdrawn' else v['state']) for v in self.catalogue.values() if name in (None, v['name'])]

    def procedure_get(self, digest):
        return self.catalogue[digest]

    def procedure_bundle(self, digest):
        return procedures.pack(self.catalogue[digest]['folder'])

    def procedure_trust(self, digest, *, command_id=None):
        self.catalogue[digest]['trusted'] = True

    # who reports, what can be read, and the record
    def _delivery_reporter(self):
        return {'kind': 'delegate', 'fingerprint': self.reporter}

    def sync(self):
        return SimpleNamespace(inventory=lambda: [{'asset_id': a, 'kind': 'uploaded', 'authority': 'project', 'name': i['name'], 'revision': i['versions'][-1][0]}
                                                  for a, i in self.items.items()])

    def read_data(self, asset, revision):
        self.reads.append((asset, revision))
        if (asset, revision) in self.unreadable: raise Unavailable('That version cannot be read.', status=404)
        raw = dict(self.items[asset]['versions'])[revision].encode()
        number = [r for r, _ in self.items[asset]['versions']].index(revision) + 1
        return SimpleNamespace(original=raw, _wire_data_bytes=b'{}', type='well-tops',
                               _wire_descriptor={'profile': 'well-tops-csv/1', 'scientific': {}, 'history': {'number': number}})

    def _post(self, area, operation, body, **options):
        if (area, operation) == ('applications', 'result-history'):
            versions = self.items[body['asset_id']]['versions']
            return {'revisions': [{'number': n, 'revision': r, 'by': 'anna', 'published_at': None} for n, (r, _) in enumerate(versions, 1)], 'display': {}}
        if (area, operation) == ('activity', 'deliver'):
            self.posts.append(json.loads(json.dumps(body)))
            answer = self.deliveries.report(body, self.reporter)
            if self.lose_response:
                self.lose_response -= 1
                raise Unavailable('The project did not answer.', status=503)
            return answer
        raise AssertionError((area, operation))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    monkeypatch.setenv('E109_COUNTER', str(tmp_path / 'count'))
    monkeypatch.setenv('E109_RECONCILED', str(tmp_path / 'reconciled'))
    monkeypatch.chdir(tmp_path)
    w = Project(tmp_path)
    w.folder = folder_of(tmp_path / 'procedures', manifest())
    w.digest = w.register(w.folder)
    w.dest = tmp_path / 'team-folder'
    w.dest.mkdir()
    w.config = tmp_path / 'dest.json'
    w.config.write_text(json.dumps({'folder': str(w.dest)}))
    w.work = tmp_path / '.ophiolite-held'
    return w


def deliver(w, items=('tops=Tops@1',), settings=(), name='team/tops-folder', **kw):
    return w.deliver(name, systems=kw.pop('systems', {'dest': str(w.config)}), items=list(items), settings=list(settings), work=w.work, wait=0, **kw)


def count(w):
    path = w.root / 'count'
    return int(path.read_text()) if path.exists() else 0


def attempts(w):
    return sorted((w.work / 'deliveries').glob('*/attempt.json')) if (w.work / 'deliveries').exists() else []


def attempt_of(answer):
    return json.loads((Path(answer['folder']) / 'attempt.json').read_text())


def delivered_files(w):
    return {str(p.relative_to(w.dest)): p.read_text() for p in sorted(w.dest.rglob('*.csv'))}


def nothing_launched(w):
    assert attempts(w) == [] and count(w) == 0 and w.posts == [] and w.deliveries.events == []


# ---------------------------------------------------------------- 1. exact version; the held record untouched (M3)

def test_held_v2_delivers_v1_and_the_held_record_is_byte_identical(world):
    w = world
    held = Exchange(ClientTransport(w), w.work)
    held.get('tops-a', output=w.root / 'got')  # this folder holds v2, the head
    before = (w.work / 'held.json').read_bytes()
    answer = deliver(w, ['tops=Tops@1'])
    assert answer['state'] == 'confirmed' and answer['reported'] and answer['items'] == 3
    assert answer['sentence'] == f'Sent to {DESTINATION} by Tops to team DB on this computer: 3 items. Recorded in the project.'.replace('Tops to team DB', 'Tops to team folder')
    assert (w.work / 'held.json').read_bytes() == before
    assert delivered_files(w) == {f"{answer['delivery_id']}/tops-0.csv": V1}  # v1's literals, not the head's
    assert w.posts[0]['refs'] == [{'project_id': 'p', 'asset_id': 'tops-a', 'revision': REV1}] and count(w) == 1
    assert w.posts[0]['destination'] == DESTINATION and w.posts[0]['procedure'] == {'digest': w.digest, 'label': 'Tops to team folder', 'version': 1}


def test_without_a_number_the_head_when_chosen_is_delivered(world):
    w = world
    answer = deliver(w, ['Tops'])  # bare: the procedure has one version slot
    assert delivered_files(w) == {f"{answer['delivery_id']}/tops-0.csv": V2} and w.posts[0]['refs'][0]['revision'] == REV2


# ---------------------------------------------------------------- 2, 13. every refusal before launch leaves nothing (D12 i, M5, 2-3)

def untrusted(w): w.catalogue[w.digest]['trusted'] = False
def withdrawn(w): w.catalogue[w.digest].update(state='withdrawn')
def tampered(w): w.procedure_bundle = lambda digest: procedures.pack(folder_of(w.root / 'other', manifest(), CODE + '\n# changed\n'))
def unreadable(w): w.unreadable.add(('tops-a', REV1))
def windows(w): procedures._windows = lambda: True
def not_a_send(w):
    m = dict(manifest(name='team/tops-copy'), step='process', outputs=[{'role': 'tops', 'label': 'Tops', 'class': 'version', 'kind': 'well-tops-csv/1'}])
    m['inputs'] = m['inputs'][:1]
    w.register(folder_of(w.root / 'proc', m, 'from ophiolite import procedure\n\n\n@procedure\ndef send(inputs, settings):\n    return {}\n'))

REFUSALS = {
    'unbound slot': (None, {'items': ['other=Tops@1']}, 'unknown-input'),
    'no such item': (None, {'items': ['tops=Bottoms@1']}, 'item-missing'),
    'no such version': (None, {'items': ['tops=Tops@9']}, 'item-version'),
    'item format': (None, {'items': ['tops=@1']}, 'item-format'),
    'no item': (None, {'items': []}, 'missing-input'),
    'two for a slot of one': (None, {'items': ['tops=Tops@1', 'tops=Tops@2']}, 'too-many-inputs'),
    'unreadable version': (unreadable, {}, 'item-unreadable'),
    'no configuration': (None, {'systems': {}}, 'missing-input'),
    'secret-looking setting': (None, {'settings': ['note=postgresql://anna-writer@db/team']}, 'setting-secret'),
    'secret-looking default': ('secret-default', {}, 'setting-secret'),
    'windows': (windows, {}, 'windows'),
    'untrusted': (untrusted, {}, 'trust-needed'),
    'declined': (untrusted, {'prompt': lambda question: False}, 'declined'),
    'withdrawn': (withdrawn, {}, 'withdrawn'),
    'inaccessible': (None, {'name': 'team/not-in-this-project'}, 'no-enabled-version'),
    'tampered bundle': (tampered, {}, 'bundle-differs'),
    'not a send': (not_a_send, {'name': 'team/tops-copy'}, 'not-a-send'),
}


@pytest.mark.parametrize('case', sorted(REFUSALS))
def test_a_refusal_before_launch_leaves_no_pending_record_no_call_and_no_report(world, case, monkeypatch):
    w = world
    monkeypatch.setattr(procedures, '_windows', procedures._windows)
    change, given, code = REFUSALS[case]
    given = dict(given)
    if change == 'secret-default':
        m = manifest(name='team/secret-default')
        m['settings'][1]['default'] = 'host@db'
        w.register(folder_of(w.root / 'secret', m))
        given = {'name': 'team/secret-default'}
    elif change: change(w)
    with pytest.raises(procedures.NotRun) as refused:
        deliver(w, **{'items': given.pop('items', ['tops=Tops@1']), **given})
    assert refused.value.code == code, (case, refused.value.code, str(refused.value))
    nothing_launched(w)
    assert not (w.work / 'deliveries').exists() or list((w.work / 'deliveries').iterdir()) == []


def test_the_windows_refusal_is_the_sentence_and_comes_first(world, monkeypatch):
    w = world
    monkeypatch.setattr(procedures, '_windows', lambda: True)
    with pytest.raises(procedures.NotRun) as refused: deliver(w, systems={})
    assert str(refused.value) == 'Delivering from this computer is not supported on Windows yet.' and not w.work.exists()


# ---------------------------------------------------------------- 5. the writer refuses: not sent, nothing written

def test_a_writer_that_refuses_is_not_sent_and_its_reason_stays_here(world):
    w = world
    answer = deliver(w, settings=['mode=refuse'])
    assert answer['state'] == 'not-sent' and answer['reported'] and delivered_files(w) == {}
    assert answer['sentence'] == f'Not sent to {DESTINATION} by Tops to team folder on this computer. Recorded in the project.'
    assert w.deliveries.states(answer['delivery_id']) == ['not-sent'] and w.posts[0]['delivery']['items'] == 0
    folder = Path(answer['folder'])
    assert 'The team folder is closed today' in (folder / 'log.txt').read_text()  # the reason, on this computer only
    assert PLANTED not in json.dumps(w.posts) and PLANTED not in (folder / 'attempt.json').read_text()


# ---------------------------------------------------------------- 6. the report accepted, its response lost: replayed

def test_a_lost_report_response_is_replayed_under_the_same_report_id_without_a_second_call(world):
    w = world
    w.lose_response = 1
    first = deliver(w)
    assert first['state'] == 'confirmed' and not first['reported'] and 'Not recorded in the project yet' in first['sentence']
    again = deliver(w)
    assert again['delivery_id'] == first['delivery_id'] and again['reported'] and count(w) == 1
    assert [p['event_id'] for p in w.posts] == [w.posts[0]['event_id']] * 2  # the saved report id, sent again
    assert w.deliveries.states(first['delivery_id']) == ['confirmed'] and attempt_of(again)['finished']
    assert deliver(w)['delivery_id'] != first['delivery_id'] and count(w) == 2  # after that, a new run is a new delivery


# ---------------------------------------------------------------- 8. a concurrent deliver from the folder is refused

def test_a_second_delivery_from_the_same_folder_is_refused_while_one_runs(world):
    w = world
    w.work.mkdir()
    fd = os.open(w.work / 'delivery.lock', os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # as a running writer holds it
        with pytest.raises(procedures.NotRun) as busy: deliver(w)
    finally: os.close(fd)
    assert busy.value.code == 'delivery-busy' and str(busy.value) == procedures.SENTENCES['delivery-busy']
    nothing_launched(w)


# ---------------------------------------------------------------- R5-1: a pending attempt is never launched again

class ParentStopped(BaseException):
    """The parent process stops after the writer ran, before it saved what the writer said."""


def stopped_parent(w, monkeypatch, **kw):
    def stop(process, folder):
        process.wait()
        raise ParentStopped()
    monkeypatch.setattr(procedures, '_launched', stop)
    with pytest.raises(ParentStopped): deliver(w, **kw)
    monkeypatch.setattr(procedures, '_launched', lambda process, folder: None)
    (path,) = attempts(w)
    return path


def test_a_pending_attempt_is_never_launched_again(world, monkeypatch):
    w = world
    path = stopped_parent(w, monkeypatch)
    pending = json.loads(path.read_text())
    assert count(w) == 1 and pending['result'] is None and isinstance(pending['process_group'], int) and w.posts == []
    answers = [deliver(w) for _ in range(2)]  # slice 2: recorded as unknown once, never launched again
    assert [a['state'] for a in answers] == ['unknown', 'unknown'] and answers[0]['delivery_id'] == pending['delivery_id']
    assert answers[0]['sentence'] == f'Outcome unknown for {DESTINATION} by Tops to team folder on this computer. It was not sent again. Recorded in the project.'
    assert count(w) == 1 and len({p['event_id'] for p in w.posts}) == 1 and w.deliveries.states(pending['delivery_id']) == ['unknown']


def test_an_unknown_outcome_is_reported_again_and_never_sent_again(world):
    w = world
    first = deliver(w, settings=['mode=malformed'])
    assert first['state'] == 'unknown' and first['reported'] and not attempt_of(first)['finished']
    again = deliver(w, settings=['mode=malformed'])
    assert (again['state'], again['delivery_id']) == ('unknown', first['delivery_id']) and count(w) == 1
    assert [p['event_id'] for p in w.posts] == [w.posts[0]['event_id']] * 2 and w.deliveries.states(first['delivery_id']) == ['unknown']


# ---------------------------------------------------------------- 9, 15. what is given again must be what the attempt saved (R1, 2-6)

def test_a_changed_configuration_settings_bundle_or_reporter_is_refused_and_nothing_runs(world, monkeypatch):
    w = world
    path = stopped_parent(w, monkeypatch)
    other = w.root / 'other.json'
    other.write_text(json.dumps({'folder': str(w.root / 'elsewhere')}))
    for given, changed in (({'systems': {'dest': str(other)}}, 'configuration'), ({'settings': ['note=other']}, 'settings')):
        with pytest.raises(procedures.NotRun) as refused: deliver(w, **given)
        assert (refused.value.code, refused.value.details['changed']) == ('delivery-changed', changed)
    w.reporter = 'another-key'
    with pytest.raises(procedures.NotRun) as refused: deliver(w)
    assert refused.value.code == 'delivery-other-person'
    w.reporter = 'anna-key'
    pinned = path.parent / 'procedure' / 'procedure.py'
    pinned.write_text(pinned.read_text() + '\n# changed here\n')
    with pytest.raises(procedures.NotRun) as refused: deliver(w)
    assert (refused.value.code, refused.value.details['changed']) == ('delivery-changed', 'procedure')
    assert count(w) == 1 and w.posts == []


# ---------------------------------------------------------------- 10. malformed answers are unknown; a mismatched id is the server's

@pytest.mark.parametrize('mode', ['malformed', 'boolean', 'raise', 'die'])
def test_a_malformed_answer_an_error_or_a_stopped_writer_is_unknown(world, mode):
    w = world
    answer = deliver(w, settings=['mode=' + mode])
    assert answer['state'] == 'unknown' and answer['items'] == 0 and answer['reported'] and count(w) == 1
    said = (f'The procedure stopped with an error: The connection was lost. {procedures.RAISED_NEXT.format(slot="dest")}' if mode == 'raise'
            else procedures.UNSAID)  # adhoc-e121-claims (O6)
    assert answer['sentence'] == f'Outcome unknown for {DESTINATION} by Tops to team folder on this computer. {said} Recorded in the project.'
    assert w.posts[0]['delivery'] == {'delivery_id': answer['delivery_id'], 'state': 'unknown', 'items': 0}


def test_a_report_naming_another_person_s_delivery_is_refused_and_stays_here(world):
    w = world
    w.reporter = 'bob-key'
    bobs = deliver(w)
    shutil.rmtree(w.work / 'deliveries')
    w.reporter = 'anna-key'
    mine = deliver(w, settings=['mode=malformed'])
    path = Path(mine['folder']) / 'attempt.json'
    attempt = json.loads(path.read_text())
    attempt['delivery_id'] = bobs['delivery_id']  # tampered here: the record refuses it (M6)
    path.write_text(json.dumps(attempt))
    again = deliver(w, settings=['mode=malformed'])
    assert (again['state'], again['reported']) == ('unknown', False) and not json.loads(path.read_text())['reported'] and w.deliveries.states(bobs['delivery_id']) == ['confirmed'] and count(w) == 2


# ---------------------------------------------------------------- 14. two slots of one kind (2-4)

def test_two_slots_of_one_kind_bind_by_slot_and_a_bare_item_is_refused(world):
    w = world
    w.add_item('tops-b', 'Other tops', [('3' * 64, 'name,md\nXA,10\n')])
    w.register(folder_of(w.root / 'two', manifest(slots=('tops', 'other'), name='team/two')))
    with pytest.raises(procedures.NotRun) as bare: deliver(w, ['Tops@1', 'other=Other tops'], name='team/two')
    assert bare.value.code == 'item-slot'
    nothing_launched(w)
    answer = deliver(w, ['other=Other tops', 'tops=Tops@2'], name='team/two')
    assert delivered_files(w) == {f"{answer['delivery_id']}/other-0.csv": 'name,md\nXA,10\n', f"{answer['delivery_id']}/tops-0.csv": V2}
    assert [s[0] for s in attempt_of(answer)['slots']] == ['other', 'tops'] and answer['items'] == 5


# ---------------------------------------------------------------- 15. the same versions twice are two deliveries (2-6)

def test_two_deliveries_of_the_same_versions_have_their_own_ids_and_records(world):
    w = world
    one, two = deliver(w), deliver(w)
    assert one['delivery_id'] != two['delivery_id'] and w.posts[0]['refs'] == w.posts[1]['refs']
    assert w.deliveries.states(one['delivery_id']) == ['confirmed'] == w.deliveries.states(two['delivery_id']) and count(w) == 2


def test_access_revoked_after_the_destination_commit_keeps_the_outcome_here(world):
    w = world
    def revoked(body, reporter): raise PermissionRefused('Project read permission required', status=403)
    w.deliveries.report = revoked
    answer = deliver(w)
    assert answer['state'] == 'confirmed' and not answer['reported'] and len(delivered_files(w)) == 1
    assert answer['sentence'].endswith('Not recorded in the project yet: Project read permission required')
    kept = attempt_of(answer)
    assert kept['result']['state'] == 'confirmed' and not kept['finished'] and w.deliveries.events == []


# ---------------------------------------------------------------- the pending record holds no configuration (D9, M6)

def test_the_attempt_and_the_report_hold_no_configuration(world):
    w = world
    w.config.write_text(json.dumps({'folder': str(w.dest), }))
    secret = w.root / 'secret.json'
    secret.write_text(json.dumps({'folder': str(w.dest) + '/' + PLANTED}))
    (w.dest / PLANTED).mkdir()
    answer = deliver(w, systems={'dest': str(secret)})
    folder = Path(answer['folder'])
    kept = '\n'.join(p.read_text(errors='replace') for p in folder.rglob('*.json'))
    assert PLANTED not in kept and PLANTED not in json.dumps(w.posts) and not (folder / 'request.json').exists()
    assert attempt_of(answer)['config_sha256'] == procedures._fingerprint({'dest': str(secret)})


# ---------------------------------------------------------------- 4-10 the scaffold, R5-8 a send with no system

def test_the_send_start_delivers_as_made(world):
    w = world  # E112 s1: `new` makes a working send start (a folder destination), no longer a stub to fill in
    folder = w.root / 'procedures' / 'scaffold-send'
    assert procedures.new(folder, 'send', 'Scaffold send')['valid']
    assert 'def main(inputs, settings, delivery):' in (folder / 'procedure.py').read_text()
    (w.root / 'team').mkdir()
    (w.root / 'team.json').write_text(json.dumps({'folder': str(w.root / 'team')}))
    w.register(folder)
    answer = deliver(w, ['data=Tops@1'], name='scaffold-send', systems={'destination': str(w.root / 'team.json')})
    assert (answer['state'], answer['items'], answer['destination'], answer['reported']) == ('confirmed', 1, 'Folder to send to', True)
    assert sorted(p.name for p in (w.root / 'team' / answer['delivery_id']).iterdir())[-1] == 'delivery.json'


def test_a_send_that_names_no_system_delivers_under_its_delivery_label(world):
    w = world
    folder = w.root / 'procedures' / 'legacy-send'
    folder.mkdir()
    shutil.copyfile(FIXTURES / 'valid/send.json', folder / 'procedure.json')
    (folder / 'procedure.py').write_text('import ophiolite\nfrom ophiolite import procedure\n\n\n@procedure\ndef send(inputs, settings, delivery):\n'
                                         '    assert delivery.system is None\n    return ophiolite.delivered(items=len(inputs["tops"]))\n')
    w.register(folder)
    answer = deliver(w, ['Tops@1', 'Tops@2'], name='send-tops', systems={})
    assert (answer['state'], answer['items'], answer['destination']) == ('confirmed', 2, 'Sent files')
    assert w.posts[0]['destination'] == 'Sent files' and [r['revision'] for r in w.posts[0]['refs']] == [REV1, REV2]
    assert w.posts[0]['procedure']['label'] == 'Send tops to the partner'


# ---------------------------------------------------------------- the command's words and exit codes

def test_the_command_says_what_became_of_the_delivery(world, capsys):
    w = world
    args = SimpleNamespace(as_=None, name='team/tops-folder', system=['dest=' + str(w.config)], item=['tops=Tops@1'], setting=[], work=w.work, wait=0,
                           set_aside=False, yes=False, version=None, json=False)
    assert cli._deliver(args, w)['state'] == 'confirmed'
    assert capsys.readouterr().out.startswith(f'Sent to {DESTINATION} by Tops to team folder on this computer: 3 items.')
    with pytest.raises(SystemExit) as stop: cli._deliver(SimpleNamespace(**{**vars(args), 'setting': ['mode=refuse']}), w)
    assert stop.value.code == cli.EXIT['conflict'] and capsys.readouterr().out.startswith('Not sent to ')


def test_the_client_may_call_the_delivery_routes_and_says_the_project_s_refusal_in_its_words(world):
    """The operation map names activity/deliver and activity/deliveries (the fake above never asks it; the gateway journey
    found it missing); a refused report keeps the project's own sentence, not the transport's generic one."""
    from ophiolite.publish import operation_path
    for op in ('report', 'deliver', 'deliveries'): assert operation_path('p', 'activity', op) == '/api/v1/projects/p/activity/' + op
    w = world
    said = 'You can no longer read every version this delivery names, so its outcome cannot be recorded.'
    def refuse(body, reporter): raise PermissionRefused('Check project access and the approved grant.', status=403, server_message=said)
    w.deliveries.report = refuse
    answer = deliver(w)
    assert (answer['state'], answer['reported']) == ('confirmed', False)
    assert answer['sentence'] == f'Sent to {DESTINATION} by Tops to team folder on this computer: 3 items. Not recorded in the project yet: {said}'


# ---------------------------------------------------------------- slice 2: reconcile, the process group, --set-aside (D8)

@pytest.fixture
def reconciling(world):
    """The same writer with `reconcile` declared, registered as team/tops-reconcile."""
    w = world
    m = dict(manifest(name='team/tops-reconcile', label='Tops to team folder'), reconcile='procedure:reconcile')
    w.folder_r = folder_of(w.root / 'procedures-r', m, CODE + RECONCILE)
    w.digest_r = w.register(w.folder_r)
    return w


def deliver_r(w, **kw):
    return deliver(w, name='team/tops-reconcile', **kw)


def reconciled(w):
    path = w.root / 'reconciled'
    return int(path.read_text()) if path.exists() else 0


def stopped_parent_r(w, monkeypatch, **kw):
    return stopped_parent(w, monkeypatch, name='team/tops-reconcile', **kw)


def test_a_writer_killed_after_its_commit_is_reconciled_to_confirmed_and_ran_once(reconciling):
    """C3 test 3 (mutation: a blind retry makes the count 2)."""
    w = reconciling
    first = deliver_r(w, settings=['mode=commit_die'])
    assert (first['state'], first['reported'], count(w)) == ('unknown', True, 1)
    again = deliver_r(w, settings=['mode=commit_die'])
    assert (again['state'], again['items'], again['delivery_id'], again['reported']) == ('confirmed', 3, first['delivery_id'], True)
    assert again['sentence'] == f'Sent to {DESTINATION} by Tops to team folder on this computer: 3 items. Recorded in the project.'
    assert count(w) == 1 and reconciled(w) == 1 and w.deliveries.states(first['delivery_id']) == ['unknown', 'confirmed']
    assert w.posts[0]['event_id'] != w.posts[1]['event_id']  # a terminal transition has its own report id (R2)
    assert attempt_of(again)['finished'] and procedures._pending(w.work, 'team/tops-reconcile') == (None, None)


def test_a_parent_stopped_before_it_saved_the_answer_is_reconciled_without_a_second_call(reconciling, monkeypatch):
    w = reconciling
    path = stopped_parent_r(w, monkeypatch)
    assert json.loads(path.read_text())['result'] is None and w.posts == []
    again = deliver_r(w)
    assert (again['state'], again['items'], count(w), reconciled(w)) == ('confirmed', 3, 1, 1)
    assert [p['delivery']['state'] for p in w.posts] == ['confirmed']


def test_a_failed_result_save_is_recovered_through_reconcile(reconciling, monkeypatch):
    """C3 test 7: the writer committed but its answer was never saved here."""
    w = reconciling
    save = procedures._save
    def failing(path, value):
        if path.name == 'attempt.json' and value.get('result'): raise OSError('No space left on device')
        save(path, value)
    monkeypatch.setattr(procedures, '_save', failing)
    with pytest.raises(OSError): deliver_r(w)
    monkeypatch.setattr(procedures, '_save', save)
    again = deliver_r(w)
    assert (again['state'], again['items'], count(w), reconciled(w)) == ('confirmed', 3, 1, 1)


def test_absence_alone_stays_unknown_and_only_the_tombstone_says_not_sent(reconciling, monkeypatch):
    """C3 test 4 with reconcile, 12a offline (4-1): the writer stopped before it wrote anything."""
    w = reconciling
    first = deliver_r(w, settings=['mode=die'])
    assert first['state'] == 'unknown'
    again = deliver_r(w, settings=['mode=die'])  # the id is absent and no tombstone was written: unknown
    assert (again['state'], again['delivery_id'], reconciled(w)) == ('unknown', first['delivery_id'], 1)
    assert again['sentence'] == f'Outcome unknown for {DESTINATION} by Tops to team folder on this computer. It was not sent again. Recorded in the project.'
    monkeypatch.setenv('E109_RECONCILE', 'tombstone')
    last = deliver_r(w, settings=['mode=die'])
    assert (last['state'], last['items'], last['sentence']) == ('not-sent', 0, f'Not sent to {DESTINATION} by Tops to team folder on this computer. Recorded in the project.')
    assert (w.dest / (first['delivery_id'] + '.withdrawn')).exists() and count(w) == 1 and reconciled(w) == 2
    assert w.deliveries.states(first['delivery_id']) == ['unknown', 'not-sent'] and attempt_of(last)['finished']


def test_without_reconcile_the_outcome_stays_unknown_and_the_writer_is_not_run_again(world):
    """C3 test 4: no `reconcile` declared; every rerun is the server's no-op."""
    w = world
    first = deliver(w, settings=['mode=commit_die'])
    for _ in range(2): assert deliver(w, settings=['mode=commit_die'])['state'] == 'unknown'
    assert count(w) == 1 and reconciled(w) == 0 and {p['event_id'] for p in w.posts} == {w.posts[0]['event_id']}
    assert w.deliveries.states(first['delivery_id']) == ['unknown']


@pytest.mark.parametrize('mode', ['unknown', 'malformed', 'raise'])
def test_a_reconcile_that_does_not_say_delivered_or_not_delivered_is_unknown(reconciling, monkeypatch, mode):
    w = reconciling
    stopped_parent_r(w, monkeypatch)
    monkeypatch.setenv('E109_RECONCILE', mode)
    again = deliver_r(w)
    assert (again['state'], again['items'], count(w), reconciled(w)) == ('unknown', 0, 1, 1)


def test_reconcile_runs_only_with_the_attempt_s_configuration(reconciling, monkeypatch):
    """C3 test 9 with reconcile (mutation: reconcile skips the fingerprint check)."""
    w = reconciling
    stopped_parent_r(w, monkeypatch)
    other = w.root / 'other.json'
    other.write_text(json.dumps({'folder': str(w.dest), 'note': 'moved'}))
    with pytest.raises(procedures.NotRun) as refused: deliver_r(w, systems={'dest': str(other)})
    assert (refused.value.code, refused.value.details['changed']) == ('delivery-changed', 'configuration')
    assert reconciled(w) == 0 and w.posts == []
    assert deliver_r(w)['state'] == 'confirmed' and reconciled(w) == 1


def test_reconcile_runs_after_the_procedure_was_withdrawn(reconciling, monkeypatch):
    """C3 test 13 (2-3, D8 decision): withdrawal stops a first launch, never the reconcile of a delivery already made."""
    w = reconciling
    stopped_parent_r(w, monkeypatch)
    w.catalogue[w.digest_r].update(state='withdrawn', withdrawn_at=1760000000)
    assert deliver_r(w)['state'] == 'confirmed' and count(w) == 1


def test_a_writer_whose_process_group_still_runs_is_never_reconciled(reconciling, monkeypatch):
    """D8: hygiene, not proof: while the recorded group runs, nothing is asked of the destination."""
    w = reconciling
    stopped_parent_r(w, monkeypatch)
    monkeypatch.setattr(procedures, '_group_alive', lambda group: True)
    with pytest.raises(procedures.NotRun) as running: deliver_r(w)
    assert (running.value.code, str(running.value)) == ('delivery-running', 'This delivery is still running on this computer; try again when it has finished.')
    assert reconciled(w) == 0 and w.posts == [] and count(w) == 1


def test_the_process_group_check_sees_a_running_group_and_its_end():
    import subprocess
    import sys
    child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], stdin=subprocess.PIPE, start_new_session=True)
    try:
        assert procedures._group_alive(child.pid)
        with pytest.raises(procedures.NotRun) as running: procedures._until_finished(child.pid, 0)
        assert running.value.code == 'delivery-running'
    finally:
        child.stdin.close(); child.wait()
    assert not procedures._group_alive(child.pid) and not procedures._group_alive(None)
    procedures._until_finished(child.pid, 0)


def test_set_aside_records_unknown_clears_this_folder_and_a_new_delivery_may_start(reconciling, monkeypatch):
    """C3 test 11."""
    w = reconciling
    path = stopped_parent_r(w, monkeypatch)
    pending = json.loads(path.read_text())
    put = deliver_r(w, set_aside=True)
    assert put['sentence'] == f'Set aside: the outcome of this delivery to {DESTINATION} stays unknown in the project; this folder no longer waits for it.'
    assert (put['state'], put['delivery_id'], put['reported']) == ('unknown', pending['delivery_id'], True)
    assert attempts(w) == [] and json.loads((path.parent / 'set-aside.json').read_text())['set_aside'] is True  # attempt.json is gone
    assert w.deliveries.states(pending['delivery_id']) == ['unknown'] and reconciled(w) == 0
    with pytest.raises(procedures.NotRun) as nothing: deliver_r(w, set_aside=True)
    assert str(nothing.value) == 'There is no delivery of team/tops-reconcile waiting in this folder to set aside.'
    fresh = deliver_r(w)
    assert fresh['state'] == 'confirmed' and fresh['delivery_id'] != pending['delivery_id'] and count(w) == 2


def test_set_aside_refuses_an_outcome_this_computer_knows_and_one_the_project_did_not_record(reconciling, monkeypatch):
    w = reconciling
    w.lose_response = 1
    known = deliver_r(w)
    assert (known['state'], known['reported']) == ('confirmed', False)
    with pytest.raises(procedures.NotRun) as refused: deliver_r(w, set_aside=True)
    assert refused.value.code == 'set-aside-known'
    assert deliver_r(w)['reported'] and procedures._pending(w.work, 'team/tops-reconcile') == (None, None)
    shutil.rmtree(w.work / 'deliveries')
    stopped_parent_r(w, monkeypatch)
    w.lose_response = 1
    with pytest.raises(procedures.NotRun) as unrecorded: deliver_r(w, set_aside=True)
    assert unrecorded.value.code == 'set-aside-unreported' and len(attempts(w)) == 1


def test_the_command_sets_a_delivery_aside(reconciling, monkeypatch, capsys):
    w = reconciling
    stopped_parent_r(w, monkeypatch)
    args = SimpleNamespace(as_=None, name='team/tops-reconcile', system=[], item=[], setting=[], work=w.work, wait=0, set_aside=True, yes=False, version=None, json=False)
    assert cli._deliver(args, w)['state'] == 'unknown'
    assert capsys.readouterr().out.startswith(f'Set aside: the outcome of this delivery to {DESTINATION} stays unknown')
