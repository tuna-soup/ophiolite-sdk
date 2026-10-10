"""Ophiolite pilot CLI: sign in, prepare exact data, run locally, publish explicitly."""
import argparse
import hashlib
import json
from types import SimpleNamespace
import math
import os
from pathlib import Path
import subprocess
import uuid
import sys
import warnings
from importlib.resources import files
from .errors import OphioliteError,Refused

_NETWORK=('Client','Credential','auth','publish')


def _load():
    """Import the networked client lazily: offline commands (bundle check/show) never load it."""
    import importlib
    package=importlib.import_module('ophiolite')
    for name in _NETWORK:
        if name not in globals():globals()[name]=getattr(package,name) if name in ('Client','Credential') else importlib.import_module('ophiolite.'+name)


def __getattr__(name):
    if name in _NETWORK:
        _load();return globals()[name]
    raise AttributeError(name)


# E31 S3: documented exit codes (docs/cli.md). argparse answers 2 for usage errors itself.
EXIT = {'ok': 0, 'refused': 1, 'usage': 2, 'access': 3, 'conflict': 4, 'busy': 5}
WHOLE = {True: '; also everyone in this project, including people who join later', False: '; not everyone in this project'}  # E78


def exit_code(error):
    """The documented exit code of an error the command raised."""
    from .errors import (AuthenticationRequired, PermissionRefused, Unavailable, IntegrityConflict, Busy, ShareOutcomeUnknown,
                         ResyncRequired)
    if isinstance(error, (AuthenticationRequired, PermissionRefused)): return EXIT['access']
    if isinstance(error, (Busy, ShareOutcomeUnknown)) or getattr(error, 'code', None) in ('unreachable', 'outcome-unknown', 'busy', 'UNAVAILABLE'): return EXIT['busy']
    if isinstance(error, (Unavailable, IntegrityConflict, ResyncRequired)): return EXIT['conflict']
    return EXIT['refused']


def error_document(error):
    """{"error": {...}}: what --json prints for a refusal (the server's code, remedy, docs and request id when it sent them)."""
    fields = {'code': getattr(error, 'code', None) or 'error', 'message': str(error), 'status': getattr(error, 'status', None),
              'remedy': getattr(error, 'remedy', None), 'docs': getattr(error, 'docs', None), 'request_id': getattr(error, 'request_id', None)}
    if (getattr(error, 'details', None) or {}).get('field'): fields['field'] = error.details['field']  # E96: the check refusal's field, never in the sentence
    if hasattr(error, 'outcome') and hasattr(error, 'to_dict'): fields.update(error.to_dict())  # E70a: outcome, sentence, facts and the server's own text
    return {'error': {k: v for k, v in fields.items() if v is not None}}


def done(args, text, payload):
    """One result: its documented JSON shape with --json, otherwise the words for people."""
    if getattr(args, 'json', False): print(json.dumps(payload, indent=2, default=str))
    elif text: print(text)
    return payload


def keyed(p,key_help):
    """E51a: the ways a key is supplied on the command line; every one goes through credential_input.read_credential."""
    if key_help:p.add_argument('--key',help=key_help)
    p.add_argument('--key-file',type=Path,help='Read the project access key from this file (a trailing line break is removed and reported)')
    p.add_argument('--key-stdin',action='store_true',help='Read the project access key from standard input (at most 4 KiB)')


def supplied_key(args):
    """(key, notes, source) from --key, --key-file, --key-stdin or OPHIOLITE_ACCESS_KEY, in that order, through the one
    reader; None when none is given. An explicitly empty OPHIOLITE_ACCESS_KEY is refused, not ignored."""
    from . import credential_input
    if getattr(args,'key',None) is not None:raw,source=args.key,'argument'
    elif getattr(args,'key_file',None) is not None:
        try:
            with open(args.key_file,'rb') as handle:raw=handle.read(credential_input.MAX_BYTES+1)
        except OSError:raise Refused('Cannot read the key file.') from None
        source='file'
    elif getattr(args,'key_stdin',False):raw,source=sys.stdin.read(credential_input.MAX_BYTES+1),'stdin'
    elif 'OPHIOLITE_ACCESS_KEY' in os.environ:
        raw,source=os.environ['OPHIOLITE_ACCESS_KEY'],'environment'
        if not raw.strip():raise Refused('OPHIOLITE_ACCESS_KEY is empty; unset it or give the key.')
    else:return None
    value,notes=credential_input.read_credential(raw,source=source)
    return value,notes,source


