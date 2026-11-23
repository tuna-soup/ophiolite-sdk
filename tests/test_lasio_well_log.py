"""E183 s2d C1: LAS is written from a well log's strict part, and the other header entries come back in order (strategy
E183-s2-curve-declaration, rev 2 closed: T1.1-T1.4, T1.6, T1.8; T1.5 is test_lasio_adapter.py).

Every log is SYNTHETIC: the capture fixture's curve, read in the well log form through test_well_log_read's mock
gateway, with header entries typed here. The written bytes are parsed by `parse` below, a complete LAS 2.0 reader of
this file's own (sections, the first-period and last-colon entry rule, the ~C column count against the ~A columns, wrap
and delimiter declarations, NULL to missing, numbers by Python's float). It shares no code with ophiolite.las_header,
the Connectors' las_reader or header_entries, nor with lasio, which writes the file."""
import copy
import inspect
import re

import pytest
from test_well_log_read import FORM, capture, described, pair, read, well_log  # noqa: F401 (capture is a fixture)
from ophiolite import lasio as adapter
from ophiolite.errors import AxisMismatch, Refused, ValidationFailed, VerificationFailed
from ophiolite.lasio import lasio_bytes, to_lasio

lasio = pytest.importorskip('lasio')


def entry(section, mnemonic, unit='', value='', description=''):
    return {'section': section, 'mnemonic': mnemonic, 'unit': unit, 'value': value, 'description': description}


# The file's header as received: 24 entries, in file order. The structural ones (~V VERS WRAP DLM, ~W STRT STOP STEP
# NULL WELL, every ~C line) carry values that are not the strict part's, so a copy of any of them shows.
RECEIVED = [
    entry('V', 'VERS', '', '2.0', 'LAS version'),
    entry('V', 'WRAP', '', 'YES', 'Wrapped rows'),
    entry('V', 'DLM', '', 'COMMA', 'Comma delimited'),
    entry('V', 'CREA', '', '2026-11-22 10:15:00', ''),
    entry('W', 'STRT', 'FT', '1.0', 'Start depth'),
    entry('W', 'STOP', 'FT', '2.0', 'Stop depth'),
    entry('W', 'STEP', 'FT', '0.5', 'Step'),
    entry('W', 'NULL', '', '-777.5', 'Null value'),
    entry('W', 'COMP', '', 'Synthetic Co', 'Company'),
    entry('W', 'WELL', '', 'HEADER-WELL-9', 'Well named in the file'),
    entry('W', 'PDAT', '', 'HEADER-DATUM', 'Permanent datum'),
    entry('W', 'SRVC', '', 'Synthetic service: logging', 'Service company'),
    entry('W', 'UWI', '', '', 'Unique well id'),
    entry('W', 'DATE', '', '22/11/2026', 'Date'),
    entry('C', 'DEPT', 'FT', '', 'Depth'),
    entry('C', 'GR', 'API', '', 'Gamma ray'),
    entry('C', 'SP', 'MV', '', 'Spontaneous potential'),
    entry('C', 'RHOB', 'G/C3', '', 'Bulk density'),
    entry('P', 'BHT', 'degC', '60', 'First reading'),
    entry('P', 'MATR', '', 'SAND', 'Matrix'),
    entry('P', 'BHT', 'degC', '61', 'Second reading'),
    entry('P', 'RMF', 'ohm.m', '0.5', 'Mud filtrate resistivity'),
    entry('O', '', '', 'Synthetic remark one', ''),
    entry('O', '', '', 'Synthetic remark two: colons kept', ''),
]
# Counted by hand: the 12 entries written as received, in file order: 1 ~V, 5 ~W (UWI's empty value stays empty), 4 ~P
# (BHT twice) and 2 ~O.
KEPT = [
    ('V', 'CREA', '', '2026-11-22 10:15:00', ''),
    ('W', 'COMP', '', 'Synthetic Co', 'Company'),
    ('W', 'PDAT', '', 'HEADER-DATUM', 'Permanent datum'),
    ('W', 'SRVC', '', 'Synthetic service: logging', 'Service company'),
    ('W', 'UWI', '', '', 'Unique well id'),
    ('W', 'DATE', '', '22/11/2026', 'Date'),
    ('P', 'BHT', 'degC', '60', 'First reading'),
    ('P', 'MATR', '', 'SAND', 'Matrix'),
    ('P', 'BHT', 'degC', '61', 'Second reading'),
    ('P', 'RMF', 'ohm.m', '0.5', 'Mud filtrate resistivity'),
    ('O', '', '', 'Synthetic remark one', ''),
    ('O', '', '', 'Synthetic remark two: colons kept', ''),
]


