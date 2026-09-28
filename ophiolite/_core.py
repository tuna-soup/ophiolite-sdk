"""Transport-free exact-read verification shared by synchronous and future async drivers."""
import hashlib
import warnings
from urllib.parse import urlsplit
from .errors import Refused
from . import validate
from .errors import InterpretationDiffers, InterpretationChanged, VerificationFailed
from .models.generated import ScientificAsset
from .models import invariants as rules


def verify_descriptor(value, project, asset, revision, curve):
    model=validate.model(ScientificAsset,value); data=model.model_dump(by_alias=True)
    rules.asset(data)
    rules.require((data['project_id'],data['asset_id'],data['revision'])==(project,asset,revision), 'Scientific descriptor does not match the requested exact identity')
    rules.require('type' not in data['scientific'], 'This is not a well log; read it with read_data')
    rules.require(data['scientific']['curve']==curve, 'Requested curve differs from returned data')
    return model


def verify_typed_descriptor(value, project, asset, revision):
    model=validate.model(ScientificAsset,value); data=model.model_dump(by_alias=True)
    rules.asset(data)
    rules.require((data['project_id'],data['asset_id'],data['revision'])==(project,asset,revision), 'Scientific descriptor does not match the requested exact identity')
    rules.require('type' in data['scientific'], 'This is a well log; read its curves with read')
    return model


def typed_result(descriptor, body, artifact):
    """Verify a typed read and build its object; exact served bytes are kept for export."""
    import json
    from .typed import CLASSES
    asset,_=validate.typed_pair(descriptor,body)
    data=asset.model_dump(by_alias=True)
    value=json.loads(body)
    if value['context']['type']=='seismic-volume' and artifact is None:pass  # E16: a volume is read as slices; its original stays on the server
    else:verify_bytes(rules.artifact(data),artifact)
    return CLASSES[value['context']['type']](asset,value,artifact,wire_descriptor=descriptor,wire_data_bytes=body)


def verify_bytes(rep, raw):
    rules.require(rep['available'] and len(raw)==rep['bytes'] and hashlib.sha256(raw).hexdigest()==rep['sha256'], 'Representation checksum or length mismatch')


def verify_pair(descriptor, normalized, artifact, requested_curve, *, strict_interpretation=False):
    asset, view=validate.pair(descriptor,normalized)
    data=asset.model_dump(by_alias=True); values=view.model_dump(by_alias=True)
    rules.require(values['curve']==requested_curve, 'Requested curve differs from returned data')
    raw=rules.artifact(data)
    verify_bytes(raw,artifact)
    evidence=rules.interpretation(asset.model_dump(by_alias=True,exclude_unset=True))
    if evidence=='recorded-differs':
        if strict_interpretation: raise InterpretationChanged('The saved and current reader interpretations differ.', 'Read the exact artifact or explicitly accept this difference.', details={'recorded':data['recorded_interpretation'],'live':data['interpretation']})
        warnings.warn('The saved and current reader interpretations differ; both records are available in the descriptor.',InterpretationDiffers,stacklevel=2)
    return asset, view

def origin(value):
    if not isinstance(value,str): raise Refused('Use a service origin.')
    parsed=urlsplit(value)
    if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/')
        or parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1')):
        raise Refused('Use HTTPS or a loopback origin without credentials or a path.')
    return value.rstrip('/')


def slice_result(volume, raw, asset, revision, axis, label):
    """E16: verify a served slice against its volume and build the SeismicSlice object."""
    from .typed import SeismicSlice
    value=validate.seismic_slice(raw,volume.data,asset,revision,axis,label)
    return SeismicSlice(value,raw,volume)
