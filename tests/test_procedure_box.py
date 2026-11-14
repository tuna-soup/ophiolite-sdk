"""E113 s1 C3: `python -m ophiolite.box` runs a tool version from the server's `/box` request with the same `_child`
as `procedures.run`, so both make the same bytes; a path outside `/box` is refused before the tool runs. The box runs
here in a child process with `root` standing in for `/box` (the real image runs it in the platform's
test_sandbox_image.py, OPHIOLITE_TEST_PODMAN=1).

Mutations (break -> FAIL, restore -> PASS; recorded in the lane's logs/c3-mut-*.txt):
a. `inside` accepts any absolute path -> the outside cases;
b. the box passes the settings it was not given (`{}`) -> the equal-bytes case."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ophiolite import procedures
from test_procedures_run import DECLARED, SHIFTED, TOPS, depth_shift, run_shift

BOX = 'import sys; from ophiolite.box import main; sys.exit(main(*sys.argv[1:]))'


def box(tmp_path, folder, request):
    """A /box tree as the server writes it (bundle, inputs, request.json), then the box in a child process."""
    root, output = tmp_path / 'box', tmp_path / 'output'
    for path, raw in procedures.contract().read_members(folder).items():
        member = root.joinpath('bundle', *path.split('/'))
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(raw)
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs' / 'tops-0.csv').write_text(TOPS)
    (root / 'request.json').write_text(json.dumps(request))
    output.mkdir()
    done = subprocess.run([sys.executable, '-B', '-c', BOX, str(root / 'request.json'), str(output), str(root)], capture_output=True, text=True)
    return done, output


def request(folder, path='/box/inputs/tops-0.csv', **changes):
    manifest = json.loads((folder / 'procedure.json').read_text())
    return {'entry': manifest['entry'], 'settings': procedures._resolved_settings(manifest, ['shift=2.5']),
            'inputs': {'tops': [{'path': path, 'kind': 'well-tops-csv/1', 'declared': DECLARED, 'asset_id': 'a-1', 'revision': 'r-1'}]}, **changes}


def test_the_box_and_a_run_on_this_computer_make_the_same_bytes(tmp_path):
    (tmp_path / 'local').mkdir()
    local = run_shift(tmp_path / 'local')
    made = (Path(local['destination']) / 'shifted.csv').read_bytes()
    folder = depth_shift(tmp_path / 'bundle')
    done, output = box(tmp_path / 'sandbox', folder, request(folder))
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in output.iterdir()) == ['0.bytes', 'outputs.json']
    assert json.loads((output / 'outputs.json').read_text()) == {
        'shifted': {'file': '0.bytes', 'profile': 'well-tops-csv/1', 'declared': {'depth_unit': 'm', 'depth_basis': 'md'}, 'filename': 'tops.csv'}}  # write_tops' name
    assert (output / '0.bytes').read_bytes() == made == SHIFTED


@pytest.mark.parametrize('path', ['/etc/passwd', '/box/../etc/passwd', '/box/inputs/../../etc/passwd', 'box/inputs/tops-0.csv',
                                  '/boxes/inputs/tops-0.csv', '/box', '/box/./inputs/tops-0.csv'])
def test_a_path_outside_box_is_refused_before_the_tool_runs(tmp_path, path):
    folder = depth_shift(tmp_path / 'bundle')
    done, output = box(tmp_path / 'sandbox', folder, request(folder, path))
    assert (done.returncode, list(output.iterdir())) == (2, []), done.stderr
    assert 'Not run: An input path is under /box: ' + path in done.stderr


def test_a_request_with_another_key_is_refused(tmp_path):
    folder = depth_shift(tmp_path / 'bundle')
    done, output = box(tmp_path / 'sandbox', folder, request(folder, snapshot='/elsewhere'))
    assert (done.returncode, list(output.iterdir())) == (2, [])
    assert 'Not run: The box request has entry, settings and inputs, and nothing else.' in done.stderr


def test_the_box_module_writes_through_the_same_child_as_a_local_run():
    from ophiolite import box as box_module
    assert box_module._child is procedures._child and box_module._encode is procedures._encode
