"""Maintainer generator for every derived contract document.

Run from the Platform root with the qualified Connectors on the path:

    PYTHONPATH=services python contracts/tools/generate.py            # everything
    PYTHONPATH=services python contracts/tools/generate.py --schemas  # JSON Schemas only
    PYTHONPATH=services python contracts/tools/generate.py --fixtures # synthetic fixtures only
    PYTHONPATH=services python contracts/tools/generate.py --types    # TypeScript types only
    PYTHONPATH=services python contracts/tools/generate.py --openapi  # OpenAPI snapshot only

Pydantic models are the executable source of the structural schemas; this tool
writes their published form. It never writes under assets/v1/fixtures/frozen/:
frozen fixtures are committed bytes, not generator output.
"""
import hashlib
import json
import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1]
ASSETS = CONTRACTS / 'assets/v1'
FIX = ASSETS / 'fixtures'
FROZEN = FIX / 'frozen'


def write(path, value):
    path = Path(path)
    if FROZEN in path.parents or path == FROZEN:
        raise RuntimeError(f'Refusing to regenerate a frozen fixture: {path}')
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def schemas():
    """Publish the Pydantic-generated schemas listed in the registry."""
    from project_gateway.scientific_assets import Asset, AssetSummary, Curve, ScientificContext, TypedContext, WellTops, Trajectory, GridSurface
    for model in (Asset, Curve, ScientificContext, AssetSummary, TypedContext, WellTops, Trajectory, GridSurface):
        write(CONTRACTS / model.CONTRACT['path'], model.model_json_schema())


LAS = b'''~Version
VERS. 2.0 : LAS version
WRAP. NO : One row per depth
~Well
STRT.M 100 : Start
STOP.M 104 : Stop
STEP.M 1 : Step
NULL. -999.25 : Missing sample marker
WELL. SYNTHETIC-M1 : Not an observed well
~Curve
DEPT.M : Source depth; datum unknown
GR.gAPI : Gamma ray
~ASCII
100 0
101 10
102 -999.25
103 30
104 40
'''


def fixtures(target=FIX):
    """Regenerate the synthetic offline fixtures with the qualified current reader."""
    from project_gateway.scientific_assets import Asset, Curve
    from project_gateway.applications import Applications
    from asset_connectors.sources import Snapshot
    FIX = Path(target)
    app = Applications.__new__(Applications)
    raw = LAS
    source = {'authority': 'synthetic-file', 'key': 'curve-a', 'revision': digest(raw), 'profile': 'las2/1'}
    FIX.mkdir(exist_ok=True)
    (FIX / 'original.las').write_bytes(raw)
    result = raw.replace(b'100 0\n101 10', b'100 2\n101 12').replace(b'103 30', b'103 32')
    (FIX / 'derived.las').write_bytes(result)
    for name, data, ref, origin in [
        ('source', raw, source, 'source-reference'),
        ('capture', raw, source, 'retained-capture'),
        ('derived', result, {'authority':'ophiolite:derived','key':'synthetic-run-b','revision':digest(result),'profile':'las2/1'}, 'managed-derived')]:
        curve = app.curve(Snapshot(ref, {}, data, 'application/x-las'), 'GR')
        curve_file = FIX / ('derived-curve.json' if name == 'derived' else 'curve.json')
        write(curve_file, curve)
        artifact_kind = 'derived-artifact' if name == 'derived' else 'original'
        reps = [{'id':'las', 'kind':artifact_kind,'media_type':'application/x-las','profile':'las2/1','bytes':len(data),'sha256':digest(data),'available':True,'losses':[]},
                {'id':'curve','kind':'normalized','media_type':'application/json','profile':'ophiolite.application-curve/1','bytes':len(curve_file.read_bytes()),'sha256':digest(curve_file.read_bytes()),'available':True,'losses':['Selected curve only; other LAS headers and curves remain in artifact']}]
        retained = name != 'source'
        descriptor = {'schema':'ophiolite.scientific-asset/1','asset_id':ref['key'] if name != 'capture' else 'capture-a',
          'revision':digest(data), 'project_id':'synthetic-project', 'authority':ref['authority'], 'origin':origin,
          'custodian':'ophiolite:managed' if retained else None, 'source_reference':None if name=='derived' else source,
          'profile':'las2/1','scientific':Curve.model_validate(curve).facts().model_dump(),
          'interpretation':curve['interpretation'],
          # Retained fixtures carry a synthetic retention record equal to the live identity.
          'interpretation_evidence':'recorded' if retained else 'live','recorded_interpretation':dict(curve['interpretation']) if retained else None,
          'representations':reps,
          'retention':{'mode':'retained' if retained else 'upstream-only','policy':'until authorized lifecycle operation' if retained else 'upstream current bytes only','historical_reads':'while-retained-and-authorized' if retained else 'not-guaranteed'},
          'parents':[source] if name=='derived' else [],
          'provenance':{'evidence':'script-declared' if name=='derived' else 'source-declared','method':'Add 2 over source depths 100–103; skip missing samples' if name=='derived' else None,'code_reference':None,'environment_reference':None,'omissions':['Synthetic offline fixture, not a server publication','No independently verified execution environment']},
          'supported_operations':['read','export','use-as-input'],'authorization':{'status':'not-evaluated'}}
        Asset.model_validate(descriptor)
        write(FIX / f'{name}.json', descriptor)
    typed(FIX)
    write(FIX/'expected.json', {'axis':[100,101,102,103,104], 'values':[2,12,None,32,40], 'changes':[{'index':0,'value':2.0},{'index':1,'value':12.0},{'index':3,'value':32.0}]})


