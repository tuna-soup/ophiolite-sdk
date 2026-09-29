import importlib.util
import json
from pathlib import Path
import sys
import threading
import httpx
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('template_backend',ROOT/'server/app.py');backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
from support import synthetic_server,client_for


@pytest.fixture
def server(tmp_path):
    with synthetic_server() as fixture,client_for(fixture.url,fixture=True) as client:
        state=backend.Backend(client,tmp_path/'work','http://127.0.0.1:56110',fixture)
        api=backend.make_server(state,0);thread=threading.Thread(target=api.serve_forever,daemon=True);thread.start()
        try:
            with httpx.Client(base_url='http://127.0.0.1:'+str(api.server_port)) as http:yield http,state,fixture
        finally:api.shutdown();api.server_close();thread.join()


def bootstrap(http):
    response=http.post('/api/bootstrap',headers={'Origin':'http://127.0.0.1:56110','Sec-Fetch-Site':'same-origin','X-Ophiolite-Bootstrap':'1'})
    assert response.status_code==200;assert response.headers['cache-control']=='no-store';assert 'access-control-allow-origin' not in response.headers
    return response.json()['proof']


@pytest.mark.parametrize('change',[{'Origin':None},{'Origin':'null'},{'Origin':'http://evil.example'},{'Host':'evil.example'},{'X-Ophiolite-Bootstrap':None},{'X-Ophiolite-Bootstrap':'0'},{'Sec-Fetch-Site':None},{'Sec-Fetch-Site':'cross-site'}])
def test_bootstrap_refuses_cross_origin_and_missing_proof_request(server,change):
    http,state,fixture=server
    headers={'Origin':state.origin,'Sec-Fetch-Site':'same-origin','X-Ophiolite-Bootstrap':'1'}
    headers.update(change);headers={k:v for k,v in headers.items() if v is not None}
    response=http.post('/api/bootstrap',headers=headers)
    assert response.status_code==403 and state.proof not in response.text
    assert 'access-control-allow-origin' not in response.headers
    assert fixture.template_mutations=={}


@pytest.mark.parametrize('change',[{'Origin':None},{'Origin':'null'},{'Origin':'http://evil.example'},{'Host':'evil.example'},{'X-Ophiolite-Proof':None},{'X-Ophiolite-Proof':'wrong'}])
def test_every_action_needs_exact_origin_host_and_proof(server,change):
    http,state,fixture=server;proof=bootstrap(http)
    headers={'Origin':state.origin,'X-Ophiolite-Proof':proof};headers.update(change);headers={k:v for k,v in headers.items() if v is not None}
    for path in ['wells','extent']:
        response=http.post('/api/'+path,headers=headers,json={})
        assert response.status_code==403 and proof not in response.text
    assert fixture.template_mutations=={}


def test_get_preflight_query_proof_duplicate_headers_and_body_bounds(server):
    http,state,fixture=server;proof=bootstrap(http)
    assert http.get('/api/wells').status_code==405
    response=http.options('/api/bootstrap',headers={'Origin':'http://evil.example','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-Ophiolite-Bootstrap'})
    assert response.status_code==403 and 'access-control-allow-origin' not in response.headers
    assert http.post('/api/wells?proof='+proof,headers={'Origin':state.origin},json={}).status_code==403
    headers={'Origin':state.origin,'X-Ophiolite-Proof':proof}
    assert http.post('/api/wells',headers=headers,content=b'x'*65537).status_code==413
    assert http.post('/api/wells',headers=headers,content=b'').status_code==413
    assert http.post('/api/wells',headers=headers,json=[]).status_code==400
    for name,value in [('Origin',state.origin),('X-Ophiolite-Proof',proof)]:
        repeated=list(headers.items())+[(name,value)]
        assert http.post('/api/wells',headers=repeated,json={}).status_code==403
    assert fixture.template_mutations=={}


def test_wells_and_extent_for_the_map_and_no_credentials_in_responses(server):
    http,state,fixture=server;proof=bootstrap(http);headers={'Origin':state.origin,'X-Ophiolite-Proof':proof}
    def post(path,body={},status=200):
        response=http.post('/api/'+path,headers=headers,json=body);assert response.status_code==status,response.text
        assert 'access_token' not in response.text and 'refresh_token' not in response.text and 'oph_api_' not in response.text
        return response.json()
    extent=post('extent');assert extent=={'bbox':[5.1,52.1,6.2,52.9],'count':2,'untransformed':0}
    answer=post('wells');features=answer['wells']['features']
    assert answer['wells']['type']=='FeatureCollection' and answer['unlocated']==1
    assert [f['properties']['name'] for f in features]==['Synthetic well 1','Synthetic well 2','Synthetic well 3']
    assert features[0]['geometry']=={'type':'Point','coordinates':[5.1,52.1]} and features[2]['geometry'] is None
    assert features[0]['properties']['source_row']=='1'  # for the popup's Technical details
    fixture.template_faults['expired']=True
    assert 'ophiolite login' in post('wells',status=401)['message']
    assert fixture.template_mutations=={}  # a map only reads


def test_bootstrap_proof_changes_per_start_and_configuration_is_loopback_only(server,tmp_path):
    http,state,fixture=server
    other=backend.Backend(state.client,tmp_path/'other',state.origin)
    assert len(state.proof)>=32 and state.proof!=other.proof
    with pytest.raises(backend.Refused):other.execute('/api/_test',{})
    for origin in ['https://127.0.0.1:56110','http://evil.example:56110','http://127.0.0.1','http://127.0.0.1:56110/path','http://user@127.0.0.1:56110']:
        with pytest.raises(ValueError):backend.Backend(state.client,tmp_path/'bad',origin)


def test_duplicate_host_is_refused_before_dispatch(server):
    http,state,fixture=server
    address=http.base_url
    import http.client as protocol
    connection=protocol.HTTPConnection(address.host,address.port)
    connection.putrequest('POST','/api/bootstrap',skip_host=True)
    for name,value in [('Host',state.frontend_host),('Host',state.frontend_host),('Origin',state.origin),('X-Ophiolite-Bootstrap','1'),('Sec-Fetch-Site','same-origin'),('Content-Length','0')]:connection.putheader(name,value)
    connection.endheaders();response=connection.getresponse()
    assert response.status==403 and state.proof.encode() not in response.read()
    connection.close();assert fixture.template_mutations=={}
