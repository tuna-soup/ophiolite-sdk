"""E60: public repositories (NLOG) as sources, in Python — the same words as the workspace's.

`client.public_repositories.search("nlog", name="HON-GT")` lists the boreholes the service answers for a name or code
(or a field), in the service's order, with whether a well with that identity is in this project and you can see it.
`preview("nlog", codes)` says what would come in; neither keeps anything. `bring_in("nlog", codes, include=[...],
audience=[...])` is a project administrator's import: the gateway lists every file of the boreholes and reads each one
from the service itself (nothing is sent from this computer), and the folder upload's report comes back with what the
service could not serve (`report.not_read`). Pressing it is the confirmation that the service's terms allow it.
`check("nlog")` asks the service again and reports what changed; nothing is replaced, appended or moved.
`attribution(result)` lists the public sources a derived result was made from, with the sentence a page shows.

A refusal is raised as a typed error carrying the sentence the workspace shows: the service is not switched on, only an
administrator may bring data in, the service is not answering, or it asked Ophiolite to slow down.
"""
import base64
import json
import time
import uuid

from .errors import Busy, IntegrityConflict, OphioliteError, PermissionRefused, Refused
from .models.api import (PublicSources, RepositoryCatalogue, RepositoryCheck, RepositoryImport, RepositoryPreview, RepositorySearch,
                         UploadRun, UploadRunStep)
from .upload_runs import CLAIM_WAIT, Report
from .well_imports import _checked

# the gateway's own sentences (Platform public_repositories.py) that name a refusal the journey words differently
NOT_ENABLED = 'This public repository is not enabled on this deployment.'
INCLUDE = ('location', 'tops', 'survey', 'logs', 'all-logs')


class RepositoryNotEnabled(PermissionRefused): code = 'repository-not-enabled'


class RepositoryAdministratorsOnly(PermissionRefused): code = 'repository-administrators-only'


class RepositoryUnavailable(Busy): code = 'repository-unavailable'


class RepositoryRateLimited(RepositoryUnavailable): code = 'repository-rate-limited'


def said(service):
    """The service as the sentences name it (the gateway's rule: its short name, else its id in capitals)."""
    return service.upper()


def _typed(error, service, operation):
    """A refusal of public-repositories in the journey's words, the server's sentence kept as `server_message`."""
    name, server = said(service), error.server_message or ''
    carried = dict(status=error.status, request_id=error.request_id, docs=error.docs, server_message=error.server_message, details=error.details)
    if isinstance(error, PermissionRefused) and server == NOT_ENABLED:
        return RepositoryNotEnabled('%s is not switched on for this Ophiolite installation. Ask the person who runs it to allow %s.' % (name, name), **carried)
    if isinstance(error, PermissionRefused) and operation == 'import' and server != NOT_ENABLED and 'keep copies' not in server:
        return RepositoryAdministratorsOnly('Only a project administrator can add data from %s.' % name, **carried)
    if error.code == 'repository-unavailable':
        if '(rate-limited)' in server:
            return RepositoryRateLimited('%s asked Ophiolite to slow down. Search again later.' % name, retry_after=getattr(error, 'retry_after', 0), **carried)
        return RepositoryUnavailable('%s is not answering right now. Nothing was changed. Try again in a few minutes.' % name,
                                     retry_after=getattr(error, 'retry_after', 0), **carried)
    return None


class BroughtIn(Report):
    """The folder upload's report of a `bring_in`, with what the service could not serve (`not_read`: code, name, kind,
    outcome) and the service it came from."""

    def __init__(self, view, service, not_read):
        super().__init__(view)
        self.service, self.not_read = service, list(not_read)

    @property
    def ok(self): return super().ok and not self.not_read

    def text(self):
        lines = [super().text()]
        lines += ['  %s%s: not read from %s (%s)' % (r['code'], '/' + r['name'] if r['name'] else '', said(self.service), r['outcome']) for r in self.not_read]
        return '\n'.join(lines)

    def to_dict(self): return {'upload': self.view, 'not_read': self.not_read}


class Attribution:
    """The public sources a derived result was made from: `records` as stored with the revision (service, licence,
    terms address, document, retrieval time) and `lines`, the sentence a page shows per service. Empty when the
    result was not made from a public repository's file."""

    def __init__(self, asset_id, sources):
        self.asset_id = asset_id
        self.records = list((sources or {}).get('records') or [])
        self.lines = list((sources or {}).get('lines') or [])

    @property
    def services(self): return sorted({r['service_id'] for r in self.records})

    def __bool__(self): return bool(self.records)

    def text(self): return '\n'.join(line['sentence'] or 'Source: %s. Terms of use: %s' % (said(line['service_id']), line['terms_url']) for line in self.lines)

    def to_dict(self): return {'asset_id': self.asset_id, 'records': self.records, 'lines': self.lines}

    def __repr__(self): return '<Attribution %s: %s>' % (self.asset_id, ', '.join(self.services) or 'no public source')


