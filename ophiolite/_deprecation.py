"""E148: one warning when a server says a route is deprecated.

A deprecated route's successful answer carries `Deprecation` (RFC 9745, `@<epoch seconds>`), `Sunset` (RFC 8594) and,
when there is one, `Link: <successor>; rel="successor-version"`. Each public client owns one `Notifier` (`Client` and
so `AsyncClient`, `Account`, `AgentClient` with its `reads` client, `OAuthApp`); the helpers that read server answers
for them take it as an argument. `note` only reads the response's headers, so sync and async share it, and it never
raises or changes the response: advisory metadata never blocks an answer. Nothing is installed on an httpx client, so
an injected transport is never mutated.
"""
import re
import warnings
from datetime import datetime, timezone
from urllib.parse import urlsplit


class OphioliteDeprecationWarning(UserWarning):
    """The server answered a deprecated route (once per route per client). Defined here, not in errors.py, which the
    QGIS plug-in carries byte for byte."""


PROJECT = re.compile(r'^(/api/v1/projects/)[^/]+(/.+)$')  # a project route; /api/v1/projects/list keeps its path
LINK = re.compile(r'<([^>]*)>\s*((?:;\s*[^,;]+)*)')


def template(url):
    """The request path with the project id replaced by {project}; the query is dropped."""
    path = urlsplit(str(url)).path
    found = PROJECT.match(path)
    return found.group(1) + '{project}' + found.group(2) if found else path


def since(value):
    found = re.fullmatch(r'@(-?\d+)', value.strip())
    if not found: return '"%s"' % value
    try: return datetime.fromtimestamp(int(found.group(1)), timezone.utc).strftime('%Y-%m-%d')
    except (OverflowError, OSError, ValueError): return '"%s"' % value


def successor(links):
    """The target of the Link value whose rel is successor-version, else None."""
    for header in links:
        for target, params in LINK.findall(header):
            rels = re.findall(r'rel\s*=\s*"?([^";]+)"?', params)
            if any('successor-version' in rel.split() for rel in rels): return target
    return None


def message(method, url, headers):
    target = successor(headers.get_list('Link') if hasattr(headers, 'get_list') else [headers.get('Link', '')])
    sunset = headers.get('Sunset')
    return '%s %s is deprecated (since %s); %s; successor %s' % (
        method.upper(), template(url), since(headers['Deprecation']), 'sunset ' + sunset if sunset else 'sunset not stated',
        target or 'none named')


class Notifier:
    """The once-set of one client: (method, route template) pairs already warned about."""

    def __init__(self):
        self.seen = set()

    def note(self, method, url, response):
        try:
            headers = response.headers
            if 'Deprecation' not in headers: return
            key = (method.upper(), template(url))
            if key in self.seen: return
            self.seen.add(key)
            text = message(method, url, headers)
        except Exception:
            return
        warnings.warn(text, OphioliteDeprecationWarning, stacklevel=3)


def of(owner):
    """The owner's notifier, or None (an object built without the client constructor)."""
    return getattr(owner, '_notifier', None)


def note(notifier, method, url, response):
    if notifier is not None: notifier.note(method, url, response)
