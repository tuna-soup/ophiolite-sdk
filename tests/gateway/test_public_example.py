"""The public-only example runs unchanged against the actual gateway."""
import importlib.util
from pathlib import Path
from test_in_process_publish import web,shared,app as platform_app,service,client
import pytest


@pytest.fixture(params=['unwrapped','wrapped'])
def app(request,monkeypatch,tmp_path):
    import project_gateway.tests.test_applications as fixture
    if request.param=='wrapped':
        header,data=fixture.LAS.split('~ASCII\n',1)
        monkeypatch.setattr(fixture,'LAS',header.replace('WRAP. NO','WRAP. YES')+'~ASCII\n'+'\n'.join(data.split())+'\n')
    lifecycle=platform_app.__wrapped__(tmp_path)
    try:yield next(lifecycle)
    finally:
        try:next(lifecycle)
        except StopIteration:pass


def test_public_example_exact_roundtrip(web,tmp_path):
    from project_gateway.tests.test_applications import LAS
    path=Path(__file__).resolve().parents[2]/'examples/public_curve_handoff.py'
    spec=importlib.util.spec_from_file_location('public_curve_handoff',path)
    example=importlib.util.module_from_spec(spec);spec.loader.exec_module(example)
    alice=client(web,'alice','delegate')
    uploaded=alice.upload_las(LAS.encode(),name='Example input',attribution='Original synthetic fixture',audience=['alice'],rights_confirmed=True)
    receipt=example.calculate(alice,tmp_path/'work',uploaded.asset_id,uploaded.revision,'GR')
    read=alice.read(receipt.asset['asset_id'],receipt.asset['revision'],['GR','CALC'])
    assert read.curves[0].values==[0,None,30]
    assert read.curves[1].values==[0,None,60]
    assert read.curves[1].axis==read.curves[0].axis
    assert read.artifact==(tmp_path/'work/result.las').read_bytes()
