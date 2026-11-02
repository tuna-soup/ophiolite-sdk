"""E137 s3 C1 (strategy D-1, D-2, D-3, D-4, F1, M3, M4, M5, R2-1, R2-6): an archive's checkshot table becomes a pack's
time-depth-csv/1 file, its cells' text unchanged, or the pack is refused by name.

The converter is called directly (C1 is not yet reachable from a definition). Every expected value is a literal of two
hand-written synthetic tables (exception: D75; no deposit byte or literal): SynTD1, tab-separated after a description
line, its depth the TVDSS column, one-way time in s, datum SRD; SynTD2, comma-separated, its depth the MD column,
two-way time in ms, datum KB. Each has four pairs."""
import shutil

import pytest

from ophiolite import starter_archive as sa
from ophiolite.errors import Refused

SYNTD1_TEXT = ('Synthetic checkshot SynTD1 (exception: D75), one-way time, relative to SRD\r\n'
               'MD\tTVDSS\tOWT\r\n'
               '100\t95.5\t0.05\r\n420\t410\t0.2\r\n830\t820.25\t0.41\r\n1250\t1230\t0.615\r\n')
SYNTD2_TEXT = ('Synthetic checkshot SynTD2 (exception: D75)\n'
               'MD,TVDSS,TWT\n'
               '120,118,96\n480,470,384\n\n960,940,768\n1500,1460,1200\n')
SYNTD1_CSV = b'depth,time\n95.5,0.05\n410,0.2\n820.25,0.41\n1230,0.615\n'
SYNTD2_CSV = b'depth,time\n120,96\n480,384\n960,768\n1500,1200\n'
DIGEST = {'SynTD1': '34c90525de54f441278c2769a1507af424212385a7059d089dc36ce4a1e55e8b',
          'SynTD2': '49423b11511b14aa06391f16be25200f5e06fe3296a55e58527f7515012c429a'}
MEMBER = {'SynTD1': 'Syn/RawData/checkshots/table-a.txt', 'SynTD2': 'Syn/RawData/checkshots/table-b.csv'}
NAMES = {'Syn': True, 'Syn/RawData': True, 'Syn/RawData/checkshots': True, MEMBER['SynTD1']: False, MEMBER['SynTD2']: False}
NOTHING = ' Nothing was sent.'


def spec(member, delimiter, depth, time):
    return {'member': member, 'header_line': 2, 'delimiter': delimiter, 'depth': depth, 'time': time}


def archive(**changed):
    td = {'SynTD1': spec(MEMBER['SynTD1'], 'tab', 'TVDSS', 'OWT'), 'SynTD2': spec(MEMBER['SynTD2'], 'comma', 'MD', 'TWT')}
    td.update(changed)
    return {'survey': 'Syn', 'time_depth': td}


def contents(models=('SynTD1', 'SynTD2'), paths=('SynTD1', 'SynTD2')):
    return [{'kind': 'wellbore-paths', 'ids': list(paths)}, {'kind': 'time-depth', 'ids': list(models)}]


def values(**changed):
    v = {('domain', 'SynTD1'): 'one-way time in s', ('depth-kind', 'SynTD1'): 'TVDSS', ('units', 'SynTD1'): 'm', ('vertical-datum', 'SynTD1'): 'SRD',
         ('domain', 'SynTD2'): 'two-way time in ms', ('depth-kind', 'SynTD2'): 'MD', ('units', 'SynTD2'): 'm', ('vertical-datum', 'SynTD2'): 'KB'}
    v.update({tuple(k.split('__')): x for k, x in changed.items()})
    return v


def refused(fn, *args, **kw):
    with pytest.raises(Refused) as e: fn(*args, **kw)
    return str(e.value)


def work_with(tmp_path, texts):
    work, stage = tmp_path / 'work', tmp_path / 'files'
    stage.mkdir(parents=True)
    for well, text in texts.items():
        target = work / MEMBER[well]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode('utf-8') if isinstance(text, str) else text)
    return work, stage


def convert(tmp_path, texts, specs=None):
    work, stage = work_with(tmp_path, texts)
    specs = specs or sa.time_depth_checked(archive(), contents(), values(), NAMES)
    return sa.converted(work, stage, {w: specs[w] for w in texts}), stage


def one(tmp_path, text, **spec_changes):
    """SynTD1's spec (header line 2, tab, TVDSS/OWT unless changed) converting TEXT."""
    specs = sa.time_depth_checked(archive(), contents(), values(), NAMES)
    specs['SynTD1'] = {**specs['SynTD1'], **spec_changes}
    return convert(tmp_path, {'SynTD1': text}, specs)


# --- the definition's key (D-1, D-2, D-3, M4) ------------------------------------------------------------------------

