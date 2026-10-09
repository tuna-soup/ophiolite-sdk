"""E95 C6 (row 79): the reported provider and model become two attributes on the caller's current span; the library
creates no span, never claims an invocation, and puts no instruction, label, conversation, digest or id anywhere."""
import json
import sys
import httpx
import pytest
from ophiolite import _genai
from ophiolite.agents import AgentClient
from test_agent_evidence import EVIDENCE_16

sdk_trace = pytest.importorskip('opentelemetry.sdk.trace')
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

LABELLED = {**EVIDENCE_16, 'model': {**EVIDENCE_16['model'], 'label': 'Claude Sonnet 5.5'},
            'conversation': {**EVIDENCE_16['conversation'], 'label': 'Gamma ray tidy'}}


@pytest.fixture
def tracer(monkeypatch):
    """The caller's provider is the process provider too, so any span the library made would be exported here."""
    exporter = InMemorySpanExporter()
    provider = sdk_trace.TracerProvider(); provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, 'get_tracer_provider', lambda: provider)
    return provider.get_tracer('caller'), exporter


def agent():
    return AgentClient('https://x.example', 'p', 'oph_agent_test', http=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={'hash': 'h' * 64, 'state': 'pending', 'evidence': 'ev-1'}))))


def test_the_pinned_convention_names():
    assert (_genai.SEMCONV, _genai.PROVIDER_NAME, _genai.REQUEST_MODEL) == ('1.37.0', 'gen_ai.provider.name', 'gen_ai.request.model')


def test_the_callers_span_gains_exactly_two_attributes_and_no_span_is_created(tracer):
    tracer, exporter = tracer
    with tracer.start_as_current_span('framework step', attributes={'step': 4}):
        agent().propose('applications/publish', {'id': 'run-1'}, evidence=LABELLED)
    [span] = exporter.get_finished_spans()  # the caller's own span, and no other
    assert dict(span.attributes) == {'step': 4, 'gen_ai.provider.name': 'anthropic', 'gen_ai.request.model': 'claude-sonnet-5-5'}
    assert 'gen_ai.operation.name' not in span.attributes and 'gen_ai.system' not in span.attributes


def test_no_text_label_conversation_digest_or_id_reaches_the_span(tracer):
    tracer, exporter = tracer
    with tracer.start_as_current_span('framework step'):
        agent().propose('applications/publish', {'id': 'run-1'}, evidence=LABELLED)
    [span] = exporter.get_finished_spans()
    stored = json.dumps([dict(span.attributes), [(e.name, dict(e.attributes)) for e in span.events], span.status.description, span.name])
    for fragment in ('Tidy', 'gamma', 'HON-GT-01', 'Claude Sonnet 5.5', 'Gamma ray tidy', 'thread-4471', 'notebook', 'well-tidy', 'ev-1', 'h' * 16):
        assert fragment not in stored, fragment


@pytest.mark.parametrize('evidence', [None, {**EVIDENCE_16, 'model': {'provider': 'anthropic'}}, {**EVIDENCE_16, 'model': {'id': 'claude-sonnet-5-5'}},
                                      {**EVIDENCE_16, 'model': {'provider': '', 'id': ''}}, {**EVIDENCE_16, 'model': 'claude'}, 'not a mapping'])
def test_nothing_is_set_without_a_provider_and_a_model(tracer, evidence):
    tracer, exporter = tracer
    with tracer.start_as_current_span('framework step'):
        _genai.annotate(evidence)
    [span] = exporter.get_finished_spans()
    assert dict(span.attributes) == {}


def test_nothing_is_set_and_nothing_raises_without_a_recording_span(tracer):
    tracer, exporter = tracer
    assert not trace.get_current_span().is_recording()
    agent().propose('applications/publish', {'id': 'run-1'}, evidence=EVIDENCE_16)
    assert exporter.get_finished_spans() == ()


def test_the_calls_work_without_opentelemetry(monkeypatch):
    monkeypatch.setitem(sys.modules, 'opentelemetry', None)  # import fails as when it is not installed
    assert agent().propose('applications/publish', {'id': 'run-1'}, evidence=EVIDENCE_16)['evidence'] == 'ev-1'
