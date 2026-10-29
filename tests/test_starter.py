"""E129 Sa C3 (strategy rev 4, D1-D3; R9-R11, O3): a starter pack definition, its decisions, the evidence each input is
bound to and the computed licence, all offline. Literal bytes and documents written in this file (the public SDK unit
lane has no Integration file); every refusal is asserted by its exact sentence.

Mutations (recorded in the E129 Sa Validation Record): the required-topic loop drops `names`; each LAS check removed in
turn; the depth-reference mapping dropped; the duplicate-pair check removed; the bytes comparison removed; the tombstone
check removed; the any-required attribution rule replaced by the first input's; share_alike taken from the first input;
the duplicate-source check removed; the names value comparison removed."""
import copy
import hashlib
import json

import pytest

from ophiolite import starter
from ophiolite.errors import Refused

LAS = '''~Version Information
 VERS.                 2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0
 WRAP.                  NO : ONE LINE PER DEPTH STEP
~Well Information
 STRT.{u}             {start} : START DEPTH
 STOP.{u}             {stop} : STOP DEPTH
 STEP.{u}                0.5 : STEP
 NULL.             {null} : NULL VALUE
 WELL.               {well} : WELL
 XCOORD.M         500000.0 : X COORDINATE
 YCOORD.M              0.0 : Y COORDINATE
~Curve Information
 DEPT.{u}                    : DEPTH
 GR  .GAPI                 : GAMMA RAY
~ASCII
{start}   45.1
{stop}   46.0
'''


def las(well, start='1000.0', stop='1000.5', u='M', null='-999.25'):
    return LAS.format(well=well, start=start, stop=stop, u=u, null=null).encode()


TOPS = b'name,md\nAlpha,1000.5\nBeta,1001.5\nGamma,1002.0\n'
DEVIATION = b'md,inclination,azimuth\n1000.0,0.0,0.0\n1001.0,1.0,45.0\n'
RID, PACK = 'ophiolite-synthetic/two-wells', 'ophiolite-synthetic/two-wells/starter'
RUN = {'checked_at': '2026-10-28T00:00:00Z', 'tool_version': '0.9.0'}
APACHE = {'name': 'Apache License 2.0', 'spdx': 'Apache-2.0', 'url': 'https://www.apache.org/licenses/LICENSE-2.0', 'redistribution': 'allowed', 'attribution': 'required'}
VALUES = {'crs': ('EPSG:32631', 'EPSG:32632'), 'vertical-datum': ('MSL', 'MSL'), 'depth-reference': ('rotary table', 'kelly bushing'),
          'depth-kind': ('MD', 'MD'), 'units': ('m', 'm'), 'nulls': ('-999.25', '-999.25'), 'names': ('SYN-1', 'SYN-2')}


def sha(raw): return hashlib.sha256(raw).hexdigest()


def fresh(tmp_path, name):
    (tmp_path / name).mkdir()
    return tmp_path / name


def files():
    return {'syn-1.las': las('SYN-1'), 'syn-2.las': las('SYN-2', '1500.0', '1500.5'), 'syn-1-tops.csv': TOPS, 'syn-1-deviation.csv': DEVIATION}


