"""E112 s4: a procedure lists the Python distributions it imports under `requires`, and every run and delivery checks
them first: a missing or too old one is refused, by name and with the install command, before a child process, a
trust question, a pending record or a report. Register warns on a text this SDK cannot read and registers.
Expected values are literals; installed versions are controlled through `_requires.installed`."""
import importlib.metadata
import json
import shlex
import subprocess
import sys
import warnings

import pytest

from ophiolite import _requires, cli, procedures
from test_deliver import attempts, count, deliver, folder_of, manifest, nothing_launched, world  # noqa: F401 (world is a fixture)
from test_procedures_run import depth_shift, tops

PYTHON = shlex.quote(sys.executable)
LABEL = 'Shift tops by a fixed depth'
MALFORMED = ['psycopg >= three', 'psycopg; python_version<"3"', 'psycopg @ https://x/y.whl', 'psycopg===3', 'psycopg>=3.1,', '>=3.1',
             'psycopg~=3', 'psycopg>=3.1rc1']


def fake_installed(monkeypatch, versions):
    def installed(name):
        if name.lower() in versions: return versions[name.lower()]
        raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(_requires, 'installed', installed)


def shift_folder(tmp_path, requires):
    """The depth-shift sample with `requires` replaced, or without the field when None."""
    folder = depth_shift(tmp_path, requires=requires if requires is not None else [])
    if requires is None:
        m = json.loads((folder / 'procedure.json').read_text()); del m['requires']
        (folder / 'procedure.json').write_text(json.dumps(m))
    return folder


def local_run(tmp_path, requires):
    folder = shift_folder(tmp_path, requires)
    path, declared = tops(tmp_path)
    return procedures.run(folder, tmp_path / 'out', {'tops': [str(path)]}, kinds={'tops': 'well-tops-csv/1'}, declared={'tops': str(declared)},
                          settings=['shift=2.5'])


def refused(call):
    with pytest.raises(procedures.NotRun) as error: call()
    return error.value


# ---------------------------------------------------------------- the grammar (S4-D2)

@pytest.mark.parametrize('text', MALFORMED)
def test_malformed_texts_are_refused_at_run_with_their_text(tmp_path, text):
    error = refused(lambda: local_run(tmp_path, [text]))
    assert (error.code, error.field, error.details) == ('requires-malformed', '/requires/0', {'text': text})
    assert str(error) == f'Not run: {LABEL} lists "{text}" under requires; write a package name with optional versions, such as psycopg>=3.1.'
    assert not (tmp_path / 'out').exists()


def test_extras_are_refused_with_their_own_ending(tmp_path):
    error = refused(lambda: local_run(tmp_path, ['psycopg>=3.1', 'psycopg[binary]>=3.1']))
    assert (error.code, error.field) == ('requires-malformed', '/requires/1')
    assert str(error) == (f'Not run: {LABEL} lists "psycopg[binary]>=3.1" under requires; extras such as [binary] cannot be checked; '
                          'list the package without them.')


def test_the_shape_and_bound_stay_the_contract_s(tmp_path):
    for n, requires in enumerate((['x'] * 33, ['x' * 101], [3])):
        verdict = procedures.validate(depth_shift(tmp_path / str(n), requires=requires))
        assert not verdict['valid'] and verdict['field'].startswith('/requires'), (requires, verdict)


# ---------------------------------------------------------------- PEP 440 order at each operator's boundary (S4-D3)

BOUNDARIES = [  # (specifier, accepted installed versions, refused installed versions)
    ('>=3.1', ['3.1', '3.1.0', '3.1.post1', '4'], ['3.1.0rc1', '3.1.dev0', '3.0.9']),
    ('>3.1', ['3.1.1', '3.2.dev1'], ['3.1', '3.1.post1', '3.0']),
    ('<4', ['3.9', '3.99.post1'], ['4.0.dev1', '4.0a1', '4', '4.1']),
    ('<=3.1', ['3.1.0', '3.1rc1', '3'], ['3.1.post1', '3.1.1']),
    ('==3.1', ['3.1.0', '3.1+local'], ['3.1.1', '3.1rc1', '3.1.post1']),
    ('==3.1.*', ['3.1.7', '3.1', '3.1.dev1'], ['3.2', '3.0.9']),
    ('!=3.1.*', ['3.2', '3.0.9'], ['3.1.7', '3.1']),
    ('~=3.1', ['3.1', '3.9'], ['4.0', '3.0', '3.1rc1']),
    ('~=3.1.2', ['3.1.2', '3.1.9'], ['3.2.0', '3.1.1']),
    ('>=3.1,<4', ['3.5'], ['4.0', '3.0']),
    ('>=3', ['1!0.1'], ['2.9']),
]


