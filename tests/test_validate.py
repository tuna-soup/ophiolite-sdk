import copy
import hashlib
import json
import pytest
from ophiolite import validate
from ophiolite.errors import VerificationFailed, Incompatible
from ophiolite.models.generated import ScientificAsset, ApplicationCurve
from ophiolite.models import invariants as rules


def encoded(descriptor,view):
    raw=json.dumps(view,allow_nan=False).encode()
    rep=next(r for r in descriptor['representations'] if r['kind']=='normalized')
    rep['bytes']=len(raw);rep['sha256']=hashlib.sha256(raw).hexdigest()
    return raw

@pytest.mark.parametrize('origin',['source','capture','derived'])
@pytest.mark.parametrize('frozen',[False,True])
def test_fixture_pairs(fixture,origin,frozen):
    d,raw,_=fixture(origin,frozen);asset,curve=validate.pair(d,raw)
    assert curve.axis==[100,101,102,103,104]
    assert curve.values==([2,12,None,32,40] if origin=='derived' else [0,10,None,30,40])
    assert curve.unit=='gAPI' and curve.context.depth_unit=='M'
    assert asset.revision==d['revision']

@pytest.mark.parametrize('where',['source','interpretation','scientific'])
def test_additive_nested_pair(fixture,where):
    d,raw,_=fixture();v=json.loads(raw)
    if where=='source':v['source']['new_label']='retained extension'
    elif where=='interpretation':v['interpretation']['new_label']='retained extension'
    else:d['scientific']['new_label']='retained extension'
    raw=encoded(d,v)
    a,c=validate.pair(d,raw)
    assert 'new_label' in (c.source.model_extra if where=='source' else c.interpretation.model_extra if where=='interpretation' else a.scientific.model_extra)

@pytest.mark.parametrize('bad',[True,'2',float('inf'),float('nan')])
def test_strict_samples(fixture,bad):
    _,raw,_=fixture();v=json.loads(raw);v['values'][0]=bad
    with pytest.raises(Exception):ApplicationCurve.model_validate(v)

@pytest.mark.parametrize('location',['profile','count','enum','required','nine'])
def test_generated_constraints_alone(fixture,location):
    from pydantic import ValidationError
    d,_,_=fixture()
    if location=='profile':d['profile']='LAS2/1'
    if location=='count':d['scientific']['sample_count']=-1
    if location=='enum':d['interpretation_evidence']='guessed'
    if location=='required':del d['schema']
    if location=='nine':d['representations']*=5
    with pytest.raises(ValidationError) as error:ScientificAsset.model_validate(d)
    if location=='profile':assert error.value.errors()[0]['type']=='string_pattern_mismatch'

def test_strict_schema_extra(fixture):
    d,_,_=fixture();d['new_field']=True
    assert ScientificAsset.model_validate(d).model_extra['new_field'] is True
    with pytest.raises(VerificationFailed):validate.schema(d,'ophiolite.scientific-asset/1')
    validate.schema(d,'ophiolite.scientific-asset/1',strict=False)

# Each case changes one semantic property; the structural model still accepts it.
CASES=[
 ('custody',lambda d:d.update(custodian='ophiolite:managed'),'Origin, custody'),
 ('history',lambda d:d['retention'].update(historical_reads='while-retained-and-authorized'),'Historical availability'),
 ('source',lambda d:d.update(authority='other'),'Source authority'),
 ('provenance',lambda d:d['provenance'].update(evidence='script-declared'),'Capture is not'),
 ('record',lambda d:d.update(interpretation_evidence='recorded'),'Recorded interpretation'),
 ('repids',lambda d:d['representations'][1].update(id=d['representations'][0]['id']),'Representation IDs'),
 ('repmedia',lambda d:d['representations'][1].update(media_type='application/x-las'),'Media type'),
 ('reprole',lambda d:d['representations'][0].update(profile='ophiolite.application-curve/1'),'Representation kind'),
 ('operations',lambda d:d.update(supported_operations=['read','read']),'Duplicate supported'),
 ('profilemembership',lambda d:d['source_reference'].update(profile='unknown/1'),'not registered'),
 ('emptyunits',lambda d:d['scientific'].update(unit=''),'Empty units'),
 ('missingcount',lambda d:d['scientific'].update(missing_count=6),'Missing count'),
 ('duplicates',lambda d:d['scientific'].update(axis_duplicates=True),'Strict ordered'),
 ('order',lambda d:d['scientific'].update(sample_count=1,missing_count=0),'Axis order'),
]
@pytest.mark.parametrize('case,mutate,message',CASES,ids=[r[0] for r in CASES])
def test_semantic_asset_guards(fixture,case,mutate,message):
    d,_,_=fixture();mutate(d)
    d=ScientificAsset.model_validate(d).model_dump(by_alias=True)
    with pytest.raises(VerificationFailed,match=message):rules.asset(d)

@pytest.mark.parametrize('case',['authority','selfparent','repeatparent','method','revision'])
def test_derived_guards(fixture,case):
    d,_,_=fixture('derived')
    if case=='authority':d['authority']='other'
    if case=='selfparent':d['parents']=[dict(authority=d['authority'],key=d['asset_id'],revision=d['revision'],profile=d['profile'])]
    if case=='repeatparent':d['parents']*=2
    if case=='method':d['provenance']['method']=None
    if case=='revision':d['revision']='0'*64
    with pytest.raises(VerificationFailed):rules.asset(ScientificAsset.model_validate(d).model_dump(by_alias=True))

