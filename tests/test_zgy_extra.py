"""E123 SZ C1: reading ZGY is an optional extra. The core dependencies do not change, the `zgy` extra pins pyzgy, and the
test-only pyzgy line carries the Linux x86_64 marker (pyzgy pulls segyio, LGPL-3.0, which has no Linux aarch64 wheel).
segyio itself is named only by `dev` and E129 (e)'s `pack` extra, which pin it unconditionally since main d1bce63fc.
Mutations: pyzgy appended to `dependencies`, the pyzgy marker dropped, or segyio added to another extra, RED."""
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / 'pyproject.toml'
MARKER = 'sys_platform == "linux" and platform_machine == "x86_64"'


def project():
    return tomllib.loads(PYPROJECT.read_text(encoding='utf-8'))['project']


def test_the_core_dependencies_do_not_change():
    assert project()['dependencies'] == ['anyio>=4.2,<5', 'httpx>=0.28,<1', 'pydantic>=2.11,<3']


def test_the_zgy_extra_pins_pyzgy():
    assert project()['optional-dependencies']['zgy'] == ['pyzgy==0.1.1']


def test_the_test_only_zgy_lines_carry_the_marker():
    lines = [d for d in project()['optional-dependencies']['dev'] if d.split('=')[0].split(';')[0].strip() in ('pyzgy', 'segyio')]
    assert lines == ['segyio==1.9.14', 'pyzgy==0.1.1; ' + MARKER]
    for name, extra in project()['optional-dependencies'].items():
        if name not in ('dev', 'pack'): assert not any(d.startswith('segyio') for d in extra), name
