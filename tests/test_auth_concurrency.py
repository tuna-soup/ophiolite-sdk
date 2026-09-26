from contextlib import contextmanager
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import queue
import threading
import time
import pytest
from ophiolite import auth
from ophiolite.errors import AuthenticationRequired
from test_auth import cache,envelope

spec=importlib.util.spec_from_file_location('token_server',Path(__file__).parent/'helpers/token_server.py')
server_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(server_module)
TokenServer=server_module.TokenServer


def worker(path,url,events,results,action='headers',ready=None):
    # Instrument the real lock entry and real cache reread, not just worker start.
    try:
        credential=auth.Credential.open(path)
        original_lock=auth._lock;original_current=credential._current
        @contextmanager
        def observed_lock(*args,**kwargs):
            events.put('lock-enter')
            with original_lock(*args,**kwargs):yield
        def observed_current():
            result=original_current();events.put('captured:'+result['credential']['refresh_token']);return result
        auth._lock=observed_lock;credential._current=observed_current
        try:
            if ready is not None:ready.set()
            if action=='delete':credential.delete();result='deleted'
            else:result=credential.headers(url,'test')['Authorization']
            results.put(('ok',result))
        finally:auth._lock=original_lock
    except Exception as error:results.put(('error',type(error).__name__))


def configured(tmp_path,server):
    value=envelope();data=value['credential'];data.update(url=server.url,issuer=server.url,
        token_endpoint=server.url+'/token',revocation_endpoint=None,expires_at=1)
    return cache(tmp_path,value)


@pytest.mark.skipif(os.name=='nt',reason='Windows lock path is not qualified')
@pytest.mark.parametrize('second_action',['headers','delete'])
def test_processes_serialize_while_provider_withholds_response(tmp_path,second_action):
    ctx=multiprocessing.get_context('spawn')
    with TokenServer() as server:
        path=configured(tmp_path,server)
        events=ctx.Queue();results=ctx.Queue()
        first=ctx.Process(target=worker,args=(path,server.url,events,results))
        second=ctx.Process(target=worker,args=(path,server.url,events,results,second_action))
        first.start()
        try:
            assert events.get(timeout=3)=='lock-enter'
            assert events.get(timeout=3)=='captured:synthetic-refresh'
            assert server.first.wait(3)
            second.start();assert events.get(timeout=3)=='lock-enter'
            # The first HTTP reply remains withheld; second must neither read stale
            # data nor send a request. The no-lock mutant produces both observations.
            assert not server.second.wait(.25)
            with pytest.raises(queue.Empty):events.get(timeout=.1)
            server.release.set()
            first.join(5);second.join(5)
            assert not first.is_alive() and not second.is_alive()
            outcomes=[results.get(timeout=1),results.get(timeout=1)]
            assert all(kind=='ok' for kind,_ in outcomes),outcomes
            assert len(server.requests)==1
            if second_action=='delete':assert not path.exists()
            else:
                assert [result for _,result in outcomes]==['Bearer rotated-access']*2
                assert events.get(timeout=1)=='captured:rotated-refresh'
        finally:
            server.release.set()
            for process in (first,second):
                if process.pid:
                    process.join(2)
                    if process.is_alive():process.terminate();process.join()


def test_threads_refresh_once(tmp_path):
    with TokenServer() as server:
        path=configured(tmp_path,server);first=auth.Credential.open(path);second=auth.Credential.open(path)
        results=[];errors=[];entered=threading.Event();captured=threading.Event()
        current=second._current
        def observed():captured.set();return current()
        second._current=observed
        def run(credential,event=None):
            try:
                if event:event.set()
                results.append(credential.headers(server.url,'test'))
            except Exception as error:errors.append(error)
        a=threading.Thread(target=run,args=(first,));b=threading.Thread(target=run,args=(second,entered))
        a.start()
        try:
            assert server.first.wait(3);b.start();assert entered.wait(1)
            assert not captured.wait(.25) and not server.second.is_set()
        finally:server.release.set();a.join(5);b.join(5)
        assert not errors and len(results)==2 and len(server.requests)==1


def test_delete_wins_before_waiting_refresh(tmp_path):
    with TokenServer() as server:
        path=configured(tmp_path,server);credential=auth.Credential.open(path)
        entered=threading.Event();outcomes=[]
        def waiting():
            entered.set()
            try:credential.headers(server.url,'test');outcomes.append('unexpected')
            except AuthenticationRequired:outcomes.append('refused')
        with auth._lock(path):
            thread=threading.Thread(target=waiting);thread.start();assert entered.wait(1)
            # Exact critical section of delete, under the same real lock.
            credential._current();path.unlink()
        thread.join(3)
        assert outcomes==['refused'] and not path.exists() and not server.requests


def test_cancel_lock_wait(tmp_path):
    path=cache(tmp_path);before=path.read_bytes();credential=auth.Credential.open(path)
    cancel=threading.Event();entered=threading.Event();outcomes=[]
    def waiting():
        entered.set()
        try:credential.headers('http://localhost:8765','test',cancel=cancel)
        except AuthenticationRequired as error:outcomes.append(str(error))
    with auth._lock(path):
        thread=threading.Thread(target=waiting);thread.start();assert entered.wait(1)
        cancel.set();thread.join(2)
        assert not thread.is_alive()
    assert outcomes==['Credential operation cancelled.'] and path.read_bytes()==before


def test_lock_timeout_and_symlink(tmp_path):
    path=cache(tmp_path)
    with auth._lock(path):
        with pytest.raises(AuthenticationRequired,match='busy'):
            with auth._lock(path,timeout=.02):pass
    lock=path.with_name(path.name+'.lock');lock.unlink();lock.symlink_to(path)
    with pytest.raises(AuthenticationRequired):
        with auth._lock(path):pass


def test_timeout_stops_before_next_lock_attempt(tmp_path,monkeypatch):
    import fcntl
    path=cache(tmp_path);attempts=[];clock=iter([0,2])
    monkeypatch.setattr(auth.time,'monotonic',lambda:next(clock))
    def occupied(fd,flags):
        attempts.append(flags)
        if len(attempts)>1:raise AssertionError('A timed-out operation attempted to lock again')
        raise BlockingIOError()
    monkeypatch.setattr(fcntl,'flock',occupied)
    with pytest.raises(AuthenticationRequired,match='busy'):
        with auth._lock(path,timeout=1):pass
