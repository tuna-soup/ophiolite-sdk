"""E85 C6: what `client.upload` checks before anything is sent when it is given one file, an address, or declarations.
No server is needed."""
import os

import pytest

from ophiolite.errors import Refused
from ophiolite.upload_runs import checked_declarations, is_address, open_file, readers


def test_one_file_is_a_folder_of_one_named_by_the_file(tmp_path):
    (tmp_path / 'tops.csv').write_bytes(b'well,top,md\n')
    folder = open_file(tmp_path / 'tops.csv')
    assert (folder.name, folder.address) == ('tops.csv', None)
    assert folder.listing() == [{'path': 'tops.csv', 'bytes': 12, 'sha256': '6f62698d2dba813e7c99cad3c4158a3bacaa3cbdc3e5f97af9dcc39461f67cd2'}]


def test_a_link_given_as_the_file_is_refused(tmp_path):
    (tmp_path / 'real.las').write_bytes(b'x'); os.symlink(tmp_path / 'real.las', tmp_path / 'link.las')
    with pytest.raises(Refused, match='link.las is not a regular file. Nothing was sent.'): open_file(tmp_path / 'link.las')


@pytest.mark.parametrize('text, address', [('https://www.nlog.nl/brh-web/rest/brh/logdocument/1', True), ('http://example.org/a.las', True),
                                           ('data/a.las', False), ('/tmp/https:/x', False), ('C:\\data\\a.las', False)])
def test_an_address_is_told_from_a_path_by_its_scheme(text, address):
    assert is_address(text) is address


def test_declarations_name_a_kind_and_only_the_items_it_takes():
    assert checked_declarations({'segy/1': {'crs': 'EPSG:23031', 'z_domain': 'time'}}) == {'segy/1': {'crs': 'EPSG:23031', 'z_domain': 'time'}}
    assert checked_declarations(None) is None
    with pytest.raises(Refused) as error: checked_declarations({'segy/1': {'depth_unit': 'm'}})
    assert str(error.value) == 'Seismic volume (SEG-Y) files do not take depth_unit; they take z_domain, crs, datum.'
    with pytest.raises(Refused, match='Well log \\(LAS\\) files do not take crs; they take no declarations.'): checked_declarations({'las2/1': {'crs': 'x'}})
    with pytest.raises(Refused, match='No kind of file is named las'): checked_declarations({'las': {}})
    assert 'geotiff/1' in [e['profile'] for e in readers()]  # the snapshot holds the fifteenth kind
