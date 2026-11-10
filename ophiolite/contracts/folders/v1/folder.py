"""ophiolite.project-folder-validator/2 (E117 s0): the one validator of a project folder block, /2 and /1 alike, and the
explicit reading of a /1 block as /2 (translate_1).

The Platform tests and the SDK (ophiolite.folder) run this same file, loaded from its source text:

    module = types.ModuleType('ophiolite_folder_contract'); module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)

Standard library only (Python 3.10). It reads its documents from beside itself and from the contracts tree it sits in
(the same layout in the Platform and in the SDK snapshot): folder-schema.json and kinds.json here, the mapper's /1
validator, folder schema and export matrix (mapper/v1), and the table targets (targets/v1). The structure is applied by
the mapper's small JSON Schema reader (one reader for both versions). Nothing here reads a file of the folder: digests,
sizes and links are the reader's (ophiolite.folder.check), which hands the verified manifest and recipe in as data.
"""
import json
import re
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
FOLDER_1, FOLDER_2 = 'ophiolite.project-folder/1', 'ophiolite.project-folder/2'
BUNDLE_2 = 'ophiolite.portable-bundle/2'
# E117 s1 (D3): the least bundle minor each folder schema needs; the one answer both SDK entry points use.
MINOR = {FOLDER_1: 12, FOLDER_2: 14}
MAPPER_WRITER = 'ophiolite-mapper'
CRS = re.compile(r'^EPSG:[1-9][0-9]{3,5}$')
# Every rule code validate() can raise beside the schema-<keyword> codes of the structure (folder-spec.py binds each to a
# row of the page and an invalid fixture).
CODES = ('manifest-invalid', 'schema-unknown', 'recipe-writer', 'path-repeated', 'path-in-asset', 'media-type', 'asset-missing',
         'asset-unknown', 'role-repeated', 'role-path', 'asset-misplaced', 'role-count', 'identity-partial', 'recipe-digest',
         'item-repeated', 'profile-unknown', 'kind-profile', 'item-suffix', 'item-file', 'osdu-kind', 'declaration-unknown',
         'crs-conflict', 'rows-type')


def _read(*parts):
    return json.loads(CONTRACTS.joinpath(*parts).read_text(encoding='utf-8'))


def _mapper():
    path = CONTRACTS / 'mapper' / 'v1' / 'mapper.py'
    module = types.ModuleType('ophiolite_mapper_contract')
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
    return module


MAPPER = _mapper()
MapperError = MAPPER.MapperError
SCHEMA = _read('folders', 'v1', 'folder-schema.json')
KINDS = _read('folders', 'v1', 'kinds.json')['profiles']
MATRIX = {row['profile']: row for row in _read('mapper', 'v1', 'export-matrix.json')['rows']}
TARGETS = {row['target']: _read('targets', 'v1', row['target'] + '.json') for row in KINDS.values() if 'target' in row}


class FolderError(ValueError):
    """The first problem found: a code (schema-<keyword> for structure, a rule's name otherwise) and a JSON path."""

    def __init__(self, code, path):
        super().__init__(f'{code} at {path}')
        self.code, self.path = code, path


def declared(profile):
    """{name: kind} of what an item of PROFILE may declare: its target's declarations, or the reader profile's own."""
    row = KINDS[profile]
    if 'target' in row: return {d['name']: d['kind'] for d in TARGETS[row['target']]['declarations']}
    return dict(row['declarations'])


def _value_ok(profile, name, value):
    kind = declared(profile)[name]
    if kind == 'number': return isinstance(value, (int, float)) and not isinstance(value, bool)
    if not isinstance(value, str): return False
    if kind == 'crs': return bool(CRS.fullmatch(value))
    if kind in ('unit', 'choice'):
        target = TARGETS[KINDS[profile]['target']]
        return value in [v['value'] for d in target['declarations'] if d['name'] == name for v in d['values']]
    return True  # text: the structure's length is the rule


