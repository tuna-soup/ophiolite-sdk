"""Transport-free exact-read verification shared by synchronous and future async drivers."""
import hashlib
import warnings
from . import validate
from .errors import InterpretationDiffers, InterpretationChanged, VerificationFailed
from .models.generated import ScientificAsset
from .models import invariants as rules


def verify_descriptor(value, project, asset, revision, curve):
    model=validate.model(ScientificAsset,value); data=model.model_dump(by_alias=True)
    rules.asset(data)
    rules.require((data['project_id'],data['asset_id'],data['revision'])==(project,asset,revision), 'Scientific descriptor does not match the requested exact identity')
    rules.require(data['scientific']['curve']==curve, 'Requested curve differs from returned data')
    return model


def verify_bytes(rep, raw):
    rules.require(rep['available'] and len(raw)==rep['bytes'] and hashlib.sha256(raw).hexdigest()==rep['sha256'], 'Representation checksum or length mismatch')


def verify_pair(descriptor, normalized, artifact, requested_curve, *, strict_interpretation=False):
    asset, view=validate.pair(descriptor,normalized)
    data=asset.model_dump(by_alias=True); values=view.model_dump(by_alias=True)
    rules.require(values['curve']==requested_curve, 'Requested curve differs from returned data')
    raw=next(r for r in data['representations'] if r['kind']!='normalized')
    verify_bytes(raw,artifact)
    evidence=rules.interpretation(data)
    if evidence=='recorded-differs':
        if strict_interpretation: raise InterpretationChanged('The saved and current reader interpretations differ.', 'Read the exact artifact or explicitly accept this difference.', details={'recorded':data['recorded_interpretation'],'live':data['interpretation']})
        warnings.warn('The saved and current reader interpretations differ; both records are available in the descriptor.',InterpretationDiffers,stacklevel=2)
    return asset, view
