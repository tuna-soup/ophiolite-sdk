"""E147 s0 (D5, C3): the pinned validators accept the release descriptors' valid fixtures and each catches its mutation.

mlcroissant and roc-validator run in a venv this test makes from the lane's wheel with the test-only `descriptors-test`
extra, never in the SDK's runtime dependencies (e8's R-d condition). The DataCite kernel-4.3 JSON schema and the W3C
PROV-JSON schema are fetched by URL and SHA-256 once per run and checked with jsonschema; an unreachable URL skips only
that schema's test with its reason, a wrong digest fails (CL-1). The DOI-less DataCite fragment is checked against the 4.3
schema with only `identifiers` removed from `required` (X-4). Each mutation is given to the validator itself, so a red
here is the validator's, not the comparator's.

E147 s1 (C3): the same venv installs `[descriptors-test,folder]` and write_folder writes two folders there, the
folder-field citation and the minimum citation (no version or publisher identifier; CC0-1.0; a description, which
RO-Crate 1.1 requires and the citation therefore does since rev 3); both pass
mlcroissant and roc-validator, and the s0 mutations are repeated on a written folder. In the test interpreter the two
written folders' datacite.json pass the DataCite fragment and their lineage/prov.json the PROV-JSON schema.

E147 s2 (C2): write_bundle writes the bundle-wells read with its citation (without prov.json) twice, licensed and with
a null licence and its notice; both pass mlcroissant and roc-validator in the venv and the DataCite fragment here.

E147 s2b (C3): write_bundle writes cited tops, trajectory, time-depth and point-set bundles (2.16) in the venv; both
validators accept them and the contract's bundle-tables fixture, and mlcroissant's records() gives each record set's
hand rows with their nulls. A wrong member path makes records() raise.

E160 s0 (C3): the contract's three work-episodes croissant.json fixtures pass mlcroissant, and records('turns') gives
each turns.jsonl line's scalar places by hand; a moved transform.jsonPath moves the values.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

try: import tomllib
except ModuleNotFoundError: import tomli as tomllib  # Python 3.10 (the dev extra installs tomli there)

SDK = Path(__file__).resolve().parents[1]
VALID = SDK / 'ophiolite/contracts/descriptors/v1/fixtures/valid'
VALIDATORS = {'mlcroissant', 'roc-validator'}
DATACITE = ('https://raw.githubusercontent.com/datacite/schema/master/source/json/kernel-4.3/datacite_4.3_schema.json',
            '464100493475c0d430600135d952e84847e44b5e57e0d005b11e0513dcf517c2')
PROV_JSON = ('https://www.w3.org/submissions/prov-json/schema',
             '39e79eec9f4a0c40f5177acced678b97e612b483671fd4edc77af46c8502fb36')
LINEAGE = {'bundle-wells': 'prov.json', 'folder-field': 'lineage/prov.json'}

# E147 s1: write_folder's two cited folders (examples/folders/build.py's wells, writer and time), in either interpreter.
WRITE = r'''
import json
from importlib.resources import files
from pathlib import Path
import pandas
from ophiolite.folder import write_folder

WELLS = [('SYN-F1', 'Synthetic field 1', 150000.0, 450000.0, 1200.0), ('SYN-F2', 'Synthetic field 2', 150750.5, 450250.0, 1325.5),
         ('SYN-F3', 'Synthetic field 3', 151500.0, 449500.25, 980.0), ('SYN-F4', 'Synthetic field 4', 152250.0, 450750.0, 1410.0)]
FIELD = Path(str(files('ophiolite').joinpath('contracts/descriptors/v1/fixtures/valid/folder-field/manifest.json')))
CITATIONS = {
    'fixture': {k: v for k, v in json.loads(FIELD.read_text())['citation'].items() if k not in ('schema', 'doi', 'descriptors')},
    'minimum': {'title': 'Synthetic field: four wells', 'description': 'Four made-up wells.', 'creators': [{'name': 'Ada Synthetic', 'kind': 'person'}],
                'publisher': {'name': 'Synthetic Survey Organisation'}, 'licence': {'spdx': 'CC0-1.0'}},
}

def write_cited(root):
    frame = pandas.DataFrame({'id': [w[0] for w in WELLS], 'name': [w[1] for w in WELLS], 'x': [w[2] for w in WELLS],
                              'y': [w[3] for w in WELLS], 'depth': [w[4] for w in WELLS],
                              'operator': ['Ophiolite examples'] * len(WELLS)})
    written = {}
    for label, citation in CITATIONS.items():
        written[label] = Path(root) / ('written-' + label)
        write_folder(written[label], {'wells': (frame, {'crs': 'EPSG:28992'})}, writer={'name': 'ophiolite-examples', 'version': '1'},
                     created_at='2026-11-04T12:00:00Z', citation=citation)
    return written
'''

# E147 s2 (C2): write_bundle's two cited bundles of the bundle-wells read (its citation without prov.json; licensed, and
# the licence-null form with its notice), in either interpreter.
BUNDLE = r'''
import json
from importlib.resources import files
from pathlib import Path
from ophiolite.bundle import write_bundle

BUNDLE_WELLS = Path(str(files('ophiolite').joinpath('contracts/descriptors/v1/fixtures/valid/bundle-wells')))
CITED = {k: v for k, v in json.loads((BUNDLE_WELLS / 'manifest.json').read_text())['citation'].items() if k != 'prov'}
BUNDLE_CITATIONS = {'licensed': CITED,
                    'unlicensed': dict(CITED, licence=None, notice='No open licence is recorded for every file of this bundle; ask the publisher before reusing it.')}

class WellsRead:
    def __init__(self):
        self.artifact = (BUNDLE_WELLS / 'assets/0/original.las').read_bytes()
        self._wire_descriptors = [json.loads((BUNDLE_WELLS / 'assets/0/descriptor-GR.json').read_bytes())]
        self._wire_curve_bytes = [(BUNDLE_WELLS / 'assets/0/curve-GR.json').read_bytes()]
        self._wire_curves = [json.loads(self._wire_curve_bytes[0])]

def write_cited_bundles(root):
    written = {}
    for label, citation in BUNDLE_CITATIONS.items():
        read = WellsRead(); d = read._wire_descriptors[0]
        written[label] = Path(root) / ('bundle-' + label)
        write_bundle(written[label], [({'asset_id': d['asset_id'], 'revision': d['revision'], 'curves': ['GR']}, read)], citation=citation)
    return written
'''

# E147 s2b (C3): write_bundle's cited bundles of the four typed tables from the asset fixtures, and a time-depth whose
# velocity (not a field of its record set) has a null, in the wheel venv.
TABLES = r'''
import hashlib
from ophiolite import _core

TYPED = files('ophiolite').joinpath('contracts/assets/v1/fixtures')

def typed(name, change=None):
    descriptor = json.loads(TYPED.joinpath(name + '.json').read_bytes()); raw = TYPED.joinpath(name + '-data.json').read_bytes()
    if change:
        data = json.loads(raw); change(data); raw = json.dumps(data).encode()
        next(r for r in descriptor['representations'] if r['kind'] == 'normalized').update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    read = _core.typed_result(descriptor, raw, TYPED.joinpath(name + '.original').read_bytes())
    return {'asset_id': descriptor['asset_id'], 'revision': descriptor['revision'], 'curves': None}, read

def null_velocity(data): data['velocity'][1] = None

def write_table_bundles(root):
    reads = {name: [typed(name)] for name in ('tops', 'trajectory', 'time-depth', 'points')}
    reads['time-depth-null-velocity'] = [typed('time-depth', null_velocity)]
    written = {}
    for label, items in reads.items():
        written[label] = Path(root) / ('tables-' + label)
        write_bundle(written[label], items, citation=CITED)
    return written
'''

# E147 s3 (C3): two starter pack folders written by the SDK's own pack writer (starter.pack_descriptors, which finalise
# calls after its checks) from a pack document whose artefacts are real files under files/: an Apache-2.0 pack (no
# licence, the notice) and a CC-BY-4.0 pack, in either interpreter.
PACK = r'''
import hashlib
from ophiolite import starter

PACK_FILES = {'targets/python/open_pack.py': b'print("open the pack")\n', 'targets/python/heads/SYN-1.geojson': b'{"type": "FeatureCollection", "features": []}\n',
              'ATTRIBUTION.md': b'# Attribution\n\nSynthetic values only.\n', 'seismic-3d/SYN-CUBE.sgy': bytes(3600)}
PACK_LICENCES = {'notice': {'name': 'Apache License 2.0', 'spdx': 'Apache-2.0', 'url': 'https://www.apache.org/licenses/LICENSE-2.0',
                            'redistribution': 'allowed', 'attribution': 'required'},
                 'open': {'name': 'Creative Commons Attribution 4.0 International', 'spdx': 'CC-BY-4.0',
                          'url': 'https://creativecommons.org/licenses/by/4.0/', 'redistribution': 'allowed', 'attribution': 'required'}}
PACK_RECORD = {'id': 'synthetic-survey/two-wells', 'publisher': {'name': 'Synthetic Survey Organisation', 'url': 'https://example.org/synthetic'}}

def write_packs(root):
    written = {}
    for label, licence in PACK_LICENCES.items():
        out = Path(root) / ('pack-' + label)
        artefacts = []
        for path, raw in PACK_FILES.items():
            (out / 'files' / path).parent.mkdir(parents=True, exist_ok=True); (out / 'files' / path).write_bytes(raw)
            artefacts.append({'path': path, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        doc = {'id': 'synthetic-survey/two-wells/starter', 'record_id': PACK_RECORD['id'], 'title': 'Synthetic starter pack: two wells',
               'summary': 'Two made-up wells and a small cube, packed for Python.', 'built_at': '2026-11-05T09:30:00Z',
               'licence': dict(licence), 'targets': [{'application': 'python', 'artefacts': artefacts}]}
        (out / 'starter.json').write_bytes(starter.dumped(doc))
        for name, raw in starter.pack_descriptors(doc, PACK_RECORD, '').items(): (out / name).write_bytes(raw)
        written[label] = out
    return written
'''

SCRIPT = WRITE + BUNDLE + TABLES + PACK + r'''
import json, shutil, sys
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
import mlcroissant
from rocrate_validator import models, services
base = Path(str(files('ophiolite').joinpath('contracts/descriptors/v1/fixtures/valid')))
load = lambda path: json.loads(Path(path).read_text())

def croissant(doc):
    try: mlcroissant.Dataset(jsonld=doc)
    except mlcroissant.ValidationError as error: return str(error)
    return None

def crate(folder):
    report = services.validate(services.ValidationSettings(rocrate_uri=str(folder), profile_identifier='ro-crate-1.1',
                                                           requirement_severity=models.Severity.REQUIRED))
    return sorted(issue.check.identifier for issue in report.get_issues())

out = {'versions': {name: version(name) for name in ('mlcroissant', 'roc-validator')}, 'valid': {}, 'mutated': {}}
for name in ('bundle-wells', 'folder-field'):
    out['valid'][name] = {'croissant': croissant(load(base / name / 'croissant.json')), 'ro-crate': crate(base / name)}
wells = base / 'bundle-wells'
doc = load(wells / 'croissant.json'); del doc['distribution'][0]['contentUrl']
out['mutated']['croissant'] = croissant(doc)
copied = Path(sys.argv[1]) / 'crate'; shutil.copytree(wells, copied)
doc = load(copied / 'ro-crate-metadata.json')
[root] = [node for node in doc['@graph'] if node['@id'] == './']; del root['datePublished']
(copied / 'ro-crate-metadata.json').write_text(json.dumps(doc))
out['mutated']['ro-crate'] = crate(copied)
written = write_cited(sys.argv[1])
out['written'] = {label: {'croissant': croissant(load(folder / 'croissant.json')), 'ro-crate': crate(folder)}
                  for label, folder in written.items()}
doc = load(written['fixture'] / 'croissant.json'); del doc['distribution'][0]['contentUrl']
out['written-mutated'] = {'croissant': croissant(doc)}
doc = load(written['fixture'] / 'ro-crate-metadata.json')
[root] = [node for node in doc['@graph'] if node['@id'] == './']; del root['datePublished']
(written['fixture'] / 'ro-crate-metadata.json').write_text(json.dumps(doc))
out['written-mutated']['ro-crate'] = crate(written['fixture'])
out['written-bundles'] = {label: {'croissant': croissant(load(folder / 'croissant.json')), 'ro-crate': crate(folder)}
                          for label, folder in write_cited_bundles(sys.argv[1]).items()}

def records(folder):
    """Every record set's rows as mlcroissant reads them offline from FOLDER, {set id: [{field name: value}]}."""
    doc = load(Path(folder) / 'croissant.json'); dataset = mlcroissant.Dataset(jsonld=str(Path(folder) / 'croissant.json'))
    return {s['@id']: [{key.rsplit('/', 1)[-1]: value.decode() if isinstance(value, bytes) else value for key, value in row.items()}
                       for row in dataset.records(record_set=s['@id'])] for s in doc.get('recordSet', [])}

