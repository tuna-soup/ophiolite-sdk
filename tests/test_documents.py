"""E222 s1 C6, offline: `client.documents` is a DocumentClient bound to the client; each method sends one request to its
route with the body the gateway's request model names and a new command id on each write unless one is given; the SDK
refuses nothing itself. `documents/add` is bounded at the schema's ceiling (the figure bound), every other request as
before.

Mutations (break -> RED): a `delete` added to the documents set; the add bound left at MAX_REQUEST_BYTES; the project
parent sent without the client's project; a fixed command id."""
import base64

import pytest

from ophiolite import documents
from ophiolite.client import Client
from ophiolite.errors import Refused
from ophiolite.publish import MAX_REQUEST_BYTES, operation_path

TYPE = 'GEOLOGY.EndOfWellReportGeological'


class Fake:
    project = 'p'

    def __init__(self):
        self.sent = []

    def _post(self, area, operation, body, retry=False):
        self.sent.append((area, operation, body, retry))
        return {'answered': operation}

    def _post_file(self, area, operation, body, answer):
        self.sent.append((area, operation, body, None))
        answer['content-type'] = 'application/pdf'
        return b'%PDF'


def test_client_documents_is_a_document_client_bound_to_the_client():
    client = Client('http://127.0.0.1:1', 'p')
    assert isinstance(client.documents, documents.DocumentClient) and client.documents._client is client


@pytest.mark.parametrize('operation', ['add', 'list', 'read', 'describe'])
def test_the_four_document_operations_have_their_paths(operation):
    assert operation_path('p one', 'documents', operation) == '/api/v1/projects/p%20one/documents/' + operation


def test_no_other_document_operation_is_sent():
    with pytest.raises(Refused, match='Unsupported application operation.'):
        operation_path('p', 'documents', 'delete')


def test_the_add_bound_is_the_schema_ceiling_and_every_other_request_keeps_its_own():
    sent = []
    client = Client('http://127.0.0.1:1', 'p')
    client._post_bytes = lambda area, operation, raw, **kw: sent.append((operation, len(raw)))
    big = 'A' * (MAX_REQUEST_BYTES + 4)
    client._post('documents', 'add', {'command_id': 'k', 'parent': {'kind': 'project', 'id': 'p'}, 'taxonomy': [TYPE], 'name': 'N',
                                      'description': 'D', 'content': big})
    with pytest.raises(Exception):
        client._post('documents', 'list', {'cursor': big})
    assert [s[0] for s in sent] == ['add']


def test_each_method_sends_the_body_its_route_names(tmp_path):
    fake = Fake()
    d = documents.DocumentClient(fake)
    (tmp_path / 'report.pdf').write_bytes(b'pdf-bytes')
    d.add(('wellbore', 'wb-1'), tmp_path / 'report.pdf', taxonomy=[TYPE], name='Report', description='Tops.', command_id='k1')
    d.add({'kind': 'project'}, b'raw', taxonomy=(TYPE,), name='Plan', description='Plan.', command_id='k2')
    d.list(); d.list(('survey', 's-1'), limit=5, cursor='7')
    assert d.read('c' * 32) == (b'%PDF', 'application/pdf')
    d.describe('c' * 32, 'Tops only.', command_id='k3')
    assert fake.sent == [
        ('documents', 'add', {'command_id': 'k1', 'parent': {'kind': 'wellbore', 'id': 'wb-1'}, 'taxonomy': [TYPE], 'name': 'Report',
                              'description': 'Tops.', 'content': base64.b64encode(b'pdf-bytes').decode(), 'file_name': 'report.pdf'}, True),
        ('documents', 'add', {'command_id': 'k2', 'parent': {'kind': 'project', 'id': 'p'}, 'taxonomy': [TYPE], 'name': 'Plan',
                              'description': 'Plan.', 'content': base64.b64encode(b'raw').decode()}, True),
        ('documents', 'list', {}, True), ('documents', 'list', {'parent': {'kind': 'survey', 'id': 's-1'}, 'limit': 5, 'cursor': '7'}, True),
        ('documents', 'read', {'document_id': 'c' * 32}, None),
        ('documents', 'describe', {'command_id': 'k3', 'document_id': 'c' * 32, 'description': 'Tops only.'}, True)]
    d.add(('well', 'w'), b'x', taxonomy=[TYPE], name='N', description='D'); d.describe('c' * 32, 'r')
    assert fake.sent[-2][2]['command_id'].startswith('document-') and fake.sent[-1][2]['command_id'].startswith('describe-')
    assert fake.sent[-2][2]['command_id'] != fake.sent[-1][2]['command_id']