def tell(notes):
    """The reader's notice on stderr (never the key)."""
    from .credential_input import notice
    if notice(notes):print(notice(notes),file=sys.stderr)


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
    common=argparse.ArgumentParser(add_help=False)  # E31: every verb prints its documented JSON shape with --json
    common.add_argument('--json',action='store_true',help='Print the documented JSON result (errors as {"error": {...}})')
    sub=parser.add_subparsers(dest='command',required=True)
    _add=sub.add_parser
    sub.add_parser=lambda *a,**k:_add(*a,parents=[common],**k)
    for name,help in [('list','List permitted scientific assets without a run'),('fetch','Read an exact revision into a new local folder'),('doctor','Check local setup without running code or contacting the server'),('login','Approve this project in your browser'),('status','Check application access'),('logout','Revoke application access'),('prepare','Fetch exact input; no computation or publication'),('run','Execute your prepared Python script on this computer'),('publish','Publish the prepared result; does not share it'),('correct','Run and explicitly publish the bounded offset example'),('share','Give colleagues read or reuse access to a result or original you own')]:
        p=sub.add_parser(name,help=help)
        p.add_argument('--configuration',type=Path,default=Path('configuration.json'))
        p.add_argument('--credentials',type=Path,help='Optional separate private credential file')
        if name=='doctor':
            p.add_argument('--online',action='store_true',help='Check the server, the credential, the project and its wells, stopping at the first failure (E51a)')
            p.add_argument('--url',help='With --online: the server address, instead of configuration.json');p.add_argument('--project',help='With --online and --url: the project id')
            keyed(p,'With --online: check this project access key (or use --key-file, --key-stdin or OPHIOLITE_ACCESS_KEY)')
        if name=='fetch':
            p.add_argument('--asset');p.add_argument('--revision');p.add_argument('--curve')
            p.add_argument('--output',type=Path,required=True)
        if name=='login':
            p.add_argument('--write',action='store_true',help='Request permission to publish results')
            p.add_argument('--no-browser',action='store_true')
            keyed(p,'Save a project access key from your account page instead of signing in (or set OPHIOLITE_ACCESS_KEY)')
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
            whole=p.add_mutually_exclusive_group()  # E78: omitted leaves it as it is
            whole.add_argument('--project',dest='project',action='store_const',const=True,help='Also share with everyone in this project, including people who join later (derived publications)')
            whole.add_argument('--no-project',dest='project',action='store_const',const=False,help='Stop sharing with everyone in this project; the people named still see it')
            p.add_argument('--dry-run',action='store_true',help='Print the change without sending it or writing anything')
    tables=sub.add_parser('targets',help='What each type of table needs: its fields, which are required and the choices that describe it (offline)')  # E86
    tables.add_argument('name',nargs='?',help='One type, for example well-tops')
    bundle=sub.add_parser('bundle',help='Check or summarize a portable bundle offline (no server or account needed)')
    bundle.add_argument('action',choices=['check','show','pack']);bundle.add_argument('path',type=Path);bundle.add_argument('archive',type=Path,nargs='?',help='pack: the .zip to write')
    export=sub.add_parser('export',help='Export exact revisions into a new portable bundle')
    export.add_argument('--configuration',type=Path,default=Path('configuration.json'))
    export.add_argument('--credentials',type=Path)
    export.add_argument('--asset',required=True,action='append',help='Repeat --asset and --revision once per exact revision');export.add_argument('--revision',required=True,action='append')
    export.add_argument('--curve',action='append',help='Well log curves; omit for well tops, trajectories and grids');export.add_argument('--output',type=Path,required=True)
    export.add_argument('--no-groups',action='store_true',help='Leave out the result groups observed at export time')
    typed=sub.add_parser('read-data',help='Read well tops, a trajectory or a horizon grid at an exact revision and save it')
    typed.add_argument('--configuration',type=Path,default=Path('configuration.json'))
    typed.add_argument('--credentials',type=Path)
    typed.add_argument('--asset',required=True);typed.add_argument('--revision',required=True);typed.add_argument('--output',type=Path,required=True)
    derived=sub.add_parser('publish-derived',help='Publish a file you derived from exact revisions, with its declared method (a command id or a work folder is required)')
    derived.add_argument('--configuration',type=Path,default=Path('configuration.json'));derived.add_argument('--credentials',type=Path)
    derived.add_argument('file',type=Path,help='The derived file (LAS 2.0 or one of the typed formats)')
    derived.add_argument('--profile',required=True,choices=['las2/1','points-csv/1','mesh-text/1','esri-ascii-grid/1','well-tops-csv/1','deviation-csv/1','opendtect-faultsticks/1',
                                                              'time-depth-csv/1'])  # E57: declare depth_type, depth_unit, time_kind, time_unit
    derived.add_argument('--name',required=True);derived.add_argument('--from',dest='parents',action='append',required=True,metavar='ASSET:REVISION',help='Repeat once per exact parent (1-32)')
    derived.add_argument('--method',required=True,help='What you did, for example scipy.spatial.Delaunay');derived.add_argument('--library',default='');derived.add_argument('--library-version',default='')
    derived.add_argument('--parameters',type=Path,help='A JSON file of the parameters you used (up to 4096 bytes)');derived.add_argument('--declare',action='append',default=[],metavar='KEY=VALUE',help='A declaration such as crs=EPSG:28992 (repeat)')
    derived.add_argument('--new-version-of');derived.add_argument('--expected-parent')
    derived.add_argument('--dry-run',action='store_true',help='Print the publication request without sending it or writing anything')
    once=derived.add_mutually_exclusive_group(required=True)
    once.add_argument('--command-id',help='Keep it: retrying with the same id is safe, a new id can publish twice');once.add_argument('--work',type=Path,help='A private work folder that keeps the command id for you')
    recover=sub.add_parser('recover',help='Recover a saved exact request from its private work folder')
    recover.add_argument('--configuration',type=Path,default=Path('configuration.json'))
    recover.add_argument('--credentials',type=Path)
    recover.add_argument('--work',type=Path,required=True)
    for name,help in (('projects','List the projects a credential reaches (no configuration or project needed)'),('orgs','List the organisations holding a project the credential reaches')):
        p=sub.add_parser(name,help=help)  # E27
        p.add_argument('--url',required=True,help='The gateway address, for example https://ophiolite.example')
        p.add_argument('--credential',type=Path,help='A saved credential file (from ophiolite login); otherwise a key below or OPHIOLITE_ACCESS_KEY')
        keyed(p,None)
        if name=='projects':p.add_argument('--limit',type=int,default=50,help='Page size while fetching (1 to 100)')
    # E31: journey verbs over the project's configuration and credential
    def project(p):
        p.add_argument('--configuration',type=Path,default=Path('configuration.json'));p.add_argument('--credentials',type=Path)
        return p
    entities=project(sub.add_parser('entities',help='List the wells and wellbores you may read'))
    entities.add_argument('--kind',choices=['well','wellbore'])
    wells=project(sub.add_parser('wells',help='The wells you may read, located (list), or their extent'))
    wells.add_argument('action',choices=['list','extent'])
    wells.add_argument('--bbox',help='minx,miny,maxx,maxy in --bbox-crs');wells.add_argument('--bbox-crs');wells.add_argument('--crs',help='Convert locations to this CRS on the server')
    wells.add_argument('--limit',type=int)
    wells.add_argument('--with-source',action='store_true',help='list: also read the source row each well is located from, from the copy its import kept (E50c)')
    wells.add_argument('--column',action='append',metavar='NAME',help='with --with-source: an original column to include (repeat; default: all)')
    changes=project(sub.add_parser('changes',help='The project event log: its head, pages after a cursor, or follow it live'))
    changes.add_argument('action',choices=['head','list','follow'])
    changes.add_argument('--epoch');changes.add_argument('--after',type=int);changes.add_argument('--seconds',type=int,default=300,help='follow: stop after this long')
    curves=project(sub.add_parser('curves',help='A depth window of one exact curve for display: every sample (level 0) or blocks with their extrema'))
    curves.add_argument('action',choices=['window'])
    curves.add_argument('--asset',required=True);curves.add_argument('--revision',required=True);curves.add_argument('--curve',required=True)
    curves.add_argument('--top',type=float,required=True);curves.add_argument('--base',type=float,required=True)
    curves.add_argument('--level',type=int,help='0 = every sample (exact); 1 to 17 = blocks of up to 2^level samples');curves.add_argument('--rows',type=int,help='Instead of --level: at most this many rows (1 to 2048)')
    curves.add_argument('--max-pages',type=int,default=64);curves.add_argument('--output',type=Path,help='Write the window as JSON to this new file')
    sources=project(sub.add_parser('sources',help='Your upstream source selections: list them, describe one (costs one full read), or read its rows'))
    sources.add_argument('action',choices=['list','describe','read'])
    sources.add_argument('id',nargs='?',help='describe/read: the selection id from `sources list`')
    sources.add_argument('--original',action='store_true',help='read: every source column as given, not the mapped view')
    sources.add_argument('--expect-revision',help='describe/read: refuse (exit 4, nothing written) unless this is the revision returned')
    sources.add_argument('--out',type=Path,help='read: write the rows to this .csv or .json file instead of standard output. The file is your own copy: it is not shared, kept up to date or checked again')
    sources.add_argument('--force',action='store_true',help='read --out: replace an existing file')
    sources.add_argument('--require-all-columns',action='store_true',help='read: refuse (nothing written) when a column of the table is not read')
    orgs=project(sub.add_parser('org-connections',help="Your organisation's database connections that you use or administer, with your own readiness"))
    orgs.add_argument('action',choices=['list']);orgs.add_argument('--organization',required=True,help='The organisation id')
    # E94: how a result was made, what changed, what depends on it, and making it again
    story=project(sub.add_parser('story',help='How an exact result version was made: its inputs and their inputs, a page at a time'))
    story.add_argument('asset');story.add_argument('revision');story.add_argument('--cursor',help='The next_cursor of the previous page')
    changed=project(sub.add_parser('what-changed',help='What differs in how two exact result versions were made'))
    changed.add_argument('asset');changed.add_argument('revision',help='The newer version');changed.add_argument('since',help='The version to compare it with')
    changed.add_argument('--since-asset',help='When the other version belongs to another result')
    depends=project(sub.add_parser('dependents',help='The results made from an exact version you may read'))
    depends.add_argument('asset');depends.add_argument('revision');depends.add_argument('--cursor')
    remake=project(sub.add_parser('remake',help='Make an exact result version again and compare; nothing is saved without --save'))
    remake.add_argument('asset');remake.add_argument('revision')
    remake.add_argument('--newer',action='store_true',help='Use the newest version of each input instead of the recorded ones')
    remake.add_argument('--command-id',help='Run (and save) once: the same id answers the same result. Needed with --save')
    remake.add_argument('--save',action='store_true',help='Save each output that differs (needs --command-id and --target)')
    remake.add_argument('--target',choices=['new-result','new-version'],help='--save: a new result only you can read, or a new version that its readers are told about')
    imports=project(sub.add_parser('well-imports',help='Import a copy of an approved well table as wells: list, status ID, start (--dry-run to preview), resume ID, cancel ID'))
    imports.add_argument('action',choices=['list','status','start','resume','cancel'])
    imports.add_argument('id',nargs='?',help='status/resume/cancel: the import id from `well-imports list`')
    imports.add_argument('--connection',help='start: the approved database connection')
    imports.add_argument('--table',help='start: the table on that connection')
    imports.add_argument('--mapping',type=Path,help='start: a JSON file holding the mapping (fields, crs, schema_digest), as the workspace saves it')
    imports.add_argument('--audience',action='append',default=[],metavar='PERSON',help='start: a project member who may read the copy and the wells it creates (repeat); you are always included')
    imports.add_argument('--command-id',help='start: the same id returns the same import instead of starting another')
    imports.add_argument('--dry-run',action='store_true',help='start: show what the import would do; nothing is kept')
    upload=project(sub.add_parser('upload',help='Upload a file, a folder, a .zip or an https address: every file it can read is added, and one report says what became of each'))
    upload.add_argument('path',help='The file, folder or .zip file, or an https:// address the deployment fetches')
    upload.add_argument('--project',dest='upload_project',help='The project (default: the configuration\'s)')
    upload.add_argument('--attribution',required=True,help='Where these files come from (shown with every file)')
    upload.add_argument('--audience',action='append',default=[],metavar='PERSON',help='A project member who may later be given access (repeat); the files start private')
    upload.add_argument('--well-notes',default='',help='Well context notes kept with every file')
    upload.add_argument('--rights-confirmed',action='store_true',help='I have permission to retain these files, derive results and share within this audience')
    upload.add_argument('--declare',action='append',default=[],metavar='KIND:KEY=VALUE',help='Say what the values of that kind\'s files mean (repeat); other kinds are not touched')
    upload.add_argument('--skip-decisions',action='store_true',help='Skip every file that still needs a decision')
    upload.add_argument('--associate-matches',action='store_true',help='Link each file to the one wellbore whose name its header names')
    upload.add_argument('--report',type=Path,help='Write the report to this .csv (or .json) file')
    upload.add_argument('--new',action='store_true',help='Start another upload instead of continuing the unfinished upload of this folder')
    init=sub.add_parser('init',help='Start an application from a packaged template (map-application, derive-and-publish, sync-worker, notebook, agent-workflow)')
    init.add_argument('template',nargs='?',help='The template name; omit with --list');init.add_argument('--output',type=Path,help='An empty or new folder (default: ./TEMPLATE)')
    init.add_argument('--list',action='store_true',help='List the packaged templates')
    # E70a: check, get and send from a folder that remembers what it holds (ophiolite.exchange)
    def held(p):
        project(p).add_argument('--work',type=Path,default=Path('.ophiolite-held'),help='The folder that remembers what you hold (default .ophiolite-held)')
        return p
    held(sub.add_parser('check',help='Say what is newer than what you hold, what is new and what you can no longer see'))
    get=held(sub.add_parser('get',help='Get the latest version of an item into a new or held folder; you then hold it'))
    get.add_argument('--item',required=True,help='The item id from ophiolite list');get.add_argument('--output',type=Path,required=True,help='Where to save it')
    get.add_argument('--curve',action='append',help='A well log: a curve to receive (repeat)')
    send=held(sub.add_parser('send',help='Send a file as a new item, or as the next version of one you hold; it is private until you share it'))
    send.add_argument('file',type=Path,help='The file to send')
    send.add_argument('--profile',required=True,choices=['las2/1','points-csv/1','mesh-text/1','esri-ascii-grid/1','well-tops-csv/1','deviation-csv/1','opendtect-faultsticks/1'])
    send.add_argument('--name',required=True);send.add_argument('--how',required=True,help='How you made it, in up to 80 characters')
    send.add_argument('--based-on',dest='based_on',action='append',required=True,metavar='ID',help='An item you hold that it is based on (repeat, 1-32)')
    send.add_argument('--of',help='An item you hold and wrote: send this as its next version')
    send.add_argument('--declare',action='append',default=[],metavar='KEY=VALUE',help='A declaration such as crs=EPSG:28992 (repeat)')
    # E96: checks against a reference (`check` above is E70a's exchange command and stays)
    checks=sub.add_parser('checks',help='Checks against a reference: publish, list, compare a result with a file, and who may publish')
    verbs=checks.add_subparsers(dest='action',required=True)
    verb=lambda name,help:project(verbs.add_parser(name,help=help,parents=[common]))
    cp=verb('publish','Publish the check records in a folder (as `python -m conformance.checks produce` writes them); administrators and granted publishers')
    cp.add_argument('folder',type=Path,help='A check folder (check.json, fixture.*, reference.*, output.json, request.json) or a folder of them')
    cl=verb('list','The checks of an exact result version, with your comparisons with files, or of an implementation')
    cl.add_argument('--asset');cl.add_argument('--revision')
    cl.add_argument('--implementation',help='An implementation id, such as ophiolite.shale-volume');cl.add_argument('--version',help='Its version, such as 1')
    cl.add_argument('--earlier',action='store_true',help='Also list earlier checks of the same data, newest first')
    cc=verb('compare','Compare an exact result version with a file you trust; saved on this result for you only')
    cc.add_argument('--asset',required=True);cc.add_argument('--revision',required=True);cc.add_argument('--file',type=Path,required=True,help='A well log (LAS) or a grid file')
    cc.add_argument('--curve',help='The curve to compare, when the file has more than one')
    cc.add_argument('--tolerance',type=float,help='The allowed difference in the compared unit (default: exactly equal)')
    cc.add_argument('--relative',action='store_true',help='--tolerance is a fraction of each value instead')
    cc.add_argument('--unit',help='The unit of --tolerance, when the file does not say it')
    cc.add_argument('--interpretation',type=Path,help='A grid: a .json with the confirmed crs, horizontal_unit, value_unit, value_meaning, direction and vertical_datum')
    cc.add_argument('--command-id',help='The same id answers the same comparison')
    pub=verbs.add_parser('publishers',help='Who may publish checks besides the project administrators (administrators only)')
    pv=pub.add_subparsers(dest='change',required=True)
    for name,help in (('list','List who may publish checks'),('add','Let a person or a workload publish checks'),('remove','Stop a person or a workload publishing checks')):
        one=project(pv.add_parser(name,help=help,parents=[common]))
        if name!='list':
            one.add_argument('principal',help='The member id, or a workload client id with --workload')
            one.add_argument('--workload',action='store_true',help='The principal is a workload client id')
    skills=sub.add_parser('skills',help='Locate packaged SDK guidance')
    skills.add_subparsers(dest='action',required=True).add_parser('path')
    return parser