def osdu_of(profile):
    """The export matrix's statement for PROFILE: {kind} or {none: reason}."""
    row = MATRIX[profile]
    return {'kind': row['kind']} if 'kind' in row else {'none': row['none']}


def _manifest(manifest, schema):
    if not isinstance(manifest, dict) or manifest.get('schema') != BUNDLE_2: raise FolderError('manifest-invalid', '$.schema')
    version = manifest.get('bundle_version')
    if not isinstance(version, str) or not re.fullmatch(r'2\.[0-9]+\.[0-9]+', version) or int(version.split('.')[1]) < MINOR[schema]:
        raise FolderError('manifest-invalid', '$.bundle_version')
    assets = manifest.get('assets', [])
    if not isinstance(assets, list) or not all(isinstance(a, dict) and isinstance(a.get('files', []), list) for a in assets):
        raise FolderError('manifest-invalid', '$.assets')
    return assets


def validate(block, manifest, recipe=None):
    """Raise FolderError for the first problem of a manifest's folder block, read with the enclosing manifest. A /1
    block goes to its own validator (mapper/v1/mapper.py validate_folder, RECIPE binding its items as there); a /2 block
    to validate_2. Returns the block."""
    schema = block.get('schema') if isinstance(block, dict) else None
    _manifest(manifest, schema if schema in MINOR else FOLDER_1)
    if schema == FOLDER_1:
        try: return MAPPER.validate_folder(block, manifest, recipe)
        except MapperError as error: raise FolderError(error.code, error.path) from None
    if schema == FOLDER_2: return validate_2(block, manifest)
    raise FolderError('schema-unknown', '$.folder.schema')


def validate_2(block, manifest):
    """The /2 rules of BLOCK, also of translate_1's reading of a /1 block: the envelope's shape, not its minor, which is
    validate()'s for a block as written (MINOR)."""
    try: MAPPER.structure(SCHEMA, block, SCHEMA, '$.folder')
    except MapperError as error: raise FolderError(error.code, error.path) from None
    assets = _manifest(manifest, FOLDER_1)
    mapper = block['writer']['name'] == MAPPER_WRITER
    if mapper != ('recipe' in block): raise FolderError('recipe-writer', '$.folder.recipe' if 'recipe' in block else '$.folder.writer.name')
    roles, writer = SCHEMA['roles'], 'mapper' if mapper else 'other'
    listed = {f.get('path') for a in assets for f in a.get('files', [])}
    paths, counts, per_asset = {}, {}, set()
    for i, row in enumerate(block['files']):
        path = f'$.folder.files[{i}]'
        rule = roles[row['role']]
        if row['path'] in paths: raise FolderError('path-repeated', f'{path}.path')
        paths[row['path']] = i
        if row['path'] in listed: raise FolderError('path-in-asset', f'{path}.path')
        if row['media_type'] not in rule['media_types']: raise FolderError('media-type', f'{path}.media_type')
        if rule['asset']:
            if row['asset'] is None: raise FolderError('asset-missing', f'{path}.asset')
            if row['asset'] >= len(assets): raise FolderError('asset-unknown', f'{path}.asset')
            if row['asset'] in per_asset: raise FolderError('role-repeated', path)
            per_asset.add(row['asset'])
            if row['path'] != rule['path'].format(asset=row['asset']): raise FolderError('role-path', f'{path}.path')
        elif row['asset'] is not None: raise FolderError('asset-misplaced', f'{path}.asset')
        elif 'pattern' in rule:
            if not re.fullmatch(rule['pattern'], row['path']) or row['path'].rsplit('/', 1)[1] in ('.', '..'):
                raise FolderError('role-path', f'{path}.path')
        else:
            if counts.get(row['role']): raise FolderError('role-repeated', path)
            if row['path'] != rule['path']: raise FolderError('role-path', f'{path}.path')
        counts[row['role']] = counts.get(row['role'], 0) + 1
    for role, rule in roles.items():
        count, n = rule[writer], counts.get(role, 0)
        if (count == 'one' and n != 1) or (count == 'none' and n) or (count == 'at-least-one' and not n) \
                or (count == 'without-assets' and not assets and not n):
            raise FolderError('role-count', f'$.folder.files:{role}')
    identity = [r for r, rule in roles.items() if rule[writer] == 'identity']
    if 0 < sum(counts.get(r, 0) for r in identity) < len(identity): raise FolderError('identity-partial', '$.folder.files')
    if mapper and block['files'][next(i for i, r in enumerate(block['files']) if r['role'] == 'recipe')]['sha256'] != block['recipe']['sha256']:
        raise FolderError('recipe-digest', '$.folder.recipe.sha256')
    _items(block, paths)
    return block


