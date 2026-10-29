"""H56 (D3, D17): a commit of this component from before the one-repository move, in either layout.

The component lived in its own repository until October 2026 (the public SDK and the archives keep those commits). In
the monorepo its history was rewritten under its directory, and docs/monorepo/sha-map.tsv maps every old commit to the
new one with the same tree. A reader that names an old commit asks resolve(): in the monorepo its mapped commit
(never the old commit, even when stale objects still hold it: its tree has the old layout), otherwise the old commit
itself when this checkout has it, else None (an export without history). A shallow checkout (actions/checkout is
depth 1) fetches the mapped commit from origin first; a mapped commit it cannot fetch is None. With
OPHIOLITE_FULL_HISTORY=1 (the nightly) a None is a failure, never a skip. No import outside the standard library, so
the component stays standalone.
"""
import os
import subprocess
from pathlib import Path

FULL = os.environ.get("OPHIOLITE_FULL_HISTORY") == "1"
MAP = "docs/monorepo/sha-map.tsv"


def _git(where, *args):
    return subprocess.run(["git", "-C", str(where), *args], capture_output=True)


def _present(where, sha):
    """SHA is in the repository holding WHERE, fetched at depth 1 from origin when that repository is shallow."""
    if _git(where, "cat-file", "-e", sha + "^{commit}").returncode == 0:
        return True
    if _git(where, "rev-parse", "--is-shallow-repository").stdout.strip() == b"true":
        subprocess.run(["git", "-C", str(where), "fetch", "--quiet", "--no-tags", "--depth=1", "origin", sha],
                       capture_output=True, timeout=300)
    return _git(where, "cat-file", "-e", sha + "^{commit}").returncode == 0


def resolve(where, commit):
    """The full commit for COMMIT (a full SHA or a prefix of this component's old history) as the repository holding
    WHERE knows it, or None."""
    top, prefix = _git(where, "rev-parse", "--show-toplevel"), _git(where, "rev-parse", "--show-prefix")
    if not (top.returncode or prefix.returncode or not prefix.stdout.strip()):  # the monorepo: the map first
        component = prefix.stdout.decode().strip().split("/")[0]
        table = Path(top.stdout.decode().strip()) / MAP
        if table.is_file():
            rows = [line.split("\t") for line in table.read_text().splitlines()[1:]]
            hits = [new for name, old, new in rows if name == component and old.startswith(commit.lower())]
            if len(hits) == 1:
                return hits[0] if _present(where, hits[0]) else None
    found = _git(where, "rev-parse", "--verify", "--quiet", commit + "^{commit}")
    return found.stdout.decode().strip() if found.returncode == 0 else None


def show(where, commit, path):
    """The bytes of PATH (relative to WHERE) at COMMIT, or None when the commit cannot be resolved."""
    sha = resolve(where, commit)
    if sha is None:
        return None
    done = _git(where, "show", "%s:./%s" % (sha, path))
    return done.stdout if done.returncode == 0 else None


def missing(commit):
    """The message a reader skips with, or fails with under OPHIOLITE_FULL_HISTORY=1."""
    return "commit %s is in neither this checkout nor its monorepo SHA map" % commit
