"""E100a C5: client.curve_window and `ophiolite curves window`, against explicit page literals, sync and async."""
import json
from urllib.parse import parse_qs
import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite.errors import Incompatible, Refused, Unavailable, VerificationFailed

DIGEST='81992992a1a15daac792bebf5979c51e0f8c3c1869a75a125999e6466e38bfba'  # the fixture's normalized representation
IDENTITY={'kind':'retained','project_id':'synthetic-project','asset_id':'curve-a','revision':'d899416c42214983308a6feec77a5f94e6d391665dd228d91957393b37caf56b','curve':'GR'}
DISPLAY='A window is for display; read the exact curve'


@pytest.fixture(autouse=True,params=['sync','async'])
def window_transport(request,monkeypatch):
    """The same cases through real AsyncClient calls (as test_read.read_transport)."""
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


def page(level=0,*,cursor=None,next=None,rows=None,top=100.0,base=104.0,items=5,**columns):
    body={'schema':'ophiolite.curve-window/1','shape':'raw' if level==0 else 'summary','identity':dict(IDENTITY),'unit':'gAPI','reference':'md','depth_unit':'M',
          'source':{'algorithm':'run-blocks','algorithm_version':1,'source_digest':DIGEST},
          'request':{'top':top,'base':base,'level':None if rows else level,'rows':rows,'cursor':cursor},
          'range':{'served_first_depth':100.0,'served_last_depth':104.0},'level':level,'exact':level==0,'limit':2048,'items':items,
          'rows_met':None if rows is None else True,'next':next,'before':None,'after':None}
    body.update(columns or ({'sample_index':[0,1,2,3,4],'depth':[100,101,102,103,104],'value':[0,10,None,30,40]} if level==0 else LEVEL1))
    return body


LEVEL1={'runs':[{'run':0,'first_index':0,'last_index':1,'first_depth':100,'last_depth':101},{'run':1,'first_index':3,'last_index':4,'first_depth':103,'last_depth':104}],
        'blocks':dict(zip(('run','first_index','last_index','first_depth','last_depth','first','last','min','min_index','min_depth','max','max_index','max_depth','count'),
                          zip((0,0,1,100,101,0,10,0,0,100,10,1,101,2),(1,3,4,103,104,30,40,30,3,103,40,4,104,2)))),
        'missing':[{'from_index':2,'to_index':2,'from_depth':102,'to_depth':102}]}
LEVEL1['blocks']={k:list(v) for k,v in LEVEL1['blocks'].items()}


def serve(fixture,pages,*,headers=None):
    """Descriptor and curve bytes as test_read; `pages` maps a cursor (None = first) to (status, body)."""
    d,raw,artifact=fixture();calls=[]
    def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith('/windows'):
            status,body=pages[parse_qs(request.url.query.decode()).get('cursor',[None])[0]]
            return httpx.Response(status,json=body,headers=headers or {})
        if '/representations/' in request.url.path:return httpx.Response(200,content=raw if request.url.path.endswith('/curve') else artifact)
        return httpx.Response(200,json=d)
    return d,calls,httpx.MockTransport(handler)


def window(fixture,pages,*args,headers=None,**options):
    d,calls,transport=serve(fixture,pages,headers=headers)
    with httpx.Client(transport=transport) as http:
        client=Client('http://localhost',d['project_id'],Credential.bearer('synthetic-token'),http)
        return client.curve_window(d['asset_id'],d['revision'],'GR',*(args or (100,104)),**({'level':0} if not options else options)),calls


def test_level_zero_equals_the_exact_read(fixture):
    """Mutation: index-shifted concatenation (or a page read twice) breaks the literals and the equality with read."""
    got,calls=window(fixture,{None:(200,page())},headers={'ETag':'"e1"','X-Ophiolite-Access-Generation':'7'})
    d,_,transport=serve(fixture,{})
    with httpx.Client(transport=transport) as http:
        exact=Client('http://localhost',d['project_id'],Credential.bearer('synthetic-token'),http).read(d['asset_id'],d['revision'],['GR'])
    assert got.exact and got.level==0 and got.pages==1 and len(got)==5
    assert got.sample_index==[0,1,2,3,4] and got.depth==[100,101,102,103,104]==exact.curves[0].axis and got.value==[0,10,None,30,40]==exact.curves[0].values
    assert (got.etag,got.access_generation,got.source_digest)==('"e1"','7',DIGEST)
    assert calls[1].endswith('/windows?curve=GR&top=100.0&base=104.0&level=0')