def _discover(args):
    """E27: projects/orgs for a credential file or OPHIOLITE_ACCESS_KEY; plain words unless --json."""
    from .account import Account
    from .errors import OphioliteError
    _load()
    try:
        notes=()
        if args.credential is not None:credential=Credential.from_file(args.credential)
        elif (given:=supplied_key(args)) is not None:
            credential,notes=Credential.bearer(given[0]),given[1];tell(notes)
        else:raise Refused('Give --credential FILE, --key-file FILE, --key-stdin or set OPHIOLITE_ACCESS_KEY.')
        if args.command=='projects' and not 1<=args.limit<=100:raise Refused('--limit is 1 to 100.')
        with Account(args.url,credential) as account:
            rows=account.projects(limit=args.limit) if args.command=='projects' else account.organizations()
    except OphioliteError:
        raise
    if args.json:return done(args,None,{'projects' if args.command=='projects' else 'organizations':rows,**({'normalised':list(notes)} if notes else {})})
    if not rows:print('This credential reaches no project.' if args.command=='projects' else 'No organisation holds a project this credential reaches.');return
    for row in rows:
        if args.command=='projects':print((row.get('name') or 'Unnamed project')+' - '+{'member':'can edit','viewer':'can view'}.get(row.get('role'),'access')+(' and administer' if row.get('can_administer') else ''))
        else:print(row.get('name') or 'Unnamed organisation')


