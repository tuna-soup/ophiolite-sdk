"""E91: table templates and the NLOG start sample.

    client.templates()                                   # the table targets with a template, their units and formats
    t = client.template('well-tops', 'csv', length='m')   # the file the deployment renders: t.bytes, t.filename
    t.save('tops.csv')
    client.start_sample()                                # an administrator adds the NLOG sample: the log and 2,222 wells

A template is the header of the target in the units and coordinate system you choose and one `#` example row the import
skips; fill it in and add it like any table. The bytes are the deployment's, kept as sent (an Excel file is never
decoded as text). A refusal keeps the deployment's sentence (choose a coordinate system, no sample in this deployment,
only an administrator adds wells).
"""
import uuid
from pathlib import Path

from .errors import Refused, VerificationFailed

FORMATS = ('csv', 'xlsx')
LENGTHS = ('m', 'ft')


def said(call):
    """A refusal in the deployment's own sentence; any other error as the transport raised it."""
    from .errors import OphioliteError
    try: return call()
    except OphioliteError as error:
        if getattr(error, 'status', None) not in (400, 403) or not error.server_message: raise
        raise type(error)(error.server_message, status=error.status, code=error.code, request_id=error.request_id, remedy=error.remedy,
                          docs=error.docs, server_message=error.server_message, details=error.details) from error


class Template:
    """One rendered template: `target`, `format`, `bytes` and `filename` (`<target>-template.<format>`)."""
    def __init__(self, target, format, data):
        self.target, self.format, self.bytes = target, format, data
        self.filename = '%s-template.%s' % (target, format)

    def save(self, path=None):
        """Write the bytes to `path` (default: ./<target>-template.<format>) and return the path."""
        out = Path(path) if path is not None else Path(self.filename)
        out.write_bytes(self.bytes)
        return out

    def __repr__(self):
        return 'Template(%r, %r, %d bytes)' % (self.target, self.format, len(self.bytes))


def listing(client):
    """[{target, display_name, lengths, needs_crs, formats}] as the deployment serves them."""
    answer = said(lambda: client._post('templates', 'list', {}, retry=True))
    rows = answer.get('templates') if isinstance(answer, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get('target'), str) for r in rows):
        raise VerificationFailed('The template list answered outside its documented shape.')
    return rows


def template(client, target, format='csv', length='m', crs=None, reference=None):
    if format not in FORMATS: raise Refused('Choose the format csv or xlsx.')
    body = {'target': target, 'length': length, **({'crs': crs} if crs else {}), **({'reference': reference} if reference else {})}
    data = said(lambda: client._post('templates', format, body, retry=True, answer_bytes=True))
    if not data: raise VerificationFailed('The template arrived empty.')
    return Template(target, format, data)


def start_sample(client, command_id=None, progress=None):
    """Start the NLOG sample and step its wells import to the end; the same `command_id` answers the same run.
    Returns {run_id, log, wells, statement}: the log as the run report shows it, the wells import's final status."""
    answer = said(lambda: client._post('upload-runs', 'sample', {'command_id': command_id or uuid.uuid4().hex}))
    if not isinstance(answer, dict) or not all(k in answer for k in ('run_id', 'log', 'wells_import', 'wells')):
        raise VerificationFailed('The sample answered outside its documented shape.')
    wells = answer['wells']
    while wells.get('state') == 'importing':
        if progress: progress(wells)
        wells = said(lambda: client._post('table-imports', 'step', {'id': answer['wells_import']}))
    return {'run_id': answer['run_id'], 'log': answer['log'], 'wells': wells, 'statement': answer.get('statement')}
