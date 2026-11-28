"""E217 s0 (D6): volume and window reads answer their result classes. Never executed."""
from typing_extensions import assert_type

from ophiolite import Client
from ophiolite.typed import SeismicSlice
from ophiolite.volume_windows import VolumeWindowResult, WindowReader
from ophiolite.windows import CurveWindow


def volumes(client: Client) -> None:
    assert_type(client.read_slice('asset', 'revision', 'inline', 100), SeismicSlice)
    assert_type(client.read_window('asset', 'revision', inline=(100, 110), by='label'), VolumeWindowResult)
    assert_type(client.iter_window('asset', 'revision', trace='1:50'), WindowReader)
    assert_type(client.curve_window('asset', 'revision', 'GR', 1000.0, 1200.0, rows=500), CurveWindow)
