"""E155 s0: the SDK's copy of the gateway's derive profiles, compared with project_gateway/publications.py.

Here, not in the exported SDK tests: it reads the Platform beside the SDK (tools/test_sdk_tests_stay_in_tree.py).
"""
import ast
from pathlib import Path

from ophiolite.agent_exchange import DERIVE_PROFILES

ROOT = Path(__file__).resolve().parents[3]


def _gateway_profiles():
    """PUBLIC_DERIVE_PROFILES as project_gateway/publications.py builds it (its tuples and += lines), read without importing it."""
    tree = ast.parse((ROOT / 'ophiolite-platform/services/project_gateway/publications.py').read_text())
    values = {}
    def value(node):
        if isinstance(node, ast.Tuple): return tuple(ast.literal_eval(e) for e in node.elts)
        if isinstance(node, ast.Name): return values[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add): return value(node.left) + value(node.right)
        raise AssertionError(ast.dump(node))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.endswith('PROFILES'):
            values[node.targets[0].id] = value(node.value)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id.endswith('PROFILES'):
            values[node.target.id] = values[node.target.id] + value(node.value)
    return values['PUBLIC_DERIVE_PROFILES']


def test_the_derive_profiles_are_the_gateways():
    """Mutation: a LAS profile added to the SDK's copy -> differs from the gateway's."""
    assert DERIVE_PROFILES == _gateway_profiles()
