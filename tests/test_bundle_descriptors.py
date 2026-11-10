"""E147 s0 C2 (D3, D4): the bundle readers, pack and the CLI read the descriptors a manifest's citation lists and refuse
one that disagrees. Strategy: docs/program-2026-09-25/E147-s0-citable-release-COMMIT-STRATEGY.md D3, D4, C2 (X-5, X-6,
X-10..X-13, X-18).

    a  both valid fixtures: check() ok with the citation's rows, open_bundle lists no file as unlisted
    b  pack -> ZipFile.namelist() equals the literal list -> open -> ok (X-5, X-10)
    c  every case of fixtures/invalid/cases.json through open_bundle, check() and the zip reader, with its code and place
       (X-11, X-13); the reader cases' archive forms are refused before extraction
    d  archives with an unlisted root JSON, a listed descriptor as a link entry, or a malformed citation are refused
       before extraction: the staging folder is never made (X-5)
    e  the CLI: the default line in words; the code and `croissant.json:$.license` only with --details (X-6, X-18)
    f  a 2.14 bundle without a citation reports byte for byte as main's reader did: literals, and the frozen 2.14 tree
       (from this checkout's history) run beside this one on the 2.14 fixtures; a checkout without that history (the
       shallow hosted checkout, the exported SDK) compares with the tree's recorded outputs, which the tree must reproduce
    g  the frozen 2.14 reader on both fixtures: `file-unlisted` naming a descriptor, its pack refused, its zip reader
       refusing the archive (D4, X-12)
"""
import contextlib
import copy as copying
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest
from ophiolite import bundle
from ophiolite.bundle import DescriptorRefused, open_bundle, pack
from ophiolite.cli import entrypoint
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.folder import check

HERE = Path(str(files('ophiolite').joinpath('contracts/descriptors/v1')))
VALID = HERE / 'fixtures' / 'valid'
CASES = json.loads((HERE / 'fixtures/invalid/cases.json').read_text())['cases']
CONTRACT = [case for case in CASES if case['layer'] == 'contract']
READER = [case for case in CASES if case['layer'] == 'reader']
FOLDERS = Path(str(files('ophiolite').joinpath('contracts/folders/v1/fixtures/valid')))
RELEASED = Path(__file__).resolve().parent / 'fixtures' / 'released-bundles'
SDK = Path(__file__).resolve().parents[1]
# The frozen 2.14 reader: ophiolite-sdk/ophiolite as it was just before the commit that added the SDK's copy of the
# descriptors contract (main at E147 s0's open: bundle 2.14, E117 s1), read from this checkout's own history.
VENDORED = 'ophiolite-sdk/ophiolite/contracts/descriptors/v1/descriptors.py'
RECORD = Path(__file__).resolve().parent / 'fixtures' / 'e147-frozen-2-14-reader.json'  # that tree's outputs, for checkouts without it
RO, CR, DC, PROV = 'ro-crate-metadata.json', 'croissant.json', 'datacite.json', 'prov.json'
WELLS_FILES = [('assets/0/original.las', 'original'), ('assets/0/descriptor-GR.json', 'descriptor'), ('assets/0/curve-GR.json', 'normalized')]
FIELD_FILES = [('items/wells.parquet', 'item'), ('lineage/prov.json', 'lineage-prov')]
CITED = {'bundle-wells': [(PROV, 'citation-prov'), (RO, 'citation-descriptor'), (CR, 'citation-descriptor'), (DC, 'citation-descriptor')],
         'folder-field': [(RO, 'citation-descriptor'), (CR, 'citation-descriptor'), (DC, 'citation-descriptor')]}
SCHEMA = {'bundle-wells': None, 'folder-field': 'ophiolite.project-folder/2'}
ITEMS = {'bundle-wells': [], 'folder-field': [{'path': 'items/wells.parquet', 'kind': 'wells', 'osdu': {'kind': 'osdu:wks:master-data--Well:1.5.0'},
                                               'derived': 'manifest', 'verdict': 'ok'}]}
