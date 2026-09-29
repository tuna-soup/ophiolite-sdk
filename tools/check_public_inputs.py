"""Fail closed on uncovered copied inputs or credential material before publication.

This verifies recorded review evidence, not legal ownership. New evidence requires
human/supervisor review; the tool must never manufacture a rights disposition.
"""
import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=(b'E4_SECRET_' + b'CANARY_DO_NOT_PUBLISH',b'-----BEGIN ' + b'PRIVATE KEY-----',b'-----BEGIN ' + b'OPENSSH PRIVATE KEY-----')
TOKEN=re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,})\b')


def inspect_bytes(path,raw):
    if any(value in raw for value in FORBIDDEN) or TOKEN.search(raw):
        raise ValueError('Credential/private-key material in '+path)


def verify(root=ROOT):
    manifest=json.loads((root/'tests/fixtures/PROVENANCE.json').read_text())
    if manifest.get('schema')!='ophiolite.sdk-public-inputs/1':raise ValueError('Unrecognized provenance schema')
    entries=manifest['inputs'];by_path={row['path']:row for row in entries}
    if len(by_path)!=len(entries):raise ValueError('Duplicate provenance path')
    source=json.loads((root/'ophiolite/contracts/SOURCE.json').read_text())
    expected={'ophiolite/contracts/'+name for name in source['files']}
    expected.update(p.relative_to(root).as_posix() for p in (root/'tests/fixtures').rglob('*') if p.is_file() and p.name!='PROVENANCE.json')
    expected.update(p.relative_to(root).as_posix() for p in (root/'ophiolite/templates').glob('*/data/*') if p.is_file())
    recordings=root/'tests/recordings'
    expected.update(p.relative_to(root).as_posix() for p in recordings.rglob('*') if p.is_file())
    if set(by_path)!=expected:raise ValueError('Copied input provenance coverage differs')
    for path,row in by_path.items():
        if Path(path).is_absolute() or '..' in Path(path).parts:raise ValueError('Unsafe provenance path')
        if row.get('disposition')!='reviewed-for-sdk' or row.get('license')!='Apache-2.0' or not row.get('evidence'):
            raise ValueError('Redistribution evidence missing for '+path)
        raw=(root/path).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Provenance hash mismatch: '+path)
        if path.startswith('ophiolite/contracts/'):
            name=path.removeprefix('ophiolite/contracts/')
            if row.get('source_commit')!=source['platform_commit'] or row['sha256']!=source['files'][name]:
                raise ValueError('Source evidence mismatch: '+path)
        inspect_bytes(path,raw)
    for name in ('LICENSE','NOTICE','THIRD_PARTY.md'):
        if not (root/name).is_file() or not (root/name).read_bytes().strip():raise ValueError('Missing notice '+name)
    return len(entries)


def archive(path,root=ROOT):
    if path.suffix=='.whl':
        with zipfile.ZipFile(path) as package:members={n:package.read(n) for n in package.namelist() if not n.endswith('/')}
        for name in members:
            if not (name.startswith('ophiolite/') or '.dist-info/' in name):raise ValueError('Unexpected wheel input: '+name)
    else:
        with tarfile.open(path) as package:
            members={member.name.split('/',1)[1]:package.extractfile(member).read() for member in package.getmembers() if member.isfile()}
    for name,raw in members.items():
        if '__pycache__' in name or name.endswith('.pyc') or '/.env' in name:raise ValueError('Private/generated archive input: '+name)
        inspect_bytes(name,raw)
        if name.startswith(('ophiolite/','templates/')):
            source=root/name
            if not source.is_file() or source.read_bytes()!=raw:raise ValueError('Archive differs from audited source: '+name)
    expected={p.relative_to(root).as_posix() for p in (root/'ophiolite/contracts').rglob('*') if p.is_file()}
    if not expected<=members.keys():raise ValueError('Archive omits a contract input')
    return len(members)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--artifact',type=Path,action='append',default=[]);args=parser.parse_args()
    print(f'Public copied inputs: {verify()} reviewed records verified')
    for path in args.artifact:print(f'{path.name}: {archive(path)} members inspected')

if __name__=='__main__':main()