TYPED = {
    'tops': ('well-tops-csv/1', 'text/csv', b'name,md,tvd,source\nTop Chalk,100.5,,picked\nBase Chalk,103,102.9,\n', {'depth_unit': 'M', 'depth_basis': 'same-as-log'}),
    'trajectory': ('deviation-csv/1', 'text/csv', b'md,inclination,azimuth\n100,0,0\n200,10,0\n300,,\n', {'depth_unit': 'M', 'azimuth_reference': 'grid-north'}),
    'grid': ('esri-ascii-grid/1', 'text/plain', b'ncols 3\nnrows 2\nxllcorner 1000\nyllcorner 5000\ncellsize 25\nNODATA_value -9999\n1 0 -9999\n4 5 6\n', {'crs': 'EPSG:28992', 'z_unit': 'm', 'z_meaning': 'depth', 'positive': 'down'}),
}


def typed(FIX):
    """Synthetic typed fixtures (E11): exact original, normalized data and a retained descriptor."""
    from asset_connectors.typed_reader import read_typed, interpretation
    from project_gateway.scientific_assets import Asset, TYPED_PAYLOADS
    from project_gateway.contracts_registry import registry
    for name, (profile, media, raw, declared) in TYPED.items():
        context, data, fidelity = read_typed(profile, raw, declared)
        kind = context['type']; ref = {'authority': 'ophiolite:uploaded', 'key': 'synthetic-' + name, 'revision': digest(raw), 'profile': profile}
        normalized = registry().normalized_profile(profile)
        payload = {'schema': normalized, 'representation': 'normalized', 'source': ref, 'source_sha256': digest(raw),
                   'interpretation': interpretation(kind), 'context': {**context, 'fidelity': fidelity}, **data}
        TYPED_PAYLOADS[kind].model_validate(payload)
        (FIX / f'{name}.original').write_bytes(raw)
        write(FIX / f'{name}-data.json', payload)
        encoded = (FIX / f'{name}-data.json').read_bytes()
        descriptor = {'schema': 'ophiolite.scientific-asset/1', 'asset_id': ref['key'], 'revision': ref['revision'], 'project_id': 'synthetic-project',
            'authority': ref['authority'], 'origin': 'retained-capture', 'custodian': 'ophiolite:managed', 'source_reference': ref, 'profile': profile,
            'scientific': payload['context'], 'interpretation': payload['interpretation'], 'interpretation_evidence': 'live', 'recorded_interpretation': None,
            'representations': [{'id': 'artifact', 'kind': 'original', 'media_type': media, 'profile': profile, 'bytes': len(raw), 'sha256': digest(raw), 'available': True, 'losses': []},
                                {'id': 'data', 'kind': 'normalized', 'media_type': 'application/json', 'profile': normalized, 'bytes': len(encoded), 'sha256': digest(encoded), 'available': True, 'losses': fidelity['losses']}],
            'retention': {'mode': 'retained', 'policy': 'until authorized lifecycle operation', 'historical_reads': 'while-retained-and-authorized'},
            'relationships': {'well_log': None}, 'parents': [],
            'provenance': {'evidence': 'source-declared', 'method': None, 'code_reference': None, 'environment_reference': None, 'omissions': ['Synthetic offline fixture, not a server publication']},
            'supported_operations': ['read', 'export'], 'authorization': {'status': 'not-evaluated'}}
        Asset.model_validate(descriptor)
        write(FIX / f'{name}.json', descriptor)


# ---------------------------------------------------------------------------
# TypeScript emission. The emitter supports exactly the keywords the registry
# schemas use and raises with the JSON path on anything else; it never emits
# `any` or `unknown` silently.

class Unsupported(ValueError):
    """A schema keyword the emitter does not translate; the path names it."""


ANNOTATIONS = {'$schema', '$id', 'x-ophiolite', 'title', 'description', 'default', 'examples', 'deprecated',
               'minLength', 'maxLength', 'pattern', 'format', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
               'multipleOf', 'minItems', 'maxItems', 'uniqueItems', 'discriminator'}
SCALARS = {'string': 'string', 'integer': 'number', 'number': 'number', 'boolean': 'boolean', 'null': 'null'}