def test_both_specs_name_member_columns_path_and_declarations():
    specs = sa.time_depth_checked(archive(), contents(), values(), NAMES)
    assert specs == {
        'SynTD1': {'member': 'Syn/RawData/checkshots/table-a.txt', 'header_line': 2, 'delimiter': '\t', 'depth': 'TVDSS', 'time': 'OWT',
                   'path': 'wells/SynTD1-time-depth.csv',
                   'how': 'the archive file Syn/RawData/checkshots/table-a.txt, columns TVDSS (depth) and OWT (time) from header line 2, '
                          'written as time-depth-csv/1 depth,time, the text unchanged',
                   'declared': {'depth_type': 'tvdss', 'depth_unit': 'm', 'time_kind': 'one-way', 'time_unit': 's', 'datum': 'SRD'}},
        'SynTD2': {'member': 'Syn/RawData/checkshots/table-b.csv', 'header_line': 2, 'delimiter': ',', 'depth': 'MD', 'time': 'TWT',
                   'path': 'wells/SynTD2-time-depth.csv',
                   'how': 'the archive file Syn/RawData/checkshots/table-b.csv, columns MD (depth) and TWT (time) from header line 2, '
                          'written as time-depth-csv/1 depth,time, the text unchanged',
                   'declared': {'depth_type': 'md', 'depth_unit': 'm', 'time_kind': 'two-way', 'time_unit': 'ms', 'datum': 'KB'}}}


def test_a_pack_without_models_needs_no_key_and_refuses_one():
    assert sa.time_depth_checked({'survey': 'Syn'}, contents()[:1], values(), NAMES) == {}
    assert refused(sa.time_depth_checked, archive(), contents()[:1], values(), NAMES) == \
        "The archive's time_depth is given, but contents lists no time-depth model." + NOTHING


@pytest.mark.parametrize('given, sentence', [
    (None, "The time-depth model of SynTD1 is not named in the archive's time_depth; name its file and columns."),
    ({'SynTD1': spec(MEMBER['SynTD1'], 'tab', 'TVDSS', 'OWT')},
     "The time-depth model of SynTD2 is not named in the archive's time_depth; name its file and columns."),
    ({'SynTD1': spec(MEMBER['SynTD1'], 'tab', 'TVDSS', 'OWT'), 'SynTD2': spec(MEMBER['SynTD2'], 'comma', 'MD', 'TWT'), 'SynTD3': spec(MEMBER['SynTD2'], 'comma', 'MD', 'TWT')},
     "The archive's time_depth names SynTD3, which contents does not list as a time-depth model."),
])
def test_the_key_names_exactly_the_contents_models(given, sentence):
    a = {'survey': 'Syn', **({} if given is None else {'time_depth': given})}
    assert refused(sa.time_depth_checked, a, contents(), values(), NAMES) == sentence + NOTHING


FORM = ("The archive's time_depth entry for SynTD1 must be {member, header_line (a line number from 1), delimiter (tab or "
        "comma), depth, time}.")


@pytest.mark.parametrize('bad', [
    'not an object', {'member': MEMBER['SynTD1'], 'header_line': 2, 'delimiter': 'tab', 'depth': 'TVDSS'},
    {**spec(MEMBER['SynTD1'], 'tab', 'TVDSS', 'OWT'), 'velocity': 'V'}, {**spec(MEMBER['SynTD1'], 'tab', 'TVDSS', 'OWT'), 'header_line': 0},
    {**spec(MEMBER['SynTD1'], 'tab', 'TVDSS', 'OWT'), 'header_line': True}, spec(MEMBER['SynTD1'], 'semicolon', 'TVDSS', 'OWT'),
    spec(MEMBER['SynTD1'], 'tab', '', 'OWT'),
])
def test_an_entry_not_of_the_form_is_refused(bad):
    assert refused(sa.time_depth_checked, archive(SynTD1=bad), contents(), values(), NAMES) == FORM + NOTHING


@pytest.mark.parametrize('member, sentence', [
    ('/Syn/RawData/checkshots/table-a.txt', "The time-depth file '/Syn/RawData/checkshots/table-a.txt' for SynTD1 is not a relative path inside the archive."),
    ('Syn/RawData/../RawData/checkshots/table-a.txt', "The time-depth file 'Syn/RawData/../RawData/checkshots/table-a.txt' for SynTD1 is not a relative path inside the archive."),
    ('Syn\\RawData\\table-a.txt', "The time-depth file 'Syn\\\\RawData\\\\table-a.txt' for SynTD1 is not a relative path inside the archive."),
    ('Syn/RawData/checkshots', "The time-depth file 'Syn/RawData/checkshots' for SynTD1 is a folder of the archive, not a file."),
    ('Syn/RawData/checkshots/', "The time-depth file 'Syn/RawData/checkshots/' for SynTD1 is a folder of the archive, not a file."),
    ('Syn/RawData/checkshots/SynTD1.txt', "The archive holds no file 'Syn/RawData/checkshots/SynTD1.txt' for the time-depth model of SynTD1."),
])
def test_the_member_is_a_file_of_the_archive(member, sentence):
    assert refused(sa.time_depth_checked, archive(SynTD1=spec(member, 'tab', 'TVDSS', 'OWT')), contents(), values(), NAMES) == sentence + NOTHING


