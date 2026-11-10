"""E162 s2a (D2): restore a portable bundle that carries a wells table (bundle 2.17) into a project, wells first.

    from ophiolite.restore import restore
    rows = restore(client, 'f3-block.zip', audience=[], attribution='Source: ...', rights_confirmed=True)

The steps, each repeatable to the same end:

0. Refuse before any write: rights not confirmed, a bundle that fails its check, a manifest whose SHA-256 is not
   `expected_manifest_sha256`, or anything outside the bounded shape (wells only, of-entity edges only, no packages,
   logs, tops, trajectories, regular grids and one wells table, every tops file and survey bound to a log).
1. Wells: the table's kept rows written again as a CSV (its columns in order) and imported through the production
   table import with the kept mapping and declarations and the wells' identity authority. A repeat finds them all here.
2. Logs and horizons, then 3. tops and surveys bound to the restored logs, each through import_bundle's own upload
   step with E18's stable commands, so a repeat returns the same destinations.
4. Each of-entity edge between a restored revision and its well is asserted again with the statement
   `RESTORED`, which names no digest (E162 s2d: a well page shows it); an edge already there is skipped.
5. One row per bundle item: `restored` with its destination, or `refused`/`failed`/`not attempted` with a reason. Any
   row that is not `restored` raises RestoreIncomplete (an ImportIncomplete) carrying them all.
"""
import csv
import hashlib
import io
import tempfile
from pathlib import Path

from .bundle import WELL_TABLE, Bundle, import_plan, open_bundle
from .errors import Refused, RestoreIncomplete, ValidationFailed

TYPES = ('well-log', 'well-tops', 'trajectory', 'regular-grid-surface', WELL_TABLE)
BOUND = ('well-tops', 'trajectory')  # restored after the logs they are bound to
RESTORED = 'Restored from the portable bundle.'  # each restored item's well association, as a well page shows it
NOT_BOUNDED = 'This bundle holds more than a restoration takes (wells, their logs, tops and surveys, regular grids and one wells table): '
DECLARED = ('crs', 'depth_kind', 'depth_reference', 'depth_unit')  # the wells import's declarations the kept mapping records
NOT_IMPORTED = 'The wells import did not give the well %s; nothing after the wells was written.'


def restore(client, bundle, *, audience, attribution, rights_confirmed, expected_manifest_sha256=None):
    """Restore BUNDLE (a folder, a .zip or an opened Bundle) into the client's project; one row per bundle item."""
    if rights_confirmed is not True:
        raise ValidationFailed(['Confirm that you may retain these files, derive results and share them within the audience; holding a bundle grants no rights.'])
    opened = bundle if isinstance(bundle, Bundle) else open_bundle(bundle)  # the full check, before anything is written
    digest = hashlib.sha256((opened.path / 'manifest.json').read_bytes()).hexdigest()
    if expected_manifest_sha256 is not None and digest != expected_manifest_sha256:
        raise Refused('This bundle is not the expected one: its manifest has SHA-256 %s, not %s. Nothing was written.' % (digest, expected_manifest_sha256))
    table = bounded(opened)
    wells = restore_wells(client, opened, table, digest, audience)
    rows = {(table.asset_id, table.revision): {'position': opened.assets.index(table), 'asset_id': table.asset_id, 'revision': table.revision,
                                               'type': WELL_TABLE, 'state': 'restored', 'destination': kept_copy(client, wells)}}
    destinations = upload(client, opened, None, rows, audience, attribution)
    logs = {a: (d['asset_id'], d['revision']) for (a, r), d in destinations.items() if rows[(a, r)]['type'] == 'well-log'}
    destinations.update(upload(client, opened, logs, rows, audience, attribution))
    associate(client, opened, destinations, wells, digest)
    report = [rows[(a.asset_id, a.revision)] for a in opened.assets]
    if any(r['state'] != 'restored' for r in report):
        raise RestoreIncomplete('The restoration did not finish; repeat it to continue (what was restored is not duplicated).', details={'assets': report})
    return report


def bounded(opened):
    """The bundle's one wells table, or Refused naming the first item outside the bounded shape."""
    for e in opened.entities:
        if e.kind != 'well': raise Refused(NOT_BOUNDED + 'the %s %r.' % (e.kind, e.name))
    for r in opened.relationships:
        if r.get('predicate') != 'of-entity': raise Refused(NOT_BOUNDED + 'a %s relationship.' % r.get('predicate'))
    tables = []
    for a in opened.assets:
        name = '%s %s' % (a.type, a.asset_id)
        if a.type not in TYPES: raise Refused(NOT_BOUNDED + name + '.')
        if a.package is not None: raise Refused(NOT_BOUNDED + 'the package ' + name + '.')
        if a.type in BOUND and not (a.entry.get('relationships') or {}).get('well_log'):
            raise Refused(NOT_BOUNDED + name + ' is bound to no well log.')
        if a.type == WELL_TABLE: tables.append(a)
    if not tables: raise Refused('This bundle holds no wells table, so its wells cannot be restored; import it with import_bundle instead.')
    return tables[0]


