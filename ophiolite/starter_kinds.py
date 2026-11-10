"""E137 s0 (strategy D-01): what each kind of a starter pack is, in one place.

One record per kind of an Open Subsurface Data record (record/5 `kinds`, the pinned OSD schema's enum): its key, its
words (`label` singular, for lines such as "not placed: seismic cube Syn"; `words` plural, for sentences), the
source profile its file lands as (None while no pack file of that kind is designed), the pack folder it is written
under and its identity (`name`: one object name; `dataset/line`: a 2D line inside its dataset, E137 D-04).

This module says what a kind is, never what a component can do with it: the SDK's read-back (`starter_archive.READERS`),
the connector's exporter (`ophiolite_opendtect.export.WRITERS`) and its import (`starter_import.PLACERS`) each keep their
own table and refuse, by these words, a kind their table does not hold. Standard library only, no I/O: the OpendTect
connector imports it in OpendTect's own Python.
"""
import re
from collections import namedtuple

Kind = namedtuple('Kind', 'key label words profile folder identity')

CATALOGUE = (
    Kind('wellbore-headers', 'well header', 'well headers', None, None, 'name'),
    Kind('wellbore-logs', 'log', 'logs', 'las2/1', 'wells', 'name'),
    Kind('wellbore-paths', 'well path', 'well paths', 'well-path-positions-csv/1', 'wells', 'name'),
    Kind('tops', 'well top', 'well tops', 'well-tops-csv/1', 'wells', 'name'),  # E137 s4 D-1
    Kind('core', 'core description', 'core descriptions', None, None, 'name'),
    Kind('time-depth', 'time-depth model', 'time-depth models', 'time-depth-csv/1', 'wells', 'name'),
    Kind('seismic-3d', 'seismic cube', 'seismic cubes', 'segy/1', 'seismic', 'name'),
    Kind('seismic-2d', '2D seismic line', '2D seismic lines', 'segy-line/1', 'seismic2d', 'dataset/line'),
    Kind('seismic-4d', '4D seismic survey', '4D seismic surveys', None, None, 'name'),
    Kind('horizons', 'horizon', 'horizons', 'points-csv/1', 'horizons', 'name'),
    Kind('surfaces', 'surface', 'surfaces', None, None, 'name'),
    Kind('faults', 'fault', 'faults', 'opendtect-faultsticks/1', 'faults', 'name'),
    Kind('reservoir-model', 'reservoir model', 'reservoir models', None, None, 'name'),
    Kind('production', 'production record', 'production records', None, None, 'name'),
    Kind('pressure', 'pressure record', 'pressure records', None, None, 'name'),
    Kind('geochemistry', 'geochemistry record', 'geochemistry records', None, None, 'name'),
    Kind('reports', 'report', 'reports', None, None, 'name'),
    Kind('source-list', 'source list', 'source lists', None, None, 'name'),
    Kind('potential-fields', 'potential-field survey', 'potential-field surveys', None, None, 'name'),
    Kind('velocity-model', 'velocity model', 'velocity models', None, None, 'name'),
    Kind('geological-model', 'geological model', 'geological models', None, None, 'name'),
    Kind('airborne-em', 'airborne electromagnetic survey', 'airborne electromagnetic surveys', None, None, 'name'),
    Kind('radiometrics', 'radiometric survey', 'radiometric surveys', None, None, 'name'),
    Kind('stress', 'stress record', 'stress records', None, None, 'name'),
)
BY_KEY = {k.key: k for k in CATALOGUE}

CANNOT_HOLD = 'A starter pack cannot hold %s yet: nothing wrote it.'  # E137 design 1; the caller adds its own ending
NOT_A_KIND = 'names %r, which is not a kind of an Open Subsurface Data record'
UNKNOWN_LABEL = 'object of a kind this version does not know'
LINE_FORM = 'The 2D line %r is not named as its dataset and its line, <dataset>/<line>; a starter pack cannot name it yet.'
LINE_SLASH = 'The 2D dataset or line name %r holds a /; a starter pack cannot name it yet.'
ONE_LINE_FILE = 'The 2D lines “%s” and “%s” would be written to one file name.'
NONE_STATED = 'none stated'  # E137 s6a D-2: the crs decision of a survey that states no coordinate system