@pytest.mark.parametrize('case',['time','subset','duplicate'])
def test_authorization_guards(fixture,case):
    d,_,_=fixture();d['authorization']={'status':'evaluated','evaluated_for':'synthetic','evaluated_at':'2026-02-28T10:00:00Z','allowed_operations':['read']}
    if case=='time':d['authorization']['evaluated_at']='2026-02-30T10:00:00Z'
    if case=='subset':d['supported_operations']=[]
    if case=='duplicate':d['authorization']['allowed_operations']=['read','read']
    with pytest.raises(VerificationFailed):rules.asset(ScientificAsset.model_validate(d).model_dump(by_alias=True))

@pytest.mark.parametrize('case',['marker','axislength','depthcurve','axismarker','valuemarker','source','hash','facts','interpretation'])
def test_pair_mutations_with_correct_hash(fixture,case):
    d,raw,_=fixture();v=json.loads(raw)
    if case=='marker':v['context']['missing_value_marker']='nan'
    if case=='axislength':v['values'].pop()
    if case=='depthcurve':v['curve']=v['context']['depth_index']
    if case=='axismarker':v['axis'][0]=-999.25
    if case=='valuemarker':v['values'][0]=-999.25
    if case=='source':v['source']['revision']='changed'
    if case=='hash':v['source_sha256']='0'*64
    if case=='facts':v['values'][0]=None
    if case=='interpretation':v['interpretation']['null_policy']='different'
    with pytest.raises(VerificationFailed):validate.pair(d,encoded(d,v))

@pytest.mark.parametrize('case',['bytes','length','unavailable'])
def test_integrity(fixture,case):
    d,raw,_=fixture();rep=next(r for r in d['representations'] if r['kind']=='normalized')
    if case=='bytes':raw=raw.replace(b'100',b'101',1)
    if case=='length':raw+=b' '
    if case=='unavailable':rep['available']=False
    with pytest.raises(VerificationFailed):validate.pair(d,raw)

@pytest.mark.parametrize('field,expected',[('reader','recorded-differs'),('parsing_policy','recorded-differs'),('lasio_version','recorded-differs'),('null_policy','recorded')])
def test_interpretation_policy(fixture,field,expected):
    d,_,_=fixture('capture');d['recorded_interpretation'][field]='different/1';d['interpretation_evidence']=expected
    assert rules.interpretation(d)==expected
    d['interpretation_evidence']='recorded' if expected=='recorded-differs' else 'recorded-differs'
    with pytest.raises(VerificationFailed,match='reader history'):rules.interpretation(d)

def test_mapping_refusal(fixture):
    d,_,_=fixture('capture');d['recorded_interpretation']['mapping']='different/1'
    with pytest.raises(Incompatible):rules.interpretation(d)

@pytest.mark.parametrize('case',['marker','depthcurve'])
def test_curve_semantics_independent_of_pair(fixture,case):
    _,raw,_=fixture();v=json.loads(raw)
    if case=='marker':v['context']['missing_value_marker']='nan'
    else:v['curve']=v['context']['depth_index']
    with pytest.raises(VerificationFailed,match='marker must be finite|differ from depth'):
        rules.curve(ApplicationCurve.model_validate(v).model_dump(by_alias=True))


def test_unknown_representation_profile_independent(fixture):
    d,_,_=fixture();rep=d['representations'][0];rep['profile']='not-registered/1'
    with pytest.raises(VerificationFailed,match='not registered'):rules.representation(rep)

@pytest.mark.parametrize('case,message',[
 ('unserved','Profile is not served'),
 ('normalized','Exactly one normalized'),
 ('artifact','Profile requires one exact'),
])
def test_representation_cardinality_and_serving(fixture,case,message):
    d,_,_=fixture()
    if case=='unserved':d['profile']='ophiolite/well-curve/1'
    if case=='normalized':d['representations'][1]={**d['representations'][0],'id':'second-artifact'}
    if case=='artifact':d['representations'][0]['kind']='captured-result'
    with pytest.raises(VerificationFailed,match=message):rules.asset(ScientificAsset.model_validate(d).model_dump(by_alias=True))


def test_profile_agreement_with_two_valid_artifact_profiles(fixture,monkeypatch):
    d,_,_=fixture();index,profiles=rules.registry();profiles=copy.deepcopy(profiles)
    profiles['alternate-las/1']=copy.deepcopy(profiles['las2/1'])
    monkeypatch.setattr(rules,'registry',lambda:(index,profiles))
    d['representations'][0]['profile']='alternate-las/1'
    with pytest.raises(VerificationFailed,match='Representation profiles must'):
        rules.asset(ScientificAsset.model_validate(d).model_dump(by_alias=True))


def test_evidence_label_independent_of_asset_shape(fixture):
    d,_,_=fixture();d['interpretation_evidence']='recorded'
    with pytest.raises(VerificationFailed,match='reader history'):rules.interpretation(d)


def test_unknown_schema_is_local_refusal():
    with pytest.raises(VerificationFailed,match='Unknown local schema'):validate.schema({},'unregistered/1')


def corpus():
    from pathlib import Path
    return json.loads((Path(__file__).parent/'fixtures/scientific-invalid.json').read_text())['cases']

@pytest.mark.parametrize('case',corpus(),ids=lambda row:row['id'])
def test_shared_scientific_corpus(case):
    raw=case['normalized_utf8'].encode();descriptor=case['descriptor']
    rep=next(r for r in descriptor['representations'] if r['kind']=='normalized')
    assert len(raw)==rep['bytes'] and hashlib.sha256(raw).hexdigest()==rep['sha256']
    with pytest.raises(VerificationFailed):validate.pair(descriptor,raw)


def test_scientific_corpus_has_each_required_invariant():
    from pathlib import Path
    required=json.loads((Path(__file__).parent/'fixtures/scientific-required.json').read_text())['required']
    ids=[case['id'] for case in corpus()]
    assert len(ids)==len(set(ids))
    assert set(ids)==set(required.values())
    assert len(required)==8
