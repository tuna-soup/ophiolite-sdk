"""E129 Sa C4 (strategy rev 4, D4-D8; R2, R4-R7, R12-R14, F1, F2, O1, O2, O4, M1, M4): `ophiolite starter build` and
`finalise`, with a fake project. The fake runs the real `UploadRuns.upload` (its start, send, answer and status are the
project's), keeps every asset's revisions, and refuses a second upload of a file it already took, so a rerun that
sends a `started` input again to learn its result fails. Every refusal is asserted by its exact sentence; every byte
comparison is with an uninterrupted run or with a copy taken before.

Mutations (recorded in the E129 Sa Validation Record): `unpublished` not written; the heads transform skipped; the
digest check moved after the upload; the PermissionRefused sentence dropped; the revision taken from the summary; the
curve-summary comparison bypassed; the current-revision check removed; the evidence digests left out of the bindings;
`started` called after `send`; `built_at` from the clock; recovery re-sends a `started` input; the `landed` entry
written before the provenance check; the moved check skipped for recovered inputs; the shared-digest check removed;
finalise computes the key from the artefact path; finalise writes each key as it resolves; the evidence.json digest
check removed; the fidelity check removed; the input-set comparison made one-sided; deposits read from evidence.json
only."""
import json
from types import SimpleNamespace as NS

import pytest

from ophiolite import cli, fidelity, starter
from ophiolite.errors import IntegrityConflict, PermissionRefused, Refused
from ophiolite.upload_runs import Report, UploadRuns
from test_starter import PACK, RID, TOPS, files, made, sha

pytest.importorskip('pyproj')
pytest.importorskip('lasio')

LAS_READER, TOPS_READER, PATH_READER = 'asset_connectors.las_reader/1', 'asset_connectors.well_tops_csv/1', 'asset_connectors.deviation_csv/1'
PROFILES = {'syn-1.las': 'las2/1', 'syn-2.las': 'las2/1', 'syn-1-tops.csv': 'well-tops-csv/1', 'syn-1-deviation.csv': 'deviation-csv/1'}
COUNTS = ('added', 'already_here', 'needs_decision', 'not_read', 'not_supported', 'cancelled', 'waiting', 'reading')


