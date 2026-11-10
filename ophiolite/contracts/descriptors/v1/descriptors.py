"""ophiolite.release-descriptors/1 (E147 s0): the citation block of a bundle manifest (bundle 2.15) and the comparison of
the three standard descriptors derived from it (RO-Crate 1.1, Croissant 1.0, DataCite kernel-4.3 JSON) with the
manifest they were derived from.

The Platform tests and the SDK run this same file, loaded from its source text, as folders/v1/folder.py is:

    module = types.ModuleType('ophiolite_descriptors_contract'); module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)

Standard library only (Python 3.10). It reads its documents from beside itself and from the contracts tree it sits in
(citation-schema.json here; the mapper's small JSON Schema reader; the folder kinds table and the table targets for a
project folder's tables). Nothing here reads a file of the bundle: links, sizes, the running total and the PROV digest
are the reader's, which hands each descriptor's bytes in (parse, verify).

What is compared is not mapping.json (the documented table) but three explicit projections, one per descriptor: each
returns a flat dict {json path: value} of the places the mapping fixes, compared for equality with the dict expected()
builds from the citation, the manifest's files and its tables. Everything outside a projection is free. A path selects
a list member by a key as [key=value] (an RO-Crate node by [@id=...], a DataCite description by its type); MISSING
stands for an absent place.

E160 s0 (D3): a folder of work episodes is the third source. Its manifest (trajectories.json, ophiolite.work-episodes/1
at 1.2.0) gives a citation, derived and never stored, its files, one record set over turns.jsonl and four responsible-AI
places of the Croissant (episodes_inputs, verify_episodes, episodes_documents).
"""
import hashlib
import json
import math
import re
import types
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
BUNDLE_2 = 'ophiolite.portable-bundle/2'
FOLDER_2 = 'ophiolite.project-folder/2'
CITATION = 'ophiolite.citation/1'
# The least bundle minor a manifest with a citation needs (2.15: the citation block and BundleFileV2.media_type).
MINOR = 15
# E147 s2b (bundle 2.16): from this minor a cited bundle's typed tables are compared as Croissant record sets.
TABLES_MINOR = 16
# E147 s2b D2: the typed bundle originals with a table target (E86) -> (target, [(field, jsonPath into data.json)]), the
# target's fields in its order that the normalized form holds in every row. Left out: `well` (the asset is one well's),
# time-depth `velocity` (the form allows a null member, which no reader can read as a column) and point-set `attributes`
# (named per file); the point-columns form (data.ophpts) has no table. Those are E147 s2c.
BUNDLE_TABLES = {
    'well-tops-csv/1': ('well-tops', [('name', '$.tops[*].name'), ('md', '$.tops[*].md'), ('tvd', '$.tops[*].tvd'),
                                      ('source', '$.tops[*].source')]),
    'deviation-csv/1': ('deviation-survey', [('md', '$.stations[*].md'), ('inclination', '$.stations[*].inclination'),
                                             ('azimuth', '$.stations[*].azimuth'), ('tvd', '$.stations[*].tvd')]),
    'time-depth-csv/1': ('time-depth', [('depth', '$.depth[*]'), ('time', '$.time[*]')]),
    'points-csv/1': ('point-set', [('x', '$.points[*][0]'), ('y', '$.points[*][1]'), ('z', '$.points[*][2]')]),
}
TABLE_DATA = 'data.json'
RO_CRATE_NAME, CROISSANT_NAME, DATACITE_NAME = 'ro-crate-metadata.json', 'croissant.json', 'datacite.json'
NAMES = (RO_CRATE_NAME, CROISSANT_NAME, DATACITE_NAME)
PROV_PATH = 'prov.json'
MANIFEST_NAME = 'manifest.json'
# E147 s3: a starter pack (Open Subsurface Data's osd.starter/1) is the second source. Its citation is derived, never
# stored (R-2): from starter.json and the catalogue record its evidence.json holds; its files are the pack's artefacts.
STARTER_NAME, STARTER_EVIDENCE, STARTER_FILES = 'starter.json', 'evidence.json', 'files/'
STARTER_PUBLISHER = {'name': 'Open Subsurface Data'}  # the pack's builder (s0 D1)
STARTER_RESOURCE = 'Starter pack'
# An artefact's media type by its suffix; any other suffix (a SEG-Y cube) is application/octet-stream.
STARTER_MEDIA = {'.py': 'text/x-python', '.ipynb': 'application/x-ipynb+json', '.md': 'text/markdown',
                 '.json': 'application/json', '.geojson': 'application/geo+json', '.csv': 'text/csv', '.las': 'text/plain',
                 '.txt': 'text/plain'}
STARTER_OTHER_MEDIA = 'application/octet-stream'
PACK_NOTICE = ('The licence of this starter pack is not one of the open licences these descriptors name; its terms are in '
               'starter.json and files/ATTRIBUTION.md.')
# The metadata file the RO-Crate names beside the descriptors, its name in the crate and the words for "disagrees with".
# E160 s0 (D3): a folder of work episodes. Its files are trajectories.json and the payload files it lists, a media type by
# suffix; its one record set, `turns`, reads turns.jsonl.
EPISODES_NAME, TURNS = 'trajectories.json', 'turns.jsonl'
EPISODES_RESOURCE = 'Work episodes'
EPISODES_MEDIA = {'.json': 'application/json', '.jsonl': 'application/jsonlines', '.parquet': 'application/x-parquet'}
# The fields of `turns` (R3): every scalar leaf of a line, in the order of work-turn-mapping.json's entries (`n` after the
# three episode places), as (name, dataType, values only). The name is the line's dotted place: the field reads its first
# part by extract.column and the rest by transform.jsonPath; a null parent or an absent key reads as null. No list or object
# place is a field (mlcroissant 1.1.1 refuses one, or reads its first member or its characters).
TURN_FIELDS = (
    ('episode', 'sc:Text', False), ('mode', 'sc:Text', False), ('split', 'sc:Text', False), ('n', 'sc:Integer', False),
    ('attempt.chain', 'sc:Text', False), ('attempt.n', 'sc:Integer', False), ('attempt.from', 'sc:Text', False),
    ('attempt.continued', 'sc:Boolean', False),
    ('action.action_id', 'sc:Text', False), ('action.at', 'sc:Float', False), ('action.operation', 'sc:Text', False),
    ('action.through.client', 'sc:Text', False), ('action.through.version', 'sc:Text', False),
    ('action.on_behalf_of.kind', 'sc:Text', False), ('action.on_behalf_of.id', 'sc:Text', False),
    ('action.plan.plan_sha256', 'sc:Text', False), ('action.plan.evidence_sha256', 'sc:Text', False),
    ('action.instruction', 'sc:Text', True),
    ('judgement.attempt_ended', 'sc:Text', False),
    ('omitted.parameters', 'sc:Integer', False), ('omitted.checks', 'sc:Integer', False),
    ('omitted.verdicts', 'sc:Integer', False), ('omitted.plan', 'sc:Integer', False), ('omitted.offered', 'sc:Integer', False),
)
TURNS_DESCRIPTION = ('One record per line of turns.jsonl (ophiolite.work-turn/1), its scalar places. The lists and objects '
                     'of a line (inputs, parameters, outputs, checks, outcomes, verdicts, offered, request) are in '
                     'turns.jsonl, read whole with ophiolite.trajectories.load_turns.')
SOURCES = {MANIFEST_NAME: ('The bundle manifest', 'the manifest'), STARTER_NAME: ('The starter pack document', 'starter.json'),
           EPISODES_NAME: ('The work episodes manifest', 'trajectories.json')}
