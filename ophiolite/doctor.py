"""E51a: `ophiolite doctor --online` — six stages, stopping at the first failure.

address             the name resolves
tls                 the server answers its public contracts index over this address (https: a trusted certificate)
credential-arrived  a credential was given and the server received it (not refused as no-credential or malformed)
credential-accepted the server accepted it (projects/list answered)
project-readable    the credential reaches the project and its wells description (GET .../features)
features            one collections request and one first items page (limit=100): numberMatched, else "at least N"

A refusal is reported with the server's own sentence, its stage and remedy. The credential goes only to the given
origin: no redirect is followed (a redirect fails its stage), no `next` link is requested. A private deployment that
cannot be reached is reported as "cannot reach the server: check Tailscale". The credential never appears in the report.
"""
import ipaddress
import json
import socket
from urllib.parse import quote, urlsplit

import httpx

from . import auth
from ._core import origin
from .errors import OphioliteError

STAGES = ('address', 'tls', 'credential-arrived', 'credential-accepted', 'project-readable', 'features')
EXIT = {'address': 5, 'tls': 5, 'credential-arrived': 3, 'credential-accepted': 3, 'project-readable': 3, 'features': 4}
TIMEOUT = 20
EXPIRES = 'not available for a key given directly'
TAILSCALE = 'cannot reach the server: check Tailscale (this deployment is private to its tailnet)'
TAILNET = (ipaddress.ip_network('100.64.0.0/10'), ipaddress.ip_network('fd7a:115c:a1e0::/48'))


class Report(dict):
    """The report (its documented --json shape); exit_code is the failed stage's exit code, 0 when every stage passed."""
    exit_code = 0


def private(host):
    """A tailnet name or address: unreachable means Tailscale is not connected."""
    if not host: return False
    if host.endswith('.ts.net'): return True
    try: return any(ipaddress.ip_address(host) in net for net in TAILNET)
    except ValueError: return False


class Stop(Exception):
    def __init__(self, stage, detail, **extra):
        super().__init__(detail); self.stage, self.detail, self.extra = stage, detail, extra


def refused(stage, response, fallback):
    """A Stop for a refused answer: the server's sentence, its stage and remedy (from the error envelope)."""
    from .application_transport import envelope
    meta = envelope(response)
    extra = {k: v for k, v in (('server_stage', meta.get('stage')), ('code', meta.get('code')), ('remedy', meta.get('remedy')), ('docs', meta.get('docs'))) if v}
    return Stop(stage, (meta.get('message') or fallback) + ' (HTTP %d)' % response.status_code, **extra)


def run(url, project, credential, *, notes=(), http=None):
    """Every stage in order until one fails; returns a Report."""
    report = Report(stages=[], normalised=list(notes))
    url = origin(url); parts = urlsplit(url); host = parts.hostname
    def passed(stage, detail, **extra): report['stages'].append({'stage': stage, 'ok': True, 'detail': detail, **extra})
    injected = http is not None; owns = not injected
    http = http or httpx.Client(timeout=TIMEOUT, follow_redirects=False, trust_env=False)
    try:
        try: socket.getaddrinfo(host, parts.port or (443 if parts.scheme == 'https' else 80))
        except OSError: raise Stop('address', 'The address %s does not resolve' % host + ('; ' + TAILSCALE if private(host) else '')) from None
        passed('address', '%s resolves' % host)
        try: remote = auth.request(url + '/api/v1/contracts', http=http) if injected else auth.request(url + '/api/v1/contracts')
        except OphioliteError: raise Stop('tls', diagnose(url, host)) from None
        report['server_contracts'] = remote.get('version', 'unreported')
        passed('tls', 'https with a trusted certificate' if parts.scheme == 'https' else 'http (not encrypted): use only on this computer or a private network')
        if credential is None:
            raise Stop('credential-arrived', 'No credential was given: use --key-file FILE, --key-stdin, --key or OPHIOLITE_ACCESS_KEY')
        reach(report, url, project, credential, http if injected else None)
        readable(report, url, project, credential, http)
        features(report, url, project, credential, http)
    except Stop as stop:
        report['stages'].append({'stage': stop.stage, 'ok': False, 'detail': stop.detail, **stop.extra})
        report.exit_code = EXIT[stop.stage]
    finally:
        if owns: http.close()
    report['ok'] = report.exit_code == 0
    return report


def diagnose(url, host):
    """Why the contracts index did not answer: a certificate, an unreachable server, or an answer that is not the index."""
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False, trust_env=False) as probe: answer = probe.get(url + '/api/v1/contracts')
    except httpx.ConnectError as error:
        if 'CERTIFICATE' in str(error).upper() or 'SSL' in str(error).upper():
            return "The server's certificate is not trusted by this computer (TLS)"
        return TAILSCALE if private(host) else 'cannot reach the server: check the address and your network'
    except httpx.TimeoutException:
        return TAILSCALE if private(host) else 'cannot reach the server: it did not answer in time'
    except httpx.HTTPError:
        return 'cannot reach the server: the connection failed'
    return 'The server answered %d where the contracts index was expected: is this an Ophiolite address?' % answer.status_code