def test_a_description_over_300_characters_is_refused():
    long = 'Syn/' + 'a' * 200 + '.txt'
    names = {**NAMES, long: False}
    assert refused(sa.time_depth_checked, archive(SynTD1=spec(long, 'tab', 'TVDSS', 'OWT')), contents(), values(), names) == \
        'The description of the time-depth model of SynTD1 would be longer than 300 characters; name a shorter file or columns.' + NOTHING


def test_a_model_needs_its_wells_path_in_the_pack():
    assert refused(sa.time_depth_checked, archive(), contents(paths=('SynTD1',)), values(), NAMES) == \
        "The time-depth model of SynTD2 needs the well's path in the pack: list SynTD2 under wellbore-paths too." + NOTHING


@pytest.mark.parametrize('domain', ['unknown', 'one-way time', 'one way time in s', 'two-way time in sec', 'One-way time in s', None])
def test_the_domain_decision_names_time_kind_and_unit(domain):
    v = values()
    if domain is None: del v[('domain', 'SynTD1')]
    else: v[('domain', 'SynTD1')] = domain
    assert refused(sa.time_depth_checked, archive(), contents(), v, NAMES) == \
        'Decision domain for SynTD1 must be one-way or two-way time in s, ms or us (for example "one-way time in s"), not %r.' % domain + NOTHING


@pytest.mark.parametrize('kind', ['TVDSD', 'depth', ''])
def test_the_depth_kind_decision_is_one_a_model_can_hold(kind):
    assert refused(sa.time_depth_checked, archive(), contents(), values(**{'depth-kind__SynTD2': kind}), NAMES) == \
        'Decision depth-kind for SynTD2 must be MD, TVD or TVDSS for its time-depth model, not %r.' % kind + NOTHING


def test_two_wells_of_one_file_stem_are_refused():
    a = {'survey': 'Syn', 'time_depth': {'Syn TD': spec(MEMBER['SynTD1'], 'tab', 'TVDSS', 'OWT'), 'syn_td': spec(MEMBER['SynTD2'], 'comma', 'MD', 'TWT')}}
    v = {(t, w): x for (t, s), x in values().items() for w in ('Syn TD', 'syn_td') if s == ('SynTD1' if w == 'Syn TD' else 'SynTD2')}
    assert refused(sa.time_depth_checked, a, contents(('Syn TD', 'syn_td'), ('Syn TD', 'syn_td')), v, NAMES) == \
        'The time-depth models of Syn TD and syn_td would be written to one file name.' + NOTHING


# --- the converter (D-4, F1, M5, R2-1, R2-6) -------------------------------------------------------------------------

def test_both_tables_are_written_as_their_pairs_with_the_text_unchanged(tmp_path):
    entries, stage = convert(tmp_path, {'SynTD1': SYNTD1_TEXT, 'SynTD2': SYNTD2_TEXT})
    assert (stage / 'wells/SynTD1-time-depth.csv').read_bytes() == SYNTD1_CSV
    assert (stage / 'wells/SynTD2-time-depth.csv').read_bytes() == SYNTD2_CSV
    assert entries == [{'path': 'wells/SynTD1-time-depth.csv', 'kind': 'time-depth', 'object': 'SynTD1', 'axes': {'pairs': 4}, 'digest': DIGEST['SynTD1']},
                       {'path': 'wells/SynTD2-time-depth.csv', 'kind': 'time-depth', 'object': 'SynTD2', 'axes': {'pairs': 4}, 'digest': DIGEST['SynTD2']}]


def test_a_byte_order_mark_scientific_notation_and_whitespace_are_read_as_the_profile_reads_them(tmp_path):
    text = '﻿desc\nMD\tTVDSS\tOWT\n1\t 2.0 \t0.001\n2\t1.5e3\t 2E0\n'
    _, stage = one(tmp_path, text)
    assert (stage / 'wells/SynTD1-time-depth.csv').read_bytes() == b'depth,time\n2.0,0.001\n1.5e3,2E0\n'


def row(n_text):
    return 'The time-depth model of SynTD1: %s No repair was applied.' % n_text + NOTHING


@pytest.mark.parametrize('data, sentence', [
    ('1\t2\t0.1\n2\t3\n', row('Data row 2 has 2 cells; the header has 3.')),
    ('1\t2\t0.1\n2\tabc\t0.2\n', row('Depth on data row 2 is not a number.')),
    ('1\t2\t0.1\n2\t3\tx\n', row('Time on data row 2 is not a number.')),
    ('1\tnan\t0.1\n2\t3\t0.2\n', row('Depth on data row 1 is not finite.')),
    ('1\t2\tinf\n2\t3\t0.2\n', row('Time on data row 1 is not finite.')),
    ('1\t2\t0.1\n2\t1e400\t0.2\n', row('Depth on data row 2 is not finite.')),
    ('1\t2\t0.1\n2\t3\t0.2\n3\t3\t0.3\n', row('Depth on data row 3 does not increase; pairs must be in strictly increasing depth.')),
    ('1\t2\t0.2\n2\t3\t0.1\n', row('Time on data row 2 does not increase; pairs must be in strictly increasing time.')),
    ('1\t1.00000000000000001\t0.1\n2\t1.00000000000000002\t0.2\n', row('Depth on data row 2 does not increase; pairs must be in strictly increasing depth.')),
    ('1\t\t0.1\n2\t3\t0.2\n', row('Depth on data row 1 is missing; every pair needs a depth.')),
    ('1\t2\t\n2\t3\t0.2\n', row('Time on data row 1 is missing; every pair needs a time.')),
    ('1\t2\t0.1\n', row('A time-depth table needs at least two pairs.')),
])
def test_a_table_that_is_not_strictly_increasing_pairs_is_refused_by_well_and_row(tmp_path, data, sentence):
    assert refused(one, tmp_path, 'desc\nMD\tTVDSS\tOWT\n' + data) == sentence
    assert not (tmp_path / 'files/wells').exists()