def _doctor(args):
    """Offline: configuration, Python and the local contracts. --online (E51a): the six stages of doctor.run, stopping
    at the first failure; the report keeps E31's server_contracts, reach, reach_ok and credential_expires."""
    from . import doctor
    from .errors import OphioliteError
    if args.url:
        if not args.online or not args.project:raise Refused('--url needs --online and --project.')
        config={'url':args.url,'project':args.project}
    else:config=configuration(args.configuration)
    path=args.credentials or credentials_path(config)
    registry=json.loads(files('ophiolite').joinpath('contracts/registry.json').read_text())
    report={'configuration':'valid' if not args.url else 'not used (--url)','python':sys.version.split()[0],'local_contracts':registry['version']}
    lines=['Configuration valid. Execution, if you choose it, stays on your computer.' if not args.url else 'Checking '+config['url']+' for project '+config['project']+'.',
           'Python: '+report['python'],'Local contracts: '+report['local_contracts'],
           'Run ophiolite status to check current grant/scopes. Use login --write only for advanced publication.']
    if not args.online:return done(args,'\n'.join(lines),report)
    named=getattr(args,'key',None) is not None or getattr(args,'key_file',None) is not None or getattr(args,'key_stdin',False)
    given=supplied_key(args) if named or not (path.exists() or path.is_symlink()) else None
    credential,notes=None,()
    if given:credential,notes=Credential.bearer(given[0]),given[1]
    elif path.exists() or path.is_symlink():credential=Credential.from_file(path)
    result=doctor.run(config['url'],config['project'],credential,notes=notes)
    result.update({k:v for k,v in report.items()})
    result.setdefault('reach','no - not checked');result.setdefault('reach_ok',False)
    from .credential_input import notice
    lines+=(['Server contracts: '+result['server_contracts']] if 'server_contracts' in result else [])
    for stage in result['stages']:
        lines.append('Stage %s: %s - %s' % (stage['stage'],'ok' if stage['ok'] else 'FAILED',stage['detail'])+(' (warning: %s)' % stage['warning'] if stage.get('warning') else ''))
        if not stage['ok'] and stage.get('remedy'):lines.append('  What to do: '+stage['remedy'])
    lines+=['Reach: '+result['reach'],'Credential expires: '+str(result.get('expires') or result.get('credential_expires') or 'not recorded')]
    if notice(notes):lines.append(notice(notes))
    return done(args,'\n'.join(lines),result)


def _dry_run(args,config):
    """E31: what a write would send, printed; no credential is read, nothing is sent and no file is written."""
    if args.command=='share':
        plan={'dry_run':True,'operation':'share','project':config['project'],'asset_id':args.asset,'read':args.read or [],'reuse':args.reuse or [],
              'whole_project':args.project,'note':'A real share first reads the current recipients (for expected_generation), then replaces them with these.'}
        return done(args,'Would share %s: readers %s; reuse %s%s. Nothing was sent.' % (args.asset,', '.join(args.read or []) or 'none',', '.join(args.reuse or []) or 'none',WHOLE.get(args.project,'')),plan)
    from .writers import WrittenOriginal
    from . import publish as planning
    parents=[tuple(p.split(':',1)) for p in args.parents]
    if any(len(p)!=2 or not all(p) for p in parents):raise Refused('Name each parent as ASSET:REVISION.')
    declared=dict(d.split('=',1) for d in args.declare if '=' in d)
    if len(declared)!=len(args.declare):raise Refused('Give each declaration as KEY=VALUE.')
    method={'name':args.method,'library':args.library,'version':args.library_version,'parameters':json.loads(args.parameters.read_text()) if args.parameters else {}}
    if not (args.library or args.library_version):method['declared']=False
    written=WrittenOriginal(args.file.read_bytes(),args.profile,declared,args.file.name)
    body,_=planning.derive_request(config['project'],written,name=args.name,from_=parents,method=method,command_id=args.command_id or 'chosen-by-the-work-folder',
                                    new_version_of=args.new_version_of,expected_parent=args.expected_parent)
    plan={'dry_run':True,'operation':'publications/derive','project':config['project'],'header':body,'bytes':len(written.bytes),'sha256':hashlib.sha256(written.bytes).hexdigest()}
    return done(args,'Would publish %s (%d bytes, %s) from %d parent(s). Nothing was sent.' % (args.name,len(written.bytes),args.profile,len(parents)),plan)


def changed_lines(c,pad=''):
    """E94: a what-changed answer in words (b is the newer version, a the one it is compared with)."""
    if c.get('sentence'):return [pad+c['sentence']]
    out=[]
    if c['settings']:out.append(pad+'Settings: '+'; '.join('%s %s%s, was %s%s' % (s['label'],s['b'],' '+s['unit'] if s.get('unit') else '',s['a'],' '+s['unit'] if s.get('unit') else '') for s in c['settings'])+'.')
    if c['inputs_same']:out.append(pad+'Inputs: the same.')
    for i in c['inputs']:
        if i.get('restricted'):out.append(pad+'An input you cannot open differs.');continue
        if i.get('sentence'):out.append(pad+'Input %s: %s' % (i.get('slot') or '',i['sentence']));continue
        version=lambda v:'version %s' % v['version'] if v and v.get('version') else 'not used'
        out.append(pad+'Input %s: %s, was %s.' % (i.get('slot') or '',version(i.get('b')),version(i.get('a'))))
        if i.get('change'):out.extend(changed_lines(i['change'],pad+'  '))
    for key,label in (('calculation','Calculation'),('release','Ophiolite release')):
        pair=c[key];out.append(pad+('%s: the same.' % label if pair['same'] else '%s: %s, was %s.' % (label,pair['b'],pair['a'])))
    return out


def _remake(args,client):
    """E94: preview the exact inputs, run once, show what differs; save only with --save, --target and --command-id."""
    if args.save and not (args.command_id and args.target):raise Refused('--save needs --command-id and --target (new-result or new-version).')
    if args.target and not args.save:raise Refused('--target is for --save.')
    if args.command_id and len(args.command_id)>48:raise Refused('--command-id is at most 48 characters.')
    preview=client.remake(args.asset,args.revision,step='preview',inputs='newer' if args.newer else 'recorded')
    inputs=[{'slot':i['slot'],'asset_id':i['asset_id'],'revision':i['revision']} for i in preview['inputs']]
    command=args.command_id or 'cli-'+uuid.uuid4().hex[:24]
    receipt=client.remake(args.asset,args.revision,step='run',inputs=inputs,command_id=command)
    status=client.remake(args.asset,args.revision,step='status',execution_id=receipt['execution_id'])
    out=['%s: %s' % (o['label'],{'equal':'the same','different':'different','saved':'saved','discarded':'discarded','expired':'no longer kept'}[o['outcome']]) for o in status['outcomes']]
    for held in status.get('held') or []:
        if held.get('summary'):out.append('  %s: %s' % (held['label'],held['summary']['reason']))
    if status.get('failure'):out.append(status['failure']['sentence'])
    payload={'preview':preview,'status':status,'saves':[]}
    different=[o for o in status['outcomes'] if o['outcome']=='different']
    if not args.save:
        if different:out.append('Nothing was saved. It is kept for you until %s; to save it run again with --save --target new-result (or new-version) and --command-id %s.' % (status.get('expires_at') or 'it expires',command))
        else:out.append('Nothing was saved.')
        return done(args,'\n'.join(out),payload)
    held={h['role']:h for h in status.get('held') or []}
    outputs=[{'role':o['role'],'target':args.target,'command_id':'%s-%d' % (command,n),
              **({'audience_digest':held[o['role']]['audience']['digest']} if args.target=='new-version' and (held.get(o['role']) or {}).get('audience') else {})}
             for n,o in enumerate(different)]
    if not outputs:out.append('Nothing differs, so nothing was saved.');return done(args,'\n'.join(out),payload)
    saved=client.remake_save(receipt['execution_id'],outputs)
    payload['saves']=saved['saves']
    for one in saved['saves']:
        told=', '.join(one['notified']) or 'nobody'
        out.append('Saved %s as %s (version %s); told: %s.' % (one['role'],'a new result only you can read' if one['target']=='new-result' else 'a new version',one.get('revision_number'),told))
    return done(args,'\n'.join(out),payload)