NAMELIST = {'bundle-wells': ['manifest.json', 'assets/0/curve-GR.json', 'assets/0/descriptor-GR.json', 'assets/0/original.las',
                             'croissant.json', 'datacite.json', 'prov.json', 'ro-crate-metadata.json'],
            'folder-field': ['manifest.json', 'croissant.json', 'datacite.json', 'items/wells.parquet', 'lineage/prov.json',
                             'ro-crate-metadata.json']}


def rows(base, verdicts=None):
    verdicts = verdicts or {}
    listed = (WELLS_FILES if base == 'bundle-wells' else FIELD_FILES) + CITED[base]
    return [{'path': p, 'role': r, 'verdict': verdicts.get(p, 'ok')} for p, r in listed]


def copy(tmp_path, base):
    shutil.copytree(VALID / base, tmp_path / base)
    return tmp_path / base


def place(case):
    """check()'s place for a case: the manifest's JSON path, the file, or `file:json path`."""
    if case['at'] == 'manifest.json': return case['path']
    return case['at'] if case['path'] is None else '%s:%s' % (case['at'], case['path'])


def zip_folder(folder, destination, names=None, extra=()):
    """An archive of FOLDER written by hand (pack refuses a damaged folder): manifest first, then NAMES (every file by
    default) in sorted order; EXTRA are (ZipInfo, bytes) entries appended as given."""
    names = names if names is not None else sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file())
    with zipfile.ZipFile(destination, 'w') as archive:
        for name in ['manifest.json'] + [n for n in names if n != 'manifest.json']:
            info = zipfile.ZipInfo(name, date_time=bundle.FIXED_TIME); info.external_attr = 0o100600 << 16
            archive.writestr(info, (folder / name).read_bytes())
        for info, data in extra: archive.writestr(info, data)
    return destination


@pytest.fixture
def no_staging(monkeypatch):
    """Fails the test if the zip reader makes its staging folder (it must refuse before extracting anything)."""
    made = []
    real = bundle.tempfile.mkdtemp
    def spy(*args, **kwargs):
        if kwargs.get('prefix') == 'ophiolite-bundle-': made.append(True)
        return real(*args, **kwargs)
    monkeypatch.setattr(bundle.tempfile, 'mkdtemp', spy)
    return made


# ---- a. the valid fixtures --------------------------------------------------------------------------------------------

@pytest.mark.parametrize('base', ['bundle-wells', 'folder-field'])
def test_a_check_is_ok_and_reports_the_citation_rows(base):
    assert check(VALID / base) == {'ok': True, 'verified': 'bytes', 'schema': SCHEMA[base], 'files': rows(base), 'items': ITEMS[base],
                                   'first_problem': None}


@pytest.mark.parametrize('base', ['bundle-wells', 'folder-field'])
def test_a_open_bundle_lists_nothing_as_unlisted_and_names_the_citation_files(base):
    opened = open_bundle(VALID / base)
    assert opened.unlisted == []
    assert opened.citation == [{'path': p, 'role': r} for p, r in CITED[base]]
    assert opened.summary()['unlisted_files'] == []


# ---- b. pack -> zip -> open --------------------------------------------------------------------------------------------

@pytest.mark.parametrize('base', ['bundle-wells', 'folder-field'])
def test_b_pack_writes_the_descriptors_and_the_archive_opens(tmp_path, base):
    archive = pack(VALID / base, tmp_path / (base + '.zip'))
    with zipfile.ZipFile(archive) as opened_zip: assert opened_zip.namelist() == NAMELIST[base]
    opened = open_bundle(archive)
    assert opened.unlisted == [] and opened.citation == [{'path': p, 'role': r} for p, r in CITED[base]]
    for name in (RO, CR, DC): assert (opened.path / name).read_bytes() == (VALID / base / name).read_bytes()


# ---- c. every case, through open_bundle, check() and the zip reader ---------------------------------------------------

def _at(document, keys):
    for key in keys[:-1]: document = document[key]
    return document, keys[-1]