# Every code this module raises (the README's table; fixtures/invalid/cases.json has a case for each).
CODES = ('citation-minor', 'citation-schema', 'citation-media-type', 'notice-without-null-licence', 'descriptor-repeated',
         'descriptor-unreadable', 'descriptor-disagrees', 'starter-record', 'starter-artefact', 'episodes-manifest')
# The reader's own codes for a descriptor or prov.json it cannot take (cases.json layer "reader"): a listed file absent,
# a PROV digest that differs; a link, a non-file or a size over the limits is descriptor-unreadable.
READER_CODES = ('file-missing', 'file-digest', 'descriptor-unreadable')

SPDX = 'https://spdx.org/licenses/'
# V-1 (roc-validator 0.13.1, required check 3.1): RO-Crate 1.1's context does not define sha256; the crate adds the term.
RO_CRATE_CONTEXT = ['https://w3id.org/ro/crate/1.1/context', {'sha256': 'https://schema.org/sha256'}]
# V-2 (required check 8.3): the root must have a license; without an open licence it is this entity, carrying the notice.
NO_LICENCE = '#licence'
RO_CRATE = 'https://w3id.org/ro/crate/1.1'
PROV_JSON = 'https://www.w3.org/submissions/prov-json/'
CROISSANT = 'http://mlcommons.org/croissant/1.0'
CROISSANT_CONTEXT = {
    '@language': 'en', '@vocab': 'https://schema.org/', 'citeAs': 'cr:citeAs', 'column': 'cr:column',
    'conformsTo': 'dct:conformsTo', 'cr': 'http://mlcommons.org/croissant/', 'rai': 'http://mlcommons.org/croissant/RAI/',
    'data': {'@id': 'cr:data', '@type': '@json'}, 'dataType': {'@id': 'cr:dataType', '@type': '@vocab'},
    'dct': 'http://purl.org/dc/terms/', 'equivalentProperty': 'cr:equivalentProperty', 'examples': {'@id': 'cr:examples', '@type': '@json'}, 'extract': 'cr:extract',
    'field': 'cr:field', 'fileProperty': 'cr:fileProperty', 'fileObject': 'cr:fileObject', 'fileSet': 'cr:fileSet',
    'format': 'cr:format', 'includes': 'cr:includes', 'isLiveDataset': 'cr:isLiveDataset', 'jsonPath': 'cr:jsonPath',
    'key': 'cr:key', 'md5': 'cr:md5', 'parentField': 'cr:parentField', 'path': 'cr:path', 'recordSet': 'cr:recordSet',
    'references': 'cr:references', 'regex': 'cr:regex', 'repeated': 'cr:repeated', 'replace': 'cr:replace',
    'samplingRate': 'cr:samplingRate', 'sc': 'https://schema.org/', 'separator': 'cr:separator', 'source': 'cr:source', 'subField': 'cr:subField',
    'transform': 'cr:transform'}
DATACITE = 'http://datacite.org/schema/kernel-4'
# A table target field's kind -> its Croissant dataType (mapping.json "field_kinds").
DATA_TYPES = {'identifier': 'sc:Text', 'name': 'sc:Text', 'text': 'sc:Text', 'reference': 'sc:Text', 'number': 'sc:Float',
              'coordinate': 'sc:Float'}
# A creator's kind -> (its schema.org type, its DataCite nameType).
KINDS = {'person': ('Person', 'Personal'), 'organisation': ('Organization', 'Organizational')}
SCHEMES = {'orcid.org': 'ORCID', 'ror.org': 'ROR'}
# What documents() writes beyond the compared places (E147 s1 D1): writer guarantees fixed by the fixtures, not
# conformance requirements. The SPDX names of the four licence ids; the DataCite schemeUri of each identifier scheme.
LICENCE_NAMES = {'CC0-1.0': 'Creative Commons Zero v1.0 Universal',
                 'CC-BY-4.0': 'Creative Commons Attribution 4.0 International',
                 'PDDL-1.0': 'Open Data Commons Public Domain Dedication & License 1.0',
                 'ODC-By-1.0': 'Open Data Commons Attribution License v1.0'}
SCHEME_URIS = {'ORCID': 'https://orcid.org', 'ROR': 'https://ror.org'}
# What each compared place is, in words (the CLI's default line: "the licence in croissant.json disagrees ...").
WORDS = {'context': 'the descriptor type', 'title': 'the title', 'description': 'the description', 'creators': 'the creators',
         'publisher': 'the publisher', 'published': 'the publication date', 'version': 'the version', 'licence': 'the licence',
         'notice': 'the access notice', 'doi': 'the identifier', 'files': 'the files', 'manifest': 'the manifest entry',
         'prov': 'the provenance file', 'tables': 'the tables', 'collection': 'the collection statement',
         'sensitive': 'the personal information statement', 'uses': 'the use case', 'usage': 'the rights bases'}


class _Missing:
    def __repr__(self): return 'MISSING'


MISSING = _Missing()


def _mapper():
    path = CONTRACTS / 'mapper' / 'v1' / 'mapper.py'
    module = types.ModuleType('ophiolite_mapper_contract')
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
    return module


def _read(*parts):
    return json.loads(CONTRACTS.joinpath(*parts).read_text(encoding='utf-8'))


MAPPER = _mapper()
SCHEMA = _read('descriptors', 'v1', 'citation-schema.json')
FOLDER_KINDS = _read('folders', 'v1', 'kinds.json')['profiles']


class DescriptorError(ValueError):
    """The first problem: a code, the file it is in (manifest.json, a descriptor's name, prov.json) and a JSON path in
    it (None for the file as a whole). `where` is what --details prints; `subject` is the compared place's row."""

    def __init__(self, code, file, path=None, subject=None, source=MANIFEST_NAME):
        self.code, self.file, self.path, self.subject, self.source = code, file, path, subject, source
        super().__init__(f'{code} at {self.where}')

    @property
    def where(self):
        return self.file if self.path is None else f'{self.file}:{self.path}'


class CitationError(DescriptorError):
    """A problem of the manifest's citation block (or of the manifest a citation needs): file manifest.json."""

    def __init__(self, code, path):
        super().__init__(code, MANIFEST_NAME, path)


class StarterError(DescriptorError):
    """E147 s3: a starter pack whose citation cannot be derived: file starter.json (or evidence.json for its record)."""

    def __init__(self, code, file, path):
        super().__init__(code, file, path, source=STARTER_NAME)


class EpisodesError(DescriptorError):
    """E160 s0: a work-episodes manifest that cannot give a citation: file trajectories.json."""

    def __init__(self, code, path):
        super().__init__(code, EPISODES_NAME, path, source=EPISODES_NAME)


def sentence(error):
    """The default line's words for a refusal: 'the licence in croissant.json disagrees with the manifest' (with
    starter.json for a starter pack). Codes stay details, except the manifest citation's own (as since s0)."""
    if error.code == 'descriptor-disagrees':
        return f'{WORDS.get(error.subject, "a value")} in {error.file} disagrees with {SOURCES[error.source][1]}'
    if error.code == 'descriptor-unreadable':
        return f'{error.file} cannot be read as JSON within the limits'
    if error.code == 'starter-record':
        return 'the catalogue record in evidence.json names no publisher'
    if error.code == 'starter-artefact':
        return 'starter.json lists an artefact twice with different contents'
    if error.code == 'episodes-manifest':
        return 'trajectories.json is not a work-episodes manifest of version 1.2.0 that lists turns.jsonl'
    if error.source == STARTER_NAME:
        return 'starter.json does not give a valid citation'
    return f'the citation in the manifest is not valid ({error.code})'


# ---- the citation block ---------------------------------------------------------------------------------------------

def _minor(manifest):
    version = manifest.get('bundle_version') if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r'2\.[0-9]+\.[0-9]+', version): return None
    return int(version.split('.')[1])