def made(tmp_path, raw=None, edit=None):
    """A definition folder in TMP_PATH, with a catalogue, a verification and a deposit custody document beside it."""
    raw = raw or files()
    (tmp_path / 'inputs').mkdir(exist_ok=True)
    for name, data in raw.items(): (tmp_path / 'inputs' / name).write_bytes(data)
    key = 'mirror/%s/%s/syn-1-tops.csv' % (RID, sha(raw['syn-1-tops.csv']))
    def verified(name): return {'as': 'verified', 'verifier_run': dict(RUN), 'path': 'logs/%s' % name}
    inputs = [{'name': n, 'file': 'inputs/%s' % n, 'sha256': sha(raw[n]), 'bytes': len(raw[n]), 'well': 'SYN-1' if n.startswith('syn-1') else 'SYN-2',
               'held': {'as': 'deposited', 'key': key} if n == 'syn-1-tops.csv' else verified(n)} for n in raw]
    for i in inputs:
        if i['name'] == 'syn-1-tops.csv': i['declare'] = {'depth_basis': 'same-as-log'}
        if i['name'] == 'syn-1-deviation.csv': i['declare'] = {'azimuth_reference': 'grid-north'}
    defn = {'format': starter.DEFINITION, 'id': PACK, 'record_id': RID, 'title': 'Two synthetic wells', 'summary': 'Two wells, their tops and a deviation survey.',
            'built_at': '2026-10-28T00:00:00Z', 'recipe': {'id': 'ophiolite.starter/a', 'repository': 'https://github.com/ophiolite-labs/arraybridge', 'commit': 'a' * 40},
            'inputs': inputs, 'targets': ['python'],
            'contents': [{'kind': 'wellbore-logs', 'ids': ['SYN-1', 'SYN-2']}, {'kind': 'tops', 'ids': ['SYN-1']}, {'kind': 'wellbore-paths', 'ids': ['SYN-1']}],
            'decisions': [{'topic': t, 'subject': w, 'value': v[n], 'source': 'chosen' if t == 'crs' else 'data', **({'note': 'the zone of its longitude'} if t == 'crs' else {})}
                          for t, v in VALUES.items() for n, w in enumerate(('SYN-1', 'SYN-2'))]}
    if edit: edit(defn)
    (tmp_path / 'definition.json').write_text(json.dumps(defn))
    (tmp_path / 'records.json').write_text(json.dumps({'catalog': {'source_commit': None, 'verification_commit': None, 'built_at': '2026-10-28T00:00:00Z', 'records_digest': 'd' * 64},
                                                       'records': [{'id': RID, 'title': 'Two synthetic wells', 'licence': dict(APACHE)}]}))
    (tmp_path / 'verification').mkdir(exist_ok=True)
    (tmp_path / 'verification' / 'ophiolite-synthetic__two-wells.json').write_text(json.dumps(
        {'record_id': RID, **RUN, 'level': 2, 'checks': [], 'files': [{'path': 'logs/%s' % n, 'bytes': len(raw[n]), 'sha256': sha(raw[n])} for n in raw if n != 'syn-1-tops.csv']}))
    (tmp_path / 'custody').mkdir(exist_ok=True)
    tops = raw['syn-1-tops.csv']
    deposit = {'format': 'osd.custody/2', 'record_id': RID, 'path': 'syn-1-tops.csv', 'origin_href': None, 'key': key, 'href': 'https://mirror.example.org/' + key,
               'sha256': sha(tops), 'bytes': len(tops), 'copied_at': '2026-10-28T00:00:00Z', 'licence': dict(APACHE), 'licence_text_sha256': None,
               'attribution': ['Tops of SYN-1, deposited by the maintainer.'], 'takedown': 'https://example.org/takedown', 'removal': {'state': 'held'},
               'deposit': {'obtained_at': '2026-10-28T00:00:00Z', 'by': 'maintainer', 'publisher_page_url': 'https://example.org/p', 'publisher_page_sha256': 'e' * 64, 'licence_text_sha256': 'f' * 64}}
    (tmp_path / 'custody' / (sha(tops) + '.json')).write_text(json.dumps(deposit))
    return tmp_path


def judged(folder):
    """definition -> local -> profiles -> heads -> decisions, as build runs them."""
    defn = starter.definition(folder / 'definition.json')
    raw = starter.local(defn)
    kinds = {n: starter.PROFILE_KIND[starter.profile(n, b)] for n, b in raw.items()}
    heads = {n: starter.las_head(n, b) for n, b in raw.items() if kinds[n] == 'wellbore-logs'}
    return defn, starter.decisions(defn, kinds, heads)


def refused(fn, *args):
    with pytest.raises(Refused) as caught: fn(*args)
    return str(caught.value)


def test_the_fourteen_decisions_are_accepted_and_give_the_literal_declarations(tmp_path):
    defn, (declared, crs) = judged(made(tmp_path))
    assert len(defn['decisions']) == 14 and [c['count'] for c in defn['contents']] == [2, 1, 1]
    assert declared == {'syn-1-tops.csv': {'depth_basis': 'same-as-log', 'depth_unit': 'm', 'depth_datum': 'rotary table'},
                        'syn-1-deviation.csv': {'azimuth_reference': 'grid-north', 'depth_unit': 'm', 'depth_datum': 'rotary table'}}
    assert crs == {'SYN-1': 'EPSG:32631', 'SYN-2': 'EPSG:32632'}


@pytest.mark.parametrize('topic', starter.WELL_TOPICS)
def test_omitting_each_required_topic_refuses_naming_it(tmp_path, topic):
    def drop(d): d['decisions'] = [x for x in d['decisions'] if (x['topic'], x['subject']) != (topic, 'SYN-2')]
    assert refused(judged, made(tmp_path, edit=drop)) == 'Decision %s for SYN-2 (wellbore-logs) is missing. Nothing was sent.' % topic


LAS_CASES = {
    'depth unit': ({'u': 'FT'}, 'syn-1.las has depth unit FT, not m as the units decision says. Nothing was sent.'),
    'null': ({'null': '-9999'}, 'syn-1.las has NULL -9999.0, not -999.25 as the nulls decision says. Nothing was sent.'),
    'well': ({'well': 'SYN-X'}, 'syn-1.las names well SYN-X, not SYN-1 as the names decision says. Nothing was sent.'),
}