class Project:
    """One project: upload runs and the assets they land, read at exact revisions. `asked` records every call."""
    url, project = 'https://gateway.example.org', 'p-starter'

    def __init__(self, out=None):
        self.out, self.asked, self.runs, self.assets, self.taken = out, [], {}, {}, set()
        self.denied, self.unreadable, self.other_content, self.summary = set(), set(), set(), {}
        self.journal_at_send = {}

    # the upload runs, as UploadRuns calls them
    def start(self, body):
        (listed,) = body['files']
        name = listed['path']
        self.asked.append(('start', name))
        if name in self.denied: raise PermissionRefused('You may not add files to this project.')
        assert name not in self.taken, 'sent again: %s' % name
        self.taken.add(name)
        run = 'run-%d' % (len(self.runs) + 1)
        self.runs[run] = {'name': name, 'sha256': listed['sha256'], 'bytes': listed['bytes'], 'state': 'open', 'declared': None, 'row': None}
        return {'run_id': run}

    def unfinished(self, folder):
        """An open run of the same file resumes (UploadRuns.unfinished); a closed one never does."""
        (f,) = folder.files
        return next((run for run, r in self.runs.items() if r['name'] == f.path and r['state'] == 'open'), None)

    def decide(self, run, ordinals, action, values):
        self.asked.append(('decide', self.runs[run]['name']))
        self.runs[run]['declared'] = {k: str(v) for k, v in values.items()}

    def send(self, run, folder):
        r = self.runs[run]
        self.asked.append(('send', r['name']))
        if self.out is not None and r['name'] not in self.journal_at_send:
            self.journal_at_send[r['name']] = json.loads((self.out / 'landing.json').read_text())['inputs'].get(r['name'])
        if r['state'] == 'open':
            if PROFILES[r['name']] != 'las2/1' and r['declared'] is None: return self.status(run, needs=True)
            asset = 'item-' + r['name'].split('.')[0]
            revisions = self.assets.setdefault(asset, {'name': r['name'], 'revisions': [], 'content': r['sha256']})['revisions']
            revisions.append('r%d' % (len(revisions) + 1))
            r.update(state='closed', row={'asset_id': asset, 'revision': revisions[-1]})
        return self.status(run)

    def status(self, run, needs=False):
        r = self.runs[run]
        self.asked.append(('status', r['name']))
        row = {'ordinal': 0, 'path': r['name'], 'bytes': r['bytes'], 'sha256': r['sha256'], 'role': 'primary', 'profile': PROFILES[r['name']],
               'state': 'needs-decision' if needs else 'added' if r['row'] else 'waiting', 'reason_code': 'needs-declarations' if needs else None,
               'declared': r['declared'], **(r['row'] or {})}
        counts = {k: 0 for k in COUNTS}
        counts[{'needs-decision': 'needs_decision', 'added': 'added', 'waiting': 'waiting'}[row['state']]] = 1
        return Report({'run_id': run, 'state': r['state'], 'label': 'Finished' if r['state'] == 'closed' else 'Open', 'folder_name': r['name'],
                       'files': 1, 'counts': counts, 'items': [row]})

    # the reads, as fidelity.landed calls them
    def assets_(self):
        for asset, a in sorted(self.assets.items()):
            yield {'asset_id': asset, 'revision': self.summary.get(asset, a['revisions'][-1]), 'curves': ['GR'] if a['name'].endswith('.las') else []}

    def provenance(self, asset, revision):
        self.asked.append(('provenance', asset, revision))
        if asset in self.unreadable: raise PermissionRefused('You may not read this item.')
        content = 'e' * 64 if asset in self.other_content else self.assets[asset]['content']
        return NS(record={'content': {'content_sha256': content}})

    def describe(self, asset, revision, curve):
        self.asked.append(('describe', asset, revision))
        return NS(interpretation=NS(reader=LAS_READER), scientific=NS(sample_count=2))

    def read(self, asset, revision, curves):
        self.asked.append(('read', asset, revision))
        return NS(curves=[NS(curve='GR', axis=[1000.0, 1000.5], values=[45.1, 46.0], unit='GAPI')])

    def read_data(self, asset, revision):
        self.asked.append(('read_data', asset, revision))
        tops = self.assets[asset]['name'].endswith('tops.csv')
        return NS(type='well-tops' if tops else 'well-path', descriptor=NS(interpretation=NS(reader=TOPS_READER if tops else PATH_READER)))


@pytest.fixture
def project(monkeypatch):
    """The fake project behind UploadRuns: the real `upload`, `answer` and `open`; the project's start, decide, send and status."""
    p = Project()
    monkeypatch.setattr(UploadRuns, 'unfinished', lambda self, folder, declared=None: p.unfinished(folder))
    monkeypatch.setattr(UploadRuns, '_call', lambda self, op, body, model=None, retry=True: p.start(body) if op == 'start' else pytest.fail(op))
    monkeypatch.setattr(UploadRuns, 'decide', lambda self, run, ordinals, action, values=None: p.decide(run, ordinals, action, values))
    monkeypatch.setattr(UploadRuns, 'send', lambda self, run, folder, progress=None, passes=3: p.send(run, folder))
    monkeypatch.setattr(UploadRuns, 'status', lambda self, run: p.status(run))
    return p


def client(p, **given):
    return NS(url=given.get('url', p.url), project=given.get('project', p.project), assets=p.assets_, provenance=p.provenance,
              describe=p.describe, read=p.read, read_data=p.read_data)


def build(folder, p, out='out', **given):
    p.out = folder / out
    return starter.build(client(p, **given), folder / 'definition.json', folder / out, catalogue=folder / 'records.json',
                         verification=folder / 'verification', custody=folder / 'custody')


def refused(error, fn, *args, **kwargs):
    with pytest.raises(error) as caught: fn(*args, **kwargs)
    return str(caught.value), cli.exit_code(caught.value)


def starts(p):
    return [a[1] for a in p.asked if a[0] == 'start']


def journal(folder, out='out'):
    return json.loads((folder / out / 'landing.json').read_text())['inputs']