class Parsed:
    pass


def fields(line):
    """One ~V, ~W, ~C or ~P line: the mnemonic is before the first period, the unit runs from there to the first space or
    tab, the description follows the last colon that a space, a tab or the line's end follows; the value lies between."""
    if '.' in line:
        dot = line.index('.')
        mnemonic, rest = line[:dot], line[dot + 1:]
        end = 0
        while end < len(rest) and rest[end] not in ' \t': end += 1
        unit, rest = rest[:end], rest[end:]
    else:
        mnemonic, unit, rest = '', '', line
    cut = -1
    for at, char in enumerate(rest):
        if char == ':' and (at + 1 == len(rest) or rest[at + 1] in ' \t'): cut = at
    value, description = (rest[:cut], rest[cut + 1:]) if cut >= 0 else (rest, '')
    return mnemonic.strip(), unit, value.strip(), description.strip()


def parse(text):
    """A complete LAS 2.0 reader for these tests (see the module text). Raises ValueError when the ~A columns disagree
    with the ~C count."""
    out = Parsed(); out.entries = []; section = None; rows = []
    for line in text.split('\n'):
        written = line.strip()
        if section == 'A':
            if written and not written.startswith('#'): rows.append(written)
            continue
        if written.startswith('~'):
            section = written[1:2].upper(); continue
        if section is None or not written or written.startswith('#'): continue
        out.entries.append(('O', '', '', written, '') if section == 'O' else (section,) + fields(line))
    first = lambda s, m: next(e[3] for e in out.entries if e[:2] == (s, m))
    out.version = {m: first('V', m) for m in ('VERS', 'WRAP', 'DLM')}
    out.null = float(first('W', 'NULL'))
    out.curves = [(e[1], e[2]) for e in out.entries if e[0] == 'C']
    out.well = {e[1]: e[3] for e in out.entries if e[0] == 'W'}
    out.other = [e[3] for e in out.entries if e[0] == 'O']
    width = len(out.curves)
    delimiter = {'SPACE': None, 'COMMA': ',', 'TAB': '\t'}[out.version['DLM'].upper()]
    split = lambda row: [t.strip() for t in row.split(delimiter)] if delimiter else row.split()
    if out.version['WRAP'].upper() == 'YES':
        tokens = [t for row in rows for t in split(row)]
        if len(tokens) % width: raise ValueError('%d values do not fill rows of %d columns' % (len(tokens), width))
        table = [tokens[i:i + width] for i in range(0, len(tokens), width)]
    else:
        table = [split(row) for row in rows]
        for number, row in enumerate(table):
            if len(row) != width: raise ValueError('row %d has %d columns, ~C declares %d' % (number, len(row), width))
    numbers = [[float(t) for t in row] for row in table]
    out.columns = {name: [None if row[i] == out.null else row[i] for row in numbers] for i, (name, _) in enumerate(out.curves)}
    out.depth = [row[0] for row in numbers]
    return out


def kept(parsed, generated=4):
    """The entries written beside the structure: not ~V VERS WRAP DLM, not ~W STRT STOP STEP NULL WELL, no ~C line, and
    not the ~Other lines the writer makes (Project, Asset, Revision, Depth datum)."""
    out, other = [], 0
    for e in parsed.entries:
        if e[0] == 'C' or (e[0] == 'V' and e[1] in ('VERS', 'WRAP', 'DLM')) or (e[0] == 'W' and e[1] in ('STRT', 'STOP', 'STEP', 'NULL', 'WELL')):
            continue
        if e[0] == 'O':
            other += 1
            if other <= generated: continue
        out.append(e)
    return out


