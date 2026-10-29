"""E67b: read an organisation's teams and the access history (who had access to what, and when) with an access key.

`Client.access_history()`, `Client.access_teams()` and `Client.export_access_history()` read the client's project
(project administrators); `Account.teams()`, `Account.team()`, `Account.person_history()` and
`Account.export_person_history()` read an organisation (its owners). They authenticate with an access key (or a browser
session's delegate): the deployment refuses an application you signed in to (`HISTORY_GRANT_REFUSED`) and an agent
(`HISTORY_AGENT_REFUSED`), so a saved sign-in is not sent at all. Nothing here changes a team or an access.
"""
import os
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from . import _client_header
from .errors import PermissionRefused, Refused, Unavailable

ACCESS_KEY_NEEDED = ('Teams and the access history are read with an access key; a saved sign-in is refused. '
                     'Create an access key on your account page and use it instead.')
FORMATS = ('csv', 'jsonl')
EXPORT_BYTES = 64 * 1024 * 1024  # at most 10,000 entries on the server's side


def history_filters(kinds=None, person=None, actor=None, since=None, until=None, project=None):
    """The server's filter object: only the filters given (since -> from, until -> to)."""
    out = {'kinds': list(kinds) if kinds is not None else None, 'person': person, 'actor': actor, 'from': since, 'to': until, 'project': project}
    return {k: v for k, v in out.items() if v is not None}


def _headers(credential, url, project):
    if credential is None: raise Refused(ACCESS_KEY_NEEDED, code='access-key-required')
    if getattr(credential, 'kind', None) == 'application': raise Refused(ACCESS_KEY_NEEDED, code='access-key-required')
    headers = credential.headers(url, project) if project is not None else credential.discovery_headers(url)
    return {**_client_header.stamp(headers), 'Content-Type': 'application/json'}


def _post(http, url, path, body, headers, *, raw=False):
    """One POST; a refusal carries the deployment's own sentence and code."""
    from . import application_transport as policy
    from .publish import json_bytes
    try:
        with http.stream('POST', url + path, content=json_bytes(body), headers=headers, follow_redirects=False) as response:
            if not response.is_success:
                head = policy.head_bytes(response)
                if response.status_code == 403:
                    meta = policy.envelope(response, head)
                    raise PermissionRefused(meta.get('message') or 'This credential cannot read this.', status=403, code=meta.get('code'), **policy.carried(meta))
                policy.status(response, path.rsplit('/', 1)[-1], head)
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > (EXPORT_BYTES if raw else policy.MAX_RESPONSE): raise policy.too_large()
    except httpx.HTTPError:
        raise Unavailable('Cannot reach the service. Check its address and network connection.', code='unreachable') from None
    return bytes(content) if raw else policy.decode(bytes(content))


def _pages(read, body, limit):
    """Every page, following next_cursor; an entry repeated across pages is refused (a cursor not followed)."""
    out, seen, cursor = [], set(), None
    while True:
        page = read({**body, 'limit': limit, **({'cursor': cursor} if cursor else {})})
        if not isinstance(page, dict) or not isinstance(page.get('entries'), list): raise Unavailable('Invalid access history response.')
        for entry in page['entries']:
            if entry.get('id') in seen: raise Unavailable('The access history repeated an entry across pages.')
            seen.add(entry.get('id')); out.append(entry)
        cursor = page.get('next_cursor')
        if not cursor: return out


def _export(read, body, fmt, dest):
    """The whole history as CSV or JSON Lines, written to DEST (a private partial file, then replaced)."""
    if fmt not in FORMATS: raise Refused('Choose csv or jsonl.')
    raw = read({**body, 'format': fmt})
    dest = Path(dest)
    partial = dest.with_name('.' + dest.name + '.' + uuid.uuid4().hex[:12] + '.partial')
    try:
        with partial.open('xb') as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
        os.replace(partial, dest)
    except BaseException:
        partial.unlink(missing_ok=True); raise
    return dest


class AccessHistoryClient:
    """Mixed into Client: the project's access history and teams (project administrators)."""

    def _access_read(self, operation, body, *, raw=False):
        if 'project_id' in body and body['project_id'] != self.project: raise Refused('The request belongs to another project.')
        path = '/api/v1/projects/' + quote(self.project, safe='') + '/access/' + operation
        return _post(self.http, self.url, path, {'project_id': self.project, **body}, _headers(self.credential, self.url, self.project), raw=raw)

    def access_history(self, *, kinds=None, person=None, actor=None, since=None, until=None, limit=100):
        """Every entry of the project's access history, newest first (all pages): dicts with id, at, kind, parts, actor,
        on_behalf_of, credential_kind, through, subject, project, from, to, role and details."""
        body = {'filters': history_filters(kinds, person, actor, since, until)}
        return _pages(lambda sent: self._access_read('history', sent), body, limit)

    def export_access_history(self, format, dest, *, kinds=None, person=None, actor=None, since=None, until=None):
        """The project's access history as one CSV or JSON Lines file at DEST (the bytes the deployment sends)."""
        body = {'filters': history_filters(kinds, person, actor, since, until)}
        return _export(lambda sent: self._access_read('history', sent, raw=True), body, format, dest)

    def access_teams(self):
        """The teams this project can use (its organisation's) and every team granted on it: id, name, role, can_compute, stranded."""
        page = self._access_read('teams', {})
        if not isinstance(page, dict) or not isinstance(page.get('teams'), list): raise Unavailable('Invalid teams response.')
        return page['teams']


class AccessHistoryAccount:
    """Mixed into Account: an organisation's teams and one person's access history (organisation owners)."""

    def _organization_read(self, operation, body, *, raw=False):
        return _post(self.http, self.url, '/api/v1/organizations/' + operation, body, _headers(self.credential, self.url, None), raw=raw)

    def teams(self, organization_id):
        """The organisation's teams: id, name, members, projects, adoptable."""
        page = self._organization_read('teams', {'organization_id': organization_id})
        if not isinstance(page, dict) or not isinstance(page.get('teams'), list): raise Unavailable('Invalid teams response.')
        return page['teams']

    def team(self, organization_id, team_id):
        """One team: its people, the projects you administer by name, the rest counted."""
        return self._organization_read('team', {'organization_id': organization_id, 'team_id': team_id})

    def person_history(self, organization_id, user_id, *, kinds=None, actor=None, since=None, until=None, project=None, limit=100):
        """Every entry of one person's access history in the organisation, newest first (all pages); the projects you do not
        administer are left out."""
        body = {'organization_id': organization_id, 'user_id': user_id, 'filters': history_filters(kinds, None, actor, since, until, project)}
        return _pages(lambda sent: self._organization_read('person-history', sent), body, limit)

    def export_person_history(self, organization_id, user_id, format, dest, *, kinds=None, actor=None, since=None, until=None, project=None):
        """One person's access history as one CSV or JSON Lines file at DEST."""
        body = {'organization_id': organization_id, 'user_id': user_id, 'filters': history_filters(kinds, None, actor, since, until, project)}
        return _export(lambda sent: self._organization_read('person-history', sent, raw=True), body, format, dest)
