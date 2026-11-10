"""E144 s1 C2: the las2/1 evaluators. Carried into the SDK byte for byte, standard library only.

The neutral input (strategy §2): {'null': float or None, 'index': Column, 'curves': [{'mnemonic', 'unit', 'values':
Column}]}, a Column a float64 sequence with NaN for a missing sample, `mnemonic` the name as the file states it (a
repeated name stays repeated) and `unit` as written. Rows are 1-based data rows. Each rule's description is the
behaviour, word for word.
"""
from .engine import Failures

SENTINELS = (-999.25, -999.0, -9999.0)


def _missing(value, null):
    return value != value or null is not None and value == null


def _gamma_ray(quantities):
    return next(q for q in quantities['quantities'] if q['name'] == 'Gamma Ray')


def gr_range(data, parameters, quantities):
    gamma = _gamma_ray(quantities)  # a suggesting mnemonic in one of the quantity's units (GAPI is a unit, not a suggestion: 3 Nov)
    curves = [c['values'] for c in data['curves'] if c['mnemonic'].upper() in gamma['suggest_from']['mnemonics'] and c['unit'] in gamma['units']]
    if not curves: return 'no-column'
    low, high, null, index, found = parameters['minimum'], parameters['maximum'], data['null'], data['index'], Failures()
    for i in range(len(index)):
        for values in curves:
            value = values[i]
            if not _missing(value, null) and not low <= value <= high:
                found.add(i + 1, index[i], value)
                break
    return found


def depth_increasing(data, parameters, quantities):
    index, null, found = data['index'], data['null'], Failures()
    first = next((v for v in index if not _missing(v, null)), None)
    last = next((index[i] for i in range(len(index) - 1, -1, -1) if not _missing(index[i], null)), None)
    direction = -1 if first is not None and last < first else 1
    previous = None
    for i in range(len(index)):
        value = index[i]
        if _missing(value, null):
            found.add(i + 1, None, None)
            continue
        if previous is not None and (value - previous) * direction <= 0:
            found.add(i + 1, value, value)
        previous = value
    return found


def null_sentinel(data, parameters, quantities):
    index, null, found = data['index'], data['null'], Failures()
    curves = [c['values'] for c in data['curves']]
    for i in range(len(index)):
        for values in curves:
            value = values[i]
            if value in SENTINELS and value != null:
                found.add(i + 1, index[i], value)
                break
    return found


def unit_known(data, parameters, quantities):
    found = Failures()
    for at, curve in enumerate(data['curves'], start=2):  # the index is ~Curve position 1
        mnemonic = curve['mnemonic'].upper()
        for quantity in quantities['quantities']:
            suggest = quantity.get('suggest_from')
            if suggest and mnemonic in suggest['mnemonics']:
                if curve['unit'] not in quantity['units']: found.add(at, None, curve['mnemonic'])
                break
    return found


EVALUATORS = {'gr-range/1': gr_range, 'depth-increasing/1': depth_increasing, 'null-sentinel/1': null_sentinel,
              'unit-known/1': unit_known}
