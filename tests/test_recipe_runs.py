"""E112 s2 (C1): a recipe runs the residual report again one journaled step at a time and resumes.

Offline. The project is a fake client with the four calls a recipe makes (`procedure_publish`, `outcome_states`,
`deliver`, `result_version`); `residuals.run` is replaced by a fake that writes a run folder as `procedures.run` does.
The fake `deliver` keeps the real signature (checked below against `ProcedureClient.deliver`) and writes the E109
records the real SDK writes (`deliveries/<id>/attempt.json`, renamed `set-aside.json`), so the step's recovery reads
them through the real `procedures.delivery_records` (round 6, 6-C3). Each test names the mutation it catches."""
import hashlib
import inspect
import json
import sys
import uuid
from pathlib import Path

import pytest

from ophiolite import procedures, recipe_runs, residuals
from ophiolite.procedures import NotRun

SET, GRID, SET2 = '@a-set:3', '@a-grid:1', '@a-set:4'
IDENTITY = {'kind': 'delegate', 'fingerprint': 'f' * 16}
RECIPE = {
    'schema': 'ophiolite.recipe/1', 'name': 'Residual report again',
    'inputs': {'selection': {'type': 'item'}, 'surface': {'type': 'item'}, 'team_db': {'type': 'file'}},
    'steps': [
        {'id': 'run', 'step': 'residuals', 'with': {'procedure': 'residual-at-wells', 'version': 2, 'selection': {'input': 'selection'},
                                                     'surface': {'input': 'surface'}, 'formation': 'DCC'}},
        {'id': 'publish', 'step': 'publish', 'with': {'run': {'from': 'run'}, 'name': 'Groningen residuals at DCC', 'for': 'Residuals within 5 m'}},
        {'id': 'states', 'step': 'states', 'with': {'result': {'from': 'publish', 'role': 'residuals'}}},
        {'id': 'send', 'step': 'deliver', 'with': {'procedure': 'residuals-to-team-database', 'item': {'from': 'publish', 'role': 'residuals'},
                                                    'as': 'Residuals within 5 m', 'systems': {'db': {'input': 'team_db'}}}},
    ]}


class Killed(BaseException):
    """The process ends here (SIGKILL in the gateway journey); never classified, the journal stays as it was."""


class Project:
    """The four calls, counted; `plan` holds what each later call does."""

    url, project = 'http://project.test', 'p1'

    def __init__(self):
        self.calls, self.plan, self.published, self.delivered = [], {}, 0, []

    def _next(self, kind):
        steps = self.plan.get(kind) or []
        return steps.pop(0) if steps else 'ok'

    def result_version(self, text):
        self.calls.append(('result_version', text))
        asset, revision = text[1:].split(':')
        return asset, revision

    def procedure_publish(self, folder, *, name=None, again_of=None, for_outcome=None):
        self.calls.append(('publish', str(folder)))
        how, state = self._next('publish'), Path(folder) / 'publish.json'
        if how == 'refused-before': raise NotRun('not-a-run')
        if not state.exists(): state.write_text(json.dumps({'command_id': 'run-' + uuid.uuid4().hex}))
        if how == 'refused-after': raise NotRun('x', sentence='Not published: the project refused the report.')
        if how == 'kill': raise Killed()
        saved = json.loads(state.read_text())
        if 'run_id' not in saved:
            self.published += 1
            state.write_text(json.dumps({**saved, 'run_id': 'r%d' % self.published}))
        return {'sentence': 'Published Groningen residuals at DCC.', 'run': {}, 'outputs': [
            {'role': 'residuals', 'receipt': {'asset_id': 'a-res', 'revision': str(self.published)}}]}

    def outcome_states(self, asset_id, revision):
        self.calls.append(('states', asset_id, revision))
        return {'outcomes': [{'label': 'Residuals within 5 m', 'version': 1, 'state': 'accepted', 'line': 'Accepted.',
                              'earlier_publications': [], 'earlier_versions': []}]}

    def deliver(self, name, *, systems=None, items=(), settings=None, work='.ophiolite-held', wait=0, prompt=None, yes=False, cache=None,
                version=None, set_aside=False, as_=None):
        self.calls.append(('deliver', str(work), tuple(items), set_aside))
        how, work = self._next('deliver'), Path(work)
        if how == 'requires': raise NotRun('x', sentence='Not run: psycopg is not installed.')
        held = procedures.delivery_records(work, name)
        if held['pending']:
            attempt = held['pending'][0]
            folder = work / 'deliveries' / attempt['delivery_id']
        else:
            attempt = {'delivery_id': str(uuid.uuid4()), 'procedure': {'name': name, 'label': 'Residuals to team database'},
                       'destination': 'Team database', 'result': None, 'reported': False, 'finished': False}
            folder = work / 'deliveries' / attempt['delivery_id']
            folder.mkdir(parents=True)
            self.delivered.append(attempt['delivery_id'])
        if set_aside:
            attempt.update(result={'state': 'unknown', 'items': 0}, reported=True, set_aside=True)
            (folder / 'attempt.json').write_text(json.dumps(attempt))
            (folder / 'attempt.json').rename(folder / 'set-aside.json')
            if how == 'kill': raise Killed()
            return {'sentence': 'Set aside.', 'delivery_id': attempt['delivery_id'], 'state': 'unknown', 'items': 0, 'reported': True,
                    'destination': 'Team database', 'folder': str(folder)}
        state = {'ok': 'confirmed', 'kill': 'confirmed', 'unreported': 'confirmed', 'unknown': 'unknown', 'not-sent': 'not-sent'}[how]
        reported = how != 'unreported'
        attempt.update(result={'state': state, 'items': 7 if state == 'confirmed' else 0}, reported=reported, finished=reported and state != 'unknown')
        (folder / 'attempt.json').write_text(json.dumps(attempt))
        if how == 'kill': raise Killed()
        return {'sentence': procedures.delivery_words(attempt), 'delivery_id': attempt['delivery_id'], 'state': state, 'items': attempt['result']['items'],
                'reported': reported, 'destination': 'Team database', 'folder': str(folder)}


