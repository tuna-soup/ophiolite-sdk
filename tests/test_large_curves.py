"""E100b C6: a curve above 100,000 samples is described with `read: windows`; `read` refuses it with the gateway's
sentence before any sample or original is requested, and `curve_window` pages it. Sync and async."""
import copy
from urllib.parse import parse_qs
import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite.errors import Refused

SENTENCE='This curve has 150,000 samples; it is read in sections. Download the original file for every sample.'
COLUMNS_DIGEST='5'*64


def pytest_generate_tests(metafunc):
    if 'large_transport' in metafunc.fixturenames:metafunc.parametrize('large_transport',['sync','async'],indirect=True)


@pytest.fixture(autouse=True)
def large_transport(request,monkeypatch):
    """The same cases through real AsyncClient calls (as test_curve_window.window_transport)."""
    if request.param=='sync':yield;return
    import asyncio,importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('async_read_adapter',Path(__file__).parent/'helpers/async_read_adapter.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    loop=asyncio.new_event_loop();instances=[]
    monkeypatch.setattr(__import__(__name__),'Client',module.adapter(loop,instances))
    try:yield
    finally:
        for client in instances:loop.run_until_complete(client.http.aclose())
        loop.close()


def large(fixture):
    """The fixture's descriptor as the gateway describes a curve stored as columns (Platform E100b C4)."""
    d,raw,artifact=fixture();d=copy.deepcopy(d)
    d['scientific'].update(sample_count=150_000,missing_count=150,read='windows')
    normalized=next(r for r in d['representations'] if r['kind']=='normalized')
    normalized.update(media_type='application/vnd.ophiolite.curve-columns',profile='ophiolite.curve-columns/1',bytes=12+400+16*150_000,sha256=COLUMNS_DIGEST)
    return d


def serve(d,pages=None):
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith('/windows'):
            return httpx.Response(200,json=pages[parse_qs(request.url.query.decode()).get('cursor',[None])[0]])
        if '/representations/' in request.url.path:return httpx.Response(500)
        return httpx.Response(200,json=d)
    return calls,httpx.MockTransport(handler)


def client(d,transport,http):
    return Client('http://localhost',d['project_id'],Credential.bearer('synthetic-token'),http)


def test_read_refuses_a_windows_only_curve_before_any_sample_or_original_is_asked(fixture):
    """Mutation: the check after the original or the normalized read (a representation request is then made)."""
    d=large(fixture);calls,transport=serve(d)
    with httpx.Client(transport=transport) as http:
        with pytest.raises(Refused) as error:client(d,transport,http).read(d['asset_id'],d['revision'],['GR'])
    assert str(error.value)==SENTENCE
    assert len(calls)==1 and '/representations/' not in calls[0] and '?curve=GR' in calls[0]  # the descriptor only


def test_describe_says_the_curve_is_read_in_windows(fixture):
    d=large(fixture);calls,transport=serve(d)
    with httpx.Client(transport=transport) as http:
        got=client(d,transport,http).describe(d['asset_id'],d['revision'],'GR')
    assert (got.scientific.read,got.scientific.sample_count)==('windows',150_000)


def page(cursor,next,first,last):
    """A level-9 summary page of one block (512 samples), its digest the columns representation's."""
    return {'schema':'ophiolite.curve-window/1','shape':'summary','identity':{'kind':'retained','project_id':'synthetic-project','asset_id':'curve-a',
            'revision':'d899416c42214983308a6feec77a5f94e6d391665dd228d91957393b37caf56b','curve':'GR'},'unit':'gAPI','reference':'md','depth_unit':'M',
            'source':{'algorithm':'run-blocks','algorithm_version':1,'source_digest':COLUMNS_DIGEST},
            'request':{'top':0.0,'base':30000.0,'level':9,'rows':None,'cursor':cursor},'range':{'served_first_depth':first*0.15,'served_last_depth':last*0.15},
            'level':9,'exact':False,'limit':2048,'items':4,'rows_met':None,'next':next,'before':None,'after':None,
            'runs':[],'missing':[],
            'blocks':{'run':[0],'first_index':[first],'last_index':[last],'first_depth':[first*0.15],'last_depth':[last*0.15],'first':[1.0],'last':[2.0],
                      'min':[0.5],'min_index':[first],'min_depth':[first*0.15],'max':[3.0],'max_index':[last],'max_depth':[last*0.15],'count':[last-first+1]}}


def test_curve_window_pages_a_windows_only_curve_to_the_end(fixture):
    """Three level-9 pages through the cursor; literal page count and blocks."""
    d=large(fixture)
    pages={None:page(None,'c1',0,511),'c1':page('c1','c2',512,1023),'c2':page('c2',None,1024,1535)}
    pages[None]['runs']=[{'run':0,'first_index':0,'last_index':149_999,'first_depth':0.0,'last_depth':22499.85}]
    calls,transport=serve(d,pages)
    with httpx.Client(transport=transport) as http:
        got=client(d,transport,http).curve_window(d['asset_id'],d['revision'],'GR',0.0,30000.0,level=9)
    assert got.pages==3 and got.blocks['first_index']==[0,512,1024] and got.blocks['count']==[512,512,512]
    assert not any('/representations/' in c for c in calls) and calls[-1].endswith('&level=9&cursor=c2')


def test_a_descriptor_whose_storage_and_read_disagree_is_refused(fixture):
    """As the gateway's rule: columns storage exactly when read is windows. Mutation: the SDK rule removed."""
    from ophiolite.errors import VerificationFailed
    d=large(fixture);json_form=copy.deepcopy(d);plain=copy.deepcopy(d)
    normalized=next(r for r in json_form['representations'] if r['kind']=='normalized')
    normalized.update(media_type='application/json',profile='ophiolite.application-curve/1',bytes=1076)
    plain['scientific'].pop('read')
    for wrong in (json_form,plain):
        calls,transport=serve(wrong)
        with httpx.Client(transport=transport) as http:
            with pytest.raises(VerificationFailed,match='stored as columns exactly when'):client(wrong,transport,http).describe(d['asset_id'],d['revision'],'GR')
