"""Pure scientific semantics beyond the generated structural contracts."""
import json
import math
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from ..errors import VerificationFailed, Incompatible

REFERENCE = ('authority','key','revision','profile')
INTERPRETATION = ('reader','parsing_policy','mapping','lasio_version','null_policy')


def require(condition, message):
    if not condition: raise VerificationFailed(message, 'No files were saved.')


def known(value, fields):
    return tuple(value.get(field) for field in fields)


@lru_cache(maxsize=1)
def registry():
    root = files('ophiolite').joinpath('contracts')
    index = json.loads(root.joinpath('registry.json').read_text())
    profiles = {row['id']:json.loads(root.joinpath(row['path']).read_text()) for row in index['profiles']}
    return index, profiles


def reference(value):
    if value is not None:
        require(value['profile'] in registry()[1], 'Reference profile is not registered')


def marker(context):
    try: result = float(context['missing_value_marker'])
    except (ValueError, TypeError, OverflowError): result = float('nan')
    require(math.isfinite(result), 'LAS missing marker must be finite')
    return result


def curve(value):
    reference(value['source']); sentinel = marker(value['context'])
    require(len(value['axis']) == len(value['values']), 'Axis and sample lengths differ')
    require(value['curve'] != value['context']['depth_index'], 'Value curve must differ from depth index')
    require(sentinel not in value['axis'], 'Depth axis cannot contain the LAS missing marker')
    require(sentinel not in value['values'], 'Missing samples must be null, not the LAS marker')


def facts(value):
    axis, values = value['axis'], value['values']; context = value['context']
    pairs = list(zip(axis, axis[1:]))
    order = ('insufficient' if not pairs else 'increasing' if all(a < b for a,b in pairs)
             else 'decreasing' if all(a > b for a,b in pairs) else 'unordered')
    return dict(curve=value['curve'], unit=value['unit'],
                unit_status='declared' if value['unit'].strip() else 'unknown',
                axis_unit=context['depth_unit'], axis_unit_status='declared' if context['depth_unit'].strip() else 'unknown',
                depth_reference=context['depth_reference'], sample_count=len(axis), missing_count=values.count(None),
                missing_value_marker=context['missing_value_marker'], axis_order=order, axis_duplicates=len(set(axis))!=len(axis))


def context(value):
    marker(value)
    for label in ('unit','axis_unit'):
        require(value[label+'_status'] == ('declared' if value[label].strip() else 'unknown'), 'Empty units are unknown')
    require(value['missing_count'] <= value['sample_count'], 'Missing count exceeds sample count')
    require(not value['axis_duplicates'] or value['axis_order']=='unordered', 'Strict ordered axes cannot contain duplicates')
    require((value['sample_count']<2)==(value['axis_order']=='insufficient'), 'Axis order needs at least two samples')


def representation(value):
    profiles = registry()[1]
    require(value['profile'] in profiles, 'Reference profile is not registered')
    profile = profiles[value['profile']]
    require(profile.get('role') == ('normalized' if value['kind']=='normalized' else 'artifact'), 'Representation kind and profile role disagree')
    require(value['media_type'] in profile.get('media_types',[]), 'Media type is not declared for this profile')


def asset(value):
    profiles = registry()[1]; reference(value['source_reference'])
    for parent in value['parents']: reference(parent)
    context(value['scientific'])
    for rep in value['representations']: representation(rep)
    retained = value['origin'] != 'source-reference'; retention = value['retention']
    require(retained == (value['custodian'] is not None) and retained == (retention['mode']=='retained'), 'Origin, custody and retention disagree')
    require(retention['historical_reads']==('while-retained-and-authorized' if retained else 'not-guaranteed'), 'Historical availability must match retention')
    if value['origin']=='managed-derived':
        require(value['authority']=='ophiolite:derived' and value['source_reference'] is None and (value['parents'] or value['parent_visibility']=='restricted'), 'Derived asset needs managed authority and exact parents')
        identities=[known(p,REFERENCE[:3]) for p in value['parents']]
        require(len(set(identities))==len(identities) and (value['authority'],value['asset_id'],value['revision']) not in identities, 'Parent identities must be distinct and not the output itself')
        require(value['provenance']['evidence']=='script-declared' and value['provenance']['method'] is not None, 'External derivation needs a declared method')
    else:
        require(value['source_reference'] is not None and value['authority']==value['source_reference']['authority'] and not value['parents'], 'Source authority/reference must be preserved')
        require(value['provenance']['evidence']=='source-declared', 'Capture is not a calculation')
    require((value['recorded_interpretation'] is None)==(value['interpretation_evidence'] in ('live','not-recorded')), 'Recorded interpretation must accompany recorded evidence and nothing else')
    reps=value['representations']
    require(len({r['id'] for r in reps})==len(reps), 'Representation IDs must be unique')
    require(value['profile'] in profiles and 'ophiolite.scientific-asset/1' in profiles[value['profile']].get('serves',[]), 'Profile is not served through this envelope')
    profile=profiles[value['profile']];rules=profile['representation_rules'];kinds=[r['kind'] for r in reps]
    require(kinds.count('normalized')==rules['normalized'], 'Exactly one normalized curve required in this bounded profile')
    artifact_kind=rules['artifact_kind_by_origin'][value['origin']]
    require(kinds.count(artifact_kind)==1 and len(kinds)==rules['total'], 'Profile requires one exact artifact and one normalized curve')
    raw=next(r for r in reps if r['kind']==artifact_kind); normalized=next(r for r in reps if r['kind']=='normalized')
    require(raw['profile']==value['profile'] and normalized['profile']==profile['normalized_profile'], 'Representation profiles must be the asset profile and its normalized profile')
    if value['origin']=='managed-derived': require(value['revision']==raw['sha256'], 'Derived revision must identify the exact artifact')
    require(len(set(value['supported_operations']))==len(value['supported_operations']), 'Duplicate supported operations')
    auth=value['authorization']
    if auth['status']=='evaluated':
        try: datetime.strptime(auth['evaluated_at'],'%Y-%m-%dT%H:%M:%SZ')
        except ValueError: raise VerificationFailed('Authorization timestamp is not a real calendar time') from None
        allowed=auth['allowed_operations']
        require(len(set(allowed))==len(allowed) and set(allowed)<=set(value['supported_operations']), 'Allowed operations must be a unique supported subset')


def interpretation(value):
    recorded=value.get('recorded_interpretation'); live=value.get('interpretation'); label=value.get('interpretation_evidence')
    if live is None and recorded is None: return 'not-available'
    if recorded is None:
        require(label in ('live','not-recorded'), 'evidence-inconsistent')
        return label
    if recorded['mapping'] != live['mapping']:
        raise Incompatible('The saved and current readers use different mappings.', 'Read the exact artifact instead.')
    comparison=('reader','parsing_policy','lasio_version')
    expected='recorded' if known(recorded,comparison)==known(live,comparison) else 'recorded-differs'
    require(label==expected, 'evidence-inconsistent')
    return expected
