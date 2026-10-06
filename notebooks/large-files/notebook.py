# %% [markdown]
# # Send a large file
# Send a seismic volume larger than one request in parts, continue it after an interruption, and read the original back
# by ranges into a file that matches byte for byte.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` the volume is made and plotted on your
# own computer and nothing is sent. To work in your project, put the `configuration.json` from Connect → Use Python in
# this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key); then set
# `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter. Sending creates
# a volume that only you can see until you share it.
# %%
import hashlib
import struct
import tempfile
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from ophiolite.gallery import connect, synthetic

client = connect()
INLINES, CROSSLINES, SAMPLES, INTERVAL_US = 60, 80, 1000, 2000  # 2 s at 2 ms: 19.4 MiB


def amplitude(inline):
    """A dipping reflector: one Ricker-like pulse per trace whose time grows with the crossline."""
    t = np.arange(SAMPLES)[None, :]
    centre = 300 + 4 * np.arange(CROSSLINES)[:, None] + 2 * inline
    x = (t - centre) / 12.0
    return ((1 - 2 * x ** 2) * np.exp(-x ** 2)).astype('>f4')


def write_volume(path):
    """A SEG-Y rev 1 volume, IEEE floats, inline and crossline numbers in bytes 189 and 193 of each trace header."""
    text = ('C 1 SYNTHETIC DIPPING REFLECTOR, MADE BY THE OPHIOLITE GALLERY'.ljust(80) * 40).encode('cp037')
    binary = bytearray(400)
    struct.pack_into('>H', binary, 16, INTERVAL_US); struct.pack_into('>H', binary, 20, SAMPLES)
    struct.pack_into('>h', binary, 24, 5); struct.pack_into('>H', binary, 300, 0x0100); struct.pack_into('>h', binary, 302, 1)
    with open(path, 'wb') as out:
        out.write(text + bytes(binary))
        for inline in range(1, INLINES + 1):
            block = np.zeros((CROSSLINES, 240 + 4 * SAMPLES), np.uint8)
            block[:, 70:72] = np.frombuffer(struct.pack('>h', 1), np.uint8)
            block[:, 114:116] = np.frombuffer(struct.pack('>H', SAMPLES), np.uint8)
            block[:, 116:118] = np.frombuffer(struct.pack('>H', INTERVAL_US), np.uint8)
            block[:, 188:192] = np.frombuffer(struct.pack('>i', inline), np.uint8)
            block[:, 192:196] = np.arange(1, CROSSLINES + 1, dtype='>i4').view(np.uint8).reshape(CROSSLINES, 4)
            block[:, 240:] = amplitude(inline).view(np.uint8)
            out.write(block.tobytes())


work = Path(tempfile.mkdtemp(prefix='ophiolite-large-'))
volume = work / 'dipping-reflector.sgy'
write_volume(volume)
digest = hashlib.sha256(volume.read_bytes()).hexdigest()
print(f'{volume.name}: {volume.stat().st_size / 1048576:.1f} MiB, {INLINES} inlines x {CROSSLINES} crosslines x {SAMPLES} samples')
# %% [markdown]
# ## Look at one inline before sending it
# %%
fig, axis = plt.subplots(figsize=(6, 4))
axis.imshow(amplitude(30).astype(float).T, aspect='auto', cmap='gray', extent=[1, CROSSLINES, SAMPLES * INTERVAL_US / 1000, 0])
axis.set_xlabel('Crossline'); axis.set_ylabel('Two-way time (ms)'); axis.set_title('Inline 30')
fig.savefig('large-files.png', bbox_inches='tight')
plt.close(fig)
print('Wrote large-files.png')
# %% [markdown]
# ## Send it in parts, then read it back
# A file larger than the deployment's request limit (`upload_bytes`) goes in parts of that size. If the connection
# drops, run the cell again: the same `command_id` continues with the parts that did not arrive. The deployment checks
# the whole file before anything is saved, then `download_original` reads it back by ranges; the copy is written only
# when every byte matches the digest the deployment states.
# %%
if synthetic():
    parts = -(-volume.stat().st_size // (8 * 1048576))
    print(f'Synthetic mode: nothing is sent. With 8 MiB requests this file goes in {parts} parts.')
else:
    limits = client.served_limits()
    print(f"This deployment takes requests up to {limits['upload_bytes'] / 1048576:g} MiB and files up to {limits['file_bytes'] / 1048576:g} MiB")
    sent = client.upload_data(volume, profile='segy/1', declared={'z_domain': 'time'}, name='Dipping reflector', attribution='Made by the Ophiolite gallery',
                              audience=[], rights_confirmed=True, command_id='large-files-' + digest[:16])
    assert sent.revision == digest
    copy = client.download_original(sent.asset_id, sent.revision, work / 'copy.sgy')
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == digest
    print('Sent and read back:', sent.revision[:12], '- the copy matches byte for byte')
