"""E53: wavelets, a wedge model and its synthetic, held to the Science reference literals (strategy Evidence 7),
with one well-formed defect per refusal and its exact sentence. Oracles are literals computed independently
(bruges 0.5.4 and numpy for the wavelets and the "same" convolution), not this module."""
import subprocess
import sys
import pytest
from ophiolite import synthetics as syn
from ophiolite.errors import ValidationFailed
from ophiolite.typed import ModelSection, SeismicSection, Wavelet

ROCKS = [{'name': 'Rodenrijs Claystone', 'vp': 4073, 'density': 2629}, {'name': 'Delft Sandstone', 'vp': 4024, 'density': 2379}]


def refused(call):
    with pytest.raises(ValidationFailed) as error: call()
    return error.value.violations[0]


def test_wavelets_equal_the_reference_literals():
    w = syn.ricker(30, 0.001, duration=0.128)
    assert isinstance(w, Wavelet) and len(w) == 129 and w.context['t0'] == pytest.approx(-0.064, abs=1e-15) and w[64] == 1.0
    assert w[63] == pytest.approx(0.9735485061943677, abs=1e-15) and w[60] == pytest.approx(0.6209286473131652, abs=1e-15)
    assert min(w.samples) == pytest.approx(-0.446260016743396, abs=1e-15) and w.samples.index(min(w.samples)) == 51
    assert w.peak_frequency() == 30.0 and (w.context['kind'], w.context['frequency_hz'], w.context['polarity']) == ('ricker', 30.0, 'impedance-increase-positive')
    r = syn.ricker(25, 0.002, 101)
    assert r[51] == pytest.approx(0.9274825968732855, abs=1e-15) and r[55] == pytest.approx(-0.1261145121115687, abs=1e-15)
    o = syn.ormsby([5, 10, 40, 50], 0.002, 101)
    assert o[50] == 1.0 and o[51] == pytest.approx(0.9366405715175151, abs=1e-15) and o[48] == pytest.approx(0.7588396020737677, abs=1e-15)
    assert o[60] == pytest.approx(-0.2855539994150138, abs=1e-15) and o.context['corners_hz'] == [5.0, 10.0, 40.0, 50.0]
    negative = syn.ricker(30, 0.001, 129, polarity='impedance-increase-negative')
    assert negative[64] == -1.0 and negative.context['polarity'] == 'impedance-increase-negative' and negative[60] == -w[60]


def test_impedance_reflectivity_and_convolution_orientation():
    assert syn.impedance(4073, 2629) == 10_707_917 and syn.impedance(4024, 2379) == 9_573_096
    assert syn.reflectivity([2, 2, 6]) == [0.0, 0.0, 0.5]
    assert syn.reflectivity([10_707_917, 9_573_096])[1] == pytest.approx(-0.05595484801474167, abs=1e-15)
    assert syn.convolve([0, 0, 1, 0, 0], [1, 2, 3]) == [0, 1, 2, 3, 0]  # convolution, not correlation ([0, 3, 2, 1, 0])
    assert syn.convolve([0, 1, 0, 0], [1, 2]) == [0, 1, 2, 0]  # even kernel: as numpy.convolve(mode='same') gives it


def test_the_wedge_and_its_synthetic_equal_the_literals():
    model = syn.wedge(ROCKS)
    assert isinstance(model, ModelSection) and (model.context['samples'], model.context['traces']) == (200, 61) and sum(map(len, model.grid)) == 12_200
    for trace in (0, 1, 13, 60):
        assert [row for row in range(200) if model.grid[row][trace] == 2] == list(range(80, 80 + trace))
    assert model.horizontal_values[-1] == 1500.0 and model.rock(2)['name'] == 'Delft Sandstone'
    section = syn.synthetic(model, syn.ricker(30, 0.001, duration=0.128))
    g = section.grid
    assert isinstance(section, SeismicSection) and (section.origin, section.polarity) == ('synthetic', 'impedance-increase-positive')
    assert g[80][13] == pytest.approx(-0.08092525942667446, abs=1e-15) and g[93][13] == pytest.approx(0.08092525942667446, abs=1e-15)
    assert g[86][13] == pytest.approx(-0.009959882892372686, abs=1e-15)
    assert g[80][60] == pytest.approx(-0.05595484801478729, abs=1e-15) and g[93][60] == pytest.approx(0.024970404973602155, abs=1e-15)
    assert all(row[0] == 0.0 for row in g)
    peaks = [max(abs(row[t]) for row in g) for t in range(11, 16)]
    assert peaks == pytest.approx([0.07873834, 0.08021843, 0.08092526, 0.08030675, 0.07882666], abs=5e-9)
    tuning = syn.tuning_thickness(section)
    assert tuning.trace == 13 and tuning.thickness == pytest.approx(0.013, abs=1e-15) and tuning.amplitude == pytest.approx(0.08092525942667446, abs=1e-15)
    assert (section.context['minimum'], section.context['maximum']) == (min(min(r) for r in g), max(max(r) for r in g))


