"""Fault sticks as OpendTect FaultStickSet ASCII (`x y z stick-index`, one point per line), written locally with
the same spelling the Connectors reader writes back, so a published file reads as the sticks you gave."""
import math
from .errors import ValidationFailed


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
