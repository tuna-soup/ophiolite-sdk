"""E106 C6, gateway lane: a colleague runs a procedure-made result again on their computer from the SDK and the command
line (charter rows 5, 6, 12, 13, 26, 29, 34). The project gives back the version, the inputs with their declarations
and the settings (`procedure-runs/prepare-again`); per output it says whether the new file is the same result (nothing
is published) or a new private result made again from the earlier one. bob made the original on his tops; tina, who
registered depth-shift, runs it again."""
import json
import os

import pytest
try:
    from project_gateway.tests.procedure_world import rows
    from project_gateway.tests.real_credentials import project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import procedures, story
from ophiolite.procedures import NotRun
from test_procedure_publish import bundle, command, enable, published, ran, runs, setting  # noqa: F401 (fixture)

SAME = 'Same result: Shifted chalk, version 1. Nothing was published.'


@pytest.fixture
def original(world, setting, tmp_path):
    """bob's published result and its input, shared with tina (read and reuse)."""
    v1 = enable(setting, tmp_path)
    ran(setting, tmp_path)
    [output] = setting['bob'].procedure_publish(tmp_path / 'out', name='Shifted chalk')['outputs']
    receipt = output['receipt']
    with world.journal.lock, world.journal.db:
        for asset in (receipt['asset_id'], setting['tops']['asset_id']): world.sources.retained_assets.grants_locked(asset, 'bob', ['alice', 'tina'], ['tina'])
    return v1, receipt


def again(setting, tmp_path, receipt, out='again', who='tina', **options):
    return setting[who].procedure_again(receipt['asset_id'], receipt['revision'], tmp_path / out, **options)


def test_the_same_result_publishes_nothing_and_names_the_earlier_one(world, setting, tmp_path, original):
    _, receipt = original
    before = published(world)
    answer = again(setting, tmp_path, receipt)
    [output] = answer['outputs']
    assert (output['outcome'], answer['sentence']) == ('same', SAME)
    assert (output['receipt']['asset_id'], output['receipt']['revision']) == (receipt['asset_id'], receipt['revision'])
    assert output['receipt']['outcome']['earlier'] == {'asset_id': receipt['asset_id'], 'revision': receipt['revision']}
    assert published(world) == before and runs(world) == 2
    assert answer['ran'].startswith('Ran Shift tops by a fixed depth, version 1, on this computer')
    run = json.loads((tmp_path / 'again/run.json').read_text())
    assert run['settings'] == json.loads((tmp_path / 'out/run.json').read_text())['settings']  # the settings came back as recorded


def test_another_version_with_other_values_is_a_new_private_result_made_again_from_the_earlier_one(world, setting, tmp_path, original):
    _, receipt = original
    folder = bundle(tmp_path, 2)
    code = folder / 'procedure.py'
    code.write_text(code.read_text().replace("float(row['md']) + sign * settings['shift']", "float(row['md']) + sign * settings['shift'] + 0.5"))
    setting['alice'].procedure_enable(setting['tina'].procedure_register(folder)['digest'])
    answer = again(setting, tmp_path, receipt, version=2)
    [output] = answer['outputs']
    assert output['outcome'] == 'different' and output['receipt']['asset_id'] != receipt['asset_id']
    assert answer['sentence'] == ('Different result: The values differ: 2 of 8: published Shifted chalk (made again) (Well tops (CSV)) as a new private result, '
                                  'made with Shift tops by a fixed depth version 2 on your computer.')
    assert rows(world, 'SELECT DISTINCT recipient FROM asset_grants WHERE asset_id=?', output['receipt']['asset_id']) == [('tina',)]
    page = setting['tina'].story(output['receipt']['asset_id'], output['receipt']['revision'])
    node = page['nodes'][0]
    assert node['kind'] == 'reported' and node['made_again_from']['asset_id'] == receipt['asset_id']
    words = story.details(node, {})
    assert words[0] == "Made with Shift tops by a fixed depth version 2 (First release) on tina's computer; Ophiolite did not run this calculation."
    assert words[-1] == 'Made again from Shifted chalk, version 1.'


def test_changed_code_with_the_same_values_is_the_same_result_of_a_newer_version(world, setting, tmp_path, original):
    _, receipt = original
    folder = bundle(tmp_path, 2)
    (folder / 'procedure.py').write_text((folder / 'procedure.py').read_text() + '\n# faster\n')
    setting['alice'].procedure_enable(setting['tina'].procedure_register(folder)['digest'])
    [output] = again(setting, tmp_path, receipt, version=2)['outputs']
    assert (output['outcome'], output['sentence']) == ('same-newer', 'Same result, newer procedure version: Shifted chalk, version 1. Nothing was published.')


