"""E55 C5: what `client.upload_runs` checks before anything is sent (a folder's files, a zip's entries), the report
it writes, and how the command line reads its answers. No server is needed."""
import csv
import io
import os
import zipfile

import pytest

from ophiolite import cli
from ophiolite.errors import Refused
from ophiolite.upload_runs import Report, open_folder, open_zip

MIB = 1024 * 1024


def make_zip(path, entries, method=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, 'w', method) as z:
        for name, raw in entries: z.writestr(name, raw)
    return path


def refused(call):
    with pytest.raises(Refused) as error: call()
    return str(error.value)


def test_a_folder_lists_every_file_in_path_order_below_its_name(tmp_path):
    (tmp_path / 'F' / 'b').mkdir(parents=True)
    (tmp_path / 'F' / 'b' / 'two.las').write_bytes(b'2'); (tmp_path / 'F' / 'a.txt').write_bytes(b'1')
    folder = open_folder(tmp_path / 'F')
    assert folder.name == 'F' and [(f['path'], f['bytes']) for f in folder.listing()] == [('F/a.txt', 1), ('F/b/two.las', 1)]


def test_a_link_and_too_many_files_are_refused_before_anything_is_sent(tmp_path):
    (tmp_path / 'F').mkdir(); (tmp_path / 'outside').write_bytes(b'x'); os.symlink(tmp_path / 'outside', tmp_path / 'F' / 'link.las')
    assert refused(lambda: open_folder(tmp_path / 'F')) == 'This folder contains F/link.las, which is not allowed. Nothing was sent. Links and special files are not followed.'
    (tmp_path / 'G').mkdir()
    for i in range(501): (tmp_path / 'G' / ('%03d.txt' % i)).write_bytes(b'x')
    assert refused(lambda: open_folder(tmp_path / 'G')) == 'A folder upload holds at most 500 files; this folder has 501. Choose a smaller folder.'


@pytest.mark.parametrize('name', ['../x.las', '/abs.las', 'a/../../x.las'])
def test_a_zip_entry_outside_the_folder_is_refused(tmp_path, name):
    path = make_zip(tmp_path / 'z.zip', [('ok.las', b'1'), (name, b'2')])
    assert refused(lambda: open_zip(path, 64 * MIB)) == 'This zip file contains %s, which is not allowed. Nothing was sent.' % name


def test_a_zip_entry_more_than_a_hundred_times_its_packed_size_is_refused(tmp_path):
    path = make_zip(tmp_path / 'z.zip', [('bomb.las', b'\0' * (4 * MIB))])
    assert refused(lambda: open_zip(path, 64 * MIB)) == 'This zip file contains bomb.las, which is not allowed. Nothing was sent.'


def test_a_zip_entry_over_the_file_limit_is_refused(tmp_path):
    path = make_zip(tmp_path / 'z.zip', [('big.bin', os.urandom(2 * MIB))], zipfile.ZIP_STORED)
    assert refused(lambda: open_zip(path, MIB)) == 'This zip file contains big.bin, which is not allowed. Nothing was sent.'


def test_four_hundred_legal_entries_over_512_mib_together_are_refused(tmp_path):
    """R2-11: each entry is legal and under 100:1, the count is under 500, but together they unpack to over 512 MiB."""
    block = os.urandom(16 * 1024) * 86  # 1.34 MiB, about 86:1 packed
    path = make_zip(tmp_path / 'z.zip', [('e%03d.bin' % i, block) for i in range(400)])
    info = zipfile.ZipFile(path).infolist()
    assert all(i.file_size < 100 * i.compress_size for i in info) and sum(i.file_size for i in info) > 512 * MIB
    assert refused(lambda: open_zip(path, 64 * MIB)) == 'This zip file contains z.zip, which is not allowed. Nothing was sent. Together its files unpack to more than 512 MiB or more than 100 times the zip.'


def test_an_unreadable_zip_keeps_the_parser_reason_out_of_the_sentence(tmp_path):
    (tmp_path / 'z.zip').write_bytes(b'not a zip')
    with pytest.raises(Refused) as error: open_zip(tmp_path / 'z.zip', MIB)
    assert str(error.value) == 'This zip file cannot be opened. Nothing was sent.' and error.value.details['technical']


def test_a_zip_lists_its_entries_with_their_digests(tmp_path):
    path = make_zip(tmp_path / 'Logs.zip', [('Logs/a.las', b'abc'), ('Logs/', b'')])
    folder = open_zip(path, MIB)
    assert folder.name == 'Logs' and folder.listing() == [{'path': 'Logs/a.las', 'bytes': 3, 'sha256': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}]
    assert folder.files[0].whole() == b'abc'


VIEW = {'run_id': 'r' * 64, 'project_id': 'p', 'folder_name': 'F', 'state': 'closed', 'label': 'Finished with files not added', 'files': 2,
        'counts': {'waiting': 0, 'reading': 0, 'added': 1, 'already_here': 0, 'needs_decision': 0, 'not_read': 0, 'not_supported': 0, 'cancelled': 1},
        'items': [{'ordinal': 0, 'path': 'F/a.las', 'state': 'added', 'kind': 'Well log (LAS 2.0)', 'read': '3 rows, 1 curves, 0 missing samples',
                   'sentence': None, 'asset_id': 'asset-1'},
                  {'ordinal': 1, 'path': 'F/b.asc', 'state': 'cancelled', 'kind': 'Grid', 'read': None, 'sentence': 'Skipped by you.', 'asset_id': None}]}


def test_the_report_names_each_outcome_and_saves_csv_or_json(tmp_path):
    report = Report(VIEW)
    assert report.counts == {'added': 1, 'already-here': 0, 'needs-decision': 0, 'not-read': 0, 'not-supported': 0, 'cancelled': 1} and not report.ok
    rows = list(csv.DictReader(io.StringIO(report.save(tmp_path / 'r.csv').read_text())))
    assert rows == [{'path': 'F/a.las', 'result': 'Added', 'kind': 'Well log (LAS 2.0)', 'read': '3 rows, 1 curves, 0 missing samples', 'reason': '', 'asset': 'asset-1'},
                    {'path': 'F/b.asc', 'result': 'Cancelled', 'kind': 'Grid', 'read': '', 'reason': 'Skipped by you.', 'asset': ''}]
    import json
    assert json.loads(report.save(tmp_path / 'r.json').read_text()) == VIEW


def test_declarations_are_read_per_kind():
    assert cli._declarations(['esri-ascii-grid/1:crs=EPSG:28992', 'esri-ascii-grid/1:z_meaning=depth', 'tops/1:md_unit=m']) == {
        'esri-ascii-grid/1': {'crs': 'EPSG:28992', 'z_meaning': 'depth'}, 'tops/1': {'md_unit': 'm'}}
    with pytest.raises(Refused): cli._declarations(['crs=EPSG:28992'])
