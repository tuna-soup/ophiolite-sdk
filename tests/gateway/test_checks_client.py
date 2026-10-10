"""E96 C6, gateway lane: `ophiolite checks` against the real check routes of an in-process gateway, signed in with
access keys made the way a person makes them. A publish prints the closed refusal sentence with no field path (the
field is in --json), `list --json` has its documented shape, `compare` says how far a file differs, an unknown key gets
the sign-in sentence, and only an administrator changes who may publish."""
import json
import os

import pytest
try:
    from project_gateway import checks as route
    from project_gateway.execution import registry
    from project_gateway.tests import check_files as cf
    from project_gateway.tests.e94_story_world import RELEASE
    from project_gateway.tests.real_credentials import ORIGIN, project  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_checks_adversarial import Held
    from project_gateway.tests.test_checks_compare import las
    from project_gateway.tests.test_checks_publish import world  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential, cli
from ophiolite.errors import OphioliteError, PermissionRefused

PUBLISHER_KEYS = ['at', 'granted_by', 'kind', 'principal']
RECORD_KEYS = ['at', 'command_id', 'differences', 'fixture', 'id', 'interpretation_digest', 'outcome', 'output_digest', 'reason', 'recorded_by',
               'reference', 'request_digest', 'rules_id', 'schema', 'server_output_digest', 'subject', 'tolerance', 'witness']


def sdk(world, person, key=None):
    return Client(ORIGIN, 'p', Credential.bearer(key or world.key(person)), world.c)


def run(client, *argv):
    """(text, payload) of one `ophiolite checks …` verb, or (sentence, --json error document) when it is refused."""
    import contextlib
    import io
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out): payload = cli._checks(cli.parser().parse_args(['checks', *argv]), client)
    except OphioliteError as error:
        return str(error), cli.error_document(error)['error']
    return out.getvalue().strip(), payload


def folder(path, stated, files, request, interpretation, suffix='.las'):
    path.mkdir(parents=True)
    (path / 'check.json').write_text(json.dumps(stated))
    for name, value in files.items(): (path / (name + ('.json' if name == 'output' else suffix))).write_bytes(cf.decoded_b64(value))
    (path / 'request.json').write_text(json.dumps(request))
    if interpretation is not None: (path / 'interpretation.json').write_text(json.dumps(interpretation))
    return path


def shale(tmp_path, name='shale', **record):
    return folder(tmp_path / name, *cf.shale(RELEASE, registry.get('ophiolite.shale-volume', '1').script_digest, **record))


def test_publish_is_checked_by_the_server_and_a_retry_answers_the_same_record(world, tmp_path):
    alice = sdk(world, 'alice')
    text, payload = run(alice, 'publish', str(shale(tmp_path)))
    assert text == 'Published 1 check for Ophiolite 2026.10.60: 1 checked by the server.'
    again = run(alice, 'publish', str(tmp_path / 'shale'))[1]
    assert [r['id'] for r in again['published']] == [r['id'] for r in payload['published']] and payload['published'][0]['witness'] == 'server'


def test_a_refused_publish_says_its_sentence_and_names_the_field_only_in_json(world, tmp_path):
    alice = sdk(world, 'alice')
    wrong = shale(tmp_path)
    (wrong / 'reference.las').write_bytes((wrong / 'reference.las').read_bytes() + b'\n')
    text, error = run(alice, 'publish', str(wrong))
    assert text == 'Not published: the reference file does not match the recorded file.'
    assert error['field'] == 'reference.digest' and error['code'] == 'check-refused' and 'reference.digest' not in text
    other = shale(tmp_path, 'other', subject={'kind': 'implementation', 'id': 'ophiolite.shale-volume', 'version': '1',
                                               'script_sha256': registry.get('ophiolite.shale-volume', '1').script_digest,
                                               'release_number': '2026.10.55', 'release_digest': 'b' * 64})
    text, error = run(alice, 'publish', str(other))
    assert text == 'Not published: the check was made for release 2026.10.55, not the release this server runs.' and error['field'] == 'release.digest'


