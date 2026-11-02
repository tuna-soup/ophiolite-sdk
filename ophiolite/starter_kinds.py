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
    Kind('tops', 'well top', 'well tops', None, None, 'name'),
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
