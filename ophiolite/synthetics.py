"""E53: wavelets, a wedge model and its synthetic seismic section, computed in plain Python.

    from ophiolite.synthetics import ricker, wedge, synthetic, tuning_thickness
    w = ricker(30, 0.001, duration=0.128)                 # 129 samples, peak 1 at t = 0
    model = wedge([{'name': 'Rodenrijs Claystone', 'vp': 4073, 'density': 2629},
                   {'name': 'Delft Sandstone', 'vp': 4024, 'density': 2379}])
    section = synthetic(model, w)                         # one reflectivity series per trace, convolved with w
    tuning_thickness(section).thickness                   # 0.013 s two-way time

The results are the SDK's own `Wavelet`, `ModelSection` and `SeismicSection`, so they write with `.write(...)`
(ophiolite.writers) and read the same way a published one does. Each carries `.method`, the record to publish it
with (`Client.publish_derived(..., method=result.method)`). Nothing is resampled, converted or padded: a
combination that would need it is refused with the sentence that says what to change. The formulas are the Science
reference's (`create_wavelet`, reflectivity and "same" convolution); numpy is not needed. Importing contacts nothing.
"""
import math
from typing import NamedTuple

from ._version import __version__
from .errors import ValidationFailed
from .typed import ModelSection, SeismicSection, Wavelet, WAVELET_DT, WAVELET_SAMPLES

POLARITIES = ('impedance-increase-positive', 'impedance-increase-negative', 'unknown')
MAX_CELLS = 1_000_000


def _refuse(sentence): raise ValidationFailed([sentence])


def _recorded(result, name, **parameters):
    result.method = {'name': name, 'declared': True, 'library': 'ophiolite', 'version': __version__, 'parameters': parameters}
    return result


def _finite(value, what):
    try: value = float(value)
    except (TypeError, ValueError): _refuse(f'{what} must be a number.')
    if not math.isfinite(value): _refuse(f'{what} must be finite.')
    return value


def _times(dt, samples, duration):
    """The odd sample count of a centred wavelet, from a count or a duration that is whole sample intervals."""
    dt = _finite(dt, 'The sample interval')
    if dt <= 0: _refuse('The sample interval must be positive.')
    if not WAVELET_DT[0] <= dt <= WAVELET_DT[1]: _refuse('A wavelet must be sampled every 0.0005 to 0.01 s.')
    if (samples is None) == (duration is None): _refuse('Give the number of samples or the duration, not both.')
    if duration is not None:
        steps = _finite(duration, 'The duration') / dt
        if abs(steps - round(steps)) > 1e-9: _refuse('The duration must be a whole number of sample intervals.')
        samples = round(steps) + 1
    if isinstance(samples, bool) or not isinstance(samples, int) or not WAVELET_SAMPLES[0] <= samples <= WAVELET_SAMPLES[1]:
        _refuse('A wavelet has 3 to 4095 samples.')
    if samples % 2 == 0: _refuse('A wavelet has an odd number of samples, so one sample is its centre.')
    return dt, samples


def _below_nyquist(frequency, dt):
    if frequency >= 0.5 / dt: _refuse(f'A frequency must be below the Nyquist frequency ({0.5 / dt:g} Hz at this interval).')


