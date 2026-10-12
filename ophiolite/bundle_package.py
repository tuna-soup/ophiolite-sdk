"""E23c: bundle 2.8 carries the source package a point set or a feature set was read from (bundle contract 2.8).

A recipe-read point set (Petrel, OpendTect) or a Shapefile-read feature set travels with its package file (the stored
package manifest row), one file per companion member (exact bytes, safe names: member names live in the entry's
`package` block) and its interpretation file (the stored row: recipe document, decisions with their evidence and the
execution). On open every link between these parts is checked, each with its own sentence. The checks prove the parts
agree with each other; they cannot prove the bundle is the original revision (a fully consistent rewrite is not
detectable without a digest from a trusted party). Offline; no transport or authentication code.
"""
import hashlib
import json

from .errors import Refused, VerificationFailed

MINOR = 8
TYPES = ('point-set', 'feature-set')
ROLES = ('package', 'companion', 'interpretation')
SOURCE_PACKAGE = 'ophiolite.source-package/1'
RECIPE_EXECUTION = 'ophiolite.recipe-execution/1'
PACKAGE_READ = 'ophiolite.package-read/1'
CARRIED = (RECIPE_EXECUTION, PACKAGE_READ)
NOT_CARRIED = ('This revision\'s interpretation is recorded as %s, which a bundle cannot carry yet; '
               'it can be exported once portable interpretations are supported.')
NO_ROWS = 'This revision was read from a source package; export it with Client.export, which reads the package and its decisions with it.'

# One sentence per link (D2, D4a); tests name the link by its sentence.
SHAPE = 'A package asset carries its package block, one package file and one interpretation file, and package files belong only to a package asset.'
UNKNOWN = 'The interpretation file is of a kind this reader does not know; it is never read as another kind.'
DUPLICATE = 'A package member is listed twice.'
PRIMARY = 'The package primary is not the bundle\'s original.'
MEMBER_FILE = 'A package member\'s file is not the one its record names.'
UNLISTED = 'A companion file is not a member of the package.'
DIGEST = 'The package digest does not match its members.'
DESCRIPTOR = 'The bundle\'s package block disagrees with the descriptor (%s).'
PACKAGE_ROW = 'The package file disagrees with the package block.'
RECIPE = 'The recipe in the interpretation file is not the one the descriptor pins.'
DECISIONS = 'The decisions in the interpretation file are not the ones the data carries.'
LISTING = 'The package or interpretation file is not the one the revision manifest lists.'