def reach(report, url, project, credential, http):
    """credential-arrived and credential-accepted, through the discovery route (as before E51a: reach and reach_ok)."""
    from . import account as accounts
    from .errors import AuthenticationRequired, PermissionRefused
    try:
        with accounts.Account(url, credential, http) as account: ids = [p['id'] for p in account.projects()]
    except (AuthenticationRequired, PermissionRefused) as error:
        report.update(reach='no - ' + str(error), reach_ok=False)
        extra = {k: v for k, v in (('server_stage', error.stage), ('code', error.code), ('remedy', error.remedy), ('docs', error.docs)) if v}
        sentence = (error.server_message or str(error)) + ' (HTTP %s)' % error.status
        if error.status == 401 or error.stage in ('no-credential', 'malformed-credential'): raise Stop('credential-arrived', sentence, **extra) from None
        report['stages'].append({'stage': 'credential-arrived', 'ok': True, 'detail': 'the server received a bearer credential'})
        raise Stop('credential-accepted', sentence, **extra) from None
    except OphioliteError as error:
        report.update(reach='no - ' + str(error), reach_ok=False)
        raise Stop('credential-arrived', str(error)) from None
    report['stages'].append({'stage': 'credential-arrived', 'ok': True, 'detail': 'the server received a bearer credential'})
    report['stages'].append({'stage': 'credential-accepted', 'ok': True, 'detail': 'the credential reaches %d project%s' % (len(ids), '' if len(ids) == 1 else 's')})
    reached = project in ids
    report.update(reach='yes' if reached else 'no - this credential does not reach ' + project, reach_ok=reached,
                  credential_expires=credential.summary().get('expires_at') if credential.kind != 'bearer' else None,
                  expires=EXPIRES if credential.kind == 'bearer' else (credential.summary().get('expires_at') or 'not recorded'))
    if not reached: raise Stop('project-readable', 'This credential does not reach %s; it reaches %s' % (project, ', '.join(ids) or 'no project'))


def get(stage, http, url, headers, what):
    try: response = http.get(url, headers=headers, follow_redirects=False)
    except httpx.TimeoutException: raise Stop(stage, 'The server did not answer %s in time' % what) from None
    except httpx.HTTPError: raise Stop(stage, 'The connection failed while reading %s' % what) from None
    if 300 <= response.status_code < 400:
        raise Stop(stage, 'The server redirected %s to another address; the redirect was not followed and the credential was not sent there' % what)
    return response


def body(stage, response, what):
    if response.status_code != 200: raise refused(stage, response, 'The server refused %s' % what)
    try: value = json.loads(response.content)
    except (ValueError, UnicodeError): raise Stop(stage, 'The answer for %s is not JSON' % what) from None
    if not isinstance(value, dict): raise Stop(stage, 'The answer for %s is not a JSON object' % what)
    return value


def readable(report, url, project, credential, http):
    base = url + '/api/v1/projects/' + quote(project, safe='')
    headers = credential.headers(url, project)
    body('project-readable', get('project-readable', http, base + '/features', headers, 'the project'), 'the project')
    try:  # the credential's scope (best effort; a refusal here does not fail the stage)
        answer = http.post(base + '/capabilities/describe', json={}, headers=headers, follow_redirects=False)
        scopes = answer.json().get('scopes') if answer.status_code == 200 else None
    except (httpx.HTTPError, ValueError, AttributeError): scopes = None
    report['scope'] = scopes if isinstance(scopes, list) else None
    report['stages'].append({'stage': 'project-readable', 'ok': True, 'detail': 'the project %s is readable' % project + (' (scope: %s)' % ', '.join(scopes) if isinstance(scopes, list) else '')})


def features(report, url, project, credential, http):
    base = url + '/api/v1/projects/' + quote(project, safe='') + '/features'
    headers = credential.headers(url, project)
    collections = body('features', get('features', http, base + '/collections', headers, 'the collections'), 'the collections').get('collections')
    ids = [c.get('id') for c in collections or [] if isinstance(c, dict)]
    if 'wells' not in ids: raise Stop('features', 'The project offers no wells collection')
    page = body('features', get('features', http, base + '/collections/wells/items?limit=100', headers, 'the first page of wells'), 'the first page of wells')
    returned = page.get('numberReturned') if isinstance(page.get('numberReturned'), int) else len(page.get('features') or [])
    matched = page.get('numberMatched')
    detail = '%d wells' % matched if isinstance(matched, int) else 'at least %d wells' % returned
    stage = {'stage': 'features', 'ok': True, 'detail': detail}
    if (matched if isinstance(matched, int) else returned) == 0: stage['warning'] = 'The project has no wells to show yet'
    report['stages'].append(stage)
