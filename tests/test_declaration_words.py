"""adhoc-e121-declarations (E121 B4): a residual run's member whose survey or surface datum is not the frame's is
refused with both values and the one to declare, never with the bare `datum_mismatch` sentence. The contract still
compares the texts trimmed and case-folded (the register's pair "Rotary Table, 6.7 m above NAP" / "Rotary Table" is
refused; "  kb " / "KB" is placed).

Mutations (Validation Record): `bind` without the datum branch -> the generic sentence and no `declared`/`frame` in
`details` -> red; `datum_mismatch` comparing the surface pair first -> the survey case names the surface -> red."""
import pytest

from ophiolite import geometry
from test_geometry_bind import B2, SET, SURFACE, SURVEY, Surface, client, refused

REGISTER = 'Rotary Table, 6.7 m above NAP'  # E121 B4, stuck log section 4
FRAME = dict(SET['members'][1]['frame'], depth_reference={'name': 'Rotary Table', 'elevation': 6.7, 'datum': 'NAP'})
MEMBERS = dict(SET, members=[SET['members'][0], dict(SET['members'][1], frame=FRAME)])


def test_the_register_pair_names_both_values_and_the_one_to_declare():
    c, _ = client(survey=dict(SURVEY, depth_datum=REGISTER))
    text, details = refused(lambda: c.well_sets.bind(MEMBERS, B2, Surface(SURFACE)))
    assert text == ('Member 2: The survey declares its depth datum as "Rotary Table, 6.7 m above NAP", but the frame names its '
                    'depth reference "Rotary Table"; the two are compared as written. Declare the survey\'s depth datum as '
                    '"Rotary Table", or give a frame whose depth reference is "Rotary Table, 6.7 m above NAP".')
    assert details == {'reason': 'geometry:datum_mismatch', 'field': 'members[1]', 'datum': 'depth_datum',
                       'declared': 'Rotary Table, 6.7 m above NAP', 'frame': 'Rotary Table'}


def test_a_surface_datum_unlike_the_frame_names_the_surface():
    c, _ = client(survey=dict(SURVEY, depth_datum='Rotary Table'))
    text, details = refused(lambda: c.well_sets.bind(MEMBERS, B2, Surface(dict(SURFACE, vertical_datum='MSL'))))
    assert text == ('Member 2: The surface declares its vertical datum as "MSL", but the frame\'s datum is "NAP"; the two are '
                    'compared as written. Declare the surface\'s vertical datum as "NAP", or give a frame whose datum is "MSL".')
    assert (details['datum'], details['declared'], details['frame']) == ('vertical_datum', 'MSL', 'NAP')


def test_the_comparison_itself_is_unchanged():
    c, _ = client(survey=dict(SURVEY, depth_datum='  rotary table '))
    assert c.well_sets.bind(MEMBERS, B2, Surface(SURFACE)).positions([0.0])[0] is not None  # trimmed, case-folded: placed
    assert geometry.datum_mismatch({'context': {'depth_datum': 'ROTARY TABLE'}}, FRAME, SURFACE) is None


@pytest.mark.parametrize('survey, surface, key', [(REGISTER, 'NAP', 'depth_datum'), ('Rotary Table', 'MSL', 'vertical_datum'),
                                                  (REGISTER, 'MSL', 'depth_datum')])
def test_the_first_pair_place_compares_is_the_one_named(survey, surface, key):
    found = geometry.datum_mismatch({'context': {'depth_datum': survey}}, FRAME, dict(SURFACE, vertical_datum=surface))
    assert found[1]['datum'] == key