def test_level_one_blocks_with_their_extrema(fixture):
    got,_=window(fixture,{None:(200,page(1))},level=1)
    assert not got.exact and got.shape=='summary' and len(got)==2 and got.pages==1
    assert got.blocks['min']==[0,30] and got.blocks['max_index']==[1,4] and got.blocks['count']==[2,2]
    assert [r['run'] for r in got.runs]==[0,1] and got.missing==[{'from_index':2,'to_index':2,'from_depth':102,'to_depth':102}]


def test_rows_is_sent_as_rows(fixture):
    got,calls=window(fixture,{None:(200,page(1,rows=8))},rows=8)
    assert calls[1].endswith('&rows=8') and got.rows_met is True and got.level==1


@pytest.mark.parametrize('options,sentence',[({'level':0,'rows':8},'Ask for a level or a number of rows, not both and not neither.'),
                                             ({},'Ask for a level or a number of rows, not both and not neither.'),
                                             ({'level':18},'Choose a level from 0 to 17.'),({'rows':2049},'Choose from 1 to 2048 rows.')])
def test_request_refused_before_anything_is_sent(fixture,options,sentence):
    d,calls,transport=serve(fixture,{})
    with httpx.Client(transport=transport) as http:
        client=Client('http://localhost',d['project_id'],Credential.bearer('synthetic-token'),http)
        with pytest.raises(Refused) as error:client.curve_window(d['asset_id'],d['revision'],'GR',100,104,**options)
    assert str(error.value)==sentence and calls==[]


def three_pages():
    return {None:(200,page(next='c1',sample_index=[0,1],depth=[100,101],value=[0,10])),
            'c1':(200,page(cursor='c1',next='c2',sample_index=[2,3],depth=[102,103],value=[None,30])),
            'c2':(200,page(cursor='c2',sample_index=[4],depth=[104],value=[40]))}


def test_three_pages_equal_the_unpaged_window(fixture):
    got,calls=window(fixture,three_pages())
    assert got.pages==3 and calls[2].endswith('&cursor=c1') and calls[3].endswith('&cursor=c2')
    assert (got.sample_index,got.depth,got.value)==([0,1,2,3,4],[100,101,102,103,104],[0,10,None,30,40])


def test_pages_that_do_not_add_up_are_refused(fixture):
    pages=three_pages();pages['c1']=(200,page(cursor='c1',sample_index=[2,3],depth=[102,103],value=[None,30]))  # stops one sample short
    with pytest.raises(VerificationFailed) as error:window(fixture,pages)
    assert str(error.value)=='The window pages do not add up to its 5 items.'


def test_more_pages_than_allowed_is_refused(fixture):
    with pytest.raises(Refused) as error:window(fixture,three_pages(),level=0,max_pages=2)
    assert str(error.value)=='This window needs more than 2 pages; ask for fewer rows or a higher level.'


def test_a_cursor_refused_midway_returns_nothing(fixture):
    pages=three_pages();pages['c1']=(400,{'code':'invalid-argument','message':'This page link is not valid; ask for the window again'})
    with pytest.raises(Refused):window(fixture,pages)


@pytest.mark.parametrize('status,kind',[(404,Unavailable),(422,Incompatible),(400,Refused)])
def test_window_errors_keep_their_sdk_class(fixture,status,kind):
    with pytest.raises(kind) as error:window(fixture,{None:(status,{'code':'x','message':'refused'})})
    assert type(error.value) is kind


def test_digest_of_other_data_is_refused(fixture):
    """Mutation: checking only the digest's length lets the second (valid, other) digest through."""
    short=page();short['source']['source_digest']=DIGEST[:-1]
    other=page();other['source']['source_digest']='0'*64
    with pytest.raises(VerificationFailed):window(fixture,{None:(200,short)})
    with pytest.raises(VerificationFailed) as error:window(fixture,{None:(200,other)})
    assert str(error.value)=='The window was computed from other data than this exact revision.'


