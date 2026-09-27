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
    people = [p for p in registry['predicates'] if p['asserted_by'] == 'people' and p['status'] == 'active']
    for p in people:  # one assert and one follow method per predicate people may assert, on the Client
        assert callable(getattr(Client, p['id'].replace('-', '_'))) and callable(getattr(Client, p['inverse'].replace('-', '_')))
    for p in registry['predicates']:
        if p['asserted_by'] == 'system': assert not hasattr(Client, p['id'].replace('-', '_'))  # derivations are only followed (lineage)
    ts = (ROOT / 'packages/typescript/src/generated/navigation.ts').read_text()
    assert all(('export function ' + ''.join([w if i == 0 else w.capitalize() for i, w in enumerate(p['id'].split('-'))]) + '(') in ts for p in people)
