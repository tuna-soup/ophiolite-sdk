"""E134 s1: your own work in a project, exported as a folder of work episodes a model can learn from
(`ophiolite.work-episodes/1` in `trajectories.json`, one `ophiolite.work-episode/1` per line of `episodes.jsonl`).

`export` pages `activity/trajectories` under the first page's `until` and refuses a page whose `reconstruction`
differs ("The record changed while exporting; export again."), whose `until` changed or whose `next` does not
advance. It writes into a hidden sibling of the destination, checks that folder with `load`, and only then renames it
to the destination: a refusal or a failed check leaves no destination and no staging folder. E134 s2: `auto` (the
default) gives values where the rights allow, `shape` lowers every episode to its shape. `load` reads a folder and
checks every rule below, naming the rule and the line it broke.

Rules of `load` (s1 §7):
  1. the manifest and every line parse as their contracts;
  2. the counts equal the episodes (`episodes`, `shape`, `values`);
  3. a shape export holds shape episodes only;
  4. the fractions are integers summing to 1000;
  5. each episode's start and end are its first and last row; rows are ordered by (at, action id); no gap at or
     above the window inside an episode;
  6. each split is `split/1` of (seed, fractions, episode id);
  7. each final entry names one of the episode's outputs, once per (ref, outcome_ref);
  8. episode ids are unique in the folder;
  9. when `episodes.parquet` is present and pyarrow imports: it reads, its schema is `PARQUET_FIELDS`, it has one
     row per line in order, each `episode` is the line's text and each scalar column equals the line's field.

E134 s3: `until` repeats an export: under unchanged rights, consent, readership, member names, release and SDK version
the same `until` gives the same `episodes.jsonl` and the same manifest but `exported_at`. With pyarrow installed the
folder also holds `episodes.parquet`, derived from the lines (its bytes repeat in the same pyarrow environment only).
"""
import hashlib
import json
import os
import secrets
import shutil
from pathlib import Path

from .errors import IntegrityConflict, Refused, VerificationFailed

MANIFEST, EPISODES, PARQUET = 'trajectories.json', 'episodes.jsonl', 'episodes.parquet'
# s3 D4: the derived file's schema, written explicitly (never inferred); `episode` is the line's text
PARQUET_FIELDS = (('episode_id', 'string'), ('mode', 'string'), ('split', 'string'), ('start', 'float64'), ('end', 'float64'),
                  ('rows', 'int64'), ('episode', 'string'))
LIMIT = 1000
CHANGED = 'The record changed while exporting; export again.'


def canonical(value):
    """The server's canonical JSON bytes (sorted keys, no spaces, no NaN, UTF-8)."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=False).encode()


def bucket(seed, identity):
    return int(hashlib.sha256(canonical(['split/1', seed, identity])).hexdigest()[:8], 16) % 1000


def split(seed, fractions, identity):
    """`split/1`: train below `train`, validation below `train + validation`, test otherwise (per thousand)."""
    n = bucket(seed, identity)
    if n < fractions['train']: return 'train'
    if n < fractions['train'] + fractions['validation']: return 'validation'
    return 'test'


def _models():
    from pydantic import TypeAdapter
    from .models.generated import WorkEpisode, WorkEpisodes
    return WorkEpisodes, TypeAdapter(WorkEpisode)


def _broken(rule, text, line=None):
    return VerificationFailed('The folder breaks rule %d: %s%s.' % (rule, text, '' if line is None else ' (line %d of %s)' % (line, EPISODES)))


def _episode(adapter, value, line):
    from pydantic import ValidationError
    try: return adapter.validate_python(value)
    except ValidationError: raise _broken(1, 'an episode is not a work episode', line) from None


def check(manifest, episodes):
    """Rules 1 to 8 over a manifest and its episodes (dictionaries); returns them parsed."""
    from pydantic import ValidationError
    model, adapter = _models()
    try: m = model.model_validate(manifest)
    except ValidationError: raise _broken(1, 'the manifest is not a work-episodes manifest') from None
    parsed = [_episode(adapter, e, n) for n, e in enumerate(episodes, 1)]
    shape = sum(e.mode == 'shape' for e in parsed)
    if (m.counts.episodes, m.counts.shape, m.counts.values) != (len(parsed), shape, len(parsed) - shape): raise _broken(2, 'the counts differ from the episodes')
    fractions = m.fractions.model_dump()
    if m.mode == 'shape':
        for n, e in enumerate(parsed, 1):
            if e.mode != 'shape': raise _broken(3, 'a shape export holds a values episode', n)
    if sum(fractions.values()) != 1000: raise _broken(4, 'the fractions do not sum to 1000')
    seen = set()
    for n, e in enumerate(parsed, 1):
        rows = e.rows
        if (e.start, e.end) != (rows[0].at, rows[-1].at): raise _broken(5, 'start and end are not the first and last row', n)
        if any((a.at, a.action_id) >= (b.at, b.action_id) for a, b in zip(rows, rows[1:])): raise _broken(5, 'rows are not ordered', n)
        if any(b.at - a.at >= m.window_seconds for a, b in zip(rows, rows[1:])): raise _broken(5, 'a gap inside an episode is at or above the window', n)
        if e.split != split(m.seed, fractions, e.episode_id): raise _broken(6, 'a split is not split/1', n)
        outputs = {o.ref for r in rows for o in r.outputs}
        pairs = [(f.ref, f.outcome_ref) for f in e.final]
        if any(ref not in outputs for ref, _ in pairs) or len(set(pairs)) != len(pairs): raise _broken(7, 'a final entry is not one of the outputs, once', n)
        if e.episode_id in seen: raise _broken(8, 'an episode id repeats', n)
        seen.add(e.episode_id)
    return m, parsed


def _scalars(episode):
    return (episode['episode_id'], episode['mode'], episode['split'], episode['start'], episode['end'], len(episode['rows']))


def write_manifest(path, manifest, sdk_version):
    """The manifest as the SDK writes it: the server's manifest with `sdk_version`, canonical, one newline."""
    Path(path).write_bytes(canonical({**manifest, 'sdk_version': sdk_version}) + b'\n')


