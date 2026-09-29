"""E27: which projects and organisations a credential reaches, before choosing a project.

A credential is bound to what it was made for (an access key or an approved application to one
project, a browser sign-in to every project the person has), so `Account.projects()` returns
exactly that bound — for a single-project credential, one project. Opening a project is the ordinary
`Client`, which checks the project as before: discovery never relaxes a project-bound call.
"""
import json
from urllib.parse import quote
import httpx
from ._core import origin
from .errors import AuthenticationRequired, PermissionRefused, Refused, Unavailable
from .models.api import OrganizationsPage, ProjectsPage


def checked(model, page, message):
    """E31: a discovery answer as documented (Unavailable otherwise, as before), handed on unchanged."""
    from pydantic import ValidationError
    try: model.model_validate(page)
    except (ValidationError, ValueError, TypeError): raise Unavailable(message) from None
    return page


class Account:
    def __init__(self, url, credential, http=None):
        self.url, self.credential = origin(url), credential
        if credential is None: raise Refused('Choose a credential (an access key or a saved sign-in).')
        self._owns_http = http is None
        self.http = http or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)

    def close(self):
        if self._owns_http: self.http.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def _discover(self, operation, body):
        headers = self.credential.discovery_headers(self.url)
        try: response = self.http.post(self.url + '/api/v1/projects/' + quote(operation, safe=''), json=body, headers=headers, follow_redirects=False)
        except httpx.HTTPError: raise Unavailable('Cannot reach the service. Check its address and network connection.', code='unreachable') from None
        if response.status_code != 200:
            from .application_transport import envelope, carried
            meta = envelope(response); more = {'code': meta.get('code'), **carried(meta)}  # E31
            if response.status_code == 401: raise AuthenticationRequired('Sign in again, or check the access key.', status=401, **more)
            if response.status_code == 403: raise PermissionRefused('This credential no longer reaches its project.', status=403, **more)
            raise Unavailable('Project discovery failed; check the service and retry.', meta.get('remedy', ''), status=response.status_code, **more)
        try: value = response.json()
        except (ValueError, UnicodeError): raise Unavailable('Project discovery answered with something that is not JSON.') from None
        if not isinstance(value, dict): raise Unavailable('Invalid project discovery response.')
        return value

    def projects(self, *, limit=50):
        """Every project this credential reaches (all pages): dicts with id, name, role, can_administer, organization_id."""
        out, cursor, seen = [], None, set()
        while True:
            page = self._discover('list', {'limit': limit, **({'cursor': cursor} if cursor else {})})
            checked(ProjectsPage, page, 'Invalid project discovery response.')  # E31: the documented page, then the same rows
            rows = page.get('projects')
            for row in rows:
                if row.get('id') in seen: raise Unavailable('Project discovery repeated a project across pages.')
                seen.add(row.get('id')); out.append(row)
            cursor = page.get('next_cursor')
            if not cursor: return out

    def organizations(self):
        """Organisations holding at least one project this credential reaches."""
        page = self._discover('organizations', {})
        checked(OrganizationsPage, page, 'Invalid organisation discovery response.')
        return page['organizations']

    def client(self, project):
        """The ordinary project client (its own project check applies)."""
        from .client import Client
        return Client(self.url, project, self.credential, None if self._owns_http else self.http)


def connect(url, credential, http=None):
    """An Account for this gateway and credential."""
    return Account(url, credential, http)
