"""E70a C2 (X4): the exchange core imports the standard library and ophiolite.errors only, so a host application's
Python can carry it. Third-party packages are blocked in a separate process; the delta after `import ophiolite` is
measured, standard-library modules excepted."""
import json
import subprocess
import sys
from pathlib import Path

PROBE = r'''
import importlib.abc, json, sys
BLOCKED = {'httpx', 'pydantic', 'numpy', 'pandas', 'anyio', 'jsonschema'}
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in BLOCKED: raise ImportError('blocked: ' + name)
sys.meta_path.insert(0, Block())
import ophiolite
before = set(sys.modules)
import ophiolite.exchange as ex
for code, sentence in ex.SENTENCES.items():
    sentence({'name': 'X', 'number': 2, 'who': 'someone', 'when': 'just now', 'folder': 'f', 'reason': 'r', 'reasons': 'r', 'newer': [], 'new': [], 'lost': [], 'visible': 1})
for code, cls in ex.REFUSALS.items(): cls('s', {}, {})
added = set(sys.modules) - before
stdlib = set(sys.stdlib_module_names)
print(json.dumps(sorted(m for m in added if m.split('.')[0] not in stdlib)))
'''


def test_the_core_imports_only_the_standard_library_and_errors():
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, '-c', PROBE], capture_output=True, text=True, cwd=root, env={'PYTHONPATH': str(root), 'PATH': ''}, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ['ophiolite.errors', 'ophiolite.exchange']  # mutation: `import httpx` or `from .publish import ...` at module level fails
