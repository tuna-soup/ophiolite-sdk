import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from ophiolite import cli,Client,Credential
from ophiolite.errors import Refused
from ophiolite.testing import fixture_server


def configuration(tmp_path,url='http://localhost',schema='ophiolite.local-configuration/1'):
    path=tmp_path/'configuration.json';path.write_text(json.dumps({'schema':schema,'url':url,'project':'p'}));return path


def test_doctor_is_local_and_does_not_open_credentials(tmp_path,monkeypatch,capsys):
    import socket,httpx
    config=configuration(tmp_path)
    def forbidden(*args,**kwargs):raise AssertionError('Offline doctor accessed a forbidden dependency')
    monkeypatch.setattr(socket,'socket',forbidden);monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    monkeypatch.setattr(httpx.Client,'send',forbidden)
    monkeypatch.setattr(Credential,'from_file',forbidden);monkeypatch.setattr(cli.auth,'request',forbidden)
    cli.main(['doctor','--configuration',str(config),'--credentials',str(tmp_path/'missing')])
    assert 'Local contracts: 1.9.0' in capsys.readouterr().out
    assert not (tmp_path/'missing').exists()


def test_doctor_online_is_explicit(tmp_path,monkeypatch,capsys):
    config=configuration(tmp_path);calls=[]
    monkeypatch.setattr(cli.auth,'request',lambda url:calls.append(url) or {'version':'1.9.0'})
    cli.main(['doctor','--configuration',str(config),'--online'])
    assert calls==['http://localhost/api/v1/contracts']
    assert 'Server contracts: 1.9.0' in capsys.readouterr().out


def test_login_write_and_sdk_namespace(tmp_path,monkeypatch):
    config=configuration(tmp_path);calls=[]
    monkeypatch.setattr(cli.auth,'device_login',lambda *args,**kwargs:calls.append((args,kwargs)))
    cli.main(['login','--configuration',str(config),'--write','--no-browser'])
    args,options=calls[0]
    assert args==('http://localhost','p') and options['write'] is True
    assert '/sdk/v1/projects/' in str(options['path'])


def test_prepare_publish_and_recovery(tmp_path,monkeypatch,capsys):
    with fixture_server() as server:
        config=configuration(tmp_path,server.url);work=tmp_path/'work'
        script=tmp_path/'source.py';script.write_text('raise AssertionError("prepare executed code")\n')
        params=tmp_path/'parameters.json';params.write_text('{}')
        monkeypatch.setattr(Credential,'from_file',lambda path:Credential.bearer('oph_api_alice'))
        args=['prepare','--configuration',str(config),'--work',str(work),'--asset','synthetic','--revision','revision','--curve','GR','--name','CLI','--script',str(script),'--parameters',str(params)]
        run=cli.main(args);assert server.handler.mutations=={'configure':1,'start':1}
        assert cli.main(args).id==run.id
        assert server.handler.mutations=={'configure':1,'start':1}
        (work/'curves.json').write_text(json.dumps([{'mnemonic':'NEW','unit':'gAPI','description':'Original synthetic','values':[0,None,10,20,30]}],indent=2));(work/'curves.json').chmod(0o600)
        result=cli.main(['publish','--configuration',str(config),'--work',str(work)])
        assert (work/'result.las').read_bytes()
        assert cli.main(['recover','--configuration',str(config),'--work',str(work)]) is None
        assert 'Committed derived asset:' in capsys.readouterr().out
        assert result.publication_id==run.id


@pytest.mark.parametrize('damage',['project','script','binding'])
def test_run_refuses_changed_selection_before_subprocess(tmp_path,monkeypatch,damage):
    config=configuration(tmp_path);work=tmp_path/'work';work.mkdir(mode=0o700)
    code=b'# original synthetic\n';script=work/'calculation.py';script.write_bytes(code);script.chmod(0o600)
    saved={'url':'http://localhost','project':'p','binding':'b','parameters':{'code_sha256':hashlib.sha256(code).hexdigest()}}
    if damage=='project':saved['project']='other'
    if damage=='script':script.write_bytes(b'changed')
    if damage=='binding':
        data=json.loads(config.read_text());data['binding']='different';config.write_text(json.dumps(data))
    state=work/'run.json';state.write_text(json.dumps({'config':saved}));state.chmod(0o600)
    calls=[];monkeypatch.setattr(subprocess,'run',lambda *args,**kwargs:calls.append(args))
    with pytest.raises(Refused):cli.main(['run','--configuration',str(config),'--work',str(work)])
    assert not calls


def test_correct_requires_explicit_publish():
    with pytest.raises(SystemExit) as error:cli.main(['correct','--start','100','--stop','101','--offset','2'])
    assert error.value.code==2


def test_correct_and_retry(tmp_path,monkeypatch,capsys):
    with fixture_server() as server:
        config=configuration(tmp_path,server.url);folder=tmp_path/'correction'
        monkeypatch.setattr(Credential,'from_file',lambda path:Credential.bearer('oph_api_alice'))
        args=['correct','--configuration',str(config),'--output',str(folder),'--asset','synthetic','--revision','revision','--curve','GR','--name','CLI','--start','100','--stop','104','--offset','1','--publish']
        receipt=cli.main(args);again=cli.main(args)
        assert receipt==again and server.handler.mutations=={'configure':1,'start':1,'publish':1}
        assert 'Recovered existing publication;' in capsys.readouterr().out
        assert all((folder/name).exists() for name in ('original.las','input.json','changes.json','result.las','receipt.json','run.json'))


