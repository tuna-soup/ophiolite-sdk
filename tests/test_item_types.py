"""E217 s0 C2 (D4): the catalogue item TypedDicts match the asset summary contract, and the wheel says it is typed.

The keys and annotation texts below were written by hand from contracts/assets/v1/summary-schema.json (its `required`
list and each property's type), never read back from the generated module. Each test names the mutation it catches.
"""
import os
import zipfile
from pathlib import Path

import pytest
from ophiolite.models.items import AssetDisplay, AssetItem, AssetPerson, AssetVersion, AssetVia

REQUIRED = {'asset_id': 'str', 'revision': 'str', 'name': 'str',
            'origin': "Literal['source-reference', 'retained-capture', 'managed-derived']", 'authority': 'str',
            'profile': 'str', 'custodian': 'str | None', 'curves': 'list[str]', 'sample_count': 'int | None',
            'allowed_operations': "list[Literal['read', 'export', 'use-as-input']]"}
OPTIONAL = {'display': 'AssetDisplay | None', 'osdu_kind': 'str | None', 'osdu_kind_reason': 'str | None'}


def texts(cls):
    """Each key's annotation as written in the module (TypedDict wraps the lazy strings in ForwardRef)."""
    return {key: getattr(value, '__forward_arg__', value) for key, value in cls.__annotations__.items()}


def test_the_asset_item_has_the_contracts_required_and_optional_keys():
    """Mutation: `revision` moved to the optional part (or a key dropped) → the key sets differ."""
    assert (set(AssetItem.__required_keys__), set(AssetItem.__optional_keys__)) == (set(REQUIRED), set(OPTIONAL))


def test_each_asset_item_key_has_the_contracts_type():
    """Mutation: `sample_count` typed `str` → its annotation text differs."""
    assert texts(AssetItem) == {**REQUIRED, **OPTIONAL}


def test_the_nested_objects_are_typed_dicts_not_models():
    """Mutation: `display` pointing at the pydantic Display model, or Via's keys made optional → red."""
    for nested in (AssetDisplay, AssetVersion, AssetPerson, AssetVia):
        assert nested.__mro__[-2:] == (dict, object) and hasattr(nested, '__required_keys__')
    assert set(AssetDisplay.__required_keys__) == set() and texts(AssetDisplay)['version'] == 'AssetVersion | None'
    assert texts(AssetVersion) == {'at': 'str | None', 'by': 'AssetPerson | None', 'via': 'AssetVia | None',
                                            'ordinal': 'int | None', 'of': 'int | None', 'source_version': 'str | None'}
    assert (set(AssetPerson.__required_keys__), set(AssetPerson.__optional_keys__)) == ({'id'}, {'label'})
    assert AssetVia.__required_keys__ == frozenset({'kind', 'key_id', 'label'})
    assert texts(AssetVia)['kind'] =="Literal['access-key']"


def test_the_built_wheel_carries_py_typed():
    """Mutation: `ophiolite/py.typed` deleted → absent from the wheel. (The pinned setuptools 84 ships `py.typed` by
    itself, so dropping only its package-data entry stays green; the entry is kept for readers of pyproject.toml.)"""
    dist = os.environ.get('OPHIOLITE_TEST_DIST')
    if not dist:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel')
        pytest.skip('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel')
    [wheel] = Path(dist).glob('ophiolite-*.whl')
    assert 'ophiolite/py.typed' in zipfile.ZipFile(wheel).namelist()