def _items(block, paths):
    seen = set()
    for i, item in enumerate(block['items']):
        path = f'$.folder.items[{i}]'
        if item['path'] in seen: raise FolderError('item-repeated', f'{path}.path')
        seen.add(item['path'])
        row = KINDS.get(item['profile'])
        if row is None or item['profile'] not in MATRIX: raise FolderError('profile-unknown', f'{path}.profile')
        if item['kind'] != row['kind']: raise FolderError('kind-profile', f'{path}.kind')
        if not item['path'].endswith(row['suffix']): raise FolderError('item-suffix', f'{path}.path')
        index = paths.get(item['path'])
        if index is None or block['files'][index]['role'] != 'item': raise FolderError('item-file', f'{path}.path')
        if block['files'][index]['media_type'] != row['media_type']: raise FolderError('media-type', f'$.folder.files[{index}].media_type')
        if item['osdu'] != osdu_of(item['profile']): raise FolderError('osdu-kind', f'{path}.osdu')
        allowed, names = declared(item['profile']), {}
        for j, declaration in enumerate(item['declarations']):
            name, where = declaration['name'], f'{path}.declarations[{j}]'
            if name in names and allowed.get(name) == 'crs': raise FolderError('crs-conflict', where)
            if name in names or name not in allowed or not _value_ok(item['profile'], name, declaration['value']):
                raise FolderError('declaration-unknown', where)
            names[name] = declaration['value']
        if (item['rows'] is None) != (row['suffix'] == '.tif') or isinstance(item['rows'], bool): raise FolderError('rows-type', f'{path}.rows')
    for i, file_row in enumerate(block['files']):
        if file_row['role'] == 'item' and file_row['path'] not in seen: raise FolderError('item-file', f'$.folder.files[{i}].path')


def profile_of(recipe):
    """The /2 profile of a /1 recipe's target: a table target's profile id, or the reader profile itself."""
    target = recipe['target']
    return f"ophiolite.table-target/{target['id']}/1" if target['kind'] == 'table-target' else target['id']


def translate_1(block, recipe, prov):
    """The /2 reading of a /1 block (never written back): the writer from `mapper`; one item per /1 item row, its
    profile from the verified RECIPE's target, its declarations the recipe's decided values, its rows the count the
    write's lineage document PROV records (ophiolite:rows_written; a /1 folder carries one item), its OSDU statement
    the export matrix's. The files are /1's rows unchanged."""
    name, _, version = block['mapper'].partition(' ')
    profile = profile_of(recipe)
    written = [a.get('ophiolite:rows_written') for a in prov['activity'].values()]
    items = [{'path': row['path'], 'profile': profile, 'kind': KINDS[profile]['kind'] if profile in KINDS else None,
              'osdu': osdu_of(profile) if profile in MATRIX else None,
              'declarations': [{'name': d['name'], 'value': d['value']} for d in recipe['declarations'] if d['value'] is not None],
              'rows': written[0] if len(written) == 1 else None}
             for row in block['files'] if row['role'] == 'item']
    return {'schema': FOLDER_2, 'writer': {'name': name, 'version': version}, 'recipe': dict(block['recipe']),
            'osdu': dict(block['osdu']), 'items': items, 'files': [dict(row) for row in block['files']]}
