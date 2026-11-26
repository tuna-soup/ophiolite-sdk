"""E191 s1: figures — a PNG, a JPEG or a PDF kept with the one item version it backs (`ophiolite.attachment/1`).

`client.figures` is a `FigureClient` bound to the client. Each method sends one request and returns the served answer
as it is; the server decides what is a figure, how large one may be, and who may add, read or withdraw one (a refusal
is the server's, with its reason in `error.details['reason']`). Each write sends a new command id unless one is given;
the same id with the same body answers the stored figure.

`figure_line` and `newest` say an answer in words and choose a figure by its label, as `ophiolite results figures`
does (labels, types, sizes and people; no ids or digests).
"""
import base64
import uuid
from pathlib import Path

from .chains import _page, _version

# E191 s1 (F16): a figure sent with a version takes its command id from the version's, so a retry of the same call
# answers the stored figures and adds none. Published; the same in every process.
NAMESPACE = uuid.UUID('3a5d0c64-9a7e-5b1c-8f2e-6d4b2a917c03')
TYPE_WORDS = {'image/png': 'PNG image', 'image/jpeg': 'JPEG image', 'application/pdf': 'PDF document'}


def _file(file, file_name):
    """(bytes, file_name) from a path or bytes; a path's name is the file name unless one is given."""
    if isinstance(file, (bytes, bytearray)): return bytes(file), file_name
    path = Path(file)
    return path.read_bytes(), file_name if file_name is not None else path.name


class FigureClient:
    """The figures of one project's item versions, through `client._post`. Nothing is refused here: the server checks
    every request and every right."""

    def __init__(self, client):
        self._client = client

    def attach(self, version, file, *, label, file_name=None, command_id=None):
        """Attach a figure (a path or bytes) to one item version ({asset_id, revision} or a pair); the answer is the
        figure's record (`ophiolite.attachment/1`)."""
        data, name = _file(file, file_name)
        body = {'command_id': command_id or 'figure-%s' % uuid.uuid4().hex, **_version(version), 'label': label,
                'content': base64.b64encode(data).decode('ascii')}
        if name is not None: body['file_name'] = name
        return self._client._post('attachments', 'add', body, retry=True)

    def list(self, version, *, limit=None, cursor=None):
        """One page of a version's figures, newest first {attachments, next}; follow `next` as `cursor`."""
        return self._client._post('attachments', 'list', _page(_version(version), limit, cursor), retry=True)

    def read(self, attachment_id):
        """A figure's bytes and type: (bytes, media_type). A withdrawn figure is refused with its reason."""
        answer = {}
        data = self._client._post_file('attachments', 'read', {'attachment_id': attachment_id}, answer)
        return data, answer.get('content-type')

    def withdraw(self, attachment_id, *, reason, command_id=None):
        """Withdraw a figure with your reason; its record stays with the version and its bytes are no longer served."""
        return self._client._post('attachments', 'withdraw', {'command_id': command_id or 'withdraw-%s' % uuid.uuid4().hex,
                                                              'attachment_id': attachment_id, 'reason': reason}, retry=True)

    def every(self, version):
        """Every figure of a version, newest first (each page followed)."""
        found, cursor = [], None
        while True:
            page = self.list(version, cursor=cursor)
            found += page['attachments']
            cursor = page.get('next')
            if not cursor: return found

    def attach_each(self, version, figures, parent_command_id):
        """E191 s1 (Q2): figures sent after their version's answer, one `add` each, as `figures=` sends them. Each
        answer is the figure's record, or {'label', 'refused'} with the server's sentence; the version stands."""
        out = []
        for index, figure in enumerate(figures):
            command = str(uuid.uuid5(NAMESPACE, '%s/figure/%d' % (parent_command_id, index)))
            try:
                out.append(self.attach(version, figure['file'], label=figure['label'], file_name=figure.get('file_name'), command_id=command))
            except Exception as refusal:  # every refusal is the server's (or the network's); the version is not undone
                out.append({'label': figure['label'], 'refused': str(refusal)})
        return out


def refused_line(figures):
    """Q2: the figures not attached, each by its label, and that the version stands; None when every one was."""
    failed = [f for f in figures if 'refused' in f]
    if not failed: return None
    return 'The version stands; %s not attached: %s.' % ('this figure was' if len(failed) == 1 else 'these figures were',
                                                          '; '.join('%s (%s)' % (f['label'], f['refused']) for f in failed))


def size_words(n):
    for unit, size in (('MiB', 1024 * 1024), ('KiB', 1024)):
        if n >= size: return '%s %s' % (('%.1f' % (n / size)).rstrip('0').rstrip('.'), unit)
    return '%d bytes' % n


def figure_line(figure):
    """One figure in words: its label, type, size, who added it and when, and a withdrawal with its reason."""
    by = figure['added_by']
    who = by['person'] if not by.get('agent') else '%s (an assistant for them)' % by['person']
    line = '%s: %s, %s, added by %s on %s' % (figure['label'], TYPE_WORDS.get(figure['media_type'], figure['media_type']),
                                              size_words(figure['bytes']), who, figure['added_at'][:10])
    if figure.get('withdrawal'):
        line += '; withdrawn by %s on %s: %s' % (figure['withdrawal']['by']['person'], figure['withdrawal']['at'][:10], figure['withdrawal']['reason'])
    return line


def newest(figures, label):
    """E189's rule: the newest figure with the label, whatever its state, and how many carry it; (None, 0) for none."""
    named = [f for f in figures if f['label'] == label]
    return (named[0] if named else None), len(named)