# E137 s8 D-5': objects OpendTect lists but its Python (odbind) cannot read; a definition or an export that names one is
# refused with its sentence, before NOT_A_KIND. `horizons-2d` is not here: 2D horizons are named under `horizons`.
CANNOT_READ = "OpendTect's Python cannot read a survey's %s, so a starter pack cannot carry them."
REFUSED = {
    'picksets': "OpendTect's Python lists a survey's picksets but cannot read their points, so a starter pack cannot carry them.",
    'polygons': "OpendTect's Python lists a survey's polygons but cannot read their points, so a starter pack cannot carry them.",
    'random-lines': CANNOT_READ % 'random lines',
    'wavelets': CANNOT_READ % 'wavelets',
    'models': CANNOT_READ % 'earth models',
    'horizon-cubes': CANNOT_READ % 'horizon cubes',
    'bodies': CANNOT_READ % 'bodies',
}


def refused(key):
    """E137 s8: the sentence of an object OpendTect lists but a pack cannot carry, or None."""
    return REFUSED.get(key) if isinstance(key, str) else None


# E137 s8 D-2', D-3': every kind of an OpendTect survey archive and the pack's route for it. `status` is `written`
# (route: the pack kind), `refused` (route: the sentence), `waits` (route: the slice) or `not data` (route: why). The
# route only; READERS, EXPORT_PROFILE and WRITERS still say what an installation can run.
ArchiveKind = namedtuple('ArchiveKind', 'key words status route')
NOT_PART = 'not part of a starter pack: %s'
ARCHIVE = (
    ArchiveKind('seismic-3d', '3D seismic cubes', 'written', 'seismic-3d'),
    ArchiveKind('seismic-2d', '2D seismic lines', 'written', 'seismic-2d'),
    ArchiveKind('line-geometry', '2D line geometry', 'written', 'seismic-2d'),
    ArchiveKind('horizons-3d', '3D horizons', 'written', 'horizons'),
    ArchiveKind('horizons-2d', '2D horizons', 'written', 'horizons'),
    ArchiveKind('faults', 'faults and fault stick sets', 'written', 'faults'),
    ArchiveKind('wells', 'wells and their paths', 'written', 'wellbore-paths'),
    ArchiveKind('logs', 'well logs', 'written', 'wellbore-logs'),
    ArchiveKind('markers', 'well markers', 'written', 'tops'),
    ArchiveKind('checkshot-tables', 'checkshot tables a definition declares', 'written', 'time-depth'),
    ArchiveKind('picksets', 'picksets and polygons', 'refused', REFUSED['picksets']),
    ArchiveKind('random-lines', 'random lines', 'refused', REFUSED['random-lines']),
    ArchiveKind('wavelets', 'wavelets', 'refused', REFUSED['wavelets']),
    ArchiveKind('models', 'earth models and stratigraphy', 'refused', REFUSED['models']),
    ArchiveKind('horizon-cubes', 'horizon cubes', 'refused', REFUSED['horizon-cubes']),
    ArchiveKind('bodies', 'bodies', 'refused', REFUSED['bodies']),
    ArchiveKind('well-other', 'well files OpendTect does not document', 'refused', CANNOT_READ % 'other well files'),
    ArchiveKind('surface-data', 'horizon attributes and other surface data', 'refused', CANNOT_READ % 'horizon attributes'),
    ArchiveKind('attribute-sets', 'attribute sets', 'refused', CANNOT_READ % 'attribute sets'),
    ArchiveKind('processing', 'processing jobs', 'refused', CANNOT_READ % 'processing jobs'),
    ArchiveKind('survey-time-depth', "the survey's own time-depth models",
                'refused', "A starter pack's time-depth models come from the archive's checkshot tables, not from the survey's own."),
    ArchiveKind('survey-definition', "the survey's definition and bookkeeping", 'not data', NOT_PART % 'OpendTect keeps it for the survey'),
    ArchiveKind('object-parameters', "an object's parameters and notes", 'not data', NOT_PART % 'it travels with its object'),
    ArchiveKind('sessions', 'sessions, selections, displays and well ties', 'not data', NOT_PART % 'a view of the data, not data'),
    ArchiveKind('documents', 'documents and images', 'not data', NOT_PART % 'the archive ships it for people to read'),
    ArchiveKind('map-overlays', 'map overlays and shapefiles', 'not data', NOT_PART % 'the archive ships it for maps'),
    ArchiveKind('raw-sources', 'raw source files beside the survey',
                'not data', NOT_PART % 'a raw file is read only when a definition declares it'),
    ArchiveKind('hidden', 'other hidden files of the archive', 'not data', NOT_PART % 'not survey data'),
)
ARCHIVE_BY_KEY = {k.key: k for k in ARCHIVE}
UNRESOLVED = 'unresolved'
SURVEY_FILES = frozenset({'.survey', '.defs', '.omf', '.fileformats'})
_BOOKKEEPING = frozenset({'omf', 'bak'})
# (folder, extension) -> kind for a file directly in an OpendTect standard folder (Seismics `cbvs` by nesting, below)
_STANDARD = {
    ('Seismics', 'cbvs'): 'seismic-3d', ('Seismics', 'wvlt'): 'wavelets', ('Seismics', 'proc'): 'processing',
    ('Seismics', 'par'): 'object-parameters', ('Seismics', 'note'): 'object-parameters', ('Seismics', 'sgydef'): 'object-parameters',
    ('Geometry', 'geom'): 'line-geometry',
    ('Surfaces', 'hor'): 'horizons-3d', ('Surfaces', '2dh'): 'horizons-2d', ('Surfaces', 'fss'): 'faults', ('Surfaces', 'flt'): 'faults',
    ('Surfaces', 'hci'): 'horizon-cubes', ('Surfaces', 'hcs'): 'horizon-cubes', ('Surfaces', 'body'): 'bodies',
    ('Surfaces', 'hov'): 'surface-data', ('Surfaces', 'sti'): 'surface-data', ('Surfaces', 'ts'): 'surface-data',
    ('Surfaces', 'txt'): 'surface-data', ('Surfaces', 'par'): 'object-parameters',
    ('WellInfo', 'well'): 'wells', ('WellInfo', 'wll'): 'logs', ('WellInfo', 'wlm'): 'markers',
    ('WellInfo', 'wlt'): 'survey-time-depth', ('WellInfo', 'csmdl'): 'survey-time-depth',
    ('WellInfo', 'tie'): 'sessions', ('WellInfo', 'disp'): 'sessions', ('WellInfo', 'pwell'): 'well-other',
    ('WellInfo', 'note'): 'object-parameters',
    ('Locations', 'pck'): 'picksets', ('Locations', 'rdl'): 'random-lines', ('Locations', 'note'): 'object-parameters',
    ('Attribs', 'attr'): 'attribute-sets',
    ('Models', 'sgd'): 'models', ('Models', 'sfw'): 'models', ('Models', 'stratlevels'): 'models',
    ('Proc', 'odcmd'): 'processing', ('Proc', 'par'): 'processing', ('Proc', 'txt'): 'processing',
    ('Misc', 'objsel'): 'sessions', ('Misc', 'sess'): 'sessions', ('Misc', 'par'): 'sessions', ('Misc', 'jpg'): 'documents',
}
_NESTED = {('Seismics', 'cbvs'): 'seismic-2d', ('Surfaces', '3dhc'): 'horizon-cubes', ('Surfaces', 'ai'): 'surface-data',
           ('Surfaces', 'bak'): 'survey-definition'}
