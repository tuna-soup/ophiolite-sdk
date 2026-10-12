"""E90 C6: `client.new_data_defaults()`, `set_new_data_defaults`, `audience`, `set_audience`, the upload's use of the
project's settings and `ophiolite new-data` / `ophiolite audience`, over answers in the Platform's documented shapes
(`context/new-data`, `las-uploads/audience`, `audience-preview`, `audience-save`, `upload-runs/check`). A snapshot is
sent back as it was reviewed: a stale one is refused in the deployment's sentence and never refetched."""
import json
from pathlib import Path

import pytest

from ophiolite import cli, new_data
from ophiolite.errors import IntegrityConflict, PermissionRefused, Refused
from ophiolite.upload_runs import NO_ATTRIBUTION, NOT_PROJECT, Report, UploadRuns, open_folder

NOT_ADMINISTRATOR = "Only a project administrator can change what new files start with. Ask one of this project's administrators."
STALE = 'These settings changed after you opened them. Reload to see the current ones, then make your change again.'
REASON = 'Say why you are making this narrower. Your reason is kept with the change.'
SETTINGS = {'visible_to': 'me', 'depth_reference': 'KB', 'coordinate_system': 'EPSG:28992', 'unit_system': 'ft', 'attribution': 'ACME 2026'}
READ = {'revision': 3, 'settings': SETTINGS, 'legacy': False, 'administrator': True, 'custom_coordinate_system': False}
SNAP = {'asset_id': 'U', 'state': 'people', 'people': [{'id': 'bob', 'can_see': True, 'legacy': False, 'build_on': False},
                                                      {'id': 'carol', 'can_see': False, 'legacy': True, 'build_on': False}],
        'policy_generation': 4, 'grants_generation': 7}
ERRORS = {403: PermissionRefused, 409: IntegrityConflict, 400: Refused}
TOPS = b'name,md,tvd\nNorth Sea Group,412.5,410.0\n'


def refusal(status, code, sentence):
    return {'status': status, 'body': {'code': code, 'error': sentence}}


class Fake:
    """The client's transports answering `area/operation` (a list is answered in order); a refusal is raised as the
    transport raises it: generic words, the deployment's sentence as server_message."""
    project = 'p'

    def __init__(self, **answers):
        self.answers, self.sent = {k: list(v) if isinstance(v, list) else v for k, v in answers.items()}, []

    def _answer(self, key, body):
        self.sent.append((key, body))
        answer = self.answers[key]
        if isinstance(answer, list): answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, dict) and 'status' in answer and 'body' in answer:
            raise ERRORS[answer['status']]('generic transport words', status=answer['status'], code=answer['body']['code'], server_message=answer['body']['error'])
        return answer

    def _post(self, area, operation, body, **options):
        return self._answer(area + '/' + operation, body)

    def _post_bytes(self, area, operation, raw, *, extra_headers, **options):
        import base64
        return self._answer(area + '/' + operation, {'upload': json.loads(base64.b64decode(extra_headers['X-Ophiolite-Upload'])), 'bytes': len(raw)})

    def keys(self): return [k for k, _ in self.sent]


def raised(call):
    with pytest.raises(Exception) as error: call()
    return error.value


# --- the settings --------------------------------------------------------------------------------------------------

def test_the_settings_read_as_a_snapshot_with_their_revision():
    snap = new_data.defaults(Fake(**{'context/new-data': READ}))
    assert snap == {**SETTINGS, 'revision': 3, 'legacy': False, 'administrator': True}
    assert new_data.lines(snap) == ['Who can see new files: Only the person who adds it', 'Depth reference for wells: Kelly bushing',
                                    'Coordinate system: EPSG:28992', 'Unit system: Feet', 'Source attribution: ACME 2026', 'Settings revision 3']


def test_a_save_sends_the_reviewed_revision_and_the_whole_settings():
    fake = Fake(**{'context/new-data-save': {**READ, 'revision': 4, 'settings': {**SETTINGS, 'visible_to': 'project'}}})
    saved = new_data.set_defaults(fake, {**SETTINGS, 'revision': 3}, visible_to='project')
    assert fake.sent == [('context/new-data-save', {'expected_revision': 3, 'settings': {**SETTINGS, 'visible_to': 'project'}})]
    assert (saved['revision'], saved['visible_to']) == (4, 'project')