@pytest.fixture
def world(tmp_path, monkeypatch):
    project = Project()
    project.residual_plan, project.residual_seen = [], []

    def run(client, name, destination, selection, surface, formation, *, display_unit='m', version=None, yes=False, prompt=None):
        journal = json.loads((destination.parent.parent.parent.parent / 'journal.json').read_text())
        project.residual_seen.append({'journal_state': journal['steps'][0]['state'], 'destination': destination, 'selection': selection, 'yes': yes})
        how = project.residual_plan.pop(0) if project.residual_plan else 'ok'
        if how == 'untrusted': raise NotRun('x', sentence='Not run: you have not trusted version 2 of Residual at wells; run it with --yes.')
        assert not destination.exists() and destination.parent.is_dir()  # O4: a new folder whose parent exists
        destination.mkdir()
        (destination / 'residuals.csv').write_text('well,residual\nW1,1.5\n')
        record = {'procedure': {'digest': 'd' * 64}, 'outputs': {'residuals': {'file': 'residuals.csv', 'sha256': 'e' * 64}}}
        (destination / 'run.json').write_text(json.dumps(record))
        if how == 'kill': raise Killed()
        return {'sentence': 'Ran Residual at wells, version 2, on this computer.', 'destination': str(destination), 'run': record}

    monkeypatch.setattr(residuals, 'run', run)
    monkeypatch.setattr(recipe_runs, '_principal', lambda client: {'url': client.url, 'project': client.project, 'identity': project.identity})
    monkeypatch.setattr(recipe_runs, '_windows', lambda: False)
    project.identity = dict(IDENTITY)
    recipe, db = tmp_path / 'recipe.json', tmp_path / 'team-db.json'
    recipe.write_text(json.dumps(RECIPE))
    db.write_text('{"dsn": "postgresql://team"}')
    project.tmp, project.recipe, project.db, project.work = tmp_path, recipe, db, tmp_path / 'again-2'
    return project


def go(w, recipe=None, **kw):
    inputs = kw.pop('inputs', None) or {'selection': SET, 'surface': GRID, 'team_db': str(w.db)}
    return recipe_runs.run(w, recipe or w.recipe, w.work, inputs, **kw)


def journal(w):
    return json.loads((w.work / 'journal.json').read_text())


def states(w):
    return [(s['id'], s['state'], s['attempt']) for s in journal(w)['steps']]


def kinds(w):
    return [c[0] for c in w.calls if c[0] != 'result_version']


# ---------------------------------------------------------------- the recipe (one validation path, 6-P3)