def test_tuning_reads_the_absolute_maximum():
    """The wedge is symmetric, so only a hand-built case tells absolute from signed maximum."""
    asymmetric = SeismicSection(None, {'context': {'sample_interval': 0.001}, 'grid': [[-0.9, 0.5], [0.2, 0.1]]}, None)
    assert syn.tuning_thickness(asymmetric).trace == 0


D8 = [
    (lambda: syn.synthetic(depth_model(), syn.ricker(30, 0.001, 129)),
     'A model in depth cannot be combined with a wavelet in time; convert the model to time first (this function does not convert).'),
    (lambda: syn.synthetic(syn.wedge(ROCKS, sample_interval=0.002), syn.ricker(30, 0.001, 129)),
     'The model is sampled every 0.002 s and the wavelet every 0.001 s; make them equal (nothing is resampled).'),
    (lambda: syn.synthetic(syn.wedge(ROCKS), shifted(syn.ricker(30, 0.001, 129), -0.063)), "The wavelet's time zero must be its centre sample."),
    (lambda: syn.synthetic(syn.wedge(ROCKS, samples=100, traces=11), syn.ricker(30, 0.001, 129)), "The wavelet is longer than the model's vertical axis."),
]


def depth_model():
    model = syn.wedge(ROCKS); model.context.update(domain='depth', sample_unit='m'); return model


def shifted(wavelet, t0):
    wavelet.context['t0'] = t0; return wavelet


@pytest.mark.parametrize('call,sentence', D8 + [
    (lambda: syn.ricker(30, 0, 129), 'The sample interval must be positive.'),
    (lambda: syn.ricker(30, -0.001, 129), 'The sample interval must be positive.'),
    (lambda: syn.ricker(30, 0.0004, 129), 'A wavelet must be sampled every 0.0005 to 0.01 s.'),
    (lambda: syn.ricker(30, 0.011, 129), 'A wavelet must be sampled every 0.0005 to 0.01 s.'),
    (lambda: syn.ricker(30, 0.001, duration=0.1285), 'The duration must be a whole number of sample intervals.'),
    (lambda: syn.ricker(30, 0.001, 128), 'A wavelet has an odd number of samples, so one sample is its centre.'),
    (lambda: syn.ricker(30, 0.001, 4097), 'A wavelet has 3 to 4095 samples.'),
    (lambda: syn.ricker(30, 0.001, 129, duration=0.128), 'Give the number of samples or the duration, not both.'),
    (lambda: syn.ricker(500, 0.001, 129), 'A frequency must be below the Nyquist frequency (500 Hz at this interval).'),
    (lambda: syn.ormsby([5, 10, 40, 500], 0.001, 129), 'A frequency must be below the Nyquist frequency (500 Hz at this interval).'),
    (lambda: syn.ormsby([5, 40, 10, 50], 0.002, 101), 'The Ormsby corner frequencies must increase.'),
    (lambda: syn.ricker(30, 0.001, 129, polarity='positive'), 'Declare the polarity as impedance-increase-positive, impedance-increase-negative or unknown.'),
    (lambda: syn.impedance(0, 2629), 'The P-wave velocity and density must be positive.'),
    (lambda: syn.impedance(4073, -1), 'The P-wave velocity and density must be positive.'),
    (lambda: syn.wedge([ROCKS[0], {**ROCKS[1], 'vp': 0}]), 'The P-wave velocity and density must be positive.'),
    (lambda: syn.convolve([0, 1, 0], [1, 2, 3, 4]), 'The kernel is longer than the signal; nothing is padded.'),
    (lambda: syn.wedge(ROCKS, samples=100), 'The wedge does not fit: the top sample plus the thickest trace is longer than the section.'),
])
def test_numerical_refusals(call, sentence):
    assert refused(call) == sentence


def test_the_module_and_the_writers_work_without_numpy():
    code = ('import sys; sys.modules["numpy"] = None\n'
            'from ophiolite import synthetics as s\n'
            'w = s.ricker(30, 0.001, duration=0.128); section = s.synthetic(s.wedge(%r), w)\n'
            'print(s.tuning_thickness(section).trace, len(s.Wavelet.write(w).bytes) > 0, len(s.SeismicSection.write(section).bytes) > 0)' % ROCKS)
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True)
    assert result.stdout.split() == ['13', 'True', 'True']
