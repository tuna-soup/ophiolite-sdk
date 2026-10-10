"""Local validation; importing or calling this module does not contact a server."""
import hashlib
import json
from importlib.resources import files
from pydantic import ValidationError
from .errors import VerificationFailed
from .models.generated import ScientificAsset, ApplicationCurve
from .models import invariants as rules


def model(kind, value):
    try: return kind.model_validate(value)
    except ValidationError as exc:
        # Do not echo arbitrary input values or internal identifiers in messages.
        raise VerificationFailed('Scientific data does not satisfy the declared contract.', 'No files were saved.') from exc


def pair(descriptor, raw):
    asset = model(ScientificAsset, descriptor)
    data = asset.model_dump(by_alias=True)
    rules.asset(data)
    rep=next(r for r in data['representations'] if r['kind']=='normalized')
    rules.require(rep['available'] and len(raw)==rep['bytes'] and hashlib.sha256(raw).hexdigest()==rep['sha256'], 'Normalized representation unavailable or integrity mismatch')
    try: value=json.loads(raw)
    except (ValueError,UnicodeError): raise VerificationFailed('Normalized data is not valid JSON.') from None
    view=model(ApplicationCurve,value); value=view.model_dump(by_alias=True)
    rules.curve(value)
    expected=data['source_reference'] or dict(authority=data['authority'],key=data['asset_id'],revision=data['revision'],profile=data['profile'])
    artifact=rules.artifact(data)
    rules.require(rules.known(value['source'],rules.REFERENCE)==rules.known(expected,rules.REFERENCE) and value['source_sha256']==artifact['sha256'], 'Curve and artifact source identities disagree')
    facts=rules.facts(value)
    rules.require(all(data['scientific'].get(k)==v for k,v in facts.items()) and rules.known(value['interpretation'],rules.INTERPRETATION)==rules.known(data['interpretation'],rules.INTERPRETATION), 'Descriptor scientific context or interpretation disagrees with curve')
    rules.interpretation(asset.model_dump(by_alias=True,exclude_unset=True))
    return asset, view


def typed_pair(descriptor, raw):
    """E11: a typed descriptor and its served data agree on bytes, identity, context and reader."""
    from .models import generated
    asset = model(ScientificAsset, descriptor)
    data = asset.model_dump(by_alias=True)
    rules.asset(data)
    rules.require('type' in data['scientific'], 'This descriptor is not typed data')
    rep=next(r for r in data['representations'] if r['kind']=='normalized')
    rules.require(rep['available'] and len(raw)==rep['bytes'] and hashlib.sha256(raw).hexdigest()==rep['sha256'], 'Normalized representation unavailable or integrity mismatch')
    try: value=json.loads(raw)
    except (ValueError,UnicodeError): raise VerificationFailed('Normalized data is not valid JSON.') from None
    # E23a: the payload model is the normalized profile the descriptor names (point-set/1 and /2 share a type).
    kinds={'ophiolite.well-tops/1':generated.WellTops,'ophiolite.trajectory/1':generated.Trajectory,'ophiolite.regular-grid-surface/1':generated.GridSurface,
           'ophiolite.triangulated-surface/1':generated.TriangulatedSurface,'ophiolite.point-set/1':generated.PointSet,'ophiolite.point-set/2':generated.PointSet2,
           'ophiolite.polyline-set/1':generated.PolylineSet,'ophiolite.seismic-volume/1':generated.SeismicVolume,
           'ophiolite.wavelet/1':generated.Wavelet,'ophiolite.model-section/1':generated.ModelSection,'ophiolite.seismic-section/1':generated.SeismicSection,
               'ophiolite.well-location-upload/1':generated.WellLocationUpload,'ophiolite.time-depth/1':generated.TimeDepth,
               'ophiolite.feature-set/1':generated.FeatureSet}  # E53; E74b; E57; E56
    if rep['profile'] not in kinds:raise VerificationFailed('This kind of data is not supported by this SDK; update it.')
    rules.require(isinstance(value,dict) and value.get('schema')==rep['profile'], 'The normalized data is not the profile the descriptor names')
    payload=model(kinds[rep['profile']],value).model_dump(by_alias=True)
    rules.typed_payload(payload)
    expected=data['source_reference'] or dict(authority=data['authority'],key=data['asset_id'],revision=data['revision'],profile=data['profile'])
    artifact=rules.artifact(data)
    rules.require(rules.known(payload['source'],rules.REFERENCE)==rules.known(expected,rules.REFERENCE) and payload['source_sha256']==artifact['sha256'], 'Typed data and artifact source identities disagree')
    rules.require(payload['context']==data['scientific'] and payload['interpretation']==data['interpretation'], 'Descriptor scientific context or interpretation disagrees with the data')
    rules.interpretation(asset.model_dump(by_alias=True,exclude_unset=True))
    return asset, value


def schema(value, schema_id, *, strict=True):
    from jsonschema import Draft202012Validator
    index,_=rules.registry()
    entries={row['id']:row['path'] for row in index['schemas']}
    entries.update({'ophiolite.contracts-registry/1':'registry-schema.json','ophiolite.contract-profile/1':'profile-schema.json'})
    if schema_id not in entries: raise VerificationFailed('Unknown local schema.')
    document=json.loads(files('ophiolite').joinpath('contracts',entries[schema_id]).read_text())
    if not strict:
        def tolerant(x):
            if isinstance(x,dict):
                if x.get('additionalProperties') is False: x['additionalProperties']=True
                for child in x.values(): tolerant(child)
            elif isinstance(x,list):
                for child in x:tolerant(child)
        tolerant(document)
    errors=list(Draft202012Validator(document).iter_errors(value))
    if errors: raise VerificationFailed('Scientific data does not satisfy the selected local schema.')
    return value


def seismic_slice(raw, volume, asset, revision, axis, label):
    """E16: a served slice document, checked against its (verified) volume description."""
    from .models import generated
    try: value=json.loads(raw)
    except (ValueError,UnicodeError): raise VerificationFailed('The slice is not valid JSON.') from None
    if not isinstance(value,dict):raise VerificationFailed('The slice is not a slice document.')
    model(generated.SeismicSlice,value)
    rules.seismic_slice(value,volume,asset,revision,axis,label)  # on the served document itself
    return value
