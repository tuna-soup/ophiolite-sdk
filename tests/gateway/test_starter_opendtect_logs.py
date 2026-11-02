"""E129 (f) C2 (strategy rev 3, D6, D7, Q6 and round 2 dispositions R2-1, R2-3, R2-4, R2-8 a, b, h, R2-10): the
OpendTect target's qualification with logs, through the real export, build and connector on the fake odbind, as
test_starter_archive_pack's C3 section runs them.

Variant `fresh` of the fake gives SYN-A no logs of its own, so the pack's SYN-A.las places DT and GR there. SYN-A's logs
as the fake gives them (`tests/fake_odbind`): MD 100 + 0.15 k, k = 0..6; GR null, 60.5, 61, 62, 63.5, 64, null; DT
null, 120.25, 121.5, 122, 123.75, 124.5, 125. Every value is float32-exact (halves and quarters); of the depths only
100.0 and 100.75 are, and 100.3 is the farthest from its float32 (100.30000305..., 3.05e-06 m)."""
import ast
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from ophiolite import starter
from test_starter_archive_pack import (build, client, copied, derive, exports, odbind, project, qualified, refused, survey_at,  # noqa: F401 (fixtures)
                                       ARTEFACTS, COMPARED, EXISTS, GUI, MOVES, NOT_PLACED, OUTSIDE, PATH_DECLARED, RESULT)
from test_starter_export import PACK, ROOT, SCHEMA, sha

FIXTURES = Path(__file__).resolve().parent / 'starter_fixtures'
V1_IMPORT = (FIXTURES / 'opendtect-v1-import.py.txt').read_bytes()  # the (c) launcher, as build wrote it before E129 (f)
V1_RESULT = (FIXTURES / 'opendtect-v1-result.json').read_bytes()  # the (c) result of that pack on the fake survey
V1_ORACLE = json.loads((FIXTURES / 'opendtect-v1-oracle.json').read_text())  # and its oracle
HEADS = ROOT / 'ophiolite-opendtect/src/ophiolite_opendtect/heads.py'
DIFFERS = 'The OpendTect import of %s differs from the pack in %d places; run ophiolite starter opendtect again after fixing the survey.'
FAILED = ("failed: OpendTect holds something other than the pack's files (%d differences); run ophiolite starter opendtect again after "
          'fixing the survey')
NOT_OURS = 'The log GR on well SYN-A is not the one this pack placed; delete it in OpendTect to place it again.'
NO_DEPTH_REFERENCE = "The pack does not state this well's depth reference."
LAS = '(files/wells/SYN-A.las, item item-SYN-A-las at r1)'
DT_LINE = ('log SYN-A DT %s into OpendTect as “DT”: 6 values, 0 differences; trimmed 1+0 empty end samples; 32-bit storage changed 5 depths '
           '(max 3.05e-06 m) and 0 values (max 0)' % LAS)
GR_LINE = ('log SYN-A GR %s into OpendTect as “GR”: 5 values, 0 differences; trimmed 1+1 empty end samples; 32-bit storage changed 4 depths '
           '(max 3.05e-06 m) and 0 values (max 0)' % LAS)
PLACED_COMPARED = COMPARED[:2] + [DT_LINE, GR_LINE] + ['not placed: seismic cube Syn2: ' + OUTSIDE, 'not placed: well path SYN-A: ' + GUI,
                                                       'not placed: well path SYN-B: ' + GUI, 'not placed: log SYN-B: the well has no logs']
ZERO = {'name': 0, 'unit': 0, 'mnemonic': 0, 'length': 0, 'md': 0, 'null_mask': 0, 'values': 0, 'storage': 0,
        'inventory': {'missing': 0, 'unexpected': 0, 'duplicate': 0, 'renamed': 0, 'gone_from_pack': 0}}


@pytest.fixture
def fresh(odbind, monkeypatch):
    monkeypatch.setenv('FAKE_ODBIND_VARIANT', 'fresh')
    return odbind


def built(exports, where, project):
    folder, export = copied(exports, 'time', where)
    build(folder, export, project)
    return folder


def opendtect_target(folder):
    return json.loads((folder / 'pack/starter.json').read_text())['targets'][0]


def stored_gr(survey):
    """The `.wll` file of SYN-A's GR in the fake survey (the fake writes OpendTect's layout: header, then float32 pairs)."""
    (path,) = [p for p in (survey / 'WellInfo').glob('SYN-A^*.wll') if b'\nName: GR\n' in p.read_bytes()]
    return path


