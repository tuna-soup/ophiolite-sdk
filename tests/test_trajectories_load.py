"""E134 s1 C4 (offline): `trajectories.load` checks a folder by the rules of s1 §7, and `trajectories.export` pages one
export under one `until` and one `reconstruction`, writing nothing at the destination unless the whole folder loads.

The valid folder is the contract's own fixture pair (`manifest.json` and `shape-episode.json`, the manifest set to
`mode: shape`); every broken folder changes one thing and stays well-formed otherwise, so the rule the test names is
the one that refuses it. Each test names the mutation it kills (logs/c4-mutations.txt)."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

import ophiolite
from ophiolite import trajectories
from ophiolite.errors import IntegrityConflict, Refused, VerificationFailed

FIXTURES = Path(ophiolite.__file__).parent / 'contracts/scientific/v1/fixtures/work-episodes'
MANIFEST = {**json.loads((FIXTURES / 'manifest.json').read_text())['manifest'], 'mode': 'shape'}
EPISODES = json.loads((FIXTURES / 'shape-episode.json').read_text())['episodes']
FIRST, SECOND = (e['episode_id'] for e in EPISODES)
PYARROW = importlib.util.find_spec('pyarrow') is not None  # s3: the export also writes episodes.parquet
# splits.json: seed 0 and the default fractions put this id in `validation`
VALIDATION = 'episode-889ebb3e1844e1d1e96dc8b83ba8d60f'


def folder(tmp_path, manifest=None, episodes=None, name='out'):
    path = tmp_path / name
    path.mkdir()
    (path / trajectories.MANIFEST).write_text(json.dumps(MANIFEST if manifest is None else manifest))
    (path / trajectories.EPISODES).write_text(''.join(json.dumps(e) + '\n' for e in (EPISODES if episodes is None else episodes)))
    return path


def refused(tmp_path, manifest=None, episodes=None, name='out'):
    with pytest.raises(VerificationFailed) as caught: trajectories.load(folder(tmp_path, manifest, episodes, name))
    return str(caught.value)


def changed(**counts): return {**MANIFEST, 'counts': {**MANIFEST['counts'], **counts}}


def values_episode():
    """An independently valid values episode: the second episode's first row, with the values fields, no outputs."""
    shape = copy.deepcopy(EPISODES[1])
    row = {**shape['rows'][0], 'inputs': [], 'outputs': [], 'parameters': [], 'checks': [], 'outcomes': [], 'verdicts': [],
           'request': None, 'instruction': None}
    return {**shape, 'episode_id': VALIDATION, 'split': 'validation', 'mode': 'values', 'rows': [row], 'end': row['at'], 'final': []}


def test_a_the_literal_folder_loads(tmp_path):
    manifest, episodes = trajectories.load(folder(tmp_path))
    assert ([e.episode_id for e in episodes], [e.split for e in episodes], manifest.counts.episodes, manifest.until) == (
        ['episode-8663b2a0d4bf49c37fdd2c377f156997', 'episode-bdafda2c048a8f4243248d3aa74009da'], ['train', 'test'], 2, 42)
    assert trajectories.split(0, {'train': 800, 'validation': 100, 'test': 100}, VALIDATION) == 'validation'


def test_a_rule_1_a_manifest_or_a_line_that_is_not_its_contract(tmp_path):
    """Mutation: the episode's validation skipped -> the second case loads -> red."""
    assert refused(tmp_path, manifest={k: v for k, v in MANIFEST.items() if k != 'salt_id'}) == (
        'The folder breaks rule 1: the manifest is not a work-episodes manifest.')
    bad = copy.deepcopy(EPISODES)
    bad[1]['rows'][0]['action_id'] = 'act_not-hex'
    assert refused(tmp_path, episodes=bad, name='line') == (
        'The folder breaks rule 1: an episode is not a work episode (line 2 of episodes.jsonl).')


def test_a_rule_2_counts_that_differ(tmp_path):
    """Mutation: the counts comparison removed -> loads -> red."""
    assert refused(tmp_path, manifest=changed(shape=1, values=1)) == 'The folder breaks rule 2: the counts differ from the episodes.'


