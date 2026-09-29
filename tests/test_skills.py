"""Packaged guidance must name real contracts, public symbols and error categories."""
import importlib
import ast
import shlex
import inspect
import json
from pathlib import Path
import re
import pytest
from ophiolite import errors
ROOT=Path(__file__).resolve().parents[1]
NAMES={'authenticate','read-exact-data','validate-locally','publish-derived-curves','share-result','recover-publication','sync-a-project'}


def resolve(symbol):
    parts=symbol.split('.')
    for boundary in range(len(parts),0,-1):
        try:value=importlib.import_module('.'.join(parts[:boundary]))
        except ModuleNotFoundError:continue
        for part in parts[boundary:]:value=getattr(value,part)
        return value
    raise AssertionError('No public SDK symbol: '+symbol)


def test_guides_use_only_existing_routes_symbols_and_errors():
    directory=ROOT/'ophiolite/skills';assert {p.name for p in directory.iterdir() if p.is_dir()}==NAMES
    routes=json.loads((ROOT/'ophiolite/contracts/openapi/v1/openapi.json').read_text())['paths']
    codes={value.code for value in vars(errors).values() if inspect.isclass(value) and issubclass(value,errors.OphioliteError)}
    for name in NAMES:
        text=(directory/name/'SKILL.md').read_text()
        declaration=json.loads(re.search(r'<!-- sdk-contract: (.*?) -->',text).group(1))
        assert declaration['symbols'],name
        assert set(re.findall(r'/api/v1/[A-Za-z0-9_/{}/-]+',text))==set(declaration['routes'])
        for route in declaration['routes']:assert route in routes,(name,route)
        for symbol in declaration['symbols']:
            assert not any(part.startswith('_') for part in symbol.split('.'))
            assert resolve(symbol) is not None
        assert set(declaration['errors'])<=codes,name
        assert set(re.findall(r'`([a-z]+(?:-[a-z]+)+)`',text))<=codes,name
        for block in re.findall(r'```python\n(.*?)```',text,re.S):
            tree=ast.parse(block)
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom) and node.module and node.module.startswith('ophiolite'):
                    for imported in node.names:assert resolve(node.module+'.'+imported.name) is not None
        from ophiolite.cli import parser
        for block in re.findall(r'```sh\n(.*?)```',text,re.S):
            for line in block.splitlines():
                words=shlex.split(line)
                if words and words[0]=='ophiolite':parser().parse_args(words[1:])
    sharing=(directory/'share-result/SKILL.md').read_text().lower()
    recovery=(directory/'recover-publication/SKILL.md').read_text().lower()
    assert 'read grants first' in sharing and 'do not retry automatically' in sharing
    assert 'original private work folder' in recovery and 'never replay sharing automatically' in recovery


def test_installed_cli_finds_all_packaged_guides(tmp_path):
    import os,subprocess
    python=os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    if not python:pytest.skip('Supply the installed wheel interpreter')
    result=subprocess.run([python,'-I','-c','from ophiolite.cli import main; main(["skills","path"])'],capture_output=True,text=True,check=True)
    directory=Path(result.stdout.strip())
    assert {p.parent.name for p in directory.glob('*/SKILL.md')}==NAMES
    assert directory.resolve()!= (ROOT/'ophiolite/skills').resolve()
