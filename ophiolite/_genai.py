"""E95: the model an agent reported, as two attributes on the caller's current span.

Ophiolite does not invoke a GenAI model, so this library creates no GenAI span and never sets
`gen_ai.operation.name` (that would claim an invocation it did not make). When the optional
`opentelemetry-api` imports, a span is current and recording, and the evidence names a provider and
a model, the span gains exactly `gen_ai.provider.name` and `gen_ai.request.model`; otherwise nothing
is set and nothing raises. The instruction, conversation, labels, digests and ids never go to a span.
The names are those of OpenTelemetry semantic conventions v1.37.0 (GenAI, status Development); a
rename changes this module and its pin test only."""

SEMCONV = '1.37.0'
PROVIDER_NAME = 'gen_ai.provider.name'
REQUEST_MODEL = 'gen_ai.request.model'


def annotate(evidence):
    """Set the reported provider and model on the current recording span, if there is one."""
    try:
        from opentelemetry import trace
    except ImportError:
        return
    try:
        model = evidence.get('model') if isinstance(evidence, dict) else None
        provider, ident = (model.get('provider'), model.get('id')) if isinstance(model, dict) else (None, None)
        if not (isinstance(provider, str) and provider and isinstance(ident, str) and ident): return
        span = trace.get_current_span()
        if not span.is_recording(): return
        span.set_attributes({PROVIDER_NAME: provider, REQUEST_MODEL: ident})
    except Exception:  # telemetry never changes what the call does
        return
