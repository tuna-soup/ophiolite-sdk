"""E131 s1 C1: `ophiolite.tools` and `@ophiolite.tool` — the same objects as the procedure names, and one `tool_*` twin
per `procedure_*` method. Expected values are literals."""
import inspect
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ophiolite
from ophiolite import procedures, tools

FIXTURES = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures'
TOPS = 'name,md\nTop Chalk,1000.5\nBase Chalk,1200\n'
SHIFTED = b'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'
# The 13 public methods of ProcedureClient when E131 s1 opened (f1d813538); a new one needs its twin and a row here.
FROZEN = ('procedure_again', 'procedure_bundle', 'procedure_enable', 'procedure_get', 'procedure_list', 'procedure_prepare_again',
          'procedure_publish', 'procedure_register', 'procedure_run', 'procedure_run_get', 'procedure_trust', 'procedure_version',
          'procedure_withdraw')
HELPERS = ('compared', 'delivered', 'refused', 'not_delivered', 'unknown', 'Stopped', 'NotRun', 'validate', 'digest', 'pack',
           'new', 'run')


def test_imports_raise_no_warning():
    code = 'import ophiolite, ophiolite.tools; from ophiolite import tool, tools, procedure; assert ophiolite.tools is tools'
    done = subprocess.run([sys.executable, '-W', 'error', '-c', code], capture_output=True, text=True, timeout=60)
    assert (done.returncode, done.stderr) == (0, '')


def test_helpers_are_the_procedure_objects():  # R2-7
    for name in HELPERS:
        assert getattr(tools, name) is getattr(procedures, name), name
    assert set(tools.__all__) == {'tool', 'ToolClient', *HELPERS}
    assert ophiolite.tool is tools.tool and ophiolite.tools is tools


def test_frozen_methods_each_have_a_twin():
    public = tuple(sorted(name for name in vars(procedures.ProcedureClient) if name.startswith('procedure_')))
    assert public == FROZEN
    twins = tuple(sorted(name for name in vars(tools.ToolClient) if name.startswith('tool_')))
    assert twins == tuple(sorted('tool_' + name[len('procedure_'):] for name in FROZEN))
    for name in FROZEN:
        twin = getattr(tools.ToolClient, 'tool_' + name[len('procedure_'):])
        assert inspect.signature(twin) == inspect.signature(getattr(procedures.ProcedureClient, name)), name
        assert twin.__name__ == 'tool_' + name[len('procedure_'):]


def test_each_twin_calls_its_procedure_method_unchanged():
    calls = []

    class Recorder(tools.ToolClient):
        pass
    for name in FROZEN:
        def stub(self, *args, _name=name, **kwargs):
            calls.append((_name, args, kwargs))
            return ('sentinel', _name)
        setattr(Recorder, name, stub)
    client = Recorder()
    for name in FROZEN:
        verb = name[len('procedure_'):]
        assert getattr(client, 'tool_' + verb)('a', 2, flag=True) == ('sentinel', name)
        assert calls[-1] == (name, ('a', 2), {'flag': True})
    assert len(calls) == 13


def test_agent_catalogue_gets_no_twins():
    assert [name for name in dir(procedures._AgentCatalogue) if name.startswith('tool_')] == []


def test_tool_marks_an_entry_that_runs(tmp_path):
    folder = tmp_path / 'depth-shift'
    shutil.copytree(FIXTURES / 'bundles/depth-shift', folder, ignore=shutil.ignore_patterns('__pycache__'))
    code = (folder / 'procedure.py').read_text()
    assert code.count('from ophiolite import procedure\n') == 1 and code.count('@procedure\n') == 1
    (folder / 'procedure.py').write_text(code.replace('from ophiolite import procedure\n', 'from ophiolite import tool\n')
                                         .replace('@procedure\n', '@tool\n'))
    (tmp_path / 'in').mkdir()
    (tmp_path / 'in/tops.csv').write_text(TOPS)
    (tmp_path / 'in/tops.declared.json').write_text('{"depth_unit": "m", "depth_basis": "md"}')
    tools.run(folder, tmp_path / 'out', {'tops': [str(tmp_path / 'in/tops.csv')]}, kinds={'tops': 'well-tops-csv/1'},
              declared={'tops': str(tmp_path / 'in/tops.declared.json')}, settings=['shift=2.5'])
    assert sorted(path.name for path in (tmp_path / 'out').iterdir()) == ['log.txt', 'run.json', 'shifted.csv']
    assert (tmp_path / 'out/shifted.csv').read_bytes() == SHIFTED


def test_tool_sets_the_procedure_mark():
    def main(inputs, settings):
        return {}
    assert not hasattr(main, '__ophiolite_procedure__')
    assert tools.tool(main) is main and main.__ophiolite_procedure__ is True
    with pytest.raises(TypeError):
        tools.tool()