def validated(doc):
    """R2-8 h: the pack document against the pinned OSD starter schema (the conformance copy)."""
    import jsonschema
    jsonschema.validate(doc, json.loads(SCHEMA.read_text()))
    assert all(1 <= len(line) <= 300 for t in doc['targets'] for line in t['oracle']['compared'])


# --- Q6 (R2-10): well paths declared from OpendTect's kelly bushing -------------------------------------------------

def test_q6_well_paths_are_declared_md_from_kb_as_the_connectors_basis():
    basis = next(ast.literal_eval(n.value) for n in ast.parse(HEADS.read_text()).body
                 if isinstance(n, ast.Assign) and [getattr(t, 'id', None) for t in n.targets] == ['BASIS'])
    assert basis == {'kind': 'MD', 'unit': 'm', 'datum': starter.OPENDTECT_MD_REFERENCE} == {'kind': 'MD', 'unit': 'm', 'datum': 'KB'}
    survey = {'crs': 'EPSG:32631', 'xyunit': 'm', 'depth_unit': 'm', 'zdomain': 'twt', 'zunit': 'ms'}
    assert starter.declarations(survey, {'wellbore-paths'})['wellbore-paths'] == PATH_DECLARED == {
        'crs': 'EPSG:32631', 'xy_unit': 'm', 'depth_unit': 'm', 'tvdss_datum': 'MSL', 'md_reference': 'KB'}


def test_d7_the_launcher_says_logs_per_curve_the_gui_well_step_and_the_measured_release(exports, tmp_path, project):
    folder = built(exports, tmp_path, project)
    text = (folder / 'pack/files/targets/opendtect/import.py').read_text()
    assert text.startswith(
        '"""Starter pack %s: the OpendTect import.\n\nPlaces the pack\'s seismic cubes, horizons and logs in an existing OpendTect survey '
        'through odbind; each log is\nplaced or refused per curve, on a well the survey already has. OpendTect 7.0.10 cannot create a well '
        'from\nPython: import each well path in OpendTect first (Survey > Import > Wells), then run this import.\nMeasured with OpendTect '
        '7.0.10; check your installation with python -m ophiolite_opendtect.host DTECT_APPL.\nRun it with the Python the OpendTect connector '
        '(ophiolite-opendtect) is installed in:\n\n    python import.py PACK --survey ROOT/NAME\n\n' % PACK)
    assert 'not\nimported by this version' not in text


# --- A6: logs placed, compared and in the oracle, one entry per curve -----------------------------------------------

def test_a6_each_curve_of_a_las_is_one_placed_entry_and_one_oracle_line(exports, tmp_path, project, fresh):
    folder = built(exports, tmp_path, project)
    project.provenance_reads.clear()
    doc, result = qualified(folder, survey_at(tmp_path), project)
    logs = [p for p in result['placed'] if p['kind'] == 'wellbore-logs']
    assert [(p['file'], p['item'], p['version'], p['well'], p['curve'], p['object'], p['values'], p['differences'], p['counts'], p['trimmed'],
             p['rounded'], p['moves'], p['said']) for p in logs] == [
        ('wells/SYN-A.las', 'item-SYN-A-las', 'r1', 'SYN-A', 'DT', 'DT', 6, 0, ZERO, [1, 0],
         {'depths': {'count': 5, 'max': 3.051757815342171e-06}, 'values': {'count': 0, 'max': 0.0}}, [], []),
        ('wells/SYN-A.las', 'item-SYN-A-las', 'r1', 'SYN-A', 'GR', 'GR', 5, 0, ZERO, [1, 1],
         {'depths': {'count': 4, 'max': 3.051757815342171e-06}, 'values': {'count': 0, 'max': 0.0}}, [], [])]
    assert all(starter.SHA256.fullmatch(p['digest']) for p in logs)
    assert (result['version'], result['compared'], result['differences']) == (2, [], 0)
    assert result['not_placed'] == [NOT_PLACED[0], NOT_PLACED[1], NOT_PLACED[4], NOT_PLACED[5]]
    assert doc['targets'][0]['oracle'] == {'compared': PLACED_COMPARED, 'values': 107, 'differences': 0, 'seed': 0}
    assert project.provenance_reads == [('item-Syn-sgy', 'r1'), ('item-Top-csv', 'r1'), ('item-SYN-A-las', 'r1')]  # the LAS file's read once
    validated(doc)


# --- R2-8 a, R2-1: the failed requalification journey; a refusal before the writes keeps the oracle ---------------

