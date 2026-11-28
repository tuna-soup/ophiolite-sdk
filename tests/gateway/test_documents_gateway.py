"""E222 s1 C6, gateway lane: `client.documents` against the in-process gateway. A 3 000 000-byte PDF (over the SDK's
ordinary request bound, under the deployment's 8 MB) is added to the project, listed, read back byte for byte with
its kept type, and described; a spreadsheet is refused by the server with its own sentence, never by the SDK.

Mutations (break -> RED): `_post` without the figure bound for documents/add -> the large add is refused client-side;
`read` typing the bytes itself -> the PDF's type; `list` sending a parent it was not given -> the project page."""
import io
import zipfile
from pathlib import Path

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)

from project_gateway import documents as served

FILES = Path(served.__file__).resolve().parents[2] / 'contracts/assets/v1/fixtures/attachments/files'
TYPE = 'GEOLOGY.EndOfWellReportGeological'


def large_pdf(size):
    """report.pdf with a PDF comment line before its end, to exactly SIZE bytes."""
    raw = (FILES / 'report.pdf').read_bytes()
    head, tail = raw.rsplit(b'%%EOF', 1)
    room = size - len(raw) - 2
    return head + b'%' + b'x' * room + b'\n' + b'%%EOF' + tail


def test_a_large_pdf_is_added_listed_read_and_described(web):
    from ophiolite.publish import MAX_REQUEST_BYTES
    alice = client(web, 'alice', 'delegate')
    data = large_pdf(3_000_000)
    assert len(data) == 3_000_000 and len(data) * 4 // 3 > MAX_REQUEST_BYTES
    added = alice.documents.add(('project', None), data, taxonomy=[TYPE], name='Field report', description='Long report.', command_id='doc-big')
    assert (added['file']['bytes'], added['file']['media_type'], added['parent']) == (3_000_000, 'application/pdf', {'kind': 'project', 'id': alice.project})
    assert alice.documents.add(('project', None), data, taxonomy=[TYPE], name='Field report', description='Long report.', command_id='doc-big') == added
    assert [d['document_id'] for d in alice.documents.list()['documents']] == [added['document_id']]
    assert alice.documents.read(added['document_id']) == (data, 'application/pdf')
    described = alice.documents.describe(added['document_id'], 'Long report, tops only.')
    assert (described['description'], described['document_id']) == ('Long report, tops only.', added['document_id'])
    assert alice.documents.every() == [described]


def test_a_spreadsheet_is_refused_by_the_server_with_its_sentence(web):
    alice = client(web, 'alice', 'delegate')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z: z.writestr('xl/workbook.xml', b'<workbook/>')
    with pytest.raises(Exception) as refused:
        alice.documents.add(('project', None), out.getvalue(), taxonomy=[TYPE], name='Tops', description='A table.')
    assert served.sentence('spreadsheet') in str(refused.value)