def apply(case, folder):
    """The case's one change, written into FOLDER (a copy of its base)."""
    target = folder / case['file']
    if 'raw' in case: target.write_bytes(case['raw'].encode())
    elif 'raw_replace' in case:
        old, new = case['raw_replace']
        text = target.read_text(encoding='utf-8')
        assert old in text, case['name']
        target.write_text(text.replace(old, new, 1), encoding='utf-8')
    elif 'set' in case or 'delete' in case:
        document = json.loads(target.read_bytes())
        for keys, value in case.get('set', []):
            spot, key = _at(document, keys)
            if isinstance(spot, list) and key == len(spot): spot.append(copying.deepcopy(value))
            else: spot[key] = copying.deepcopy(value)
        for keys in case.get('delete', []):
            spot, key = _at(document, keys)
            del spot[key]
        target.write_text(json.dumps(document, indent=2), encoding='utf-8')
    return folder


@pytest.mark.parametrize('case', CONTRACT, ids=[case['name'] for case in CONTRACT])
def test_c_each_contract_case_is_refused_by_open_bundle_check_and_the_zip_reader(tmp_path, case):
    folder = apply(case, copy(tmp_path, case['base']))
    with pytest.raises(DescriptorRefused) as caught: open_bundle(folder)
    assert (caught.value.code, caught.value.file, caught.value.json_path) == (case['code'], case['at'], case['path'])
    problem = check(folder)['first_problem']
    assert {k: problem[k] for k in ('code', 'path')} == {'code': case['code'], 'path': place(case)}
    assert problem['sentence'] == caught.value.sentence and '$' not in problem['sentence']
    with pytest.raises(DescriptorRefused) as zipped: open_bundle(zip_folder(folder, tmp_path / 'case.zip'))
    assert (zipped.value.code, zipped.value.file, zipped.value.json_path) == (case['code'], case['at'], case['path'])


def _reader_case(case, folder, monkeypatch, outside):
    """The reader's own change: the file removed, made a link or a directory, or the limit set so the file is over it."""
    target = folder / case['file']
    if case.get('remove'): target.unlink()
    elif case.get('reader') == 'link':
        shutil.copy(target, outside / case['file']); target.unlink(); target.symlink_to(outside / case['file'])
    elif case.get('reader') == 'directory':
        target.unlink(); target.mkdir(); (target / 'inside.json').write_text('{}')
    elif case.get('reader') == 'over-file-limit':
        limit = target.stat().st_size - 1
        earlier = [folder / p for p, _ in WELLS_FILES] + [folder / PROV]
        assert all(p.stat().st_size <= limit for p in earlier)  # the descriptor is the first file over it
        monkeypatch.setattr(bundle, 'MAX_FILE_BYTES', limit)
    elif case.get('reader') == 'over-total':
        before = sum((folder / p).stat().st_size for p, _ in FIELD_FILES) + (folder / RO).stat().st_size
        monkeypatch.setattr(bundle, 'MAX_TOTAL_BYTES', before + target.stat().st_size - 1)  # croissant.json takes it over
    else: apply(case, folder)
    return folder


@pytest.mark.parametrize('case', READER, ids=[case['name'] for case in READER])
def test_c_each_reader_case_is_refused_by_open_bundle_and_check_with_its_code_and_file(tmp_path, monkeypatch, case):
    (tmp_path / 'outside').mkdir()
    folder = _reader_case(case, copy(tmp_path, case['base']), monkeypatch, tmp_path / 'outside')
    with pytest.raises(DescriptorRefused) as caught: open_bundle(folder)
    assert (caught.value.code, caught.value.file, caught.value.json_path) == (case['code'], case['at'], None)
    report = check(folder)
    assert report['first_problem'] == {'code': case['code'], 'path': case['at'],
                                       **({'sentence': caught.value.sentence} if case['code'] == 'descriptor-unreadable' else {})}
    if case['base'] == 'folder-field':  # a /2 folder's check lists every row with its verdict
        assert next(r for r in report['files'] if r['path'] == case['at'])['verdict'] == case['code']


