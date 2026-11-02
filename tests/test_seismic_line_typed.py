"""E137 s1 C5: the SDK reads a 2D seismic line pair from the contract snapshot as a typed object (`read_data`), so
connectors can place a project's line; before this commit the kind was refused as not supported by this SDK. The
original is checked byte for byte; literals written by hand from the fixture (seismic-line.json, 5 traces)."""
import json
from importlib.resources import files

import pytest

from ophiolite import _core, typed, validate
from ophiolite.errors import VerificationFailed

FIXTURES = files('ophiolite').joinpath('contracts/assets/v1/fixtures')


def load():
    return (json.loads(FIXTURES.joinpath('seismic-line.json').read_bytes()), FIXTURES.joinpath('seismic-line-data.json').read_bytes(),
            FIXTURES.joinpath('seismic-line.original').read_bytes())


def test_the_snapshot_pair_reads_as_a_seismic_line():
    descriptor, body, original = load()
    result = _core.typed_result(descriptor, body, original)
    assert isinstance(result, typed.SeismicLine) and typed.CLASSES['seismic-line'] is typed.SeismicLine and 'seismic-line' in typed.TYPES
    assert [g[0] for g in result.geometry] == [103, 101, 102, 105, 104] and [g[1] for g in result.geometry] == [1.5, -2.0, 0.0, None, 7.0]
    assert result.original == original and len(original) == 4880 and result.context['format_code'] == 5
    assert repr(result) == '<SeismicLine Syn2D/L1 5×4 time>'


def test_a_changed_original_is_refused():
    descriptor, body, original = load()
    with pytest.raises(VerificationFailed):
        _core.typed_result(descriptor, body, original[:-1] + bytes([original[-1] ^ 1]))


def test_the_kind_is_known_to_validate():
    descriptor, body, _ = load()
    _, payload = validate.typed_pair(descriptor, body)
    assert payload['schema'] == 'ophiolite.seismic-line/1' and len(payload['geometry']) == 5