@pytest.mark.parametrize('specifier,accepted,refused_', BOUNDARIES, ids=[b[0] for b in BOUNDARIES])
def test_each_operator_accepts_and_refuses_at_its_boundary(specifier, accepted, refused_):
    for found in accepted:
        assert _requires.unmet(['pkg' + specifier], version=lambda name: found) == [], (specifier, found)
    for found in refused_:
        assert _requires.unmet(['pkg' + specifier], version=lambda name: found) == [
            {'requirement': 'pkg' + specifier, 'name': 'pkg', 'found': found, 'readable': True}], (specifier, found)


def test_an_installed_version_that_does_not_parse_is_refused_with_its_text(tmp_path, monkeypatch):
    fake_installed(monkeypatch, {'probe': 'not-a-version'})
    error = refused(lambda: local_run(tmp_path, ['probe>=1']))
    assert str(error) == (f"Not run: {LABEL} needs probe>=1; probe not-a-version is installed, a version this check cannot read; "
                          f"install it with: {PYTHON} -m pip install 'probe>=1'")


# ---------------------------------------------------------------- the run (S4-D4 1)

def test_a_missing_distribution_is_refused_before_anything_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('a child process was started'))
    error = refused(lambda: local_run(tmp_path, ['ophiolite-no-such-dist>=1']))
    assert (error.code, error.field) == ('requires-missing', '/requires')
    assert str(error) == f"Not run: {LABEL} needs ophiolite-no-such-dist; install it with: {PYTHON} -m pip install 'ophiolite-no-such-dist>=1'"
    assert error.details == {'missing': [{'requirement': 'ophiolite-no-such-dist>=1', 'name': 'ophiolite-no-such-dist', 'found': None}]}
    assert sorted(p.name for p in tmp_path.iterdir()) == ['depth-shift', 'in']  # no destination, no .partial-*


def test_two_missing_are_named_in_one_sentence(tmp_path):
    error = refused(lambda: local_run(tmp_path, ['ophiolite-no-a>=1', 'pydantic>=2', 'ophiolite-no-b']))
    assert str(error) == (f"Not run: {LABEL} needs ophiolite-no-a and ophiolite-no-b; install them with: {PYTHON} -m pip install "
                          f"'ophiolite-no-a>=1' ophiolite-no-b")


def test_an_old_version_is_refused_with_what_is_installed(tmp_path):
    have = importlib.metadata.version('pydantic')
    error = refused(lambda: local_run(tmp_path, ['pydantic>=999']))
    assert str(error) == f"Not run: {LABEL} needs pydantic>=999; pydantic {have} is installed; install it with: {PYTHON} -m pip install 'pydantic>=999'"


def test_a_present_distribution_runs(tmp_path):
    local_run(tmp_path, ['pydantic>=2', 'httpx~=0.28', 'Pydantic >= 2.0 , < 99'])
    assert json.loads((tmp_path / 'out/run.json').read_text())['outputs']


def test_without_requires_a_run_is_unchanged(tmp_path):
    made = {}
    for case, requires in (('absent', None), ('empty', [])):
        (tmp_path / case).mkdir()
        local_run(tmp_path / case, requires)
        out = tmp_path / case / 'out'
        record = json.loads((out / 'run.json').read_text())
        assert record['procedure']['digest'] == procedures.digest(tmp_path / case / 'depth-shift'), case
        made[case] = ({p.name: p.read_bytes() for p in out.iterdir() if p.name != 'run.json'}, record['procedure']['digest'])
    assert made['absent'][0] == made['empty'][0] and made['absent'][0]['shifted.csv'] == b'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'
    assert made['absent'][1] != made['empty'][1]  # the manifest is in the digest (5-F3)


