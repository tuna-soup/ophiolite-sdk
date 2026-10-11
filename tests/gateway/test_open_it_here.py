"""E104 C3: a publication's "Send again" line, copied from its card and run against the real gateway routes: a lost
answer then a rerun is one version, a rerun after that is the same receipt, and a line built on an older version is
refused once a newer one exists. The card's link is the exact version's E45 page."""
import html
import os
import re
import pytest
try:
    from project_gateway.tests.test_one_api_matrix import web,shared,app,service
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY')=='1':raise
    pytest.skip('Platform test runtime is needed for the gateway lane',allow_module_level=True)
from ophiolite import Client,Credential
from ophiolite.bundle import Curve
from ophiolite.errors import IntegrityConflict

LAS_TEXT='''~Version
VERS. 2.0 :
WRAP. NO :
~Well
STRT.M 100 :
STOP.M 102 :
STEP.M 1 :
NULL. -999.25 :
WELL. SDK :
~Curve
DEPT.M :
GR.GAPI :
~ASCII
100 10
101 -999.25
102 30
'''


def copied(receipt):
    return html.unescape(re.search(r'<summary>Send again</summary><p>.*?</p><pre>(.*?)</pre>',receipt._repr_html_(),re.S).group(1))


def test_the_send_again_line_adds_one_version_through_a_lost_answer_and_refuses_after_a_newer_one(web,monkeypatch):
    client=Client('https://workspace.example','p',Credential.bearer('oph_api_alice:read,write'),web.c)
    source=client.upload_data(LAS_TEXT.encode(),profile='las2/1',name='Open it here source',attribution='Synthetic',audience=[],rights_confirmed=True,command_id='oih-src')
    curve=lambda value:Curve.write([100,101,102],{'GR2':('gAPI',[value,None,60])},depth_unit='m')
    first=client.publish_derived(curve(1),name='Open it here',from_=[(source.asset_id,source.revision)],method={'name':'Doubled','declared':False},command_id='oih-1')
    card=first._repr_html_()
    assert '<a href="https://workspace.example/project/p/data/m~'+first.asset_id+'?revision='+first.revision+'">Open in Workspace</a>' in card
    line=copied(first)
    assert line.startswith("client.publish_derived(new_written, name='Open it here', from_=[['"+source.asset_id+"', '"+source.revision+"']]")
    new_written=curve(2)
    real=Client._post_bytes
    def lost(self,*a,**k):
        real(self,*a,**k);raise ConnectionError('the response was lost')
    monkeypatch.setattr(Client,'_post_bytes',lost)
    with pytest.raises(ConnectionError):eval(line)
    monkeypatch.setattr(Client,'_post_bytes',real)
    second=eval(copied(first))  # copied again from the card after the lost answer: the same line, the same request id
    assert (second.asset_id,second.revision_number)==(first.asset_id,2) and eval(copied(first))==second  # the same receipt, not a third version
    assert [(h.number,h.revision) for h in client.history(second).revisions]==[(1,first.revision),(2,second.revision)]
    line=copied(second)
    client.publish_derived(curve(3),name='Open it here',from_=[(source.asset_id,source.revision)],method={'name':'Doubled','declared':False},command_id='oih-3',
                           new_version_of=second.asset_id,expected_parent=second.revision)
    new_written=curve(4)
    with pytest.raises(IntegrityConflict):eval(line)
    assert [h.number for h in client.history(second).revisions]==[1,2,3]