def test_a_member_who_does_not_administer_is_refused_in_the_deployments_words():
    fake = Fake(**{'context/new-data-save': refusal(403, 'PERMISSION_DENIED', NOT_ADMINISTRATOR)})
    error = raised(lambda: new_data.set_defaults(fake, {**SETTINGS, 'revision': 3}, unit_system='m'))
    assert isinstance(error, PermissionRefused) and str(error) == NOT_ADMINISTRATOR  # mutation: the transport's generic words


def test_a_stale_snapshot_is_refused_and_never_refetched():
    fake = Fake(**{'context/new-data-save': refusal(409, 'settings-changed', STALE), 'context/new-data': READ})
    error = raised(lambda: new_data.set_defaults(fake, {**SETTINGS, 'revision': 2}, unit_system='m'))
    assert isinstance(error, IntegrityConflict) and str(error) == STALE
    assert fake.keys() == ['context/new-data-save']  # mutation: a silent refetch and retry would send context/new-data and succeed


def test_an_unknown_setting_is_refused_before_anything_is_sent():
    fake = Fake()
    assert str(raised(lambda: new_data.set_defaults(fake, {**SETTINGS, 'revision': 3}, colour='red'))).startswith('New data has no setting colour')
    assert fake.sent == []


# --- the one control on an original ----------------------------------------------------------------------------------

def test_the_audience_snapshot_keeps_an_earlier_entry_as_legacy():
    snap = new_data.audience(Fake(**{'las-uploads/audience': SNAP}), 'U')
    assert snap['people'] == [{'id': 'bob', 'can_see': True, 'build_on': False}, {'id': 'carol', 'can_see': 'legacy', 'build_on': False}]


def test_set_audience_sends_both_generations_of_the_reviewed_snapshot():
    fake = Fake(**{'las-uploads/audience-save': {**SNAP, 'policy_generation': 5, 'grants_generation': 8, 'replayed': False}})
    snap = new_data.audience(Fake(**{'las-uploads/audience': SNAP}), 'U')
    new_data.save(fake, new_data.change(snap, 'people', ['bob', 'dan'], ['dan']), command_id='c1')
    (key, body), = fake.sent
    assert (key, body['expected_generation'], body['expected_grants_generation']) == ('las-uploads/audience-save', 4, 7)  # mutation: one token only
    assert body['people'] == [{'id': 'bob', 'can_see': True, 'build_on': False}, {'id': 'carol', 'can_see': 'legacy', 'build_on': False},
                              {'id': 'dan', 'can_see': True, 'build_on': True}]


def test_stale_recipients_are_refused_with_the_policy_generation_current():
    fake = Fake(**{'las-uploads/audience-save': refusal(409, 'recipients-changed', 'Recipients changed; reload before saving')})
    error = raised(lambda: new_data.save(fake, new_data.change(new_data._audience_snapshot(SNAP, 'U'), 'me')))
    assert isinstance(error, IntegrityConflict) and str(error) == 'Recipients changed; reload before saving'
    assert [k for k, _ in fake.sent] == ['las-uploads/audience-save']


def test_a_narrower_change_without_a_reason_keeps_the_deployments_sentence():
    fake = Fake(**{'las-uploads/audience-save': refusal(400, 'reason-required', REASON)})
    assert str(raised(lambda: new_data.save(fake, new_data.change(new_data._audience_snapshot(SNAP, 'U'), 'me')))) == REASON


def run_cli(argv, fake):
    args = cli.parser().parse_args(argv)
    return {'new-data': cli._new_data, 'audience': cli._audience}[argv[0]](args, fake)


def test_a_dry_run_says_who_is_told_and_who_loses_access_and_changes_nothing(capsys):
    fake = Fake(**{'las-uploads/audience': SNAP, 'las-uploads/audience-preview': {'told': 0, 'losing': 1, 'narrower': True}})
    run_cli(['audience', '--asset', 'U', '--set', 'me', '--dry-run'], fake)
    assert capsys.readouterr().out.strip() == 'No one will be told. 1 person will lose access.'
    assert fake.keys() == ['las-uploads/audience', 'las-uploads/audience-preview']  # mutation: a dry run that saves


