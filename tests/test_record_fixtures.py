import base64
import copy
import importlib.util
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import record_fixtures as recorder
sys.path.pop(0)
PROVENANCE={'synthetic_seed':'platform-test-retained-applications','evidence':'Isolated new synthetic test'}

def rows():return json.loads((ROOT/'tests/recordings/synthetic-read.json').read_text())

@pytest.mark.parametrize('case',['provenance','empty','extra','method','path','status','headers','private'])
def test_recording_refusals(case):
    value=rows();provenance=dict(PROVENANCE)
    if case=='provenance':provenance['synthetic_seed']='owner-deployment'
    if case=='empty':value=[]
    if case=='extra':value[0]['request_headers']={}
    if case=='method':value[0]['method']='POST'
    if case=='path':value[0]['path']='/rpc/private'
    if case=='status':value[0]['status']=403
    if case=='headers':value[0]['headers']['authorization']='synthetic-placeholder'
    if case=='private':value[0]['body_base64']=base64.b64encode(b'/home/private/example').decode()
    with pytest.raises(ValueError):recorder.admit(value,provenance)


def test_recorder_preserves_bytes():
    value=rows();assert json.loads(recorder.admit(value,PROVENANCE))==value

@pytest.mark.parametrize('case',['filename','existing'])
def test_recorder_cli_refusal(tmp_path,monkeypatch,case):
    source=tmp_path/'input.json';source.write_text(json.dumps(rows()))
    provenance=tmp_path/'provenance.json';provenance.write_text(json.dumps(PROVENANCE))
    (tmp_path/'tests/recordings').mkdir(parents=True)
    (tmp_path/'tests/recordings/existing.json').write_text('existing retained bytes')
    name='../outside.json' if case=='filename' else 'existing.json'
    monkeypatch.setattr(recorder,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['recorder','--input',str(source),'--provenance',str(provenance),'--name',name])
    with pytest.raises(ValueError,match='filename|exists'):recorder.main()
    assert (tmp_path/'tests/recordings/existing.json').read_text()=='existing retained bytes'
