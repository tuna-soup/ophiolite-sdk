"""E18: a bundle as one zip. Packing is deterministic and never overwrites; reading checks the
archive before anything is extracted, and no refusal below leaves an extracted file behind. The
name, case and link refusals use archives valid under every other rule; the size, ratio and
folder refusals are also caught later by the manifest checks (defence in depth)."""
import hashlib
import io
import json
import stat
import struct
import tempfile
import zipfile
from pathlib import Path
import pytest
from ophiolite import bundle
from ophiolite.errors import Refused, VerificationFailed
from test_bundle import written, typed_items, typed_read
from test_seismic import slices_bundle


@pytest.fixture
def staging(tmp_path, monkeypatch):
    """Extraction happens under this folder; it must stay empty after every refusal."""
    folder = tmp_path / 'staging'; folder.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(folder))
    return folder


def zip_of(entries, *, attrs=None, method=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)); info.external_attr = (attrs or {}).get(name, 0o100600 << 16)
            info.compress_type = method; z.writestr(info, data)
    return buffer.getvalue()


def entries_of(folder):
    folder = Path(folder)
    return [(p.relative_to(folder).as_posix(), p.read_bytes()) for p in sorted(folder.rglob('*')) if p.is_file()]


def test_round_trips_for_every_bundle_version(tmp_path, staging):
    curve = written(tmp_path)                                                       # 1.0
    typed = bundle.write_bundle(tmp_path / 'typed', typed_items())                   # 2.0
    mesh = typed_read('mesh')
    newer = bundle.write_bundle(tmp_path / 'mesh', [({'asset_id': mesh._wire_descriptor['asset_id'], 'revision': mesh._wire_descriptor['revision'], 'curves': None}, mesh)])  # 2.2
    sliced = slices_bundle(tmp_path, 'sliced')                                        # 2.3
    for source in (curve, typed, newer, sliced):
        archive = bundle.pack(source.path, tmp_path / (source.path.name + '.zip'))
        again = bundle.pack(source.path, tmp_path / (source.path.name + '-again.zip'))
        assert archive.read_bytes() == again.read_bytes()  # deterministic
        opened = bundle.open_bundle(archive)
        assert opened.manifest == source.manifest and [a.revision for a in opened.assets] == [a.revision for a in source.assets]
        assert [sorted(a.curves) for a in opened.assets] == [sorted(a.curves) for a in source.assets]
        if source is curve: assert opened.assets[0].curves['GR'].values == source.assets[0].curves['GR'].values
        if source is sliced: assert opened.assets[0].slices[0].values == source.assets[0].slices[0].values
        extracted = opened.path; assert extracted.is_relative_to(staging)
        opened.close(); assert not extracted.exists()  # the bundle owns its extracted folder
    with pytest.raises(Refused): bundle.pack(curve.path, tmp_path / (curve.path.name + '.zip'))  # never overwrites