def _literal(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if value is None:
        return 'null'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise Unsupported(f'literal of type {type(value).__name__}')


def _union(members):
    seen = []
    for member in members:
        if member not in seen:
            seen.append(member)
    return ' | '.join(seen)


def _wrap(text):
    return f'({text})' if ' | ' in text else text


def ts_type(schema, path='$', indent=0):
    """Translate one JSON Schema subschema to a TypeScript type expression."""
    if not isinstance(schema, dict):
        raise Unsupported(f'{path}: schema must be an object')
    keys = set(schema) - ANNOTATIONS
    unknown = keys - {'type', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'const', 'anyOf', 'oneOf', '$ref', '$defs'}
    if unknown:
        raise Unsupported(f'{path}: unsupported keyword(s) {sorted(unknown)}')
    if '$ref' in schema:
        ref = schema['$ref']
        if not ref.startswith('#/$defs/') or len(keys) != 1:
            raise Unsupported(f'{path}: only bare local $ref to $defs is supported, got {ref!r}')
        return ref.removeprefix('#/$defs/')
    if 'const' in schema:
        return _literal(schema['const'])
    if 'enum' in schema:
        return _union(_literal(v) for v in schema['enum'])
    for combinator in ('anyOf', 'oneOf'):
        if combinator in schema:
            if keys - {combinator}:
                raise Unsupported(f'{path}: {combinator} combined with {sorted(keys - {combinator})}')
            return _union(ts_type(sub, f'{path}/{combinator}/{i}', indent) for i, sub in enumerate(schema[combinator]))
    kind = schema.get('type')
    if kind is None:
        raise Unsupported(f'{path}: no type, const, enum, $ref, anyOf or oneOf')
    if isinstance(kind, list):
        return _union(ts_type({**schema, 'type': k}, path, indent) for k in kind)
    if kind in SCALARS:
        return SCALARS[kind]
    if kind == 'array':
        if 'items' not in schema:
            raise Unsupported(f'{path}: array without items')
        return _wrap(ts_type(schema['items'], f'{path}/items', indent)) + '[]'
    if kind == 'object':
        if 'properties' not in schema:
            raise Unsupported(f'{path}: object without properties')
        extra = schema.get('additionalProperties', None)
        if extra not in (None, False):
            raise Unsupported(f'{path}: additionalProperties must be absent or false')
        required = set(schema.get('required', []))
        pad = '  ' * (indent + 1)
        lines = ['{']
        for name, sub in schema['properties'].items():
            label = name if name.isidentifier() else json.dumps(name)  # quoted when not an identifier
            optional = '' if name in required else '?'
            lines.append(f'{pad}{label}{optional}: {ts_type(sub, f"{path}/properties/{name}", indent + 1)};')
        lines.append('  ' * indent + '}')
        return '\n'.join(lines)
    raise Unsupported(f'{path}: unsupported type {kind!r}')


def _plain(schema):
    return {k: v for k, v in schema.items() if k not in ('$schema', '$id', 'x-ophiolite', 'title', 'description', '$defs')}


def emit(entries):
    """Emit `export type` declarations for (name, schema) entries and their $defs.

    A definition name that appears in several schemas must be structurally
    identical everywhere; otherwise generation fails rather than guessing.
    """
    named = {}
    order = []
    def add(name, schema, origin):
        plain = _plain(schema)
        if name in named:
            if named[name][0] != plain:
                raise Unsupported(f'{origin}: definition {name} differs from an earlier definition')
            return
        named[name] = (plain, origin)
        order.append(name)
    for name, schema in entries:
        for def_name, definition in schema.get('$defs', {}).items():
            add(def_name, definition, f'{name}/$defs/{def_name}')
        add(name, schema, name)
    out = []
    for name in order:
        plain, origin = named[name]
        out.append(f'export type {name} = {ts_type(plain, origin)};\n')
    return '\n'.join(out)


TYPES_PATH = CONTRACTS / 'generated/v1/ophiolite-contracts.ts'


def types_text():
    from project_gateway.contracts_registry import load
    registry = load(CONTRACTS)
    entries = [(entry['title'], entry['document']) for entry in registry.schemas.values()]
    header = ('// Generated by contracts/tools/generate.py --types from every schema listed in contracts/registry.json.\n'
              '// Do not edit; regenerate with: PYTHONPATH=services python contracts/tools/generate.py --types\n'
              '// Sources: ' + ', '.join(entry['path'] for entry in registry.schemas.values()) + '\n\n')
    return header + emit(entries)


def types():
    """Write the TypeScript types; nothing is written when emission fails."""
    TYPES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TYPES_PATH.write_text(types_text())


OPENAPI_PATH = CONTRACTS / 'openapi/v1/openapi.json'


def openapi():
    """Snapshot the live /api/v1/openapi.json document."""
    from project_gateway.openapi import document
    write(OPENAPI_PATH, document())


STEPS = {'--schemas': schemas, '--fixtures': fixtures, '--types': types, '--openapi': openapi}


def main(argv):
    chosen = [STEPS[a] for a in argv] if argv else list(STEPS.values())
    for step in chosen:
        step()


if __name__ == '__main__':
    main(sys.argv[1:])