def test_a_rule_3_a_values_episode_under_a_shape_manifest(tmp_path):
    """R1-16: the values episode is valid on its own and the counts balance, so only rule 3 can refuse it. Mutation: rule 3
    removed -> loads -> red."""
    assert refused(tmp_path, manifest=changed(episodes=3, values=1), episodes=[*EPISODES, values_episode()]) == (
        'The folder breaks rule 3: a shape export holds a values episode (line 3 of episodes.jsonl).')
    assert len(trajectories.load(folder(tmp_path, {**changed(episodes=3, values=1), 'mode': 'auto'}, [*EPISODES, values_episode()], 'auto'))[1]) == 3


def test_a_rule_4_fractions_that_do_not_sum_to_a_thousand(tmp_path):
    """The splits stay `split/1` of these fractions (the test share is never reached below 900). Mutation: rule 4 removed
    -> loads -> red."""
    assert refused(tmp_path, manifest={**MANIFEST, 'fractions': {'train': 800, 'validation': 100, 'test': 99}}) == (
        'The folder breaks rule 4: the fractions do not sum to 1000.')


@pytest.mark.parametrize('case,text', [
    ('start', 'start and end are not the first and last row'),
    ('reversed', 'rows are not ordered'),
    ('window', 'a gap inside an episode is at or above the window'),
])
def test_a_rule_5_bounds_order_and_gaps(tmp_path, case, text):
    """R2-3, R2-15: equal-time rows with reversed action ids, and a gap equal to the window (600 s, the fixture's gap).
    Mutation: each clause of rule 5 removed in turn -> that case loads -> red."""
    bad, manifest = copy.deepcopy(EPISODES), MANIFEST
    second = bad[1]
    if case == 'start': second['start'] -= 1
    if case == 'reversed':
        at = second['rows'][0]['at']
        second['rows'] = [{**second['rows'][1], 'at': at}, second['rows'][0]]
        second['end'] = at
    if case == 'window': manifest = {**MANIFEST, 'window_seconds': 600}
    assert refused(tmp_path, manifest=manifest, episodes=bad) == 'The folder breaks rule 5: %s (line 2 of episodes.jsonl).' % text
    assert trajectories.load(folder(tmp_path, {**MANIFEST, 'window_seconds': 601}, name='under'))


def test_a_rule_6_a_split_that_is_not_split_1(tmp_path):
    """Mutation: rule 6 removed -> loads -> red."""
    bad = copy.deepcopy(EPISODES)
    bad[0]['split'] = 'validation'
    assert refused(tmp_path, episodes=bad) == 'The folder breaks rule 6: a split is not split/1 (line 1 of episodes.jsonl).'


@pytest.mark.parametrize('case', ['duplicate', 'foreign'])
def test_a_rule_7_final_entries(tmp_path, case):
    """R1-16: a duplicate (ref, outcome_ref), and a final entry naming no output. Mutation: either clause removed -> red."""
    bad = copy.deepcopy(EPISODES)
    first = bad[0]
    if case == 'duplicate': first['final'].append(dict(first['final'][0]))
    else: first['final'][0]['ref'] = 'ref-' + '0' * 32
    assert refused(tmp_path, episodes=bad) == 'The folder breaks rule 7: a final entry is not one of the outputs, once (line 1 of episodes.jsonl).'


def test_a_rule_8_an_episode_id_twice(tmp_path):
    """Mutation: rule 8 removed -> loads -> red."""
    assert refused(tmp_path, manifest=changed(episodes=3, shape=3), episodes=[*EPISODES, EPISODES[0]]) == (
        'The folder breaks rule 8: an episode id repeats (line 3 of episodes.jsonl).')


class Transport:
    """A fake client: answers the given pages in order and keeps every body it was sent."""
    def __init__(self, *pages): self.pages, self.bodies = list(pages), []
    def _post(self, area, operation, body, retry=False):
        assert (area, operation, retry) == ('activity', 'trajectories', True)
        self.bodies.append(body)
        return copy.deepcopy(self.pages.pop(0))