def canonical(value):
    """The Platform's canonical JSON for digests (sorted keys, `,` and `:`, ASCII escapes)."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest_of(members):
    """The package identity: sha256 over the canonical member records sorted by name (Connectors `source_package.build`)."""
    records = sorted(({'name': m['name'], 'role': m['role'], 'digest': m['sha256'], 'bytes': m['bytes']} for m in members), key=lambda r: r['name'])
    return sha(canonical(records).encode())


def rows_needed(descriptor):
    """The representation ids a package export reads besides the artifact and the data (C4)."""
    return ['package', 'interpretation'] + ['companion:' + m['name'] for m in descriptor['package']['members'] if m['role'] != 'primary']


def write_files(read, folder, put, original):
    """(files, block) for the package of a typed read; refuses what a bundle cannot carry before anything is written."""
    from .bundle import MAX_FILE_BYTES
    package = read._wire_descriptor['package']
    rows = getattr(read, 'package_rows', None)
    if not isinstance(rows, dict) or any(not isinstance(rows.get(i), (bytes, bytearray)) for i in rows_needed(read._wire_descriptor)): raise Refused(NO_ROWS)
    try: schema = json.loads(rows['interpretation']).get('schema')
    except (ValueError, AttributeError): schema = None
    if schema not in CARRIED: raise Refused(NOT_CARRIED % (schema if isinstance(schema, str) else 'an unreadable record')[:80])
    companions = [m for m in package['members'] if m['role'] != 'primary']
    for m in companions:
        size = len(rows['companion:' + m['name']])
        if size > MAX_FILE_BYTES:
            raise Refused('The package file %s is %d bytes; a bundle file holds at most %d bytes (32 MiB). Nothing was written.' % (m['name'][:80], size, MAX_FILE_BYTES))
    files, paths = [put(folder + 'package.json', bytes(rows['package']), 'package')], {}
    for k, m in enumerate(companions, 1):
        paths[m['name']] = folder + 'companion-%d.bin' % k
        files.append(put(paths[m['name']], bytes(rows['companion:' + m['name']]), 'companion'))
    files.append(put(folder + 'interpretation.json', bytes(rows['interpretation']), 'interpretation'))
    block = {'package_digest': package['package_digest'],
             'members': [{'name': m['name'], 'role': m['role'], 'sha256': m['sha256'], 'bytes': m['bytes'], 'file': original if m['role'] == 'primary' else paths[m['name']]}
                         for m in package['members']],
             'recipe': package['recipe'], 'interpretation': folder + 'interpretation.json'}
    return files, block


def _json(raw, what):
    from .bundle import _finite_json
    return _finite_json(raw, what)


def require(condition, sentence):
    if not condition: raise VerificationFailed(sentence)


class Package:
    """What a bundle carries about the package a revision was read from, checked on open: `digest`, `members` (name, role,
    sha256, bytes, file), `recipe` (the pin, None for a Shapefile), `companions` ({member name: exact bytes}),
    `interpretation` (the stored record) and `decisions` (as recorded)."""
    def __init__(self, block, companions, interpretation, row):
        self.digest, self.members, self.recipe = block['package_digest'], block['members'], block['recipe']
        self.companions, self.interpretation, self.row = companions, interpretation, row
        self.decisions = interpretation.get('decisions') or []

    def __repr__(self):
        return '<Package %d members, %s>' % (len(self.members), 'recipe' if self.recipe else 'no recipe')


def check(entry, files, raw_of, descriptor, data):
    """Verify a package asset of a bundle against itself, its descriptor and its data (verbatim /1 contract, D4a).
    `raw_of(path)` gives a listed file's checked bytes. Returns a Package, or None for an asset without one."""
    block, roles = entry.get('package'), [f.get('role') for f in files]
    if descriptor.get('package') is None and block is None and not set(roles) & set(ROLES): return None
    require(entry.get('type') in TYPES and isinstance(block, dict) and descriptor.get('package') is not None and roles.count('interpretation') == 1, SHAPE)
    _guard('shape', lambda: require(roles.count('package') == 1, SHAPE))
    by_path = {f['path']: f for f in files}
    interpretation_raw = raw_of(next(f['path'] for f in files if f['role'] == 'interpretation'))
    interpretation = _json(interpretation_raw, 'The interpretation file')
    require(isinstance(interpretation, dict) and interpretation.get('schema') in CARRIED and block.get('interpretation') == next(f['path'] for f in files if f['role'] == 'interpretation'), UNKNOWN)
    members = block.get('members')
    require(isinstance(members, list) and 0 < len(members) <= 8 and all(isinstance(m, dict) for m in members), SHAPE)
    _guard('duplicate', lambda: require(len({m.get('name') for m in members}) == len(members), DUPLICATE))
    original = next((f['path'] for f in files if f['role'] == 'original'), None)
    _guard('primary', lambda: require([m.get('file') for m in members if m.get('role') == 'primary'] == [original], PRIMARY))
    def member_files():
        for m in members:
            listed = by_path.get(m.get('file'))
            require(listed is not None and listed['role'] in ('original', 'companion') and (listed['sha256'], listed['bytes']) == (m.get('sha256'), m.get('bytes'))
                    and sha(raw_of(listed['path'])) == m.get('sha256'), MEMBER_FILE)
    _guard('member-files', member_files)
    _guard('unlisted', lambda: require({f['path'] for f in files if f['role'] == 'companion'} <= {m.get('file') for m in members}, UNLISTED))
    _guard('digest', lambda: require(digest_of(members) == block.get('package_digest'), DIGEST))
    recorded = descriptor['package']
    def against_descriptor():
        require(block.get('package_digest') == recorded['package_digest'], DESCRIPTOR % 'package digest')
        require([{k: m.get(k) for k in ('name', 'role', 'sha256', 'bytes')} for m in members] == recorded['members'], DESCRIPTOR % 'members')
        require(block.get('recipe') == recorded['recipe'], DESCRIPTOR % 'recipe')
    _guard('descriptor', against_descriptor)
    row_raw = raw_of(next(f['path'] for f in files if f['role'] == 'package')) if 'package' in roles else None
    row = _json(row_raw, 'The package file') if row_raw is not None else None
    def package_row():
        projected = sorted(({'name': m.get('name'), 'role': m.get('role'), 'digest': m.get('sha256'), 'bytes': m.get('bytes')} for m in members), key=lambda r: r['name'])
        require(row == {'schema': SOURCE_PACKAGE, 'members': projected, 'package_digest': block.get('package_digest')}, PACKAGE_ROW)
    if row_raw is not None: _guard('package-row', package_row)
    fidelity = (data.get('context') or {}).get('fidelity') or {}
    if interpretation['schema'] == RECIPE_EXECUTION:
        recipe = interpretation.get('recipe') or {}
        _guard('recipe', lambda: require(recorded['recipe'] is not None and isinstance(recipe.get('document'), dict)
                                         and sha(canonical(recipe['document']).encode()) == recipe.get('sha256') == recorded['recipe']['sha256']
                                         and recipe.get('reference') == recorded['recipe']['reference'], RECIPE))
        _guard('decisions', lambda: require(interpretation.get('decisions') == fidelity.get('decisions') and interpretation.get('execution') == fidelity.get('execution')
                                            and interpretation.get('package_digest') == recorded['package_digest'], DECISIONS))
    else:  # a Shapefile read without a recipe: no recipe check applies
        _guard('recipe', lambda: require(recorded['recipe'] is None and block.get('recipe') is None, RECIPE))
        _guard('decisions', lambda: require((interpretation.get('decisions') or []) == (fidelity.get('decisions') or []) and interpretation.get('interpretation') == data.get('interpretation')
                                            and interpretation.get('package_digest') == recorded['package_digest'], DECISIONS))
    if descriptor.get('manifest') is not None:  # the source revision listing (/1 only): the rows are the stored ones
        listed = {r['id']: (r['sha256'], r['bytes']) for r in descriptor['manifest'].get('representations', [])}
        _guard('listing', lambda: require(listed.get('package') == (sha(row_raw or b''), len(row_raw or b'')) and listed.get('interpretation') == (sha(interpretation_raw), len(interpretation_raw)), LISTING))
    companions = {m['name']: raw_of(m['file']) for m in members if m.get('role') != 'primary'}
    return Package(block, companions, interpretation, row)


