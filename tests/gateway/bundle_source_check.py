"""E122 s5b (D5): an independent check of a portable bundle's source records against the gateway that served them.

It imports no `ophiolite` module: it reads `manifest.json` as JSON, takes the exported (asset_id, revision) pairs from
the caller (the test's own creations), checks the inventory first, then validates each carried record against the
Platform's `source-provenance/1` schema (jsonschema) and compares it, as parsed JSON, with the route's `record`."""
import json
from collections import Counter
from pathlib import Path

WRAPPER = {'schema', 'asset_id', 'revision', 'record'}
SCHEMA = 'ophiolite.source-provenance/1'


def check(root, expected, route, schema):
    """The failures of the bundle at ROOT as (kind, (asset_id, revision)) pairs, empty when it holds.

    EXPECTED lists the exported pairs with multiplicity; ROUTE(asset_id, revision) returns the served provenance answer
    (a dict) or raises when the route refuses; SCHEMA is the Platform's source-provenance/1 schema document."""
    import jsonschema
    manifest = json.loads((Path(root) / 'manifest.json').read_text())
    entries = [e if isinstance(e, dict) else {} for e in manifest.get('assets') or []]
    found = Counter((e.get('asset_id'), e.get('revision')) for e in entries)
    wanted = Counter(tuple(pair) for pair in expected)
    if found != wanted:
        return [('inventory', pair) for pair in sorted((found - wanted) + (wanted - found), key=repr)]
    valid = jsonschema.Draft202012Validator(schema).is_valid
    failures = []
    for e in entries:
        key = (e['asset_id'], e['revision'])
        held = e.get('source_record')
        try:
            served = route(*key)
        except Exception:
            failures.append(('route-refuses', key)); continue
        record = served.get('record')
        if held is None:
            if record is not None: failures.append(('record-missing', key))
            continue
        if not isinstance(held, dict) or set(held) != WRAPPER or held.get('schema') != SCHEMA or not isinstance(held.get('record'), dict) \
                or not valid(held['record']):
            failures.append(('schema', key)); continue
        if (held['asset_id'], held['revision']) != key:
            failures.append(('identity', key)); continue
        if record is None:
            failures.append(('record-unexpected', key))
        elif held['record'] != record:
            failures.append(('differs-from-route', key))
    return failures
