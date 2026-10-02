"""E53: wavelets, rock model sections and seismic sections read sample-exact, with offline invariants
that mirror the server and a spectrum bounded to at most 1001 bins of 1 Hz (D7)."""
import copy
import hashlib
import json
import math
from importlib.resources import files
import pytest
from ophiolite import _core, typed
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.typed import Wavelet, ModelSection, SeismicSection

FIX = files('ophiolite').joinpath('contracts/assets/v1/fixtures')


def load(name):
    return json.loads(FIX.joinpath(f'{name}.json').read_bytes()), FIX.joinpath(f'{name}-data.json').read_bytes(), FIX.joinpath(f'{name}.original').read_bytes()


def rehash(descriptor, body):
    rep = next(r for r in descriptor['representations'] if r['kind'] == 'normalized'); rep['bytes'], rep['sha256'] = len(body), hashlib.sha256(body).hexdigest()


def test_served_payloads_read_to_the_literals():
    wavelet = _core.typed_result(*load('wavelet'))
    assert isinstance(wavelet, Wavelet) and wavelet.samples == [-0.25, 0.5, 1.0, 0.5, -0.25] and wavelet.to_numpy().tolist() == wavelet.samples
    assert wavelet.times == pytest.approx([-0.004, -0.002, 0.0, 0.002, 0.004]) and wavelet.original == load('wavelet')[2]
    assert repr(wavelet) == '<Wavelet ricker 30 Hz, 5 samples every 0.002 s>'
    model = _core.typed_result(*load('model-section'))
    assert isinstance(model, ModelSection) and model.grid == [[1, 1], [1, 2], [2, 2]] and model.to_numpy().tolist() == model.grid
    assert [(r['index'], r['name'], r['vp'], r['density']) for r in model.rocks] == [(1, 'Claystone', 4073.0, 2629.0), (2, 'Sandstone', 4024.0, 2379.0)]
    assert model.rock(2)['name'] == 'Sandstone' and model.sample_values == [0.0, 0.002, 0.004] and model.horizontal_values == [0.0, 25.0]
    with pytest.raises(Refused, match='not in this model'): model.rock(3)
    section = _core.typed_result(*load('seismic-section'))
    assert isinstance(section, SeismicSection) and section.grid == [[0.0, 0.0], [-0.05, 0.0], [0.05, -0.05]] and section.to_numpy().shape == (3, 2)
    assert (section.origin, section.polarity, section.horizontal_values) == ('not-stated', 'unknown', [1.0, 2.0]) and repr(section) == '<SeismicSection 3×2 time>'
    assert {'wavelet', 'model-section', 'seismic-section'} <= set(typed.TYPES) == set(typed.CLASSES)


def ricker(frequency, dt, n=129):
    return [(1 - 2 * x * x) * math.exp(-x * x) for x in (math.pi * frequency * (k - n // 2) * dt for k in range(n))]


def made(samples, dt, frequency=30.0):
    context = {'type': 'wavelet', 'kind': 'ricker', 'frequency_hz': frequency, 'corners_hz': None, 'dt': dt, 't0': -(len(samples) // 2) * dt,
               'sample_count': len(samples), 'minimum': min(samples), 'maximum': max(samples)}
    return Wavelet(None, {'context': context, 'samples': samples}, b'')


def test_peak_frequency_reads_the_samples_on_a_one_hertz_grid():
    samples = ricker(30, 0.001)
    assert made(samples, 0.001).peak_frequency() == 30.0
    assert made(samples, 0.002).peak_frequency() == 15.0 and made(samples, 0.0005).peak_frequency() == 60.0  # the interval is read, not assumed
    frequencies, magnitudes = made(ricker(30, 0.0005), 0.0005).spectrum()
    assert len(frequencies) == len(magnitudes) == 1001 and frequencies[-1] == 1000.0 and made(ricker(30, 0.0005), 0.0005).peak_frequency() == 30.0
    assert len(made(ricker(10, 0.01), 0.01).spectrum()[0]) == 51 and made(ricker(10, 0.01), 0.01).peak_frequency() == 10.0
    assert made(ricker(40, 0.001), 0.001, frequency=30.0).frequency_note() == 'strongest 40.0, declared 30'
    assert made(samples, 0.001).frequency_note() == 'strongest 30.0, declared 30'


@pytest.mark.parametrize('samples,dt,sentence', [
    (ricker(30, 0.001), 0.0004, 'A wavelet must be sampled every 0.0005 to 0.01 s.'),
    (ricker(30, 0.001), 0.011, 'A wavelet must be sampled every 0.0005 to 0.01 s.'),
    ([0.0, 1.0], 0.001, 'A wavelet has 3 to 4095 samples.'),
    ([0.0] * 4096 + [1.0], 0.001, 'A wavelet has 3 to 4095 samples.'),
])
def test_the_spectrum_is_bounded(samples, dt, sentence):
    with pytest.raises(Refused) as refused: made(samples, dt).peak_frequency()
    assert str(refused.value) == sentence


def ormsby(c): c.update(kind='ormsby', frequency_hz=None, corners_hz=[5.0, 10.0, 10.0, 60.0])


@pytest.mark.parametrize('name,edit,message', [
    ('wavelet', lambda p: p['samples'].__setitem__(0, -0.3), 'Samples and their context disagree'),
    ('wavelet', lambda p: p['context'].update(frequency_hz=None), 'kind and its declared frequencies'),
    ('wavelet', lambda p: ormsby(p['context']), 'corner frequencies must increase'),
    ('wavelet', lambda p: (p['samples'].append(0.0), p['context'].update(sample_count=6)), 'odd number of samples'),
    ('model-section', lambda p: p['context'].update(rock_count=3), 'Rocks and their context disagree'),
    ('model-section', lambda p: p['grid'][2].__setitem__(1, 7), 'names a rock that is not listed'),
    ('model-section', lambda p: p['grid'][1].pop(), 'The grid and its axes disagree'),
    ('seismic-section', lambda p: p['context'].update(maximum=0.5), 'Samples and their context disagree'),
    ('seismic-section', lambda p: p['grid'].pop(), 'The grid and its axes disagree'),
    ('seismic-section', lambda p: p['context'].update(sample_unit='m'), 'An axis and its unit disagree'),
    ('seismic-section', lambda p: p['context'].update(horizontal_unit='m'), 'An axis and its unit disagree'),
])
def test_inconsistencies_are_refused_offline_after_rehashing(name, edit, message):
    """Valid JSON, valid digests and a descriptor that agrees with the payload: only the invariant can refuse."""
    descriptor, body, original = load(name)
    payload = json.loads(body); edit(payload)
    descriptor = copy.deepcopy(descriptor); descriptor['scientific'] = payload['context']
    raw = json.dumps(payload).encode(); rehash(descriptor, raw)
    with pytest.raises(VerificationFailed, match=message): _core.typed_result(descriptor, raw, original)
