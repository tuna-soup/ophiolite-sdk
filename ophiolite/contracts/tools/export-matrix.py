#!/usr/bin/env python3
"""E116 s3 C1 (D4): write contracts/mapper/v1/export-matrix.json (ophiolite.osdu-export-matrix/1), the OSDU kind each
reader profile and each table target would export as, from the declarations that already state it.

    python contracts/tools/export-matrix.py            # rewrite the document
    python contracts/tools/export-matrix.py --check    # exit 1 naming the first difference

E168 s0 (D5): it also writes osdu_kind and osdu_kind_reason into every profile document of profiles/v1 that has a row,
and --check covers those documents too.

One row per reader profile of connectors/v1/readers.json and per table target of targets/v1/. A reader's kind is its
own `osdu.kind` (E55: the reader registry is the one place an upload kind is declared), else the `osdu_export` of the
typed-standards row of its type, else none ("no correspondence declared"). A table target's is the `osdu_export` of its
`standards.profile` row, or its `standards.none` reason. An unversioned kind becomes the one vocabulary kind of that
name; a name the vocabulary does not hold is none, "not a kind the box vendors at v0.30.1". written_by_box is true only
for what ophiolite-mapper writes in slice 3 (WRITTEN); every other row is a declaration. Standard library only.
"""
import json
import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1]
OUT = CONTRACTS / 'mapper/v1/export-matrix.json'
PROFILES = CONTRACTS / 'profiles/v1'
WRITTEN = {'las2/1': 'osdu:wks:work-product-component--WellLog:1.5.0', 'ophiolite.table-target/wells/1': 'osdu:wks:master-data--Well:1.5.0'}
DECLARATIONS = ['osdu.namespace', 'osdu.legal_tag', 'osdu.owners', 'osdu.viewers']


class Refused(Exception):
    pass


def _json(path):
    return json.loads((CONTRACTS / path).read_text(encoding='utf-8'))


def _versioned(name, kinds):
    """The vocabulary kind of an unversioned name (work-product-component--WellLog), or None."""
    found = [k for k in kinds if k.split(':')[2] == name]
    if len(found) > 1: raise Refused(f'{name} names {len(found)} vocabulary kinds')
    return found[0] if found else None


def _row(profile, statement, kinds, typed):
    """{profile, kind | none, written_by_box, declarations, losses} from one statement: a kind name, an osdu_export
    or a reason."""
    losses = typed.get('differences', []) if typed else []
    if 'kind' in statement:
        kind = statement['kind'] if statement['kind'].count(':') == 3 else _versioned(statement['kind'], kinds)
        if kind is None:
            statement = {'none': f'{statement["kind"]} is not a kind the box vendors at v0.30.1'}
        elif kind not in kinds:
            raise Refused(f'{profile}: {kind} is not in the vocabulary')
        else:
            written = WRITTEN.get(profile) == kind
            if profile in WRITTEN and not written: raise Refused(f'{profile}: written as {WRITTEN[profile]}, declared {kind}')
            return {'profile': profile, 'kind': kind, 'written_by_box': written, 'declarations': DECLARATIONS if written else [],
                    'losses': losses}
    if profile in WRITTEN: raise Refused(f'{profile} is written by the box but declares no kind')
    return {'profile': profile, 'none': statement['none'], 'written_by_box': False, 'declarations': [], 'losses': losses}


def document():
    kinds = set(_json('mapper/v1/osdu-vocabulary.json')['kinds'])
    typed = {r['profile']: r for r in _json('mappings/v1/typed-standards.json')['types']}
    rows = []
    for reader in _json('connectors/v1/readers.json')['readers']:
        row = typed.get(f'ophiolite.{reader.get("type")}/1')
        if (reader.get('osdu') or {}).get('kind'): statement = {'kind': reader['osdu']['kind']}
        elif row and 'osdu_export' in row: statement = row['osdu_export']
        else: statement = {'none': 'no correspondence declared'}
        rows.append(_row(reader['profile'], statement, kinds, row))
    for path in sorted((CONTRACTS / 'targets/v1').glob('*.json')):
        target = json.loads(path.read_text(encoding='utf-8'))
        standards = target['standards']
        row = typed.get(standards.get('profile'))
        if row and 'osdu_export' in row: statement = row['osdu_export']
        elif 'none' in standards: statement = {'none': standards['none']}
        else: statement = {'none': 'no correspondence declared'}
        rows.append(_row(target['id'], statement, kinds, row))
    names = [r['profile'] for r in rows]
    if len(set(names)) != len(names): raise Refused('a profile is listed twice')
    missing = sorted(set(WRITTEN) - set(names))
    if missing: raise Refused(f'{missing[0]} is written by the box but is not a reader profile or table target')
    return {'schema': 'ophiolite.osdu-export-matrix/1', 'tag': 'v0.30.1', 'rows': rows}


def text(doc):
    rows = ',\n'.join('  ' + json.dumps(r, ensure_ascii=False) for r in doc['rows'])
    return '{\n' + f' "schema": {json.dumps(doc["schema"])},\n "tag": {json.dumps(doc["tag"])},\n "rows": [\n{rows}\n ]\n' + '}\n'


def profiles(doc, folder=PROFILES):
    """E168 s0 (D5): {path: text} of every profile document with a matrix row, its osdu_kind and osdu_kind_reason
    written from the row (one of them null). Documents without a row are left as they are."""
    rows = {r['profile']: r for r in doc['rows']}
    out = {}
    for path in sorted(Path(folder).glob('*.json')):
        profile = json.loads(path.read_text(encoding='utf-8'))
        row = rows.get(profile.get('id'))
        if row is None: continue
        profile['osdu_kind'], profile['osdu_kind_reason'] = (row['kind'], None) if row.get('kind') else (None, row['none'])
        out[path] = json.dumps(profile, indent=2, ensure_ascii=False) + '\n'
    return out


def main(argv, out=OUT, folder=PROFILES):
    try: doc = document()
    except Refused as error:
        print(f'export-matrix: refused: {error}', file=sys.stderr); return 1
    wanted = {Path(out): text(doc), **profiles(doc, folder)}
    if '--check' in argv:
        differs = [p for p, t in wanted.items() if not p.exists() or p.read_text(encoding='utf-8') != t]
        if differs:
            print(f'export-matrix: {differs[0].name} differs from the generator', file=sys.stderr); return 1
        print(f'export-matrix.json and {len(wanted) - 1} profile documents equal the generator'); return 0
    for path, body in wanted.items(): path.write_text(body, encoding='utf-8')
    print(f'wrote {out} and {len(wanted) - 1} profile documents'); return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