def test_more_than_100000_pairs_are_refused(tmp_path):
    text = 'desc\nMD\tTVDSS\tOWT\n' + ''.join('%d\t%d\t%d\n' % (i, i, i) for i in range(1, 100_002))
    assert refused(one, tmp_path, text) == row('The table has more than 100,000 pairs.')
    _, stage = one(tmp_path / 'ok', 'desc\nMD\tTVDSS\tOWT\n' + ''.join('%d\t%d\t%d\n' % (i, i, i) for i in range(1, 100_001)))
    assert (stage / 'wells/SynTD1-time-depth.csv').read_bytes().count(b'\n') == 100_001


@pytest.mark.parametrize('header, sentence', [
    ('MD\tTVD\tOWT', "The header of the time-depth file for SynTD1 does not name the column 'TVDSS' exactly once."),
    ('MD\tTVDSS\tOWT\tOWT', "The header of the time-depth file for SynTD1 does not name the column 'OWT' exactly once."),
])
def test_the_named_columns_are_header_cells_exactly_once(tmp_path, header, sentence):
    assert refused(one, tmp_path, 'desc\n%s\n1\t2\t0.1\t0.1\n' % header) == sentence + NOTHING


def test_the_time_column_is_found_by_name_not_by_position(tmp_path):
    _, stage = one(tmp_path, 'desc\nOWT\tMD\tTVDSS\n0.1\t1\t2\n0.2\t2\t3\n')
    assert (stage / 'wells/SynTD1-time-depth.csv').read_bytes() == b'depth,time\n2,0.1\n3,0.2\n'


def test_a_header_line_past_the_end_and_a_file_that_is_not_text_are_refused(tmp_path):
    assert refused(one, tmp_path, 'desc\n', header_line=3) == 'The time-depth file for SynTD1 has no line 3 to read as its header.' + NOTHING
    assert refused(one, tmp_path / 'b', b'desc\nMD\tTVDSS\tOWT\n1\t\xff\t0.1\n') == \
        "The time-depth file 'Syn/RawData/checkshots/table-a.txt' for SynTD1 is not UTF-8 text." + NOTHING


def sized(last_time_width):
    """A table whose written file is 16,777,216 bytes (16 MiB) with a last time cell 25 wide: 11 header bytes, 99,864
    rows of 168 bytes and one of 53."""
    body = ''.join('%083d,%083d\n' % (i, i) for i in range(1, 99_865)) + '%026d,%0*d\n' % (99_865, last_time_width, 99_865)
    return 'depth,time\n' + body


def test_a_written_file_of_16_mib_is_held_and_one_byte_more_is_refused(tmp_path):
    _, stage = one(tmp_path, sized(25), header_line=1, delimiter=',', depth='depth', time='time')
    assert (stage / 'wells/SynTD1-time-depth.csv').stat().st_size == 16_777_216
    assert refused(one, tmp_path / 'over', sized(26), header_line=1, delimiter=',', depth='depth', time='time') == \
        'The time-depth model of SynTD1 would be larger than 16 MiB written; a starter pack cannot hold it.' + NOTHING
    assert not (tmp_path / 'over/files/wells').exists()


def test_a_refused_second_model_leaves_no_file_of_the_first(tmp_path):
    bad = SYNTD2_TEXT.replace('480,470,384', '480,470,9')
    assert refused(convert, tmp_path, {'SynTD1': SYNTD1_TEXT, 'SynTD2': bad}) == \
        'The time-depth model of SynTD2: Time on data row 2 does not increase; pairs must be in strictly increasing time. No repair was applied.' + NOTHING
    assert not (tmp_path / 'files/wells').exists()


# --- C2: a pack holds the models (D-2, D-3, D-5, D-6, F2, M1, M3, M6, R2-1) -------------------------------------------
#
# The real exporter on the fake odbind (wells SYN-A and SYN-B) in its own process; the archive carries SynTD2's table
# for SYN-A (MD, two-way ms, datum SRD) and SynTD1's for SYN-B (TVDSS, one-way s, datum KB; SYN-B has no logs).

import json  # noqa: E402
import os  # noqa: E402

from ophiolite import starter  # noqa: E402
from test_starter_archive_pack import build, current, nothing_landed, project, typed_reader  # noqa: E402,F401 (fixture)
from test_starter_export import FAKE, CONNECTOR, made, run, tree, zipped  # noqa: E402

