"""Shared original synthetic fixture and public-SDK recipes for the four templates.

Keep this file when copying a template. It is educational support, never a gateway
or authentication substitute. Real credentials are loaded only in explicit live mode.
"""
import json
import os
from pathlib import Path
import re
import tempfile

from ophiolite import Client, Credential
from ophiolite.errors import ShareOutcomeUnknown, IntegrityConflict, Refused, ValidationFailed
from ophiolite.writers import write_curves
from ophiolite import validate
from ophiolite.testing import WELLS, synthetic_server  # noqa: F401 (E52: moved into the SDK; a downloaded notebook needs no template)

TEMPLATE_VERSION = '0.1.0'


def client_for(url, project='p', *, fixture=False):
    if fixture: credential = Credential.bearer('oph_api_alice')
    else:
        # The SDK owns discovery, private storage, locking and refresh.
        from ophiolite.auth import default_path
        path = os.environ.get('OPHIOLITE_CREDENTIAL') or default_path(url, project)
        if os.environ.get('OPHIOLITE_ACCESS_KEY') and not os.environ.get('OPHIOLITE_CREDENTIAL') and not (os.path.exists(path) or os.path.islink(path)):
            credential = Credential.bearer(os.environ['OPHIOLITE_ACCESS_KEY'])  # H4 (E32 F8): as the README and the command line say
        else:
            credential = Credential.from_file(path)
    return Client(url,project,credential)


def derive(values, factor=2):
    return [None if value is None else value * factor for value in values]


def stage(client, folder, *, mnemonic='CALC', factor=2, asset=None, curve='GR'):
    """Read one exact permitted curve and compute the derived curve locally. Nothing is published yet."""
    asset = asset or next(iter(client.assets()), None)
    if asset is None: raise Refused('No permitted curve is available. Ask the owner to grant access.')
    selected = client.read(asset['asset_id'],asset['revision'],[curve])
    # Explicit local model validation preserves the scientific fields; the SDK read
    # has already verified the original normalized bytes and their exact digest.
    view = selected.curves[0]
    validate.schema(view.model_dump(by_alias=True),'ophiolite.application-curve/1')
    values = derive(view.values,factor)
    method = {'name':'multiply','library':'ophiolite-template','version':TEMPLATE_VERSION,'parameters':{'factor':factor,'curve':curve}}
    state = {'selected':selected,'asset':asset,'work':client.work_folder(folder),'view':view,'values':values,'method':method}
    try: return rename_stage(state, mnemonic)
    except ValidationFailed: return {**state,'mnemonic':mnemonic,'written':None}  # validate_stage names the problem


def validate_stage(state):
    """The derived curve keeps every sample and every missing value of its input."""
    view, values = state['view'], state['values']
    if len(values) != len(view.values) or any((a is None) != (b is None) for a, b in zip(view.values, values)):
        raise ValidationFailed(['The derived curve must keep every sample and every missing value of its input.'])
    if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,15}', state['mnemonic']):
        raise ValidationFailed(['Name the derived curve with 1-16 capital letters, digits or underscores, starting with a letter.'])
    if state['mnemonic'] == view.curve.upper():
        raise ValidationFailed(['Name the derived curve differently from its input curve.'])
    return state['written']


def rename_stage(state, mnemonic):
    """The staged calculation under another curve name (the file is written again; nothing is sent)."""
    view = state['view']
    state['mnemonic'] = mnemonic
    state['written'] = write_curves(view.axis,{mnemonic:(view.unit,state['values'])},depth_unit=view.context.depth_unit,well='TEMPLATE',filename='derived.las')
    return state


def publish_stage(state, *, name='Synthetic curve calculation'):
    """E31 S5: one publication through publications/derive, recoverable from the work folder: a lost answer is
    retried with the same saved command id, so the same file is published once."""
    written = validate_stage(state)
    parent = (state['asset']['asset_id'], state['asset']['revision'])
    return state['work'].publish_derived(written,name=name,from_=[parent],method=state['method'])


def share_after_read(client, receipt, audience):
    before = client.grants(receipt)
    try:
        return {'state':'shared','grants':client.share(receipt,read=audience,expected_generation=before.generation).model_dump(), 'previous':before.model_dump()}
    except (ShareOutcomeUnknown, IntegrityConflict):
        # Observe once; never replay an uncertain sharing write.
        observed = client.grants(receipt)
        return {'state':'inspect-recipients','message':'Read recipients first before deciding whether to share again.', 'grants':observed.model_dump()}


def workflow(client, folder, *, share=None, mnemonic='CALC'):
    """Read, compute and publish; run it again on the same folder after a crash or a lost answer and the saved
    command publishes once."""
    folder = Path(folder)
    state = stage(client,folder,mnemonic=mnemonic)
    done = state['work'].published_derived(state['written'])
    if done is not None: return {'state':'recovered','receipt':done.model_dump(by_alias=True),'work_folder':str(folder)}  # already published: nothing is sent
    receipt = publish_stage(state)
    answer = {'state':'published','receipt':receipt.model_dump(by_alias=True),'work_folder':str(folder)}
    if share is not None: answer['sharing'] = share_after_read(client,receipt,share)
    return answer


def command(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='Read an exact permitted curve and publish a bounded local calculation.')
    parser.add_argument('--fixture',action='store_true');parser.add_argument('--work');parser.add_argument('--share',action='append')
    args=parser.parse_args(argv)
    folder=args.work or str(Path(tempfile.mkdtemp(prefix='ophiolite-template-'))/'work')
    from ophiolite.errors import OphioliteError
    try:
        if args.fixture:
            with synthetic_server() as server, client_for(server.url,fixture=True) as client:
                answer=workflow(client,folder,share=args.share)
        else:
            with client_for(os.environ['OPHIOLITE_URL'],os.environ['OPHIOLITE_PROJECT']) as client:
                answer=workflow(client,folder,share=args.share)
    except OphioliteError as error:
        import sys
        print(guidance(error),file=sys.stderr)
        return 2
    print(json.dumps(answer,indent=2))
    return 0



def interval_offset(client, folder, *, offset=1):
    asset=next(iter(client.assets()))
    data=client.read(asset['asset_id'],asset['revision'],['GR'])
    work=client.work_folder(folder)
    binding=work.configure(asset['asset_id'],asset['revision'],curve='GR',name='Bounded interval correction',publication_profile='curve-edits/1')
    axis=data.curves[0].axis
    return work.correct(binding,start=min(axis),stop=max(axis),offset=offset)


def guidance(error):
    from ophiolite.errors import AuthenticationRequired,PermissionRefused,CapacityExceeded,Busy,IntegrityConflict,VerificationFailed
    if isinstance(error,AuthenticationRequired):return 'Run ophiolite login for this project, then retry the requested action.'
    if isinstance(error,PermissionRefused):return 'Access was refused. Ask the data owner to check your permission.'
    if isinstance(error,CapacityExceeded):return 'This input exceeds the supported size. Select a smaller input.'
    if isinstance(error,Busy):return 'The service is busy. Wait, then choose Retry.'
    if isinstance(error,(IntegrityConflict,VerificationFailed)):return 'The input changed or failed verification. Read the exact version again before continuing.'
    return 'The request needs correction. Review the supplied values and try again.'