def page(episodes, after, reconstruction='a' * 64, until=42, last=False):
    return {'schema': 'ophiolite.work-episodes-page/1', 'manifest': MANIFEST if last else None, 'episodes': episodes,
            'next': None if last else after, 'until': until, 'reconstruction': reconstruction}


def nothing_left(tmp_path): return sorted(p.name for p in tmp_path.iterdir())


def test_b_two_pages_under_one_until_write_the_folder(tmp_path):
    """The continuation carries the first page's `until`; the folder gets `sdk_version`. Mutation: `until` not sent back
    -> the second body differs -> red."""
    client = Transport(page([EPISODES[0]], 1), page([EPISODES[1]], None, last=True))
    assert trajectories.export(client, tmp_path / 'out', purpose='training', mode='shape') == {'episodes': 2, 'values': 0, 'destination': str(tmp_path / 'out'),
                                                                                              'parquet': PYARROW}
    assert client.bodies == [{'purpose': 'training', 'mode': 'shape', 'seed': 0, 'after': 0, 'limit': 1000},
                             {'purpose': 'training', 'mode': 'shape', 'seed': 0, 'after': 1, 'limit': 1000, 'until': 42}]
    manifest, episodes = trajectories.load(tmp_path / 'out')
    assert (manifest.sdk_version, [e.episode_id for e in episodes], nothing_left(tmp_path)) == (ophiolite.__version__, [FIRST, SECOND], ['out'])
    assert (tmp_path / 'out' / trajectories.EPISODES).read_bytes() == b''.join(trajectories.canonical(e) + b'\n' for e in EPISODES)


@pytest.mark.parametrize('second,error,text', [
    (page([EPISODES[1]], None, last=True, until=43), VerificationFailed, 'The server answered another boundary while exporting; export again.'),
    (page([EPISODES[1]], 1), VerificationFailed, 'The server did not advance the export; export again.'),
    (page([EPISODES[1]], None, reconstruction='b' * 64, last=True), IntegrityConflict, 'The record changed while exporting; export again.'),
    (page([{**EPISODES[1], 'rows': []}], None, last=True), VerificationFailed, 'The folder breaks rule 1: an episode is not a work episode (line 1 of episodes.jsonl).'),
], ids=['until-changed', 'next-not-advancing', 'reconstruction-changed', 'malformed-later-page'])
def test_c_a_refused_page_leaves_no_destination_and_no_staging(tmp_path, second, error, text):
    """R1-15, R1-18, R2-15: a changed `until`, a `next` that does not advance, a changed reconstruction (an interior row or
    an outcome changed on the server with counts and ids unchanged: only the digest tells), a later page that is not its
    contract. Mutation: each comparison removed in turn -> a folder is written -> red."""
    client = Transport(page([EPISODES[0]], 1), second)
    with pytest.raises(error) as caught: trajectories.export(client, tmp_path / 'out', purpose='training')
    assert (str(caught.value), nothing_left(tmp_path)) == (text, [])


def test_c_a_folder_that_fails_at_staging_is_not_renamed(tmp_path):
    """R1-18: every page parses, but the folder breaks rule 5 (the manifest's window is the gap). Mutation: `load` of the
    staging folder removed -> the destination exists -> red."""
    client = Transport(page(EPISODES, None, last=True))
    client.pages[0]['manifest'] = {**MANIFEST, 'window_seconds': 600}
    with pytest.raises(VerificationFailed) as caught: trajectories.export(client, tmp_path / 'out', purpose='training')
    assert (str(caught.value), nothing_left(tmp_path)) == (
        'The folder breaks rule 5: a gap inside an episode is at or above the window (line 2 of episodes.jsonl).', [])


