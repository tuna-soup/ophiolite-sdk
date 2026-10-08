"""E93 C6 against the in-process gateway (Platform C2/C5): the library's literal report becomes the action row's
`through` and its sentence; an active trace is the row's trace context."""
import json

from test_in_process_publish import web, shared, app, service, client  # noqa: F401


def actions(web):
    with web.a.journal.lock:
        rows = [json.loads(r[0]) for r in web.a.journal.db.execute("SELECT body FROM activity_events WHERE event_id LIKE 'act_%' ORDER BY seq")]
    return rows


def test_the_python_library_is_named_on_the_row_and_in_its_sentence(web):  # noqa: F811
    from project_gateway import record
    from project_gateway.tests.test_applications import LAS
    before = len(actions(web))
    alice = client(web, 'alice', 'delegate')
    alice.upload_las(LAS.encode(), name='Header input', attribution='Original synthetic fixture', audience=['alice'], rights_confirmed=True, command_id='header-upload')
    (row,) = actions(web)[before:]
    through = row['data']['record']['through']
    assert through['raw'] == 'ophiolite-python/0.1.0' and through['client'] == 'ophiolite-python' and through['version'] == '0.1.0'
    assert record.through_words(through) == 'Through the Python library 0.1.0'
    assert row['data']['record']['trace_context'] is None  # no active trace: none recorded


def test_an_active_trace_is_on_the_row(web):  # noqa: F811
    import pytest
    sdk = pytest.importorskip('opentelemetry.sdk.trace')
    from project_gateway.tests.test_applications import LAS
    before = len(actions(web))
    alice = client(web, 'alice', 'delegate')
    with sdk.TracerProvider().get_tracer('test').start_as_current_span('caller') as span:
        alice.upload_las(LAS.encode(), name='Traced input', attribution='Original synthetic fixture', audience=['alice'], rights_confirmed=True, command_id='traced-upload')
        trace_id = '%032x' % span.get_span_context().trace_id
    (row,) = actions(web)[before:]
    assert trace_id in json.dumps(row['data']['record']['trace_context'])