def _scheme(identifier):
    return SCHEMES.get(identifier.split('/')[2]) if identifier.startswith('https://') else None


def validate_block(citation, folder=False):
    """Raise CitationError for the first problem of a citation block on its own (structure, then the rules the
    structure cannot say). FOLDER: the manifest carries a project folder, whose PROV is its lineage row."""
    try: MAPPER.structure(SCHEMA, citation, SCHEMA, '$.citation')
    except MAPPER.MapperError as error: raise CitationError('citation-schema', error.path) from None
    try: date.fromisoformat(citation['published'])
    except ValueError: raise CitationError('citation-schema', '$.citation.published') from None
    for i, creator in enumerate(citation['creators']):
        if 'identifier' in creator and _scheme(creator['identifier']) != ('ORCID' if creator['kind'] == 'person' else 'ROR'):
            raise CitationError('citation-schema', f'$.citation.creators[{i}].identifier')
    # One identifier, one node with one name (s1 X-4): a repeat with another name is refused at the later name.
    names = {}
    people = [(f'$.citation.creators[{i}]', c) for i, c in enumerate(citation['creators'])]
    for at, entity in people + [('$.citation.publisher', citation['publisher'])]:
        if 'identifier' not in entity: continue
        if names.setdefault(entity['identifier'], entity['name']) != entity['name']:
            raise CitationError('citation-schema', at + '.name')
    if folder and 'prov' in citation: raise CitationError('citation-schema', '$.citation.prov')
    if citation['licence'] is None and 'notice' not in citation: raise CitationError('citation-schema', '$.citation.notice')
    if citation['licence'] is not None and 'notice' in citation: raise CitationError('notice-without-null-licence', '$.citation.notice')
    seen = set()
    for i, name in enumerate(citation['descriptors']):
        if name in seen: raise CitationError('descriptor-repeated', f'$.citation.descriptors[{i}]')
        seen.add(name)
    return citation


def validate_citation(manifest):
    """Raise CitationError for the first problem of MANIFEST's citation: its bundle minor (2.15 or later), the block,
    and a media type on every asset file row. Returns the block."""
    minor = _minor(manifest)
    if manifest.get('schema') != BUNDLE_2 or minor is None or minor < MINOR: raise CitationError('citation-minor', '$.bundle_version')
    validate_block(manifest['citation'], folder='folder' in manifest)
    for i, asset in enumerate(manifest.get('assets') or []):
        for j, row in enumerate(asset.get('files') or []):
            if 'media_type' not in row: raise CitationError('citation-media-type', f'$.assets[{i}].files[{j}].media_type')
    return manifest['citation']


# ---- what is compared -----------------------------------------------------------------------------------------------

def inputs(manifest):
    """(citation, files, tables) of a validated manifest: files are the asset rows and the folder rows, in manifest
    order, as {path, sha256, bytes, media_type, role} (role: only documents() reads it); tables are a /2 folder's
    table-target items, each {id (the item's name), file, fields: [{name, dataType, extract: {column}}]} in its target's
    field order, then (from bundle 2.16, E147 s2b) the bundle's typed tables (bundle_tables)."""
    keys = ('path', 'sha256', 'bytes', 'media_type', 'role')
    files = [{k: row.get(k) for k in keys} for asset in manifest.get('assets') or [] for row in asset.get('files') or []]
    folder = manifest.get('folder')
    if isinstance(folder, dict): files += [{k: row.get(k) for k in keys} for row in folder.get('files') or []]
    tables = []
    if isinstance(folder, dict) and folder.get('schema') == FOLDER_2:
        for item in folder['items']:
            kind = FOLDER_KINDS.get(item['profile'], {})
            if 'target' not in kind: continue
            target = _read('targets', 'v1', kind['target'] + '.json')
            tables.append({'id': PurePosixPath(item['path']).stem, 'file': item['path'],
                           'fields': [{'name': f['name'], 'dataType': DATA_TYPES[f['kind']], 'extract': {'column': f['name']}}
                                      for f in target['fields']]})
    if (_minor(manifest) or 0) >= TABLES_MINOR: tables += bundle_tables(manifest.get('assets') or [])
    return manifest['citation'], files, tables


def bundle_tables(assets):
    """E147 s2b: the typed tables of bundle ASSETS (manifest asset entries), in asset order: an asset whose profile is a
    BUNDLE_TABLES key and whose normalized file is data.json (not the point-columns form) gives {id
    (`<asset folder>/<target>`), file (that data.json), fields: [{name, dataType, extract: {jsonPath}}]}. The writer
    asks this for its minor; inputs() adds it from bundle 2.16."""
    tables = []
    for asset in assets:
        entry = BUNDLE_TABLES.get(asset.get('profile'))
        data = next((row['path'] for row in asset.get('files') or [] if row.get('role') == 'normalized'), None)
        if entry is None or data is None or PurePosixPath(data).name != TABLE_DATA: continue
        target, paths = entry
        kinds = {f['name']: f['kind'] for f in _read('targets', 'v1', target + '.json')['fields']}
        tables.append({'id': f'{PurePosixPath(data).parent}/{target}', 'file': data,
                       'fields': [{'name': name, 'dataType': DATA_TYPES[kinds[name]], 'extract': {'jsonPath': path}}
                                  for name, path in paths]})
    return tables


def _ids(citation):
    return [c.get('identifier', f'#creator-{n}') for n, c in enumerate(citation['creators'], 1)]


def _publisher_id(citation):
    return citation['publisher'].get('identifier', '#publisher')


def _licence(citation):
    return SPDX + citation['licence']['spdx'] if citation['licence'] else MISSING


def _expected_ro_crate(c, files, tables, manifest=MANIFEST_NAME):
    out = []
    add = lambda path, subject, value: out.append((path, subject, value))
    meta, root = '$.@graph[@id=ro-crate-metadata.json]', '$.@graph[@id=./]'
    add('$.@context', 'context', RO_CRATE_CONTEXT)
    add(meta + '.conformsTo', 'context', RO_CRATE)
    add(meta + '.about', 'context', './')
    add(root + '.name', 'title', c['title'])
    add(root + '.description', 'description', c.get('description', MISSING))
    ids = _ids(c)
    add(root + '.author', 'creators', ids)
    for ident, creator in zip(ids, c['creators']):
        add(f'$.@graph[@id={ident}].@type', 'creators', KINDS[creator['kind']][0])
        add(f'$.@graph[@id={ident}].name', 'creators', creator['name'])
    publisher = _publisher_id(c)
    add(root + '.publisher', 'publisher', publisher)
    add(f'$.@graph[@id={publisher}].@type', 'publisher', 'Organization')
    add(f'$.@graph[@id={publisher}].name', 'publisher', c['publisher']['name'])
    add(root + '.datePublished', 'published', c['published'])
    add(root + '.version', 'version', c.get('version', MISSING))
    add(root + '.license', 'licence', _licence(c) if c['licence'] else NO_LICENCE)
    if not c['licence']:
        add(f'$.@graph[@id={NO_LICENCE}].@type', 'licence', 'CreativeWork')
        add(f'$.@graph[@id={NO_LICENCE}].name', 'licence', 'No open licence')
        add(f'$.@graph[@id={NO_LICENCE}].description', 'notice', c['notice'])
    add(root + '.conditionsOfAccess', 'notice', c.get('notice', MISSING))
    add(root + '.identifier', 'doi', MISSING)
    parts = [f['path'] for f in files] + [manifest] + ([PROV_PATH] if 'prov' in c else [])
    add(root + '.hasPart', 'files', sorted(parts))
    add(f'$.@graph[@id={manifest}].sha256', 'manifest', MISSING)
    add(f'$.@graph[@id={manifest}].encodingFormat', 'manifest', 'application/json')
    if 'prov' in c:
        node = f'$.@graph[@id={PROV_PATH}]'
        add(node + '.sha256', 'prov', c['prov']['sha256'])
        add(node + '.contentSize', 'prov', str(c['prov']['bytes']))
        add(node + '.encodingFormat', 'prov', 'application/json')
        add(node + '.conformsTo', 'prov', PROV_JSON)
    for f in files:
        node = f'$.@graph[@id={f["path"]}]'
        add(node + '.sha256', 'files', f['sha256'])
        add(node + '.contentSize', 'files', str(f['bytes']))
        add(node + '.encodingFormat', 'files', f['media_type'])
    return out