def test_compressible_data_is_stored_within_the_ratio_and_reads(tmp_path, staging):
    source = written(tmp_path)
    original = source.path / 'assets/0/original.las'
    manifest = json.loads((source.path / 'manifest.json').read_text())
    # A valid bundle whose original is highly compressible: pack must keep it readable.
    las = original.read_text().replace('~ASCII', '# ' + 'x' * 200_000 + '\n~ASCII')
    original.write_text(las)
    for f in manifest['assets'][0]['files']:
        if f['role'] == 'original': f['sha256'], f['bytes'] = hashlib.sha256(las.encode()).hexdigest(), len(las.encode())
    (source.path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(VerificationFailed): bundle.open_bundle(source.path)  # the descriptor still pins the old original: invalid
    fresh = written(tmp_path / 'fresh')
    archive = bundle.pack(fresh.path, tmp_path / 'fresh.zip')
    with zipfile.ZipFile(archive) as z:
        assert all(i.compress_type == zipfile.ZIP_STORED or i.file_size <= i.compress_size * bundle.ZIP_RATIO for i in z.infolist())
    assert bundle.open_bundle(archive).assets[0].revision == fresh.assets[0].revision


def test_pack_refuses_unlisted_files_and_leaves_nothing_on_failure(tmp_path, monkeypatch):
    source = written(tmp_path)
    (source.path / 'notes.txt').write_text('mine')
    with pytest.raises(Refused, match='does not list'): bundle.pack(source.path, tmp_path / 'x.zip')
    (source.path / 'notes.txt').unlink()
    calls = []
    real = zipfile.ZipFile.writestr
    def failing(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2: raise OSError('disk full')
        return real(self, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, 'writestr', failing)
    with pytest.raises(OSError): bundle.pack(source.path, tmp_path / 'y.zip')
    assert not (tmp_path / 'y.zip').exists() and not list(tmp_path.glob('.y.zip.packing-*'))


def base_entries(tmp_path):
    return entries_of(written(tmp_path).path)


@pytest.mark.parametrize('case', ['traversal', 'absolute', 'case-collision', 'link', 'folder', 'manifest-size', 'entry-count', 'ratio', 'unlisted', 'missing-manifest'])
def test_archive_refusals_extract_nothing(tmp_path, staging, monkeypatch, case):
    entries = base_entries(tmp_path); attrs = {}; method = zipfile.ZIP_STORED
    first = entries[0][0]
    def listed(name, data):  # the manifest lists the entry, so only the name rule can refuse it
        manifest = json.loads(dict(entries)['manifest.json'])
        manifest['assets'][0]['files'].append({'path': name, 'role': 'descriptor', 'curve': 'X', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        entries[:] = [(n, json.dumps(manifest).encode() if n == 'manifest.json' else d) for n, d in entries] + [(name, data)]
    escaped = tmp_path / 'escaped.txt'
    if case == 'traversal': listed('assets/0/..', b'x')
    if case == 'absolute': listed(str(escaped), b'x')
    if case == 'case-collision': listed(first.rsplit('/', 1)[0] + '/' + first.rsplit('/', 1)[1].swapcase(), b'x')  # valid layout, same name ignoring case
    if case == 'link': attrs[first] = (stat.S_IFLNK | 0o777) << 16
    if case == 'folder': entries.append(('assets/9/', b''))
    if case == 'manifest-size': entries = [(n, d + b' ' * (bundle.MAX_MANIFEST_BYTES + 1) if n == 'manifest.json' else d) for n, d in entries]
    if case == 'entry-count': monkeypatch.setattr(bundle, 'MAX_ENTRIES', len(entries) - 1)
    if case == 'ratio': entries = [(n, d if n != first else d + b' ' * 5_000_000) for n, d in entries]; method = zipfile.ZIP_DEFLATED
    if case == 'unlisted': entries.append(('assets/0/extra.json', b'{}'))
    if case == 'missing-manifest': entries = [(n, d) for n, d in entries if n != 'manifest.json']
    path = tmp_path / 'case.zip'; path.write_bytes(zip_of(entries, attrs=attrs, method=method))
    with pytest.raises(VerificationFailed): bundle.open_bundle(path)
    assert list(staging.iterdir()) == [] and not escaped.exists()


def test_lying_sizes_and_disagreeing_headers_are_refused(tmp_path, staging):
    raw = bytearray(zip_of(base_entries(tmp_path)))
    # Central directory: the first entry declares one byte fewer than it holds (sizes at offsets 20 and 24 of the record).
    central = raw.rfind(b'PK\x01\x02', 0, raw.find(b'PK\x05\x06'))
    first_record = raw.find(b'PK\x01\x02')
    compressed, size = struct.unpack_from('<II', raw, first_record + 20)
    struct.pack_into('<II', raw, first_record + 20, compressed - 1, size - 1)
    path = tmp_path / 'lying.zip'; path.write_bytes(bytes(raw))
    with pytest.raises(VerificationFailed): bundle.open_bundle(path)
    assert list(staging.iterdir()) == []
    raw = bytearray(zip_of(base_entries(tmp_path / 'b')))
    local = raw.find(b'PK\x03\x04'); name_length = struct.unpack_from('<H', raw, local + 26)[0]
    raw[local + 30] = ord('X') if raw[local + 30] != ord('X') else ord('Y')  # the local header names another file
    path = tmp_path / 'headers.zip'; path.write_bytes(bytes(raw))
    with pytest.raises(VerificationFailed): bundle.open_bundle(path)
    assert list(staging.iterdir()) == []


def test_a_migration_package_is_not_a_bundle(tmp_path):
    """E18: a project-move package (E10) is refused by the bundle reader for what it is."""
    folder = tmp_path / 'package'; (folder / 'rows').mkdir(parents=True)
    raw = json.dumps({'schema': 'ophiolite.project-migration/1', 'files': {}, 'tables': {}}).encode()
    (folder / 'manifest.json').write_bytes(raw); (folder / 'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
    with pytest.raises(VerificationFailed, match='not an Ophiolite portable bundle'): bundle.open_bundle(folder)
