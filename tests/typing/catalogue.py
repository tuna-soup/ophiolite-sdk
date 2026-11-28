"""E217 s0 (D6): catalogue items are typed dicts with the contract's keys, nested `display` included. Never executed."""
from collections.abc import Iterator

from typing_extensions import assert_type

from ophiolite import Client
from ophiolite.models.items import AssetDisplay, AssetItem, AssetPerson, AssetVersion


def catalogue(client: Client) -> None:
    assert_type(client.assets(), Iterator[AssetItem])
    for item in client.assets():
        assert_type(item['asset_id'], str)
        assert_type(item['revision'], str)
        assert_type(item['curves'], list[str])
        assert_type(item['sample_count'], int | None)
        assert_type(item['custodian'], str | None)
        display = item.get('display')
        assert_type(display, AssetDisplay | None)
        if display is not None:
            version = display.get('version')
            assert_type(version, AssetVersion | None)
            if version is not None:
                assert_type(version.get('by'), AssetPerson | None)
                assert_type(version.get('ordinal'), int | None)


def found(client: Client) -> None:
    log = client.find_log(curves=['GR'], operation='read')
    assert_type(log, AssetItem)
    assert_type(log['name'], str)
    assert_type(log.get('osdu_kind'), str | None)
