"""E119a slice 1: a well set, your own private list of wellbores under their wells, each with the exact trajectory
version and the frame that places it in the world.

A set is an uploaded, versioned document (`well-set/1`) that stays with its author: it is saved with no audience, a
new version is the next version of the same set, and the server refuses every sharing route. The server checks each
member (the well and wellbore are yours to read and associated, the trajectory is a deviation survey of that wellbore
that you may use, the frame's CRS is projected in metres) and names the member it refuses.

`from_list` builds a set from wellbores. Where a wellbore has two or more trajectory versions it refuses until you
name one by its label: the refusal lists each version by its readable label, or "Trajectory version of <date>",
never by an identifier. Two versions under one label are named by the version itself, a mapping of exactly
`asset_id` and `revision` (D-10).

`bind` (slice 2) prepares one member for computing: the server checks it again exactly as at saving (the set's
inspection, nothing stored), its trajectory is read at the saved version, and the one trajectory geometry
(`ophiolite.geometry.place`) places it against a surface, or the refusal names the member and one defect (north,
datum, coordinate system, units or tie-in) in a sentence.
"""
import json
import re
import uuid

from . import geometry
from .errors import Refused

PROFILE = 'well-set/1'
SCHEMA = 'ophiolite.well-set/1'
TRAJECTORY = 'deviation-csv/1'
UNNAMED_WELLBORE = 'Unnamed wellbore'
EXACT = ('asset_id', 'revision')  # a trajectory version named by itself in `from_list`'s choose (D-10)


def _readable(text):
    from .procedures import contract
    return contract().labels.readable_label(text) if isinstance(text, str) else None


def version_label(item):
    """How a trajectory version is named to a person: its readable name, else the date it was associated."""
    readable = _readable(item.get('name'))
    if readable: return readable
    at = ((item.get('association') or {}).get('asserted_at') or '')[:10]
    return 'Trajectory version of %s' % at if at else 'Trajectory version'


def wellbore_label(entity):
    return _readable(getattr(entity, 'name', None)) or UNNAMED_WELLBORE


def _id(value, key):
    if isinstance(value, str): return value
    if isinstance(value, dict): return value[key]
    return getattr(value, key)


def _revision(value):
    if value is None: return None
    return {'asset_id': _id(value, 'asset_id'), 'revision': _id(value, 'revision')}


def member(well, wellbore, trajectory=None, frame=None):
    """One member: a well and its wellbore (Entity or id), and optionally an exact trajectory revision with its frame."""
    return {'well': _id(well, 'entity_id'), 'wellbore': _id(wellbore, 'entity_id'), 'trajectory': _revision(trajectory),
            'frame': dict(frame) if frame is not None else None}


def document(label, members):
    """The `well-set/1` document as it is uploaded."""
    if not isinstance(label, str) or not label.strip(): raise Refused('Name the well set.')
    members = [dict(m) for m in members]
    if not members: raise Refused('A well set has at least one wellbore.')
    return {'schema': SCHEMA, 'label': label, 'members': members}


def encode(doc):
    return (json.dumps(doc, indent=2, allow_nan=False, ensure_ascii=False) + '\n').encode('utf-8')


def _target(well_set):
    if isinstance(well_set, dict): return well_set['asset_id'], well_set['revision']
    return well_set.asset_id, well_set.revision