def _expected_croissant(c, files, tables, manifest=MANIFEST_NAME):
    out = []
    add = lambda path, subject, value: out.append((path, subject, value))
    add('$.@context', 'context', CROISSANT_CONTEXT)
    add('$.conformsTo', 'context', CROISSANT)
    add('$.@type', 'context', 'sc:Dataset')
    add('$.name', 'title', c['title'])
    add('$.description', 'description', c.get('description', MISSING))
    for i, (ident, creator) in enumerate(zip(_ids(c), c['creators'])):
        add(f'$.creator[{i}].@type', 'creators', KINDS[creator['kind']][0])
        add(f'$.creator[{i}].name', 'creators', creator['name'])
        add(f'$.creator[{i}].@id', 'creators', ident)
    add('$.publisher.@type', 'publisher', 'Organization')
    add('$.publisher.name', 'publisher', c['publisher']['name'])
    add('$.publisher.@id', 'publisher', _publisher_id(c))
    add('$.datePublished', 'published', c['published'])
    add('$.version', 'version', c.get('version', MISSING))
    add('$.license', 'licence', _licence(c))
    add('$.conditionsOfAccess', 'notice', c.get('notice', MISSING))
    add('$.identifier', 'doi', MISSING)
    add('$.citeAs', 'doi', MISSING)
    if manifest == EPISODES_NAME:
        rai = c['rai']
        add('$.rai:dataCollection', 'collection', rai['collection'])
        add('$.rai:personalSensitiveInformation', 'sensitive', rai['sensitive'])
        add('$.rai:dataUseCases', 'uses', rai['uses'])
        add('$.usageInfo', 'usage', rai['usage'] or MISSING)
    for f in files:
        node = f'$.distribution[@id={f["path"]}]'
        add(node + '.contentUrl', 'files', f['path'])
        add(node + '.sha256', 'files', f['sha256'])
        add(node + '.contentSize', 'files', f'{f["bytes"]} B')
        add(node + '.encodingFormat', 'files', f['media_type'])
    for table in tables:
        node = f'$.recordSet[@id={table["id"]}]'
        add(node + '.field', 'tables', [f'{table["id"]}/{f["name"]}' for f in table['fields']])
        for f in table['fields']:
            field = f'{node}.field[@id={table["id"]}/{f["name"]}]'
            add(field + '.name', 'tables', f['name'])
            add(field + '.dataType', 'tables', f['dataType'])
            add(field + '.source.fileObject', 'tables', table['file'])
            if 'jsonPath' in f['extract']:
                add(field + '.source.extract.jsonPath', 'tables', f['extract']['jsonPath'])
                add(field + '.source.extract.column', 'tables', MISSING)
            else: add(field + '.source.extract.column', 'tables', f['extract']['column'])
            if manifest == EPISODES_NAME:
                add(field + '.source.transform.jsonPath', 'tables', f.get('transform', {}).get('jsonPath', MISSING))
    return out


def _expected_datacite(c, files, tables):
    out = []
    add = lambda path, subject, value: out.append((path, subject, value))
    add('$.schemaVersion', 'context', DATACITE)
    add('$.types.resourceTypeGeneral', 'context', 'Dataset')
    add('$.titles[0].title', 'title', c['title'])
    add('$.descriptions[descriptionType=Abstract].description', 'description', c.get('description', MISSING))
    for i, creator in enumerate(c['creators']):
        identifier = creator.get('identifier')
        add(f'$.creators[{i}].name', 'creators', creator['name'])
        add(f'$.creators[{i}].nameType', 'creators', KINDS[creator['kind']][1])
        add(f'$.creators[{i}].nameIdentifiers[0].nameIdentifier', 'creators', identifier or MISSING)
        add(f'$.creators[{i}].nameIdentifiers[0].nameIdentifierScheme', 'creators', _scheme(identifier) if identifier else MISSING)
    add('$.publisher', 'publisher', c['publisher']['name'])
    add('$.publicationYear', 'published', c['published'][:4])
    add('$.dates[dateType=Issued].date', 'published', c['published'])
    add('$.version', 'version', c.get('version', MISSING))
    add('$.rightsList[*].rightsIdentifier', 'licence', [c['licence']['spdx']] if c['licence'] else MISSING)
    add('$.rightsList[*].rightsIdentifierScheme', 'licence', ['SPDX'] if c['licence'] else MISSING)
    add('$.descriptions[descriptionType=Other].description', 'notice', c.get('notice', MISSING))
    add('$.identifiers', 'doi', MISSING)
    add('$.sizes', 'files', [f'{sum(f["bytes"] for f in files)} bytes'])
    add('$.formats', 'files', sorted({f['media_type'] for f in files}))
    return out


# ---- the projections ------------------------------------------------------------------------------------------------

def _get(value, *keys):
    for key in keys:
        if not isinstance(value, dict) or key not in value: return MISSING
        value = value[key]
    return value


def _ref(value):
    """An @id reference's target ({"@id": x} -> x); any other value as it is."""
    return value['@id'] if isinstance(value, dict) and '@id' in value else value


def _list(value):
    if value is MISSING: return []
    return value if isinstance(value, list) else [value]


def _project_ro_crate(doc, tables=(), manifest=MANIFEST_NAME):
    out = []
    add = lambda path, subject, value: out.append((path, subject, value))
    graph = [n for n in _list(_get(doc, '@graph')) if isinstance(n, dict) and isinstance(n.get('@id'), str)]
    nodes = {}
    for node in graph: nodes.setdefault(node['@id'], node)
    meta, root = nodes.get(RO_CRATE_NAME, {}), nodes.get('./', {})
    m, r = '$.@graph[@id=ro-crate-metadata.json]', '$.@graph[@id=./]'
    add('$.@context', 'context', _get(doc, '@context'))
    add(m + '.conformsTo', 'context', _ref(_get(meta, 'conformsTo')))
    add(m + '.about', 'context', _ref(_get(meta, 'about')))
    add(r + '.name', 'title', _get(root, 'name'))
    add(r + '.description', 'description', _get(root, 'description'))
    authors = [_ref(a) for a in _list(_get(root, 'author'))]
    add(r + '.author', 'creators', authors if _get(root, 'author') is not MISSING else MISSING)
    for ident in authors:
        node = nodes.get(ident, {}) if isinstance(ident, str) else {}
        add(f'$.@graph[@id={ident}].@type', 'creators', _get(node, '@type'))
        add(f'$.@graph[@id={ident}].name', 'creators', _get(node, 'name'))
    publisher = _ref(_get(root, 'publisher'))
    add(r + '.publisher', 'publisher', publisher)
    if isinstance(publisher, str):
        add(f'$.@graph[@id={publisher}].@type', 'publisher', _get(nodes.get(publisher, {}), '@type'))
        add(f'$.@graph[@id={publisher}].name', 'publisher', _get(nodes.get(publisher, {}), 'name'))
    add(r + '.datePublished', 'published', _get(root, 'datePublished'))
    add(r + '.version', 'version', _get(root, 'version'))
    add(r + '.license', 'licence', _ref(_get(root, 'license')))
    if NO_LICENCE in nodes:
        add(f'$.@graph[@id={NO_LICENCE}].@type', 'licence', _get(nodes[NO_LICENCE], '@type'))
        add(f'$.@graph[@id={NO_LICENCE}].name', 'licence', _get(nodes[NO_LICENCE], 'name'))
        add(f'$.@graph[@id={NO_LICENCE}].description', 'notice', _get(nodes[NO_LICENCE], 'description'))
    add(r + '.conditionsOfAccess', 'notice', _get(root, 'conditionsOfAccess'))
    add(r + '.identifier', 'doi', _get(root, 'identifier'))
    parts = _get(root, 'hasPart')
    add(r + '.hasPart', 'files', MISSING if parts is MISSING else sorted(str(_ref(p)) for p in _list(parts)))
    for node in graph:
        if 'File' not in _list(_get(node, '@type')): continue
        at = f'$.@graph[@id={node["@id"]}]'
        if node['@id'] == manifest:
            add(at + '.sha256', 'manifest', _get(node, 'sha256'))
            add(at + '.encodingFormat', 'manifest', _get(node, 'encodingFormat'))
            continue
        subject = 'prov' if node['@id'] == PROV_PATH else 'files'
        add(at + '.sha256', subject, _get(node, 'sha256'))
        add(at + '.contentSize', subject, _get(node, 'contentSize'))
        add(at + '.encodingFormat', subject, _get(node, 'encodingFormat'))
        if subject == 'prov': add(at + '.conformsTo', 'prov', _ref(_get(node, 'conformsTo')))
    return out


