import copy
import json
from pathlib import Path
import numpy as np
import pytest
from ophiolite.client import CurveSet
from ophiolite.validate import pair
from ophiolite.errors import AxisMismatch, Refused

FIXTURES=Path(__file__).parent/'fixtures/views'

def view(name='increasing'):
    data=json.loads((FIXTURES/(name+'.json')).read_text());models=[pair(d,raw.encode()) for d,raw in zip(data['descriptors'],data['normalized_utf8'])]
    result=CurveSet([a for a,c in models],[c for a,c in models],data['artifact_utf8'].encode(),url='https://workspace.example',project='synthetic-project')
    return result,data

@pytest.mark.parametrize('name',['increasing','decreasing','duplicates'])
@pytest.mark.parametrize('method',['to_numpy','to_frame'])
def test_full_values_axis_and_metadata(name,method):
    data,oracle=view(name);result,meta=getattr(data,method)()
    expected=np.array(oracle['expected_array'],dtype='float64')
    actual=result.to_numpy() if method=='to_frame' else result
    np.testing.assert_array_equal(actual,expected,strict=True)
    assert actual.shape==(5,2)
    expected_meta=oracle['expected_descriptor']
    expected_meta={**expected_meta,'contracts':{**expected_meta['contracts'],'registry_version':json.loads((Path(__file__).parents[1]/'ophiolite/contracts/registry.json').read_text())['version']}}  # the bundled registry
    assert meta.model_dump()==expected_meta
    assert np.isnan(actual).sum(axis=0).tolist()==[1,1]
    if method=='to_frame':
        assert list(result.index)==oracle['expected_descriptor']['axis']['values']
        assert list(result.columns)==['GR','RHOB'] and result.attrs=={}
        assert meta.attach(result) is result and result.attrs=={'ophiolite':expected_meta}

@pytest.mark.parametrize('method',['to_numpy','to_frame'])
@pytest.mark.parametrize('case,reason',[(v,'values') for v in ('coordinate','length','reorder')]+[
 ('unit','unit'),('status','unit'),('reference','reference'),('index','reference'),('reader','interpretation'),('nullpolicy','interpretation'),('source','source'),('project','source')])
def test_refuses_incompatible_axes_and_context(method,case,reason):
    data,_=view();curve=data.curves[1];asset=data.descriptors[1]
    if case=='coordinate':curve.axis[0]=99
    if case=='length':curve.axis.pop();curve.values.pop()
    if case=='reorder':curve.axis.reverse()
    if case=='unit':curve.context.depth_unit='FT'
    if case=='status':asset.scientific.axis_unit_status='unknown'
    if case=='reference':curve.context.depth_reference='different known reference'
    if case=='index':curve.context.depth_index='TVD'
    if case=='reader':curve.interpretation.lasio_version='different'
    if case=='nullpolicy':curve.interpretation.null_policy='different'
    if case=='source':curve.source.revision='another-exact-revision'
    if case=='project':asset.project_id='another-project'
    with pytest.raises(AxisMismatch) as error:getattr(data,method)()
    assert error.value.reason==reason and error.value.curves==('GR','RHOB')
    if case in ('coordinate','reorder'):assert error.value.first_differing_index==0
    if case=='length':assert error.value.first_differing_index==4

@pytest.mark.parametrize('case',['empty','missing-description','duplicate'])
def test_refuses_incomplete_view(case):
    data,_=view()
    if case=='empty':data.curves=[];data.descriptors=[]
    if case=='missing-description':data.descriptors.pop()
    if case=='duplicate':data.curves[1].curve='GR'
    with pytest.raises(Refused):data.to_numpy()


def test_link_is_exact_and_percent_encoded():
    data,_=view();data.descriptors[0].project_id='a project';data.descriptors[0].asset_id='x/y?#';data.descriptors[0].revision='r/1?';data.descriptors[0].scientific.curve='GR /?#'
    assert data.workspace_url()=='https://workspace.example/project/a%20project/asset/x%2Fy%3F%23?revision=r%2F1%3F&kind=scientific&curve=GR%20%2F%3F%23'
    data.url='';assert data.workspace_url() is None


def test_no_silent_column_reordering():
    data,oracle=view();data.curves.reverse();data.descriptors.reverse()
    array,meta=data.to_numpy()
    np.testing.assert_array_equal(array,np.array(oracle['expected_array'],dtype='float64')[:,::-1])
    assert list(meta.curves)==['RHOB','GR']


def test_missing_extras_in_base_wheel(tmp_path):
    import os,subprocess
    python=os.environ.get('OPHIOLITE_TEST_WHEEL_PYTHON')
    assert python, 'Provide the base-only installed-wheel interpreter'
    script=r'''
import importlib.util,json
from importlib.resources import files
from ophiolite import Descriptor
from ophiolite.client import CurveSet
from ophiolite.validate import pair
from ophiolite.errors import MissingExtra
assert importlib.util.find_spec('numpy') is None
assert importlib.util.find_spec('pandas') is None
root=files('ophiolite').joinpath('contracts/assets/v1/fixtures')
a,c=pair(json.loads(root.joinpath('source.json').read_text()),root.joinpath('curve.json').read_bytes())
data=CurveSet([a],[c],root.joinpath('original.las').read_bytes())
for method,extra in [('to_numpy','numpy'),('to_frame','pandas')]:
 try:getattr(data,method)()
 except MissingExtra as error:assert extra in str(error)
 else:raise AssertionError('Missing optional dependency silently accepted')
assert 'Technical details' in data._repr_html_()
'''
    result=subprocess.run([python,'-I','-c',script],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

@pytest.mark.parametrize('method,extra',[('to_numpy','numpy'),('to_frame','pandas')])
def test_optional_import_refusal_is_typed(monkeypatch,method,extra):
    import builtins
    from ophiolite.errors import MissingExtra
    data,_=view();original=builtins.__import__
    def blocked(name,*args,**kwargs):
        if name==extra:raise ImportError('Optional package deliberately unavailable')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',blocked)
    with pytest.raises(MissingExtra,match=extra):getattr(data,method)()