ARTEFACTS = ['targets/python/open_pack.py', 'targets/python/heads/SYN-1.geojson', 'targets/python/heads/SYN-2.geojson', 'ATTRIBUTION.md']


def test_build_lands_each_input_and_writes_the_unpublished_pack(tmp_path, project):
    folder = made(tmp_path)
    doc = build(folder, project)
    written = json.loads((folder / 'out/starter.json').read_bytes())
    assert written == doc and written['unpublished'] is True and written['format'] == 'osd.starter/1' and written['id'] == PACK
    target = written['targets'][0]
    assert [a['path'] for a in target['artefacts']] == ARTEFACTS and not any('key' in a for a in target['artefacts'])
    for a in target['artefacts']:
        raw = (folder / 'out/files' / a['path']).read_bytes()
        assert (a['sha256'], a['bytes']) == (sha(raw), len(raw))
    assert [d['from'] for d in written['derived']] == [sha(files()['syn-1.las']), sha(files()['syn-2.las'])]
    assert target['oracle'] == starter.ORACLE and target['import'] == 'targets/python/open_pack.py' and written['fidelity'] == 'fidelity/ophiolite-synthetic__two-wells__starter.json'
    fd = json.loads((folder / 'out' / written['fidelity']).read_text())
    assert fd['record'] == RID and [(i['name'], i['result'], i['output']['kind'], i['output']['id']) for i in fd['inputs']] == [
        ('syn-1.las', 'converted', 'wellbore-logs', 'item-syn-1'), ('syn-2.las', 'converted', 'wellbore-logs', 'item-syn-2'),
        ('syn-1-tops.csv', 'converted', 'tops', 'item-syn-1-tops'), ('syn-1-deviation.csv', 'converted', 'wellbore-paths', 'item-syn-1-deviation')]
    assert fd['inputs'][0]['representative'] == [{'field': 'GR@1000.0', 'value': 45.1, 'unit': 'GAPI'}, {'field': 'samples', 'value': 2, 'unit': None}]
    assert [project.runs[r]['declared'] for r in sorted(project.runs)] == [None, None, {'depth_basis': 'same-as-log', 'depth_unit': 'm', 'depth_datum': 'rotary table'},
                                                                         {'azimuth_reference': 'grid-north', 'depth_unit': 'm', 'depth_datum': 'rotary table'}]


def test_the_heads_are_the_zones_central_meridians(tmp_path, project):
    folder = made(tmp_path)
    build(folder, project)
    heads = {w: json.loads((folder / ('out/files/targets/python/heads/%s.geojson' % w)).read_text())['geometry']['coordinates'] for w in ('SYN-1', 'SYN-2')}
    assert heads == {'SYN-1': [3.0, 0.0], 'SYN-2': [9.0, 0.0]}


def test_a_changed_input_byte_refuses_before_any_call(tmp_path, project):
    folder = made(tmp_path)
    (folder / 'inputs/syn-1-tops.csv').write_bytes(TOPS + b'Delta,1003.0\n')
    assert refused(Refused, build, folder, project) == ('syn-1-tops.csv is not the file the definition names: its SHA-256 differs. Nothing was sent.', 1)
    assert project.asked == [] and not (folder / 'out').exists()


def test_a_permission_denial_on_the_second_input_names_what_landed(tmp_path, project):
    folder = made(tmp_path)
    project.denied.add('syn-2.las')
    assert refused(PermissionRefused, build, folder, project) == (
        'This access key may not add files to project p-starter: syn-2.las was not landed (1 of 4 inputs landed before it, kept in landing.json). No pack document was written.', 3)
    assert {n: e['state'] for n, e in journal(folder).items()} == {'syn-1.las': 'landed'} and not (folder / 'out/starter.json').exists()