def test_c_an_existing_destination_is_refused_before_any_call(tmp_path):
    """Mutation: the existence check removed -> the export runs into the folder -> red."""
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out' / 'mine.txt').write_text('kept')
    client = Transport()
    for destination, mode, text in ((tmp_path / 'out', 'shape', 'The destination exists; name a new folder.'),
                                    (tmp_path / 'none' / 'out', 'auto', "The destination's folder does not exist.")):
        with pytest.raises(Refused) as caught: trajectories.export(client, destination, purpose='training', mode=mode)
        assert str(caught.value) == text
    assert (client.bodies, nothing_left(tmp_path), (tmp_path / 'out' / 'mine.txt').read_text()) == ([], ['out'], 'kept')


# --- d: E134 s2 modes (R1-3) ------------------------------------------------------------------------------------------------

VALUES = {**MANIFEST, 'mode': 'auto', 'counts': {**MANIFEST['counts'], 'episodes': 3, 'shape': 2, 'values': 1}}


class Recorder:
    """A fake client for the public method and the CLI: answers one last page and keeps every call."""
    def __init__(self, episodes, manifest): self.episodes, self.manifest, self.calls = episodes, manifest, []
    def _post(self, area, operation, body, retry=False):
        self.calls.append((area, operation, body))
        if (area, operation) == ('ai-use', 'self-grant'):
            return {'asset_id': body['asset_id'], 'purpose': body['purpose'], 'state': body['state'], 'sequence': 3, 'at': 1.5}
        return {'schema': 'ophiolite.work-episodes-page/1', 'manifest': self.manifest, 'episodes': self.episodes, 'next': None,
                'until': 42, 'reconstruction': 'a' * 64}


def modes(calls): return [body['mode'] for area, _, body in calls if area == 'activity']


def test_d_the_method_defaults_to_auto_and_passes_each_mode(tmp_path):
    """No mode, `auto`, `shape`: the body carries the mode asked for, auto when none. A values episode under an auto
    manifest loads and is counted. Mutation: the default left at shape, or a shape-only refusal kept -> red."""
    from ophiolite.client import Client
    client = Recorder([*EPISODES, values_episode()], VALUES)
    found = Client.export_trajectories(client, tmp_path / 'one', purpose='training')
    assert found == {'episodes': 3, 'values': 1, 'destination': str(tmp_path / 'one'), 'parquet': PYARROW}
    Client.export_trajectories(client, tmp_path / 'two', purpose='training', mode='auto')
    client.manifest = MANIFEST
    client.episodes = EPISODES
    Client.export_trajectories(client, tmp_path / 'three', purpose='evaluation', mode='shape')
    assert modes(client.calls) == ['auto', 'auto', 'shape']
    assert [e.mode for e in trajectories.load(tmp_path / 'one')[1]] == ['shape', 'shape', 'values']


def test_d_a_values_episode_with_a_null_outcome_label_loads(tmp_path):
    """R1-16 (C6, `work-episode/1` 1.1.0): an outcome label left out or scrubbed is null, and `load` (the generated
    models, from the installed wheel on the installed-SDK lane) reads it. Mutation: the models before C6 (a required
    label) -> rule 1 -> red."""
    episode = values_episode()
    episode['rows'][0]['outcomes'] = [{'ref': 'ref-' + '1' * 32, 'outcome_ref': 'outcome-' + '2' * 32, 'version': 1, 'state': 'accepted',
                                       'declaration_sha256': '3' * 64, 'evaluation_sha256': None, 'label': None}]
    _, parsed = trajectories.load(folder(tmp_path, VALUES, [*EPISODES, episode]))
    assert (parsed[2].mode, parsed[2].rows[0].outcomes[0].label) == ('values', None)


@pytest.mark.parametrize('argv,mode',[([], 'auto'), (['--mode', 'auto'], 'auto'), (['--mode', 'shape'], 'shape')], ids=['no-mode', 'auto', 'shape'])
def test_d_the_cli_defaults_to_auto(tmp_path, argv, mode):
    """`--mode` is optional, auto by default; `values` is not a choice. Mutation: `required=True` kept -> no-mode red."""
    from ophiolite import cli
    args = cli.parser().parse_args(['trajectories', 'export', '--scope', 'project:p', '--purpose', 'training', '--destination', str(tmp_path / 'x'), *argv])
    assert args.mode == mode
    with pytest.raises(SystemExit): cli.parser().parse_args(['trajectories', 'export', '--scope', 'project:p', '--purpose', 'training',
                                                             '--destination', str(tmp_path / 'x'), '--mode', 'values'])


