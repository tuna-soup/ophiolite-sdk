"""The worker against a synthetic event log: a first run resyncs and saves the checkpoint; a second run only catches up
from the saved cursor; follow prints one line per change."""
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ophiolite import Client, Credential
from ophiolite.testing import fixture_server
import worker

EVENT = lambda cursor: {'project': 'p', 'cursor': cursor, 'epoch': 'e1', 'kind': 'entity-changed', 'subject_kind': 'entity', 'subject_id': 'well-1',
                        'generation': cursor, 'revision': None, 'actor_kind': 'person', 'actor': 'alice', 'at': 1.0}
WELL = {'entity_id': 'well-1', 'kind': 'well', 'name': 'W1', 'owner': 'alice', 'generation': 1}


class Log:
    def __init__(self): self.head, self.calls = 2, []
    def __call__(self, method, path, raw, headers):
        operation = '/'.join(path.split('?')[0].rsplit('/', 2)[-2:]); self.calls.append(operation)
        body = json.loads(raw or b'{}')
        if operation == 'changes/head': return 200, {'epoch': 'e1', 'cursor': self.head}
        if operation == 'changes/list':
            events = [EVENT(c) for c in range(body['after'] + 1, self.head + 1)]
            return 200, {'epoch': 'e1', 'changes': events, 'cursor': self.head, 'has_more': False}
        if operation == 'changes/stream':
            page = {'epoch': 'e1', 'changes': [EVENT(self.head + 1)], 'cursor': self.head + 1, 'has_more': False}
            return 200, ('event: change\nid: e1:%d\ndata: %s\n\n' % (self.head + 1, json.dumps(page))).encode()
        if operation == 'capabilities/describe': return 200, {'operations': [{'area': 'entities', 'operation': 'list', 'allowed': True}]}
        if operation == 'entities/list': return 200, {'entities': [WELL], 'next_cursor': None}
        if operation == 'entities/get': return 200, WELL
        if operation == 'catalog/inventory': return 200, {'assets': [], 'next_cursor': None}
        if operation == 'result-groups/list': return 200, {'groups': [], 'next_cursor': None}
        return 404, {'error': 'unknown', 'code': 'NOT_FOUND'}


def test_first_run_resyncs_then_the_next_catches_up_and_follow_prints_each_change(tmp_path):
    log = Log()
    with fixture_server(log) as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as client:
        out = io.StringIO()
        worker.run(client, tmp_path / 'checkpoint.json', once=True, out=out)
        saved = json.loads((tmp_path / 'checkpoint.json').read_text())
        assert saved['epoch'] == 'e1' and saved['cursor'] == 2 and 'entities/list' in log.calls
        log.head = 4; log.calls.clear(); out = io.StringIO()
        worker.run(client, tmp_path / 'checkpoint.json', seconds=1, out=out)
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        assert lines[0]['cursor'] == 4 and lines[1] == {'cursor': 5, 'kind': 'entity-changed', 'subject': 'well-1'}
