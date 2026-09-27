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
    typed = 'type' in value['scientific']
    if typed:
        mapping = {'well-tops': 'well-tops/1', 'trajectory': 'trajectory/1', 'regular-grid-surface': 'regular-grid-surface/1',
                   'triangulated-surface': 'triangulated-surface/1', 'point-set': 'point-set/1', 'polyline-set': 'polyline-set/1', 'seismic-volume': 'seismic-volume/1'}
        require(value['interpretation'].get('mapping') == mapping.get(value['scientific']['type']), 'Scientific context and interpretation disagree')
    else:
        context(value['scientific'])
        require(value.get('relationships') is None, 'Relationships belong to typed uploads only')
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
    declared=(profiles.get(profile['normalized_profile']) or {}).get('interpretation') or {}
    require(value['interpretation'].get('mapping')==declared.get('mapping'), 'Interpretation is not the one this profile declares')
    if value['origin']=='managed-derived': require(value['revision']==raw['sha256'], 'Derived revision must identify the exact artifact')
    if value.get('manifest') is not None: manifest(value, raw, normalized)
    require(len(set(value['supported_operations']))==len(value['supported_operations']), 'Duplicate supported operations')
    auth=value['authorization']
    if auth['status']=='evaluated':
        try: datetime.strptime(auth['evaluated_at'],'%Y-%m-%dT%H:%M:%SZ')
        except ValueError: raise VerificationFailed('Authorization timestamp is not a real calendar time') from None
        allowed=auth['allowed_operations']
        require(len(set(allowed))==len(allowed) and set(allowed)<=set(value['supported_operations']), 'Allowed operations must be a unique supported subset')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def manifest(value, raw, normalized):
    """E19 (asset contract 1.8.0): recompute the revision manifest digest offline and tie it to what
    was served: the artifact, the normalized representation, every disclosed lineage entry and the
    parents. Hidden entries stay bare commitments; the digest covers them all."""
    m = value['manifest']
    require(m['schema'] == 'ophiolite.revision-manifest/1', 'Unknown revision manifest')
    require((m['artifact']['sha256'], m['artifact']['bytes']) == (raw['sha256'], raw['bytes']), 'The revision manifest names another artifact')
    listed = {r['id']: (r['sha256'], r['bytes']) for r in m['representations']}
    require(len(listed) == len(m['representations']) and listed.get(normalized['id']) == (normalized['sha256'], normalized['bytes']),
            'The served representation is not the one the revision manifest names')
    disclosed = set()
    for entry in m['lineage']:
        parts = [entry.get(k) for k in ('predicate', 'reference', 'salt')]
        require(all(p is None for p in parts) or all(p is not None for p in parts), 'A lineage entry is disclosed partly')
        if entry.get('salt') is not None:
            reference = {k: v for k, v in entry['reference'].items() if v is not None}
            require(_sha(entry['salt'] + _canonical([entry['predicate'], reference])) == entry['commitment'], 'A disclosed lineage entry does not match its commitment')
            if entry['predicate'] == 'derived-from': disclosed.add(known(reference, REFERENCE[:3]))
    require({known(p, REFERENCE[:3]) for p in value['parents']} <= disclosed, 'A parent is not a disclosed lineage entry')
    body = {'schema': 'ophiolite.revision-manifest/1', 'asset_id': value['asset_id'], 'revision': value['revision'],
            'artifact': {'sha256': m['artifact']['sha256'], 'bytes': m['artifact']['bytes']},
            'representations': sorted(({'id': r['id'], 'sha256': r['sha256'], 'bytes': r['bytes']} for r in m['representations']), key=lambda r: r['id']),
            'lineage': sorted(e['commitment'] for e in m['lineage'])}
    require(_sha(_canonical(body)) == m['digest'], 'The revision manifest digest does not match its contents')


def interpretation(value):
    if 'interpretation_evidence' not in value and 'recorded_interpretation' not in value: return 'not-available'
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