@pytest.mark.parametrize('granted,state', [(True, 'granted'), (False, 'withdrawn')])
def test_d_grant_own_ai_use_sends_the_self_grant(granted, state):
    """Mutation: the state not derived from `granted` -> the withdrawn case red."""
    from ophiolite.client import Client
    client = Recorder([], None)
    answer = Client.grant_own_ai_use(client, 'a-1', 'evaluation', granted, command_id='c-1')
    assert client.calls == [('ai-use', 'self-grant', {'asset_id': 'a-1', 'purpose': 'evaluation', 'state': state, 'command_id': 'c-1'})]
    assert answer['state'] == state


def test_d_the_cli_records_a_self_grant(capsys):
    """`ophiolite ai-use self-grant ASSET --purpose P [--withdraw]`. Mutation: `--withdraw` ignored -> red."""
    from ophiolite import cli
    args = cli.parser().parse_args(['ai-use', 'self-grant', 'a-1', '--purpose', 'training', '--withdraw'])
    assert (args.command, args.action, args.asset, args.purpose, args.withdraw) == ('ai-use', 'self-grant', 'a-1', 'training', True)
    with pytest.raises(SystemExit): cli.parser().parse_args(['ai-use', 'self-grant', 'a-1', '--purpose', 'embedding'])


# --- s3: the conformance folder, episodes.parquet and rule 9, until (E134 s3 C3; logs/s3-mutations.txt) ---------------------

CONFORMANCE = FIXTURES / 'folder'  # the Platform's frozen folder (D5), synced by tools/sync.py; never regenerated here
LINES = (CONFORMANCE / 'episodes.jsonl').read_text().splitlines()
FROZEN = json.loads((CONFORMANCE / 'trajectories.json').read_text())
PINNED = [('episode_id', 'string'), ('mode', 'string'), ('split', 'string'), ('start', 'double'), ('end', 'double'), ('rows', 'int64'), ('episode', 'string')]


@pytest.fixture
def blocked(monkeypatch):
    """`import pyarrow` fails, as in an environment without it (test_tables' pattern)."""
    import builtins
    real = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split('.')[0] == 'pyarrow': raise ImportError('blocked: ' + name)
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)


def conformance_pages(until=20):
    return Transport({'schema': 'ophiolite.work-episodes-page/1', 'manifest': FROZEN, 'episodes': [json.loads(line) for line in LINES], 'next': None,
                      'until': until, 'reconstruction': 'a' * 64})


def leftovers(tmp_path): return sorted(p.name for p in tmp_path.iterdir())


def test_s3_e_the_conformance_folder_loads(tmp_path):
    """D5: the synced copy loads with its literal counts and modes. M6: line 2's split flipped -> rule 6, named."""
    manifest, episodes = trajectories.load(CONFORMANCE)
    assert ((manifest.counts.episodes, manifest.counts.values, manifest.counts.shape), [e.mode for e in episodes], manifest.until) == ((2, 1, 1), ['shape', 'values'], 20)
    second = json.loads(LINES[1])
    assert second['split'] == 'train'
    assert refused(tmp_path, FROZEN, [json.loads(LINES[0]), {**second, 'split': 'test'}]) == (
        'The folder breaks rule 6: a split is not split/1 (line 2 of episodes.jsonl).')


