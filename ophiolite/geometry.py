"""E119a: the one trajectory geometry, `ophiolite/contracts/geometry/v1/trajectory.py` (ophiolite.trajectory-geometry/1),
byte-identical to the Platform's through the contract snapshot (SOURCE.json). It is loaded from its source text, as
the procedure validator is, so no bytecode is written into the package, and it imports nothing but `math`.

`minimum_curvature` and `interpolate` are what `Trajectory.minimum_curvature()` and `transform.vertical_depth` compute
with; `place` puts a well set member's trajectory in its surface's world (x, y in the frame's coordinate system, z the
depth below the frame's datum) or names the defect with a key of `REFUSALS`; `offset_bound` is the largest distance
between a segment's arc and its chord. `client.well_sets.bind` checks a member and places it. Nothing here contacts a
server."""
import types
from pathlib import Path

CONTRACT = Path(__file__).resolve().parent / 'contracts' / 'geometry' / 'v1' / 'trajectory.py'
_contract = None


def contract():
    """The packaged geometry module (loaded once, from source text)."""
    global _contract
    if _contract is None:
        module = types.ModuleType('ophiolite_trajectory_geometry')
        module.__file__ = str(CONTRACT)
        exec(compile(CONTRACT.read_text(encoding='utf-8'), str(CONTRACT), 'exec'), module.__dict__)
        _contract = module
    return _contract


def minimum_curvature(stations):
    """[(east, north, tvd)]: each station's offsets from the first, by minimum curvature (angles in degrees)."""
    return contract().minimum_curvature(stations)


def interpolate(stations, mds, limit=True):
    """[(east, north, tvd) | None]: each measured depth placed on the survey's own arc, from its first station; None
    outside the survey. With `limit` a segment turning more than 179.9 degrees is refused (`Unreadable`)."""
    return contract().interpolate(stations, mds, limit=limit)


def place(trajectory, frame, surface, mds=()):
    """A trajectory's normalized data ({'context', 'stations'}) placed by a well set member's frame against a surface's
    context: {'reason': None, 'stations', 'positions', 'surface_sign'} or {'reason': <a key of REFUSALS>}."""
    return contract().place(trajectory, frame, surface, mds)


def offset_bound(dogleg, length):
    """The largest distance in metres between a segment's arc (LENGTH metres, turning DOGLEG degrees) and its chord."""
    return contract().offset_bound(dogleg, length)


def refusals():
    """{key: sentence} for every defect `place` names."""
    return dict(contract().REFUSALS)


# adhoc-e121-declarations (E121 B4): `datum_mismatch` with both values and the one to declare. The contract compares the
# texts trimmed and case-folded, never by their parts, so "Rotary Table, 6.7 m above NAP" is not "Rotary Table".
DATUM_WORDS = {
    'depth_datum': 'The survey declares its depth datum as "{declared}", but the frame names its depth reference "{frame}"; '
                   'the two are compared as written. Declare the survey\'s depth datum as "{frame}", or give a frame '
                   'whose depth reference is "{declared}".',
    'vertical_datum': 'The surface declares its vertical datum as "{declared}", but the frame\'s datum is "{frame}"; the two '
                      'are compared as written. Declare the surface\'s vertical datum as "{frame}", or give a frame whose '
                      'datum is "{declared}".',
}


def datum_mismatch(trajectory, frame, surface):
    """For `datum_mismatch`: (sentence, details {'datum', 'declared', 'frame'}) of the first pair `place` compares that
    differs (the survey's `depth_datum` with the frame's depth reference name, then the surface's `vertical_datum` with
    the frame's datum), or None when both agree."""
    fold, reference = contract()._datum, frame['depth_reference']
    pairs = [('depth_datum', trajectory['context'].get('depth_datum'), reference['name']),
             ('vertical_datum', surface.get('vertical_datum'), reference['datum'])]
    for field, declared, given in pairs:
        if fold(declared) != fold(given):
            declared, given = (declared or '').strip(), (given or '').strip()
            return DATUM_WORDS[field].format(declared=declared, frame=given), {'datum': field, 'declared': declared, 'frame': given}
    return None
