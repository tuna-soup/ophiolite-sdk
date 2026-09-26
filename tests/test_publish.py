import copy
import pytest
from ophiolite.publish import validate_derived_curves,validate_changes
from ophiolite.errors import ValidationFailed
from test_las_header import original


def derived():return [{'mnemonic':'NEW','unit':'m/s','description':'Calculated curve','values':[0,None,12]}]


def test_valid_derived_preserves_values():
    data=derived()
    assert validate_derived_curves(data,source=original(),sample_count=3) is data
    assert data[0]['values']==[0,None,12]


@pytest.mark.parametrize('case',['missing','extra','source-duplicate','source-case-duplicate','axis-collision','unselected-collision','derived-collision','lowercase','unit-space','unit-empty','description-colon','description-tilde','description-control','description-empty','wrong-count','nan','boolean','marker','string','empty','nine','total','oversize'])
def test_derived_guards(case):
    source=original();data=derived();count=3
    if case=='missing':del data[0]['unit']
    if case=='extra':data[0]['extra']=1
    if case=='source-duplicate':source=source.replace(b'~ASCII',b'GR.gAPI : duplicate\n~ASCII')
    if case=='source-case-duplicate':source=source.replace(b'~ASCII',b'gr.gAPI : case duplicate\n~ASCII')
    if case=='axis-collision':data[0]['mnemonic']='DEPT'
    if case=='unselected-collision':
        source=source.replace(b'~ASCII',b'RHOB.g/cc : unselected\n~ASCII');data[0]['mnemonic']='RHOB'
    if case=='derived-collision':data.append(copy.deepcopy(data[0]))
    if case=='lowercase':data[0]['mnemonic']='lower'
    if case=='unit-space':data[0]['unit']='m s'
    if case=='unit-empty':data[0]['unit']=''
    if case=='description-colon':data[0]['description']='two: parts'
    if case=='description-tilde':data[0]['description']='two~parts'
    if case=='description-control':data[0]['description']='line\nend'
    if case=='description-empty':data[0]['description']=''
    if case=='wrong-count':data[0]['values'].append(2)
    if case=='nan':data[0]['values'][0]=float('nan')
    if case=='boolean':data[0]['values'][0]=True
    if case=='marker':data[0]['values'][0]=-999.25
    if case=='string':data[0]['values'][0]='2'
    if case=='empty':data=[]
    if case=='nine':data=[dict(derived()[0],mnemonic='D'+str(i)) for i in range(9)]
    if case=='total':
        source=source.replace(b'~ASCII',('\n'.join('C'+str(i)+'.x : Source' for i in range(58))+'\n~ASCII').encode())
        data=[dict(derived()[0],mnemonic='D'+str(i)) for i in range(5)]
    if case=='oversize':count=100000;data=[dict(derived()[0],values=[1.123456789012345]*count,mnemonic='D'+str(i)) for i in range(2)]
    with pytest.raises(ValidationFailed) as error:validate_derived_curves(data,source=source,sample_count=count)
    assert error.value.violations and error.value.details['violations']


def test_all_independent_violations_reported():
    data=[{'mnemonic':'bad','unit':'not a unit','description':'colon: text','values':[True]}]
    with pytest.raises(ValidationFailed) as error:validate_derived_curves(data,source=original(),sample_count=3)
    assert len(error.value.violations)==5


@pytest.mark.parametrize('changes',[
 [],[{'index':0}],[{'index':0,'value':2,'extra':1}],
 [{'index':True,'value':2}],[{'index':-1,'value':2}],[{'index':3,'value':2}],
 [{'index':0,'value':2},{'index':0,'value':3}],
 [{'index':0,'value':True}],[{'index':0,'value':'2'}],
 [{'index':0,'value':float('nan')}],[{'index':0,'value':float('inf')}],
 [{'index':0,'value':-999.25}],[{'index':0,'value':0}],
 [{'index':i,'value':1} for i in range(1001)],
])
def test_changes_refusals(changes):
    with pytest.raises(ValidationFailed):validate_changes(changes,values=[0,None,12],null_marker=-999.25)


def test_valid_changes_null_and_zero():
    changes=[{'index':0,'value':None},{'index':1,'value':0}]
    assert validate_changes(changes,values=[0,None,12],null_marker=-999.25) is changes


def test_changes_count_limit_independent_of_indices():
    with pytest.raises(ValidationFailed):
        validate_changes([{'index':i,'value':1} for i in range(1001)],values=[0]*1001,null_marker=-999.25)