def test_legacy_help_sentences_and_flags():
    import argparse
    frozen=json.loads((Path(__file__).parent/'fixtures/cli-0.2-help.json').read_text())
    parser=cli.parser();assert parser.description==frozen['description']
    sub=next(a for a in parser._actions if isinstance(a,argparse._SubParsersAction))
    descriptions={choice.dest:choice.help for choice in sub._choices_actions}
    for name,expected in frozen['commands'].items():
        assert descriptions[name]==expected['help']
        actions={a.dest:a for a in sub.choices[name]._actions}
        for dest,fields in expected['arguments'].items():
            action=actions[dest]
            assert {'options':action.option_strings,'help':action.help,'required':action.required,'default':str(action.default)}==fields


def test_local_run_calls_current_python_with_selected_folder(tmp_path,monkeypatch,capsys):
    config=configuration(tmp_path);work=tmp_path/'work';work.mkdir(mode=0o700)
    script=work/'calculation.py';script.write_bytes(b'# Original synthetic calculation\n');script.chmod(0o600)
    state=work/'run.json';state.write_text(json.dumps({'config':{'url':'http://localhost','project':'p','parameters':{'code_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}}}));state.chmod(0o600)
    calls=[];monkeypatch.setattr(subprocess,'run',lambda args,**kwargs:calls.append((args,kwargs)))
    cli.main(['run','--configuration',str(config),'--work',str(work)])
    assert calls==[([sys.executable,str(script),str(work)],{'check':True,**({'umask':0o077} if os.name=='posix' else {})})]
    assert 'operating-system permissions' in capsys.readouterr().out


def test_prepare_refuses_nonobject_parameters_before_configure(tmp_path,monkeypatch):
    with fixture_server() as server:
        config=configuration(tmp_path,server.url);script=tmp_path/'script.py';script.write_text('# original synthetic\n')
        parameters=tmp_path/'parameters.json';parameters.write_text('[]')
        monkeypatch.setattr(Credential,'from_file',lambda path:Credential.bearer('oph_api_alice'))
        with pytest.raises(Refused,match='parameters must be an object'):
            cli.main(['prepare','--configuration',str(config),'--work',str(tmp_path/'work'),'--asset','synthetic','--revision','revision','--curve','GR','--name','Example','--script',str(script),'--parameters',str(parameters)])
        assert not server.requests


@pytest.mark.parametrize('change',['schema','project','selection','curve','url'])
def test_invalid_configuration(change,tmp_path):
    config=configuration(tmp_path);value=json.loads(config.read_text())
    if change=='schema':value['schema']='other'
    if change=='project':value['project']=''
    if change=='selection':value['asset']='missing-revision'
    if change=='curve':value['curve']=None
    if change=='url':value['url']='https://user:password@example.org'
    config.write_text(json.dumps(value))
    with pytest.raises(ValueError):cli.configuration(config)


@pytest.mark.parametrize('start,stop,offset',[(2,1,1),(0,1,float('nan')),(0,1,True)])
def test_workfolder_offset_refuses_unsafe_parameters(tmp_path,start,stop,offset):
    from ophiolite.errors import ValidationFailed
    with Client('http://localhost','p') as client:
        with pytest.raises(ValidationFailed):client.work_folder(tmp_path/'work').correct(None,start=start,stop=stop,offset=offset)


def test_binding_list_shape_is_not_silently_empty():
    import httpx
    from ophiolite.errors import VerificationFailed
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'bindings':{}}))) as http:
        with pytest.raises(VerificationFailed):Client('http://localhost','p',http=http).bindings()


@pytest.mark.skipif(os.name!='posix',reason='POSIX file permission contract')
def test_local_calculation_outputs_are_private_and_publishable(tmp_path,monkeypatch):
    with fixture_server() as server:
        config=configuration(tmp_path,server.url);work=tmp_path/'work'
        script=tmp_path/'calculation.py'
        curves=[{'mnemonic':'NEW','unit':'gAPI','description':'Original synthetic','values':[0,None,10,20,30]}]
        script.write_text('import pathlib,sys\n(pathlib.Path(sys.argv[1])/"curves.json").write_text('+repr(json.dumps(curves))+')\n')
        parameters=tmp_path/'parameters.json';parameters.write_text('{}')
        monkeypatch.setattr(Credential,'from_file',lambda path:Credential.bearer('oph_api_alice'))
        cli.main(['prepare','--configuration',str(config),'--work',str(work),'--asset','synthetic','--revision','revision','--curve','GR','--name','Private output','--script',str(script),'--parameters',str(parameters)])
        prior=os.umask(0o022)
        try:cli.main(['run','--configuration',str(config),'--work',str(work)])
        finally:os.umask(prior)
        assert (work/'curves.json').stat().st_mode & 0o777 == 0o600
        result=cli.main(['publish','--configuration',str(config),'--work',str(work)])
        assert result.publication_id and (work/'result.las').read_bytes()


def test_checkpoint_permission_error_is_not_reported_as_invalid_json(tmp_path):
    from ophiolite import publish
    from ophiolite.errors import RecoveryUnavailable
    path=tmp_path/'checkpoint.json';path.write_text('{}');path.chmod(0o644)
    with pytest.raises(RecoveryUnavailable,match='Cannot read the private work checkpoint'):
        publish._stored(path)