ZIP_REFUSALS = {  # the reader cases as archives: what the zip reader says, before extraction except for the PROV digest
    'a-listed-descriptor-missing': 'The archive holds entries its manifest does not list, or lacks listed ones.',
    'a-descriptor-that-is-a-link': 'An archive entry is a link, folder or special file.',
    'a-descriptor-that-is-a-directory': 'An archive entry name is unsafe or outside the bundle layout.',  # `datacite.json/`
    'a-descriptor-over-the-file-limit': 'An archive entry exceeds the supported size.',
    'the-descriptors-over-the-total': 'The archive exceeds the supported total size.'}


@pytest.mark.parametrize('case', READER, ids=[case['name'] for case in READER])
def test_c_each_reader_case_as_an_archive(tmp_path, monkeypatch, no_staging, case):
    folder = copy(tmp_path, case['base'])
    names = sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file())
    extra = []
    if case.get('remove'): names.remove(case['file'])
    elif case.get('reader') in ('link', 'directory'):
        names.remove(case['file'])
        info = zipfile.ZipInfo(case['file'] + ('/' if case['reader'] == 'directory' else ''), date_time=bundle.FIXED_TIME)
        info.external_attr = ((stat.S_IFLNK | 0o777) if case['reader'] == 'link' else (stat.S_IFDIR | 0o700)) << 16
        extra.append((info, b'/etc/passwd' if case['reader'] == 'link' else b''))
    elif case.get('reader') == 'over-file-limit':
        monkeypatch.setattr(bundle, 'MAX_FILE_BYTES', (folder / case['file']).stat().st_size - 1)
    elif case.get('reader') == 'over-total':
        monkeypatch.setattr(bundle, 'MAX_TOTAL_BYTES', sum((folder / n).stat().st_size for n in names) - 1)
    else: apply(case, folder)
    archive = zip_folder(folder, tmp_path / 'case.zip', names, extra)
    if case['name'] == 'the-prov-digest-differs':
        with pytest.raises(DescriptorRefused) as caught: open_bundle(archive)
        assert (caught.value.code, caught.value.file) == ('file-digest', PROV)
        return
    with pytest.raises(VerificationFailed) as caught: open_bundle(archive)
    assert str(caught.value) == ZIP_REFUSALS[case['name']]
    assert no_staging == []


def test_c_the_cases_cover_both_layers():
    assert len(CONTRACT) == 41 and len(READER) == 6  # E147 s1: the two one-identifier cases (X-4), no-description (rev 3)
    assert [c['name'] for c in CONTRACT if c['base'] == 'bundle-tables'] == [  # E147 s2b: the three bundle-table cases
        'bundle-table-json-path', 'bundle-table-missing', 'bundle-table-column']


STARTER = [case for case in CASES if case['layer'] == 'starter']


def test_c_the_starter_pack_cases_are_refused_by_the_vendored_contract():
    # E147 s3 C1b: the nine pack cases (layer starter, strategy V-1) through verify_starter, by count and code
    contract = bundle._descriptors_contract()
    pack = VALID / 'starter-pack'
    refused = []
    for case in STARTER:
        named = {name: (pack / name).read_bytes() for name in ('starter.json', 'evidence.json', RO, CR, DC)}
        document = json.loads(named[case['file']])
        for keys, value in case.get('set', []):
            place = document
            for key in keys[:-1]: place = place[key]
            if isinstance(place, list) and keys[-1] == len(place): place.append(value)
            else: place[keys[-1]] = value
        for keys in case.get('delete', []):
            place = document
            for key in keys[:-1]: place = place[key]
            del place[keys[-1]]
        named[case['file']] = json.dumps(document).encode()
        starter, record = json.loads(named.pop('starter.json')), json.loads(named.pop('evidence.json'))['record']
        with pytest.raises(contract.DescriptorError) as caught:
            contract.verify_starter(starter, record, named)
        refused.append((caught.value.code, caught.value.path) == (case['code'], case['path']))
    assert len(STARTER) == 9 and all(refused)
    assert all('set' in case or 'delete' in case for case in STARTER)


