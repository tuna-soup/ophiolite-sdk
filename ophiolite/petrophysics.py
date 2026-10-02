"""E52: shale volume from gamma ray, by the one table Ophiolite publishes (ophiolite.shale-volume-methods/1).

The constants are read from the packaged contract snapshot when this module is imported, so they cannot differ from
the table the server uses. The gamma-ray index is computed on halves, (g/2 - c/2) / (s/2 - c/2), then clipped to
[0, 1]: halving is exact, so ordinary values equal the plain form bit for bit, and the difference of two finite halves
cannot overflow. Percentiles are Hyndman and Fan type 7 over the half-open depth range [top, base). Missing samples
(None) stay missing; a zero stays zero. Importing this module contacts nothing.

    picks = picks_from_percentiles(depth, gr, top=2466.86, base=2620.22)
    vsh = shale_volume(gr, method='linear', clean=picks['clean'], shale=picks['shale'])
    method = shale_volume_method(method='linear', picks=picks, unit='gAPI')
    written = write_curves(depth, {'VSH': ('V/V', vsh)}, depth_unit='M', notes=[calculation_record('linear', picks, 'gAPI', 'M')])
"""
import hashlib
import json
import math
from importlib.resources import files

from .errors import ValidationFailed

_CONTRACTS = files('ophiolite').joinpath('contracts')
TABLE = json.loads(_CONTRACTS.joinpath('scientific/v1/shale-volume-methods.json').read_bytes())
# The digest a method record names: SHA-256 of the table's canonical JSON, as the server computes it.
TABLE_DIGEST = hashlib.sha256(json.dumps(TABLE, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
QUANTITIES = {q['name']: q for q in json.loads(_CONTRACTS.joinpath('vocabulary/v1/quantities.json').read_bytes())['quantities']}
CONSTANTS = {m['id']: dict(m['constants']) for m in TABLE['methods']}
LABELS = {m['id']: m['label'] for m in TABLE['methods']}
METHODS = tuple(CONSTANTS)
INPUT_UNITS = tuple(TABLE['input']['units'])
OUTPUT = TABLE['output']
MAX_SAMPLES = TABLE['max_samples']


def _number(value):
    """The server's spelling: a whole number without a fraction, else the shortest round-trip form."""
    value = float(value)
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def _method(method):
    if method not in CONSTANTS: raise ValidationFailed([f'{method} is not a shale-volume method; choose one of {", ".join(METHODS)}.'])
    return method


def _picks(clean, shale):
    try: clean, shale = float(clean), float(shale)
    except (TypeError, ValueError): raise ValidationFailed(['The clean and shale values must be numbers.']) from None
    if not (math.isfinite(clean) and math.isfinite(shale)): raise ValidationFailed(['The clean and shale values must be numbers.'])
    if not shale > clean: raise ValidationFailed(['The shale value must be higher than the clean value.'])
    return clean, shale


def gamma_ray_index(g, clean, shale):
    """0 at the clean value and 1 at the shale value, clipped to [0, 1]; None stays None."""
    if g is None: return None
    return min(1.0, max(0.0, (g / 2 - clean / 2) / (shale / 2 - clean / 2)))


def _fraction(method, x):
    c = CONSTANTS[method]
    if method == 'linear': return x
    if method in ('larionov-tertiary', 'larionov-older'): return c['a'] * (2 ** (c['b'] * x) - 1)
    if method == 'clavier': return c['a'] - math.sqrt(c['b'] - (x + c['c']) ** 2)
    if method == 'steiber': return x / (c['a'] - c['b'] * x)
    raise ValidationFailed([f'{method} is not a shale-volume method.'])


def shale_volume(values, *, method, clean, shale):
    """Shale volume per sample by one method of the table. Missing samples (None) stay missing."""
    _method(method); clean, shale = _picks(clean, shale)
    values = list(values)
    if len(values) > MAX_SAMPLES: raise ValidationFailed([f'This curve is larger than the calculation supports ({MAX_SAMPLES:,} samples).'])
    return [None if g is None else _fraction(method, gamma_ray_index(float(g), clean, shale)) for g in values]


def percentile(ordered, p):
    """Hyndman and Fan type 7 over values already sorted ascending."""
    h = (len(ordered) - 1) * p / 100
    low = math.floor(h)
    return ordered[low] + (h - low) * (ordered[min(low + 1, len(ordered) - 1)] - ordered[low])


def typed_picks(clean, shale):
    """Clean and shale values you type, in the curve's unit."""
    clean, shale = _picks(clean, shale)
    return {'how': 'typed', 'clean': clean, 'shale': shale}


def picks_from_percentiles(depth, values, top, base, low=5.0, high=95.0, *, depth_unit=''):
    """Clean and shale values from the low and high percentile of the non-missing samples in [top, base)."""
    try: top, base, low, high = float(top), float(base), float(low), float(high)
    except (TypeError, ValueError): raise ValidationFailed(['The depths and percentiles must be numbers.']) from None
    if not (math.isfinite(top) and math.isfinite(base)) or base <= top: raise ValidationFailed(['The base depth must be below the top depth.'])
    if not (0 <= low < high <= 100): raise ValidationFailed(['The low percentile must be below the high percentile, both between 0 and 100.'])
    depth, values = list(depth), list(values)
    if len(depth) != len(values): raise ValidationFailed(['Give one depth per value.'])
    ordered = sorted(float(g) for d, g in zip(depth, values) if g is not None and top <= d < base)
    if not ordered:
        where = f'{_number(top)} and {_number(base)}' + (f' {depth_unit}' if depth_unit else '')
        raise ValidationFailed([f'There are no gamma-ray samples between {where}. Choose a range inside the log.'])
    clean, shale = percentile(ordered, low), percentile(ordered, high)
    _picks(clean, shale)
    return {'how': 'percentile', 'clean': clean, 'shale': shale, 'top': top, 'base': base, 'low': low, 'high': high, 'samples': len(ordered)}


def calculation_record(method, picks, unit, depth_unit=''):
    """The sentence the calculated file carries in its ~Other section; the server writes the same bytes."""
    words = TABLE['record_sentence']
    common = {'label': LABELS[_method(method)], 'clean': _number(picks['clean']), 'shale': _number(picks['shale']), 'unit': unit, 'table': TABLE_DIGEST[:12]}
    if picks['how'] == 'typed': return words['typed'].format(**common)
    return words['percentile'].format(**common, low=_number(picks['low']), high=_number(picks['high']), top=_number(picks['top']),
                                      base=_number(picks['base']), depth_unit=depth_unit)


def shale_volume_method(*, method, picks, curve='GR', unit='gAPI', quantity='Gamma Ray', outputs=None, curves=None):
    """The method record to publish with the result: the keys, outputs and table digest the server records for the
    same calculation (library `ophiolite`). An unlisted quantity, or an output that is not a curve of the file
    (`curves`, by default the depth index DEPT and VSH), is refused here, before anything is published."""
    _method(method)
    if unit not in INPUT_UNITS:
        raise ValidationFailed(["This curve's unit is not stated as gAPI, so the clean and shale values cannot be read. Choose another curve, or upload a corrected copy of the file with the unit stated."])
    if quantity is None: raise ValidationFailed(['Confirm that this curve is a gamma ray.'])
    if quantity not in QUANTITIES: raise ValidationFailed([f'{quantity} is not a quantity Ophiolite lists.'])
    if quantity != TABLE['input']['quantity']: raise ValidationFailed(['Shale volume is calculated from a gamma-ray curve.'])
    if not isinstance(picks, dict) or picks.get('how') not in ('typed', 'percentile'):
        raise ValidationFailed(['Give picks from typed_picks or picks_from_percentiles.'])
    _picks(picks['clean'], picks['shale'])
    outputs = outputs if outputs is not None else {OUTPUT['curve']: {'unit': OUTPUT['unit'], 'quantity': OUTPUT['quantity']}}
    curves = set(curves) if curves is not None else {'DEPT', OUTPUT['curve']}
    for key, entry in outputs.items():
        if entry.get('quantity') not in QUANTITIES: raise ValidationFailed([f'{entry.get("quantity")} is not a quantity Ophiolite lists.'])
        if key not in curves: raise ValidationFailed([f'{key} is not a curve of the calculated file.'])
    recorded = {k: (float(v) if k in ('clean', 'shale', 'top', 'base', 'low', 'high') else v) for k, v in picks.items() if v is not None}
    parameters = {'method': method, 'picks': recorded, 'clip': [0, 1], 'table': TABLE_DIGEST,
                  'inputs': {curve: {'unit': unit, 'quantity': quantity, 'basis': 'confirmed'}},
                  'outputs': {k: dict(v) for k, v in outputs.items()}}
    return {'name': TABLE['method_record']['name'], 'declared': True, 'library': 'ophiolite', 'version': TABLE['id'], 'parameters': parameters}