def test_a_typed_input_takes_its_revision_from_the_upload_row(tmp_path, project, monkeypatch):
    """R4/F2: the summary names a newer revision than the row; the reads and the journal carry the row's."""
    folder = made(tmp_path)
    send = project.send
    def newer(run, f):
        report = send(run, f)
        if project.runs[run]['name'] == 'syn-1-tops.csv' and project.runs[run]['row']: project.summary['item-syn-1-tops'] = 'r7'
        return report
    monkeypatch.setattr(UploadRuns, 'send', lambda self, run, f, progress=None, passes=3: newer(run, f))
    build(folder, project)
    assert journal(folder)['syn-1-tops.csv']['revision'] == 'r1'
    assert [a for a in project.asked if a[0] in ('provenance', 'read_data') and a[1] == 'item-syn-1-tops'] == [('provenance', 'item-syn-1-tops', 'r1'), ('read_data', 'item-syn-1-tops', 'r1')]


def test_a_las_input_with_a_newer_summary_keeps_the_fidelity_refusal(tmp_path, project, monkeypatch):
    folder = made(tmp_path)
    send = project.send
    def newer(run, f):
        report = send(run, f)
        if project.runs[run]['name'] == 'syn-1.las': project.summary['item-syn-1'] = 'r7'
        return report
    monkeypatch.setattr(UploadRuns, 'send', lambda self, run, f, progress=None, passes=3: newer(run, f))
    assert refused(Refused, build, folder, project) == (fidelity.NEWER % 'syn-1.las', 1)
    assert not (folder / 'out/starter.json').exists() and journal(folder)['syn-1.las']['state'] == 'started'


def test_a_moved_revision_on_a_rerun_is_a_conflict(tmp_path, project):
    folder = made(tmp_path)
    build(folder, project)
    project.summary['item-syn-1-tops'] = 'r2'
    assert refused(IntegrityConflict, build, folder, project) == (starter.MOVED % 'syn-1-tops.csv', 4)


BINDINGS = {
    'the gateway URL': ({'url': 'https://other.example.org'}, None, 'The gateway URL'),
    'the project': ({'project': 'p-other'}, None, 'The project'),
    'an evidence file': ({}, lambda f: (f / 'records.json').write_text((f / 'records.json').read_text() + ' '), 'The evidence file records.json'),
}


@pytest.mark.parametrize('case', sorted(BINDINGS))
def test_a_rerun_with_another_binding_refuses_naming_it(tmp_path, project, case):
    given, change, said = BINDINGS[case]
    folder = made(tmp_path)
    build(folder, project)
    if change: change(folder)
    assert refused(Refused, build, folder, project, **given) == (starter.BINDING % said + starter.NOT_WRITTEN, 1)


def test_each_input_is_journaled_started_with_its_run_before_any_content_is_sent(tmp_path, project):
    folder = made(tmp_path)
    build(folder, project)
    assert project.journal_at_send == {'syn-1.las': {'state': 'started', 'run_id': 'run-1'}, 'syn-2.las': {'state': 'started', 'run_id': 'run-2'},
                                       'syn-1-tops.csv': {'state': 'started', 'run_id': 'run-3'}, 'syn-1-deviation.csv': {'state': 'started', 'run_id': 'run-4'}}


def failing(monkeypatch, when):
    """starter.replaced raising once, when WHEN(path, bytes) first holds."""
    real, fired = starter.replaced, []
    def replaced(path, raw):
        if not fired and when(path, raw):
            fired.append(path); raise OSError('interrupted')
        return real(path, raw)
    monkeypatch.setattr(starter, 'replaced', replaced)
    return fired


def landed_entry(name, state='landed'):
    return lambda path, raw: path.name == 'landing.json' and json.loads(raw)['inputs'].get(name, {}).get('state') == state


INTERRUPTIONS = {
    'after the fidelity document': lambda path, raw: path.parent.name == 'fidelity',
    'between inputs, after the second run started': landed_entry('syn-2.las', 'started'),
    'after the server added an input, before its landed rename': landed_entry('syn-1-tops.csv'),
}