def logs(d, curve, artifact, curves=('GR',), entries=RECEIVED, **declared):
    """A read in the well log form of `curves` (each from the capture curve; SP and RHOB with their own unit and values)."""
    own = {'GR': {}, 'SP': {'unit': 'mV', 'values': [1.0, 2.0, 3.0, None, 5.0]}, 'RHOB': {'unit': 'g/cm3', 'values': [2.1, 2.2, 2.3, 2.4, None]}}
    answers = {}
    for name in curves:
        c = {**copy.deepcopy(curve), 'curve': name, **own[name]}
        if name == 'GR': c.update(declared.pop('gr', {}))
        form_d, raw = described(copy.deepcopy(d), well_log(c, entries=entries, **declared))
        form_d['scientific']['missing_value_marker'] = c['context']['missing_value_marker']  # the source's, as stated
        answers[name] = form_d, raw
    return read(d, answers, artifact, curves=curves, form=FORM)[0]


def written(data):
    return parse(lasio_bytes(to_lasio(data)).decode())


def test_the_reader_of_these_tests_reads_wrap_delimiter_and_null_and_rejects_a_column_short():
    text = ('~V\nVERS. 2.0 :\nWRAP. YES :\nDLM . COMMA :\n~W\nNULL. -5 :\n~C\nDEPT.M :\nA.u : first\nB.u : second\n~A\n'
            '1,2\n-5\n2,3,4\n')
    got = parse(text)
    assert got.depth == [1.0, 2.0] and got.columns == {'DEPT': [1.0, 2.0], 'A': [2.0, 3.0], 'B': [None, 4.0]}
    assert got.curves == [('DEPT', 'M'), ('A', 'u'), ('B', 'u')]
    with pytest.raises(ValueError): parse(text.replace('2,3,4', '2,3'))
    with pytest.raises(ValueError): parse(text.replace('YES', 'NO'))
    assert fields(' CREA.  2026-11-22 10:15:00') == ('CREA', '', '2026-11-22 10:15:00', '')
    assert fields('COM1. a: b : c') == ('COM1', '', 'a: b', 'c')


def test_t11_the_entries_as_received_come_back_in_order_and_the_structure_is_the_outputs(capture):
    """Acceptance 4. Mutations: entries sorted by mnemonic; a repeat dropped; the source VERS/WRAP copied; the source ~C
    lines appended: red each."""
    d, curve, artifact = capture
    raw = lasio_bytes(to_lasio(logs(d, curve, artifact))).decode()
    got = parse(raw)
    assert kept(got) == KEPT and len(KEPT) == 12  # 1 ~V, 5 ~W, 4 ~P (BHT twice), 2 ~O
    assert got.version == {'VERS': '2.0', 'WRAP': 'NO', 'DLM': 'SPACE'}  # D2: the bytes' own structure
    assert [e[1] for e in got.entries if e[0] == 'V'] == ['VERS', 'WRAP', 'DLM', 'CREA']  # the received ones once, not again
    assert got.curves == [('DEPT', 'M'), ('GR', 'gAPI')]  # D3/D8: generated from the strict selected data
    assert got.depth == [100.0, 101.0, 102.0, 103.0, 104.0] and got.columns['GR'] == [0.0, 10.0, None, 30.0, 40.0]
    assert [e[3] for e in got.entries if e[0] == 'C'] == ['', '']  # no source description
    assert got.other[:4] == ['Project %s' % d['project_id'], 'Asset %s' % d['asset_id'], 'Revision %s' % d['revision'], 'Depth datum unknown']
    rows = raw.split('~ASCII')[1].split('\n', 1)
    short = rows[0] + '\n' + '\n'.join(' '.join(r.split()[:-1]) for r in rows[1].splitlines())
    with pytest.raises(ValueError): parse(raw.split('~ASCII')[0] + '~ASCII' + short)  # a dropped column is rejected