def _names(client):
    """{member id: name} for the words; empty when the members cannot be read (the words then say "a project member")."""
    try:return dict(((client.members() or {}).get('display') or {}).get('member_names') or {})
    except OphioliteError:return {}


def _checks(args,client):
    """E96: checks publish | list | compare | publishers, each with its documented --json shape."""
    from . import checks as told
    if args.action=='publish':
        stored=[client.check_publish(folder) for folder in told.folders(args.folder)]
        return done(args,told.published_line(stored),{'published':stored})
    if args.action=='list':
        if (args.asset is None)!=(args.revision is None):raise Refused('Give --asset and --revision together.')
        if bool(args.asset)==bool(args.implementation):raise Refused('Name a result (--asset and --revision) or an --implementation and its --version.')
        if args.implementation and not args.version:raise Refused('Give the --version of the implementation.')
        answer=client.check_list(asset=args.asset,revision=args.revision,implementation=args.implementation,version=args.version)
        return done(args,'\n'.join(told.list_lines(answer,_names(client),earlier=args.earlier)),answer)
    if args.action=='compare':
        raw=args.file.read_bytes()
        curve=args.curve
        if curve is None and args.interpretation is None:
            curves=told.las_curves(raw)
            if len(curves)>1:raise Refused('This file has %d curves. Choose the one to compare with --curve.' % len(curves))
            if curves:curve=curves[0][0]
        interpretation=json.loads(args.interpretation.read_text()) if args.interpretation else None
        tolerance=None
        if args.relative and args.tolerance is None:raise Refused('--relative needs --tolerance.')
        if args.tolerance is not None:
            tolerance={'kind':'relative','value':args.tolerance} if args.relative else ({'kind':'absolute','value':args.tolerance,'unit':args.unit} if args.unit else args.tolerance)
        found=client.check_compare(args.asset,args.revision,raw,curve=curve,tolerance=tolerance,interpretation=interpretation,file_name=args.file.name,command_id=args.command_id)
        return done(args,'\n'.join(told.compare_lines(found,curve,unit=dict(told.las_curves(raw)).get(curve) or (interpretation or {}).get('value_unit'))),found)
    names=_names(client)
    if args.change=='list':
        answer=client.check_publishers('list')
        text='\n'.join(told.publisher_line(e,names) for e in answer['publishers']) or 'Only the project administrators can publish checks for this project.'
        return done(args,text,answer)
    kind='workload' if args.workload else 'person'
    answer=client.check_publishers('grant' if args.change=='add' else 'revoke',args.principal,kind=kind)
    return done(args,told.publisher_line({'principal':args.principal},names,'can' if args.change=='add' else 'can no longer'),answer)


def _curves(args,client):
    """E100a: ophiolite curves window; --json prints the same document as CurveWindow.to_dict()."""
    if args.output is not None and (args.output.exists() or args.output.is_symlink()):raise Refused('The output file already exists; choose a new file.')
    window=client.curve_window(args.asset,args.revision,args.curve,args.top,args.base,level=args.level,rows=args.rows,max_pages=args.max_pages)
    document=window.to_dict()
    if args.output is not None:
        with open(args.output,'x') as out:out.write(json.dumps(document,indent=2)+'\n')
    what='%d samples (exact)' % len(window) if window.exact else '%d blocks at level %d (for display; read the exact curve for analysis)' % (len(window),window.level)
    return done(args,'%s %s..%s %s: %s in %d page%s%s' % (args.curve,args.top,args.base,window.depth_unit or 'depth unit unknown',what,window.pages,'' if window.pages==1 else 's',
                                                        ' - written to %s' % args.output if args.output else ''),document)


def _journey(args,client):
    """E31: entities, wells, changes and sources, each with its documented --json shape."""
    if args.command=='entities':
        rows=[{'entity_id':e.entity_id,'kind':e.kind,'name':e.name} for e in client.entities(kind=args.kind)]
        return done(args,'\n'.join('%s %s' % (r['kind'],r['name']) for r in rows) or 'No well or wellbore you may read.',{'entities':rows})
    if args.command=='wells':
        if args.action=='extent':
            extent=client.extent(**({'crs':args.crs} if args.crs else {}))
            return done(args,('%d wells in %s: %s' % (extent['count'],extent['crs'],extent['bbox'])) if extent['bbox'] else 'No well you may read is located.',{'extent':extent})
        bbox=[float(v) for v in args.bbox.split(',')] if args.bbox else None
        if bbox is not None and len(bbox)!=4:raise Refused('Give --bbox as minx,miny,maxx,maxy.')
        if args.column and not args.with_source:raise Refused('Give --column with --with-source.')
        wells=client.wells(bbox=bbox,bbox_crs=args.bbox_crs,crs=args.crs,limit=args.limit)
        rows=[{'entity_id':w.entity_id,'name':w.name,'location':w.location} for w in wells]
        if not args.with_source:
            return done(args,'\n'.join(repr(w) for w in wells) or 'No well you may read.',{'wells':rows,'crs':wells.crs,'untransformed':wells.untransformed})
        # E50c: one mark per well, in the order listed; `row` holds the original columns asked for (null unless joined)
        frame=wells.with_source(columns=args.column);import pandas as pd
        names=[c for c in frame.columns if c.startswith('source.')]
        for row,(_,joined) in zip(rows,frame.iterrows()):
            state,reason=joined['source_state'],joined['source_reason']
            row['source']={'state':state,'reason':None if pd.isna(reason) else str(reason),
                           'row':{n[len('source.'):]:joined[n] for n in names} if state=='joined' else None}
        text='\n'.join('%r: %s%s' % (w,r['source']['state'],' ('+r['source']['reason']+')' if r['source']['reason'] else '') for w,r in zip(wells,rows))
        return done(args,text or 'No well you may read.',{'wells':rows,'crs':wells.crs,'untransformed':wells.untransformed})
    if args.command in ('story','dependents'):
        from . import story as told
        page=(client.story if args.command=='story' else client.dependents)(args.asset,args.revision,cursor=args.cursor)
        return done(args,'\n'.join(told.lines(page)),page)
    if args.command=='what-changed':
        answer=client.what_changed((args.since_asset or args.asset,args.since),(args.asset,args.revision))
        return done(args,'\n'.join(changed_lines(answer)),answer)
    if args.command=='remake':return _remake(args,client)
    if args.command=='sources':
        return _sources(args,client)
    if args.command=='org-connections':  # E39: projectless; no sign-in or password is ever answered
        rows=client.org_connections(args.organization)
        return done(args,'\n'.join('%s  %s: %s' % (r['id'],r['name'],(r.get('readiness') or {}).get('code') or ('ready' if r['you']['use'] else 'administered')) for r in rows)
                    or 'No organisation connection you use or administer.',{'organization_id':args.organization,'connections':rows})
    if args.command=='well-imports':
        return _well_imports(args,client)
    sync=client.sync()
    if args.action=='head':
        head=sync.head()
        return done(args,'Epoch %s, cursor %d' % (head['epoch'],head['cursor']),{'head':head})
    if (args.epoch is None)!=(args.after is None):raise Refused('Give --epoch and --after together (or neither, to start from the head).')
    if args.action=='list':
        epoch,after=(args.epoch,args.after) if args.epoch is not None else (lambda h:(h['epoch'],h['cursor']))(sync.head())
        events=[e for page in sync.changes(epoch,after) for e in page['changes']]
        return done(args,'\n'.join('%s %s %s' % (e['cursor'],e['kind'],e.get('subject_id') or '') for e in events) or 'No change after this cursor.',{'changes':events})
    for event in sync.follow(epoch=args.epoch,after=args.after,seconds=args.seconds,reconnect=False):  # follow: one line per event
        print(json.dumps(event) if args.json else '%s %s %s' % (event['cursor'],event['kind'],event.get('subject_id') or ''),flush=True)
    return None