class PublicRepositories:
    def __init__(self, client):
        self.client = client

    def _call(self, operation, body, model, service=None, retry=False):
        try: answer = self.client._post('public-repositories', operation, body, retry=retry)
        except OphioliteError as error:
            typed = _typed(error, service, operation) if service else None
            if typed is None: raise
            raise typed from error
        return _checked(model, answer, 'public repository ' + operation)

    def catalogue(self):
        """The public repositories this deployment reads, with each one's terms and what can be brought in."""
        return self._call('catalogue', {}, RepositoryCatalogue)

    def search(self, service, *, name=None, field=None, side=None):
        """The boreholes SERVICE lists for a name or code (at least three characters) or a field, in its order. Nothing is
        kept. Each row says whether a well with that identity is in this project and you can see it."""
        if (name is None) == (field is None): raise Refused('Search by name or by field.')
        body = {'service': service, **{k: v for k, v in (('name', name), ('field', field), ('side', side)) if v is not None}}
        return self._call('search', body, RepositorySearch, service)['items']

    def preview(self, service, codes):
        """What would come in from these boreholes (position, tops, surveys, log files); nothing is kept."""
        return self._call('preview', {'service': service, 'codes': list(codes)}, RepositoryPreview, service)['items']

    def bring_in(self, service, codes, *, audience, include=None, folder_name=None, command_id=None, progress=None):
        """A project administrator's import of these boreholes: `include` chooses location, tops, survey, logs (the
        composite logs) and all-logs (the service's default when omitted); `audience` names who may read what comes in
        (never a project default). The gateway reads every file from the service; returns the report (`BroughtIn`)."""
        body = {'service': service, 'codes': list(codes), 'audience': list(audience), 'command_id': command_id or uuid.uuid4().hex,
                **({'include': list(include)} if include is not None else {}), **({'folder_name': folder_name} if folder_name else {})}
        started = self._call('import', body, RepositoryImport, service, retry=True)  # the command id makes a repeat safe
        view = self._drive(started['run']['run_id'], service, progress)
        return BroughtIn(view, service, started['not_read'])

    def check(self, service, codes=None):
        """Ask SERVICE again for every file of it you can read (or of these boreholes) and report what changed:
        `sentence` and per file `state` and `changed` (bytes, meaning). A report only: nothing is replaced or appended."""
        return self._call('check', {'service': service, **({'codes': list(codes)} if codes else {})}, RepositoryCheck, service)

    def attribution(self, result):
        """The public sources of a derived result (a receipt, a selection or an asset id) you may read."""
        asset = result if isinstance(result, str) else getattr(result, 'asset_id', None) or result['asset_id']
        info = self.client._post('publications', 'info', {'asset_id': asset})
        sources = info.get('public_sources') if isinstance(info, dict) else None
        if sources is not None: _checked(PublicSources, sources, 'publication information')
        return Attribution(asset, sources)

    # --- the run's files, each read by the gateway from the service -----------------------------------------------------

    def _status(self, run_id):
        return _checked(UploadRun, self.client._post('upload-runs', 'status', {'run_id': run_id}, retry=True), 'folder upload status')

    def _file(self, run_id, ordinal):
        header = {'project_id': self.client.project, 'run_id': run_id, 'ordinal': ordinal, 'mode': 'head', 'repository': True}
        extra = {'Content-Type': 'application/octet-stream', 'X-Ophiolite-Upload': base64.b64encode(json.dumps(header, separators=(',', ':')).encode()).decode()}
        return _checked(UploadRunStep, self.client._post_bytes('upload-runs', 'file', b'', extra_headers=extra, retry=True), 'folder upload file')

    def _drive(self, run_id, service, progress, passes=3):
        """Ask the gateway to read each waiting file, in order; a file another request holds is waited for (at most
        CLAIM_WAIT seconds). Returns the run's final view."""
        until, done = time.monotonic() + CLAIM_WAIT, 0
        while done < passes:
            view = self._status(run_id)
            if view['state'] != 'open': return view
            waiting = [i for i in view['items'] if i['state'] == 'waiting' and i['role'] == 'primary']
            if not waiting:
                if not any(i['state'] == 'reading' and i['role'] == 'primary' for i in view['items']) or time.monotonic() > until: return view
                time.sleep(5.0); continue
            done += 1
            for item in waiting:
                try: self._file(run_id, item['ordinal'])
                except IntegrityConflict as error:
                    if error.code == 'run-ended': return self._status(run_id)
                    if error.code != 'claimed': raise
                except OphioliteError as error:
                    typed = _typed(error, service, 'file')
                    if typed is None: raise
                    raise typed from error
                if progress: progress(Report(self._status(run_id)))
        return self._status(run_id)
