"""E222 s1: documents — a PDF, a PNG or a JPEG kept with a well, a wellbore, a survey or the project, with its OSDU
type, a name and a short description (`ophiolite.document/1`).

`client.documents` is a `DocumentClient` bound to the client. Each method sends one request and returns the served
answer as it is; the server decides what is a document, how large one may be, which types are listed, and who may add,
read or describe one (a refusal is the server's, with its reason in `error.details['reason']`). Each write sends a new
command id unless one is given; the same id with the same body answers the stored document.
"""
import base64
import uuid
from pathlib import Path

PARENTS = ('well', 'wellbore', 'survey', 'project')


def _file(file, file_name):
    """(bytes, file_name) from a path or bytes; a path's name is the file name unless one is given."""
    if isinstance(file, (bytes, bytearray)): return bytes(file), file_name
    path = Path(file)
    return path.read_bytes(), file_name if file_name is not None else path.name


def _parent(client, parent):
    """{kind, id} from a dict or a (kind, id) pair; the project parent is the client's project when no id is given."""
    kind, ident = (parent['kind'], parent.get('id')) if isinstance(parent, dict) else tuple(parent)
    return {'kind': kind, 'id': client.project if kind == 'project' and ident is None else ident}


class DocumentClient:
    """The documents of one project, through `client._post`. Nothing is refused here: the server checks every request
    and every right."""

    def __init__(self, client):
        self._client = client

    def add(self, parent, file, *, taxonomy, name, description, file_name=None, command_id=None):
        """Add a document (a path or bytes) to a parent ({kind, id} or a pair; ('project', None) is this project) with
        its OSDU type codes, a name and a description; the answer is the document's record."""
        data, sent_name = _file(file, file_name)
        body = {'command_id': command_id or 'document-%s' % uuid.uuid4().hex, 'parent': _parent(self._client, parent),
                'taxonomy': list(taxonomy), 'name': name, 'description': description, 'content': base64.b64encode(data).decode('ascii')}
        if sent_name is not None: body['file_name'] = sent_name
        return self._client._post('documents', 'add', body, retry=True)

    def list(self, parent=None, *, limit=None, cursor=None):
        """One page of the project's documents, or one parent's, newest first {documents, next}; follow `next` as
        `cursor`. Only documents whose parent you may read are listed."""
        body = {}
        if parent is not None: body['parent'] = _parent(self._client, parent)
        if limit is not None: body['limit'] = limit
        if cursor is not None: body['cursor'] = cursor
        return self._client._post('documents', 'list', body, retry=True)

    def read(self, document_id):
        """A document's bytes and type: (bytes, media_type), the type it was kept as."""
        answer = {}
        data = self._client._post_file('documents', 'read', {'document_id': document_id}, answer)
        return data, answer.get('content-type')

    def describe(self, document_id, description, *, command_id=None):
        """Give a document a new short description (a person's act); the earlier ones are kept."""
        return self._client._post('documents', 'describe', {'command_id': command_id or 'describe-%s' % uuid.uuid4().hex,
                                                            'document_id': document_id, 'description': description}, retry=True)

    def every(self, parent=None):
        """Every document you may read, of the project or one parent, newest first (each page followed)."""
        found, cursor = [], None
        while True:
            page = self.list(parent, cursor=cursor)
            found += page['documents']
            cursor = page.get('next')
            if not cursor: return found
