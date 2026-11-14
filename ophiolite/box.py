"""E113 s1: a tool version run in the project's sandbox, inside the operator's sandbox image.

    python -m ophiolite.box /box/request.json /output

The server writes the bundle to `/box/bundle`, each exact input version under `/box/inputs` and the request,
`ophiolite.procedure-box/1` (`{entry, settings, inputs: {slot: [{path, kind, declared, asset_id, revision}]}}`), to
`/box/request.json`, all read-only. This module turns that request into the child request `procedures.run` writes and
calls the same `_child`, so a run on this computer and a run in the sandbox make their bytes with the same code. What
the tool made lands in the output folder exactly as `_child` writes its exchange: `outputs.json` and `<n>.bytes`, or
`error.json`; the server reads it and trusts nothing else. A path outside `/box` is refused before the tool runs.
"""
import json
import sys
import tempfile
from pathlib import Path, PurePosixPath

from .procedures import LocalVersion, _child, _encode

BOX = PurePosixPath('/box')
REQUEST_KEYS = {'entry', 'settings', 'inputs'}
INPUT_KEYS = {'path', 'kind', 'declared', 'asset_id', 'revision'}


class Refused(ValueError):
    """The request is not one the box runs; nothing ran."""


def inside(path, root):
    """The file a `/box/...` path names under `root` (the box itself mounts it at `/box`); anything else is refused."""
    if not isinstance(path, str): raise Refused('An input path is text.')
    pure = PurePosixPath(path)
    if not pure.is_absolute() or BOX not in pure.parents or any(part in ('.', '..') for part in path.split('/')[1:]):
        raise Refused('An input path is under /box: ' + path[:200])
    return Path(root, *pure.relative_to(BOX).parts)


def child_request(request, output, root):
    """The request `_child` reads, from the box's request; raises Refused before anything runs."""
    if not isinstance(request, dict) or set(request) - REQUEST_KEYS or not {'entry', 'inputs'} <= set(request):
        raise Refused('The box request has entry, settings and inputs, and nothing else.')
    if not isinstance(request['inputs'], dict) or not isinstance(request.get('settings', {}), dict):
        raise Refused('The box request has entry, settings and inputs, and nothing else.')
    inputs = {}
    for slot, items in request['inputs'].items():
        if not isinstance(items, list) or not all(isinstance(i, dict) and not set(i) - INPUT_KEYS and {'path', 'kind'} <= set(i) for i in items):
            raise Refused('Each input is {path, kind, declared, asset_id, revision}.')
        inputs[slot] = [LocalVersion(str(inside(i['path'], root)), i['kind'], dict(i.get('declared') or {}), i.get('asset_id'), i.get('revision'))
                        for i in items]
    return {'snapshot': str(Path(root) / 'bundle'), 'exchange': str(output), 'entry': request['entry'],
            'settings': request.get('settings', {}), 'inputs': {slot: _encode(value) for slot, value in inputs.items()}}


def main(request_path, output, root=str(BOX)):
    """Run the box's request; the exit status is `_child`'s (0 made outputs, 3 wrote error.json), 2 when refused."""
    try: child = child_request(json.loads(Path(request_path).read_text(encoding='utf-8')), output, root)
    except (OSError, ValueError) as error:
        print('Not run: ' + str(error), file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='ophiolite-box-') as scratch:  # /tmp, the box's only other writable place
        path = Path(scratch) / 'child.json'
        path.write_text(json.dumps(child), encoding='utf-8')
        return _child(str(path))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