def test_a_withdrawn_version_refuses_with_its_date_and_runs_nothing(world, setting, tmp_path, original):
    v1, receipt = original
    v2 = setting['tina'].procedure_register(bundle(tmp_path, 2))
    setting['alice'].procedure_enable(v2['digest']); setting['alice'].procedure_withdraw(v2['digest'])
    with pytest.raises(NotRun) as caught: again(setting, tmp_path, receipt, version=2)
    assert caught.value.code == 'withdrawn' and str(caught.value).startswith('Not run: this procedure was withdrawn on ')
    setting['alice'].procedure_withdraw(v1['digest'])  # the version that made it: the project refuses to prepare the run
    with pytest.raises(NotRun) as caught: again(setting, tmp_path, receipt)
    assert (caught.value.code, str(caught.value)) == ('refused', 'You cannot use the procedure version this result was made with.')
    assert not (tmp_path / 'again').exists() and runs(world) == 1


def test_a_result_the_colleague_cannot_read_refuses_in_words_and_runs_nothing(world, setting, tmp_path, original):
    _, receipt = original
    with world.journal.lock, world.journal.db: world.sources.retained_assets.grants_locked(receipt['asset_id'], 'bob', ['alice'], [])  # tina loses the read
    with pytest.raises(NotRun) as caught: again(setting, tmp_path, receipt)
    assert (caught.value.code, str(caught.value)) == ('refused', 'You cannot read this result.')
    assert not (tmp_path / 'again').exists() and runs(world) == 1


def test_a_changed_cached_copy_refuses_and_runs_nothing(world, setting, tmp_path, original):
    v1, receipt = original
    again(setting, tmp_path, receipt, out='warm')
    code = tmp_path / 'cache' / v1['digest'] / 'procedure.py'
    code.write_text(code.read_text() + '\n# changed\n')
    with pytest.raises(NotRun) as caught: again(setting, tmp_path, receipt)
    assert caught.value.code == 'cache-changed' and not (tmp_path / 'again').exists() and runs(world) == 2


def test_the_command_line_runs_again_in_words_and_json_carries_the_outcome(world, setting, tmp_path, original):
    _, receipt = original
    code, text, err = command(setting['tina'], 'again', receipt['asset_id'], '--revision', receipt['revision'], '--output', tmp_path / 'again')
    assert code == 0, err
    assert text.splitlines()[-1] == SAME
    code, text, err = command(setting['tina'], 'again', receipt['asset_id'], '--revision', receipt['revision'], '--output', tmp_path / 'again-2', '--json')
    assert code == 0, err
    [output] = json.loads(text)['outputs']
    assert output['receipt']['outcome']['outcome'] == 'same' and output['receipt']['asset_id'] == receipt['asset_id']


def test_a_publish_of_a_run_made_again_resumes_with_its_earlier_result(world, setting, tmp_path, original, monkeypatch):
    _, receipt = original
    def stop(state): raise KeyboardInterrupt
    monkeypatch.setattr(procedures, 'before_report', stop)
    with pytest.raises(KeyboardInterrupt): again(setting, tmp_path, receipt)
    assert json.loads((tmp_path / 'again/publish.json').read_text())['again_of'] == {'asset_id': receipt['asset_id'], 'revision': receipt['revision']}
    monkeypatch.setattr(procedures, 'before_report', lambda state: None)
    answer = setting['tina'].procedure_publish(tmp_path / 'again')
    assert answer['outputs'][0]['outcome'] == 'same' and runs(world) == 2


def test_an_ordinary_run_again_keeps_its_input_record_and_output_bytes(world, setting, tmp_path, original):
    """E120 s6 t3 (D-19, round 8 rows 2-2 and 4-2): passing the server's wellbore through leaves an ordinary run made
    again as it was. The input record is a frozen literal (its key set exactly; `file` after the run's temporary
    download directory), and the output is the shift's literal bytes (1000.5 and 1200 less 2.5 m), not a second run.
    Mutation: add `wellbore` to run.json's input record → the key set differs → red."""
    _, receipt = original
    again(setting, tmp_path, receipt)
    [used] = json.loads((tmp_path / 'again/run.json').read_text())['inputs']['tops']
    assert sorted(used) == ['asset_id', 'declared', 'file', 'kind', 'revision', 'sha256']
    assert os.path.basename(used['file']) == 'tops-0.csv' and os.path.basename(os.path.dirname(used['file'])).startswith('ophiolite-inputs-')
    assert (used['asset_id'], used['revision'], used['kind'], used['declared']) == \
        (setting['tops']['asset_id'], setting['tops']['revision'], 'well-tops-csv/1', {'depth_unit': 'm', 'depth_basis': 'same-as-log'})
    assert used['sha256'] == 'bccf61bf244a0fc06d3a489d23f581fef9e51eaa3bdd97830e36dd175f285a9f'
    assert (tmp_path / 'again/shifted.csv').read_bytes() == b'name,md\nTop Chalk,998\nBase Chalk,1197.5\n'
