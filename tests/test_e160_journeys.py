"""E160 s0: the folder-described contract as the SDK reads it (offline).

C1: the 1.2.0 manifest (`tier`, `files`) of the contract's conformance folder loads through `trajectories.load` with
that folder's own `episodes.jsonl`. Mutation (logs/c1-mutations.txt): the SDK's generated `WorkEpisodes` without
`files` (extra='forbid') -> rule 1 refuses the folder."""
import json
import shutil
from pathlib import Path

import ophiolite
from ophiolite import trajectories

FIXTURES = Path(ophiolite.__file__).parent / 'contracts/scientific/v1/fixtures/work-episodes'
M12 = json.loads((FIXTURES / 'manifest-1.2.json').read_text())['manifest']


def test_c1_the_1_2_0_manifest_loads_with_its_folder(tmp_path):
    folder = tmp_path / 'out'
    folder.mkdir()
    shutil.copyfile(FIXTURES / 'folder/episodes.jsonl', folder / trajectories.EPISODES)
    (folder / trajectories.MANIFEST).write_text(json.dumps(M12))
    manifest, episodes = trajectories.load(folder)
    assert manifest.tier == 'local-evaluation'
    assert [(f.name, f.bytes, f.sha256) for f in manifest.files] == [
        ('episodes.jsonl', 2191, 'a9d44e7c9be1a5e2cc4ef0575e1a4d3b2daa1935adeaceeaba88b885264ff394')]
    assert [e.mode for e in episodes] == ['shape', 'values']


# ---- C4: describe and turns refused until their slice; the journey skeleton (strategy D4, C4) ----------------------

import copy
import hashlib

import pytest

from ophiolite.errors import Refused

CONTRACTS = Path(ophiolite.__file__).parent / 'contracts'
CONFORMANCE = FIXTURES / 'folder'
FROZEN = json.loads((CONFORMANCE / 'trajectories.json').read_text())
TURNS = CONTRACTS / 'scientific/v1/fixtures/work-turns'
JOURNEYS = {row['case']: row for row in json.loads((Path(__file__).parent / 'fixtures/e160/journeys.json').read_text())['journeys']}


class Silent:
    """A client that fails the test if anything is sent."""
    def _post(self, *args, **kwargs): pytest.fail('a describe export sent a request')


class Pages:
    """The conformance folder as one last page (test_trajectories_load's conformance pages)."""
    def __init__(self): self.bodies = []
    def _post(self, area, operation, body, retry=False):
        self.bodies.append(body)
        return {'schema': 'ophiolite.work-episodes-page/1', 'manifest': copy.deepcopy(FROZEN), 'next': None, 'until': 20,
                'reconstruction': 'a' * 64, 'episodes': [json.loads(line) for line in (CONFORMANCE / 'episodes.jsonl').read_text().splitlines()]}


def test_c4_describe_is_refused_before_anything_is_sent_or_written(tmp_path):
    """D4: export and the client method refuse describe=True with the sentence; nothing is sent, no folder is left.
    Mutation: the check moved after the destination checks or the first page -> Silent fails or a folder is left."""
    from ophiolite.client import Client
    with pytest.raises(Refused) as caught: trajectories.export(Silent(), tmp_path / 'out', purpose='training', describe=True)
    assert str(caught.value) == JOURNEYS[2]['now'] == 'Describing the folder is not available yet.'
    with pytest.raises(Refused) as caught: Client.export_trajectories(Silent(), tmp_path / 'out', purpose='training', describe=True)
    assert str(caught.value) == JOURNEYS[2]['now']
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_c4_the_cli_refuses_describe_before_reading_any_configuration(tmp_path, monkeypatch, capsys):
    """`ophiolite trajectories export ... --describe` with no configuration and an empty environment: the sentence on
    stderr, the refusal exit code, no folder. Mutation: the check after `configuration(...)` -> the configuration's
    refusal is printed instead; `--describe` not forwarded -> argparse exits 2."""
    from ophiolite import cli
    for name in [n for n in __import__('os').environ if n.startswith('OPHIOLITE')]: monkeypatch.delenv(name)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    with pytest.raises(SystemExit) as caught:
        cli.entrypoint(['trajectories', 'export', '--scope', 'project:p', '--purpose', 'training', '--destination', str(tmp_path / 'out'), '--describe'])
    assert caught.value.code == cli.EXIT['refused'] == 1
    assert capsys.readouterr().err.strip().splitlines()[-1] == JOURNEYS[2]['now']
    assert not (tmp_path / 'out').exists()