def _project_croissant(doc, tables=(), manifest=MANIFEST_NAME):
    by_path = {t['id'] for t in tables if any('jsonPath' in f['extract'] for f in t['fields'])}
    episodes = manifest == EPISODES_NAME  # E160 s0: the responsible-AI places and every field's two JSON paths
    out = []
    add = lambda path, subject, value: out.append((path, subject, value))
    add('$.@context', 'context', _get(doc, '@context'))
    add('$.conformsTo', 'context', _ref(_get(doc, 'conformsTo')))
    add('$.@type', 'context', _get(doc, '@type'))
    add('$.name', 'title', _get(doc, 'name'))
    add('$.description', 'description', _get(doc, 'description'))
    for i, creator in enumerate(_list(_get(doc, 'creator'))):
        add(f'$.creator[{i}].@type', 'creators', _get(creator, '@type'))
        add(f'$.creator[{i}].name', 'creators', _get(creator, 'name'))
        add(f'$.creator[{i}].@id', 'creators', _get(creator, '@id'))
    publisher = _get(doc, 'publisher')
    add('$.publisher.@type', 'publisher', _get(publisher, '@type'))
    add('$.publisher.name', 'publisher', _get(publisher, 'name'))
    add('$.publisher.@id', 'publisher', _get(publisher, '@id'))
    add('$.datePublished', 'published', _get(doc, 'datePublished'))
    add('$.version', 'version', _get(doc, 'version'))
    add('$.license', 'licence', _ref(_get(doc, 'license')))
    add('$.conditionsOfAccess', 'notice', _get(doc, 'conditionsOfAccess'))
    add('$.identifier', 'doi', _get(doc, 'identifier'))
    add('$.citeAs', 'doi', _get(doc, 'citeAs'))
    if episodes:
        add('$.rai:dataCollection', 'collection', _get(doc, 'rai:dataCollection'))
        add('$.rai:personalSensitiveInformation', 'sensitive', _get(doc, 'rai:personalSensitiveInformation'))
        add('$.rai:dataUseCases', 'uses', _get(doc, 'rai:dataUseCases'))
        add('$.usageInfo', 'usage', _get(doc, 'usageInfo'))
    for entry in _list(_get(doc, 'distribution')):
        node = f'$.distribution[@id={_get(entry, "@id")}]'
        add(node + '.contentUrl', 'files', _get(entry, 'contentUrl'))
        add(node + '.sha256', 'files', _get(entry, 'sha256'))
        add(node + '.contentSize', 'files', _get(entry, 'contentSize'))
        add(node + '.encodingFormat', 'files', _get(entry, 'encodingFormat'))
    for record_set in _list(_get(doc, 'recordSet')):
        node = f'$.recordSet[@id={_get(record_set, "@id")}]'
        fields = _list(_get(record_set, 'field'))
        add(node + '.field', 'tables', [_get(f, '@id') for f in fields])
        for f in fields:
            field = f'{node}.field[@id={_get(f, "@id")}]'
            add(field + '.name', 'tables', _get(f, 'name'))
            add(field + '.dataType', 'tables', _ref(_get(f, 'dataType')))
            add(field + '.source.fileObject', 'tables', _ref(_get(f, 'source', 'fileObject')))
            if _get(record_set, '@id') in by_path or episodes:
                add(field + '.source.extract.jsonPath', 'tables', _get(f, 'source', 'extract', 'jsonPath'))
            add(field + '.source.extract.column', 'tables', _get(f, 'source', 'extract', 'column'))
            if episodes: add(field + '.source.transform.jsonPath', 'tables', _get(f, 'source', 'transform', 'jsonPath'))
    return out


def _typed(entries, key, value):
    return next((e for e in _list(entries) if isinstance(e, dict) and e.get(key) == value), {})


def _project_datacite(doc, tables=()):
    out = []
    add = lambda path, subject, value: out.append((path, subject, value))
    add('$.schemaVersion', 'context', _get(doc, 'schemaVersion'))
    add('$.types.resourceTypeGeneral', 'context', _get(doc, 'types', 'resourceTypeGeneral'))
    titles = _list(_get(doc, 'titles'))
    add('$.titles[0].title', 'title', _get(titles[0], 'title') if titles else MISSING)
    add('$.descriptions[descriptionType=Abstract].description', 'description',
        _get(_typed(_get(doc, 'descriptions'), 'descriptionType', 'Abstract'), 'description'))
    for i, creator in enumerate(_list(_get(doc, 'creators'))):
        identifiers = _list(_get(creator, 'nameIdentifiers'))
        add(f'$.creators[{i}].name', 'creators', _get(creator, 'name'))
        add(f'$.creators[{i}].nameType', 'creators', _get(creator, 'nameType'))
        add(f'$.creators[{i}].nameIdentifiers[0].nameIdentifier', 'creators',
            _get(identifiers[0], 'nameIdentifier') if identifiers else MISSING)
        add(f'$.creators[{i}].nameIdentifiers[0].nameIdentifierScheme', 'creators',
            _get(identifiers[0], 'nameIdentifierScheme') if identifiers else MISSING)
    add('$.publisher', 'publisher', _get(doc, 'publisher'))
    add('$.publicationYear', 'published', _get(doc, 'publicationYear'))
    add('$.dates[dateType=Issued].date', 'published', _get(_typed(_get(doc, 'dates'), 'dateType', 'Issued'), 'date'))
    add('$.version', 'version', _get(doc, 'version'))
    rights = _get(doc, 'rightsList')
    add('$.rightsList[*].rightsIdentifier', 'licence',
        MISSING if rights is MISSING else [r.get('rightsIdentifier') if isinstance(r, dict) else None for r in _list(rights)])
    add('$.rightsList[*].rightsIdentifierScheme', 'licence',
        MISSING if rights is MISSING else [r.get('rightsIdentifierScheme') if isinstance(r, dict) else None for r in _list(rights)])
    add('$.descriptions[descriptionType=Other].description', 'notice',
        _get(_typed(_get(doc, 'descriptions'), 'descriptionType', 'Other'), 'description'))
    add('$.identifiers', 'doi', _get(doc, 'identifiers'))
    add('$.sizes', 'files', _get(doc, 'sizes'))
    add('$.formats', 'files', _get(doc, 'formats'))
    return out


