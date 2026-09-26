"""Ophiolite pilot CLI: sign in, prepare exact data, run locally, publish explicitly."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from importlib.resources import files
from . import Client,Credential,auth,publish
from .errors import Refused


def configuration(path):
    try:value=json.loads(Path(path).read_text())
    except (OSError,ValueError):raise Refused('Cannot read configuration. Download configuration.json from Connect → Use Python.') from None
    if not isinstance(value,dict) or value.get('schema') not in ('ophiolite.read-configuration/1','ophiolite.local-configuration/1'):
        raise Refused('Download a supported configuration from Connect → Use Python.')
    if not isinstance(value.get('project'),str) or not value['project']:raise Refused('Configuration must name a service and project.')
    value['url']=auth.origin(value.get('url'))
    if ('asset' in value)!=('revision' in value):raise Refused('An exact selection needs both asset and revision.')
    for key in ('asset','revision','curve'):
        if key in value and (not isinstance(value[key],str) or not value[key]):raise Refused('Invalid exact-read selection; download configuration again.')
    return value


def credentials_path(config):return auth.default_path(config['url'],config['project'])


def parser():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name,help in [('list','List permitted scientific assets without a run'),('fetch','Read an exact revision into a new local folder'),('doctor','Check local setup without running code or contacting the server'),('login','Approve this project in your browser'),('status','Check application access'),('logout','Revoke application access'),('prepare','Fetch exact input; no computation or publication'),('run','Execute your prepared Python script on this computer'),('publish','Publish the prepared result; does not share it'),('correct','Run and explicitly publish the bounded offset example'),('share','Give colleagues read or reuse access to a result or original you own')]:
        p=sub.add_parser(name,help=help)
        p.add_argument('--configuration',type=Path,default=Path('configuration.json'))
        p.add_argument('--credentials',type=Path,help='Optional separate private credential file')
        if name=='doctor':p.add_argument('--online',action='store_true',help='Explicitly compare the server contract version')
        if name=='fetch':
            p.add_argument('--asset');p.add_argument('--revision');p.add_argument('--curve')
            p.add_argument('--output',type=Path,required=True)
        if name=='login':
            p.add_argument('--write',action='store_true',help='Request permission to publish results')
            p.add_argument('--no-browser',action='store_true')
        if name in ('prepare','run','publish'):p.add_argument('--work',type=Path,default=Path('run'))
        if name=='correct':
            for field in ('start','stop','offset'):p.add_argument('--'+field,type=float,required=True)
            p.add_argument('--output',type=Path,default=Path('curve-result'))
            p.add_argument('--publish',action='store_true',required=True,help='Explicitly authorize example publication')
        if name=='prepare':
            p.add_argument('--script',type=Path,required=True)
            p.add_argument('--parameters',type=Path,required=True)
        if name in ('prepare','correct'):
            p.add_argument('--asset');p.add_argument('--revision');p.add_argument('--curve');p.add_argument('--name')
            p.add_argument('--release');p.add_argument('--asset-index',type=int);p.add_argument('--runner',action='append')
        if name=='share':
            p.add_argument('--asset',required=True);p.add_argument('--read',action='append');p.add_argument('--reuse',action='append')
    recover=sub.add_parser('recover',help='Recover a saved exact request from its private work folder')
    recover.add_argument('--configuration',type=Path,default=Path('configuration.json'))
    recover.add_argument('--credentials',type=Path)
    recover.add_argument('--work',type=Path,required=True)
    skills=sub.add_parser('skills',help='Locate packaged SDK guidance')
    skills.add_subparsers(dest='action',required=True).add_parser('path')
    return parser


def _binding(client,work,config,args,profile):
    if args.asset or args.release:
        if not args.curve or not args.name or (args.asset and (not args.revision or args.release)):
            raise Refused('Describe one input with --asset/--revision/--curve/--name or --release/--curve/--name.')
        return work.configure(args.asset,args.revision,curve=args.curve,name=args.name,
            release_id=args.release,asset_index=args.asset_index or 0,runners=args.runner,
            publication_profile=profile)
    ident=config.get('binding')
    if not ident:raise Refused('Choose a binding or describe an exact input.')
    candidates=[item for item in client.bindings() if item.id==ident]
    if len(candidates)!=1 or candidates[0].publication_profile!=profile:
        raise Refused('Choose an authorized configuration for this calculation.')
    return candidates[0]


def _local_run(config,work):
    state=publish._stored(work/'run.json');saved=state['config']
    if any(saved.get(key)!=config[key] for key in ('url','project')) or (config.get('binding') and saved.get('binding') not in (None,config['binding'])):
        raise Refused('Run folder belongs to another project or input. Choose its configuration.')
    script=work/'calculation.py'
    if hashlib.sha256(publish._private_bytes(script)).hexdigest()!=saved['parameters']['code_sha256']:
        raise Refused('Script changed. Prepare a new run folder.')
    print('Running your Python script locally. It has your operating-system permissions; review code before running.',flush=True)
    subprocess.run([sys.executable,str(script),str(work)],check=True,
                   **({"umask":0o077} if os.name=="posix" else {}))
    print('Calculation finished. Inspect the outputs before ophiolite publish.')


def main(argv=None):
    args=parser().parse_args(argv)
    if args.command=='skills':
        print(files('ophiolite').joinpath('skills'));return
    config=configuration(args.configuration)
    path=args.credentials or credentials_path(config)
    if args.command=='doctor':
        print('Configuration valid. Execution, if you choose it, stays on your computer.')
        print('Python:',sys.version.split()[0])
        registry=json.loads(files('ophiolite').joinpath('contracts/registry.json').read_text())
        print('Local contracts:',registry['version'])
        print('Run ophiolite status to check current grant/scopes. Use login --write only for advanced publication.')
        if args.online:
            remote=auth.request(config['url']+'/api/v1/contracts')
            print('Server contracts:',remote.get('version','unreported'))
        return
    if args.command=='run':return _local_run(config,args.work.resolve())
    if args.command=='login':
        def notify(url,message):
            print(message,url,flush=True)
            if not args.no_browser:
                import webbrowser
                webbrowser.open(url)
        return auth.device_login(config['url'],config['project'],path=path,write=args.write,notify=notify)
    credential=Credential.from_file(path)
    if args.command=='logout':
        credential.revoke();print('Local authorization removed.');return
    with Client(config['url'],config['project'],credential) as client:
        if args.command=='status':
            with credential.snapshot(client.url,client.project) as headers:result=client._grant_status(headers)
            print(result['state'],result['project_id'],','.join(result['scopes']));return
        if args.command=='list':
            for item in client.assets():print(json.dumps(item))
            return
        if args.command=='fetch':
            asset,revision,curve=[getattr(args,k) or config.get(k) for k in ('asset','revision','curve')]
            client.read(asset,revision,[curve]).save(args.output,legacy_order=True)
            print('Saved exact LAS, curve.json and descriptor.json. No run or publication was created.');return
        if args.command=='share':
            item=next((item for item in client.assets() if item['asset_id']==args.asset),None)
            if item is None:raise Refused('Asset unavailable to this credential; check the asset ID and your project access')
            # Fetch-and-replace: guarded from this read onwards, and safe to retry after a lost response.
            snapshot=client.grants(item)
            if snapshot.generation is None:result=client.share(item,read=args.read or [],reuse=args.reuse or [])
            else:result=client.share(item,read=args.read or [],reuse=args.reuse or [],expected_generation=snapshot.generation)
            print('Uploaded original' if item.get('authority')=='ophiolite:uploaded' else 'Published result',args.asset,'readers:',', '.join(result.recipients) or 'none','reuse:',', '.join(result.reuse_recipients) or 'none');return result
        if args.command=='recover':return client.recover(args.work)
        if config.get('schema')!='ophiolite.local-configuration/1':
            raise Refused('This command needs an advanced calculation configuration. For local analysis use list/fetch.')
        if args.command=='correct':
            if not all(math.isfinite(x) for x in (args.start,args.stop,args.offset)) or args.start>args.stop:
                raise Refused('Finite ordered interval and offset required')
            work=client.work_folder(args.output)
            binding=_binding(client,work,config,args,'curve-edits/1')
            return work.correct(binding,start=args.start,stop=args.stop,offset=args.offset)
        work=client.work_folder(args.work)
        if args.command=='prepare':
            parameters=json.loads(args.parameters.read_text())
            if not isinstance(parameters,dict):raise Refused('Calculation parameters must be an object.')
            script=args.script.read_bytes()
            binding=_binding(client,work,config,args,'las-derived-curves/1')
            run=work.start(binding,application_version='manual-rock-physics/1',parameters=parameters,script=script)
            run.input()
            print('Exact input ready. No calculation or publication performed. Run:',run.id);return run
        run=publish.parse_run(publish._stored(work.path/'resolved.json'),client)
        receipt=work.publish(run,derived_curves=publish._stored(work.path/'curves.json'))
        work.download(receipt)
        print('Committed derived asset:',run.id)
        print('Revision:',receipt.output_reference.revision)
        print('Publication does not change sharing. Manage recipients explicitly in Workspace.')
        return receipt


def entrypoint():
    try:main()
    except (ValueError,OSError,KeyError,TypeError,subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error,ValueError) else 'Operation failed. Check configuration, local files and access; retain the run folder to retry.',file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':entrypoint()
