"""E126a acceptance 1: a pandas DataFrame becomes the LAS file `write_curves` makes; missing stays missing, nothing is
inferred, and every float reads back exactly. lasio is the independent reader."""
import math

import lasio
import numpy as np
import pandas as pd
import pytest
from ophiolite import Client, Credential
from ophiolite.errors import ValidationFailed
from ophiolite.frames import write_frame
from ophiolite.testing import synthetic_server

GR = pd.DataFrame({'GR': [0, 10, np.nan, 30, 40]}, index=[100, 101, 102, 103, 104])


def refused(frame, units, sentence, **options):
    with pytest.raises(ValidationFailed) as caught: write_frame(frame, units, **{'depth_unit': 'M', **options})
    assert sentence in str(caught.value)


def test_a_missing_sample_is_written_as_the_marker_and_reads_back_missing():
    written = write_frame(GR, {'GR': 'gAPI'}, depth_unit='M')
    assert written.profile == 'las2/1' and written.declared == {} and written.filename == 'derived.las'
    rows = written.bytes.decode().split('~ASCII\n')[1].splitlines()
    assert rows == ['100 0', '101 10', '102 -999.25', '103 30', '104 40']  # one marker, at 102
    back = lasio.read(written.bytes.decode())
    assert [None if math.isnan(v) else v for v in back['GR']] == [0.0, 10.0, None, 30.0, 40.0]
    assert back.curves['GR'].unit == 'gAPI' and back.curves['DEPT'].unit == 'M'


def test_every_float_reads_back_exactly():
    written = write_frame(pd.DataFrame({'X': [0.1 + 0.2, 1e-7, 2.6]}, index=[1.0, 2.0, 3.0]), {'X': 'v/v'}, depth_unit='M')
    assert list(lasio.read(written.bytes.decode())['X']) == [0.30000000000000004, 1e-07, 2.6]


def test_nothing_is_inferred_and_nothing_altered():
    refused(pd.DataFrame({'GR': [1.0], 'PHI': [0.2]}, index=[1.0]), {'GR': 'gAPI'}, "Declare a unit for ['PHI']; nothing is inferred.")
    refused(pd.DataFrame({'GR': [1.0, 2.0]}, index=[np.nan, 1.0]), {'GR': 'gAPI'}, 'Depth cannot be missing.')
    refused(pd.DataFrame({'GR': [1.0, -999.25]}, index=[1.0, 2.0]), {'GR': 'gAPI'},
            'Curve GR has a real value equal to the null marker -999.25; choose another marker.')
    refused(pd.DataFrame({'GR': [1.0, 2.0]}, index=[5.0, 5.0]), {'GR': 'gAPI'}, 'Depths must be distinct; 5.0 appears more than once.')
    refused(pd.DataFrame({'NAME': ['a']}, index=[1.0]), {'NAME': 'none'}, "Column ['NAME'] is not numeric; write numbers only.")
    refused(GR, {'GR': 'gAPI', 'RHOB': 'g/cm3'}, "These units name no column: ['RHOB'].")
    refused(GR, {'GR': 'gAPI'}, 'Declare the depth unit; nothing is inferred.', depth_unit=None)
    with pytest.raises(ValidationFailed, match='Pass a pandas DataFrame whose index is the depth.'): write_frame([[1, 2]], {}, depth_unit='M')
    refused(pd.DataFrame([[1.0, 2.0]], columns=['GR', 'GR'], index=[1.0]), {'GR': 'gAPI'}, "Column labels must be distinct: ['GR'].")
    refused(pd.DataFrame({'N': [9007199254740993]}, index=[1.0]), {'N': 'count'}, '9007199254740993 in N cannot be written exactly; nothing is rounded.')
    refused(pd.DataFrame({'N': [1.0]}, index=[9007199254740993]), {'N': 'count'}, '9007199254740993 in the depth cannot be written exactly; nothing is rounded.')
    refused(pd.DataFrame({'GR': [np.inf]}, index=[1.0]), {'GR': 'gAPI'}, 'A sample must be finite.')
    wide = pd.DataFrame({'GR': np.array([1, 2], dtype=np.longdouble) + np.longdouble('1e-19')}, index=[1.0, 2.0])
    if np.dtype(np.longdouble).itemsize > 8:  # x86-64 Linux (the CI hosts): an 80-bit float would be rounded
        refused(wide, {'GR': 'gAPI'}, "Column ['GR'] is wider than a 64-bit float and cannot be written exactly; nothing is rounded.")
        refused(pd.DataFrame({'GR': [1.0]}, index=np.array([1], dtype=np.longdouble) + np.longdouble('1e-19')), {'GR': 'gAPI'},
                'The depth is wider than a 64-bit float and cannot be written exactly; nothing is rounded.')
    else: assert write_frame(wide, {'GR': 'gAPI'}, depth_unit='M').profile == 'las2/1'  # longdouble is binary64 here


def test_integers_numpy_scalars_and_pandas_missing_are_admitted():
    frame = pd.DataFrame({'N': pd.array([1, None, 3], dtype='Int64'), 'I': np.array([7, 8, 9], dtype='int32')}, index=np.array([1.5, 2.5, 3.5]))
    rows = write_frame(frame, {'N': 'count', 'I': 'count'}, depth_unit='M').bytes.decode().split('~ASCII\n')[1].splitlines()
    assert rows == ['1.5 1 7', '2.5 -999.25 8', '3.5 3 9']
    exact = write_frame(pd.DataFrame({'N': [2**53, 2**53 + 2]}, index=[1, 2**53 + 2]), {'N': 'count'}, depth_unit='M').bytes.decode()
    assert exact.endswith('\n1 9007199254740992\n9007199254740994 9007199254740994\n')  # large integers a float holds exactly are admitted


def test_frame_metadata_is_not_carried():
    frame = GR.copy(); frame.attrs['source'] = 'secret'; frame.index.name = 'MD'
    text = write_frame(frame, {'GR': 'gAPI'}, depth_unit='M', well='W-1', notes=['Computed in a notebook']).bytes.decode()
    assert 'secret' not in text and 'MD' not in text and 'WELL. W-1 : well' in text and ' Computed in a notebook' in text


def test_a_published_frame_reads_back_with_its_missing_sample():
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        asset = next(iter(alice.assets()))
        frame, _ = alice.read(asset['asset_id'], asset['revision'], ['GR']).to_frame()
        receipt = alice.publish_derived(write_frame(frame * 2, {'GR': 'gAPI'}, depth_unit='M'), name='Doubled', from_=[(asset['asset_id'], asset['revision'])],
                                        method={'name': 'double'}, command_id='e126a-frame')
        back, meta = alice.read(receipt.asset_id, receipt.revision, ['GR']).to_frame()
        assert meta.curves['GR'].missing_count == 1 and meta.curves['GR'].unit == 'gAPI' and meta.axis.unit == 'M'
        values = [None if math.isnan(v) else v for v in back['GR'].tolist()]
        assert values == [0.0, 20.0, None, 60.0, 80.0] and list(back.index) == [100.0, 101.0, 102.0, 103.0, 104.0]