def test_t12a_the_value_unit_is_the_strict_one(capture):
    """The received ~C says GR is in API; the strict part says gAPI. Mutation: the unit taken from the received ~C: red."""
    d, curve, artifact = capture
    got = written(logs(d, curve, artifact))
    assert got.curves[1] == ('GR', 'gAPI') and ('API' not in [u for _, u in got.curves])


def test_t12b_the_well_is_the_declared_one(capture):
    """Mutation: write the received WELL: red."""
    d, curve, artifact = capture
    data = logs(d, curve, artifact, well='SYNTHETIC-W7')
    raw = lasio_bytes(to_lasio(data)).decode()
    assert parse(raw).well['WELL'] == 'SYNTHETIC-W7' and 'HEADER-WELL-9' not in raw
    with pytest.raises(Refused) as caught: to_lasio(data, well='ANOTHER')
    assert caught.value.message == "A well log's well is the declaration stored with it; well= is not taken."


def test_t12c_the_null_marker_written_is_the_outputs_not_the_sources(capture):
    """C5. The source marker is -777.5: a real sample of -777.5 is written as a number and read back as that number; a
    real sample of -999.25 (the output's marker) is refused. Mutation: test the source marker instead: red."""
    d, curve, artifact = capture
    source = {'context': {**curve['context'], 'missing_value_marker': '-777.5'}}
    got = written(logs(d, curve, artifact, gr={**source, 'values': [-777.5, 10.0, None, 30.0, 40.0]}))
    assert got.null == -999.25 and got.columns['GR'] == [-777.5, 10.0, None, 30.0, 40.0]
    with pytest.raises(ValidationFailed) as caught:
        to_lasio(logs(d, curve, artifact, gr={**source, 'values': [-999.25, 10.0, None, 30.0, 40.0]}))
    assert caught.value.violations == ('Curve GR has a real value equal to the null marker -999.25; it would read back as missing.',)


def test_t12d_the_depth_range_is_the_datas(capture):
    """The received STRT, STOP, STEP say 1.0, 2.0, 0.5. Mutation: copy the received STRT: red."""
    d, curve, artifact = capture
    got = written(logs(d, curve, artifact))
    assert (float(got.well['STRT']), float(got.well['STOP']), float(got.well['STEP'])) == (100.0, 104.0, 1.0)


def test_t13_a_selection_is_written_in_the_callers_order_and_nothing_else(capture):
    d, curve, artifact = capture
    got = written(logs(d, curve, artifact, curves=('RHOB', 'GR')))
    assert got.curves == [('DEPT', 'M'), ('RHOB', 'g/cm3'), ('GR', 'gAPI')] and 'SP' not in got.columns
    assert got.columns['RHOB'] == [2.1, 2.2, 2.3, 2.4, None] and got.columns['GR'] == [0.0, 10.0, None, 30.0, 40.0]
    got = written(logs(d, curve, artifact, curves=('SP',)))
    assert got.curves == [('DEPT', 'M'), ('SP', 'mV')] and got.columns['SP'] == [1.0, 2.0, 3.0, None, 5.0]
    assert kept(got) == KEPT


@pytest.mark.parametrize('axis, step', [
    ([100.0, 101.0, 102.5, 103.0, 104.0], '0'),  # irregular: 0, never the first spacing
    ([2.0, 2.1, 2.2, 2.3, 2.4], '0.1'),  # the numbers as written are 0.1 apart, though their float differences are not equal
    ([2.0, 2.1, 2.2, 2.3, 2.45], '0'),
])
def test_t14_step_is_the_spacing_only_when_it_is_constant(capture, axis, step):
    """Mutations: STEP from the first two depths (lasio's own); STEP from float differences: red."""
    d, curve, artifact = capture
    raw = lasio_bytes(to_lasio(logs(d, curve, artifact, gr={'axis': axis}))).decode()
    got = parse(raw)
    assert got.well['STEP'] == step and got.depth == axis
    assert (got.well['STRT'], got.well['STOP']) == (repr(axis[0]), repr(axis[-1]))


