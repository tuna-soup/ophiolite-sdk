"""E149 s1 C4: the SDK's list of changes an agent may propose is the set the server declares proposable, read from the
synced OpenAPI document's x-ophiolite-agent (contracts/agents/v1), both ways."""
import json
from pathlib import Path
from ophiolite import agents

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = json.loads((ROOT / 'ophiolite/contracts/openapi/v1/openapi.json').read_text())


def declared_proposable():
    found = set()
    for path, methods in OPENAPI['paths'].items():
        for method in methods.values():
            if isinstance(method, dict) and (method.get('x-ophiolite-agent') or {}).get('admitted') in ('proposable', 'both'):
                found.add('/'.join(path.split('/')[-2:]))
    return found


NOT_STANDALONE = {'table-imports/read'}  # E153 s1: a file step, sent with a job (files=)


def test_the_changes_are_the_declared_proposable_operations():
    """Mutations: publications/derive back in CHANGES, or publications/share dropped → red."""
    assert set(agents.CHANGES) == declared_proposable() - NOT_STANDALONE
    assert len(agents.CHANGES) == len(set(agents.CHANGES)) == 27  # E153 s1: the four JSON steps of a table import; s1b: six more; E154 s0: request and withdraw; s1: bind
    assert 'publications/derive' not in agents.CHANGES


def test_the_declared_set_is_read_from_the_document():
    # literal, so a document that lost its extensions cannot agree with an emptied CHANGES
    assert {'publications/share', 'runners/cancel', 'verdicts/record'} <= declared_proposable()
    assert 'upload-runs/decide' not in declared_proposable()
    assert 'publications/derive' not in declared_proposable()  # E166 s0: covered only, a step of its reported run
