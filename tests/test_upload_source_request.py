"""E122 s6 C2: `upload_data(..., application_source=...)` sends s4a's source block as the upload request's `source`,
only when given, so an upload without one keeps its exact request (and retry fingerprint); `source` stays the file."""
import base64
import inspect
import json

import pytest

from ophiolite.errors import ValidationFailed
from ophiolite.publish import SOURCE_SYSTEM, upload_metadata

F3 = {'system': 'application:opendtect', 'instance': 'F3_Demo', 'container': 'F3_Demo', 'id': '100050.2'}
COMMON = dict(filename='well.las', name='Well', attribution='Synthetic test', audience=['alice'], rights_confirmed=True)
PLAIN = {'project_id': 'p', 'command_id': 'plain', 'filename': 'well.las', 'name': 'Well', 'attribution': 'Synthetic test', 'audience': ['alice'],
         'rights_confirmed': True, 'well_notes': ''}


def header(extra):
    return json.loads(base64.b64decode(extra['X-Ophiolite-Upload']))


def test_an_upload_without_a_source_sends_the_request_it_sent_before():
    value, extra = upload_metadata('p', 'plain', **COMMON)
    assert value == PLAIN and header(extra) == PLAIN


def test_an_application_source_travels_as_the_requests_source():
    value, extra = upload_metadata('p', 'plain', application_source=F3, **COMMON)
    assert value == {**PLAIN, 'source': F3} and header(extra) == {**PLAIN, 'source': F3}
    lean, _ = upload_metadata('p', 'plain', application_source={'system': 'application:opendtect', 'id': '100050.2', 'instance': None}, **COMMON)
    assert lean['source'] == {'system': 'application:opendtect', 'id': '100050.2'}
    asked, _ = upload_metadata('p', 'plain', application_source={**F3, 'as_new': True}, **COMMON)
    assert asked['source'] == {**F3, 'as_new': True}  # the server answers it (D4), as it does a send's


def test_a_malformed_block_is_refused_before_anything_is_sent():
    with pytest.raises(ValidationFailed) as error: upload_metadata('p', 'plain', application_source={**F3, 'system': 'opendtect'}, **COMMON)
    assert error.value.violations == (SOURCE_SYSTEM,)


def test_a_header_over_its_limit_is_refused_with_its_sentence():
    big = {**F3, 'id': 'x' * 256, 'container': 'y' * 256, 'instance': 'z' * 160}
    upload_metadata('p', 'plain', **{**COMMON, 'attribution': 'a' * 500, 'well_notes': 'n' * 1000, 'audience': ['u%02d' % i + 'v' * 120 for i in range(30)]})
    with pytest.raises(ValidationFailed) as error:
        upload_metadata('p', 'plain', application_source=big, **{**COMMON, 'attribution': 'a' * 500, 'well_notes': 'n' * 1000,
                                                                'audience': ['u%02d' % i + 'v' * 120 for i in range(30)]})
    assert error.value.violations == ('Upload details exceed the supported header size.',)


def test_the_file_keyword_is_still_source():
    from ophiolite.client import Client
    params = inspect.signature(Client.upload_data).parameters
    assert list(params)[1] == 'source' and params['application_source'].default is None