def _sources(args,client):
    """E50a: sources list | describe ID | read ID (--original, --expect-revision, --out FILE [--force])."""
    if args.action=='list':
        if args.id or args.original or args.expect_revision or args.out or args.force or args.require_all_columns:raise Refused('sources list takes no id or read options.')
        from .models.api import SourceSelectionsPage
        from .sources import _checked
        rows=_checked(SourceSelectionsPage,client._post('sources','list',{}),'source listing')['selections']
        return done(args,'\n'.join('%s  %s (%s): %s' % (r['id'],r['name'],r['profile'],r['state']) for r in rows) or 'No source selection of yours in this project.',{'selections':rows})
    if not args.id:raise Refused('Give the selection id: ophiolite sources %s ID (see `ophiolite sources list`).' % args.action)
    if args.action=='describe':
        if args.original or args.out or args.force or args.require_all_columns:raise Refused('describe takes only --expect-revision.')
        with warnings.catch_warnings():  # the coverage sentence below says it once
            warnings.simplefilter('ignore',UserWarning)
            described=client.source(args.id).describe(args.expect_revision).to_dict()
        text='%s: %d rows, %d columns (%s), %s, revision %s' % (described['name'],described['row_count'],len(described['columns']),
              ', '.join(c['name'] for c in described['columns']),described['crs'],described['revision'])
        if 'coverage' in described:text+='\n'+described['coverage']
        return done(args,text,{'source':described})
    out=args.out
    if out is not None:
        if out.suffix.lower() not in ('.csv','.json'):raise Refused('Write --out to a .csv or .json file.')
        if out.exists() and not args.force:raise Refused('%s exists; add --force to replace it.' % out)
    elif args.force:raise Refused('--force is for --out.')
    with warnings.catch_warnings(record=True) as said:  # E50b1: a partial read's line goes to standard error, never into the rows
        warnings.simplefilter('always',UserWarning)
        snapshot=client.source(args.id).read(args.expect_revision,require_all_columns=args.require_all_columns)
    for warning in said:sys.stderr.write(str(warning.message)+'\n')
    columns=snapshot.columns if args.original else snapshot.mapped_columns()
    rows=snapshot.records(original=args.original)
    about={'id':snapshot.id,'name':snapshot.name,'profile':snapshot.profile,'revision':snapshot.revision,'sha256':snapshot.sha256,'crs':snapshot.crs,
           'original':bool(args.original),'columns':columns,'row_count':len(rows)}
    if out is None:
        if args.json:return done(args,None,{'source':about,'rows':rows})
        sys.stdout.write(_csv(columns,rows));return {'source':about,'rows':rows}
    _write_atomic(out,_csv(columns,rows) if out.suffix.lower()=='.csv' else json.dumps({'source':about,'rows':rows},indent=2,default=str)+'\n',args.force)
    return done(args,'Wrote %d rows of %s (revision %s, %s) to %s. This copy is yours; it is not shared or kept up to date.' % (len(rows),snapshot.name,snapshot.revision,snapshot.crs,out),
                {'source':about,'out':str(out)})


def _counted(counts):
    return '%d added, %d already here, %d skipped' % (counts['created'],counts['already_here'],counts['skipped'])


def _rows(title,rows,total,said):
    if not rows:return []
    lines=[title]+['  %s: %s' % (r['row_key'] or 'row %d (no identifier)' % r['ordinal'],said(r)) for r in rows]
    return lines+(['  and %d more' % (total-len(rows))] if total>len(rows) else [])


def _reviewed(review):
    """E42a: a dry run in words: what a start would do; nothing was kept."""
    from .well_imports import words
    c=review['counts']
    lines=['Dry run, nothing was kept. %s (%s): %d rows; %d would be added, %d already here, %d skipped, %d possible duplicates.' % (
        review['source_name'],review['key'],c['rows'],c['create'],c['already_here'],c['skipped'],c['possible_duplicates'])]
    return '\n'.join(lines+_rows('Rows that would be skipped:',review['skipped'],c['skipped'],words))


def _result(answer):
    """E42a: an import in words: its state, what it did, every listed skipped row and every well located otherwise."""
    from .well_imports import FINAL,words
    lines=['%s: %s.' % (answer['words'],_counted(answer['counts']))]
    if answer['reason'] and answer['state'] not in FINAL:lines.append(answer['reason'])
    lines+=_rows('Skipped rows:',answer['skipped'],answer['counts']['skipped'],words)
    lines+=_rows('Located by other evidence:',answer['superseded'],len(answer['superseded']),lambda r:r['reason'])
    return '\n'.join(lines)


def _declarations(given):
    """--declare KIND:KEY=VALUE (repeat) as {kind: {key: value}}."""
    out={}
    for text in given:
        kind,_,pair=text.partition(':');key,eq,value=pair.partition('=')
        if not (kind and key and eq):raise Refused('Give each declaration as KIND:KEY=VALUE, for example esri-ascii-grid/1:crs=EPSG:28992.')
        out.setdefault(kind,{})[key]=value
    return out


def _upload(args,client):
    """E55: upload a folder or a .zip; exit 0 when every file is added or already here, 4 when any is not (the report
    is still written), 1 on a refusal before anything was sent."""
    if not args.rights_confirmed:raise Refused('Confirm with --rights-confirmed that you may retain these files, derive results and share them within the audience.')
    runs=client.upload_runs
    def progress(report):
        if not args.json:print('Adding files... %d of %d.' % (sum(v for k,v in report.counts.items() if k!='not-sent'),report.view['files']),file=sys.stderr,flush=True)
    from .upload_runs import is_address
    report=runs.upload(args.path if is_address(args.path) else Path(args.path),attribution=args.attribution,audience=args.audience,rights_confirmed=True,well_notes=args.well_notes,
                       declare=_declarations(args.declare),skip_decisions=args.skip_decisions,associate_matches=args.associate_matches,new=args.new,progress=progress)
    if args.report:report.save(args.report)
    done(args,report.text()+('\nReport written to %s' % args.report if args.report else ''),{'upload':report.view})
    report.exit_code=0 if report.ok else EXIT['conflict']
    return report