@pytest.mark.parametrize('case', sorted(INTERRUPTIONS))
def test_an_interrupted_build_continues_to_the_same_bytes(tmp_path, project, monkeypatch, case):
    (tmp_path / 'whole').mkdir(); (tmp_path / 'cut').mkdir()
    whole = made(tmp_path / 'whole')
    build(whole, project)
    expected = {p: (whole / 'out' / p).read_bytes() for p in ('starter.json', 'fidelity/ophiolite-synthetic__two-wells__starter.json')}
    project.__init__()  # a new project for the interrupted run: the same names give the same assets and revisions
    cut = made(tmp_path / 'cut')
    fired = failing(monkeypatch, INTERRUPTIONS[case])
    with pytest.raises(OSError): build(cut, project)
    assert fired
    build(cut, project)  # the fake refuses a second upload of a file it took: a started input is read from its run
    assert {p: (cut / 'out' / p).read_bytes() for p in expected} == expected
    assert sorted(starts(project)) == sorted(PROFILES)


def test_recovery_verifies_provenance_before_journaling_landed(tmp_path, project, monkeypatch):
    """M1: the server added the tops; their provenance is unreadable, then names other bytes, then is restored."""
    folder = made(tmp_path)
    project.unreadable.add('item-syn-1-tops')
    assert refused(Refused, build, folder, project) == (fidelity.UNREAD % 'syn-1-tops.csv', 1)
    assert journal(folder)['syn-1-tops.csv'] == {'state': 'started', 'run_id': 'run-3'}
    assert refused(Refused, build, folder, project) == (fidelity.UNREAD % 'syn-1-tops.csv', 1)
    assert journal(folder)['syn-1-tops.csv']['state'] == 'started'
    project.unreadable.clear(); project.other_content.add('item-syn-1-tops')
    assert refused(Refused, build, folder, project) == (fidelity.DIFFERS % 'syn-1-tops.csv', 1)
    assert journal(folder)['syn-1-tops.csv']['state'] == 'started'
    project.other_content.clear()
    build(folder, project)
    assert journal(folder)['syn-1-tops.csv']['state'] == 'landed' and starts(project).count('syn-1-tops.csv') == 1


def test_a_recovered_input_whose_revision_moved_is_a_conflict(tmp_path, project, monkeypatch):
    folder = made(tmp_path)
    failing(monkeypatch, landed_entry('syn-1-tops.csv'))
    with pytest.raises(OSError): build(folder, project)
    project.summary['item-syn-1-tops'] = 'r2'
    assert refused(IntegrityConflict, build, folder, project) == (starter.MOVED % 'syn-1-tops.csv', 4)
    assert journal(folder)['syn-1-tops.csv']['state'] == 'started'


def test_an_artefact_with_an_inputs_or_another_artefacts_bytes_refuses(tmp_path, project, monkeypatch):
    folder = made(tmp_path)
    monkeypatch.setattr(starter, 'open_pack', lambda defn: files()['syn-1.las'])
    assert refused(Refused, build, folder, project) == (
        'targets/python/open_pack.py has the same bytes as syn-1.las; an artefact must be made, not copied. Nothing was written.', 1)
    monkeypatch.setattr(starter, 'open_pack', lambda defn: b'print("open")\n')
    monkeypatch.setattr(starter, 'attribution', lambda defn, sources, evidence: b'print("open")\n')
    assert refused(Refused, build, folder, project) == (
        'ATTRIBUTION.md has the same bytes as targets/python/open_pack.py; an artefact must be made, not copied. Nothing was written.', 1)
    assert project.asked == [] and not (folder / 'out/starter.json').exists()


# --- finalise ----------------------------------------------------------------------------------------------------------

def derive(folder, out='out'):
    """The derived custody documents an upload of OUT/files would write (E13's layout: custody/<sha256>.json). Each names
    its file `derived-<last segment>`, so its key's last segment is not the artefact's own name."""
    doc = json.loads((folder / out / 'starter.json').read_text())
    keys = {}
    for a in doc['targets'][0]['artefacts']:
        path = 'derived-' + a['path'].rsplit('/', 1)[-1]
        key = 'mirror/%s/%s/%s' % (RID, a['sha256'], path)
        custody = {'format': 'osd.custody/2', 'record_id': RID, 'path': path, 'origin_href': None, 'key': key, 'href': 'https://mirror.example.org/' + key,
                   'sha256': a['sha256'], 'bytes': a['bytes'], 'copied_at': '2026-10-28T02:00:00Z', 'licence': {k: v for k, v in doc['licence'].items() if k != 'sources'},
                   'licence_text_sha256': None, 'attribution': ['Made by the starter recipe.'], 'takedown': 'https://example.org/takedown', 'removal': {'state': 'held'},
                   'derived': {'pack_id': PACK, 'recipe_id': 'ophiolite.starter/a', 'from': sorted({i['sha256'] for i in doc['inputs']})}}
        (folder / 'custody' / (a['sha256'] + '.json')).write_text(json.dumps(custody))
        keys[a['path']] = key
    return doc, keys