def write_parquet(lines, path):
    """s3 D4: `episodes.parquet` from the lines' texts (zstd, the pinned schema, zero rows for none); False without pyarrow."""
    try: import pyarrow as pa, pyarrow.parquet as pq
    except ImportError: return False
    scalars = [_scalars(json.loads(line)) for line in lines]
    schema = pa.schema([(name, getattr(pa, kind)()) for name, kind in PARQUET_FIELDS])
    columns = [[s[i] for s in scalars] for i in range(6)] + [list(lines)]
    pq.write_table(pa.table(columns, schema=schema), path, compression='zstd')
    return True


def _rule_9(path, lines, episodes):
    try: import pyarrow as pa, pyarrow.parquet as pq
    except ImportError: return
    try: table = pq.read_table(path)
    except Exception: raise _broken(9, '%s cannot be read' % PARQUET) from None
    if not table.schema.equals(pa.schema([(name, getattr(pa, kind)()) for name, kind in PARQUET_FIELDS])): raise _broken(9, 'the schema of %s is not the pinned one' % PARQUET)
    if table.num_rows != len(lines): raise _broken(9, '%s does not hold one row per line' % PARQUET)
    columns = [table.column(name).to_pylist() for name, _ in PARQUET_FIELDS]
    for n, (line, episode) in enumerate(zip(lines, episodes)):
        if columns[6][n] != line: raise _broken(9, 'a row of %s is not its line' % PARQUET, n + 1)
        if tuple(c[n] for c in columns[:6]) != _scalars(episode): raise _broken(9, 'a column of %s differs from its line' % PARQUET, n + 1)


def load(folder):
    """(manifest, episodes) of an exported folder, checked by rules 1 to 9 (`VerificationFailed` names the rule)."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding='utf-8'))
        lines = (folder / EPISODES).read_text(encoding='utf-8').splitlines()
        episodes = [json.loads(line) for line in lines]
    except (OSError, ValueError): raise _broken(1, 'the folder does not hold %s and %s as JSON' % (MANIFEST, EPISODES)) from None
    found = check(manifest, episodes)
    if (folder / PARQUET).exists(): _rule_9(folder / PARQUET, lines, episodes)
    return found


def pages(client, body):
    """Every page of one export: one `until`, one `reconstruction`, an advancing `next`, the manifest on the last only."""
    _, adapter = _models()
    after, first = 0, None
    while True:
        page = client._post('activity', 'trajectories', {**body, 'after': after, 'limit': LIMIT, **({'until': first['until']} if first else {})}, retry=True)
        if first is None: first = page
        elif page.get('reconstruction') != first['reconstruction']: raise IntegrityConflict(CHANGED)
        elif page.get('until') != first['until']: raise VerificationFailed('The server answered another boundary while exporting; export again.')
        for n, e in enumerate(page['episodes'], 1): _episode(adapter, e, n)
        if page['next'] is not None and page['next'] <= after: raise VerificationFailed('The server did not advance the export; export again.')
        if (page['manifest'] is None) == (page['next'] is None): raise VerificationFailed('The server answered the manifest on another page than the last.')
        yield page
        if page['next'] is None: return
        after = page['next']


def export(client, destination, *, purpose, mode='auto', window_seconds=None, seed=0, until=None):
    """Write your own work in the client's project to `destination` (a new folder): {episodes, values, destination,
    parquet}. `until` (s3): the boundary of an earlier export's manifest, to repeat it; default the highest row now."""
    from ._version import __version__
    destination = Path(destination)
    if destination.exists() or destination.is_symlink(): raise Refused('The destination exists; name a new folder.')
    if not destination.parent.is_dir(): raise Refused('The destination\'s folder does not exist.')
    body = {'purpose': purpose, 'mode': mode, 'seed': seed, **({'window_seconds': window_seconds} if window_seconds is not None else {}),
            **({'until': until} if until is not None else {})}
    staging = destination.parent / ('.%s.partial-%s' % (destination.name, secrets.token_hex(4)))
    os.mkdir(staging, 0o700)
    try:
        written, manifest = [], None
        with open(staging / EPISODES, 'wb') as lines:
            for page in pages(client, body):
                for e in page['episodes']:
                    written.append(canonical(e).decode())
                    lines.write(canonical(e) + b'\n')
                manifest = page['manifest']
        write_manifest(staging / MANIFEST, manifest, __version__)
        parquet = write_parquet(written, staging / PARQUET)
        load(staging)
        if destination.exists() or destination.is_symlink(): raise Refused('The destination exists; name a new folder.')
        os.rename(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {'episodes': len(written), 'values': manifest['counts']['values'], 'destination': str(destination), 'parquet': parquet}


class TrajectoryClient:
    def export_trajectories(self, destination, *, purpose, mode='auto', window_seconds=None, seed=0, until=None):
        """E134: your own consented work in this project, as a folder of work episodes at `destination` (a new folder);
        `auto` gives values where the rights allow, `shape` never values; `until` repeats an earlier export's boundary
        (s3). With pyarrow installed the folder also holds episodes.parquet. Returns {episodes, values, destination, parquet}."""
        return export(self, destination, purpose=purpose, mode=mode, window_seconds=window_seconds, seed=seed, until=until)