def test_a_one_step_change_applies_the_snapshot_it_previewed(capsys):
    fake = Fake(**{'las-uploads/audience': SNAP, 'las-uploads/audience-preview': {'told': 1, 'losing': 0, 'narrower': False},
                   'las-uploads/audience-save': {**SNAP, 'state': 'project', 'people': [], 'policy_generation': 5, 'grants_generation': 8, 'replayed': False}})
    run_cli(['audience', '--asset', 'U', '--set', 'project'], fake)
    assert capsys.readouterr().out.splitlines() == ['1 person will be told. Saved.', 'Generations: who can see 5, recipients 8.']
    (_, previewed), (_, saved) = fake.sent[1:]
    assert {k: v for k, v in saved.items() if k != 'command_id'} == previewed and (previewed['expected_generation'], previewed['expected_grants_generation']) == (4, 7)


def test_a_narrower_one_step_change_needs_a_reason_before_it_is_saved():
    fake = Fake(**{'las-uploads/audience': SNAP, 'las-uploads/audience-preview': {'told': 0, 'losing': 1, 'narrower': True}})
    assert 'say why with --reason' in str(raised(lambda: run_cli(['audience', '--asset', 'U', '--set', 'me'], fake)))
    assert 'las-uploads/audience-save' not in fake.keys()


def test_new_data_set_saves_once_at_the_revision_just_read(capsys):
    fake = Fake(**{'context/new-data': READ, 'context/new-data-save': {**READ, 'revision': 4, 'settings': {**SETTINGS, 'unit_system': 'm'}}})
    run_cli(['new-data', '--set', 'unit_system=m'], fake)
    assert fake.sent[1] == ('context/new-data-save', {'expected_revision': 3, 'settings': {**SETTINGS, 'unit_system': 'm'}})
    assert 'Unit system: Metres' in capsys.readouterr().out


# --- the upload takes the settings ---------------------------------------------------------------------------------

def folder(tmp_path):
    (tmp_path / 'F').mkdir(exist_ok=True); (tmp_path / 'F' / 'tops.csv').write_bytes(TOPS)
    return open_folder(tmp_path / 'F')


def check_answer(revision=3, offered=('depth_unit',)):
    return {'reads': 'head', 'kind': {'profile': 'well-tops-csv/1', 'label': 'Well tops'}, 'stated': [], 'asks': [], 'proposals': [], 'same_as': None,
            'suggestions': [{'key': k, 'value': 'ft', 'class': 'project-default', 'source': 'Project default, settings revision %d' % revision} for k in offered],
            'refusal': None, 'table': None, 'web_page': False, 'read': None, 'defaults_revision': revision}


def test_an_omitted_audience_and_attribution_are_left_to_the_project_with_its_revision(tmp_path):
    fake = Fake(**{'context/new-data': READ})
    sent = UploadRuns(fake).defaults(folder(tmp_path), None, None, None, False)
    assert sent == {'defaults_revision': 3}  # mutation: the SDK sending the legacy audience [] makes "Only you" a choice, not the default


def test_named_people_and_an_attribution_need_no_settings(tmp_path):
    fake = Fake()
    assert UploadRuns(fake).defaults(folder(tmp_path), 'NLOG', ['bob'], None, False) == {'attribution': 'NLOG', 'audience': ['bob']}
    assert UploadRuns(fake).defaults(folder(tmp_path), 'NLOG', 'me', None, False) == {'attribution': 'NLOG', 'audience': []}
    assert fake.sent == []


def test_everyone_in_the_project_must_be_the_projects_setting(tmp_path):
    fake = Fake(**{'context/new-data': READ})
    assert str(raised(lambda: UploadRuns(fake).defaults(folder(tmp_path), 'NLOG', 'project', None, False))) == NOT_PROJECT
    fake = Fake(**{'context/new-data': {**READ, 'settings': {**SETTINGS, 'visible_to': 'project'}}})
    assert UploadRuns(fake).defaults(folder(tmp_path), 'NLOG', 'project', None, False) == {'attribution': 'NLOG', 'defaults_revision': 3}


def test_no_attribution_given_and_none_in_the_project_is_a_usage_error(tmp_path, capsys, monkeypatch):
    fake = Fake(**{'context/new-data': {**READ, 'settings': {**SETTINGS, 'attribution': ''}}, 'upload-runs/list': {'runs': []}})
    assert str(raised(lambda: UploadRuns(fake).defaults(folder(tmp_path), None, 'me', None, False))) == NO_ATTRIBUTION
    fake.upload_runs = UploadRuns(fake)
    args = cli.parser().parse_args(['upload', str(tmp_path / 'F'), '--rights-confirmed', '--audience', 'me'])
    monkeypatch.setattr(cli, '_layout_upload', lambda args, client: None)
    with pytest.raises(SystemExit) as code: cli._upload(args, fake)
    assert code.value.code == 2 and capsys.readouterr().err.strip() == NO_ATTRIBUTION


