import importlib.util
import sys
from pathlib import Path
import pytest
from pydantic import ValidationError

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sdk_generator',ROOT/'tools/generate_models.py')
generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)

def generated(schema):
    namespace={'__name__':'generated_probe'}
    source=generator.Generator().generate({'probe.json':{'title':'Probe','type':'object','required':['value'],'properties':{'value':schema}}})
    import types
    module=types.ModuleType('generated_probe');sys.modules[module.__name__]=module
    exec(source,module.__dict__)
    return module.Probe

def test_snapshot_generation():
    assert generator.Generator().generate(generator.documents())==(ROOT/'ophiolite/models/generated.py').read_text()

@pytest.mark.parametrize('schema,good,bad',[
 ({'type':'string','pattern':'^[a-z]+$'},'abc','ABC'),
 ({'type':'string','minLength':2,'maxLength':3},'ab','a'),
 ({'type':'string','maxLength':3},'ab','abcd'),
 ({'type':'integer','minimum':1,'maximum':3},2,0),
 ({'type':'integer','maximum':3},2,4),
 ({'type':'number','exclusiveMinimum':0},0.1,0),
 ({'type':'array','items':{'type':'integer'},'minItems':1,'maxItems':2},[1],[]),
 ({'type':'array','items':{'type':'integer'},'maxItems':2},[1],[1,2,3]),
 ({'enum':['yes','no']},'yes','maybe'),
 ({'const':'fixed'},'fixed','other'),
 ({'anyOf':[{'type':'number'},{'type':'null'}]},None,'1'),
 ({'type':['integer','null']},None,'1'),
 ({'type':'boolean'},True,1),
])
def test_declared_keyword_constraints(schema,good,bad):
    model=generated(schema);assert model.model_validate({'value':good}).value==good
    with pytest.raises(ValidationError):model.model_validate({'value':bad})

def test_server_checked_value_rules_are_accepted_and_left_to_the_server():
    model=generated({'type':'object','maxProperties':3,'if':{'required':['kind']},'then':{'required':['size']}})  # E54: the server checks these
    assert model.model_validate({'value':{'kind':'x'}}).value.kind=='x'  # not required here: the then-rule is the server's

@pytest.mark.parametrize('key,value',[(k,{}) for k in ('allOf','not','patternProperties','dependentSchemas','format')]+[('uniqueItems',True),('additionalProperties',{'type':'string'})])
def test_unsupported_keywords_refuse(key,value):
    with pytest.raises(ValueError,match='unsupported|Unsupported'):
        generated({'type':'object',key:value})

def test_default_ref_and_discriminated_union():
    docs={'p.json':{'title':'Probe','type':'object','required':['choice'],'properties':{
        'count':{'type':'integer','default':2},'choice':{'oneOf':[{'$ref':'#/$defs/A'},{'$ref':'#/$defs/B'}],'discriminator':{'propertyName':'kind'}}},
        '$defs':{'A':{'type':'object','required':['kind'],'properties':{'kind':{'const':'a'}}},
                 'B':{'type':'object','required':['kind'],'properties':{'kind':{'const':'b'}}}}}}
    import types
    module=types.ModuleType('generated_union');sys.modules[module.__name__]=module
    exec(generator.Generator().generate(docs),module.__dict__)
    assert module.Probe.model_validate({'choice':{'kind':'a'}}).count==2
    with pytest.raises(ValidationError):module.Probe.model_validate({'choice':{'kind':'c'}})

@pytest.mark.parametrize('name',['123',''])
def test_invalid_model_name(name):
    with pytest.raises(ValueError,match='Invalid model name'):generator.name(name)

def test_non_object_schema():
    with pytest.raises(ValueError,match='schema must be an object'):generator.Generator().scan(True,'probe')

def test_conflicting_definitions():
    g=generator.Generator();g.model('Thing',{'type':'object'},'a')
    with pytest.raises(ValueError,match='Conflicting model'):g.model('Thing',{'type':'object','description':'different'},'b')

def test_nonlocal_model_ref():
    with pytest.raises(ValueError,match='Unsupported model reference'):generated({'$ref':'other.json'})

def test_nonobject_named_model():
    with pytest.raises(ValueError,match='Non-object named model'):generator.Generator().generate({'p':{'title':'Probe','type':'string'}})

def test_colliding_aliases():
    with pytest.raises(ValueError,match='Colliding Python field alias'):
        generator.Generator().generate({'p':{'title':'Probe','type':'object','properties':{'a-b':{'type':'string'},'a_b':{'type':'string'}}}})

def test_invalid_field_name():
    with pytest.raises(ValueError,match='Unsupported field name'):
        generator.Generator().generate({'p':{'title':'Probe','type':'object','properties':{'1x':{'type':'string'}}}})

def test_check_mode_refuses_drift(tmp_path,monkeypatch):
    model=tmp_path/'ophiolite/models/generated.py';model.parent.mkdir(parents=True);model.write_text('drift')
    monkeypatch.setattr(generator,'ROOT',tmp_path);monkeypatch.setattr(sys,'argv',['generator','--check'])
    with pytest.raises(ValueError,match='Generated models differ'):generator.main()
