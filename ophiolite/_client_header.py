"""E93: what this program tells the gateway about itself, on every gateway request: `X-Ophiolite-Client` names the
product and version only (no host name, no path, no user text), and `traceparent` carries the caller's active
OpenTelemetry trace when there is one. The gateway shows it as "Through the Python library 0.1.0"; it is a report
from the client, never an authorisation (the server resolves the credential on its own)."""
import contextvars

from ._version import __version__

HEADER = 'X-Ophiolite-Client'
_NAME = contextvars.ContextVar('ophiolite_client_name', default='ophiolite-python')


def name(product):
    """Set the product for this context (the command line sets `ophiolite-cli`)."""
    _NAME.set(product)


def value():
    return '%s/%s' % (_NAME.get(), __version__)


def traceparent():
    """The W3C traceparent of the active OpenTelemetry span, or None (no OpenTelemetry, or no valid span). Never invented."""
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    context = trace.get_current_span().get_span_context()
    if not context.is_valid: return None
    return '00-%032x-%016x-%02x' % (context.trace_id, context.span_id, int(context.trace_flags))


def headers():
    trace = traceparent()
    return {HEADER: value(), **({'traceparent': trace} if trace else {})}


def stamp(given):
    """`given` (authorization and the like) with this program's report added; a caller's own value is not replaced."""
    return {**headers(), **(given or {})}