STANDARD_FOLDERS = frozenset({f for f, _ in _STANDARD} | {'Features', 'GMT', 'Madagascar', 'NLAs', 'SITFAL'})
_DOCUMENTS = frozenset({'pdf', 'docx', 'xlsx', 'jpg', 'png', 'bmp', 'ico'})
_OVERLAYS = frozenset({'kml', 'geojson', 'shp', 'shx', 'dbf', 'prj'})
_RAW = frozenset({'txt', 'dat', 'las', 'sgy', 'segy', 'deviation', 'zip', 'disp', 'ini', 'log'})


def _ext(name):
    return name.rsplit('.', 1)[1].lower() if '.' in name.lstrip('.') else ''


def archive_kind(member, declared=()):
    """E137 s8 D-6: the ARCHIVE key of MEMBER, a file path `<survey>/...` of an OpendTect survey archive, or UNRESOLVED
    when its path alone does not establish one. A raw text table is `checkshot-tables` only when DECLARED names it."""
    parts = member.split('/')[1:]
    if not parts or not parts[-1]: return UNRESOLVED
    name, ext = parts[-1], _ext(parts[-1])
    if len(parts) == 1:
        if name in SURVEY_FILES or ext in _BOOKKEEPING: return 'survey-definition'
        if name.startswith('.'): return 'hidden'
    elif parts[0] in STANDARD_FOLDERS:
        if len(parts) == 2:
            if ext in _BOOKKEEPING or name in SURVEY_FILES: return 'survey-definition'
            return _STANDARD.get((parts[0], ext), UNRESOLVED)
        return _NESTED.get((parts[0], ext), UNRESOLVED) if len(parts) == 3 else UNRESOLVED
    if member in declared: return 'checkshot-tables'
    if ext in _DOCUMENTS: return 'documents'
    if ext in _OVERLAYS: return 'map-overlays'
    if ext in _RAW: return 'raw-sources'
    return UNRESOLVED