A_MEMBER, B_MEMBER = 'Syn_Survey/RawData/checkshots/table-b.csv', 'Syn_Survey/RawData/checkshots/table-a.txt'
A_CSV, B_CSV = SYNTD2_CSV, SYNTD1_CSV
A_DECLARED = {'depth_type': 'md', 'depth_unit': 'm', 'time_kind': 'two-way', 'time_unit': 'ms', 'datum': 'SRD'}
B_DECLARED = {'depth_type': 'tvdss', 'depth_unit': 'm', 'time_kind': 'one-way', 'time_unit': 's', 'datum': 'KB'}
A_CONTEXT = {'type': 'time-depth', 'depth_type': 'md', 'depth_unit': 'm', 'time_kind': 'two-way', 'time_unit': 'ms', 'datum': 'SRD',
             'seismic_reference_elevation': None, 'count': 4, 'depth_range': [120.0, 1500.0], 'time_range': [96.0, 1200.0], 'velocity_provided': False}
B_CONTEXT = {'type': 'time-depth', 'depth_type': 'tvdss', 'depth_unit': 'm', 'time_kind': 'one-way', 'time_unit': 's', 'datum': 'KB',
             'seismic_reference_elevation': None, 'count': 4, 'depth_range': [95.5, 1230.0], 'time_range': [0.05, 0.615], 'velocity_provided': False}


def tables(a=SYNTD2_TEXT, b=SYNTD1_TEXT):
    return zipped([('Syn_Survey/', b''), ('Syn_Survey/.survey', b'Name: Syn_Survey\nSeismic Reference Datum: 0\n'),
                   ('Syn_Survey/.defs', b'Depth in feet: No\n'), (A_MEMBER, a.encode('utf-8')), (B_MEMBER, b.encode('utf-8'))])


def modelled(d):
    d['contents'] += [{'kind': 'time-depth', 'ids': ['SYN-A', 'SYN-B']}]
    d['contents'] = [c if c['kind'] != 'wellbore-logs' else {**c, 'ids': ['SYN-A']} for c in d['contents']]
    for r in d['decisions']:
        if (r['subject'], r['topic']) == ('SYN-B', 'depth-kind'): r['value'] = 'TVDSS'
        if (r['subject'], r['topic']) == ('SYN-B', 'vertical-datum'): r['value'] = 'KB'
    d['decisions'] += [{'topic': 'domain', 'subject': 'SYN-A', 'value': 'two-way time in ms', 'source': 'data'},
                       {'topic': 'domain', 'subject': 'SYN-B', 'value': 'one-way time in s', 'source': 'data'}]
    d['inputs'][0]['archive']['time_depth'] = {'SYN-A': spec(A_MEMBER, 'comma', 'MD', 'TWT'), 'SYN-B': spec(B_MEMBER, 'tab', 'TVDSS', 'OWT')}


def pack(folder, raw=None):
    return made(folder, edit=modelled, raw=tables() if raw is None else raw)


def exported(folder, out):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
        mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
        return run(folder, out)


@pytest.fixture(scope='module')
def models_once(tmp_path_factory):
    folder, out = pack(tmp_path_factory.mktemp('definition')), tmp_path_factory.mktemp('out')
    report, export = exported(folder, out)
    return folder, out, report, export


def test_the_export_holds_each_model_as_its_pairs_and_says_where_it_came_from(models_once):
    _, _, report, export = models_once
    assert (export / 'files/wells/SYN-A-time-depth.csv').read_bytes() == A_CSV
    assert (export / 'files/wells/SYN-B-time-depth.csv').read_bytes() == B_CSV
    told = {d['path']: d['how'] for d in report['derived'] if d['path'].endswith('-time-depth.csv')}
    assert told == {'wells/SYN-A-time-depth.csv': 'the archive file %s, columns MD (depth) and TWT (time) from header line 2, '
                                                  'written as time-depth-csv/1 depth,time, the text unchanged' % A_MEMBER,
                    'wells/SYN-B-time-depth.csv': 'the archive file %s, columns TVDSS (depth) and OWT (time) from header line 2, '
                                                  'written as time-depth-csv/1 depth,time, the text unchanged' % B_MEMBER}
    assert [f for f in report['files'] if f['kind'] == 'time-depth'] == [
        {'path': 'wells/SYN-A-time-depth.csv', 'kind': 'time-depth', 'object': 'SYN-A'}, {'path': 'wells/SYN-B-time-depth.csv', 'kind': 'time-depth', 'object': 'SYN-B'}]
    assert not any(p.name == 'work' for p in (models_once[1] / 'exports').rglob('*'))


