from importlib.resources import files
import pytest
from ophiolite.las_header import curves,null_marker
from ophiolite.errors import Refused


def original():return files('ophiolite').joinpath('contracts/assets/v1/fixtures/original.las').read_bytes()


def test_complete_header_inventory():
    raw=original();inventory=curves(raw)
    assert [curve.mnemonic for curve in inventory]==['DEPT','GR']
    assert [curve.unit for curve in inventory]==['M','gAPI']
    assert all(curve.description for curve in inventory)
    assert null_marker(raw)==-999.25


def test_header_only_wrapped_empty_unit_and_description_colon():
    raw=b'~Version\nWRAP. YES\n~Well\nNULL. -999.25 : missing\n~Curve\nDEPT.M : Depth: measured\nUNKNOWN. : Unknown unit\n~ASCII\n100\n0\n'
    inventory=curves(raw)
    assert [(c.mnemonic,c.unit,c.description) for c in inventory]==[('DEPT','M','Depth: measured'),('UNKNOWN','','Unknown unit')]
    assert null_marker(raw)==-999.25


@pytest.mark.parametrize('raw',[b'',b'~ASCII\n1 2\n',b'~Curve\nmalformed\n~ASCII\n1\n',b'\xff'])
def test_bad_curve_header(raw):
    with pytest.raises(Refused):curves(raw)


@pytest.mark.parametrize('raw',[b'~Well\nNULL. nan',b'~Well\nNULL. inf',b'~Well\nNULL. word',b'~Well\nOTHER. 1',b'~Well\nNULL. -1\nNULL. -2'])
def test_bad_null_marker(raw):
    with pytest.raises(Refused):null_marker(raw)