def _guard(name, check):
    """One named link; tests replace this function to skip one guard and show a mutated bundle reaches it (the control)."""
    check()


# --- plain words for `ophiolite bundle show` (C4; D5) -----------------------------------------------------------------
# The default output is words a non-engineer reads: no checksum, asset id, recipe id or enum token. `--details` prints those.

KIND_WORDS = {'well-log': 'a well log', 'well-tops': 'well tops', 'trajectory': 'a well trajectory', 'regular-grid-surface': 'a grid surface',
              'triangulated-surface': 'a triangulated surface', 'point-set': 'a set of points', 'polyline-set': 'a set of lines (fault sticks)',
              'seismic-slice': 'seismic slices', 'wavelet': 'a wavelet', 'model-section': 'a model section', 'seismic-section': 'a seismic section',
              'time-depth': 'a time-depth relation', 'feature-set': 'map features'}
UNIT_WORDS = {'m': 'metres', 'ft': 'feet', 'ms': 'milliseconds', 's': 'seconds', 'us/ft': 'microseconds per foot'}
FIELD_WORDS = {'z_meaning': 'What Z measures', 'z_unit': 'The unit of Z', 'positive': 'Which way Z increases', 'crs': 'The coordinate system',
               'xy_unit': 'The unit of X and Y', 'vertical_datum': 'The height reference', 'encoding': 'The text encoding'}