def test_each_model_lands_as_time_depth_csv_with_its_own_wells_declarations(tmp_path, project):
    """F2, M3: the declaration projection and the whole landed context, each a literal, per model. Mutations: one
    model's declarations reused for the other; time_unit a constant ms."""
    folder, out = pack(tmp_path / 'definition'), tmp_path / 'export'
    exported(folder, out)
    build(folder, out, project)
    for name, declared, context, pairs in (('SYN-A-time-depth.csv', A_DECLARED, A_CONTEXT, ([120.0, 480.0, 960.0, 1500.0], [96.0, 384.0, 768.0, 1200.0])),
                                           ('SYN-B-time-depth.csv', B_DECLARED, B_CONTEXT, ([95.5, 410.0, 820.25, 1230.0], [0.05, 0.2, 0.41, 0.615]))):
        profile, sent, landed = project.read[name]
        assert (profile, {k: sent[k] for k in declared}) == ('time-depth-csv/1', declared)
        assert landed == context
        data = typed_reader.read_typed(profile, project.assets['item-' + name.replace('.', '-')]['raw'], sent)[1]
        assert (data['depth'], data['time']) == pairs


def test_a_definition_without_the_wells_path_is_refused_before_extraction(tmp_path):
    def edit(d):
        modelled(d)
        d['contents'] = [c if c['kind'] != 'wellbore-paths' else {**c, 'ids': ['SYN-A']} for c in d['contents']]
    folder = made(tmp_path / 'definition', edit=edit, raw=tables())
    assert refused(exported, folder, tmp_path / 'out') == \
        "The time-depth model of SYN-B needs the well's path in the pack: list SYN-B under wellbore-paths too." + NOTHING
    assert not (tmp_path / 'out/derived.json').exists()


def test_a_model_whose_value_changed_but_stays_increasing_is_refused_by_its_digest(tmp_path, models_once):
    """M1: an interior value changed, count and increase kept, export.json's digest kept; only the digest refuses.
    Mutation: read_time_depth returning the stated digest."""
    folder, _, _, export = models_once
    stage = tmp_path / 'stage'
    shutil.copytree(export / 'files', stage)
    (stage / 'outline.geojson').unlink()
    p = stage / 'wells/SYN-B-time-depth.csv'
    p.write_bytes(p.read_bytes().replace(b'410,0.2\n', b'411,0.2\n'))
    doc = json.loads((stage / 'export.json').read_text())
    doc['files'] += [{'path': 'wells/SYN-A-time-depth.csv', 'kind': 'time-depth', 'object': 'SYN-A', 'axes': {'pairs': 4}, 'digest': DIGEST['SynTD2']},
                     {'path': 'wells/SYN-B-time-depth.csv', 'kind': 'time-depth', 'object': 'SYN-B', 'axes': {'pairs': 4}, 'digest': DIGEST['SynTD1']}]
    assert refused(sa.read_back, stage, doc, sa.definition(folder / 'definition.json')) == (
        'wells/SYN-B-time-depth.csv does not hold what export.json states: its values differ from those odbind gave (digest of the '
        'expected representation).' + NOTHING)


@pytest.mark.parametrize('bad, sentence', [
    (SYNTD1_TEXT.replace('420\t410\t0.2', '420\t410\t0.01'),
     'The time-depth model of SYN-B: Time on data row 2 does not increase; pairs must be in strictly increasing time. No repair was applied.'),
    (None, None),
], ids=['not-increasing', 'over-16-mib'])
def test_a_refused_model_publishes_nothing_and_keeps_the_previous_export(tmp_path, bad, sentence):
    """M6, R2-1: a valid model (SYN-A) then a refused one (SYN-B); the previous derived.json pointer is unchanged and
    no work folder is left."""
    out = tmp_path / 'out'
    exported(pack(tmp_path / 'good'), out)
    before = (out / 'derived.json').read_bytes()
    if sentence is None:
        rows = ''.join('%083d\t%083d\t%083d\n' % (i, i, i) for i in range(1, 99_865)) + '%026d\t%026d\t%026d\n' % ((99_865,) * 3)
        bad, sentence = 'desc\nMD\tTVDSS\tOWT\n' + rows, 'The time-depth model of SYN-B would be larger than 16 MiB written; a starter pack cannot hold it.'
    assert refused(exported, pack(tmp_path / 'bad', tables(b=bad)), out) == sentence + NOTHING
    assert (out / 'derived.json').read_bytes() == before
    assert not any(p.name == 'work' for p in (out / 'exports').rglob('*'))


def test_an_export_interrupted_while_converting_resumes_to_the_same_bytes(tmp_path, monkeypatch, models_once):
    """M6, acceptance 8: interrupted inside `converted` (after the first model's digest); the rerun's files and report
    equal an uninterrupted export's."""
    folder, out = pack(tmp_path / 'definition'), tmp_path / 'out'
    calls = []
    real = sa.time_depth_digest
    def interrupted(rows):
        calls.append(1)
        if len(calls) == 2: raise OSError('interrupted')
        return real(rows)
    monkeypatch.setattr(sa, 'time_depth_digest', interrupted)
    with pytest.raises(OSError): exported(folder, out)
    monkeypatch.undo()
    assert not (out / 'derived.json').exists() and not any(p.name == 'work' for p in (out / 'exports').rglob('*'))
    report, export = exported(folder, out)
    uninterrupted = models_once[2]
    assert {k: v for k, v in report.items() if k != 'definition'} == {k: v for k, v in uninterrupted.items() if k != 'definition'}
    assert tree(export / 'files') == tree(models_once[3] / 'files')