def _wavelet(kind, samples, dt, polarity, frequency=None, corners=None):
    if polarity not in POLARITIES: _refuse('Declare the polarity as impedance-increase-positive, impedance-increase-negative or unknown.')
    if polarity == 'impedance-increase-negative': samples = [-v for v in samples]
    n = len(samples)
    context = {'type': 'wavelet', 'kind': kind, 'frequency_hz': frequency, 'corners_hz': corners, 'dt': dt, 't0': -(n // 2) * dt,
               'time_unit': 's', 'polarity': polarity, 'sample_count': n, 'minimum': min(samples), 'maximum': max(samples)}
    return Wavelet(None, {'context': context, 'samples': samples}, None)


def ricker(frequency, dt, samples=None, *, duration=None, polarity='impedance-increase-positive'):
    """A zero-phase Ricker wavelet, (1 - 2x²)·exp(-x²) with x = π·f·t, centred, peak 1 (−1 for negative polarity).
    Give the odd sample count, or the duration in seconds (a whole number of intervals; one more sample than steps)."""
    dt, n = _times(dt, samples, duration)
    frequency = _finite(frequency, 'The frequency')
    if frequency <= 0: _refuse('The frequency must be positive.')
    _below_nyquist(frequency, dt)
    values = [(1 - 2 * x * x) * math.exp(-x * x) for x in (math.pi * frequency * (k - n // 2) * dt for k in range(n))]
    return _recorded(_wavelet('ricker', values, dt, polarity, frequency=frequency), 'ophiolite.ricker', frequency_hz=frequency, dt=dt, samples=n, polarity=polarity)


def _sinc(x): return 1.0 if x == 0 else math.sin(math.pi * x) / (math.pi * x)


def ormsby(corners, dt, samples=None, *, duration=None, polarity='impedance-increase-positive'):
    """A zero-phase Ormsby band-pass wavelet with corners f1 < f2 < f3 < f4 (Hz), centred and scaled to peak 1."""
    dt, n = _times(dt, samples, duration)
    if not isinstance(corners, (list, tuple)) or len(corners) != 4: _refuse('Give the Ormsby corners as four frequencies.')
    f1, f2, f3, f4 = corners = [_finite(f, 'A corner frequency') for f in corners]
    if not 0 <= f1 < f2 < f3 < f4: _refuse('The Ormsby corner frequencies must increase.')
    _below_nyquist(f4, dt)

    def raw(t):
        return (math.pi * f4 ** 2 / (f4 - f3) * _sinc(f4 * t) ** 2 - math.pi * f3 ** 2 / (f4 - f3) * _sinc(f3 * t) ** 2) \
            - (math.pi * f2 ** 2 / (f2 - f1) * _sinc(f2 * t) ** 2 - math.pi * f1 ** 2 / (f2 - f1) * _sinc(f1 * t) ** 2)
    peak = raw(0.0)
    result = _wavelet('ormsby', [raw((k - n // 2) * dt) / peak for k in range(n)], dt, polarity, corners=corners)
    return _recorded(result, 'ophiolite.ormsby', corners_hz=corners, dt=dt, samples=n, polarity=polarity)


def impedance(vp, density):
    """Acoustic impedance: P-wave velocity (m/s) times density (kg/m3)."""
    vp, density = _finite(vp, 'A P-wave velocity'), _finite(density, 'A density')
    if vp <= 0 or density <= 0: _refuse('The P-wave velocity and density must be positive.')
    return vp * density


def reflectivity(impedances):
    """Normal-incidence reflection coefficients down a trace: R[0] = 0, R[i] = (Z[i] - Z[i-1]) / (Z[i] + Z[i-1])."""
    z = [_finite(v, 'An impedance') for v in impedances]
    if any(v <= 0 for v in z): _refuse('An impedance must be positive.')
    return [0.0] + [(b - a) / (b + a) for a, b in zip(z, z[1:])]


def convolve(signal, kernel):
    """Convolution trimmed to the signal's length and centred on the kernel's centre sample (numpy's mode 'same')."""
    signal, kernel = list(signal), list(kernel)
    if not kernel: _refuse('The kernel needs at least one sample.')
    if len(kernel) > len(signal): _refuse('The kernel is longer than the signal; nothing is padded.')
    n, m, offset = len(signal), len(kernel), (len(kernel) - 1) // 2
    return [sum(kernel[j] * signal[i - j] for j in range(max(0, i - n + 1), min(m, i + 1))) for i in range(offset, offset + n)]


def _rock(rock, index):
    name = rock.get('name') if isinstance(rock, dict) else None
    if not isinstance(name, str) or not name.strip() or len(name) > 128 or any(c in name for c in '\r\n'):
        _refuse('Give every rock a name (up to 128 characters, one line).')
    impedance(rock.get('vp'), rock.get('density'))
    return {'index': index, 'name': ' '.join(name.split()), 'vp': float(rock['vp']), 'density': float(rock['density'])}


def wedge(rocks, *, samples=200, traces=61, sample_interval=0.001, top=80, horizontal_step=25.0):
    """A wedge model in two-way time: rock 1 everywhere except rock 2 on samples top .. top+i-1 of trace i, so trace i is
    i samples thick and trace 0 has none. `rocks` is [encasing, wedge], each {'name', 'vp' (m/s), 'density' (kg/m3)}."""
    if not isinstance(rocks, (list, tuple)) or len(rocks) != 2: _refuse('A wedge has two rocks: the encasing rock and the wedge.')
    listed = [_rock(rock, index) for index, rock in enumerate(rocks, 1)]
    interval = _finite(sample_interval, 'The sample interval'); step = _finite(horizontal_step, 'The horizontal step')
    if interval <= 0 or step <= 0: _refuse('The sample interval and the horizontal step must be positive.')
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (samples, traces, top)) or samples < 1 or traces < 1 or top < 0:
        _refuse('Give whole numbers of samples and traces and a top sample.')
    if samples * traces > MAX_CELLS: _refuse('A section holds at most 1,000,000 samples.')
    if top + traces - 1 > samples: _refuse('The wedge does not fit: the top sample plus the thickest trace is longer than the section.')
    grid = [[2 if top <= row < top + trace else 1 for trace in range(traces)] for row in range(samples)]
    context = {'type': 'model-section', 'domain': 'time', 'first_sample': 0.0, 'sample_interval': interval, 'sample_unit': 's',
               'samples': samples, 'traces': traces, 'horizontal': 'distance', 'horizontal_first': 0.0, 'horizontal_step': step,
               'horizontal_unit': 'm', 'rock_count': 2, 'velocity_unit': 'm/s', 'density_unit': 'kg/m3'}
    return _recorded(ModelSection(None, {'context': context, 'rocks': listed, 'grid': grid}, None), 'ophiolite.wedge',
                     rocks=listed, samples=samples, traces=traces, sample_interval=interval, top=top, horizontal_step=step)


def synthetic(model, wavelet):
    """The normal-incidence synthetic of a rock model in time: each trace's reflectivity convolved with the wavelet
    (same length, centred). Same sample interval, a centred odd wavelet, no longer than the model; polarity is the
    wavelet's. The result's origin is 'synthetic': publish it with its model and wavelet as parents."""
    c, w = model.context, wavelet.context
    if c['domain'] != 'time':
        _refuse('A model in depth cannot be combined with a wavelet in time; convert the model to time first (this function does not convert).')
    if c['sample_interval'] != w['dt']:
        _refuse(f"The model is sampled every {c['sample_interval']:g} s and the wavelet every {w['dt']:g} s; make them equal (nothing is resampled).")
    n = len(wavelet.samples)
    if n % 2 == 0 or abs(w['t0'] + (n // 2) * w['dt']) > 1e-12: _refuse("The wavelet's time zero must be its centre sample.")
    if n > c['samples']: _refuse("The wavelet is longer than the model's vertical axis.")
    z = {rock['index']: impedance(rock['vp'], rock['density']) for rock in model.rocks}
    columns = [convolve(reflectivity([z[row[trace]] for row in model.grid]), wavelet.samples) for trace in range(c['traces'])]
    grid = [[column[row] for column in columns] for row in range(c['samples'])]
    values = [v for row in grid for v in row]
    axes = {key: c[key] for key in ('domain', 'first_sample', 'sample_interval', 'sample_unit', 'samples', 'traces', 'horizontal',
                                    'horizontal_first', 'horizontal_step', 'horizontal_unit')}
    context = {'type': 'seismic-section', **axes, 'origin': 'synthetic', 'polarity': w['polarity'], 'minimum': min(values), 'maximum': max(values)}
    return _recorded(SeismicSection(None, {'context': context, 'grid': grid}, None), 'ophiolite.synthetic',
                     reflectivity='normal incidence, (Z[i] - Z[i-1]) / (Z[i] + Z[i-1])', convolution='same length, centred on the wavelet centre')


class Tuning(NamedTuple):
    trace: int          # the trace with the strongest absolute sample (the first, if two are equal)
    amplitude: float    # that sample's absolute value
    thickness: float    # trace × sample interval: the wedge's thickness there (trace i of `wedge` is i samples thick)


def tuning_thickness(section):
    """The trace whose largest absolute sample is the strongest, on a section from `synthetic(wedge(...), ...)`."""
    grid = section.grid
    peaks = [max(abs(row[trace]) for row in grid) for trace in range(len(grid[0]))]
    trace = peaks.index(max(peaks))
    return Tuning(trace, peaks[trace], trace * section.context['sample_interval'])
