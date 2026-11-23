"""E93: what this program tells the gateway about itself, on every gateway request: `X-Ophiolite-Client` names the
product and version only (no host name, no path, no user text), and `traceparent` carries the caller's active
OpenTelemetry trace when there is one. The gateway shows it as "Through the Python library 0.1.0"; it is a report
from the client, never an authorisation (the server resolves the credential on its own)."""
import contextvars
import re

from ._version import __version__
from .errors import Refused

HEADER = 'X-Ophiolite-Client'
LIMIT = 128  # the gateway drops a longer report (record.CLIENT_LIMIT)
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,39}')  # the gateway's grammar (record._TOKEN); widened there first, never here
NAMED = 'Name the application and its version as two short words, such as ("ophiolite-opendtect", "0.1.0").'
HOSTED = 'Name the application before the host it runs in.'
_NAME = contextvars.ContextVar('ophiolite_client_name', default='ophiolite-python')


def name(product):
    """Set the product for this context (the command line sets `ophiolite-cli`)."""
    _NAME.set(product)


def value():
    return '%s/%s' % (_NAME.get(), __version__)


def _pair(given):
    if not (isinstance(given, tuple) and len(given) == 2 and all(isinstance(p, str) and TOKEN.fullmatch(p) for p in given)): raise Refused(NAMED)
    return '%s/%s' % given


def sender(application=None, host=None):
    """E182 s1: the report of a program that names itself and, when it knows it, the application it runs in, as
    `name/version[; host=name/version]`; None names nothing (this library's own report). Refused before any request
    when it would not reach the gateway as given."""
    if application is None:
        if host is not None: raise Refused(HOSTED)
        return None
    said = _pair(application) + ('' if host is None else '; host=' + _pair(host))
    if len(said) > LIMIT: raise Refused(NAMED)
    return said


def traceparent():
    """The W3C traceparent of the active OpenTelemetry span, or None (no OpenTelemetry, or no valid span). Never invented."""
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    context = trace.get_current_span().get_span_context()
    if not context.is_valid: return None
    return '00-%032x-%016x-%02x' % (context.trace_id, context.span_id, int(context.trace_flags))


def headers(sender=None):
    trace = traceparent()
    return {HEADER: sender or value(), **({'traceparent': trace} if trace else {})}


def stamp(given, sender=None):
    """`given` (authorization and the like) with this program's report added (SENDER, a client's own name, before the
    context's); a caller's own value is not replaced."""
    return {**headers(sender), **(given or {})}
