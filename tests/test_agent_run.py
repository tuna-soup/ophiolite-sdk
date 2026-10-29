"""E112 s3 C3 (D-44): an agent reports a run as a run again of an earlier result (`AgentRun(again_of=...)`), strategy
s3-D7. Every case builds a NEW AgentRun over the folder state the earlier one saved (7-M3), so a value kept only on
the object cannot pass; expected requests are literals."""
import hashlib
import json

import pytest

from ophiolite.errors import Refused
from ophiolite.procedures import LOCAL_RUN, AgentRun

RAW = b'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'
AGAIN = {'asset_id': 'a-result', 'revision': 'r-7'}
REFUSED = 'This run was first reported as a run again of another result; report it with the same one.'


def folder(tmp_path):
    run = tmp_path / 'again'
    run.mkdir()
    (run / 'shifted.csv').write_bytes(RAW)
    record = {'schema': LOCAL_RUN, 'procedure': {'name': 'depth-shift', 'version': 1, 'digest': 'd' * 64, 'rules_version': '1.3.0'},
              'settings': {'shift': 2.5}, 'inputs': {'tops': [{'asset_id': 'a-tops', 'revision': 'r-1', 'kind': 'well-tops-csv/1'}]},
              'systems': {}, 'outputs': {'shifted': {'file': 'shifted.csv', 'sha256': hashlib.sha256(RAW).hexdigest(), 'profile': 'well-tops-csv/1',
                                                     'declared': {'depth_unit': 'm'}}}, 'runner': 'this computer'}
    (run / 'run.json').write_text(json.dumps(record))
    return run


def expected(command_id, **extra):
    return {'command_id': command_id, 'procedure': {'digest': 'd' * 64}, 'settings': {'shift': 2.5},
            'inputs': {'tops': [{'asset_id': 'a-tops', 'revision': 'r-1'}]},
            'outputs': [{'role': 'shifted', 'sha256': hashlib.sha256(RAW).hexdigest(), 'bytes': len(RAW), 'declared': {'depth_unit': 'm'}}],
            'publish': {'shifted': {'name': 'Shifted tops'}}, **extra}


def state(run): return json.loads((run / 'agent-run.json').read_text())


class LostAnswer(Exception):
    pass


class Agent:
    """Proposes nothing: the answer to the proposal is lost, after the request was built (and its state saved)."""
    def propose(self, *args, **kwargs): raise LostAnswer()


def first(run, again_of):
    with pytest.raises(LostAnswer): AgentRun(Agent(), run, name='Shifted tops', again_of=again_of).report('Run the residuals again')
    return state(run)['command_id']


def test_a_run_again_is_saved_before_the_proposal_and_a_new_object_sends_the_same_request(tmp_path):
    # mutation: again_of kept on the object only (not in the state) -> the new object's request has no again_of
    run = folder(tmp_path)
    command = first(run, dict(AGAIN))
    assert state(run) == {'schema': 'ophiolite.agent-run/1', 'command_id': command, 'again_of': AGAIN}
    again = AgentRun(None, run, name='Shifted tops', again_of=dict(AGAIN)).request()
    assert again == expected(command, again_of=AGAIN)
    assert json.dumps(again, sort_keys=True) == json.dumps(AgentRun(None, run, name='Shifted tops', again_of=dict(AGAIN)).request(), sort_keys=True)


@pytest.mark.parametrize('other', [{'asset_id': 'a-other', 'revision': 'r-7'}, {'asset_id': 'a-result', 'revision': 'r-8'}, None])
def test_another_or_no_reference_after_the_first_request_is_refused(tmp_path, other):
    # mutation: the saved reference not compared -> a second report with another result (or none) goes out
    run = folder(tmp_path)
    command = first(run, dict(AGAIN))
    with pytest.raises(Refused) as error: AgentRun(None, run, name='Shifted tops', again_of=other).request()
    assert str(error.value) == REFUSED and state(run) == {'schema': 'ophiolite.agent-run/1', 'command_id': command, 'again_of': AGAIN}


def test_an_ordinary_report_has_no_again_of_key(tmp_path):
    # mutation: 'again_of': None always sent (or saved) -> the gateway's retry identity of every ordinary report changes
    run = folder(tmp_path)
    command = first(run, None)
    assert state(run) == {'schema': 'ophiolite.agent-run/1', 'command_id': command}
    assert AgentRun(None, run, name='Shifted tops').request() == expected(command)
    with pytest.raises(Refused) as error: AgentRun(None, run, name='Shifted tops', again_of=dict(AGAIN)).request()
    assert str(error.value) == REFUSED


def test_a_state_saved_before_again_of_existed_counts_as_none(tmp_path):
    run = folder(tmp_path)
    (run / 'agent-run.json').write_text(json.dumps({'schema': 'ophiolite.agent-run/1', 'command_id': 'run-legacy'}))
    assert AgentRun(None, run, name='Shifted tops').request() == expected('run-legacy')
    with pytest.raises(Refused) as error: AgentRun(None, run, name='Shifted tops', again_of=dict(AGAIN)).request()
    assert str(error.value) == REFUSED


@pytest.mark.parametrize('bad', [{'asset_id': 'a-result'}, {'asset_id': 'a-result', 'revision': 7}, {'asset_id': '', 'revision': 'r-7'},
                                 {**AGAIN, 'profile': 'well-tops-csv/1'}, ('a-result', 'r-7')])
def test_a_reference_that_is_not_an_asset_and_a_revision_is_refused_before_anything_is_saved(tmp_path, bad):
    run = folder(tmp_path)
    with pytest.raises(Refused): AgentRun(None, run, name='Shifted tops', again_of=bad)
    assert not (run / 'agent-run.json').exists()