# E147 s2b T9 (Y-7): a cited tops bundle written by the E147 s2 code is 2.15, with no record set; this reader
# expects tables only from 2.16 on, so it still opens and checks, as a folder and as an archive.
CITED_2_15 = Path(__file__).resolve().parent / 'fixtures' / 'cited-2.15-tops'
TOPS_FILES = [('assets/0/original.csv', 'original'), ('assets/0/descriptor.json', 'descriptor'), ('assets/0/data.json', 'normalized')]


def test_c_a_cited_2_15_tops_bundle_opens_and_checks_as_a_folder_and_an_archive(tmp_path):
    assert json.loads((CITED_2_15 / 'manifest.json').read_bytes())['bundle_version'] == '2.15.0'
    assert 'recordSet' not in json.loads((CITED_2_15 / CR).read_bytes())
    cited = [{'path': p, 'role': r} for p, r in [(RO, 'citation-descriptor'), (CR, 'citation-descriptor'), (DC, 'citation-descriptor')]]
    assert check(CITED_2_15) == {'ok': True, 'verified': 'bytes', 'schema': None, 'items': [], 'first_problem': None,
                                 'files': [{**row, 'verdict': 'ok'} for row in [{'path': p, 'role': r} for p, r in TOPS_FILES] + cited]}
    opened = open_bundle(CITED_2_15)
    assert (opened.unlisted, opened.citation) == ([], cited)
    archive = pack(CITED_2_15, tmp_path / 'tops.zip')
    with zipfile.ZipFile(archive) as opened_zip:
        assert opened_zip.namelist() == ['manifest.json', 'assets/0/data.json', 'assets/0/descriptor.json', 'assets/0/original.csv',
                                         CR, DC, RO]
    opened = open_bundle(archive)
    assert (opened.unlisted, opened.citation) == ([], cited)
    assert run('bundle', 'check', str(archive))[0] == 0


# ---- d. archives refused before extraction ----------------------------------------------------------------------------

def test_d_an_unlisted_root_json_is_refused_before_extraction(tmp_path, no_staging):
    folder = copy(tmp_path, 'bundle-wells')
    (folder / 'notes.json').write_text('{}')
    with pytest.raises(VerificationFailed, match='outside the bundle layout'): open_bundle(zip_folder(folder, tmp_path / 'a.zip'))
    (folder / 'notes.json').unlink()
    manifest = json.loads((folder / 'manifest.json').read_text())
    manifest['citation']['descriptors'] = [RO, DC]  # croissant.json is in the archive but not listed
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    with pytest.raises(VerificationFailed, match='does not list'): open_bundle(zip_folder(folder, tmp_path / 'b.zip'))
    assert no_staging == []


def test_d_a_descriptor_link_entry_is_refused_before_extraction(tmp_path, no_staging):
    folder = copy(tmp_path, 'folder-field')
    names = sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name != CR)
    info = zipfile.ZipInfo(CR, date_time=bundle.FIXED_TIME); info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(VerificationFailed, match='link, folder or special file'):
        open_bundle(zip_folder(folder, tmp_path / 'a.zip', names, [(info, b'../../etc/passwd')]))
    assert no_staging == []


def test_d_a_malformed_citation_is_refused_before_extraction(tmp_path, no_staging):
    folder = copy(tmp_path, 'bundle-wells')
    manifest = json.loads((folder / 'manifest.json').read_text())
    manifest['citation']['descriptors'].append('dcat.json')
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    with pytest.raises(DescriptorRefused) as caught: open_bundle(zip_folder(folder, tmp_path / 'a.zip'))
    assert (caught.value.code, caught.value.path) == ('citation-schema', '$.citation.descriptors[3]')
    assert no_staging == []


# ---- e. the CLI ----------------------------------------------------------------------------------------------------------