EXPECTED = {RO_CRATE_NAME: _expected_ro_crate, CROISSANT_NAME: _expected_croissant, DATACITE_NAME: _expected_datacite}
PROJECTIONS = {RO_CRATE_NAME: _project_ro_crate, CROISSANT_NAME: _project_croissant, DATACITE_NAME: _project_datacite}


def _crate(name, manifest):
    """The source file: the RO-Crate's metadata file (E147 s3: manifest.json, or starter.json for a starter pack); for
    Croissant, whether the responsible-AI places are compared (E160 s0: trajectories.json)."""
    return {'manifest': manifest} if name in (RO_CRATE_NAME, CROISSANT_NAME) else {}


def expected(name, citation, files, tables, manifest=MANIFEST_NAME):
    """{json path: value} the descriptor NAME must hold, from the citation, the files and the tables (inputs())."""
    return {path: value for path, _, value in EXPECTED[name](citation, files, tables, **_crate(name, manifest))}


def project(name, document, tables=(), manifest=MANIFEST_NAME):
    """{json path: value} of the places the mapping fixes in a parsed descriptor NAME (MISSING where absent); a
    Croissant field's jsonPath is a place only in the record sets a bundle table (inputs()) names, and in every record set of
    a work-episodes folder (MANIFEST trajectories.json), with its transform's jsonPath."""
    out = {}
    for path, _, value in PROJECTIONS[name](document, tables, **_crate(name, manifest)): out.setdefault(path, value)
    return out


def _disagreement(name, document, citation, files, tables, manifest=MANIFEST_NAME):
    want = EXPECTED[name](citation, files, tables, **_crate(name, manifest))
    have = {}
    for path, subject, value in PROJECTIONS[name](document, tables, **_crate(name, manifest)):
        have.setdefault(path, (subject, value))
    for path, subject, value in want:
        if have.get(path, (subject, MISSING))[1] != value:
            return DescriptorError('descriptor-disagrees', name, path, subject, source=manifest)
    known = {path for path, _, _ in want}
    for path, (subject, value) in have.items():
        if path not in known and value is not MISSING:
            return DescriptorError('descriptor-disagrees', name, path, subject, source=manifest)
    return None


def compare(name, document, citation, files, tables, manifest=MANIFEST_NAME):
    """The first place where descriptor NAME disagrees with the manifest (or starter.json), as (code, name, json path),
    or None. Places are taken in the expected order, then any place only the descriptor has (an extra file, creator or
    field)."""
    error = _disagreement(name, document, citation, files, tables, manifest)
    return None if error is None else (error.code, error.file, error.path)


def parse(name, raw):
    """A descriptor's bytes as a JSON object; anything else (not UTF-8, not JSON, NaN or Infinity, a number that
    overflows, not an object) is descriptor-unreadable."""
    def refuse(value): raise ValueError(value)

    def finite(text):
        number = float(text)
        if not math.isfinite(number): raise ValueError(text)
        return number
    try: document = json.loads(raw.decode('utf-8'), parse_constant=refuse, parse_float=finite)
    except (UnicodeDecodeError, ValueError): raise DescriptorError('descriptor-unreadable', name) from None
    if not isinstance(document, dict): raise DescriptorError('descriptor-unreadable', name)
    return document


def verify(manifest, raw):
    """Raise DescriptorError for the first problem of MANIFEST's citation and its descriptors. RAW maps each listed
    descriptor's name to its bytes, read by the caller under its guards (a listed descriptor the caller could not read
    is the caller's refusal, never passed here). Returns the citation."""
    validate_citation(manifest)
    citation, files, tables = inputs(manifest)
    for name in citation['descriptors']:
        error = _disagreement(name, parse(name, raw[name]), citation, files, tables)
        if error is not None: raise error
    return citation


# ---- writing (E147 s1) ----------------------------------------------------------------------------------------------

def _entities(c):
    """[(@id, schema.org type, name)]: the creators, then the publisher, one entry per identifier."""
    out, seen = [], set()
    entries = [(i, KINDS[x['kind']][0], x['name']) for i, x in zip(_ids(c), c['creators'])]
    for entry in entries + [(_publisher_id(c), 'Organization', c['publisher']['name'])]:
        if entry[0] not in seen: out.append(entry); seen.add(entry[0])
    return out


def _file_name(f):
    return 'Lineage (PROV-JSON)' if f.get('role') == 'lineage-prov' else PurePosixPath(f['path']).name


def _ro_crate(c, files, tables, manifest=MANIFEST_NAME):
    root = {'@id': './', '@type': 'Dataset', 'name': c['title']}
    if 'description' in c: root['description'] = c['description']
    root['datePublished'] = c['published']
    if 'version' in c: root['version'] = c['version']
    root['license'] = {'@id': _licence(c) if c['licence'] else NO_LICENCE}
    if 'notice' in c: root['conditionsOfAccess'] = c['notice']
    root['author'] = [{'@id': i} for i in _ids(c)]
    root['publisher'] = {'@id': _publisher_id(c)}
    parts = [f['path'] for f in files] + ([PROV_PATH] if 'prov' in c else []) + [manifest]
    root['hasPart'] = [{'@id': p} for p in parts]
    graph = [{'@id': RO_CRATE_NAME, '@type': 'CreativeWork', 'conformsTo': {'@id': RO_CRATE}, 'about': {'@id': './'}}, root]
    graph += [{'@id': i, '@type': kind, 'name': name} for i, kind, name in _entities(c)]
    if c['licence']:
        graph.append({'@id': _licence(c), '@type': 'CreativeWork', 'name': LICENCE_NAMES[c['licence']['spdx']]})
    else:
        graph.append({'@id': NO_LICENCE, '@type': 'CreativeWork', 'name': 'No open licence', 'description': c['notice']})
    graph.append({'@id': manifest, '@type': 'File', 'name': SOURCES[manifest][0], 'encodingFormat': 'application/json'})
    if 'prov' in c:
        graph.append({'@id': PROV_PATH, '@type': 'File', 'name': 'Provenance (PROV-JSON)', 'sha256': c['prov']['sha256'],
                      'contentSize': str(c['prov']['bytes']), 'encodingFormat': 'application/json',
                      'conformsTo': {'@id': PROV_JSON}})
    for f in files:
        node = {'@id': f['path'], '@type': 'File', 'name': _file_name(f), 'sha256': f['sha256'],
                'contentSize': str(f['bytes']), 'encodingFormat': f['media_type']}
        if f.get('role') == 'lineage-prov': node['conformsTo'] = {'@id': PROV_JSON}
        graph.append(node)
    return {'@context': RO_CRATE_CONTEXT, '@graph': graph}