def typed_payload(value):
    """Cross-field rules the schema cannot state, checked offline for every typed payload (E11)."""
    c = value['context']; kind = c['type']
    def spatial(rows):
        require(all(r[0] is not None and r[1] is not None for r in rows), 'Every row needs x and y')
        xs, ys, zs = [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows if r[2] is not None]
        require(c['x_range'] == [min(xs), max(xs)] and c['y_range'] == [min(ys), max(ys)] and c['z_range'] == ([min(zs), max(zs)] if zs else None), 'Coordinates and their context disagree')
        names = [a['name'] for a in value['attributes']]
        require(names == list(c['attributes']) and len(set(names)) == len(names) and all(len(a['values']) == len(rows) for a in value['attributes']), 'Attributes and their context disagree')
    if kind == 'triangulated-surface':
        v, t = value['vertices'], value['triangles']
        require(len(v) == c['vertex_count'] and len(t) == c['triangle_count'] and c['missing_z_count'] == sum(p[2] is None for p in v), 'Vertices, triangles and their context disagree')
        require(all(0 <= i < len(v) for tri in t for i in tri) and all(len(set(tri)) == 3 for tri in t), 'A triangle refers to a missing or repeated vertex')
        spatial(v)
    elif kind == 'point-set':
        p = value['points']
        require(len(p) == c['count'] and c['missing_z_count'] == (sum(q[2] is None for q in p) if c['z_provided'] else 0), 'Points and their context disagree')
        require(c['z_provided'] or all(q[2] is None for q in p), 'Points carry z although the file has none')
        spatial(p)
    elif kind == 'polyline-set':
        sticks = value['sticks']; points = [[p['x'], p['y'], p['z']] for s in sticks for p in s['points']]
        require(len({s['index'] for s in sticks}) == len(sticks), 'A stick index repeats')
        require(len(sticks) == c['sticks'] and len(points) == c['points'], 'Sticks, points and their context disagree')
        value = {**value, 'attributes': []}; spatial(points)
    elif kind == 'seismic-volume':
        seismic_context(c)
        il = c['inline']
        require([k['inline'] for k in value['chunks']] == line_numbers(il), 'Chunks do not follow the inline numbers')
        require(all(k['bytes'] == c['crossline']['count'] * c['samples'] * 4 for k in value['chunks']), 'A chunk has the wrong size')
        require(value['decisions'] == c['fidelity']['decisions'], 'Decisions disagree with the fidelity report')


def line_numbers(line):
    return [line['first'] + i * line['step'] for i in range(line['count'])]


def seismic_context(c):
    """E16: a volume's grid, trace length and line ranges agree."""
    for axis in ('inline', 'crossline'):
        line = c[axis]; require(line['first'] + (line['count'] - 1) * line['step'] == line['last'], 'Line range, step and count disagree')
    require(c['inline']['count'] * c['crossline']['count'] == c['traces'] and c['trace_bytes'] == 240 + 4 * c['samples'], 'Trace count, grid and trace length disagree')
    require(bool(c['fidelity']['decisions']), 'A seismic volume records its header decisions')


SLICE_AXES = {'inline': ('crossline', 'sample'), 'crossline': ('inline', 'sample'), 'sample': ('inline', 'crossline')}


def seismic_slice(value, volume, asset, revision, axis, label):
    """E16: a slice agrees with the volume it was read from — identity, direction, axes, sample
    meaning, shape and exactly the chunks that hold it. Offline; no bytes of the volume needed."""
    c = volume['context']
    require((value['asset_id'], value['revision'], value['source_sha256']) == (asset, revision, volume['source_sha256']), 'The slice belongs to another exact revision')
    require(value['source'] == volume['source'] and value['interpretation'] == volume['interpretation'], 'The slice and the volume disagree on source or reader')
    require((value['axis'], value['label']) == (axis, label), 'The slice is not the one requested')
    require('not the complete volume' in value['scope'], 'The slice does not state its scope')
    inlines, crosslines = line_numbers(c['inline']), line_numbers(c['crossline'])
    z = [c['first_sample'] + k * c['sample_interval'] for k in range(c['samples'])]
    values = {'inline': inlines, 'crossline': crosslines, 'sample': z}
    rows, columns = SLICE_AXES[axis]
    require((value['rows']['name'], value['columns']['name']) == (rows, columns), 'Slice axes do not match the slice direction')
    require(value['rows']['values'] == values[rows] and value['columns']['values'] == values[columns], 'Slice axes disagree with the volume')
    require(value['sample'] == {'domain': c['z_domain'], 'unit': c['sample_unit'], 'first': c['first_sample'], 'interval': c['sample_interval']}, 'Sample meaning disagrees with the volume')
    require(len(value['values']) == len(values[rows]) and all(len(r) == len(values[columns]) for r in value['values']), 'Slice values and axes disagree')
    chunks = [k['sha256'] for k in volume['chunks']]
    if axis == 'inline':
        require(label in inlines and value['chunks'] == [chunks[inlines.index(label)]], 'The slice was not read from its inline')
    else:
        require(label in (crosslines if axis == 'crossline' else range(c['samples'])) and value['chunks'] == chunks, 'The slice was not read from every inline')
