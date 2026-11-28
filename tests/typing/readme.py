"""E217 s0 (D6): the README's Python block, as a type checker reads it against the installed wheel. Never executed."""
from typing_extensions import assert_type

from ophiolite import Client, Credential, CurveSet
from ophiolite.locations import Well, Wells
from ophiolite.models.generated import ApplicationCurve
from ophiolite.models.items import AssetItem


def readme(credential: Credential) -> None:
    with Client.from_configuration('ophiolite-demo/configuration.json', credential=credential) as client:
        assert_type(client, Client)
        wells = client.wells()
        assert_type(wells, Wells)
        log = next(item for item in client.assets() if 'GR' in item['curves'])
        assert_type(log, AssetItem)
        read = client.read(log['asset_id'], log['revision'], ['GR'])
        assert_type(read, CurveSet)
        gr = read.curves[0]
        assert_type(gr, ApplicationCurve)
        assert_type(len(wells), int)
        assert_type(wells[0], Well)
        assert_type(wells[0].name, str)
        assert_type(gr.values, list[float | None])
        assert_type(gr.axis[0], float)
        assert_type(gr.axis[-1], float)
