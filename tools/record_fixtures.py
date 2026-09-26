"""Admit recordings from a declared new synthetic fixture; never redact scientific bytes."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from check_public_inputs import inspect_bytes

ROOT=Path(__file__).resolve().parents[1]


def admit(rows,provenance):
    if provenance.get('synthetic_seed')!='platform-test-retained-applications' or not provenance.get('evidence'):
        raise ValueError('Reviewed new synthetic fixture provenance required')
    if not isinstance(rows,list) or not rows:raise ValueError('Empty recording')
    for row in rows:
        if set(row)!={'method','path','status','body_base64','headers'}:
            raise ValueError('Only public response recording fields may be saved')
        if row['method']!='GET' or not row['path'].startswith('/api/v1/projects/p/scientific-assets') or row['status']!=200:
            raise ValueError('Only successful synthetic public scientific reads may be recorded')
        if set(row['headers'])!={'content-type'}:raise ValueError('Do not record authentication or operational headers')
        raw=base64.b64decode(row['body_base64'],validate=True)
        inspect_bytes(row['path'],raw)
        if any(term in raw.lower() for term in (b'access_token',b'refresh_token',b'oph_api_',b'password',b'/home/',b'/tmp/')):
            raise ValueError('Recording contains credentials or private operational data')
    return (json.dumps(rows,indent=2)+'\n').encode()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--provenance',type=Path,required=True);parser.add_argument('--name',required=True);args=parser.parse_args()
    if not args.name.endswith('.json') or Path(args.name).name!=args.name:raise ValueError('Use a plain JSON recording filename')
    provenance=json.loads(args.provenance.read_text());raw=admit(json.loads(args.input.read_text()),provenance)
    path=ROOT/'tests/recordings'/args.name;path.parent.mkdir(exist_ok=True)
    if path.exists():raise ValueError('Recording exists; review an explicit replacement separately')
    source=json.loads((ROOT/'ophiolite/contracts/SOURCE.json').read_text())
    manifest=ROOT/'tests/fixtures/PROVENANCE.json';data=json.loads(manifest.read_text())
    data['inputs'].append({'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),
                          'source_commit':source['platform_commit'],'origin':'New Platform synthetic in-process public-route fixture',
                          'license':'Apache-2.0','disposition':'reviewed-for-sdk','evidence':provenance['evidence']})
    path.write_bytes(raw);manifest.write_text(json.dumps(data,indent=2)+'\n')
    print(f'Admitted {len(json.loads(raw))} responses without redaction; exact bodies retained')

if __name__=='__main__':main()