def _croissant(c, files, tables):
    doc = {'@context': CROISSANT_CONTEXT, '@type': 'sc:Dataset', 'conformsTo': CROISSANT, 'name': c['title']}
    if 'description' in c: doc['description'] = c['description']
    doc['creator'] = [{'@type': KINDS[x['kind']][0], '@id': i, 'name': x['name']} for i, x in zip(_ids(c), c['creators'])]
    doc['publisher'] = {'@type': 'Organization', '@id': _publisher_id(c), 'name': c['publisher']['name']}
    doc['datePublished'] = c['published']
    if 'version' in c: doc['version'] = c['version']
    if c['licence']: doc['license'] = _licence(c)
    if 'notice' in c: doc['conditionsOfAccess'] = c['notice']
    if 'rai' in c:  # E160 s0: a work-episodes folder
        doc['rai:dataCollection'] = c['rai']['collection']
        doc['rai:personalSensitiveInformation'] = c['rai']['sensitive']
        doc['rai:dataUseCases'] = c['rai']['uses']
        if c['rai']['usage']: doc['usageInfo'] = c['rai']['usage']
    doc['distribution'] = [{'@type': 'cr:FileObject', '@id': f['path'], 'name': PurePosixPath(f['path']).name,
                            'contentUrl': f['path'], 'encodingFormat': f['media_type'], 'sha256': f['sha256'],
                            'contentSize': f'{f["bytes"]} B'} for f in files]
    if tables:
        doc['recordSet'] = [{'@type': 'cr:RecordSet', '@id': t['id'], 'name': t['id'],
                             **({'description': t['description']} if 'description' in t else {}), 'field': [
            {'@type': 'cr:Field', '@id': f'{t["id"]}/{f["name"]}', 'name': f['name'], 'dataType': f['dataType'],
             'source': {'fileObject': {'@id': t['file']}, 'extract': f['extract'],
                        **({'transform': f['transform']} if 'transform' in f else {})}} for f in t['fields']]}
            for t in tables]
    return doc


def _datacite(c, files, tables, resource_type):
    creators = []
    for x in c['creators']:
        creator = {'name': x['name'], 'nameType': KINDS[x['kind']][1]}
        if 'identifier' in x:
            scheme = _scheme(x['identifier'])
            creator['nameIdentifiers'] = [{'nameIdentifier': x['identifier'], 'nameIdentifierScheme': scheme,
                                           'schemeUri': SCHEME_URIS[scheme]}]
        creators.append(creator)
    doc = {'schemaVersion': DATACITE, 'types': {'resourceTypeGeneral': 'Dataset', 'resourceType': resource_type},
           'titles': [{'title': c['title']}], 'creators': creators, 'publisher': c['publisher']['name'],
           'publicationYear': c['published'][:4], 'dates': [{'date': c['published'], 'dateType': 'Issued'}]}
    if 'version' in c: doc['version'] = c['version']
    if c['licence']:
        spdx = c['licence']['spdx']
        doc['rightsList'] = [{'rights': LICENCE_NAMES[spdx], 'rightsUri': _licence(c), 'rightsIdentifier': spdx,
                              'rightsIdentifierScheme': 'SPDX', 'schemeUri': SPDX}]
    descriptions = [{'description': c[key], 'descriptionType': kind}
                    for key, kind in (('description', 'Abstract'), ('notice', 'Other')) if key in c]
    if descriptions: doc['descriptions'] = descriptions
    doc['sizes'] = [f'{sum(f["bytes"] for f in files)} bytes']
    doc['formats'] = sorted({f['media_type'] for f in files})
    return doc


def documents(citation, files, tables, resource_type, manifest=MANIFEST_NAME):
    """{name: document} for each descriptor CITATION lists, from the citation, the files and the tables (inputs()) and
    RESOURCE_TYPE (DataCite's words for the release: 'Project folder', 'Well log bundle', 'Starter pack'). Each holds
    what expected() fixes; the rest (names, order, licence labels) is this writer's, fixed by the valid fixtures.
    MANIFEST is the metadata file the RO-Crate names (starter.json for a pack). Serialize with serialize()."""
    write = {RO_CRATE_NAME: lambda: _ro_crate(citation, files, tables, manifest),
             CROISSANT_NAME: lambda: _croissant(citation, files, tables),
             DATACITE_NAME: lambda: _datacite(citation, files, tables, resource_type)}
    return {name: write[name]() for name in citation['descriptors']}