tables = write_table_bundles(sys.argv[1])
out['tables'] = {label: {'version': load(folder / 'manifest.json')['bundle_version'], 'croissant': croissant(load(folder / 'croissant.json')),
                         'ro-crate': crate(folder), 'records': records(folder)} for label, folder in tables.items()}
out['tables']['fixture'] = {'croissant': croissant(load(base / 'bundle-tables/croissant.json')), 'ro-crate': crate(base / 'bundle-tables'),
                            'records': records(base / 'bundle-tables')}
wrong = Path(sys.argv[1]) / 'tables-wrong-path'; shutil.copytree(tables['tops'], wrong)
doc = load(wrong / 'croissant.json'); doc['recordSet'][0]['field'][0]['source']['extract']['jsonPath'] = '$.top[*].name'
(wrong / 'croissant.json').write_text(json.dumps(doc))
try: out['tables-wrong-path'] = records(wrong)
except Exception as error: out['tables-wrong-path'] = type(error).__name__
packs = write_packs(sys.argv[1])
out['packs'] = {label: {'croissant': croissant(load(folder / 'croissant.json')), 'ro-crate': crate(folder),
                        'license': load(folder / 'croissant.json').get('license')} for label, folder in packs.items()}
out['packs']['fixture'] = {'croissant': croissant(load(base / 'starter-pack/croissant.json'))}
doc = load(packs['notice'] / 'croissant.json'); del doc['distribution'][0]['sha256']
out['packs-mutated'] = {'croissant': croissant(doc)}
out['episodes'] = {name: {'croissant': croissant(load(base / name / 'croissant.json')), 'records': records(base / name)}
                   for name in ('episodes-shape', 'episodes-auto', 'episodes-empty')}