MEMBER_WORDS = {'readme': 'the README', 'crs-metadata': 'the coordinate system file', 'primary': 'the file itself', 'companion': 'a companion file'}
NOT_CONFIRMED = 'The original revision cannot be independently confirmed.'
NEEDS_DECISION = 'Needs a decision'


def _unit(value):
    return UNIT_WORDS.get(value, value)


def _statement(field, value, decided):
    """One decided field as a sentence: 'Z is time in milliseconds'."""
    if field == 'z_meaning':
        unit = decided.get('z_unit')
        return 'Z is %s%s' % (value, ' in ' + _unit(unit) if unit else '')
    if field == 'z_unit': return 'Z is in ' + _unit(value)
    if field == 'positive': return 'Z increases %s' % {'up': 'upwards', 'down': 'downwards'}.get(value, value)
    if field == 'crs': return 'Coordinates are in ' + str(value)
    if field == 'xy_unit': return 'X and Y are in ' + _unit(value)
    if field == 'vertical_datum': return 'Heights are relative to ' + str(value)
    return '%s is %s' % (FIELD_WORDS.get(field, 'A setting'), value)


def _source(observations):
    member = next((o for o in observations if o.get('source') == 'member'), None)
    if member is not None:
        where = member.get('locator') or ''
        return 'read from %s of %s' % (where, MEMBER_WORDS.get(member.get('role'), 'a file in the package')) if where else 'read from ' + MEMBER_WORDS.get(member.get('role'), 'a file in the package')
    if any(o.get('source') == 'declared' for o in observations): return 'as declared at upload'
    return 'as the import recipe states'


def decision_lines(decisions):
    """Plain sentences for recorded decisions, in a fixed order; an unresolved field says 'Needs a decision'."""
    lines = [d if d.endswith('.') else d + '.' for d in decisions if isinstance(d, str)]  # a package read records its decisions as sentences (E56)
    decisions = [d for d in decisions if isinstance(d, dict)]
    decided = {d['field']: d['selected'] for d in decisions if d.get('status') == 'decided'}
    for d in sorted(decisions, key=lambda d: (list(FIELD_WORDS).index(d['field']) if d['field'] in FIELD_WORDS else 99, d['field'])):
        if d.get('status') != 'decided':
            lines.append('%s: %s.' % (FIELD_WORDS.get(d['field'], 'A setting'), NEEDS_DECISION)); continue
        if d['field'] == 'z_unit' and 'z_meaning' in decided: continue  # said with what Z measures
        lines.append('%s; %s.' % (_statement(d['field'], d['selected'], decided), _source(d.get('observations') or [])))
    return lines


def show_words(opened):
    """The default `bundle show` text for an opened bundle (D5): what it holds, in words."""
    count = len(opened.assets)
    lines = ['This bundle holds %d exact revision%s. Checksums show the files are intact, not who made them. %s' % (count, '' if count == 1 else 's', NOT_CONFIRMED)]
    for asset in opened.assets:
        kind = KIND_WORDS.get(asset.type, 'data')
        lines.append('')
        lines.append('%s: %s%s.' % (asset.name or 'An unnamed item', kind, ', %d curve%s' % (len(asset.curves), '' if len(asset.curves) == 1 else 's') if asset.curves else ''))
        package = getattr(asset, 'package', None)
        if package is None: continue
        others = sum(1 for m in package.members if m['role'] != 'primary')
        how = 'with an import recipe' if package.recipe is not None else 'by its format'
        lines.append('  Read from a file that comes with %d companion file%s, %s; the files travel in this bundle.' % (others, '' if others == 1 else 's', how))
        lines.extend('  ' + line for line in decision_lines(package.decisions))
    return '\n'.join(lines)