def test_c4_load_turns_is_refused(tmp_path):
    with pytest.raises(Refused) as caught: trajectories.load_turns(TURNS / 'shape')
    assert str(caught.value) == JOURNEYS[3]['now'] == 'Reading turns is not available yet.'


def test_c4_an_export_without_describe_is_today_s_folder(tmp_path):
    """Journeys 1 and 5 now: the conformance folder exports as E134 wrote it, its manifest without tier or files; the
    expected files row of journey 1 is that folder's own episodes.jsonl. Mutation: describe forwarded as a body key ->
    the body differs."""
    from ophiolite.client import Client
    client = Pages()
    Client.export_trajectories(client, tmp_path / 'out', purpose='training')
    assert client.bodies == [{'purpose': 'training', 'mode': 'auto', 'seed': 0, 'after': 0, 'limit': 1000}]
    out = tmp_path / 'out'
    assert (out / trajectories.EPISODES).read_bytes() == (CONFORMANCE / 'episodes.jsonl').read_bytes()
    manifest = json.loads((out / trajectories.MANIFEST).read_text())
    assert sorted(manifest) == sorted(FROZEN) and 'tier' not in manifest and 'files' not in manifest
    assert {k: v for k, v in manifest.items() if k != 'sdk_version'} == {k: v for k, v in FROZEN.items() if k != 'sdk_version'}
    raw = (out / trajectories.EPISODES).read_bytes()
    assert JOURNEYS[1]['expected']['files'] == [['episodes.jsonl', len(raw), hashlib.sha256(raw).hexdigest()]]
    assert JOURNEYS[5]['expected']['differs_by'] == ['files', 'tier']


def test_c4_the_skeleton_has_one_row_per_acceptance_subcase_and_its_slice():
    assert sorted(JOURNEYS) == [1, 2, 3, 4, 5]
    assert {case: row['flips_in'] for case, row in JOURNEYS.items()} == {1: 's1', 2: 's2', 3: 's2', 4: 's3', 5: 's1'}


def test_c4_the_expected_fields_and_lines_are_the_contract_fixtures():
    """Journeys 2 to 4 expected: the field names of the contract's episodes croissant.json fixtures and the line counts
    of the work-turns fixtures (written by hand in journeys.json; this ties them to the contract)."""
    valid = CONTRACTS / 'descriptors/v1/fixtures/valid'
    fields = lambda base: [f['name'] for f in json.loads((valid / base / 'croissant.json').read_text())['recordSet'][0]['field']]
    expected = JOURNEYS[2]['expected']
    assert fields('episodes-auto') == expected['values']
    assert fields('episodes-shape') == [name for name in expected['values'] if name not in expected['shape_leaves_out']]
    lines = {mode: len((TURNS / mode / 'turns.jsonl').read_text().splitlines()) for mode in ('shape', 'auto', 'empty')}
    assert lines == JOURNEYS[3]['expected']['lines'] == {'shape': 3, 'auto': 4, 'empty': 0}
    assert JOURNEYS[4]['expected']['lines_read'] == {'shape': 3, 'auto': 4}


def test_c4_no_trainer_adapter_exists_yet():
    assert not hasattr(trajectories, 'to_art') and not hasattr(trajectories, 'to_agent_lightning')