def test_the_cli_says_it_and_json_names_it(tmp_path, capsys):
    folder = shift_folder(tmp_path, ['ophiolite-no-such-dist>=1'])
    path, declared = tops(tmp_path)
    argv = ['procedures', 'run', str(folder), '--output', str(tmp_path / 'out'), '--input', f'tops={path}', '--kind', 'tops=well-tops-csv/1',
            '--declared', f'tops={declared}', '--setting', 'shift=2.5']
    with pytest.raises(SystemExit) as stop: cli.main(argv)
    said = capsys.readouterr()
    assert (stop.value.code, said.out) == (1, '')
    assert said.err == f"Not run: {LABEL} needs ophiolite-no-such-dist; install it with: {PYTHON} -m pip install 'ophiolite-no-such-dist>=1'\n"
    with pytest.raises(SystemExit) as stop: cli.main(argv + ['--json'])
    error = json.loads(capsys.readouterr().out)['error']
    assert stop.value.code == 1 and error['code'] == 'requires-missing' and error['field'] == '/requires'
    assert error['details'] == {'missing': [{'requirement': 'ophiolite-no-such-dist>=1', 'name': 'ophiolite-no-such-dist', 'found': None}]}


def test_the_no_kind_start_stays_e105a_s(tmp_path):
    # the made starts write "requires": [] (test_procedure_templates); E105a's own start does not move (S4-D6, 5-M1)
    assert procedures.new(tmp_path / 'fresh', 'process', 'Shift tops by a fixed depth')['valid']
    assert 'requires' not in json.loads((tmp_path / 'fresh/procedure.json').read_text())


# ---------------------------------------------------------------- register warns and registers (S4-D4 3)

class Registrar(procedures.ProcedureClient):
    def __init__(self): self.sent = []

    def _post(self, area, operation, body, **options):
        self.sent.append((area, operation, body))
        return {'digest': 'sha256:x'}


def test_register_warns_and_registers(tmp_path):
    client = Registrar()
    text = 'psycopg; python_version<"3"'
    unreadable = shift_folder(tmp_path / 'a', [text])
    with pytest.warns(procedures.ProcedureWarning) as said: client.procedure_register(unreadable, command_id='c-1')
    assert [str(w.message) for w in said] == [
        f'{LABEL} lists "{text}" under requires, which this SDK cannot check; running it will be refused until it is a package name with optional versions.']
    assert client.sent == [('procedures', 'register', procedures.register_request(unreadable, 'c-1'))]
    absent = shift_folder(tmp_path / 'b', ['ophiolite-no-such-dist>=1'])
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        client.procedure_register(absent, command_id='c-2')  # a computer may register what it does not run
    assert client.sent[-1] == ('procedures', 'register', procedures.register_request(absent, 'c-2'))


# ---------------------------------------------------------------- deliver (S4-D4 2): before trust, pending record, writer and report

def test_deliver_refuses_before_trust_pending_record_and_writer(world):
    w = world
    m = dict(manifest(name='team/needs-a-package'), requires=['psycopg-no-such>=3.1'])
    digest = w.register(folder_of(w.root / 'needs', m), trusted=False)  # registered by another member: running it asks for trust (5-M4)
    asked = []
    for kw in ({}, {'as_': 'Tops handed over'}):
        error = refused(lambda: deliver(w, name='team/needs-a-package', prompt=lambda question: asked.append(question) or True, **kw))
        assert error.code == 'requires-missing', kw
        assert str(error) == f"Not run: Tops to team folder needs psycopg-no-such; install it with: {PYTHON} -m pip install 'psycopg-no-such>=3.1'"
        assert asked == [] and w.catalogue[digest]['trusted'] is False  # no question, no trust written
        nothing_launched(w)  # no attempt, no writer, no report
        assert not (w.work / 'deliveries').exists()  # and so no intents/ for the gate (5-M5); the stand-in has no gate route


def test_a_pending_attempt_is_reported_again_after_the_package_is_gone(world, monkeypatch):
    w = world
    fake_installed(monkeypatch, {'ophiolite-probe': '1.0'})
    w.register(folder_of(w.root / 'probe', dict(manifest(name='team/probe'), requires=['ophiolite-probe>=1'])))
    w.lose_response = 1
    first = deliver(w, name='team/probe')
    assert first['state'] == 'confirmed' and not first['reported'] and count(w) == 1
    fake_installed(monkeypatch, {})  # removed after the launch (5-F4)
    again = deliver(w, name='team/probe')
    assert again['delivery_id'] == first['delivery_id'] and again['reported'] and count(w) == 1
    assert [p['event_id'] for p in w.posts] == [w.posts[0]['event_id']] * 2  # the saved report id, sent again
    assert refused(lambda: deliver(w, name='team/probe')).code == 'requires-missing'  # a new delivery is checked
