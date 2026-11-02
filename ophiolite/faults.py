"""Fault sticks as OpendTect FaultStickSet ASCII (`x y z stick-index`, one point per line), written locally with
the same spelling the Connectors reader writes back, so a published file reads as the sticks you gave.

E137 s2 C3 (F1): `read` is the Connectors reader's rule (`asset_connectors.faults.read`), its caps and its sentences:
sticks in the order they first appear, each stick's points in file order, the stick indices as written; every stick
of two points or more, every coordinate finite, at most 200,000 points and 20,000 sticks."""
import math
from .errors import ValidationFailed

MAX_POINTS, MAX_STICKS = 200_000, 20_000
BANNER = '# OpendTect FaultStickSet\n'  # E137 s2 A-1: line 1 of an exported fault file, Intake's marker (`asset_connectors.detect`)


def read(text):
    sticks, order = {}, []
    count = 0
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('!'): continue
        parts = stripped.replace(',', ' ').split()
        if len(parts) not in (4, 5): raise ValidationFailed(['Line %d: expected x y z stick-index [node-index].' % number])
        try:
            x, y, z = (float(v) for v in parts[:3]); index = int(parts[3])
        except ValueError: raise ValidationFailed(['Line %d: coordinates must be numbers and the stick index a whole number.' % number]) from None
        if not all(math.isfinite(v) for v in (x, y, z)): raise ValidationFailed(['Line %d: coordinates must be finite.' % number])
        if index not in sticks: sticks[index] = []; order.append(index)
        sticks[index].append({'x': x, 'y': y, 'z': z}); count += 1
        if count > MAX_POINTS or len(sticks) > MAX_STICKS: raise ValidationFailed(['The file holds too many points or sticks.'])
    if not sticks: raise ValidationFailed(['The file holds no fault-stick points.'])
    if any(len(points) < 2 for points in sticks.values()): raise ValidationFailed(['Every stick needs at least two points.'])
    return [{'index': i, 'points': sticks[i]} for i in order]


def write(sticks):
    lines = []
    sticks = list(sticks)
    if not sticks: raise ValidationFailed(['Write at least one fault stick.'])
    for stick in sticks:
        index, points = stick.get('index'), list(stick.get('points') or [])
        if not isinstance(index, int) or isinstance(index, bool): raise ValidationFailed(['Each stick needs a whole-number index.'])
        if len(points) < 2: raise ValidationFailed([f'Stick {index} needs at least two points.'])
        for p in points:
            x, y, z = (p['x'], p['y'], p['z']) if isinstance(p, dict) else p
            if any(v is None for v in (x, y, z)): raise ValidationFailed([f'Stick {index} has a point with a missing coordinate; fault sticks cannot hold one.'])
            if not all(math.isfinite(float(v)) for v in (x, y, z)): raise ValidationFailed([f'Stick {index} has a coordinate that is not finite.'])
            lines.append('%s %s %s %d' % (repr(float(x)), repr(float(y)), repr(float(z)), index))
    return '\n'.join(lines) + '\n'