class WellSets:
    """`client.well_sets`: save, version, list and read your well sets."""

    def __init__(self, client):
        self.client = client

    def save(self, label, members, *, attribution, rights_confirmed, name=None, command_id=None):
        """Save a new set (private to you); returns the upload receipt (asset id and exact revision)."""
        return self._upload(document(label, members), name or label, attribution, rights_confirmed, command_id)

    def new_version(self, well_set, label, members, *, attribution, rights_confirmed, name=None, command_id=None):
        """Save the next version of `well_set` (a receipt, or {asset_id, revision} of its current version)."""
        asset, revision = _target(well_set)
        return self._upload(document(label, members), name or label, attribution, rights_confirmed, command_id,
                            append_to=asset, expected_parent=revision)

    def _upload(self, doc, name, attribution, rights_confirmed, command_id, **version):
        return self.client.upload_data(encode(doc), profile=PROFILE, name=name, attribution=attribution, audience=[],
                                       rights_confirmed=rights_confirmed, filename='well-set.json',
                                       command_id=command_id or uuid.uuid4().hex, **version)

    def list(self):
        """Your well sets in the catalogue, each at its current version."""
        return [item for item in self.client.assets() if item.get('profile') == PROFILE]

    def read(self, asset, revision):
        """A set at an exact version, read as a typed pair (`WellSet`)."""
        return self.client.read_data(asset, revision)

    def from_list(self, label, wellbores, *, frames=None, choose=None):
        """Build a set document from wellbores (Entity or id). Each wellbore's well is the one it is part of. A wellbore
        with one trajectory version takes it; with none, the member has no trajectory; with two or more, `choose`
        must name one by its label ({wellbore id: label}), or by the version itself ({wellbore id: {'asset_id': ...,
        'revision': ...}}, exactly those two keys) where two versions share a label. `frames` gives each chosen trajectory's frame
        ({wellbore id: frame}). Returns the document; pass its label and members to `save` or `new_version`."""
        frames, choose = dict(frames or {}), dict(choose or {})
        members, open_choices = [], []
        for wanted in wellbores:
            bore = self.client.entity(wanted)
            if bore.kind != 'wellbore': raise Refused('%s is not a wellbore.' % (_readable(bore.name) or 'This entity'))
            well = bore.well()
            if well is None: raise Refused('%s is not part of a well you can read.' % wellbore_label(bore))
            found, seen = [], set()
            for item in self.client.data(bore, profile=TRAJECTORY):
                key = (item['asset_id'], item['revision'])
                if key not in seen: seen.add(key); found.append(item)
            before = len(open_choices)
            chosen = self._choose(bore, found, choose.get(bore.entity_id), open_choices)
            if len(open_choices) > before: continue
            frame = frames.get(bore.entity_id)
            if chosen is not None and frame is None:
                raise Refused('%s has a trajectory but no frame; the frame says where it starts and how it is oriented.' % wellbore_label(bore))
            members.append(member(well, bore, chosen, frame if chosen is not None else None))
        if open_choices:  # a label names no version where each open choice is between versions under one label
            by_label = ' Name one version by its label in choose.' if any(helps for _, helps in open_choices) else ''
            raise Refused(' '.join(text for text, _ in open_choices) + by_label)
        return document(label, members)

    def bind(self, well_set, member, surface):
        """Check MEMBER of WELL_SET (a `WellSet` read with `read`, or its document) again and place its trajectory against
        SURFACE (a surface read with `client.read_data`, or its context). Returns a `Bound`; refuses with one sentence naming
        the member and the defect, `details` {'reason', 'field'}: the server's "well-set:<key>" (withdrawn, rights, reuse,
        unreadable or removed well or wellbore, association ended), or "geometry:<key>" for what the geometry cannot place
        (coordinate system, datum, north, units, time, tie-in). MEMBER is its position from 0 or its wellbore."""
        label, members = _members(well_set)
        i = _index(members, member)
        chosen = members[i]
        if chosen['trajectory'] is None:
            raise _refused(i, 'It has no trajectory, so there is nothing to place.', 'no-trajectory')
        try:  # D2 (run), E111 s4a D-A2: the same member checks as at saving (the server inspects a one-member document); nothing is stored; people and agents alike
            self.client._post('las-uploads', 'check-member', {'label': label, 'member': chosen})
        except Refused as error:
            reason = (error.details or {}).get('reason')
            if isinstance(reason, str) and reason.startswith('well-set:'): raise _refused(i, error.message, reason) from None
            raise
        trajectory = self.client.read_data(chosen['trajectory']['asset_id'], chosen['trajectory']['revision'])
        context = surface.context if hasattr(surface, 'context') else surface
        placed = geometry.place(_survey(trajectory), chosen['frame'], context)
        if placed['reason'] == 'datum_mismatch':  # adhoc-e121-declarations (B4): both values and the one to declare
            sentence, datum = geometry.datum_mismatch(_survey(trajectory), chosen['frame'], context)
            refused = _refused(i, sentence, 'geometry:datum_mismatch')
            refused.details.update(datum)
            raise refused
        if placed['reason'] is not None:
            raise _refused(i, geometry.refusals()[placed['reason']], 'geometry:' + placed['reason'])
        return Bound(i, chosen, trajectory, context, placed)

    @staticmethod
    def _choose(bore, found, wanted, open_choices):
        if not found: return None
        if len(found) == 1 and wanted is None: return found[0]
        found = sorted(found, key=lambda i: (version_label(i), (i.get('association') or {}).get('asserted_at') or ''))  # listed in a stable order
        labels = [version_label(i) for i in found]
        unique = any(labels.count(text) == 1 for text in labels)  # some version a label still names
        if isinstance(wanted, dict):  # D-10: the version itself, never told back (the sentence names no identifier)
            if set(wanted) != set(EXACT):
                raise Refused('%s: choose names a trajectory version by its label, or by a mapping of exactly asset_id and revision.' % wellbore_label(bore))
            matches = [i for i in found if (i['asset_id'], i['revision']) == (wanted['asset_id'], wanted['revision'])]
            if matches: return matches[0]
            open_choices.append(('%s has no trajectory version you can read matching the one named.' % wellbore_label(bore), unique))
            return None
        if wanted is not None:
            matches = [i for i, text in zip(found, labels) if text == wanted]
            if len(matches) == 1: return matches[0]
        listed = ', '.join('"%s"' % text for text in labels)
        exact = ' Name one by passing the version itself in choose.' if len(set(labels)) < len(labels) else ''
        if wanted is not None and wanted in labels:
            open_choices.append(('%s has more than one trajectory version named "%s" (%s).%s' % (wellbore_label(bore), wanted, listed, exact), False))
        elif wanted is not None:
            open_choices.append(('%s has no trajectory version named "%s"; its versions are %s.%s' % (wellbore_label(bore), wanted, listed, exact), unique))
        else:
            open_choices.append(('%s has %d trajectory versions: %s.%s' % (wellbore_label(bore), len(found), listed, exact), unique))
        return None