def test_t14_a_one_sample_axis_writes_and_reads_back(capture):
    d, curve, artifact = capture
    got = written(logs(d, curve, artifact, gr={'axis': [100.0], 'values': [None]}))
    assert got.depth == [100.0] and got.columns['GR'] == [None] and got.well['STEP'] == '0'


@pytest.mark.parametrize('pdat', ['HEADER-DATUM', 'KB'])
def test_t16_the_datum_is_written_once_in_other_and_the_received_pdat_as_received(capture, pdat):
    """The declared datum is KB. A received PDAT, equal to it or not, is written as received; no datum mnemonic is
    written. Mutation: drop a received entry whose value equals the declared datum: red."""
    d, curve, artifact = capture
    entries = [dict(e, value=pdat) if e['mnemonic'] == 'PDAT' else e for e in RECEIVED]
    raw = lasio_bytes(to_lasio(logs(d, curve, artifact, entries=entries, datum='KB'))).decode()
    got = parse(raw)
    assert raw.count('Depth datum KB') == 1 and got.other[3] == 'Depth datum KB'
    assert [e for e in got.entries if e[1] == 'PDAT'] == [('W', 'PDAT', '', pdat, 'Permanent datum')]
    assert [e[1] for e in got.entries if e[0] == 'W'] == ['STRT', 'STOP', 'STEP', 'NULL', 'WELL', 'COMP', 'PDAT', 'SRVC', 'UWI', 'DATE']


def test_t16_no_code_path_of_the_adapter_compares_a_received_entry_value():
    """R-K1: a received entry's texts are only written (a header item, an ~Other line), never compared."""
    source = inspect.getsource(adapter)
    assert source.count("entry['value']") == 2
    assert not re.search(r"entry\[['\"](value|unit|description)['\"]\]\s*(==|!=|<|>|in\b|not in\b)", source)
    assert not re.search(r"(==|!=|\bin)\s*entry\[['\"](value|unit|description)['\"]\]", source)
    assert not re.search(r"\bmeta\.(well|depth_datum|depth_unit|depth_kind)\b\s*(==|!=)|(==|!=)\s*meta\.(well|depth_datum|depth_unit|depth_kind)\b", source)


def test_a_received_entry_lasio_would_write_otherwise_returns_nothing(capture):
    """lasio writes an empty value that has a unit as 0. The re-read of the entries finds it, and nothing is returned
    (never a 0 the file did not say). Mutation: the entries' re-read dropped: red."""
    d, curve, artifact = capture
    entries = RECEIVED + [entry('P', 'TDL', 'm', '', 'Logger depth, not stated')]
    las = to_lasio(logs(d, curve, artifact, entries=entries))
    with pytest.raises(VerificationFailed) as caught: lasio_bytes(las)
    assert caught.value.message == 'lasio wrote the header entries as received differently or out of order; nothing was returned.'


@pytest.mark.parametrize('second, reason', [
    (lambda c: {'well': 'SYNTHETIC-W2'}, 'well'),
    (lambda c: {'kind': 'TVD'}, 'kind'),
    (lambda c: {'datum': 'KB'}, 'datum'),
])
def test_t18_well_logs_that_differ_are_refused_before_any_file_is_built(capture, monkeypatch, second, reason):
    """Mutation: to_lasio without the alignment check: red."""
    d, curve, artifact = capture
    data = pair(d, curve, artifact, **second(curve))
    built = []
    monkeypatch.setattr(lasio, 'LASFile', lambda *a, **k: built.append(1))
    with pytest.raises(AxisMismatch) as caught: to_lasio(data)
    assert caught.value.reason == reason and built == []


def test_t18_old_and_new_forms_together_are_refused(capture, fixture):
    from ophiolite.client import WellLogSet
    d, curve, artifact = capture
    new = logs(d, curve, artifact)
    old, _ = read(d, {}, artifact, old=(d, fixture('capture')[1]))
    with pytest.raises(Refused) as caught: to_lasio(WellLogSet(new.descriptors + old.descriptors, new.curves + old.curves, artifact))
    assert caught.value.message == 'Well logs and application curves are not combined in one view; read them with one form.'
