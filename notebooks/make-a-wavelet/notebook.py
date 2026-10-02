# %% [markdown]
# # Make a wavelet
# Compute a 30 Hz Ricker wavelet, check its strongest frequency against the declared one, and, in your project, upload
# it and add a second version.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` everything is computed on your own
# computer and nothing is published. To work in your project, put the `configuration.json` from Connect → Use Python in
# this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then set
# `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter. Uploading
# there creates a wavelet that only you can see until you share it.
# %%
import uuid
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.gallery import connect, synthetic
from ophiolite.synthetics import ricker
from ophiolite.typed import Wavelet

client = connect()
wavelet = ricker(30, 0.001, duration=0.128)
c = wavelet.context
print(f"{c['sample_count']} samples every {c['dt'] * 1000:g} ms, from {c['t0'] * 1000:g} to {-c['t0'] * 1000:g} ms")
# %% [markdown]
# ## Frequency content
# The spectrum is read from the samples on a 1 Hz grid up to the Nyquist frequency, so it shows what the samples hold,
# not what the file declares. The same samples read at twice the interval have their strongest frequency at half.
# %%
peak = wavelet.peak_frequency()
print(f'Strongest at {peak:g} Hz (read to the nearest 1 Hz); declared {c["frequency_hz"]:g} Hz')
assert peak == 30.0
stretched = Wavelet(None, {'context': {**c, 'dt': 0.002, 't0': 2 * c['t0']}, 'samples': wavelet.samples}, None)
print(f'The same samples every 2 ms: strongest at {stretched.peak_frequency():g} Hz')
assert stretched.peak_frequency() == 15.0
# %%
frequencies, magnitudes = wavelet.spectrum()
fig, (left, right) = plt.subplots(1, 2, figsize=(9, 3.5), layout='constrained')
left.plot([t * 1000 for t in wavelet.times], wavelet.samples)
left.set_xlabel('Time (ms)')
left.set_ylabel('Amplitude')
left.set_title('Ricker 30 Hz')
right.plot(frequencies[:151], magnitudes[:151])
right.axvline(peak, linestyle='--', color='grey')
right.set_xlabel('Frequency (Hz)')
right.set_ylabel('Magnitude')
right.set_title(f'Strongest at {peak:g} Hz')
fig.savefig('make-a-wavelet.png', bbox_inches='tight')
plt.close(fig)
print('Wrote make-a-wavelet.png')
# %% [markdown]
# ## Upload it, then add a second version
# The file states its kind, frequency, interval, first time and polarity, so nothing is declared beside it. A sharper
# wavelet uploaded with `append_to` and `expected_parent` becomes version 2 of the same wavelet; version 1 is kept.
# %%
if synthetic():
    print('Synthetic mode: nothing is published. Set OPHIOLITE_URL and OPHIOLITE_PROJECT to upload in your project.')
else:
    upload = dict(profile='wavelet-text/1', name='Ricker 30 Hz', attribution='Computed with ophiolite.synthetics', audience=[], rights_confirmed=True)
    first = client.upload_data(Wavelet.write(wavelet).bytes, filename='ricker-30.txt', command_id=uuid.uuid4().hex, **upload)
    sharper = ricker(35, 0.001, duration=0.128)
    second = client.upload_data(Wavelet.write(sharper).bytes, filename='ricker-35.txt', command_id=uuid.uuid4().hex,
                                append_to=first.asset_id, expected_parent=first.revision, **upload)
    assert second.asset_id == first.asset_id and second.revision != first.revision
    for number, receipt, expected in ((1, first, wavelet), (2, second, sharper)):
        read = client.read_data(first.asset_id, receipt.revision)
        assert read.samples == expected.samples
        print(f'version {number}: {receipt.revision[:12]} strongest at {read.peak_frequency():g} Hz')