@pytest.fixture
def built(tmp_path, project):
    folder = made(tmp_path)
    build(folder, project)
    doc, keys = derive(folder)
    return folder, doc, keys


def test_finalise_reads_each_key_from_its_document(built):
    folder, doc, keys = built
    done = starter.finalise(folder / 'out', folder / 'custody')
    assert {a['path']: a['key'] for a in done['targets'][0]['artefacts']} == keys
    assert keys['ATTRIBUTION.md'] == 'mirror/%s/%s/derived-ATTRIBUTION.md' % (RID, doc['targets'][0]['artefacts'][3]['sha256'])
    raw = (folder / 'out/starter.json').read_bytes()
    assert json.loads(raw)['unpublished'] is True and json.loads(raw) == done
    starter.finalise(folder / 'out', folder / 'custody')
    assert (folder / 'out/starter.json').read_bytes() == raw


def unchanged(folder, fn, *args):
    before = (folder / 'out/starter.json').read_bytes()
    said = refused(Refused, fn, *args)
    assert (folder / 'out/starter.json').read_bytes() == before
    return said


def last(doc): return doc['targets'][0]['artefacts'][-1]


def custody_of(folder, a): return folder / 'custody' / (a['sha256'] + '.json')


def tombstone(folder, a):
    d = json.loads(custody_of(folder, a).read_text())
    d['removal'] = {'state': 'removed', 'removed_at': '2026-10-28T03:00:00Z', 'request': 'https://example.org/i/1', 'approved_by': 'maintainer'}
    (folder / 'custody' / (a['sha256'] + '.removed.json')).write_text(json.dumps(d)); custody_of(folder, a).unlink()


def edited(change):
    def edit(folder, a):
        d = json.loads(custody_of(folder, a).read_text()); change(d); custody_of(folder, a).write_text(json.dumps(d))
    return edit


FINALISE = {  # each on the last artefact, after the first three resolved
    'removed': (tombstone, 'artefact ATTRIBUTION.md: its custody document is removed: never in a pack.'),
    'missing': (lambda folder, a: custody_of(folder, a).unlink(), 'artefact ATTRIBUTION.md: no held custody document has its SHA-256.'),
    'another size': (edited(lambda d: d.update(bytes=1)), 'artefact ATTRIBUTION.md: bytes {n}, its custody document states 1.'),
    'another pack': (edited(lambda d: d['derived'].update(pack_id=RID + '/other')), 'artefact ATTRIBUTION.md: custody key {key} is an artefact of %s/other, not %s.' % (RID, PACK)),
    'a deposit': (edited(lambda d: (d.pop('derived'), d.update(deposit={'obtained_at': '2026-10-28T00:00:00Z', 'by': 'maintainer', 'publisher_page_url': 'https://example.org/p',
                                                                           'publisher_page_sha256': 'e' * 64, 'licence_text_sha256': 'f' * 64}))),
                  'artefact ATTRIBUTION.md: custody key {key} is a deposit copy of %s, not an artefact of %s.' % (RID, PACK)),
    'a sha256 not its file name': (edited(lambda d: d.update(sha256='e' * 64)), 'artefact ATTRIBUTION.md: key {key} is not mirror/%s/%s/derived-ATTRIBUTION.md; '
                                   'file name {sha}.json does not name the digest %s.' % (RID, 'e' * 64, 'e' * 64)),
}