def bad(change):
    doc = json.loads(json.dumps(RECIPE))
    change(doc)
    return doc


def with_(n, **fields):
    return lambda d: d['steps'][n]['with'].update(fields)


INVALID = [  # (case, change, where, words in the sentence)
    ('duplicate id', lambda d: d['steps'][1].update(id='run'), '/steps/1/id', 'two steps are called run'),
    ('from itself', with_(1, run={'from': 'publish'}), '/steps/1/with/run', 'not an earlier step'),
    ('from a later step', with_(2, result={'from': 'send', 'role': 'residuals'}), '/steps/2/with/result', 'not an earlier step'),
    ('from a states step', lambda d: d['steps'][3]['with'].update(item={'from': 'states', 'role': 'residuals'}), '/steps/3/with/item',
     'makes nothing a later step can use'),
    ('from a missing id', with_(1, run={'from': 'nowhere'}), '/steps/1/with/run', 'not an earlier step'),
    ('from the wrong kind', with_(2, result={'from': 'run', 'role': 'residuals'}), '/steps/2/with/result', 'not a publish step'),
    ('unknown input', with_(0, selection={'input': 'wells'}), '/steps/0/with/selection', 'does not declare'),
    ('input of the wrong type', with_(0, selection={'input': 'team_db'}), '/steps/0/with/selection', 'is a file, not a item'),
    ('a secret three levels down', with_(3, settings={'note': 'x'}, systems={'db': {'input': 'team_db', 'nested': {'password': 'x'}}}),
     '/steps/3/with/systems/db/nested/password', 'names a secret'),
    ('root extra key', lambda d: d.update(owner='me'), '/owner', 'no such field'),
    ('step extra key', lambda d: d['steps'][0].update(note='x'), '/steps/0', 'exactly'),
    ('unknown step', lambda d: d['steps'][0].update(step='upload'), '/steps/0/step', 'a step is one of'),
    ('a with key of another kind', with_(0, run={'from': 'run'}), '/steps/0/with/run', 'a residuals step takes'),
    ('version not a whole number', with_(0, version=True), '/steps/0/with/version', 'whole number'),
    ('name of 81 characters', lambda d: d.update(name='n' * 81), '/name', '1 to 80'),
    ('17 inputs', lambda d: d['inputs'].update({'x%d' % i: {'type': 'file'} for i in range(14)}), '/inputs', '1 to 16'),
    ('17 steps', lambda d: d['steps'].extend({'id': 's%d' % i, 'step': 'states', 'with': {'result': {'from': 'publish', 'role': 'r'}}} for i in range(13)),
     '/steps', '1 to 16'),
    ('missing formation', lambda d: d['steps'][0]['with'].pop('formation'), '/steps/0/with/formation', 'missing'),
    ('bad display unit', with_(0, display_unit='km'), '/steps/0/with/display_unit', 'm or ft'),
]
STRUCTURAL = {'root extra key', 'step extra key', 'unknown step', 'a with key of another kind', 'version not a whole number', 'name of 81 characters',
              '17 inputs', '17 steps', 'missing formation', 'bad display unit'}  # what the schema can say; references are code only


@pytest.mark.parametrize('case,change,where,words', INVALID, ids=[c[0] for c in INVALID])
def test_an_invalid_recipe_is_refused_at_its_place_with_its_reason_and_without_jsonschema(case, change, where, words, monkeypatch, tmp_path):
    # mutation: the earlier-step check removed from _reference -> 'from itself' and 'from a later step' pass -> red
    monkeypatch.setitem(sys.modules, 'jsonschema', None)  # 6-C5: the one validation path needs no optional dependency
    path = tmp_path / 'r.json'
    path.write_text(json.dumps(bad(change)))
    with pytest.raises(NotRun) as refused:
        recipe_runs.load(path)
    assert refused.value.code == 'recipe-invalid' and refused.value.field == where and words in str(refused.value), str(refused.value)
    assert str(refused.value).startswith('Not run: the recipe is not valid at ')
    assert sorted(p.name for p in tmp_path.iterdir()) == ['r.json']  # nothing written


def test_the_sample_recipe_is_valid():
    assert recipe_runs.check(json.loads(json.dumps(RECIPE))) == RECIPE