def serialize(document):
    """A written document's bytes: two-space JSON, UTF-8, one closing newline."""
    return (json.dumps(document, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


# E147 s2 D4: an export's licence from its files' own (a catalogue file's `acquisition.listed_in.licence`). The open rule
# is the Platform's rights_policy.open_licence (its OPEN_LICENCES are LICENCE_NAMES' keys; a test keeps them equal).
MIXED = "The files of this bundle are not under one open licence; each file's terms are in its descriptor."
UNSTATED = 'No open licence is recorded for every file of this bundle; ask the publisher before reusing it.'


def _open(licence):
    return (isinstance(licence, dict) and licence.get('spdx') in LICENCE_NAMES and licence.get('redistribution') == 'allowed'
            and licence.get('share_alike') is not True)


def export_licence(licences):
    """(licence, notice) of a citation from each file's licence, None where a file states none: ({'spdx': id}, None)
    when every file carries the same open licence (by its SPDX id, whatever its name), (None, MIXED) when every file
    carries one but not that, and (None, UNSTATED) when any file, or every file, carries none."""
    licences = list(licences)
    if not licences or any(not isinstance(x, dict) for x in licences): return None, UNSTATED
    if all(_open(x) for x in licences) and len({x['spdx'] for x in licences}) == 1: return {'spdx': licences[0]['spdx']}, None
    return None, MIXED


# ---- the starter pack (E147 s3) -------------------------------------------------------------------------------------

# Where a citation place comes from in starter.json, for the place a refusal names.
_STARTER_PLACES = {'$.citation.title': '$.title', '$.citation.description': '$.summary', '$.citation.published': '$.built_at'}


def starter_citation(starter, record):
    """The citation of a starter pack, derived (strategy E147 s3 §1): title, description (its summary), published (the
    date of built_at), one organisation creator (the catalogue RECORD's publisher, R-1), Open Subsurface Data as
    publisher, the pack licence's SPDX id when it is open (else a null licence and PACK_NOTICE), no DOI, the three
    descriptors. Raises StarterError (starter-record; citation-schema at the starter.json place)."""
    name = _get(record, 'publisher', 'name')
    if not isinstance(name, str) or not name: raise StarterError('starter-record', STARTER_EVIDENCE, '$.record.publisher.name')
    doc = starter if isinstance(starter, dict) else {}
    built = doc.get('built_at')
    licence = doc.get('licence')
    block = {'schema': CITATION, 'title': doc.get('title'), 'description': doc.get('summary'),
             'published': built[:10] if isinstance(built, str) else built,
             'creators': [{'name': name, 'kind': 'organisation'}], 'publisher': dict(STARTER_PUBLISHER),
             'licence': {'spdx': licence['spdx']} if _open(licence) else None}
    if block['licence'] is None: block['notice'] = PACK_NOTICE
    block.update(doi=None, descriptors=list(NAMES))
    try: validate_block(block)
    except CitationError as error:
        raise StarterError(error.code, STARTER_NAME, _STARTER_PLACES.get(error.path, error.path)) from None
    return block


def _media(path):
    return STARTER_MEDIA.get(PurePosixPath(path).suffix.lower(), STARTER_OTHER_MEDIA)


def starter_files(starter):
    """The files a starter pack's descriptors list: each artefact of every target once, in the order first listed, at
    its place in the pack folder (files/<path>), with its digest, size and media type (STARTER_MEDIA). An artefact that
    is not {path, sha256, bytes}, or a path listed again with another digest or size, is starter-artefact."""
    files, seen = [], {}
    targets = starter.get('targets') if isinstance(starter, dict) else None
    for i, target in enumerate(targets if isinstance(targets, list) else [None]):
        artefacts = target.get('artefacts') if isinstance(target, dict) else None
        if not isinstance(artefacts, list): raise StarterError('starter-artefact', STARTER_NAME, f'$.targets[{i}].artefacts')
        for j, a in enumerate(artefacts):
            at = f'$.targets[{i}].artefacts[{j}]'
            if not (isinstance(a, dict) and isinstance(a.get('path'), str) and isinstance(a.get('sha256'), str)
                    and isinstance(a.get('bytes'), int) and not isinstance(a.get('bytes'), bool)):
                raise StarterError('starter-artefact', STARTER_NAME, at)
            path = STARTER_FILES + a['path']
            if path in seen:
                if (seen[path]['sha256'], seen[path]['bytes']) != (a['sha256'], a['bytes']):
                    raise StarterError('starter-artefact', STARTER_NAME, at)
                continue
            seen[path] = {'path': path, 'sha256': a['sha256'], 'bytes': a['bytes'], 'media_type': _media(a['path']), 'role': None}
            files.append(seen[path])
    return files


def starter_inputs(starter, record):
    """(citation, files, tables) of a starter pack, as inputs() gives them for a manifest; a pack has no tables (E147
    s2c). STARTER is starter.json's document, RECORD the catalogue record its evidence.json holds."""
    return starter_citation(starter, record), starter_files(starter), []


def verify_starter(starter, record, raw):
    """Raise DescriptorError for the first problem of a starter pack's derived citation and its three descriptors. RAW
    maps each descriptor's name to its bytes, read by the caller under its guards. Returns the citation."""
    citation, files, tables = starter_inputs(starter, record)
    for name in citation['descriptors']:
        error = _disagreement(name, parse(name, raw[name]), citation, files, tables, STARTER_NAME)
        if error is not None: raise error
    return citation


def starter_documents(starter, record):
    """{name: document} of a starter pack's three descriptors (documents() with 'Starter pack' and starter.json)."""
    citation, files, tables = starter_inputs(starter, record)
    return documents(citation, files, tables, STARTER_RESOURCE, STARTER_NAME)


# ---- a folder of work episodes (E160 s0) ----------------------------------------------------------------------------

EPISODES_SCHEMA = _read('scientific', 'v1', 'work-episodes.json')
# The notice of a null licence: the values of the folder rely on several licences (each id named), or on none.
EPISODES_NOTICE = "The values in this folder rely on more than one licence ({}); each value's terms are in the record it links to."
EPISODES_UNLICENSED = 'This folder relies on no listed licence; ask the deployment that exported it before reusing it.'


def episodes_manifest(raw):
    """trajectories.json's bytes as a manifest a citation can be derived from: JSON of an object that passes the
    work-episodes schema (the mapper's reader; the model's own rules are the SDK's check), at 1.2.0 (with `tier` and
    `files`) and listing turns.jsonl. Anything else is episodes-manifest at its place (None: the file as a whole)."""
    try: manifest = parse(EPISODES_NAME, raw)
    except DescriptorError: raise EpisodesError('episodes-manifest', None) from None
    try: MAPPER.structure(EPISODES_SCHEMA, manifest, EPISODES_SCHEMA, '$')
    except MAPPER.MapperError as error: raise EpisodesError('episodes-manifest', error.path) from None
    for key in ('tier', 'files'):
        if key not in manifest: raise EpisodesError('episodes-manifest', f'$.{key}')
    if TURNS not in [f['name'] for f in manifest['files']]: raise EpisodesError('episodes-manifest', '$.files')
    return manifest


def episodes_citation(manifest):
    """The citation of a work-episodes folder, derived (strategy E160 s0 D3): its title and creator and publisher the
    deployment (an organisation, never a person), a sentence of purpose, mode and counts, the UTC date of exported_at,
    the release as version, the one licence the values rely on (else a null licence and a notice naming each), no DOI
    and croissant.json only."""
    deployment, counts = manifest['deployment_id'], manifest['counts']
    try: published = datetime.fromtimestamp(manifest['exported_at'], timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError): raise EpisodesError('episodes-manifest', '$.exported_at') from None
    ids = list(dict.fromkeys(x['spdx'] for x in manifest['licences']))
    block = {'schema': CITATION, 'title': f'Work episodes from {deployment}',
             'description': (f"Work episodes for {manifest['purpose']}, exported in {manifest['mode']} mode: "
                             f"{counts['episodes']} episodes, {counts['values']} with values and {counts['shape']} shape only."),
             'published': published, 'version': manifest['release'],
             'creators': [{'name': deployment, 'kind': 'organisation'}], 'publisher': {'name': deployment},
             'licence': {'spdx': ids[0]} if len(ids) == 1 else None}
    if block['licence'] is None: block['notice'] = EPISODES_NOTICE.format(', '.join(ids)) if ids else EPISODES_UNLICENSED
    block.update(doi=None, descriptors=[CROISSANT_NAME])
    # A manifest the schema passed always gives a valid block; kept so a later schema cannot hand out an invalid one.
    try: validate_block(block)
    except CitationError: raise EpisodesError('episodes-manifest', None) from None
    return block


def episodes_rai(manifest):
    """The four responsible-AI places of the Croissant: how the episodes were collected (consent, the tier, the release,
    the cursor), the manifest's linkage sentence, the purpose, and each rights basis as `<basis> v<version> sha256:<hex>`
    in manifest order."""
    return {'collection': (f"Captured by consent on a {manifest['tier']} deployment and exported by release "
                           f"{manifest['release']} up to cursor {manifest['until']}."),
            'sensitive': manifest['linkage'], 'uses': manifest['purpose'],
            'usage': [f"{b['basis']} v{b['version']} sha256:{b['sha256']}" for b in manifest['rights_bases']]}


def episodes_files(manifest, raw):
    """trajectories.json (the digest and size of RAW, its bytes), then each file it lists, in its order."""
    rows = [{'path': EPISODES_NAME, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
             'media_type': EPISODES_MEDIA['.json'], 'role': None}]
    return rows + [{'path': f['name'], 'sha256': f['sha256'], 'bytes': f['bytes'],
                    'media_type': EPISODES_MEDIA[PurePosixPath(f['name']).suffix], 'role': None} for f in manifest['files']]


def episodes_tables(manifest):
    """The one record set, `turns` over turns.jsonl: TURN_FIELDS, without the values-only field in a shape folder."""
    fields = []
    for name, data_type, values in TURN_FIELDS:
        if values and manifest['mode'] == 'shape': continue
        column, _, rest = name.partition('.')
        field = {'name': name, 'dataType': data_type, 'extract': {'column': column}}
        if rest: field['transform'] = {'jsonPath': '$.' + rest}
        fields.append(field)
    return [{'id': 'turns', 'file': TURNS, 'description': TURNS_DESCRIPTION, 'fields': fields}]


def episodes_inputs(raw):
    """(citation, files, tables) of a work-episodes folder from RAW, its trajectories.json bytes, as inputs() gives them for
    a bundle. The citation carries `rai` (episodes_rai) beside the block, which only the Croissant reads."""
    manifest = episodes_manifest(raw)
    citation = dict(episodes_citation(manifest), rai=episodes_rai(manifest))
    return citation, episodes_files(manifest, raw), episodes_tables(manifest)


def verify_episodes(manifest_raw, raw):
    """Raise DescriptorError for the first problem of a work-episodes folder's manifest (MANIFEST_RAW, its bytes) and its
    croissant.json (RAW maps the name to its bytes, read by the caller under its guards). Returns the derived citation."""
    citation, files, tables = episodes_inputs(manifest_raw)
    for name in citation['descriptors']:
        error = _disagreement(name, parse(name, raw[name]), citation, files, tables, EPISODES_NAME)
        if error is not None: raise error
    return {key: value for key, value in citation.items() if key != 'rai'}


def episodes_documents(manifest_raw):
    """{name: document} of a work-episodes folder's descriptor (documents() with 'Work episodes' and trajectories.json)."""
    citation, files, tables = episodes_inputs(manifest_raw)
    return documents(citation, files, tables, EPISODES_RESOURCE, EPISODES_NAME)