def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try: entrypoint(list(argv)); code = 0
        except SystemExit as exit_: code = exit_.code or 0
    return code, out.getvalue()


LICENCE = {'bundle-wells': next(c for c in CASES if c['name'] == 'the-licence-in-lower-case'),
           'folder-field': next(c for c in CASES if c['name'] == 'a-licence-when-the-licence-is-null')}
SAID = {'bundle-wells': 'Bundle not verified: the licence in croissant.json disagrees with the manifest.\n',
        'folder-field': 'Project folder not verified: the licence in croissant.json disagrees with the manifest.\n'}


@pytest.mark.parametrize('base', ['bundle-wells', 'folder-field'])
def test_e_the_default_line_is_in_words_and_the_place_only_with_details(tmp_path, base):
    folder = apply(LICENCE[base], copy(tmp_path, base))
    assert run('bundle', 'check', str(folder)) == (1, SAID[base])
    code, said = run('bundle', 'check', str(folder), '--details')
    assert code == 1 and said.startswith(SAID[base])
    assert '  first problem: descriptor-disagrees at croissant.json:$.license\n' in said
    code, said = run('bundle', 'check', str(folder), '--json')
    document = json.loads(said)
    found = document['error'] if 'error' in document else document['first_problem']
    assert code == 1 and (found['code'], found['path']) == ('descriptor-disagrees', 'croissant.json:$.license')


def test_e_an_archive_says_the_same_line(tmp_path):
    folder = apply(LICENCE['bundle-wells'], copy(tmp_path, 'bundle-wells'))
    assert run('bundle', 'check', str(zip_folder(folder, tmp_path / 'a.zip'))) == (1, SAID['bundle-wells'])


def test_e_a_missing_descriptor_says_where_in_words(tmp_path):
    folder = copy(tmp_path, 'folder-field')
    (folder / DC).unlink()
    assert run('bundle', 'check', str(folder)) == (1, 'Project folder not verified: datacite.json: it is missing.\n')
    folder = copy(tmp_path, 'bundle-wells')
    (folder / DC).unlink()
    assert run('bundle', 'check', str(folder)) == (1, 'Bundle not verified: datacite.json is missing or has the wrong size.\n')


@pytest.mark.parametrize('base', ['bundle-wells', 'folder-field'])
def test_e_a_valid_fixture_is_verified(base):
    code, said = run('bundle', 'check', str(VALID / base))
    assert code == 0 and said.startswith(('Bundle verified: 1 exact revisions', 'Project folder verified: 1 item (wells, 4 rows)'))


# ---- f. a 2.14 bundle without a citation, byte for byte ---------------------------------------------------------------

def bundle_2_14(tmp_path):
    """bundle-wells as main wrote it: bundle 2.14, no citation, no media types, no descriptors and no prov.json."""
    folder = copy(tmp_path, 'bundle-wells')
    manifest = json.loads((folder / 'manifest.json').read_text())
    manifest['bundle_version'] = '2.14.0'
    del manifest['citation']
    for row in manifest['assets'][0]['files']: del row['media_type']
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    for name in (RO, CR, DC, PROV): (folder / name).unlink()
    return folder


def test_f_a_2_14_bundle_reports_as_main_did(tmp_path):
    folder = bundle_2_14(tmp_path)
    assert check(folder) == {'ok': True, 'verified': 'bytes', 'schema': None, 'files': rows('bundle-wells')[:3], 'items': [], 'first_problem': None}
    assert run('bundle', 'check', str(folder)) == (0, 'Bundle verified: 1 exact revisions, 1 curves, 0 other data. Checksums show integrity, not authorship.\n')
    archive = pack(folder, tmp_path / 'a.zip')
    with zipfile.ZipFile(archive) as opened_zip: assert opened_zip.namelist() == ['manifest.json'] + sorted(p for p, _ in WELLS_FILES)
    (folder / CR).write_bytes((VALID / 'bundle-wells' / CR).read_bytes())  # a root descriptor a 2.14 manifest does not list
    assert check(folder)['first_problem'] == {'code': 'file-unlisted', 'path': CR}
    with pytest.raises(Refused, match=r'does not list \(croissant.json\)'): pack(folder, tmp_path / 'b.zip')