def test_the_published_schemas_agree_with_the_code_on_the_corpus():
    # 6-P3 parity: mutation `additionalProperties: true` at a step in recipe-v1.schema.json -> 'step extra key' valid -> red
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((recipe_runs.SCHEMAS / 'recipe-v1.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    assert not list(validator.iter_errors(RECIPE))
    for case, change, _, _ in INVALID:
        if case in STRUCTURAL: assert list(validator.iter_errors(bad(change))), case


def test_a_written_journal_matches_its_published_schema(world):
    jsonschema = pytest.importorskip('jsonschema')
    go(world)
    schema = json.loads((recipe_runs.SCHEMAS / 'recipe-journal-v1.schema.json').read_text())
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors(journal(world)))


def test_an_unreadable_recipe_is_refused(tmp_path):
    (tmp_path / 'r.json').write_text('{not json')
    with pytest.raises(NotRun) as refused:
        recipe_runs.load(tmp_path / 'r.json')
    assert refused.value.code == 'recipe-unreadable'


# ---------------------------------------------------------------- a whole run, and the order of things

def test_a_recipe_runs_its_four_steps_in_order_and_records_each(world):
    said = go(world)
    assert said['state'] == 'finished' and said['sentence'] == 'Finished: all 4 steps of "Residual report again".'
    assert kinds(world) == ['publish', 'states', 'deliver'] and len(world.residual_seen) == 1
    j = journal(world)
    assert [(s['id'], s['state'], s['attempt'], s['folder']) for s in j['steps']] == [
        ('run', 'finished', 1, 'steps/1-run/a1'), ('publish', 'finished', 1, 'steps/2-publish/a1'),
        ('states', 'finished', 1, 'steps/3-states/a1'), ('send', 'finished', 1, 'steps/4-send/a1')]
    assert j['bindings']['selection'] == {'type': 'item', 'text': SET, 'asset_id': 'a-set', 'revision': '3'}
    assert j['bindings']['team_db']['sha256'] == hashlib.sha256(world.db.read_bytes()).hexdigest()
    assert j['steps'][1]['result'] == {'run_id': 'r1', 'outputs': {'residuals': {'asset_id': 'a-res', 'revision': '1'}}}
    assert j['steps'][2]['result'] == {'outcomes': [{'label': 'Residuals within 5 m', 'version': 1, 'state': 'accepted'}]}
    assert ('deliver', str(world.work / 'steps/4-send/a1'), ('@a-res:1',), False) in world.calls  # 2-R4: the receipt, never a name
    assert j['steps'][3]['result']['state'] == 'confirmed' and j['steps'][3]['result']['reported'] is True
    assert world.residual_seen[0]['selection'] == SET  # the bound @ASSET:REVISION


def test_the_step_is_recorded_started_before_it_is_entered(world):
    # 1-M2. mutation: the `started` save moved after the step call -> the fake sees `waiting` -> red
    go(world)
    assert world.residual_seen[0]['journal_state'] == 'started'


def test_a_crash_inside_a_step_leaves_it_started_and_the_same_attempt_runs_again(world):
    world.residual_plan = ['kill']
    with pytest.raises(Killed):
        go(world)
    assert states(world)[0] == ('run', 'started', 1)
    assert go(world)['state'] == 'finished'
    assert len(world.residual_seen) == 1 and states(world)[0] == ('run', 'finished', 1)  # the finished run folder adopted, not run again


def test_a_new_work_folder_binds_a_new_selection_version(world):
    # 6-C6 at unit level: a run again for another well-set version is a new folder with its own bindings
    go(world)
    world.work = world.tmp / 'again-3'
    go(world, inputs={'selection': SET2, 'surface': GRID, 'team_db': str(world.db)})
    assert journal(world)['bindings']['selection']['revision'] == '4' and world.residual_seen[-1]['selection'] == SET2


# ---------------------------------------------------------------- failed, stopped (2-D2, S2-D1)

def test_an_untrusted_version_without_yes_fails_its_step_with_no_effect_and_attempt_two_runs_in_a_new_folder(world):
    # mutation: an uncertain outcome classed `failed` (or `failed` not raising the attempt) -> attempt/folder differ -> red
    world.residual_plan = ['untrusted']
    said = go(world)
    assert said['state'] == 'failed' and kinds(world) == [] and world.residual_seen[0]['yes'] is False
    assert said['sentence'] == ('Stopped at step 1 of 4 (run): Not run: you have not trusted version 2 of Residual at wells; run it with --yes. '
                                'Run the same command again to continue.')
    assert [s['state'] for s in journal(world)['steps'][1:]] == ['waiting'] * 3
    go(world, yes=True)
    assert journal(world)['steps'][0]['folder'] == 'steps/1-run/a2' and world.residual_seen[1]['yes'] is True


def test_a_publish_refused_before_its_record_fails_and_after_its_record_stops(world):
    # 6-F3: the journal itself is the oracle. mutation: _effects for publish returns 'none' -> 'refused-after' gives
    # attempt 2 in a2 -> red
    world.plan['publish'] = ['refused-before']
    assert go(world)['state'] == 'failed' and states(world)[1] == ('publish', 'failed', 1)
    world.plan['publish'] = ['refused-after']
    assert go(world)['state'] == 'stopped'
    j = journal(world)
    assert states(world)[1] == ('publish', 'stopped', 2) and j['steps'][1]['folder'] == 'steps/2-publish/a2'
    handle = (world.work / j['steps'][0]['result']['run'] / 'publish.json').read_text()
    assert go(world)['state'] == 'finished'
    assert states(world)[1] == ('publish', 'finished', 2) and journal(world)['steps'][1]['folder'] == 'steps/2-publish/a2'
    assert json.loads((world.work / j['steps'][0]['result']['run'] / 'publish.json').read_text())['command_id'] == json.loads(handle)['command_id']
    assert world.published == 1


def test_a_missing_requirement_fails_the_delivery_before_any_record(world):
    world.plan['deliver'] = ['requires']
    said = go(world)
    assert said['state'] == 'failed' and 'psycopg is not installed' in said['sentence']
    assert procedures.delivery_records(world.work / 'steps/4-send/a1', 'residuals-to-team-database') == {
        'finished': [], 'pending': [], 'set_aside': [], 'intents': []}


# ---------------------------------------------------------------- deliveries: the folder's records decide (6-F1, 6-D2)

def test_a_kill_after_the_delivery_finished_record_resumes_without_a_second_delivery(world):
    # 6-C1. mutation: the finished-record branch removed from _deliver -> deliver called again -> two ids -> red
    world.plan['deliver'] = ['kill']
    with pytest.raises(Killed):
        go(world)
    assert states(world)[3] == ('send', 'started', 1)
    assert go(world)['state'] == 'finished'
    assert len(world.delivered) == 1 and kinds(world).count('deliver') == 1
    assert journal(world)['steps'][3]['result']['delivery_id'] == world.delivered[0]


def test_a_kill_after_set_aside_resumes_as_set_aside_without_a_delivery_or_a_refusal(world):
    # 6-C2. mutation: the set-aside branch removed -> a second delivery -> red
    world.plan['deliver'] = ['unknown']
    assert go(world)['state'] == 'unknown'
    world.plan['deliver'] = ['kill']
    with pytest.raises(Killed):
        go(world, set_aside='send')
    said = go(world)
    assert said['state'] == 'finished' and states(world)[3] == ('send', 'set_aside', 1) and len(world.delivered) == 1


def test_a_confirmed_delivery_not_yet_recorded_stops_and_is_reported_again_in_the_same_folder(world):
    # 6-D2. mutation: confirmed without `reported` mapped to finished -> the first run finishes -> red
    world.plan['deliver'] = ['unreported']
    said = go(world)
    assert said['state'] == 'stopped' and states(world)[3] == ('send', 'stopped', 1)
    assert journal(world)['steps'][3]['result']['reported'] is False
    assert go(world)['state'] == 'finished'
    assert len(world.delivered) == 1 and journal(world)['steps'][3]['result']['reported'] is True


def test_an_unknown_delivery_is_asked_again_in_its_folder_and_a_reported_not_sent_is_a_new_attempt(world):
    # 1-M4, 6-D3. mutation: `unknown` treated as `failed` -> the second run delivers in a2 -> red
    world.plan['deliver'] = ['unknown']
    said = go(world)
    assert said['state'] == 'unknown' and said['sentence'].endswith('or set it aside with --set-aside send.')
    world.plan['deliver'] = ['not-sent']
    assert go(world)['state'] == 'failed'
    assert [c[1] for c in world.calls if c[0] == 'deliver'] == [str(world.work / 'steps/4-send/a1')] * 2 and len(world.delivered) == 1
    assert go(world)['state'] == 'finished'
    assert states(world)[3] == ('send', 'finished', 2) and len(world.delivered) == 2
    assert world.calls[-1][1] == str(world.work / 'steps/4-send/a2')


def test_set_aside_records_who_decided_and_the_recipe_continues(world):
    world.plan['deliver'] = ['unknown']
    go(world)
    said = go(world, set_aside='send')
    assert said['state'] == 'finished' and states(world)[3] == ('send', 'set_aside', 1)
    assert journal(world)['steps'][3]['decided_by'] == IDENTITY and world.calls[-1][3] is True


def test_only_an_unknown_delivery_can_be_set_aside(world):
    go(world)
    before = (world.work / 'journal.json').read_bytes()
    for step in ('send', 'publish', 'nowhere'):
        with pytest.raises(NotRun) as refused:
            go(world, set_aside=step)
        assert refused.value.code == 'recipe-set-aside'
    assert (world.work / 'journal.json').read_bytes() == before


def test_the_fake_delivery_keeps_the_real_signature():
    # 6-C3: the fake is not a recorder with an invented argument
    assert inspect.signature(Project.deliver) == inspect.signature(procedures.ProcedureClient.deliver)


# ---------------------------------------------------------------- refused before any step (1-D3, 1-F2)

def refused_without_a_step(w, code, **kw):
    before, calls = (w.work / 'journal.json').read_bytes(), list(w.calls)
    with pytest.raises(NotRun) as refused:
        go(w, **kw)
    assert refused.value.code == code, str(refused.value)
    assert (w.work / 'journal.json').read_bytes() == before and w.calls == calls
    return refused.value


def test_a_resume_with_another_recipe_principal_file_or_item_is_refused_before_any_step(world):
    # mutation: the bindings comparison removed from _same_inputs -> the changed file resumes -> red
    world.plan['publish'] = ['refused-before']
    go(world)
    other = world.tmp / 'other.json'
    other.write_text(json.dumps({**RECIPE, 'name': 'Another'}))
    refused_without_a_step(world, 'recipe-changed', recipe=other)
    refused_without_a_step(world, 'recipe-inputs', inputs={'selection': SET2, 'surface': GRID, 'team_db': str(world.db)})
    world.db.write_text('{"dsn": "postgresql://elsewhere"}')
    refused_without_a_step(world, 'recipe-inputs')
    world.db.write_text('{"dsn": "postgresql://team"}')
    world.identity = {'kind': 'grant', 'user_id': 'u2'}
    refused_without_a_step(world, 'recipe-principal')


def test_a_second_runner_in_the_same_folder_is_refused(world):
    from ophiolite.exchange import folder_lock
    world.plan['publish'] = ['refused-before']
    go(world)
    with folder_lock(world.work / 'journal.lock', timeout=0):
        refused = refused_without_a_step(world, 'recipe-busy')
    assert str(refused) == 'This recipe is already running in this folder.'


def test_a_missing_or_unknown_input_is_refused_before_anything_is_written(world):
    with pytest.raises(NotRun) as refused:
        go(world, inputs={'selection': SET, 'surface': GRID})
    assert refused.value.code == 'recipe-input' and '--input team_db=VALUE' in str(refused.value) and not world.work.exists()


def test_a_recipe_with_a_delivery_is_refused_on_windows_before_its_journal(world, monkeypatch):
    # S2-R10. mutation: the Windows check moved after the journal save -> journal.json exists -> red
    monkeypatch.setattr(recipe_runs, '_windows', lambda: True)
    with pytest.raises(NotRun) as refused:
        go(world)
    assert refused.value.code == 'windows' and not world.work.exists() and world.calls == []


# ---------------------------------------------------------------- show

def test_show_says_where_the_recipe_is_in_words_only(world):
    # 6-V1. mutation: show adds the step folder or the result -> a path or id in the lines -> red
    world.plan['deliver'] = ['unknown']
    go(world)
    lines = recipe_runs.show(world.work)['lines']
    assert lines[:4] == ['Residual report again: 4 steps', '1. run (residuals): Finished', '2. publish (publish): Finished', '3. states (states): Finished']
    assert lines[4].startswith('4. send (deliver): Needs attention: Outcome unknown for Team database')
    text = '\n'.join(lines)
    for technical in ('steps/', 'a-res', 'r1', 'sha256', 'set_aside', 'started', world.delivered[0], str(world.tmp)):
        assert technical not in text, technical