def test_s3_f_the_base_wheel_loads_the_folder_from_its_package(tmp_path):
    """R2-8: the installed base wheel (no pyarrow) resolves the folder from its own package and loads it (rules 1-8)."""
    import os, subprocess
    python = os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if not python: pytest.fail('Set OPHIOLITE_TEST_WHEEL_PYTHON to the independently installed SDK wheel interpreter')
    script = '''
import importlib.resources, json
try:
    import pyarrow
    raise SystemExit("pyarrow is installed in the base wheel environment")
except ImportError: pass
from ophiolite import trajectories
folder = importlib.resources.files("ophiolite") / "contracts/scientific/v1/fixtures/work-episodes/folder"
manifest, episodes = trajectories.load(folder)
print(json.dumps([manifest.counts.episodes, manifest.counts.values, manifest.counts.shape, [e.mode for e in episodes], str(folder)]))
'''
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path), 'PYTHONNOUSERSITE': '1'}
    done = subprocess.run([python, '-I', '-c', script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr + done.stdout
    counts = json.loads(done.stdout)
    assert counts[:4] == [2, 1, 1, ['shape', 'values']] and not counts[4].startswith(str(Path(__file__).resolve().parents[1] / 'ophiolite'))


def test_s3_p_the_manifest_writer_gives_the_frozen_bytes(tmp_path):
    """R2-6: the SDK's writer, given the parsed frozen manifest (sdk_version null), writes the frozen bytes. M10: other
    separators or key order -> red."""
    trajectories.write_manifest(tmp_path / 'm.json', FROZEN, None)
    assert (tmp_path / 'm.json').read_bytes() == (CONFORMANCE / 'trajectories.json').read_bytes()


def rewrite(path, row, column, value, kinds=None):
    """`episodes.parquet` written again with one cell changed (well-formed, the pinned schema unless `kinds` differ)."""
    import pyarrow as pa, pyarrow.parquet as pq
    data = pq.read_table(path).to_pydict()
    if row is not None: data[column][row] = value
    if column == 'drop': data = {k: v[:1] for k, v in data.items()}
    if column == 'extra': data = {k: v + v[1:] for k, v in data.items()}
    schema = pa.schema([(name, getattr(pa, (kinds or {}).get(name, kind))()) for name, kind in trajectories.PARQUET_FIELDS])
    pq.write_table(pa.table(data, schema=schema), path, compression='zstd')


def exported(tmp_path, name='out'):
    found = trajectories.export(conformance_pages(), tmp_path / name, purpose='training')
    return found, tmp_path / name


@pytest.mark.parametrize('row,column,value,kinds,text', [
    (1, 'episode_id', 'episode-' + '0' * 32, None, 'a column of episodes.parquet differs from its line (line 2 of episodes.jsonl)'),
    (1, 'mode', 'shape', None, 'a column of episodes.parquet differs from its line (line 2 of episodes.jsonl)'),
    (1, 'split', 'test', None, 'a column of episodes.parquet differs from its line (line 2 of episodes.jsonl)'),
    (1, 'start', 1793293201.0, None, 'a column of episodes.parquet differs from its line (line 2 of episodes.jsonl)'),
    (1, 'end', 1793293201.0, None, 'a column of episodes.parquet differs from its line (line 2 of episodes.jsonl)'),
    (1, 'rows', 2, None, 'a column of episodes.parquet differs from its line (line 2 of episodes.jsonl)'),
    (0, 'episode', LINES[0].replace('"shape"', '"values"'), None, 'a row of episodes.parquet is not its line (line 1 of episodes.jsonl)'),
    (None, 'rows', None, {'rows': 'int32'}, 'the schema of episodes.parquet is not the pinned one'),
    (None, 'drop', None, None, 'episodes.parquet does not hold one row per line'),
    (None, 'extra', None, None, 'episodes.parquet does not hold one row per line'),
], ids=['M7a-episode_id', 'M7b-mode', 'M7c-split', 'M7d-start', 'M7e-end', 'M7f-rows', 'M7g-episode', 'M7h-int32', 'R2-7-missing', 'R2-7-extra'])
def test_s3_g_the_export_writes_episodes_parquet_and_rule_9_checks_it(tmp_path, row, column, value, kinds, text):
    """D4, R1-7: the pinned schema (literal), two rows, the lines as `episode`; each broken file, valid otherwise, is
    rule 9. M8: the scalar comparison removed -> M7a-f load; M7i: the length check removed -> the R2-7 cases load."""
    import pyarrow.parquet as pq
    found, out = exported(tmp_path)
    assert (found['parquet'], leftovers(tmp_path)) == (True, ['out'])
    table = pq.read_table(out / trajectories.PARQUET)
    assert ([(f.name, str(f.type)) for f in table.schema], table.num_rows, table.column('episode').to_pylist()) == (PINNED, 2, LINES)
    assert [e.mode for e in trajectories.load(out)[1]] == ['shape', 'values']
    rewrite(out / trajectories.PARQUET, row, column, value, kinds)
    with pytest.raises(VerificationFailed) as caught: trajectories.load(out)
    assert str(caught.value) == 'The folder breaks rule 9: %s.' % text


def test_s3_h_without_pyarrow_no_parquet_is_written_or_read(tmp_path, blocked):
    """D4: blocked, the export writes no parquet and says so; a folder holding one (unreadable) loads without reading it."""
    found, out = exported(tmp_path)
    assert (found['parquet'], sorted(p.name for p in out.iterdir())) == (False, ['episodes.jsonl', 'trajectories.json'])
    (out / trajectories.PARQUET).write_bytes(b'not parquet')
    assert len(trajectories.load(out)[1]) == 2


def test_s3_i_the_cli_sends_until_first_and_the_page_s_until_after(tmp_path):
    """`--until 4711` parses; the first body carries it, the continuation the first page's (clamped) `until`. M9: `if
    until:` -> the zero case in test_s3_q."""
    from ophiolite import cli
    from ophiolite.client import Client
    args = cli.parser().parse_args(['trajectories', 'export', '--scope', 'project:p', '--purpose', 'training', '--destination', str(tmp_path / 'x'),
                                    '--until', '4711'])
    assert args.until == 4711
    client = Transport(page([EPISODES[0]], 1, until=42), page([EPISODES[1]], None, last=True, until=42))
    Client.export_trajectories(client, tmp_path / 'out', purpose='training', mode='shape', until=args.until)
    assert [(b['after'], b.get('until')) for b in client.bodies] == [(0, 4711), (1, 42)]


@pytest.mark.parametrize('block', [False, True], ids=['pyarrow', 'blocked'])
def test_s3_m_an_empty_export_writes_a_zero_row_parquet_or_none(tmp_path, monkeypatch, block, request):
    """R1-8: no episodes -> a zero-row table with the pinned schema and `parquet: True`; blocked -> none, False; both load."""
    if block: request.getfixturevalue('blocked')
    empty = {**FROZEN, 'counts': {**FROZEN['counts'], 'episodes': 0, 'values': 0, 'shape': 0}}
    client = Transport({'schema': 'ophiolite.work-episodes-page/1', 'manifest': empty, 'episodes': [], 'next': None, 'until': 0, 'reconstruction': 'a' * 64})
    found = trajectories.export(client, tmp_path / 'out', purpose='training')
    assert (found['episodes'], found['parquet']) == (0, not block)
    assert trajectories.load(tmp_path / 'out')[1] == []
    if not block:
        import pyarrow.parquet as pq
        table = pq.read_table(tmp_path / 'out' / trajectories.PARQUET)
        assert ([(f.name, str(f.type)) for f in table.schema], table.num_rows) == (PINNED, 0)


def test_s3_n_a_truncated_parquet_cannot_be_read(tmp_path):
    _, out = exported(tmp_path)
    data = (out / trajectories.PARQUET).read_bytes()
    (out / trajectories.PARQUET).write_bytes(data[:len(data) // 2])
    with pytest.raises(VerificationFailed) as caught: trajectories.load(out)
    assert str(caught.value) == 'The folder breaks rule 9: episodes.parquet cannot be read.'


def test_s3_o_a_failed_parquet_write_leaves_nothing(tmp_path, monkeypatch):
    """E13: the write raising removes the staging folder; no destination."""
    import pyarrow.parquet as pq
    def broken(*args, **kwargs): raise OSError('disk full')
    monkeypatch.setattr(pq, 'write_table', broken)
    with pytest.raises(OSError): trajectories.export(conformance_pages(), tmp_path / 'out', purpose='training')
    assert leftovers(tmp_path) == []