def known(key):
    """True when KEY is a kind of the catalogue (a str of the 24)."""
    return isinstance(key, str) and key in BY_KEY


def cannot_hold(key):
    """The by-name refusal of a catalogue kind a component has no writer or reader for."""
    return CANNOT_HOLD % BY_KEY[key].words


def label(key):
    """The singular words of KEY; never the key itself."""
    return BY_KEY[key].label if known(key) else UNKNOWN_LABEL


def depth(key):
    """E137 s0 D-04: the segments of a pack path of KEY: `<folder>/<name>`, or `<folder>/<dataset>/<line>` for a 2D line."""
    return 3 if BY_KEY[key].identity == 'dataset/line' else 2


H2D_FOLDER = 'horizons2d'  # E137 s6b D-1': `horizons2d/<horizon>/<line>.csv`, one points-csv/1 file per line of a 2D horizon


def pack_path(key, form=None):
    """E137 s6b D-3: (segments, first folder) of a pack path of KEY; a 2D horizon's line (`form` '2d') is
    `horizons2d/<horizon>/<line>.csv`, every other file as `depth` and its kind's folder say."""
    if key == 'horizons' and form == '2d': return 3, H2D_FOLDER
    return depth(key), BY_KEY[key].folder


def stem(name):
    """A file stem of NAME, as `ophiolite_opendtect.export.file_name` makes it: every character other than a letter,
    digit, '.', '_' or '-' as '_', no leading dot."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', name).lstrip('.') or '_'


def line_paths(ids):
    """E137 s0 D-04 (R1-15, R2-8): {id: `seismic2d/<dataset stem>/<line stem>.sgy`} of 2D line IDS, each
    `<dataset>/<line>`; raises ValueError with the sentence when an id is not of that form or when two datasets, or two
    lines of one dataset, map to one stem (compared lowercased)."""
    out, datasets, lines = {}, {}, {}
    for oid in ids:
        parts = oid.split('/')
        if len(parts) > 2: raise ValueError(LINE_SLASH % oid)
        if len(parts) != 2 or not all(parts): raise ValueError(LINE_FORM % oid)
        dataset, line = (stem(p) for p in parts)
        first = datasets.setdefault(dataset.lower(), (parts[0], oid))
        if first[0] != parts[0]: raise ValueError(ONE_LINE_FILE % (first[1], oid))
        twin = lines.setdefault((dataset.lower(), line.lower()), oid)
        if twin != oid: raise ValueError(ONE_LINE_FILE % (twin, oid))
        out[oid] = '%s/%s/%s.sgy' % (BY_KEY['seismic-2d'].folder, dataset, line)
    return out