@pytest.mark.parametrize('case', sorted(LAS_CASES))
def test_each_las_check_refuses_a_mismatching_file(tmp_path, case):
    change, sentence = LAS_CASES[case]
    raw = files()
    raw['syn-1.las'] = las(**{'well': 'SYN-1', **change})
    assert refused(judged, made(tmp_path, raw)) == sentence


def test_a_names_value_other_than_the_subject_refuses(tmp_path):
    def rename(d): next(x for x in d['decisions'] if (x['topic'], x['subject']) == ('names', 'SYN-1'))['value'] = 'SYN-9'
    assert refused(judged, made(tmp_path, edit=rename)) == "names for SYN-1: only the well's own name is supported in this version. Nothing was sent."


def test_a_second_value_and_an_unknown_subject_refuse(tmp_path):
    def twice(d): d['decisions'].append(dict(d['decisions'][0], value='EPSG:4326'))
    assert refused(judged, made(fresh(tmp_path, 'a'), edit=twice)) == 'Decision crs for SYN-1 has two values. Nothing was sent.'
    def stranger(d): d['decisions'].append(dict(d['decisions'][0], subject='SYN-3'))
    assert refused(judged, made(fresh(tmp_path, 'b'), edit=stranger)) == 'Decision crs names SYN-3, which is not an object of contents. Nothing was sent.'


def test_a_declare_that_a_topic_fills_refuses(tmp_path):
    def both(d): next(i for i in d['inputs'] if i['name'] == 'syn-1-tops.csv')['declare']['depth_unit'] = 'ft'
    assert refused(judged, made(tmp_path, edit=both)) == 'depth_unit is given by the units decision. Nothing was sent.'


def test_a_changed_local_byte_refuses_before_anything(tmp_path):
    folder = made(tmp_path)
    (folder / 'inputs' / 'syn-2.las').write_bytes(las('SYN-2', '1500.0', '1500.6'))
    assert refused(judged, folder) == 'syn-2.las is not the file the definition names: its SHA-256 differs. Nothing was sent.'


def evidence(folder):
    defn = starter.definition(folder / 'definition.json')
    return defn, starter.bound(defn, folder / 'records.json', folder / 'verification', folder / 'custody')


def test_each_input_is_bound_to_its_evidence(tmp_path):
    defn, (ev, read) = evidence(made(tmp_path))
    assert ev['record']['id'] == RID and sorted(ev['deposits']) == ['syn-1-tops.csv'] and ev['verification']['tool_version'] == '0.9.0'
    assert sorted(p.rsplit('/', 1)[-1] for p in read) == sorted(['records.json', 'ophiolite-synthetic__two-wells.json', sha(TOPS) + '.json'])
    assert [s['licence'] for s in starter.licences(defn, ev)] == [APACHE] * 4


def rewrite(path, change):
    doc = json.loads(path.read_text()); change(doc); path.write_text(json.dumps(doc))


def test_a_wrong_verifier_run_another_path_and_another_size_refuse(tmp_path):
    folder = made(fresh(tmp_path, 'a'))
    rewrite(folder / 'verification' / 'ophiolite-synthetic__two-wells.json', lambda v: v.update(tool_version='0.9.1'))
    assert refused(evidence, folder) == 'input syn-1.las: verifier_run 2026-10-28T00:00:00Z 0.9.0 is not the latest verification of %s. Nothing was sent.' % RID
    folder = made(fresh(tmp_path, 'b'))
    rewrite(folder / 'verification' / 'ophiolite-synthetic__two-wells.json', lambda v: v['files'][0].update(path='logs/other.las'))
    assert refused(evidence, folder) == 'input syn-1.las: path logs/syn-1.las is not a file of the latest verification of %s. Nothing was sent.' % RID
    folder = made(fresh(tmp_path, 'c'))
    rewrite(folder / 'verification' / 'ophiolite-synthetic__two-wells.json', lambda v: v['files'][1].update(bytes=1))
    assert refused(evidence, folder) == 'input syn-2.las: bytes %d, the verification states 1. Nothing was sent.' % len(files()['syn-2.las'])


