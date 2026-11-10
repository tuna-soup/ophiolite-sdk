"""E140 s2 C4 (D-F, Q3, R7, R13): the starter export's extraction total is a local policy, `max_uncompressed`: the
`--max-uncompressed-bytes` flag, else the 8 GiB default (`UNCOMPRESSED`, unchanged). The starter export is offline and
holds no client, so no deployment serves it (Q3, the stated waiver of "each served by capabilities").

The bound is checked over the archive's own listing before anything is written (`bounded`): at the bound M the archive is
read, at M + 1 it is refused with both numbers, also when every member alone is below M (the sum is compared). The
sentence keeps its old opening ("The archive holds more than N bytes uncompressed"), which the round-trip packs classify.
The keyword reaches the check through each hop, proved by one recorder per hop: the command line to `export`, `export`
to `extracted`, `extracted` to the check.

Mutations (each applied, red, restored): `>` to `>=` in `bounded`; the largest member compared instead of the sum; the
flag ignored in `cli.py`; the keyword dropped where `export` calls `extracted`; the keyword ignored in `extracted` (the
default used). Each forwarding mutation fails exactly one of the three hop tests."""
import io
import zipfile
from types import SimpleNamespace

import pytest

from ophiolite import starter_archive as sa
from ophiolite.errors import Refused

M = 1000


def infos(*sizes):
    return [SimpleNamespace(file_size=n) for n in sizes]


def refused(call, *args, **kw):
    with pytest.raises(Refused) as caught: call(*args, **kw)
    return str(caught.value)


def over(cap, total):
    return 'The archive holds more than %d bytes uncompressed: it holds %d.' % (cap, total) + sa.NOTHING


# --- the check over the listing ------------------------------------------------------------------------------------------

@pytest.mark.parametrize('sizes', [(M - 1,), (M,), (400, 300, 300)], ids=['M-1', 'M', 'three-summing-to-M'])
def test_an_archive_at_or_under_the_bound_is_read(sizes):
    assert sa.bounded(infos(*sizes), M) is None


@pytest.mark.parametrize('sizes', [(M + 1,), (400, 300, 301)], ids=['M+1', 'three-each-under-M-summing-to-M+1'])
def test_an_archive_over_the_bound_is_refused_with_its_own_total(sizes):
    assert refused(sa.bounded, infos(*sizes), M) == over(M, M + 1)


def test_the_default_is_8_gib_and_the_keyword_moves_it():
    listed = infos(4 << 30, (4 << 30) + 1)
    assert sa.UNCOMPRESSED == 8 << 30
    assert refused(sa.bounded, listed) == over(8 << 30, (8 << 30) + 1)
    assert sa.bounded(listed, (8 << 30) + 1) is None


# --- the keyword reaches the check (R13) ---------------------------------------------------------------------------------

def zipped(tmp_path):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as z:
        z.writestr('Syn_Survey/.survey', b'Name: Syn_Survey\n')
        z.writestr('Syn_Survey/a', b'x' * 100)
    (tmp_path / 'a.zip').write_bytes(raw.getvalue())
    (tmp_path / 'x').mkdir()
    return tmp_path / 'a.zip', tmp_path / 'x', len(b'Name: Syn_Survey\n') + 100


def test_extracted_refuses_one_byte_below_the_archive_total_and_writes_nothing(tmp_path):
    path, dest, total = zipped(tmp_path)
    assert refused(sa.extracted, path, dest, 'Syn_Survey', max_uncompressed=total - 1) == over(total - 1, total)
    assert not any(dest.rglob('*'))
    assert sa.extracted(path, dest, 'Syn_Survey', max_uncompressed=total) == dest
    assert (dest / 'Syn_Survey' / 'a').read_bytes() == b'x' * 100


class Reached(Exception):
    pass


def test_export_passes_its_keyword_to_extracted(tmp_path, monkeypatch):
    seen = []
    def recorder(path, dest, survey, **kw):
        seen.append(kw)
        raise Reached
    defn = {'inputs': [{'archive': {'survey': 'Syn_Survey', 'log_step': 0.15}}], 'contents': [], 'values': {}}
    monkeypatch.setattr(sa, 'definition', lambda *a, **kw: defn)
    monkeypatch.setattr(sa, 'evidence', lambda *a: (None, None))
    monkeypatch.setattr(sa, 'checked_file', lambda d: tmp_path / 'a.zip')
    monkeypatch.setattr(sa, 'members', lambda path: {})
    monkeypatch.setattr(sa, 'time_depth_checked', lambda *a: {})
    monkeypatch.setattr(sa, 'extracted', recorder)
    for kw, cap in (({'max_uncompressed': 12345}, 12345), ({}, 8 << 30)):
        with pytest.raises(Reached):
            sa.export(tmp_path / 'definition.json', tmp_path / 'out', catalogue=None, verification=None, custody=None, python='python', **kw)
        assert seen.pop() == {'max_uncompressed': cap}


def test_the_command_passes_its_flag_to_export(tmp_path, monkeypatch):
    from ophiolite import cli
    seen = []
    def recorder(definition, out, **kw):
        seen.append(kw)
        raise Reached
    monkeypatch.setattr(sa, 'export', recorder)
    words = ['starter', 'export', str(tmp_path / 'definition.json'), '--out', str(tmp_path / 'out'), '--catalogue', str(tmp_path / 'records.json'),
             '--verification', str(tmp_path / 'verification'), '--custody', str(tmp_path / 'custody'), '--opendtect-python', 'python']
    for extra, cap in ((['--max-uncompressed-bytes', '12345'], 12345), ([], None)):
        with pytest.raises(Reached): cli.main(words + extra)
        assert seen.pop().get('max_uncompressed') == cap
