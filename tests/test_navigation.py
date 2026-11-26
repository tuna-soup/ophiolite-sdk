"""E20: navigation is generated from the synced predicate registry, in Python and TypeScript."""
import json
import subprocess
import sys
from pathlib import Path
from ophiolite import navigation
from ophiolite.client import Client

ROOT = Path(__file__).resolve().parents[1]


def test_generated_navigation_matches_the_registry():
    done = subprocess.run([sys.executable, str(ROOT / 'tools/generate_navigation.py'), '--check'], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout
    registry = json.loads((ROOT / 'ophiolite/contracts/relationships/v1/registry.json').read_text())
    assert navigation.REGISTRY_VERSION == registry['version'] and set(navigation.PREDICATES) == {p['id'] for p in registry['predicates']}
    people = [p for p in registry['predicates'] if p['asserted_by'] == 'people' and p['status'] == 'active' and p['id'] != 'made-for']
    for p in people:  # one assert and one follow method per predicate people may assert, on the Client
        assert callable(getattr(Client, p['id'].replace('-', '_'))) and callable(getattr(Client, p['inverse'].replace('-', '_')))
    for p in registry['predicates']:
        if p['asserted_by'] == 'system': assert not hasattr(Client, p['id'].replace('-', '_'))  # derivations are only followed (lineage)
    ts = (ROOT / 'packages/typescript/src/generated/navigation.ts').read_text()
    assert all(('export function ' + ''.join([w if i == 0 else w.capitalize() for i, w in enumerate(p['id'].split('-'))]) + '(') in ts for p in people)


def test_made_for_is_listed_but_has_no_generated_method():
    """E192 s2 C4: made-for is stated only by a send (the associate route refuses it), so neither language has an
    assert or a follow for it; the predicate stays in PREDICATES. Mutation: the UNSENT skip removed from the generator
    (and the files regenerated) -> the methods and exports come back."""
    assert navigation.PREDICATES['made-for']['inverse'] == 'made-for-of'
    py = (ROOT / 'ophiolite/navigation.py').read_text()
    ts = (ROOT / 'packages/typescript/src/generated/navigation.ts').read_text()
    assert 'def made_for(' not in py and 'def made_for_of(' not in py
    assert not hasattr(Client, 'made_for') and not hasattr(Client, 'made_for_of')
    assert 'function madeFor(' not in ts and 'function madeForOf(' not in ts and '"made-for": {' in ts
