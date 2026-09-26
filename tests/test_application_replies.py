import base64
import copy
import json
from pathlib import Path
import pytest
from ophiolite import publish
from ophiolite.errors import VerificationFailed

RECORDINGS=Path(__file__).parent/'recordings'


def exchanges():
    return json.loads((RECORDINGS/'applications-workflow.json').read_text())['exchanges']


@pytest.mark.parametrize('operation',['configure','start','publish'])
def test_recorded_application_replies(operation):
    row=next(r for r in exchanges() if r['path'].endswith('/'+operation))
    assert publish.verify_application_reply(operation,json.loads(base64.b64decode(row['request_base64'])),row['response'],'p')


@pytest.mark.parametrize('operation,field',[
 ('configure','project_id'),('configure','curve'),('configure','name'),('configure','publication_profile'),
 ('configure','managed_input.revision'),('configure','managed_input.asset_id'),
 ('start','project_id'),('start','binding.id'),('start','binding.generation'),
 ('start','application_version'),('start','parameters'),
 ('publish','project_id'),('publish','id'),('publish','state'),('publish','receipt'),
 ('publish','receipt.manifest.parent.revision'),
])
def test_response_cannot_change_request_identity(operation,field):
    row=next(r for r in exchanges() if r['path'].endswith('/'+operation))
    data=copy.deepcopy(row['response']);parts=field.split('.');target=data
    for part in parts[:-1]:target=target[part]
    key=parts[-1]
    target[key]=None if field=='receipt' else ({'changed':True} if field=='parameters' else ('started' if field=='state' else (target[key]+1 if isinstance(target[key],int) else 'different')))
    with pytest.raises(VerificationFailed):
        publish.verify_application_reply(operation,json.loads(base64.b64decode(row['request_base64'])),data,'p')


def test_recorded_upload_identity():
    from ophiolite.models.api import UploadResult
    rows=json.loads((RECORDINGS/'las-uploads-workflow.json').read_text())['exchanges']
    uploaded=next(row for row in rows if row['path'].endswith('/upload'))
    result=publish.parse(UploadResult,uploaded['response'])
    import hashlib
    assert result.revision==hashlib.sha256(base64.b64decode(uploaded['request_base64'])).hexdigest()
