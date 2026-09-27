"""Contract coverage and deterministic browser generation; no Node runtime needed."""
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ts_generator',ROOT/'tools/generate_ts_client.py')
generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)


def test_committed_typescript_outputs_match_snapshot():
    for path,content in generator.outputs().items():
        assert (generator.PACKAGE/path).read_text()==content,path
    assert (generator.PACKAGE/'src/generated/contracts.ts').read_bytes()==(generator.CONTRACTS/'generated/v1/ophiolite-contracts.ts').read_bytes()


def test_every_route_has_one_generated_operation_and_truthful_coverage():
    document=json.loads((generator.CONTRACTS/'openapi/v1/openapi.json').read_text())
    generated=generator.outputs();coverage=json.loads(generated['operation-coverage.json'])
    expected={method.upper()+' '+path for path,ops in document['paths'].items() if path.startswith('/api/v1/') for method in ops if method in generator.METHODS}
    assert len(coverage)==len(expected)==181
    assert {row['operation'] for row in coverage}==expected
    assert len({row['function'] for row in coverage})==len(coverage)
    for row in coverage:
        assert row['request'] in ('schema','tested-override','explicitly-untyped')
        assert row['response'] in ('schema','tested-override','explicitly-untyped')
        signature=generated['src/generated/operations.ts'].split('export function '+row['function']+'(')[1].split('\n')[0]
        if row['response']=='explicitly-untyped':assert 'Promise<unknown>' in signature


def test_unsupported_request_schema_keyword_refuses_with_route():
    document=json.loads((generator.CONTRACTS/'openapi/v1/openapi.json').read_text())
    path='/api/v1/projects/{project}/applications/start'
    document['paths'][path]['post']['requestBody']['content']['application/json']['schema']['not']={}
    with pytest.raises(ValueError,match='POST .*applications/start/request: unsupported keyword not'):
        generator.outputs(document)


def test_override_requires_real_route_source_adapter_and_recorded_response():
    coverage=json.loads(generator.outputs()['operation-coverage.json'])
    for row in coverage:
        if row['response']!='tested-override':continue
        override=row['override'];assert 'ophiolite/models/api.py' in override['source']
        recording=json.loads((ROOT/override['recording']).read_text())
        method,path=row['operation'].split(' ',1)
        assert any(x['method']==method and x['path']==path.replace('{project}','p') for x in recording['exchanges'])
        assert override['adapter'] and override['response_type']
    overrides=json.loads((ROOT/'tools/ts-operation-overrides.json').read_text())
    bad=copy.deepcopy(overrides);del bad[next(iter(bad))]['recording']
    with pytest.raises(ValueError,match='missing override recording'):generator.outputs(overrides=bad)
    bad=copy.deepcopy(overrides);bad['POST /api/v1/no-such-route']=next(iter(bad.values()))
    with pytest.raises(ValueError,match='absent operation'):generator.outputs(overrides=bad)