def test_r2_8a_a_log_altered_after_a_pass_writes_the_failed_oracle_and_finalise_refuses_with_the_count(exports, tmp_path, project, fresh):
    folder = built(exports, tmp_path, project)
    survey = survey_at(tmp_path)
    qualified(folder, survey, project)
    passed = (folder / 'pack/starter.json').read_bytes()
    assert opendtect_target(folder)['oracle']['differences'] == 0
    # a refusal before the writes (a pack file changed) keeps the passing oracle: starter.json byte-identical
    top = folder / 'pack/files/horizons/Top.csv'
    kept = top.read_bytes()
    top.write_bytes(kept.replace(b',105.0,10,20', b',105.25,10,20'))
    assert refused(qualified, folder, survey, project) == 'artefact horizons/Top.csv: the file in files/ is not the one starter.json names.' + starter.UNCHANGED
    assert (folder / 'pack/starter.json').read_bytes() == passed
    top.write_bytes(kept)
    # one stored GR value changed in OpendTect (its first, 60.5 -> 60.75; float32 little-endian after the header)
    path = stored_gr(survey)
    raw = path.read_bytes()
    start = len(raw) - 5 * 8  # GR's five stored (md, value) pairs end the file
    assert struct.unpack('<2f', raw[start:start + 8]) == (100.1500015258789, 60.5)
    path.write_bytes(raw[:start + 4] + struct.pack('<f', 60.75) + raw[start + 8:])
    doc, result = qualified(folder, survey, project)  # an ordinary run with a difference: written, not refused
    assert result['differences'] == 1 and [p.get('curve') for p in result['placed']] == [None, None, 'DT']
    (gr,) = result['compared']
    assert (gr['curve'], gr['values'], gr['differences'], gr['counts'], gr['item']) == ('GR', 5, 1, {**ZERO, 'values': 1}, 'item-SYN-A-las')
    assert result['not_placed'][2] == {'kind': 'wellbore-logs', 'object': 'SYN-A', 'file': 'wells/SYN-A.las', 'curve': 'GR', 'reason': NOT_OURS}
    oracle = doc['targets'][0]['oracle']
    assert oracle == {'compared': [FAILED % 1] + COMPARED[:2] + [DT_LINE, GR_LINE.replace(' into ', ' compared in ', 1).replace('5 values, 0 differences', '5 values, 1 differences'),
                                                                'not placed: seismic cube Syn2: ' + OUTSIDE, 'not placed: well path SYN-A: ' + GUI,
                                                                'not placed: log SYN-A GR: ' + NOT_OURS,
                                                                'not placed: well path SYN-B: ' + GUI, 'not placed: log SYN-B: the well has no logs'],
                      'values': 107, 'differences': 1, 'seed': 0}
    assert json.loads((folder / 'pack/files' / RESULT).read_bytes()) == result
    validated(doc)
    derive(folder)
    before = (folder / 'pack/starter.json').read_bytes()
    assert refused(starter.finalise, folder / 'pack', folder / 'custody') == DIFFERS % (PACK, 1) + starter.UNCHANGED
    assert (folder / 'pack/starter.json').read_bytes() == before and starter.DIFFERS == DIFFERS and starter.FAILED == FAILED


def test_r2_1_a_cube_or_horizon_difference_gates_finalise_too(exports, tmp_path, project, odbind):
    """Q5, S1: a pack with no log placed whose comparison differs is refused by finalise, not only a log's."""
    folder = built(exports, tmp_path, project)
    doc, _ = qualified(folder, survey_at(tmp_path), project)
    p = folder / 'pack/starter.json'
    doc['targets'][0]['oracle']['differences'] = 3  # as a failed comparison writes it
    p.write_bytes(starter.dumped(doc))
    derive(folder)
    assert refused(starter.finalise, folder / 'pack', folder / 'custody') == DIFFERS % (PACK, 3) + starter.UNCHANGED
    assert p.read_bytes() == starter.dumped(doc)


# --- R2-4 (R2-8 b): a frozen (c) pack is recognised, checked and requalified ----------------------------------------

