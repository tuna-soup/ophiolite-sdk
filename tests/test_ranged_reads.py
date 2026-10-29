"""E100d1 A4: an original above the whole-answer bound is read by ranges, its parts checked as download_original
checks them and the whole verified against the descriptor's digest. Every case runs through Client and AsyncClient."""
import hashlib
import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite import _ranges
from ophiolite.errors import CapacityExceeded, VerificationFailed
from ophiolite.models import invariants as rules


def pytest_generate_tests(metafunc):
    if 'reader' in metafunc.fixturenames:metafunc.parametrize('reader',['sync','async'],indirect=True)


@pytest.fixture(autouse=True)
def reader(request,monkeypatch):
    """The same table through real AsyncClient calls (as test_large_curves.large_transport). The fixture's original
    is 311 bytes; bounds of 100 and 128 bytes make it a three-part read."""
    monkeypatch.setattr(_ranges,'WHOLE_BYTES',100);monkeypatch.setattr(_ranges,'PART_BYTES',128)
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


def serve(fixture,tamper=None):
    """A deployment that answers the original whole only up to 100 bytes (413 above, as the gateway does above
    32 MiB) and by 206 parts otherwise; `tamper(index, part, headers)` changes one part."""
    d,body,original=fixture();calls=[]
    raw=rules.artifact(d)
    digest=hashlib.sha256(original).hexdigest()
    def handler(request):
        calls.append((request.url.path,request.headers.get('range')))
        if request.url.path.endswith('/representations/'+raw['id']):
            if 'range' not in request.headers:return httpx.Response(413)
            first,last=(int(x) for x in request.headers['range'].removeprefix('bytes=').split('-'))
            part=original[first:last+1];headers={'content-range':'bytes %d-%d/%d'%(first,first+len(part)-1,len(original)),'x-content-sha256':digest}
            if tamper:part,headers=tamper(len([c for c in calls if c[1]])-1,part,headers)
            return httpx.Response(206,content=part,headers=headers)
        if '/representations/' in request.url.path:return httpx.Response(200,content=body)
        return httpx.Response(200,json=d)
    return d,original,calls,httpx.MockTransport(handler)


def read(d,transport):
    with httpx.Client(transport=transport) as http:
        return Client('http://localhost',d['project_id'],Credential.bearer('synthetic-token'),http).read(d['asset_id'],d['revision'],['GR'])


def test_an_original_above_the_bound_is_read_in_parts_and_verified(fixture):
    """Mutation: the whole read kept above the bound (the deployment answers 413: CapacityExceeded)."""
    d,original,calls,transport=serve(fixture)
    got=read(d,transport)
    assert got.artifact==original
    assert [c[1] for c in calls if c[1]]==['bytes=0-127','bytes=128-255','bytes=256-383']


def test_at_the_bound_the_original_is_asked_whole(fixture,monkeypatch):
    d,original,calls,transport=serve(fixture);monkeypatch.setattr(_ranges,'WHOLE_BYTES',len(original))
    with pytest.raises(CapacityExceeded):read(d,transport)  # this deployment refuses a whole answer; none was ranged
    assert not [c for c in calls if c[1]]


def other_start(i,part,headers):
    return part,({**headers,'content-range':'bytes 0-%d/311'%(len(part)-1)} if i==1 else headers)

def other_digest(i,part,headers):
    return part,({**headers,'x-content-sha256':'0'*64} if i==1 else headers)

def other_total(i,part,headers):
    return part,({**headers,'content-range':headers['content-range'].replace('/311','/312')} if i==1 else headers)

def empty(i,part,headers):
    return (b'' if i==1 else part),headers

def longer(i,part,headers):
    return (part+b'x' if i==2 else part),headers

def corrupt(i,part,headers):  # a well-formed part with one byte altered; the stated digest unchanged
    return (bytes([part[0]^1])+part[1:] if i==1 else part),headers


@pytest.mark.parametrize('tamper',[other_start,other_digest,other_total,empty,longer])
def test_a_part_that_is_not_the_next_part_of_the_same_file_is_refused(fixture,tamper):
    """Mutation: each check of _ranges.Parts.accept removed in turn (the read then returns or fails elsewhere)."""
    d,original,calls,transport=serve(fixture,tamper)
    with pytest.raises(VerificationFailed) as error:read(d,transport)
    assert str(error.value)==_ranges.OTHER_PART


def test_a_corrupt_part_fails_the_whole_digest_before_the_curve_is_asked(fixture):
    """Mutation: verify_bytes after the ranged read removed (the corrupt original is returned)."""
    d,original,calls,transport=serve(fixture,corrupt)
    with pytest.raises(VerificationFailed) as error:read(d,transport)
    assert str(error.value)!=_ranges.OTHER_PART
    normalized=next(r for r in d['representations'] if r['kind']=='normalized')
    assert not [c for c in calls if c[0].endswith('/representations/'+normalized['id'])]
