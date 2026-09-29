"""Keep a local copy of a project current and act on each change (the E28 event log).

    python worker.py --checkpoint state/checkpoint.json          # catch up, then follow live
    python worker.py --checkpoint state/checkpoint.json --once   # catch up and stop

The SDK's Sync does the protocol: a resync when the checkpoint no longer matches (new epoch, other credential or
capabilities), otherwise a catch-up from the saved cursor; the cursor advances only after the local copy is updated.
An event names a subject; re-read it (the cache already did for wells, assets and result groups) before acting.
"""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import client_for  # noqa: E402


def act(event):
    """Replace this with what your application does when something changes."""
    return {'cursor': event['cursor'], 'kind': event['kind'], 'subject': event.get('subject_id')}


def run(client, checkpoint, *, once=False, seconds=300, out=sys.stdout):
    sync = client.sync(checkpoint)
    seen = sync.run()
    print(json.dumps({'caught_up': seen, 'cursor': sync.checkpoint.values['cursor'], 'epoch': sync.checkpoint.values['epoch']}), file=out, flush=True)
    if once: return seen
    for event in sync.follow(epoch=sync.checkpoint.values['epoch'], after=sync.checkpoint.values['cursor'], seconds=seconds, reconnect=False):
        print(json.dumps(act(event)), file=out, flush=True)
    return seen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--checkpoint', type=Path, default=Path('state/checkpoint.json'))
    parser.add_argument('--once', action='store_true'); parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args(argv)
    with client_for(os.environ['OPHIOLITE_URL'], os.environ['OPHIOLITE_PROJECT']) as client:
        run(client, args.checkpoint, once=args.once, seconds=args.seconds)


if __name__ == '__main__':
    main()