@pytest.mark.parametrize('change,sentence',[
    (lambda p:p['identity'].update(revision='other'),'The window does not match the requested exact identity.'),
    (lambda p:p['identity'].update(curve='RHOB'),'The window does not match the requested exact identity.'),
    (lambda p:p.update(exact=False),'Only a level 0 window is exact.'),
    (lambda p:p.update(sample_index=[0,2,1,3,4]),'The window sample indices do not increase.'),
    (lambda p:p.update(value=[0,10,None,30]),'The window columns differ in length.'),
    (lambda p:p['request'].update(top=99.0),'The window answers another request.')])
def test_page_that_does_not_answer_the_request_is_refused(fixture,change,sentence):
    body=page();change(body)
    with pytest.raises(VerificationFailed) as error:window(fixture,{None:(200,body)})
    assert str(error.value)==sentence


def test_level_above_zero_claiming_exact_is_refused(fixture):
    body=page(1);body['exact']=True
    with pytest.raises(VerificationFailed) as error:window(fixture,{None:(200,body)},level=1)
    assert str(error.value)=='Only a level 0 window is exact.'


def test_exact_sample_boundaries_refuse_a_window(fixture):
    """One test per boundary; mutation: remove one guard (each then fails another way or passes the window on)."""
    from ophiolite import scientific,writers,publish
    got,_=window(fixture,{None:(200,page(1))},level=1)
    with pytest.raises(Refused,match='^'+DISPLAY+'$'):scientific.to_numpy(got)
    with pytest.raises(Refused,match='^'+DISPLAY+'$'):writers.write_curves([100,101],{'GR':('gAPI',got)})
    with pytest.raises(Refused,match='^'+DISPLAY+'$'):writers.write_curves(got,{'GR':('gAPI',[1,2])})
    with pytest.raises(Refused,match='^'+DISPLAY+'$'):publish.validate_derived_curves([got],source=b'',sample_count=5)


def cli_run(fixture,monkeypatch,tmp_path,pages,*argv):
    from ophiolite import cli
    d,calls,transport=serve(fixture,pages)
    (tmp_path/'configuration.json').write_text(json.dumps({'schema':'ophiolite.read-configuration/1','url':'http://localhost','project':d['project_id']}))
    monkeypatch.setenv('OPHIOLITE_ACCESS_KEY','oph_api_alice');monkeypatch.setenv('HOME',str(tmp_path));monkeypatch.chdir(tmp_path)
    real=Client
    monkeypatch.setattr(cli,'Client',lambda url,project,credential:real(url,project,credential,httpx.Client(transport=transport)),raising=False)
    try:cli.entrypoint(['curves','window','--asset',d['asset_id'],'--revision',d['revision'],'--curve','GR','--top','100','--base','104',*argv])
    except SystemExit as stop:return stop.code
    return 0


def test_cli_json_equals_the_sdk_result(fixture,monkeypatch,tmp_path,capsys):
    if Client.__name__!='Client':pytest.skip('the command line is synchronous')
    assert cli_run(fixture,monkeypatch,tmp_path,three_pages(),'--level','0','--json')==0
    printed=json.loads(capsys.readouterr().out)
    assert printed==window(fixture,three_pages())[0].to_dict() and printed['pages']==3 and printed['value']==[0,10,None,30,40]
    assert cli_run(fixture,monkeypatch,tmp_path,three_pages(),'--level','0','--output','w.json')==0
    assert json.loads((tmp_path/'w.json').read_text())==printed
    assert cli_run(fixture,monkeypatch,tmp_path,three_pages(),'--level','0','--output','w.json')==1  # an existing file is refused
    assert 'The output file already exists; choose a new file.' in capsys.readouterr().err


def test_cli_exit_codes(fixture,monkeypatch,tmp_path,capsys):
    if Client.__name__!='Client':pytest.skip('the command line is synchronous')
    assert cli_run(fixture,monkeypatch,tmp_path,{},'--level','0','--rows','8')==1
    assert cli_run(fixture,monkeypatch,tmp_path,{None:(404,{'code':'not-found','message':'no'})},'--level','0')==4
    assert cli_run(fixture,monkeypatch,tmp_path,{None:(422,{'code':'incompatible-context','message':'no'})},'--level','0')==1
