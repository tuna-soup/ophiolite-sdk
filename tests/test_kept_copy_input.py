"""E181 s1 C2: the SDK reads a kept copy of a wells table (`sql-wells/1`) as a tool input. Offline: the vendored rules
1.6.0 validate a folder reading one, and a run's download of one keeps its type and a .json name. The real download
over the gateway is the Platform's test_kept_copy_input test 8.

Mutation: the `EXTENSIONS` entry removed -> the file is `wells-0.csv` -> red.

E181 s1b C2 (D-4): a first run's `@A:V` in a slot accepting `sql-wells/1` alone downloads the original with no
description asked (the gateway refuses the descriptor of a kept copy); any other slot describes as before. Mutations:
D-4 removed (`profile` left None) -> the one-kind test sees a describe -> red; `original_only` true for any profile ->
the envelope-served and two-kind tests download without describing -> red; the LAS refusal not caught -> the
non-LAS test raises Refused, not NotRun -> red."""
import json

import pytest

from ophiolite import Client, Credential, procedures
from ophiolite.errors import Incompatible

KIND = 'sql-wells/1'
ASSET, REVISION = 'a' * 64, 'b' * 64
RAW = b'{"rows":[]}'


def test_a_folder_reading_a_kept_copy_is_valid_offline(tmp_path):
    procedures.new(tmp_path / 'fix', 'process', 'Correct a well position')
    manifest = json.loads((tmp_path / 'fix/procedure.json').read_text())
    manifest['inputs'] = [{'slot': 'wells', 'label': 'Wells table', 'class': 'version', 'kinds': [KIND], 'cardinality': 'one'}]
    (tmp_path / 'fix/procedure.json').write_text(json.dumps(manifest))
    verdict = procedures.validate(tmp_path / 'fix')
    assert (verdict['valid'], verdict['rules_version']) == (True, '1.6.0'), verdict
    assert 'It reads Well locations from a SQL table and makes' in verdict['sentence']


def test_a_kept_copy_is_downloaded_for_a_run_as_json_with_its_kind(tmp_path, monkeypatch):
    client = Client('https://ophiolite.test', 'p', Credential.bearer('oph_api_alice'))
    asked = []

    def original(asset, revision, destination, *_, described=True):  # E212 s1: download_original's body, the describe for its notice skipped or not
        asked.append((asset, revision, destination.name, described))
        destination.write_bytes(RAW)
    monkeypatch.setattr(client, '_save_original', original)
    given = client._download_version(ASSET, REVISION, tmp_path / 'inputs' / 'wells-0', profile=KIND, declared={})
    assert asked == [(ASSET, REVISION, 'wells-0.json', False)]  # E212 s1: a kept copy has no describe to read a notice from
    assert (given.path, given.kind, given.asset_id, given.revision) == (str(tmp_path / 'inputs/wells-0.json'), KIND, ASSET, REVISION)
    assert (tmp_path / 'inputs/wells-0.json').read_bytes() == RAW


class Described(Exception):
    """A description was asked (the spy stops there)."""


def _spied(monkeypatch, raw=RAW, describe=None):
    client = Client('https://ophiolite.test', 'p', Credential.bearer('oph_api_alice'))
    seen = {'described': [], 'saved': []}

    def original(asset, revision, destination, *_, described=True):  # E212 s1: download_original's body; a notice's describe is a 'described' entry
        seen['saved'].append(destination.name); destination.write_bytes(raw)
        if described: seen['described'].append('notice')

    def described(path, *_args, **_kw):
        seen['described'].append(path)
        raise describe or Described(path)
    monkeypatch.setattr(client, '_save_original', original)
    monkeypatch.setattr(client, '_json', described)
    return client, seen


def _slot(*kinds):
    return {'inputs': [{'slot': 'wells', 'label': 'Wells table', 'class': 'version', 'kinds': list(kinds), 'cardinality': 'one'}]}


def test_original_only_is_the_contract_literal():
    assert [procedures.original_only(p) for p in (KIND, 'well-location/1', 'las2/1', 'nothing/1')] == [True, False, False, False]


def test_a_one_kind_kept_copy_slot_downloads_with_no_description(tmp_path, monkeypatch):
    client, seen = _spied(monkeypatch)
    given = client._project_inputs({'wells': [f'@{ASSET}:{REVISION}']}, _slot(KIND))
    try:
        assert seen == {'described': [], 'saved': ['wells-0.json']}
        (only,) = given['wells']
        assert (only.kind, only.declared, only.asset_id, only.revision) == (KIND, {}, ASSET, REVISION)
        assert open(only.path, 'rb').read() == RAW
    finally: procedures._discard(given)


@pytest.mark.parametrize('kinds', [('well-location/1',), (KIND, 'well-location/1')], ids=['envelope-served', 'two-kinds'])
def test_every_other_slot_still_asks_for_the_description(tmp_path, monkeypatch, kinds):
    client, seen = _spied(monkeypatch)
    with pytest.raises(Described):
        client._project_inputs({'wells': [f'@{ASSET}:{REVISION}']}, _slot(*kinds))
    assert (len(seen['described']), seen['saved']) == (1, [])


def test_a_refused_description_of_something_not_a_log_is_not_run_and_keeps_nothing(tmp_path, monkeypatch):
    client, seen = _spied(monkeypatch, describe=Incompatible('This scientific route serves registered profiles only'))
    with pytest.raises(procedures.NotRun) as refused:
        client._download_version(ASSET, REVISION, tmp_path / 'inputs' / 'wells-0')
    assert (refused.value.code, seen['saved']) == ('project-input-kind', ['wells-0.las'])
    assert list((tmp_path / 'inputs').iterdir()) == []