def _well_imports(args,client):
    """E42a: well-imports list | status ID | start [--dry-run] | resume ID | cancel ID. A start prints its id before the
    first step, so an interrupted import is resumed from any process; a paused import exits 4 with its reason."""
    from .errors import IntegrityConflict
    from .well_imports import PAUSED
    imports=client.well_imports()
    if args.action!='start' and (args.connection or args.table or args.mapping or args.audience or args.command_id or args.dry_run):
        raise Refused('Only start takes --connection, --table, --mapping, --audience, --command-id or --dry-run.')
    if args.action=='list':
        if args.id:raise Refused('well-imports list takes no id.')
        rows=imports.list()
        return done(args,'\n'.join('%s  %s: %s (%s)' % (r['id'],r['key'],r['words'],_counted(r['counts'])) for r in rows) or 'No well import in this project.',{'imports':rows})
    if args.action=='start':
        if args.id:raise Refused('start takes no id; continue an import with: ophiolite well-imports resume ID')
        if not (args.connection and args.table and args.mapping):raise Refused('Give --connection, --table and --mapping FILE.')
        try:mapping=json.loads(args.mapping.read_text())
        except (OSError,ValueError):raise Refused('%s is not a readable JSON mapping.' % args.mapping) from None
        review=imports.preview(args.connection,args.table,mapping)
        if args.dry_run:return done(args,_reviewed(review),{'preview':review})
        started=imports.start(args.connection,args.table,mapping,preview_digest=review['preview_digest'],audience=args.audience,command_id=args.command_id)
        if not args.json:print('Import %s started. If it stops, continue with: ophiolite well-imports resume %s' % (started['id'],started['id']),flush=True)
        ident=started['id']
    else:
        if not args.id:raise Refused('Give the import id: ophiolite well-imports %s ID (see `ophiolite well-imports list`).' % args.action)
        ident=args.id
        if args.action=='status':
            answer=imports.status(ident);return done(args,_result(answer),{'import':answer})
        if args.action=='cancel':
            answer=imports.cancel(ident);return done(args,_result(answer),{'import':answer})
    answer=imports.run(ident)
    if answer['state'] in PAUSED:
        raise IntegrityConflict('%s: %s Continue with: ophiolite well-imports resume %s' % (answer['words'],answer['reason'] or '',ident))
    return done(args,_result(answer),{'import':answer})


def _exchange(args,client):
    """E70a: one closed outcome; its sentence for people, {outcome, sentence, facts, technical} with --json. A refusal
    raises with its own sentence and exit code (cli.exit_code)."""
    exchange=client.exchange(args.work)
    if args.command=='check':result=exchange.check()
    elif args.command=='get':result=exchange.get(args.item,output=args.output,**({'curves':args.curve} if args.curve else {}))
    else:
        declared=dict(d.split('=',1) for d in args.declare if '=' in d)
        if len(declared)!=len(args.declare):exchange._raise('not-valid',{'reasons':'give each declaration as KEY=VALUE'})
        result=exchange.send(args.file,name=args.name,profile=args.profile,how=args.how,based_on=args.based_on,of=args.of,declare=declared or None)
    done(args,result.sentence,result.to_dict())
    return result


def _csv(columns,rows):
    import csv,io
    stream=io.StringIO();writer=csv.writer(stream,lineterminator='\n');writer.writerow(columns)
    for row in rows:writer.writerow(['' if row.get(c) is None else row.get(c) for c in columns])
    return stream.getvalue()


def _write_atomic(path,text,force):
    """Write beside the target and move it into place; never a half-written file, never an overwrite without --force."""
    import os,tempfile
    path=Path(path);handle,temporary=tempfile.mkstemp(prefix='.'+path.name+'.',dir=str(path.parent or Path('.')))
    try:
        with os.fdopen(handle,'w',encoding='utf-8',newline='') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        if force:os.replace(temporary,path)
        else:
            try:os.link(temporary,path)
            except FileExistsError:raise Refused('%s exists; add --force to replace it.' % path) from None
            os.unlink(temporary)
    except BaseException:
        try:os.unlink(temporary)
        except FileNotFoundError:pass
        raise


SKIP=('node_modules','dist','__pycache__','.venv')


def templates():
    """The packaged templates: name -> template.json."""
    root=files('ophiolite').joinpath('templates')
    return {d.name:json.loads(d.joinpath('template.json').read_text()) for d in root.iterdir() if d.is_dir() and d.joinpath('template.json').is_file()}


def _copy(source,target):
    target.mkdir(parents=True,exist_ok=True)
    for item in source.iterdir():
        if item.name in SKIP:continue
        if item.is_dir():_copy(item,target/item.name)
        else:(target/item.name).write_bytes(item.read_bytes())


def _init(args):
    """E31: copy a packaged template (and the shared support.py beside it) into a new folder; nothing is sent."""
    available=templates()
    if args.list or not args.template:
        rows=[{'name':name,'template_version':meta['template_version'],'test_command':meta['test_command']} for name,meta in sorted(available.items())]
        return done(args,'\n'.join('%s (template %s)' % (r['name'],r['template_version']) for r in rows),{'templates':rows})
    if args.template not in available:raise Refused('Choose a template: '+', '.join(sorted(available)))
    output=(args.output or Path(args.template)).resolve()
    if output.exists() and any(output.iterdir()):raise Refused('Choose a new or empty folder; %s is not empty.' % output)
    root=files('ophiolite').joinpath('templates')
    _copy(root.joinpath(args.template),output/args.template)
    (output/'support.py').write_bytes(root.joinpath('support.py').read_bytes())
    meta=available[args.template]
    return done(args,'Created %s in %s. Next: cd %s, install requirements.lock, then run: %s' % (args.template,output,output/args.template,' '.join(meta['test_command'])),
                {'template':args.template,'path':str(output/args.template),'support':str(output/'support.py'),'test_command':meta['test_command']})


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


def _targets(args):
    """E86: the table types (no name), or one type's fields and declarations; --json prints the document itself."""
    from . import targets
    if args.name is None:
        listed=targets.targets()
        return done(args,'\n'.join(t.target+' - '+t.display_name+(' (waits for '+t.pending.epic+')' if t.pending else '') for t in listed),
                    {'targets':[{'target':t.target,'display_name':t.display_name,'pending':t.pending.epic if t.pending else None} for t in listed]})
    try:one=targets.target(args.name)
    except KeyError as error:
        message=error.args[0]
        if args.json:print(json.dumps({'error':{'code':'unknown-target','message':message}},indent=2))
        else:print(message,file=sys.stderr)
        raise SystemExit(EXIT['usage'])
    lines=[one.display_name+': '+one.description]
    lines+=['  '+f.label+(' (required)' if f.required else '') for f in one.fields]
    lines+=['  '+d.label+(': '+', '.join(v.label for v in d.values) if getattr(d,'values',None) else '') for d in one.declarations]
    lines+=['  Each column: '+', '.join(c.label for c in one.column_rows)] if one.column_rows else []
    return done(args,'\n'.join(lines),targets.document(args.name))


def main(argv=None):
    from . import _client_header
    token=_client_header._NAME.set('ophiolite-cli')  # E93: the command line names itself on every gateway request
    try:return _main(argv)
    finally:_client_header._NAME.reset(token)


