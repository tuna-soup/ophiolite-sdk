"""E23b D7 (SDK mirror of the Workspace words): what a person reads for a recipe field and its value. Printed objects
use these words and never a raw field key or enum token; the raw particulars stay in `details()`."""

FIELDS = {'crs': 'Coordinate system', 'xy_unit': 'Horizontal unit', 'z_unit': 'Vertical unit', 'z_meaning': 'Values',
          'positive': 'Positive direction', 'vertical_datum': 'Vertical datum'}
VALUES = {'z_meaning': {'depth': 'depth', 'elevation': 'elevation', 'time': 'time', 'unknown': 'not stated'},
          'positive': {'up': 'up', 'down': 'down', 'unknown': 'not stated'}}


def field_label(field):
    return FIELDS[field]


def value_label(field, value):
    """A unit, CRS or datum is printed as stated; an enum value by its word."""
    if value is None: return 'not stated'
    return VALUES[field][value] if field in VALUES else str(value)