def table_csv(table):
    """The kept rows as CSV bytes: the source's columns in order, a value as written by repr for numbers, empty for none."""
    columns = [c['name'] for c in table.source_schema]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\r\n')
    writer.writerow(columns)
    for row in table.source_rows:
        writer.writerow(['' if row.get(c) is None else repr(row[c]) if isinstance(row[c], float) else str(row[c]) for c in columns])
    return out.getvalue().encode()


def restore_wells(client, opened, asset, digest, audience):
    """Step 1: {exported well entity id: restored well entity id}, by identity; Refused for a well not given."""
    authorities = {(e.identity or {}).get('authority') for e in opened.entities}
    if len(authorities) != 1 or None in authorities: raise Refused('The wells in this bundle name %d identity authorities; a restoration takes one.' % len(authorities))
    table = asset.data
    mapping = table.mapping
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / ('%s.csv' % (asset.entry.get('name') or 'wells').replace('/', '-')[:80])
        path.write_bytes(table_csv(table))
        done = client.imports.from_table(path, 'wells', dict(mapping['fields']), declarations={k: mapping[k] for k in DECLARED if k in mapping},
                                         authority=next(iter(authorities)), audience=list(audience),
                                         command_id=hashlib.sha256(('%s:wells' % digest).encode()).hexdigest()[:32])
    if (done.get('run') or {}).get('state') != 'complete': raise Refused('The wells import did not finish: %s. Nothing after the wells was written.' % (done.get('run') or {}).get('state'))
    restored = {((w.document.get('identity') or {}).get('authority'), (w.document.get('identity') or {}).get('key')): w for w in client.wells()}
    wells = {}
    for e in opened.entities:
        found = restored.get((e.identity.get('authority'), e.identity.get('key')))
        if found is None: raise Refused(NOT_IMPORTED % e.identity.get('key'))
        wells[e.entity_id] = found
    return wells


def kept_copy(client, wells):
    """The restored kept table that locates the restored wells: {asset_id, revision}."""
    sources = {(w.location or {}).get('source', {}).get('asset_id'): (w.location or {}).get('source', {}).get('revision') for w in wells.values()}
    asset, revision = next(iter(sources.items())) if len(sources) == 1 else (None, None)
    return {'asset_id': asset, 'revision': revision}


def upload(client, opened, well_logs, rows, audience, attribution):
    """Steps 2 and 3: with well_logs None, the logs and horizons; then, with {exported log: restored (asset, revision)},
    the tops and surveys bound to the restored logs. Rows for this pass go into ROWS; {(asset, revision): destination} of
    what was restored."""
    bound = well_logs is not None
    restored = {}
    plan = [s for s in import_plan(opened, well_logs or {}) if s['type'] != WELL_TABLE and (s['type'] in BOUND) == bound]
    for position, step in enumerate(plan):
        key = (step['asset_id'], step['revision'])
        if step['state'] != 'ready':
            rows[key] = public(step); continue
        try: row = client._import_step(step, audience=audience, attribution=attribution, rights_confirmed=True)
        except Exception as error:
            rows[key] = {**public(step), 'state': 'failed', 'reason': str(error)[:300]}
            for later in plan[position + 1:]: rows[(later['asset_id'], later['revision'])] = {**public(later), 'state': 'not attempted'}
            stop(opened, rows, error)
        rows[key] = dict(row, state='restored') if row['state'] == 'imported' else row
        if row['state'] == 'imported': restored[key] = row['destination']
    return restored


def stop(opened, rows, error):
    """A failed upload stops the restoration; every item not reached is `not attempted`."""
    report = [rows.get((a.asset_id, a.revision)) or {'position': n, 'asset_id': a.asset_id, 'revision': a.revision, 'type': a.type, 'state': 'not attempted'}
              for n, a in enumerate(opened.assets)]
    raise RestoreIncomplete('The restoration stopped; repeat it to continue (what was restored is not duplicated).', details={'assets': report}) from error


def public(step):
    return {k: v for k, v in step.items() if k in ('position', 'asset_id', 'revision', 'type', 'state', 'reason', 'destination', 'origin')}


def associate(client, opened, destinations, wells, digest):
    """Step 4: each whole-revision of-entity edge again, between the restored revision and the restored well."""
    present = {}
    for r in opened.relationships:
        subject = r['subject']
        if subject.get('row') is not None: continue  # the table's row edges: the wells import made them
        destination = destinations.get((subject['asset_id'], subject['revision']))
        well = wells.get(r['object']['entity_id'])
        if destination is None or well is None: continue
        if well.entity_id not in present:
            present[well.entity_id] = {(i.get('asset_id'), i.get('revision')) for i in client.data(well.entity_id)}
        if (destination['asset_id'], destination['revision']) in present[well.entity_id]: continue
        client.of_entity(destination['asset_id'], destination['revision'], well.entity_id,
                         statement=RESTORED,  # E162 s2d: a reader's sentence; the digest is the record's manifest_sha256
                         command_id=hashlib.sha256(('%s:%s:%s' % (digest, destination['revision'], well.entity_id)).encode()).hexdigest()[:32])
