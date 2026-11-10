"""E163 s1 C1: the module's public names are visible (`__all__`, `__dir__`) and still served lazily."""
import ast
import json
import subprocess
import sys
from pathlib import Path

import ophiolite

INIT = Path(ophiolite.__file__)
# every public name and the object it must be: (module, qualified name), or the module itself for `tools`
EXPECTED = {
    'Client': ('ophiolite.client', 'Client'), 'Credential': ('ophiolite.auth', 'Credential'),
    'CurveSet': ('ophiolite.client', 'CurveSet'), 'AsyncClient': ('ophiolite.aio', 'AsyncClient'),
    'Descriptor': ('ophiolite.scientific', 'Descriptor'), 'connect': ('ophiolite.account', 'connect'),
    'Account': ('ophiolite.account', 'Account'), 'Sync': ('ophiolite.sync', 'Sync'),
    'Checkpoint': ('ophiolite.sync', 'Checkpoint'), 'ResyncRequired': ('ophiolite.errors', 'ResyncRequired'),
    'tool': ('ophiolite.tools', 'tool'), 'tools': ('ophiolite.tools', None),
    'compared': ('ophiolite.procedures', 'compared'), 'delivered': ('ophiolite.procedures', 'delivered'),
    'refused': ('ophiolite.procedures', 'refused'), 'not_delivered': ('ophiolite.procedures', 'not_delivered'),
    'unknown': ('ophiolite.procedures', 'unknown'), 'WrittenOriginal': ('ophiolite.writers', 'WrittenOriginal'),
    'OAuthApp': ('ophiolite.oauth_app', 'OAuthApp'),
    'OphioliteDeprecationWarning': ('ophiolite._deprecation', 'OphioliteDeprecationWarning'),
    'kinds': ('ophiolite.osdu', 'kinds'), 'profiles_for': ('ophiolite.osdu', 'profiles_for'),
}
LEFT_OUT = {'__contracts__', 'procedure', 'oauth_app'}  # served, not listed (design 5)

RESOLVE = '''
import json, sys, types
import ophiolite
seen = {}
for name in sys.argv[1:]:
    value = getattr(ophiolite, name)
    seen[name] = [value.__name__, None] if isinstance(value, types.ModuleType) else [value.__module__, value.__qualname__]
print(json.dumps(seen))
'''


def fresh(code, *argv):
    done = subprocess.run([sys.executable, '-c', code, *argv], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout


def served():
    """The names __getattr__ answers, read from its comparisons in the source."""
    function = next(n for n in ast.parse(INIT.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '__getattr__')
    names = set()
    for test in (n.test for n in ast.walk(function) if isinstance(n, ast.If)):
        if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == 'name':
            names |= {c.value for c in ast.walk(test.comparators[0]) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return names


def test_all_is_the_served_names_less_three():
    assert ophiolite.__all__ == list(EXPECTED)
    assert served() - LEFT_OUT == set(ophiolite.__all__) and LEFT_OUT <= served()


def test_each_name_is_its_object_in_a_fresh_process_in_either_order():
    for order in (list(EXPECTED), list(reversed(EXPECTED))):
        assert {k: tuple(v) for k, v in json.loads(fresh(RESOLVE, *order)).items()} == EXPECTED, order


def test_oauth_app_resolves_first_in_a_fresh_process():
    assert json.loads(fresh(RESOLVE, 'OAuthApp')) == {'OAuthApp': ['ophiolite.oauth_app', 'OAuthApp']}


def test_star_import_binds_exactly_all():
    bound = fresh('import json as _json\nfrom ophiolite import *\nprint(_json.dumps(sorted(k for k in dir() if not k.startswith("_"))))')
    assert json.loads(bound) == sorted(EXPECTED)


def test_dir_shows_every_public_name():
    assert set(ophiolite.__all__) | {'__version__', '__contracts__'} <= set(dir(ophiolite))


def test_import_stays_light():
    loaded = fresh('import ophiolite, sys\nprint(" ".join(m for m in ("httpx", "anyio") if m in sys.modules))')
    assert loaded.strip() == ''
