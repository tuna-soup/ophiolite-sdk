"""E183 s2b C1: `upload_las(..., curve_declaration=...)` and `upload_data` send the caller's curve declaration, only when
given, in one request or with `begin` (strategy E183-s2-curve-declaration, rev 2 closed: T1.1 to T1.4; T1.2's gateway
half, T1.5 and T1.6 are in tests/gateway/test_curve_declaration_gateway.py).

Every value is synthetic. The frozen request below was written by this SDK at 8d547c035, before this lane."""
import base64
import json

import pytest

from ophiolite.client import Client
from ophiolite.errors import ValidationFailed
from ophiolite.publish import upload_metadata

DECLARED = {'well': 'SYNTHETIC-W1', 'depth_kind': 'MD', 'depth_datum': 'unknown'}
SEND = dict(name='Synthetic log', attribution='Synthetic test', audience=['alice'], rights_confirmed=True, command_id='plain')
# D-2: the request of a LAS upload without a declaration, as this SDK sent it before E183 s2b.
FROZEN_BODY = {'project_id': 'p', 'command_id': 'plain', 'filename': 'input.las', 'name': 'Synthetic log', 'attribution': 'Synthetic test',
               'audience': ['alice'], 'rights_confirmed': True, 'well_notes': ''}
FROZEN_HEADER = ('eyJwcm9qZWN0X2lkIjoicCIsImNvbW1hbmRfaWQiOiJwbGFpbiIsImZpbGVuYW1lIjoiaW5wdXQubGFzIiwibmFtZSI6IlN5bnRoZXRpYyBsb2ciLCJhdHRy'
                 'aWJ1dGlvbiI6IlN5bnRoZXRpYyB0ZXN0IiwiYXVkaWVuY2UiOlsiYWxpY2UiXSwicmlnaHRzX2NvbmZpcm1lZCI6dHJ1ZSwid2VsbF9ub3RlcyI6IiJ9')
LAS_ONLY = 'Only a LAS file takes a curve declaration.'
TOO_BIG = 'Upload details exceed the supported header size.'


class Recorded(Client):
    """A client that records what it would send and sends nothing."""
    def __init__(self):
        self.project, self.sent = 'p', []

    def _send(self, source, body, extra):
        self.sent.append((body, extra))
        return 'sent'

    def _post(self, *args, **kwargs): raise AssertionError('nothing may be sent')
    _post_bytes = _post


def header(extra):
    return json.loads(base64.b64decode(extra['X-Ophiolite-Upload']))


def test_t11_without_it_the_request_and_header_are_as_before():
    """D-2. Mutation: the field always sent (as None): red."""
    client = Recorded()
    client.upload_las(b'~Version\n', **SEND)
    client.upload_data(b'~Version\n', profile='las2/1', filename='input.las', **SEND)
    for body, extra in client.sent:
        assert body == FROZEN_BODY
        assert extra == {'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': FROZEN_HEADER}


def test_t12_with_it_the_header_carries_the_three_fields_as_given():
    client = Recorded()
    client.upload_las(b'~Version\n', curve_declaration=DECLARED, **SEND)
    client.upload_data(b'~Version\n', profile='las2/1', filename='input.las', curve_declaration=DECLARED, **SEND)
    for body, extra in client.sent:
        assert body == {**FROZEN_BODY, 'curve_declaration': DECLARED} and header(extra) == body
    assert header(client.sent[0][1])['curve_declaration'] == {'well': 'SYNTHETIC-W1', 'depth_kind': 'MD', 'depth_datum': 'unknown'}


def test_t13_begin_carries_the_declaration_and_publish_does_not():
    """Mutation: the declaration passed to publish (or not to begin): red."""
    sent = []

    class Parts(Client):
        def __init__(self): pass
        def _post(self, area, operation, body, retry=False):
            sent.append((operation, body))
            return {'upload_id': 'u', 'state': 'checked'} if operation == 'begin' else {'asset_id': 'a'}
        def _transfer_parts(self, file, view): return view

    file = type('File', (), {'size': 2048})()
    for body in (FROZEN_BODY, {**FROZEN_BODY, 'curve_declaration': DECLARED}):
        Parts()._upload_parts(file, '0' * 64, body)
    begin = {'command_id': 'plain', 'filename': 'input.las', 'profile': 'las2/1', 'declared': {}, 'bytes': 2048, 'sha256': '0' * 64}
    assert [b for operation, b in sent if operation == 'begin'] == [begin, {**begin, 'curve_declaration': DECLARED}]
    publishes = [b for operation, b in sent if operation == 'publish']
    assert len(publishes) == 2 and all('curve_declaration' not in b for b in publishes)
    assert publishes[0] == publishes[1]


@pytest.mark.parametrize('declaration,words', [
    ({**DECLARED, 'well': ''}, 'Invalid request fields: curve_declaration.well'),
    ({**DECLARED, 'well': '   '}, 'Invalid request fields: curve_declaration.well'),
    ({**DECLARED, 'depth_datum': ' padded'}, 'Invalid request fields: curve_declaration.depth_datum'),
    ({**DECLARED, 'well': 'padded '}, 'Invalid request fields: curve_declaration.well'),
    ({**DECLARED, 'depth_kind': 'KB'}, 'Invalid request fields: curve_declaration.depth_kind'),
    ({**DECLARED, 'depth_kind': 'md'}, 'Invalid request fields: curve_declaration.depth_kind'),
    ({'well': 'SYNTHETIC-W1'}, 'Invalid request fields: curve_declaration.depth_datum, curve_declaration.depth_kind'),
    ({**DECLARED, 'extra': 'x'}, 'Invalid request fields: curve_declaration.extra'),
    ('SYNTHETIC-W1', 'Invalid request fields: curve_declaration'),
])
def test_t14_a_malformed_declaration_is_refused_before_any_request(declaration, words):
    client = Recorded()
    with pytest.raises(ValidationFailed) as no: client.upload_las(b'~Version\n', curve_declaration=declaration, **SEND)
    assert no.value.violations == (words,) and client.sent == []


def test_t14_only_a_las_file_takes_it():
    client = Recorded()
    with pytest.raises(ValidationFailed) as no:
        client.upload_data(b'well,top,md\n', profile='well-tops-csv/1', curve_declaration=DECLARED, **SEND)
    assert no.value.violations == (LAS_ONLY,) and client.sent == []


def test_t14_the_header_limit_counts_the_declaration():
    common = dict(filename='input.las', name='n', attribution='a', rights_confirmed=True, audience=['u%02d' % i + 'v' * 147 for i in range(35)])
    upload_metadata('p', 'c', **common)  # fits without it
    long = {'well': 'W' * 512, 'depth_kind': 'TVDSS', 'depth_datum': 'D' * 512}
    with pytest.raises(ValidationFailed) as no: upload_metadata('p', 'c', curve_declaration=long, **common)
    assert no.value.violations == (TOO_BIG,)


def test_t16_a_partial_declaration_is_not_completed_from_anywhere():
    """D-1 (C1 (b)): `well` only is refused, never filled in; the caller's text is sent as given, never trimmed."""
    client = Recorded()
    with pytest.raises(ValidationFailed): client.upload_las(b'~Well\nWELL. SYNTHETIC-W9 : well\n', curve_declaration={'well': 'SYNTHETIC-W1'}, **SEND)
    assert client.sent == []
    client.upload_las(b'~Well\nWELL. SYNTHETIC-W9 : well\n', curve_declaration={**DECLARED, 'well': 'a  b'}, **SEND)
    assert header(client.sent[0][1])['curve_declaration'] == {**DECLARED, 'well': 'a  b'}