def test_a_removed_deposit_and_a_verified_copy_refuse(tmp_path):
    folder = made(fresh(tmp_path, 'a'))
    held = folder / 'custody' / (sha(TOPS) + '.json')
    tomb = folder / 'custody' / (sha(TOPS) + '.removed.json')
    doc = json.loads(held.read_text())
    doc['removal'] = {'state': 'removed', 'removed_at': '2026-10-28T01:00:00Z', 'request': 'https://example.org/issues/1', 'approved_by': 'maintainer'}
    tomb.write_text(json.dumps(doc))
    assert refused(evidence, folder) == 'input syn-1-tops.csv: its custody document is removed: never in a pack. Nothing was sent.'
    folder = made(fresh(tmp_path, 'b'))
    def verified(d):
        del d['deposit']; d['origin_href'] = 'https://example.org/tops.csv'; d['verifier_run'] = dict(RUN)
    rewrite(folder / 'custody' / (sha(TOPS) + '.json'), verified)
    assert refused(evidence, folder) == 'input syn-1-tops.csv: custody key mirror/%s/%s/syn-1-tops.csv is a verified copy, not a deposit. Nothing was sent.' % (RID, sha(TOPS))


def lic(**k): return {**APACHE, **k}


LICENCES = {
    'first not-required, then required': ([lic(attribution='not-required'), lic(attribution='required')], {'attribution': 'required'}),
    'not-required and unknown': ([lic(attribution='not-required'), lic(attribution='unknown')], {'attribution': 'unknown'}),
    'share_alike on the second only': ([lic(), lic(share_alike=True)], {'attribution': 'required', 'share_alike': True}),
    'share_alike on neither': ([lic(), lic()], {'attribution': 'required'}),
}


@pytest.mark.parametrize('case', sorted(LICENCES))
def test_the_computed_licence(case):
    given, expected = LICENCES[case]
    sources = [{'input': 'a.las', 'licence': given[0]}, {'input': 'b.las', 'licence': given[1]}]
    assert starter.computed_licence(sources) == {'name': APACHE['name'], 'spdx': 'Apache-2.0', 'url': APACHE['url'], 'redistribution': 'allowed', **expected}


def test_a_licence_not_allowed_or_disagreeing_refuses():
    assert refused(starter.computed_licence, [{'input': 'a.las', 'licence': lic()}, {'input': 'b.las', 'licence': lic(redistribution='restricted')}]) \
        == 'input b.las: redistribution restricted: never in a pack. Nothing was sent.'
    assert refused(starter.computed_licence, [{'input': 'a.las', 'licence': lic()}, {'input': 'b.las', 'licence': lic(url='https://example.org/l')}]) \
        == "Unsupported combination: the inputs' licence url differs. Nothing was sent."


CUSTODY = {
    'removal.state removed in a held file': (lambda d: d.update(removal={'state': 'removed', 'removed_at': '2026-10-28T01:00:00Z', 'request': 'https://example.org/i', 'approved_by': 'm'}),
                                             'removal state removed in {sha}.json'),
    'a key of another record': (lambda d: d.update(key=d['key'].replace(RID, 'acme/other')), 'key mirror/acme/other/{sha}/syn-1-tops.csv is not mirror/%s/{sha}/syn-1-tops.csv' % RID),
    'not a custody document': (lambda d: d.pop('removal'), '{sha}.json is not a custody document'),
}


@pytest.mark.parametrize('case', sorted(CUSTODY))
def test_a_custody_document_is_checked_beyond_its_file_name(tmp_path, case):
    change, problem = CUSTODY[case]
    folder = made(tmp_path)
    rewrite(folder / 'custody' / (sha(TOPS) + '.json'), change)
    assert refused(evidence, folder) == 'input syn-1-tops.csv: %s. Nothing was sent.' % problem.format(sha=sha(TOPS))


def test_a_custody_file_that_is_not_json_or_names_another_digest_refuses(tmp_path):
    folder = made(tmp_path)
    p = folder / 'custody' / (sha(TOPS) + '.json')
    raw = p.read_bytes()
    p.write_text('{')
    assert refused(evidence, folder) == 'input syn-1-tops.csv: %s.json is not JSON. Nothing was sent.' % sha(TOPS)
    doc = json.loads(raw)
    assert starter.custody_problems(doc, 'e' * 64 + '.json') == ['file name %s.json does not name the digest %s' % ('e' * 64, sha(TOPS))]


def test_the_attribution_lists_each_source_and_the_deposit_lines(tmp_path):
    defn, (ev, _) = evidence(made(tmp_path))
    text = starter.attribution(defn, starter.licences(defn, ev), ev).decode()
    assert text.splitlines()[4:7] == ['- syn-1.las: Apache License 2.0 (Apache-2.0), https://www.apache.org/licenses/LICENSE-2.0',
                                      '- syn-2.las: Apache License 2.0 (Apache-2.0), https://www.apache.org/licenses/LICENSE-2.0',
                                      '- syn-1-tops.csv: Apache License 2.0 (Apache-2.0), https://www.apache.org/licenses/LICENSE-2.0']
    assert '  Tops of SYN-1, deposited by the maintainer.' in text.splitlines()
