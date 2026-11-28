"""E217 s0 (D6, C6): the asynchronous client, as a type checker reads it against the installed wheel. Never executed.

An unawaited call is a coroutine of what the synchronous call returns; awaited, it is that value. `read` is
AsyncClient's own; `history` is attached by the loop in aio.py and declared for the checker (D2); so are AsyncWorkFolder's
calls. `assets` is an asynchronous iterator of catalogue items.
"""
from collections.abc import AsyncIterator, Coroutine
from typing import Any

from typing_extensions import assert_type

from ophiolite import AsyncClient, CurveSet
from ophiolite.aio import AsyncWorkFolder
from ophiolite.models.api import Binding, History
from ophiolite.models.items import AssetItem


async def asynchronous(client: AsyncClient, asset: str, revision: str) -> None:
    curves: list[str] = ['GR']
    reading = assert_type(client.read(asset, revision, curves), Coroutine[Any, Any, CurveSet])  # kept, then awaited
    read = await reading
    assert_type(read, CurveSet)
    asking = assert_type(client.history(asset), Coroutine[Any, Any, History])
    history = await asking
    assert_type(history, History)
    items = client.assets()
    assert_type(items, AsyncIterator[AssetItem])
    async for item in items:
        assert_type(item, AssetItem)
    folder = client.work_folder('run-folder')
    assert_type(folder, AsyncWorkFolder)
    binding = await folder.configure(asset, revision, curve='GR', name='gamma ray')
    assert_type(binding, Binding)