SCRIPT = r'''
import contextlib, hashlib, io, json, sys, zipfile
sys.path.insert(0, sys.argv[1])
import ophiolite
assert ophiolite.__file__.startswith(sys.argv[1]), ophiolite.__file__
from ophiolite.bundle import open_bundle, pack
from ophiolite.folder import check
from ophiolite.cli import entrypoint
def cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try: entrypoint(list(argv)); code = 0
        except SystemExit as exit_: code = exit_.code or 0
    return [code, out.getvalue()]
def attempt(call):
    try: return ['ok', call()]
    except Exception as error: return [type(error).__name__, str(error)]
results = {}
for n, target in enumerate(json.loads(sys.argv[2])):
    archive = '%s/%d.zip' % (sys.argv[3], n)
    def packed():
        pack(target, archive)
        with open(archive, 'rb') as handle: data = handle.read()
        with zipfile.ZipFile(archive) as z: names = z.namelist()
        return [hashlib.sha256(data).hexdigest(), names]
    def opened(path):
        found = open_bundle(path)
        return [found.summary(), found.unlisted]
    results[target] = {'check': check(target), 'open': attempt(lambda: opened(target)), 'pack': attempt(packed),
                       'zip': attempt(lambda: opened(archive)), 'zip-new': attempt(lambda: opened(sys.argv[4] + '/%d.zip' % n)) if len(sys.argv) > 4 else None,
                       'cli': [cli('bundle', 'check', target), cli('bundle', 'check', target, '--details'), cli('bundle', 'check', target, '--json')]}
print(json.dumps(results, sort_keys=True, default=str))
'''