def test_a_changed_model_byte_refuses_the_build_naming_it(tmp_path, project):
    folder, out = pack(tmp_path / 'definition'), tmp_path / 'export'
    exported(folder, out)
    p = current(out) / 'files/wells/SYN-A-time-depth.csv'
    p.write_bytes(p.read_bytes().replace(b'480,384', b'480,385'))
    assert refused(build, folder, out, project) == (
        'wells/SYN-A-time-depth.csv in the export at %s is not the file its report names: its SHA-256 differs.' % out + starter.NOT_WRITTEN)
    nothing_landed(folder, project)


# --- C3: the Python and ResInsight targets (D-8, F3, M2, R2-3, R2-8, R2-9, R2-10, R2-12) ------------------------------

import shutil  # noqa: E402

from test_starter_python import (WELL_KINDS, built, files, notebook, ran, rotated, targets, with_lines,  # noqa: E402,F401 (fixtures)
                                 BOTH, PYTHON, RESINSIGHT, ROTATED_ORACLE)
from test_starter_resinsight import ORACLE, connectors, imported, written  # noqa: E402,F401 (fixture)

A_PAIRS = [[120.0, 96.0], [480.0, 384.0], [960.0, 768.0], [1500.0, 1200.0]]
B_PAIRS = [[95.5, 0.05], [410.0, 0.2], [820.25, 0.41], [1230.0, 0.615]]
MODELS_EXPECTED = [{'well': 'SYN-A', 'path': 'wells/SYN-A-time-depth.csv', 'pairs': A_PAIRS},
                   {'well': 'SYN-B', 'path': 'wells/SYN-B-time-depth.csv', 'pairs': B_PAIRS}]
MODELS = ['wells/SYN-A-time-depth.csv', 'wells/SYN-B-time-depth.csv']
MODELS_SAID = ['Time-depth model SYN-A: 4 pairs checked', 'Time-depth model SYN-B: 4 pairs checked']
TD_SAID = 'Time-depth models: not placed; this starter does not import time-depth models into ResInsight'
RI_TD = "\nThis starter does not import time-depth models into ResInsight; the pack's time-depth models are not imported.\n"


def three(d):
    modelled(d); d['targets'] = ['opendtect', 'python', 'resinsight']


def lines_models(d):
    """R2-9: the 2D lines, the well paths and logs and the models; no cube."""
    with_lines(WELL_KINDS, BOTH + ['resinsight'])(d); modelled(d)


@pytest.fixture(scope='module')
def targeted(tmp_path_factory):
    """{case: (definition folder, export OUT)}: the rotated survey with the two models, all three targets (`cube`);
    the lines, paths and models without a cube (`lines`)."""
    out = {}
    for case, edit, variant in (('cube', three, 'rotated'), ('lines', lines_models, None)):
        folder, export = made(tmp_path_factory.mktemp('definition-' + case), edit=edit, raw=tables()), tmp_path_factory.mktemp('export-' + case)
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv('PYTHONPATH', os.pathsep.join([str(FAKE), str(CONNECTOR)]))
            if variant: mp.setenv('FAKE_ODBIND_VARIANT', variant)
            else: mp.delenv('FAKE_ODBIND_VARIANT', raising=False)
            run(folder, export)
        out[case] = folder, export
    return out


def test_the_notebook_checks_every_pair_and_says_so_after_the_run_and_a_rerun(targeted, rotated, tmp_path, project, notebook):
    """D-8 (F3), R2-3: expected.json gains `time_depth` last (the pairs as floats in file order), the model files join
    the Python target's reads, the waiting oracle is the pack's without models; the notebook passes, its result names
    each model's pair count and the oracle says each model checked, two values per pair and one per model, also after
    a rerun (bytes unchanged). Mutations: the model paths not in the target's reads; the oracle line left out."""
    folder = built(targeted, tmp_path, project, 'cube')
    python = targets(folder)['python']
    assert python['oracle'] == starter.ORACLE_PYTHON
    assert [a['path'] for a in python['artefacts']] == PYTHON + MODELS  # the derived order: the models are converted after the export
    expected = json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert list(expected)[-1] == 'time_depth' and expected['time_depth'] == MODELS_EXPECTED and expected['schema'] == 'ophiolite.starter-python-expected/1'
    doc, result = ran(folder)
    assert result['differences'] == [] and result['time_depth'] == [{'well': 'SYN-A', 'path': MODELS[0], 'pairs': 4}, {'well': 'SYN-B', 'path': MODELS[1], 'pairs': 4}]
    assert targets(folder)['python']['oracle'] == {'compared': ROTATED_ORACLE + MODELS_SAID, 'values': 11 + 2 * 9, 'differences': 0, 'seed': 0}
    kept = files(folder)
    ran(folder)
    assert files(folder) == kept


