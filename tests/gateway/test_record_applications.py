"""Generate explicit synthetic route recordings, without credentials or headers."""
import base64
import json
import os
from pathlib import Path
import pytest
from test_in_process_publish import web,shared,app,service,client


def test_gateway_recording_roundtrip(web,tmp_path):
    from project_gateway.tests.test_applications import LAS
    records=[]
    def capture(response):
        response.read();request=response.request
        if '/applications/' not in request.url.path and '/las-uploads/' not in request.url.path:return
        records.append({'method':request.method,'path':request.url.path,
                        'request_base64':base64.b64encode(request.content).decode(),
                        'status':response.status_code,'response':response.json()})
    web.c.event_hooks['response'].append(capture)
    alice=client(web,'alice','delegate')
    upload=alice.upload_las(LAS.encode(),name='Recording input',attribution='Original synthetic fixture',audience=['alice','bob'],rights_confirmed=True,command_id='recording-upload')
    alice.upload_info(upload)
    work=alice.work_folder(tmp_path/'work')
    binding=work.configure(upload.asset_id,upload.revision,curve='GR',name='Recorded calculation')
    run=work.start(binding,application_version='recording/1',parameters={});run.input()
    receipt=work.publish(run,derived_curves=[{'mnemonic':'NEW','unit':'gAPI','description':'Original synthetic result','values':[0,None,60]}])
    work.download(receipt);alice.share(receipt,read=['bob'],expected_generation=alice.grants(receipt).generation);alice.grants(receipt)
    assert records and all(row['status']==200 for row in records)
    destination=os.environ.get('OPHIOLITE_RECORDING_DIR')
    if destination:
        for area in ('applications','las-uploads'):
            path=Path(destination)/(area+'-workflow.json')
            path.write_text(json.dumps({'schema':'ophiolite.sdk-recording/1',
                'source':'Platform 16c1bb1 test_one_api_matrix, original synthetic LAS; HTTP header values deliberately omitted',
                'exchanges':[r for r in records if '/'+area+'/' in r['path']]},indent=2)+'\n')
