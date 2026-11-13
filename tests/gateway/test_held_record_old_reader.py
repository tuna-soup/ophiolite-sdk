"""E173 s0 C1 (D1): an older SDK refuses a folder in which this SDK recorded the words an item was named by and whether it
stays, instead of dropping both on its next get. The production writer of this tree saves the folder; the released
2026.10.117 wheel, frozen in the gateway's fixtures (E122 s2), reads that exact file in a separate process. The refusal
is proved, not assumed: the same old reader loads a folder this tree wrote without words. Here under tests/gateway
because exported SDK tests do not read above the SDK.

Mutation: the record written as /1 with words (no promotion in `_save`) -> the old reader loads it."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from ophiolite.exchange import Exchange

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WHEEL = ROOT / 'ophiolite-platform/services/project_gateway/tests/fixtures/e122s2/ophiolite-2026.10.117-py3-none-any.whl'
WHEEL_SHA256 = '2242d38651bdcff1f2e55c8cc819713751a76fedd26169ba54713ab51b331037'  # as test_upload_source_released.py pins it
spec = importlib.util.spec_from_file_location('exchange_fake', HERE.parent / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
CANNOT_READ = 'The project refused this: this folder holds a record this version cannot read. Nothing was sent.'

OLD_READER = r'''
import json, sys
import ophiolite.exchange as ex
class Transport: url, project = 'https://project.example', 'p'
out = {'file': ex.__file__, 'schema': ex.SCHEMA, 'answers': []}
e = ex.Exchange(Transport(), sys.argv[1])
for call in (e.held, lambda: e.get('poro')):
    try: call(); out['answers'].append('loaded')
    except ex.NotValid as refusal: out['answers'].append(str(refusal))
    except Exception as other: out['answers'].append('loaded, then %s' % type(other).__name__)
print(json.dumps(out))
'''


def released(tmp_path):
    assert hashlib.sha256(WHEEL.read_bytes()).hexdigest() == WHEEL_SHA256
    target = tmp_path / 'released'
    with zipfile.ZipFile(WHEEL) as wheel: wheel.extractall(target)
    return target


def old_reader(tmp_path, folder):
    target = released(tmp_path) if not (tmp_path / 'released').exists() else tmp_path / 'released'
    out = subprocess.run([sys.executable, '-c', OLD_READER, str(folder)], cwd=tmp_path, env={**os.environ, 'PYTHONPATH': str(target)},
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    answer = json.loads(out.stdout)
    assert answer['file'].startswith(str(target)) and answer['schema'] == 'ophiolite.held/1'  # the released core, not this tree's
    return answer['answers']


def written(tmp_path, name, fields):
    """A folder this tree's production writer saved: a get, the entry's fields set as a later slice's call would, a check."""
    fake = fake_module.Fake(); fake.add('poro', b'porosity v1', name='Porosity')
    folder = tmp_path / name
    e = Exchange(fake, folder, clock=lambda: 1300.0)
    e.get('poro')
    if fields:
        held = json.loads((folder / 'held.json').read_text())
        held['items']['poro'].update(fields)
        (folder / 'held.json').write_text(json.dumps(held))
    e.check()  # the production `_save` writes the record
    return folder


def test_the_released_sdk_refuses_a_folder_with_words_and_a_mode_and_changes_nothing(tmp_path):
    named = written(tmp_path, 'named', {'words': {'name': 'Top Rotliegend', 'type': 'horizon'}, 'mode': 'stays'})
    before = (named / 'held.json').read_bytes()
    assert old_reader(tmp_path, named) == [CANNOT_READ, CANNOT_READ]  # first: the mutation's failure is the old reader loading it
    assert (named / 'held.json').read_bytes() == before
    held = json.loads(before)
    assert held['schema'] == 'ophiolite.held/2' and held['items']['poro']['mode'] == 'stays'


@pytest.mark.parametrize('stay, mode', [(True, 'stays'), (False, 'follows')])
def test_the_released_sdk_refuses_a_folder_that_public_calls_by_name_wrote(tmp_path, stay, mode):
    """E173 s1 (F3): the folder made by `get(name=..., stay=...)` alone, with no record edit. Mutation: get by name
    writes neither words nor a mode -> the folder stays /1 and the old reader loads it."""
    fake = fake_module.Fake(); fake.add('poro', b'porosity v1', name='Porosity', profile='table/1')
    folder = tmp_path / 'public'
    Exchange(fake, folder, clock=lambda: 1300.0).get(name='Porosity', stay=stay, output=tmp_path / 'out')
    before = (folder / 'held.json').read_bytes()
    held = json.loads(before)
    assert held['schema'] == 'ophiolite.held/2' and held['items']['poro']['words'] == {'name': 'Porosity'} and held['items']['poro']['mode'] == mode
    assert old_reader(tmp_path, folder) == [CANNOT_READ, CANNOT_READ]
    assert (folder / 'held.json').read_bytes() == before


def test_the_same_released_sdk_reads_a_folder_used_by_id(tmp_path):
    """The control: without words or a mode this tree writes /1, and the released reader loads it."""
    plain = written(tmp_path, 'plain', {})
    assert json.loads((plain / 'held.json').read_text())['schema'] == 'ophiolite.held/1'
    assert old_reader(tmp_path, plain) == ['loaded', 'loaded, then CouldNotReach']  # it went on to ask the (bare) transport
