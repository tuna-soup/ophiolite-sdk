"""E217 s0 (D6): writes answer their receipts, and downloads the path they saved. Never executed."""
from pathlib import Path

from typing_extensions import assert_type

from ophiolite import Client, WrittenOriginal
from ophiolite.bundle import Bundle
from ophiolite.models.api import PublicationReceipt, UploadResult
from ophiolite.presentation import PresentedReceipt


def writes(client: Client, written: WrittenOriginal) -> None:
    audience: list[str] = []
    parents: list[tuple[str, str]] = [('a', 'r')]
    method: dict[str, str] = {'name': 'smooth'}
    selections: list[tuple[str, str, list[str]]] = [('a', 'r', ['GR'])]
    uploaded = client.upload_las(b'~V', name='GR', attribution='me', audience=audience, rights_confirmed=True)
    assert_type(uploaded, UploadResult)
    assert_type(uploaded.revision, str)
    assert_type(client.upload_data(b'x', profile='points-csv/1', name='tops', attribution='me', audience=audience,
                                   rights_confirmed=True), UploadResult)
    receipt = client.publish_derived(written, name='GR smoothed', from_=parents, method=method, command_id='c1')
    assert_type(receipt, PresentedReceipt)
    assert_type(receipt.asset_id, str)
    assert_type(client.change_units('a', 'r', curves={'DT': 'us/m'}, name='DT in us/m', command_id='c2'), PublicationReceipt)
    assert_type(client.export_file('a', 'r', 'out.parquet'), Path)
    assert_type(client.download_original('a', 'r', 'original.las'), Path)
    assert_type(client.export(selections, 'bundle'), Bundle)
