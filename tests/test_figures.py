"""E191 s1 C4 (D-11), offline: `client.figures` is a FigureClient bound to the client; each method sends one request to
its route with the body the gateway's request model names and a new command id on each write unless one is given; the
SDK refuses nothing itself. `attachments/add` is bounded at the schema's ceiling (F7), every other request as before.
Figures sent with a version take command ids made from the version's (F16); the words name labels, never ids.

Mutations (break -> RED): a `delete` added to the attachment set; the add bound left at MAX_REQUEST_BYTES; a random
figure command id; an id or digest in `figure_line`."""
import base64
import re
import uuid

import pytest

from ophiolite import figures
from ophiolite.client import Client
from ophiolite.errors import Refused
from ophiolite.publish import FIGURE_REQUEST_BYTES, MAX_REQUEST_BYTES, operation_path

V = {'asset_id': 'a1', 'revision': 'f' * 64}


class Fake:
    def __init__(self, refuse=()):
        self.sent, self.refuse = [], refuse

    def _post(self, area, operation, body, retry=False):
        self.sent.append((area, operation, body, retry))
        if body.get('label') in self.refuse: raise Refused('This is not a figure.')
        return {'answered': operation, 'label': body.get('label')}

    def _post_file(self, area, operation, body, answer):
        self.sent.append((area, operation, body, None))
        answer['content-type'] = 'application/pdf'
        return b'%PDF'


def test_client_figures_is_a_figure_client_bound_to_the_client():
    client = Client('http://127.0.0.1:1', 'p')
    assert isinstance(client.figures, figures.FigureClient) and client.figures._client is client


@pytest.mark.parametrize('operation', ['add', 'list', 'read', 'withdraw'])
def test_the_four_attachment_operations_have_their_paths(operation):
    assert operation_path('p one', 'attachments', operation) == '/api/v1/projects/p%20one/attachments/' + operation


def test_no_other_attachment_operation_is_sent():
    with pytest.raises(Refused, match='Unsupported application operation.'):
        operation_path('p', 'attachments', 'delete')


def test_the_add_bound_is_the_schema_ceiling_and_every_other_request_keeps_its_own():
    assert FIGURE_REQUEST_BYTES == 22_402_392 == 4 * -(-16 * 1024 * 1024 // 3) + 32_768
    sent = []
    client = Client('http://127.0.0.1:1', 'p')
    client._post_bytes = lambda area, operation, raw, **kw: sent.append((operation, len(raw)))
    big = 'A' * (MAX_REQUEST_BYTES + 4)
    client._post('attachments', 'add', {'command_id': 'k', **V, 'label': 'L', 'content': big})
    with pytest.raises(Exception):
        client._post('attachments', 'list', {**V, 'cursor': big})
    assert [s[0] for s in sent] == ['add']


def test_each_method_sends_the_body_its_route_names(tmp_path):
    fake = Fake()
    f = figures.FigureClient(fake)
    (tmp_path / 'plot.png').write_bytes(b'png-bytes')
    f.attach(V, tmp_path / 'plot.png', label='Plot', command_id='k1')
    f.attach(('a1', 'f' * 64), b'raw', label='Raw', command_id='k2')
    f.attach(V, tmp_path / 'plot.png', label='Named', file_name='other.png', command_id='k3')
    f.list(V); f.list(V, limit=5, cursor='n')
    assert f.read('c' * 32) == (b'%PDF', 'application/pdf')
    f.withdraw('c' * 32, reason='Superseded', command_id='k4')
    assert fake.sent == [
        ('attachments', 'add', {'command_id': 'k1', **V, 'label': 'Plot', 'content': base64.b64encode(b'png-bytes').decode(), 'file_name': 'plot.png'}, True),
        ('attachments', 'add', {'command_id': 'k2', **V, 'label': 'Raw', 'content': base64.b64encode(b'raw').decode()}, True),
        ('attachments', 'add', {'command_id': 'k3', **V, 'label': 'Named', 'content': base64.b64encode(b'png-bytes').decode(), 'file_name': 'other.png'}, True),
        ('attachments', 'list', V, True), ('attachments', 'list', {**V, 'limit': 5, 'cursor': 'n'}, True),
        ('attachments', 'read', {'attachment_id': 'c' * 32}, None),
        ('attachments', 'withdraw', {'command_id': 'k4', 'attachment_id': 'c' * 32, 'reason': 'Superseded'}, True)]
    f.attach(V, b'x', label='New'); f.withdraw('c' * 32, reason='r')
    assert fake.sent[-2][2]['command_id'] != fake.sent[-1][2]['command_id'] and fake.sent[-2][2]['command_id'].startswith('figure-')


def test_figures_with_a_version_take_ids_from_its_command_and_a_refusal_is_named_by_label():
    fake = Fake(refuse={'Drawing'})
    out = figures.FigureClient(fake).attach_each(V, [{'label': 'Plot', 'file': b'a'}, {'label': 'Drawing', 'file': b'b'}], 'parent-1')
    ids = [s[2]['command_id'] for s in fake.sent]
    assert ids == [str(uuid.uuid5(figures.NAMESPACE, 'parent-1/figure/0')), str(uuid.uuid5(figures.NAMESPACE, 'parent-1/figure/1'))]
    assert out == [{'answered': 'add', 'label': 'Plot'}, {'label': 'Drawing', 'refused': 'This is not a figure.'}]
    assert figures.refused_line(out) == 'The version stands; this figure was not attached: Drawing (This is not a figure.).'
    assert figures.refused_line(out[:1]) is None


FIGURE = {'attachment_id': 'c' * 32, 'label': 'Crossplot', 'media_type': 'image/png', 'bytes': 40_090, 'sha256': 'd' * 64,
          'added_by': {'person': 'alice', 'agent': 'agent-1', 'job': 'e' * 32}, 'added_at': '2026-11-24T10:00:00Z', 'withdrawal': None}


def test_a_figure_line_names_its_label_type_size_and_people_and_no_id():
    line = figures.figure_line(FIGURE)
    assert line == 'Crossplot: PNG image, 39.2 KiB, added by alice (an assistant for them) on 2026-11-24'
    gone = figures.figure_line({**FIGURE, 'added_by': {'person': 'bob', 'agent': None, 'job': None},
                                'withdrawal': {'by': {'person': 'alice'}, 'at': '2026-11-25T08:00:00Z', 'reason': 'Superseded'}})
    assert gone == 'Crossplot: PNG image, 39.2 KiB, added by bob on 2026-11-24; withdrawn by alice on 2026-11-25: Superseded'
    assert not re.search(r'[0-9a-f]{32}', line + gone)
    assert [figures.size_words(n) for n in (12, 1024, 1536, 16 * 1024 * 1024)] == ['12 bytes', '1 KiB', '1.5 KiB', '16 MiB']


def test_newest_takes_the_first_listed_with_the_label_and_counts_them():
    listed = [{'label': 'A', 'n': 3}, {'label': 'B', 'n': 2}, {'label': 'A', 'n': 1}]
    assert figures.newest(listed, 'A') == ({'label': 'A', 'n': 3}, 2) and figures.newest(listed, 'C') == (None, 0)