def test_timeout_and_capacity_say_nothing_was_saved_and_try_again(world, tmp_path):
    world.app.state.checks.maps.runner = held = Held()
    grid = folder(tmp_path / 'grid', *cf.scalar(RELEASE, registry.get('scalar-offset', '1').script_digest), suffix='.asc')
    alice = sdk(world, 'alice')
    text, error = run(alice, 'publish', str(grid))
    assert (text, error['field']) == ('Not published: the server did not finish the check in time. Nothing was saved.', 'timeout')
    text, error = run(alice, 'publish', str(grid))
    assert (text, error['field']) == ('Not published: the server is busy. Try again.', 'capacity')
    held.done.set()


def test_list_json_has_its_documented_shape_and_the_words_say_checked_against(world, tmp_path):
    alice = sdk(world, 'alice')
    run(alice, 'publish', str(shale(tmp_path)))
    text, answer = run(alice, 'list', '--implementation', 'ophiolite.shale-volume', '--version', '1', '--json')
    assert sorted(answer) == ['groups', 'records'] and [sorted(r) for r in answer['records']] == [RECORD_KEYS]
    assert [sorted(g) for g in answer['groups']] == [['disagreement', 'earlier', 'key', 'latest']] and answer['groups'][0]['earlier'] == []
    words = run(alice, 'list', '--implementation', 'ophiolite.shale-volume', '--version', '1')[0].splitlines()
    assert words[0].startswith('Checked against an independent calculation (version 1) on Literal gamma ray, ') and words[0].endswith(': passed.')
    assert words[1:] == ['Exactly equal.', 'This shows these numbers on this data only.']


def test_compare_says_how_far_a_file_differs_and_that_it_is_kept_on_this_result_only(world, tmp_path):
    result = world.upload()
    mine = tmp_path / 'mine.las'; mine.write_bytes(las(gr=('0', '-999.25', '30.0004')))
    text, found = run(sdk(world, 'alice'), 'compare', '--asset', result['asset_id'], '--revision', result['revision'], '--file', str(mine))
    assert text.splitlines() == ['Differs by at most 0.0004 gAPI, at 1 of 3 depths.', 'Saved on this result only.',
                                 'This is not a check of the method that made this result.']
    assert found['witness'] == 'personal' and found['differences']['count'] == 1


def test_an_unknown_key_gets_the_sign_in_sentence_not_a_check_sentence(world, tmp_path):
    with pytest.raises(PermissionRefused) as refused:
        sdk(world, 'alice', key='oph_key_' + 'x' * 40).check_publish(shale(tmp_path))
    assert refused.value.stage == 'credential-refused' and 'field' not in refused.value.details
    assert not str(refused.value).startswith(('Published', 'Publishing checks', 'Not published'))


def test_only_an_administrator_changes_who_may_publish(world, tmp_path):
    alice, bob = sdk(world, 'alice'), sdk(world, 'bob')
    check = shale(tmp_path)
    assert run(bob, 'publish', str(check))[0] == 'Publishing checks needs permission. Ask a project administrator.'
    for verb in (['list'], ['add', 'bob'], ['remove', 'bob']):
        assert run(bob, 'publishers', *verb)[0] == 'Only a project administrator can change who may publish checks.', verb
    assert run(alice, 'publishers', 'add', 'bob')[0] == 'Bob can publish checks for this project.'
    text, listed = run(alice, 'publishers', 'list', '--json')
    assert [sorted(e) for e in listed['publishers']] == [PUBLISHER_KEYS]
    assert [(e['principal'], e['kind'], e['granted_by']) for e in listed['publishers']] == [('bob', 'person', 'alice')]
    assert run(bob, 'publish', str(check))[0] == 'Published 1 check for Ophiolite 2026.10.60: 1 checked by the server.'
    assert run(alice, 'publishers', 'remove', 'bob')[0] == 'Bob can no longer publish checks for this project.'
    assert run(bob, 'publish', str(check))[0] == 'Publishing checks needs permission. Ask a project administrator.'
    assert run(alice, 'publishers', 'list')[0] == 'Only the project administrators can publish checks for this project.'
    assert route.SENTENCES['permission'] not in run(bob, 'publish', str(check))[0]