@pytest.mark.parametrize('case', sorted(FINALISE))
def test_finalise_refuses_an_artefact_and_leaves_the_pack_unchanged(built, case):
    folder, doc, keys = built
    change, sentence = FINALISE[case]
    a = last(doc)
    change(folder, a)
    said, code = unchanged(folder, starter.finalise, folder / 'out', folder / 'custody')
    assert (said, code) == (sentence.format(n=a['bytes'], key=keys['ATTRIBUTION.md'], sha=a['sha256']) + starter.UNCHANGED, 1)


def test_finalise_refuses_a_changed_evidence_json(built):
    folder, _, _ = built
    p = folder / 'out/evidence.json'
    p.write_bytes(p.read_bytes().replace(b'"0.9.0"', b'"0.9.9"'))
    assert unchanged(folder, starter.finalise, folder / 'out', folder / 'custody') == (
        'evidence.json is not the evidence this pack was built from: its SHA-256 differs.' + starter.UNCHANGED, 1)


FIDELITY = 'fidelity/ophiolite-synthetic__two-wells__starter.json'


def fidelity_edit(change):
    def edit(folder):
        p = folder / 'out' / FIDELITY
        if change is None: p.unlink(); return
        if change == 'text': p.write_text('{'); return
        d = json.loads(p.read_text()); change(d); p.write_text(json.dumps(d))
    return edit


EXTRA = {'sha256': 'f' * 64, 'name': 'extra.las', 'result': 'converted', 'output': {'kind': 'wellbore-logs', 'id': 'item-x', 'converter': 'c', 'version': '1'}}
FIDELITY_CASES = {
    'missing': (None, 'fidelity %s: not found in out.' % FIDELITY),
    'not JSON': ('text', 'fidelity %s: not JSON.' % FIDELITY),
    'another record': (lambda d: d.update(record='ophiolite-synthetic/other'), 'fidelity %s: record ophiolite-synthetic/other, the pack is of %s.' % (FIDELITY, RID)),
    'an input with no result': (lambda d: d['inputs'].pop(2), 'fidelity %s: no result for input syn-1-tops.csv.' % FIDELITY),
    'a result for a non-input': (lambda d: d['inputs'].append(EXTRA), 'fidelity %s: input extra.las is not a pack input.' % FIDELITY),
    'an output kind not in contents': (lambda d: d['inputs'][3]['output'].update(kind='seismic-3d'), 'fidelity %s: input syn-1-deviation.csv became seismic-3d, not a contents kind.' % FIDELITY),
}


@pytest.mark.parametrize('case', sorted(FIDELITY_CASES))
def test_finalise_checks_the_fidelity_document(built, case):
    folder, _, _ = built
    change, sentence = FIDELITY_CASES[case]
    fidelity_edit(change)(folder)
    assert unchanged(folder, starter.finalise, folder / 'out', folder / 'custody') == (sentence + starter.UNCHANGED, 1)


def test_finalise_reconciles_each_deposit_with_the_custody_documents_now(built, tmp_path):
    folder, _, _ = built
    tops = {'sha256': sha(TOPS)}
    held = custody_of(folder, tops).read_bytes()
    edited(lambda d: d['licence'].update(name='Another licence'))(folder, tops)
    assert unchanged(folder, starter.finalise, folder / 'out', folder / 'custody') == (
        "input syn-1-tops.csv: its custody document's licence differs from the one this pack was built with." + starter.UNCHANGED, 1)
    custody_of(folder, tops).write_bytes(held)
    tombstone(folder, tops)
    assert unchanged(folder, starter.finalise, folder / 'out', folder / 'custody') == (
        'input syn-1-tops.csv: its custody document is removed: never in a pack.' + starter.UNCHANGED, 1)


def test_finalise_runs_offline_from_the_command_line(built, monkeypatch, capsys):
    folder, doc, keys = built
    monkeypatch.setattr(cli, '_load', lambda: pytest.fail('finalise read the configuration'))
    cli.main(['starter', 'finalise', str(folder / 'out'), '--custody', str(folder / 'custody')])
    assert capsys.readouterr().out == 'Finalised %s: 4 artefact keys written; it stays unpublished.\n' % PACK
    assert [a['key'] for a in json.loads((folder / 'out/starter.json').read_text())['targets'][0]['artefacts']] == [keys[p] for p in ARTEFACTS]