def test_a_kept_default_is_sent_as_kept_and_a_typed_value_as_yours(tmp_path):
    fake = Fake(**{'context/new-data': READ, 'upload-runs/check': check_answer()})
    sent = UploadRuns(fake).defaults(folder(tmp_path), 'NLOG', [], {'well-tops-csv/1': {'depth_unit': 'project-default', 'depth_basis': 'same-as-log'}}, False)
    assert sent['files'][0]['decisions'] == {'depth_basis': 'same-as-log'} and sent['files'][0]['suggested'] == ['depth_unit']
    assert sent['defaults_revision'] == 3 and 'context/new-data-save' not in fake.keys()  # nothing writes the settings back
    typed = UploadRuns(Fake()).defaults(folder(tmp_path), 'NLOG', [], {'well-tops-csv/1': {'depth_unit': 'ft'}}, False)
    assert 'files' not in typed and 'defaults_revision' not in typed  # a typed value equal to the default is yours: E55's path, declared


def test_use_project_defaults_keeps_every_offered_default_and_a_missing_one_is_refused(tmp_path):
    fake = Fake(**{'context/new-data': READ, 'upload-runs/check': check_answer()})
    sent = UploadRuns(fake).defaults(folder(tmp_path), 'NLOG', [], None, True)
    assert sent['files'][0]['suggested'] == ['depth_unit'] and sent['files'][0]['decisions'] == {}
    fake = Fake(**{'context/new-data': READ, 'upload-runs/check': check_answer(offered=())})
    assert str(raised(lambda: UploadRuns(fake).defaults(folder(tmp_path), 'NLOG', [], {'well-tops-csv/1': {'depth_unit': 'project-default'}}, False))) == \
        'The project has no default depth_unit for F/tops.csv; give a value instead.'


def test_settings_that_moved_between_the_read_and_the_check_stop_the_upload(tmp_path):
    fake = Fake(**{'context/new-data': READ, 'upload-runs/check': check_answer(revision=4)})
    assert 'changed while this upload was being prepared' in str(raised(lambda: UploadRuns(fake).defaults(folder(tmp_path), 'NLOG', [], None, True)))


def test_the_report_says_what_was_taken_from_the_project():
    view = {'run_id': 'r', 'state': 'closed', 'label': 'Done', 'folder_name': 'F', 'files': 1, 'items': [],
            'counts': {'added': 1, 'already_here': 0, 'needs_decision': 0, 'not_read': 0, 'not_supported': 0, 'cancelled': 0, 'waiting': 0, 'reading': 0},
            'settings': {'attribution': 'ACME 2026', 'well_notes': '', 'audience': [], 'defaults': {'revision': 3, 'accepted_by': 'alice', 'fields': ['attribution', 'audience']}}}
    assert Report(view).text().splitlines()[-1] == 'Project default, accepted by you (settings revision 3): attribution "ACME 2026"; Only you can see it.'
    view['settings']['project_audience'] = 'read'
    assert Report(view).text().endswith('Everyone in this project can see it.')


def test_the_e90_routes_reach_the_deployment_and_nothing_else_of_context_does():
    """Found by the C8 recipe against the in-process gateway: the client refused its own routes ("Unsupported
    application operation.") before sending anything; the fake transport above never asks `operation_path`."""
    from ophiolite.publish import operation_path
    for area, op in (('context', 'new-data'), ('context', 'new-data-save'), ('las-uploads', 'audience'), ('las-uploads', 'audience-preview'),
                     ('las-uploads', 'audience-save')):
        assert operation_path('p', area, op) == '/api/v1/projects/p/%s/%s' % (area, op)
    with pytest.raises(Refused): operation_path('p', 'context', 'save')
    with pytest.raises(Refused): operation_path('p', 'las-uploads', 'audience-delete')


def test_naming_people_on_an_only_me_original_chooses_people():
    """Found by the C8 recipe: giving a colleague access again after "Only me" kept the state 'me' and sent nobody."""
    snap = new_data._audience_snapshot({**SNAP, 'state': 'me', 'people': []}, 'U')
    body = new_data.change(snap, people=['bob'], build_on=['bob'])
    assert (body['state'], body['people']) == ('people', [{'id': 'bob', 'can_see': True, 'build_on': True}])
    assert new_data.change(snap)['state'] == 'me' and new_data.change(snap, state='project')['state'] == 'project'
