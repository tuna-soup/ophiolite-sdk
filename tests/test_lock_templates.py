"""E126b (D2): the template lock compares only what resolving the SDK line reads; a changed base dependency, named
extra or Python floor still refuses."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACCEPTED = '622b528bb70318d322b52bf090ed0395515c1f76'
spec = importlib.util.spec_from_file_location('lock_templates', ROOT / 'tools/lock_templates.py')
lock = importlib.util.module_from_spec(spec); spec.loader.exec_module(lock)
EXTRAS = lock.requested_extras('ophiolite[pandas,numpy,validation] @ git+https://github.com/tuna-soup/ophiolite-sdk@622b528b')


def pyproject(dependencies='"anyio>=4.2,<5", "httpx>=0.28,<1"', pandas='"pandas>=2"', lasio=None, python='>=3.10', description='SDK'):
    extra = '' if lasio is None else 'lasio = [%s]\n' % lasio
    return ('[project]\nname = "ophiolite"\ndescription = "%s"\nrequires-python = "%s"\ndependencies = [%s]\n'
            '[project.optional-dependencies]\npandas = [%s]\nnumpy = ["numpy>=1.24"]\nvalidation = ["jsonschema>=4.26"]\n%s'
            % (description, python, dependencies, pandas, extra)).encode()


def test_the_extras_are_read_from_the_sdk_line():
    assert EXTRAS == ['pandas', 'numpy', 'validation'] and lock.requested_extras('pytest>=8') == []


def test_bytes_resolution_does_not_read_are_accepted():
    lock.check_metadata(pyproject(), pyproject(), EXTRAS)
    lock.check_metadata(pyproject(), pyproject(lasio='"lasio>=0.32"', description='SDK with adapters'), EXTRAS)


@pytest.mark.parametrize('changed', [pyproject(dependencies='"anyio>=4.2,<5", "httpx>=0.28,<1", "pydantic>=2.11,<3"'),
                                     pyproject(pandas='"pandas>=3"'), pyproject(python='>=3.11')],
                         ids=['base dependency', 'named extra', 'python floor'])
def test_a_change_resolution_reads_refuses(changed):
    with pytest.raises(ValueError, match='SDK metadata changed; qualify a new source pin before locking templates.'):
        lock.check_metadata(pyproject(), changed, EXTRAS)


def test_every_template_resolves_the_same_sdk_metadata_as_the_accepted_pin():
    spec = importlib.util.spec_from_file_location('sdk_history', ROOT / 'tools/history.py')
    history = importlib.util.module_from_spec(spec); spec.loader.exec_module(history)
    accepted = history.show(ROOT, ACCEPTED, 'pyproject.toml')  # None in an export without history (the installed-wheel lane)
    assert accepted is not None or not history.FULL, history.missing(ACCEPTED)
    templates = sorted(p.parent.name for p in (ROOT / 'ophiolite/templates').glob('*/requirements.in'))
    assert templates == ['agent-workflow', 'derive-and-publish', 'map-application', 'notebook', 'sync-worker']
    for name in templates:
        first = (ROOT / 'ophiolite/templates' / name / 'requirements.in').read_text().splitlines()[0]
        assert first.endswith('@' + ACCEPTED), name
        if accepted is not None:  # full clones compare each template's own extras
            lock.check_metadata(accepted, (ROOT / 'pyproject.toml').read_bytes(), lock.requested_extras(first))