class Bound:
    """A member checked and placed (`WellSets.bind`): `stations` [(md, x, y, z)] in the frame's coordinate system, z
    the depth below the frame's datum (positive down); `positions(mds)` places measured depths on the arc; a surface
    value times `surface_sign` is a depth below the same datum."""

    def __init__(self, index, member, trajectory, surface, placed):
        self.index, self.member, self.trajectory, self.surface = index, member, trajectory, surface
        self.frame = member['frame']
        self.stations, self.surface_sign = placed['stations'], placed['surface_sign']

    def positions(self, mds):
        """[(x, y, z) | None] for each measured depth (None outside the survey)."""
        return geometry.place(_survey(self.trajectory), self.frame, self.surface, list(mds))['positions']

    def __repr__(self):
        return '<Bound member %d: %d stations>' % (self.index + 1, len(self.stations))


def _survey(trajectory):
    return {'context': trajectory.context, 'stations': trajectory.stations}


def _members(well_set):
    if isinstance(well_set, dict): return well_set['label'], well_set['members']
    return well_set.label, well_set.members


def _index(members, member):
    if isinstance(member, int) and not isinstance(member, bool):
        if 0 <= member < len(members): return member
        raise Refused('The set has %d members; choose one by its position from 0 or by its wellbore.' % len(members))
    wanted = _id(member, 'entity_id')
    found = [i for i, m in enumerate(members) if m['wellbore'] == wanted]
    if not found: raise Refused('That wellbore is not a member of this set.')
    return found[0]


_LEAD = re.compile(r'^Member [0-9]+: ')


def _refused(index, sentence, reason):
    return Refused('Member %d: %s' % (index + 1, _LEAD.sub('', sentence)), details={'reason': reason, 'field': 'members[%d]' % index})