def _main(argv=None):
    args=parser().parse_args(argv)
    if args.command in ('projects','orgs'):return _discover(args)
    if args.command=='init':return _init(args)  # E31: offline; copies packaged files only
    if args.command=='skills':
        return done(args,str(files('ophiolite').joinpath('skills')),{'path':str(files('ophiolite').joinpath('skills'))})
    if args.command=='targets':return _targets(args)  # E86: offline; reads the packaged contracts only
    if args.command=='bundle':
        # Offline: no configuration, credentials or network are read.
        from .bundle import open_bundle,pack
        if args.action=='pack':
            if args.archive is None:raise SystemExit('Name the .zip to write: ophiolite bundle pack FOLDER ARCHIVE.zip')
            print('Packed',pack(args.path,args.archive),'- check it with: ophiolite bundle check',args.archive);return
        opened=open_bundle(args.path)
        if args.action=='check':
            return done(args,'Bundle verified: %d exact revisions, %d curves, %d other data. Checksums show integrity, not authorship.' % (len(opened.assets),sum(len(a.curves) for a in opened.assets),sum(a.data is not None for a in opened.assets)),
                        {'verified':True,'revisions':len(opened.assets),'curves':sum(len(a.curves) for a in opened.assets),'other_data':sum(a.data is not None for a in opened.assets)})
        print(json.dumps({**opened.summary(),'items':[{'asset_id':a.asset_id,'revision':a.revision,'name':a.name,'type':a.type,'curves':sorted(a.curves),'history':a.history,'parent_visibility':a.parent_visibility} for a in opened.assets]},indent=2));return
    _load()
    if args.command=='doctor':return _doctor(args)
    config=configuration(args.configuration)
    if getattr(args,'upload_project',None):config={**config,'project':args.upload_project}  # E55: ophiolite upload --project
    path=args.credentials or credentials_path(config)
    if args.command=='run':return _local_run(config,args.work.resolve())
    if getattr(args,'dry_run',False) and args.command!='well-imports':return _dry_run(args,config)  # E31: before any credential, network or file write (E42a: an import's dry run is its server preview, which keeps nothing)
    given=supplied_key(args) if args.command=='login' else None
    if given:
        # E25a: saved for later processes; nothing is sent now and the key is never printed.
        auth.key_login(config['url'],config['project'],given[0],path=path,source=given[2]);tell(given[1])
        print('Project access key saved for',config['project'],'- ophiolite status shows what it is for; remove it on the account page to stop it everywhere.');return
    if args.command=='login':
        def notify(url,message):
            print(message,url,flush=True)
            if not args.no_browser:
                import webbrowser
                webbrowser.open(url)
        return auth.device_login(config['url'],config['project'],path=path,write=args.write,notify=notify)
    given=None if (path.exists() or path.is_symlink()) else supplied_key(SimpleNamespace())
    if given:
        credential=Credential.bearer(given[0]);tell(given[1])  # this process only; nothing is saved
    else:credential=Credential.from_file(path)
    if args.command=='logout':
        if credential.kind=='bearer':print('Nothing saved to remove: the project access key came from OPHIOLITE_ACCESS_KEY.');return
        if credential.kind=='access_key':
            credential.delete();print('Local project access key removed. Remove it from the account page to stop it working everywhere.');return
        credential.revoke();print('Local authorization removed.');return
    if args.command=='status' and credential.kind!='application':
        summary=credential.summary()
        if summary['kind']=='bearer':print('Project access key from OPHIOLITE_ACCESS_KEY for',config['project'],'(not saved)');return
        print('Project access key',repr(summary['label'] or 'unnamed'),'for',summary['project'],'-',summary['scope'] or 'scope not recorded','- expires',summary['expires_at'] or 'date not recorded');return
    with Client(config['url'],config['project'],credential) as client:
        if args.command=='status':
            with credential.snapshot(client.url,client.project) as headers:result=client._grant_status(headers)
            return done(args,' '.join([result['state'],result['project_id'],','.join(result['scopes'])]),{'state':result['state'],'project_id':result['project_id'],'scopes':list(result['scopes'])})
        if args.command=='list':
            items=list(client.assets())
            if args.json:return done(args,None,{'assets':items})
            for item in items:print(json.dumps(item))
            return
        if args.command=='curves':return _curves(args,client)
        if args.command in ('entities','wells','changes','sources','org-connections','well-imports','story','what-changed','dependents','remake'):return _journey(args,client)
        if args.command=='checks':return _checks(args,client)
        if args.command in ('check','get','send'):return _exchange(args,client)
        if args.command=='upload':return _upload(args,client)
        if args.command=='publish-derived':  # E30b
            from .writers import WrittenOriginal
            parents=[tuple(p.split(':',1)) for p in args.parents]
            if any(len(p)!=2 or not all(p) for p in parents):raise Refused('Name each parent as ASSET:REVISION.')
            declared=dict(d.split('=',1) for d in args.declare if '=' in d)
            if len(declared)!=len(args.declare):raise Refused('Give each declaration as KEY=VALUE.')
            method={'name':args.method,'library':args.library,'version':args.library_version,'parameters':json.loads(args.parameters.read_text()) if args.parameters else {}}
            if not (args.library or args.library_version):method['declared']=False
            written=WrittenOriginal(args.file.read_bytes(),args.profile,declared,args.file.name)
            options=dict(name=args.name,from_=parents,method=method,new_version_of=args.new_version_of,expected_parent=args.expected_parent)
            from .publish import WorkFolder
            receipt=WorkFolder(client,args.work).publish_derived(written,**options) if args.work else client.publish_derived(written,command_id=args.command_id,**options)
            return done(args,'Published %s as version %d of %s - it is private until you share it.' % (args.name,receipt.revision_number,receipt.asset_id),
                        {'published':receipt.model_dump(mode='json',by_alias=True)})
        if args.command=='read-data':
            data=client.read_data(args.asset,args.revision)
            if args.output.exists():raise Refused('The output folder already exists; choose a new folder.')
            args.output.mkdir(parents=True)
            (args.output/'original').write_bytes(data.original);(args.output/'data.json').write_bytes(data._wire_data_bytes)
            (args.output/'descriptor.json').write_text(json.dumps(data._wire_descriptor,indent=2)+'\n')
            return done(args,'Saved the exact original, data.json and descriptor.json for %s - units and references are as declared; unknown stays unknown.' % data.type,
                        {'saved':str(args.output),'type':data.type,'files':['original','data.json','descriptor.json']})
        if args.command=='export':
            if len(args.asset)!=len(args.revision):raise Refused('Give one --revision for each --asset, in the same order.')
            opened=client.export([(a,r,args.curve or None) for a,r in zip(args.asset,args.revision)],args.output,groups=not args.no_groups)
            return done(args,'Exported %d exact revision(s) to %s - check it offline with: ophiolite bundle check %s' % (len(opened.assets),args.output,args.output),
                        {'exported':str(args.output),'revisions':len(opened.assets)})
        if args.command=='fetch':
            asset,revision,curve=[getattr(args,k) or config.get(k) for k in ('asset','revision','curve')]
            client.read(asset,revision,[curve]).save(args.output,legacy_order=True)
            return done(args,'Saved exact LAS, curve.json and descriptor.json. No run or publication was created.',{'saved':str(args.output),'files':['LAS','curve.json','descriptor.json']})
        if args.command=='share':
            item=next((item for item in client.assets() if item['asset_id']==args.asset),None)
            if item is None:raise Refused('Asset unavailable to this credential; check the asset ID and your project access')
            # Fetch-and-replace: guarded from this read onwards, and safe to retry after a lost response.
            snapshot=client.grants(item)
            if snapshot.generation is None:raise Refused('This server does not support conditional sharing; upgrade it before changing recipients.')
            result=client.share(item,read=args.read or [],reuse=args.reuse or [],expected_generation=snapshot.generation,project=args.project)
            done(args,' '.join(['Uploaded original' if item.get('authority')=='ophiolite:uploaded' else 'Published result',args.asset,'readers:',', '.join(result.recipients) or 'none','reuse:',', '.join(result.reuse_recipients) or 'none'])+WHOLE.get(getattr(result,'project',None),''),
                 {'shared':args.asset,'recipients':list(result.recipients),'reuse_recipients':list(result.reuse_recipients),'whole_project':getattr(result,'project',None)})
            return result
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


def entrypoint(argv=None):
    """Run the CLI and exit with the documented code: 0 done, 1 refused or invalid, 2 usage, 3 sign-in or permission,
    4 not found or conflict, 5 busy or unavailable. With --json a refusal prints {"error": {...}} on stdout."""
    wants_json='--json' in (sys.argv[1:] if argv is None else argv)
    try:result=main(argv)
    except (ValueError,OSError,KeyError,TypeError,subprocess.CalledProcessError) as error:
        code=exit_code(error) if isinstance(error,ValueError) else EXIT['refused']
        if wants_json:print(json.dumps(error_document(error) if isinstance(error,ValueError) else {'error':{'code':'local-failure','message':'Operation failed. Check configuration, local files and access; retain the run folder to retry.'}},default=str))
        else:print(str(error) if isinstance(error,ValueError) else 'Operation failed. Check configuration, local files and access; retain the run folder to retry.',file=sys.stderr)
        raise SystemExit(code)
    if getattr(result,'exit_code',0):raise SystemExit(result.exit_code)  # E51a: doctor --online exits with its failed stage's code


if __name__=='__main__':entrypoint()