moved = Path(sys.argv[1]) / 'episodes-moved'; shutil.copytree(base / 'episodes-shape', moved)
doc = load(moved / 'croissant.json'); doc['recordSet'][0]['field'][4]['source']['transform']['jsonPath'] = '$.n'
(moved / 'croissant.json').write_text(json.dumps(doc))
out['episodes-moved'] = [row['attempt.chain'] for row in records(moved)['turns']]
print(json.dumps(out))
'''


def names(requirements):
    return {re.split(r'[<>=!~\[ ;@]', r.strip(), 1)[0].lower() for r in requirements if r.strip() and not r.strip().startswith('#')}


def load(path):
    return json.loads(Path(path).read_text())


def test_the_validators_are_a_test_only_extra():
    """R-d: the validators are only in `descriptors-test`; not runtime, not dev, not in a template image lock."""
    project = tomllib.loads((SDK / 'pyproject.toml').read_text())['project']
    extras = project['optional-dependencies']
    assert extras['descriptors-test'] == ['mlcroissant==1.1.1', 'roc-validator==0.13.1']
    assert not names(project['dependencies']) & VALIDATORS
    assert {name for name, reqs in extras.items() if names(reqs) & VALIDATORS} == {'descriptors-test'}
    locks = sorted((SDK / 'ophiolite/templates').glob('*/requirements.lock'))
    assert locks
    for lock in locks: assert not names(lock.read_text().splitlines()) & VALIDATORS, lock


# ---- mlcroissant and roc-validator, from the wheel -----------------------------------------------------------------

@pytest.fixture(scope='module')
def validated(tmp_path_factory):
    dist = os.environ.get('OPHIOLITE_TEST_DIST')
    if not dist:
        if os.environ.get('OPHIOLITE_REQUIRE_WHEEL') == '1': pytest.fail('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel')
        pytest.skip('Set OPHIOLITE_TEST_DIST to the folder holding the built wheel')
    [wheel] = Path(dist).glob('ophiolite-*.whl')
    work = tmp_path_factory.mktemp('descriptor-validators')
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('OPHIOLITE_')}
    run = lambda *argv, timeout=900: subprocess.run([str(a) for a in argv], cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
    made = run(sys.executable, '-m', 'venv', work / 'venv')
    assert made.returncode == 0, made.stderr
    python = work / 'venv/bin/python'
    done = run(python, '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '%s[descriptors-test,folder]' % wheel)
    assert done.returncode == 0, done.stderr
    done = run(python, '-I', '-c', SCRIPT, work)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    print('E147 s0 validators: %s' % json.dumps(result['versions'], sort_keys=True))
    return result


def test_mlcroissant_and_roc_validator_accept_both_valid_fixtures(validated):
    assert validated['versions'] == {'mlcroissant': '1.1.1', 'roc-validator': '0.13.1'}
    clean = {'croissant': None, 'ro-crate': []}
    assert validated['valid'] == {'bundle-wells': clean, 'folder-field': clean}


def test_mlcroissant_and_roc_validator_catch_their_own_mutations(validated):
    mutated = validated['mutated']
    assert 'FileObject(original.las)] Property "https://schema.org/contentUrl" is mandatory, but does not exist.' in mutated['croissant']
    assert mutated['ro-crate'] == ['ro-crate-1.1_8.4']  # Root Data Entity: datePublished


def test_mlcroissant_and_roc_validator_accept_both_written_folders_and_catch_the_mutations(validated):
    clean = {'croissant': None, 'ro-crate': []}
    assert validated['written'] == {'fixture': clean, 'minimum': clean}
    mutated = validated['written-mutated']
    assert 'FileObject(wells.parquet)] Property "https://schema.org/contentUrl" is mandatory, but does not exist.' in mutated['croissant']
    assert mutated['ro-crate'] == ['ro-crate-1.1_8.4']


def test_mlcroissant_and_roc_validator_accept_both_written_bundles(validated):
    clean = {'croissant': None, 'ro-crate': []}
    assert validated['written-bundles'] == {'licensed': clean, 'unlicensed': clean}


TOPS_ROWS = [{'name': 'Top Chalk', 'md': 100.5, 'tvd': None, 'source': 'picked'}, {'name': 'Base Chalk', 'md': 103.0, 'tvd': 102.9, 'source': None}]
TIME_DEPTH_ROWS = [{'depth': 0.0, 'time': 0.0}, {'depth': 0.96, 'time': 1.0}, {'depth': 1.91, 'time': 2.0}]
POINT_ROWS = [{'x': 1.0, 'y': 2.0, 'z': 3.0}, {'x': 4.0, 'y': 5.0, 'z': None}]
TABLE_RECORDS = {  # written from the asset fixtures; the rows by hand from their data files, nulls kept (Y-11)
    'tops': {'assets/0/well-tops': TOPS_ROWS},
    'trajectory': {'assets/0/deviation-survey': [{'md': 100.0, 'inclination': 0.0, 'azimuth': 0.0, 'tvd': None},
                                                 {'md': 200.0, 'inclination': 10.0, 'azimuth': 0.0, 'tvd': None},
                                                 {'md': 300.0, 'inclination': None, 'azimuth': None, 'tvd': None}]},
    'time-depth': {'assets/0/time-depth': TIME_DEPTH_ROWS},
    'points': {'assets/0/point-set': POINT_ROWS},
    'time-depth-null-velocity': {'assets/0/time-depth': TIME_DEPTH_ROWS},
}


def test_e147_s2b_mlcroissant_reads_each_written_table_as_its_rows(validated):
    """E147 s2b C3: each cited table bundle is 2.16, both validators accept it, and mlcroissant's records() gives the
    hand rows; a null velocity (not a field) leaves the depth and time rows whole."""
    tables = validated['tables']
    for label, expected in TABLE_RECORDS.items():
        assert tables[label] == {'version': '2.16.0', 'croissant': None, 'ro-crate': [], 'records': expected}, label


def test_e147_s2b_mlcroissant_reads_the_contract_fixture_s_two_tops_tables_apart(validated):
    """Y-8: the bundle-tables fixture's two tops assets read as their own rows."""
    assert validated['tables']['fixture'] == {'croissant': None, 'ro-crate': [], 'records': {
        'assets/0/well-tops': TOPS_ROWS,
        'assets/1/well-tops': [{'name': 'Top Sand', 'md': 210.25, 'tvd': 208.5, 'source': 'picked'},
                               {'name': 'Base Sand', 'md': 231.0, 'tvd': None, 'source': 'revised'}],
        'assets/2/time-depth': TIME_DEPTH_ROWS, 'assets/3/point-set': POINT_ROWS}}


def test_e147_s2b_a_wrong_member_path_gives_no_tops_rows(validated):
    """The records come from the jsonPath: under `$.top[*].name` mlcroissant 1.1.1's records() raises."""
    assert validated['tables-wrong-path'] == 'GenerationError'


def test_e147_s3_both_validators_accept_the_written_packs_and_mlcroissant_catches_a_missing_digest(validated):
    """E147 s3 C3: a pack with the notice (Apache-2.0, no `license`) and an open one (CC-BY-4.0, its SPDX URL) pass
    mlcroissant with 0 errors and roc-validator's required checks; so does the contract's starter-pack croissant. A
    distribution without its sha256 is mlcroissant's error."""
    assert validated['packs'] == {'notice': {'croissant': None, 'ro-crate': [], 'license': None},
                                  'open': {'croissant': None, 'ro-crate': [], 'license': 'https://spdx.org/licenses/CC-BY-4.0'},
                                  'fixture': {'croissant': None}}
    assert 'sha256' in validated['packs-mutated']['croissant']


EPISODE_A, EPISODE_B = 'episode-610d2047223cbad946050597edee1139', 'episode-ea531be7df5907affc7e2368fc59484d'
CHAIN, FROM = 'ref-da2fbb3481d67653be0f15b3701bc39b', 'ref-01651f18401e3159f90d8addf999bff3'
SHAPE_ONLY = object()


def turn(episode, mode, n, action, attempt=(None, None, None, None), ended=None, through=(None, None),
         behalf=(None, None), plan=(None, None), offered=None, instruction=SHAPE_ONLY):
    """One `turns` record as mlcroissant gives it: every field of the folder, a null for a place the line leaves null."""
    row = {'episode': episode, 'mode': mode, 'split': 'train', 'n': n,
           'attempt.chain': attempt[0], 'attempt.n': attempt[1], 'attempt.from': attempt[2], 'attempt.continued': attempt[3],
           'action.action_id': action[0], 'action.at': action[1], 'action.operation': action[2],
           'action.through.client': through[0], 'action.through.version': through[1],
           'action.on_behalf_of.kind': behalf[0], 'action.on_behalf_of.id': behalf[1],
           'action.plan.plan_sha256': plan[0], 'action.plan.evidence_sha256': plan[1], 'judgement.attempt_ended': ended,
           'omitted.parameters': 0, 'omitted.checks': 0, 'omitted.verdicts': 0, 'omitted.plan': 0, 'omitted.offered': offered}
    if instruction is not SHAPE_ONLY: row['action.instruction'] = instruction
    return row


REMAKE = ('act_ed96303918a149569353f76c343d920c', 1793275260.0, 'results/remake-run')
WELLS = ('act_12b927acd6c073a752699f0ec0dbfc81', 1793278800.0, 'table-imports/start')
UNITS = ('act_03e1fbe8d12150d5be6da1db55fcf611', 1793282400.0, 'table-imports/start')
SHALE = ('act_5e3f0c0a1d2b4c6e8f00112233445566', 1793275200.0, 'derive/ShaleVolume')
CLI = ('ophiolite-cli', '1.4.0')
EPISODE_RECORDS = {  # by hand from the work-turns fixtures' turns.jsonl (E160 s0 C2), which the folders carry byte for byte
    'episodes-shape': [
        turn(EPISODE_A, 'shape', 1, REMAKE, (CHAIN, 2, FROM, False), 'accepted'),
        turn(EPISODE_A, 'shape', 2, WELLS, (CHAIN, 3, None, True), 'superseded', offered=1),
        turn(EPISODE_A, 'shape', 3, UNITS, through=CLI, behalf=('person', 'person-3d20f00ad0da46054840dab16ae4da32'),
             plan=('f1' * 32, 'f2' * 32))],
    'episodes-auto': [
        turn(EPISODE_B, 'shape', 1, SHALE, through=CLI, instruction=None),
        turn(EPISODE_A, 'values', 1, REMAKE, (CHAIN, 2, FROM, False), 'withdrawn',
             instruction='Make it again with the published log'),
        turn(EPISODE_A, 'values', 2, WELLS, (CHAIN, 3, FROM, False), 'discarded', offered=1, instruction=None),
        turn(EPISODE_A, 'values', 3, UNITS, (CHAIN, 4, None, True), 'open', instruction=None)],
    'episodes-empty': [],
}


def test_e160_s0_mlcroissant_reads_each_episode_folder_as_its_turns(validated):
    """E160 s0 C3: the three work-episodes croissant.json fixtures pass mlcroissant 1.1.1 with 0 errors (the responsible-AI
    places and usageInfo included), and records('turns') gives every line's scalar places, a null where the line has one
    or lacks the object (a shape line in an auto folder has a null instruction); an empty turns.jsonl gives no record."""
    assert validated['episodes'] == {name: {'croissant': None, 'records': {'turns': rows}}
                                     for name, rows in EPISODE_RECORDS.items()}


def test_e160_s0_the_turn_records_come_from_the_transform_path(validated):
    """A field's transform.jsonPath decides its value: `attempt.chain` (sc:Text) read at `$.n` gives the attempt numbers
    as text."""
    assert validated['episodes-moved'] == ['2', '3', None]


# ---- the DataCite and PROV-JSON schemas, fetched by digest ---------------------------------------------------------

@pytest.fixture(scope='session')
def schema_cache(tmp_path_factory):
    return tmp_path_factory.mktemp('descriptor-schemas')


def fetched(cache, url, digest):
    """The schema at URL, fetched once per run (CL-1): unreachable skips, a wrong digest fails."""
    target = cache / digest
    if not target.exists():
        try:
            with urllib.request.urlopen(url, timeout=60) as response: data = response.read()
        except (urllib.error.URLError, OSError) as error:
            pytest.skip('CL-1: %s is unreachable (%s); this schema check did not run' % (url, error))
        if hashlib.sha256(data).hexdigest() != digest:
            pytest.fail('%s does not have the pinned SHA-256 %s; the pin is wrong, not the network' % (url, digest))
        target.write_bytes(data)
    return load(target)


def datacite_fragment(cache):
    schema = fetched(cache, *DATACITE)
    fragment = dict(schema, required=[r for r in schema['required'] if r != 'identifiers'])
    changed = sorted(key for key in set(schema) | set(fragment) if schema.get(key) != fragment.get(key))
    assert (changed, sorted(set(schema['required']) - set(fragment['required']))) == (['required'], ['identifiers'])
    return fragment


def errors(schema, cls, doc):
    return sorted(error.message for error in cls(schema).iter_errors(doc))


def test_the_datacite_fragment_of_both_fixtures_is_valid_and_titles_are_required(schema_cache):
    jsonschema = pytest.importorskip('jsonschema')
    fragment = datacite_fragment(schema_cache)
    for name in ('bundle-wells', 'folder-field'):
        assert errors(fragment, jsonschema.Draft7Validator, load(VALID / name / 'datacite.json')) == [], name
    doc = load(VALID / 'bundle-wells/datacite.json'); del doc['titles']
    assert errors(fragment, jsonschema.Draft7Validator, doc) == ["'titles' is a required property"]


def test_both_lineage_files_are_prov_json_and_an_entity_must_be_an_object(schema_cache):
    jsonschema = pytest.importorskip('jsonschema')
    schema = fetched(schema_cache, *PROV_JSON)
    for name, path in LINEAGE.items():
        assert errors(schema, jsonschema.Draft4Validator, load(VALID / name / path)) == [], name
    doc = load(VALID / 'bundle-wells/prov.json'); doc['entity'][next(iter(doc['entity']))] = 'not an entity'
    assert errors(schema, jsonschema.Draft4Validator, doc) == ["'not an entity' is not of type 'object'"]


@pytest.fixture(scope='module')
def written_here(tmp_path_factory):
    """E147 s1: the two cited folders written by this interpreter's SDK (its folder extra)."""
    pytest.importorskip('pandas'); pytest.importorskip('pyarrow'); pytest.importorskip('pyproj')
    namespace = {}
    exec(compile(WRITE, 'WRITE', 'exec'), namespace)
    return namespace['write_cited'](tmp_path_factory.mktemp('written-here'))


def test_both_written_folders_datacite_and_lineage_pass_their_schemas(schema_cache, written_here):
    jsonschema = pytest.importorskip('jsonschema')
    fragment, prov = datacite_fragment(schema_cache), fetched(schema_cache, *PROV_JSON)
    assert sorted(written_here) == ['fixture', 'minimum']
    for label, folder in written_here.items():
        assert errors(fragment, jsonschema.Draft7Validator, load(folder / 'datacite.json')) == [], label
        assert errors(prov, jsonschema.Draft4Validator, load(folder / 'lineage/prov.json')) == [], label
    assert load(written_here['minimum'] / 'datacite.json')['rightsList'][0]['rightsIdentifier'] == 'CC0-1.0'


def test_both_written_bundles_datacite_passes_the_fragment(schema_cache, tmp_path):
    """E147 s2 (C2): write_bundle's licensed and licence-null bundles, written by this interpreter's SDK."""
    jsonschema = pytest.importorskip('jsonschema')
    fragment = datacite_fragment(schema_cache)
    namespace = {}
    exec(compile(BUNDLE, 'BUNDLE', 'exec'), namespace)
    written = namespace['write_cited_bundles'](tmp_path)
    assert sorted(written) == ['licensed', 'unlicensed']
    for label, folder in written.items():
        assert errors(fragment, jsonschema.Draft7Validator, load(folder / 'datacite.json')) == [], label
    assert 'rightsList' not in load(written['unlicensed'] / 'datacite.json')
    assert load(written['licensed'] / 'datacite.json')['rightsList'][0]['rightsIdentifier'] == 'CC-BY-4.0'


def test_e147_s3_the_written_packs_and_the_pack_fixture_datacite_pass_the_fragment(schema_cache, tmp_path):
    """E147 s3 C3: the two packs starter.pack_descriptors writes, and the contract's starter-pack datacite.json."""
    jsonschema = pytest.importorskip('jsonschema')
    fragment = datacite_fragment(schema_cache)
    namespace = {'Path': Path}
    exec(compile(PACK, 'PACK', 'exec'), namespace)
    written = namespace['write_packs'](tmp_path)
    assert sorted(written) == ['notice', 'open']
    for label, folder in written.items():
        assert errors(fragment, jsonschema.Draft7Validator, load(folder / 'datacite.json')) == [], label
    assert errors(fragment, jsonschema.Draft7Validator, load(VALID / 'starter-pack/datacite.json')) == []
    assert 'rightsList' not in load(written['notice'] / 'datacite.json')
    assert load(written['open'] / 'datacite.json')['rightsList'][0]['rightsIdentifier'] == 'CC-BY-4.0'
    doc = load(written['open'] / 'datacite.json'); del doc['creators']
    assert errors(fragment, jsonschema.Draft7Validator, doc) == ["'creators' is a required property"]