def frozen(folder, survey):
    """The pack as (c) completed it: the (c) launcher run on the survey, its result and oracle in starter.json."""
    pack = folder / 'pack'
    script = pack / 'files' / starter.OPENDTECT_IMPORT
    script.write_bytes(V1_IMPORT)
    done = subprocess.run([sys.executable, str(script), str(pack), '--survey', str(survey), '--json'], capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr
    (pack / 'files' / RESULT).write_bytes(V1_RESULT)
    doc = json.loads((pack / 'starter.json').read_text())
    (t,) = doc['targets']
    next(a for a in t['artefacts'] if a['path'] == starter.OPENDTECT_IMPORT).update(sha256=sha(V1_IMPORT), bytes=len(V1_IMPORT))
    t['artefacts'].append({'path': RESULT, 'sha256': sha(V1_RESULT), 'bytes': len(V1_RESULT)})
    t['oracle'] = V1_ORACLE
    (pack / 'starter.json').write_bytes(starter.dumped(doc))
    return doc


def test_r2_4_the_frozen_v1_oracle_is_the_c_oracle_of_the_v1_result():
    assert starter.oracle_of(json.loads(V1_RESULT)) == starter._oracle_v1(json.loads(V1_RESULT)) == V1_ORACLE
    assert 'version' not in json.loads(V1_RESULT) and json.loads(V1_RESULT)['ticket'] == 'E129 (f)'


def test_r2_4_a_frozen_v1_pack_validates_and_is_requalified_to_version_2(exports, tmp_path, project, odbind):
    folder = built(exports, tmp_path, project)
    survey = survey_at(tmp_path)
    validated(frozen(folder, survey))
    doc, result = qualified(folder, survey, project)
    assert (result['version'], result['differences'], result['compared'], 'ticket' in result) == (2, 0, [], False)
    assert [(p['kind'], p['object'], p['values'], p['differences'], p['moves']) for p in result['placed']] == [
        ('seismic-3d', 'Syn · Ophiolite v1', 80, 0, []), ('horizons', 'Top · Ophiolite v1', 16, 0, MOVES)]
    # the (c) launcher declares well paths `unknown`, so its logs are refused with D2's sentence until the pack is rebuilt
    refusal = {'kind': 'wellbore-logs', 'object': 'SYN-A', 'file': 'wells/SYN-A.las', 'reason': NO_DEPTH_REFERENCE}
    assert result['not_placed'] == [NOT_PLACED[0], NOT_PLACED[1], {**refusal, 'curve': 'DT'}, {**refusal, 'curve': 'GR'}, NOT_PLACED[4], NOT_PLACED[5]]
    raw = (folder / 'pack/files' / RESULT).read_bytes()
    t = doc['targets'][0]
    assert raw != V1_RESULT and t['artefacts'][-1] == {'path': RESULT, 'sha256': sha(raw), 'bytes': len(raw)}
    assert [a['path'] for a in t['artefacts']] == ARTEFACTS + [RESULT]
    assert t['oracle'] == {'compared': COMPARED[:2] + ['not placed: seismic cube Syn2: ' + OUTSIDE, 'not placed: well path SYN-A: ' + GUI,
                                                       'not placed: log SYN-A DT: ' + NO_DEPTH_REFERENCE, 'not placed: log SYN-A GR: ' + NO_DEPTH_REFERENCE,
                                                       'not placed: well path SYN-B: ' + GUI, 'not placed: log SYN-B: the well has no logs'],
                           'values': 96, 'differences': 0, 'seed': 0}
    validated(doc)


@pytest.mark.parametrize('tamper', ['oracle', 'shape'])
def test_r2_4_a_tampered_frozen_v1_pack_is_refused_and_nothing_is_written(exports, tmp_path, project, odbind, tamper):
    folder = built(exports, tmp_path, project)
    survey = survey_at(tmp_path)
    doc = frozen(folder, survey)
    pack = folder / 'pack'
    if tamper == 'oracle':
        doc['targets'][0]['oracle']['differences'] = 1  # test_starter_archive_pack's tamper, on the (c) representation
        sentence = starter.RESULT_NOT_NAMED
    else:  # a (c) result without its ticket is not the (c) shape, even when starter.json names its bytes
        result = json.loads(V1_RESULT); del result['ticket']
        raw = starter.dumped(result)
        (pack / 'files' / RESULT).write_bytes(raw)
        doc['targets'][0]['artefacts'][-1].update(sha256=sha(raw), bytes=len(raw))
        sentence = starter.RESULT_UNREADABLE
    (pack / 'starter.json').write_bytes(starter.dumped(doc))
    before = {p: (pack / p).read_bytes() for p in ('starter.json', 'files/' + RESULT)}
    assert refused(qualified, folder, survey, project) == sentence
    assert {p: (pack / p).read_bytes() for p in before} == before


# --- R2-8 h: every oracle line within the schema's 300 characters, a long-named log in success and failure ---------

LONG = 'SYN-' + 'L' * 260  # a well name that does not fit one oracle line


def long_result(differences):
    log = {'kind': 'wellbore-logs', 'file': 'wells/%s.las' % LONG, 'item': None, 'version': None, 'well': LONG, 'curve': 'GR', 'object': 'GR',
           'digest': '0' * 64, 'values': 5, 'differences': differences, 'counts': {**ZERO, 'values': differences}, 'trimmed': [1, 1],
           'rounded': {'depths': {'count': 4, 'max': 3.051757815342171e-06}, 'values': {'count': 0, 'max': 0.0}}, 'moves': [], 'said': []}
    refusal = {'kind': 'wellbore-logs', 'object': LONG, 'file': 'wells/%s.las' % LONG, 'curve': 'DT', 'reason': EXISTS}
    return {'format': starter.RESULT_FORMAT, 'version': 2, 'pack': PACK, 'survey': 'Syn_Survey', 'placed': [] if differences else [log],
            'compared': [log] if differences else [], 'not_placed': [refusal], 'differences': differences}


def joined(lines):
    """The oracle's lines as one text again: each continued line's `… ` dropped."""
    text = lines[0]
    for line in lines[1:]: text += (' ' + line[2:]) if line.startswith('… ') else '\n' + line
    return text


@pytest.mark.parametrize('differences', [0, 1], ids=['success', 'failure'])
def test_r2_8h_a_long_named_log_gives_oracle_lines_of_at_most_300_characters(differences):
    import jsonschema
    oracle = starter.oracle_of(long_result(differences))
    schema = json.loads(SCHEMA.read_text())['properties']['targets']['items']['properties']['oracle']
    jsonschema.validate(oracle, schema)
    # 'log ' + LONG + ' GR' (271); '… (files/wells/' + LONG + '.las, not landed in' (298); the rest of that line, 7 longer with
    # 'compared in'; 'not placed: log ' + LONG + ' DT: A log of this' (298); '… ' + the rest of EXISTS (77)
    assert [len(line) for line in oracle['compared']] == ([140] if differences else []) + [271, 298, 169 if differences else 162, 298, 77]
    verb = 'compared in' if differences else 'into'
    assert joined(oracle['compared']).split('\n')[1 if differences else 0:] == [
        'log %s GR (files/wells/%s.las, not landed in Ophiolite) %s OpendTect as “GR”: 5 values, %d differences; trimmed 1+1 empty end samples; '
        '32-bit storage changed 4 depths (max 3.05e-06 m) and 0 values (max 0)' % (LONG, LONG, verb, differences),
        'not placed: log %s DT: %s' % (LONG, EXISTS)]
    assert (oracle['values'], oracle['differences']) == (5, differences)


def test_c4_the_oracle_states_the_labels_opendtect_gave_a_log():
    """C4 (measured live on 7.0.10): OpendTect labels a log itself; the oracle line says so when the labels differ."""
    result = long_result(0)
    (log,) = result['placed']
    log.update(well='SYN-C', file='wells/SYN-C.las', curve='RT', object='RT',
               labels={'given': {'unit': 'ohm.m', 'mnemonic': 'RT'}, 'stored': {'unit': '', 'mnemonic': ''}})
    result['not_placed'] = []
    assert starter.oracle_of(result)['compared'] == [
        'log SYN-C RT (files/wells/SYN-C.las, not landed in Ophiolite) into OpendTect as “RT”: 5 values, 0 differences; trimmed 1+1 empty end '
        'samples; 32-bit storage changed 4 depths (max 3.05e-06 m) and 0 values (max 0); OpendTect labels it unit “”, mnemonic “” (the LAS '
        'file: “ohm.m”, “RT”)']
    log['labels'] = {'given': {'unit': 'API', 'mnemonic': 'GR'}, 'stored': {'unit': 'API', 'mnemonic': 'GR'}}
    assert starter.oracle_of(result)['compared'][0].endswith('and 0 values (max 0)')


def test_r2_8h_a_word_longer_than_a_line_is_cut():
    lines = starter.bounded('not placed: log ' + 'W' * 700 + ' GR: ' + EXISTS)
    # split at the last space within 300 ('not placed: log'), then the 700-letter word cut at 298 letters a line
    assert [len(line) for line in lines] == [15, 300, 300, 200] and len(EXISTS) == 89
    assert lines[:2] == ['not placed: log', '… ' + 'W' * 298] and lines[3] == '… ' + 'W' * 104 + ' GR: ' + EXISTS