@pytest.fixture(scope='module')
def frozen(tmp_path_factory):
    """The 2.14 reader (VENDORED's comment), never from the network; None when that tree cannot be produced (no git,
    or a history without the commit: the shallow hosted checkout, the exported SDK), and then RECORD stands in."""
    def git(where, *argv):
        return subprocess.run(['git', '-C', str(where)] + list(argv), capture_output=True, check=True).stdout
    try:
        top = git(SDK, 'rev-parse', '--show-toplevel').decode().strip()
        added = git(top, 'log', '--diff-filter=A', '--format=%H', '--', VENDORED).decode().split()
        if not added: raise subprocess.CalledProcessError(1, 'git log')
        data = git(top, 'archive', '--format=tar', added[-1] + '^', 'ophiolite-sdk/ophiolite')
    except (OSError, subprocess.CalledProcessError) as error:
        if os.environ.get('E147_RECORD') == '1': pytest.fail('E147_RECORD needs the frozen 2.14 tree (%s)' % type(error).__name__)
        print('E147 s0: the frozen 2.14 tree is not in this checkout (%s); its recorded outputs stand in' % type(error).__name__)
        yield None
        return
    root = tmp_path_factory.mktemp('frozen-2-14')
    with tarfile.open(fileobj=io.BytesIO(data)) as tar: tar.extractall(root, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
    assert (root / 'ophiolite-sdk/ophiolite/bundle.py').is_file() and not (root / 'ophiolite-sdk/ophiolite/contracts/descriptors').exists()
    yield root / 'ophiolite-sdk'
    shutil.rmtree(root, ignore_errors=True)


def run_reader(sdk_root, targets, out, new_zips=None):
    out.mkdir(exist_ok=True)
    argv = [sys.executable, '-c', SCRIPT, str(sdk_root), json.dumps([str(t) for t in targets]), str(out)] + ([str(new_zips)] if new_zips else [])
    found = subprocess.run(argv, capture_output=True, text=True, cwd=out, timeout=600)
    assert found.returncode == 0, found.stderr[-2000:]
    return json.loads(found.stdout)


def normal(found, tmp_path):
    """The reader's outputs with this run's folders named, so a recorded run compares with a live one."""
    text = json.dumps(found, sort_keys=True)
    for root, name in ((tmp_path, '<tmp>'), (FOLDERS, '<folders>'), (RELEASED, '<released>'), (SDK, '<sdk>')): text = text.replace(str(root), name)
    return json.loads(text)


def frozen_reader(test, frozen, targets, tmp_path, new_zips=None):
    """The frozen 2.14 reader's outputs: run from the tree where this checkout has it, and then equal to RECORD
    (E147_RECORD=1 rewrites RECORD's entry instead); RECORD itself where the tree is not in the checkout."""
    recorded = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    if frozen is None: return recorded[test]
    found = normal(run_reader(frozen, targets, tmp_path / 'old', new_zips), tmp_path)
    if os.environ.get('E147_RECORD') == '1':
        recorded[test] = found
        RECORD.write_text(json.dumps(recorded, indent=1, sort_keys=True) + '\n')
    assert found == recorded[test]
    return found


def test_f_main_and_this_reader_report_the_2_14_fixtures_byte_for_byte(tmp_path, frozen):
    targets = [FOLDERS / name for name in sorted(os.listdir(FOLDERS))] + [RELEASED / '2.0', RELEASED / '2.11', bundle_2_14(tmp_path)]
    unlisted = tmp_path / 'unlisted'
    shutil.copytree(targets[-1], unlisted)
    (unlisted / CR).write_bytes((VALID / 'bundle-wells' / CR).read_bytes())  # an unlisted root descriptor beside 2.14
    targets.append(unlisted)
    old, new = frozen_reader('f', frozen, targets, tmp_path), normal(run_reader(SDK, targets, tmp_path / 'new'), tmp_path)
    assert sorted(old) == sorted(normal([str(t) for t in targets], tmp_path)) == sorted(new)
    for target in old: assert new[target] == old[target], target
    assert old['<tmp>/bundle-wells']['check']['ok'] and old['<tmp>/unlisted']['check']['first_problem'] == {'code': 'file-unlisted', 'path': CR}


# ---- g. the frozen 2.14 reader on the 2.15 fixtures (D4) ----------------------------------------------------------------

def test_g_the_2_14_reader_names_the_descriptors_unlisted_and_refuses_to_pack(tmp_path, frozen):
    targets = [copy(tmp_path, 'bundle-wells'), copy(tmp_path, 'folder-field')]
    new_zips = tmp_path / 'new'; new_zips.mkdir()
    for n, target in enumerate(targets): pack(target, new_zips / ('%d.zip' % n))
    found = frozen_reader('g', frozen, targets, tmp_path, new_zips)
    wells, field = found['<tmp>/bundle-wells'], found['<tmp>/folder-field']
    assert wells['check']['first_problem'] == {'code': 'file-unlisted', 'path': CR}
    assert field['check']['first_problem'] == {'code': 'file-unlisted', 'path': CR}
    assert [r['path'] for r in wells['check']['files'] if r['verdict'] == 'file-unlisted'] == [CR, DC, PROV, RO]
    assert [r['path'] for r in field['check']['files'] if r['verdict'] == 'file-unlisted'] == [CR, DC, RO]
    assert wells['open'][1][1] == [CR, DC, PROV, RO] and field['open'][1][1] == [CR, DC, RO]
    for result in (wells, field):
        assert result['pack'][0] == 'Refused' and 'does not list (croissant.json, datacite.json' in result['pack'][1]
        assert result['zip-new'] == ['VerificationFailed', 'An archive entry name is unsafe or outside the bundle layout.']
    # the 2.14 CLI checks a project folder by ophiolite.folder.check (the descriptors unlisted, exit 1); a server bundle
    # goes through open_bundle, which reports unlisted files only in its summary, as for any stray file in 2.14
    assert field['cli'][0] == [1, 'Project folder not verified: croissant.json: the manifest does not list it.\n']