def test_a_folder_of_the_python_targets_artefacts_alone_runs_the_notebook(targeted, tmp_path, project):
    """R2-3: the target's listed artefacts are everything the notebook reads (a model file left out of `reads` makes
    the notebook fail on the missing file)."""
    from test_pack_notebook import notebook as run_notebook
    folder = built(targeted, tmp_path / 'built', project, 'cube')
    only = tmp_path / 'only'
    for a in targets(folder)['python']['artefacts']:
        (only / 'files' / a['path']).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(folder / 'pack/files' / a['path'], only / 'files' / a['path'])
    shutil.copyfile(folder / 'pack/starter.json', only / 'starter.json')
    done, result = run_notebook(tmp_path, pack=only)
    assert done.returncode == 0, done.stderr
    assert result['differences'] == [] and [m['pairs'] for m in result['time_depth']] == [4, 4]


@pytest.mark.parametrize('change, said', [
    (lambda t: t.replace(b'480,384', b'480,385'), ['pair 2 of the time-depth model of SYN-A']),
    (lambda t: t[:t.rindex(b'1500,1200\n')], ['the number of pairs of the time-depth model of SYN-A']),
    (lambda t: t + b'1600,1300\n', ['the number of pairs of the time-depth model of SYN-A']),
], ids=['changed-pair', 'removed-final-pair', 'appended-pair'])
def test_the_notebook_names_a_model_that_differs_from_expected(targeted, tmp_path, project, change, said):
    """M2, R2-8: the notebook run directly on the pack with SYN-A's file changed after the build while expected.json
    keeps the original pairs: the specific pair, or the count, is named and the notebook fails. Mutation: the notebook
    comparing counts only (the changed pair passes)."""
    from test_pack_notebook import notebook as run_notebook
    folder = built(targeted, tmp_path / 'built', project, 'cube')
    p = folder / 'pack/files' / MODELS[0]
    p.write_bytes(change(p.read_bytes()))
    done, result = run_notebook(tmp_path, pack=folder / 'pack')
    assert done.returncode != 0 and result['differences'] == said


def test_lines_paths_and_models_without_a_cube_expect_the_models_too(targeted, tmp_path, project, notebook, connectors):
    """R2-9: the no-cube branch: /2 with the lines, then `time_depth`; the models are the target's artefacts and the
    result's key; ResInsight states lines and models not placed."""
    folder = built(targeted, tmp_path, project, 'lines')
    expected = json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert (expected['schema'], expected['cube'], list(expected)[-2:], expected['time_depth']) == (
        'ophiolite.starter-python-expected/2', None, ['lines', 'time_depth'], MODELS_EXPECTED)
    assert set(MODELS) <= {a['path'] for a in targets(folder)['python']['artefacts']}
    doc, result = ran(folder)
    assert result['differences'] == [] and set(result) == starter.RESULT_KEYS | {'lines', 'time_depth'}
    assert targets(folder)['python']['oracle']['compared'][-2:] == MODELS_SAID
    assert targets(folder)['resinsight']['oracle']['compared'][1:3] == [starter.LINES_LINE, TD_SAID]


def test_resinsight_states_the_models_not_placed_before_after_and_on_a_rerun(targeted, tmp_path, project, connectors):
    """D-8, R2-12: TD_LINE after the cube's line in the waiting oracle, after a passing comparison and after a rerun
    (bytes unchanged); the launcher says it; the models are not the target's artefacts. Mutation: TD_LINE only in the
    waiting oracle (the comparison's oracle loses it, a resume refuses)."""
    folder = built(targeted, tmp_path, project, 'cube')
    ri = targets(folder)['resinsight']
    assert ri['oracle'] == {**starter.ORACLE_RESINSIGHT, 'compared': [starter.ORACLE_RESINSIGHT['compared'][0], TD_SAID, *starter.ORACLE_RESINSIGHT['compared'][1:]]}
    assert RI_TD in (folder / 'pack/files' / starter.RI_IMPORT).read_text()
    assert [a['path'] for a in ri['artefacts']] == RESINSIGHT
    imported(folder, connectors)
    assert targets(folder)['resinsight']['oracle'] == {**ORACLE, 'compared': [ORACLE['compared'][0], TD_SAID, *ORACLE['compared'][1:]]}
    kept = written(folder)
    imported(folder, connectors)
    assert written(folder) == kept


def test_a_pack_of_paths_and_logs_holds_no_model_by_its_folder(rotated, tmp_path, project):
    """R2-10: `wells/` holds paths and logs too; a pack without models has no `time_depth` key, no model statement, and
    keeps its launcher bytes. Mutation: detection by the `wells/` prefix."""
    folder = built(rotated, tmp_path, project)
    doc = json.loads((folder / 'pack/starter.json').read_text())
    assert any(d['path'].startswith('wells/') for d in doc['derived']) and not starter.holds_time_depth(doc)
    assert 'time_depth' not in json.loads((folder / 'pack/files' / starter.PY_EXPECTED).read_text())
    assert starter.resinsight_waiting(False, False, starter.holds_time_depth(doc)) == starter.ORACLE_RESINSIGHT
    assert b'time-depth' not in starter.resinsight_import({'id': 'x'}, {})
    assert starter.holds_time_depth({'derived': [{'path': 'wells/SYN-A-time-depth.csv'}]})
