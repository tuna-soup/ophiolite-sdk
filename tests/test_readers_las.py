"""E128 s3: ophiolite.readers reads las2/1 whole. Every input is a byte literal written here (board ruling e128s2,
carried: no files, nothing copied from a third-party file; the bundled HON-GT-01 excerpt is read by path). Every
expected value is a literal written from the grammar (E128-readers-S3-COMMIT-STRATEGY.md); the server's readers are
then given the same bytes and asked to agree (parity), never used as the expectation."""
import math
from pathlib import Path
from types import MappingProxyType

import pytest

import ophiolite
from ophiolite import readers
from ophiolite.readers import Las, ReadRefused, las
from ophiolite.writers import write_curves

NO_REPAIR = ' No repair was applied.'
NAN = float('nan')
LAS_ROWS_MAX, LAS_VALUES = 4_000_000, 16_777_216


def typed(actual, expected, where):
    """`actual` equals `expected` with the type at every level. A float matches a float that is NaN when it is NaN, and
    otherwise equal with the same sign (so -0.0 is not 0.0); None matches only None (E128 s3 point 2d)."""
    if isinstance(expected, dict):
        assert type(actual) is MappingProxyType, where
        assert list(actual) == list(expected), (where, list(actual), list(expected))
        for key in expected: typed(actual[key], expected[key], where + '.' + key)
    elif isinstance(expected, tuple):
        assert type(actual) is tuple and len(actual) == len(expected), (where, actual, expected)
        for i, (a, e) in enumerate(zip(actual, expected)): typed(a, e, '%s[%d]' % (where, i))
    elif isinstance(expected, float):
        assert type(actual) is float, (where, actual, expected)
        if math.isnan(expected): assert math.isnan(actual), (where, actual)
        else: assert actual == expected and math.copysign(1, actual) == math.copysign(1, expected), (where, actual, expected)
    else:
        assert type(actual) is type(expected) and actual == expected, (where, actual, expected)


# The pieces most cases are built from, with the header tuples they read to.
V2 = b'~Version\nVERS.   2.0 : CWLS LAS 2.0\nWRAP.   NO  : one line per depth\n'
V2_ITEMS = (('VERS', '', '2.0', 'CWLS LAS 2.0'), ('WRAP', '', 'NO', 'one line per depth'))
WR = V2.replace(b'WRAP.   NO ', b'WRAP.   YES')
WR_ITEMS = (('VERS', '', '2.0', 'CWLS LAS 2.0'), ('WRAP', '', 'YES', 'one line per depth'))
W = (b'~Well\nSTRT.M  1500.0000 : start\nSTOP.M 1501.0000 : stop\nSTEP.M 0.5000 : step\nNULL.  -999.2500 : null\n'
     b'WELL.  A-1 : well\nUWI .  0012 : uwi\n')
W_ITEMS = (('STRT', 'M', '1500.0000', 'start'), ('STOP', 'M', '1501.0000', 'stop'), ('STEP', 'M', '0.5000', 'step'),
           ('NULL', '', '-999.2500', 'null'), ('WELL', '', 'A-1', 'well'), ('UWI', '', '0012', 'uwi'))
C = b'~Curve\nDEPT.M   : depth\nGR  .GAPI 30 310 01 00 : gamma\n'
C_ITEMS = (('DEPT', 'M', '', 'depth'), ('GR', 'GAPI', '30 310 01 00', 'gamma'))
C3 = b'~Curve\nDEPT.M : d\nA. : a\nB. : b\n'
C3_ITEMS = (('DEPT', 'M', '', 'd'), ('A', '', '', 'a'), ('B', '', '', 'b'))
A = b'~ASCII\n1500.0 10\n1500.5 -999.2500\n1501.0 12\n'
A_DATA = ((1500.0, 10.0), (1500.5, None), (1501.0, 12.0))
SPACE = {'version': '2.0', 'layout': 'las2', 'delimiter': 'space'}
BASE = {'context': SPACE, 'version': '2.0', 'version_section': V2_ITEMS, 'well': W_ITEMS, 'curves': C_ITEMS, 'parameters': (),
        'other': None, 'null': '-999.2500', 'data': A_DATA}


def read_as(**changes):
    return {**BASE, **changes}


def W12(text):
    """A ~W written for a LAS 1.2 file: WELL as `descr : value`."""
    return text.replace(b'WELL.  A-1 : well', b'WELL.  : A-1').replace(b'UWI .  0012 : uwi', b'COMP.  COMPANY : ACME')


W12_ITEMS = W_ITEMS[:4] + (('WELL', '', 'A-1', ''), ('COMP', '', 'ACME', 'COMPANY'))
VERSION = 'Unsupported LAS: version %s is not read; LAS 1.2, 2.0 and 3.0 files are. No conversion was applied.'
LAYOUT = ('Unsupported LAS: this file uses LAS 3.0 data sections (such as ~Log_Data with its definitions), which are not read; '
          'LAS files with one ~ASCII data section are. No conversion was applied.')
SECTION = ' is not a LAS 2 section; LAS files with the ~V, ~W, ~C, ~P, ~O and ~A sections are read.' + NO_REPAIR
SAME, REFUSED = 'same', 'refused'

# name: (bytes, declared, expected, (read_las, read_columns)). `expected` is the Las fields, or a refusal
# (sentence, code, field, row). Each server outcome is SAME (it reads what the SDK reads, over the S3-D4 projection),
# REFUSED, or the data rows it reads instead (NaN as 'nan', -0.0 as '-0'). Since D-31 no case reads differently: the
# D-1 to D-5 divergences are refused by both servers in the SDK's words, and each split takes the side its name says.
CASES = {
    # --- the named hard cases (main strategy §5, s3) ---
    'a 2.0 file': (V2 + W + C + A, None, read_as(), (SAME, SAME)),
    'a 1.2 file, its ~W in the 1.2 order': (
        V2.replace(b'2.0 :', b'1.2 :') + W12(W) + C + A, None,
        read_as(context={**SPACE, 'version': '1.2'}, version='1.2', version_section=(('VERS', '', '1.2', 'CWLS LAS 2.0'), V2_ITEMS[1]),
                well=W12_ITEMS), (SAME, SAME)),
    'a 3.0 file in the LAS 2 layout': (
        V2.replace(b'2.0 :', b'3.0 :') + W + C + A, None,
        read_as(context={**SPACE, 'version': '3.0'}, version='3.0', version_section=(('VERS', '', '3.0', 'CWLS LAS 2.0'), V2_ITEMS[1])),
        (SAME, SAME)),
    'a wrapped file, rows by the curve count': (
        WR + W + C + b'~A\n1500.0\n10\n1500.5\n-999.25\n', None, read_as(version_section=WR_ITEMS, data=((1500.0, 10.0), (1500.5, None))),
        (SAME, SAME)),
    'a ~V line without a colon': (
        V2 + b'CREA.   2020-10-11\n' + W + C + A, None,
        read_as(version_section=V2_ITEMS + (('CREA', '', '2020-10-11', ''),)), (SAME, SAME)),
    'duplicate mnemonics kept in order': (
        V2 + W + b'WELL. B-2 : again\n~Curve\nDEPT.M : d\nGR.GAPI : g\nGR.GAPI : g2\n~A\n1 2 3\n', None,
        read_as(well=W_ITEMS + (('WELL', '', 'B-2', 'again'),), curves=(('DEPT', 'M', '', 'd'), ('GR', 'GAPI', '', 'g'), ('GR', 'GAPI', '', 'g2')),
                data=((1.0, 2.0, 3.0),)), (SAME, SAME)),
    '~O present and empty': (V2 + W + C + b'~Other\n' + A, None, read_as(other=()), (SAME, SAME)),
    '~O lines as written': (
        V2 + W + C + b'~Other\n  free text: here\n\n# c\nline two\n' + A, None,
        read_as(other=('  free text: here', '', '# c', 'line two')), (SAME, SAME)),
    'the NULL text kept, -999.25 nulls -999.2500': (
        V2 + W.replace(b'-999.2500', b'-999.25') + C + A, None, read_as(well=W_ITEMS[:3] + (('NULL', '', '-999.25', 'null'),) + W_ITEMS[4:],
                                                                         null='-999.25'), (SAME, SAME)),
    # --- version ---
    'VERS 1.20': (V2.replace(b'2.0 :', b'1.20 :') + W + C + A, None,
                  read_as(context={**SPACE, 'version': '1.2'}, version='1.20', version_section=(('VERS', '', '1.20', 'CWLS LAS 2.0'), V2_ITEMS[1]),
                          well=W_ITEMS[:4] + (('WELL', '', 'well', 'A-1'), ('UWI', '', 'uwi', '0012'))), (SAME, SAME)),
    'VERS 2': (V2.replace(b'2.0 :', b'2 :') + W + C + A, None,
               read_as(version='2', version_section=(('VERS', '', '2', 'CWLS LAS 2.0'), V2_ITEMS[1])), (SAME, SAME)),
    'VERS in Arabic-Indic digits is read by float()': (
        V2.replace(b'2.0 :', '٢.٠ :'.encode()) + W + C + A, None,
        read_as(version='٢.٠', version_section=(('VERS', '', '٢.٠', 'CWLS LAS 2.0'), V2_ITEMS[1])), (SAME, SAME)),
    'VERS twice: the policy takes the first, ~W in the 2.0 order': (
        V2.replace(b'2.0 :', b'1.2 :') + b'VERS. 2.0 : again\n' + W + C + A, None,
        read_as(context={**SPACE, 'version': '1.2'}, version='1.2',
                version_section=(('VERS', '', '1.2', 'CWLS LAS 2.0'), V2_ITEMS[1], ('VERS', '', '2.0', 'again'))), (SAME, SAME)),
    'a lowercase vers acts in a 1.2 file': (
        V2.replace(b'VERS.   2.0', b'vers.   1.2') + W12(W) + C + A, None,
        read_as(context={**SPACE, 'version': '1.2'}, version='1.2', version_section=(('vers', '', '1.2', 'CWLS LAS 2.0'), V2_ITEMS[1]),
                well=W12_ITEMS), (SAME, SAME)),
    'a lowercase strt is exempt from the 1.2 order': (
        V2.replace(b'2.0 :', b'1.2 :') + W12(W).replace(b'STRT', b'strt') + C + A, None,
        read_as(context={**SPACE, 'version': '1.2'}, version='1.2', version_section=(('VERS', '', '1.2', 'CWLS LAS 2.0'), V2_ITEMS[1]),
                well=(('strt', 'M', '1500.0000', 'start'),) + W12_ITEMS[1:]), (SAME, SAME)),
    '~W before ~V is read in the 2.0 order': (
        W12(W) + V2.replace(b'2.0 :', b'1.2 :') + C + A, None,
        read_as(context={**SPACE, 'version': '1.2'}, version='1.2', version_section=(('VERS', '', '1.2', 'CWLS LAS 2.0'), V2_ITEMS[1]),
                well=W_ITEMS[:4] + (('WELL', '', '', 'A-1'), ('COMP', '', 'COMPANY', 'ACME'))), (SAME, SAME)),
    'an unstated version': (W + C + A, None, (VERSION % 'not stated', 'version', 'VERS', None), (REFUSED, REFUSED)),
    'a BOM: no version is found': (b'\xef\xbb\xbf' + V2 + W + C + A, None, (VERSION % 'not stated', 'version', 'VERS', None),
                                   (REFUSED, REFUSED)),
    'VERS 1.3': (V2.replace(b'2.0 :', b'1.3 :') + W + C + A, None, (VERSION % '1.3', 'version', 'VERS', None), (REFUSED, REFUSED)),
    # --- layout and delimiter ---
    'LAS 3 data sections': (
        V2.replace(b'2.0 :', b'3.0 :') + W + b'~Log_Definition\nDEPT.M : d\n~Log_Data | Log_Definition\n1 2\n', None,
        (LAYOUT, 'layout', None, None), (REFUSED, REFUSED)),
    'a second ~A': (V2 + W + C + A + A, None, (LAYOUT, 'layout', None, None), (REFUSED, REFUSED)),
    'a comma delimiter': (
        V2 + b'DLM .  COMMA : c\n' + W + C + A, None,
        ('Unsupported LAS: the data are delimited by COMMA; LAS files delimited by spaces or tabs are read. No conversion was applied.',
         'delimiter', 'DLM', None), (REFUSED, REFUSED)),
    'DLM TAB with tab data': (
        V2 + b'DLM .  TAB : tab\n' + W + C + b'~A\n1500.0\t10\n1500.5\t11\n', None,
        read_as(context={**SPACE, 'delimiter': 'tab'}, version_section=V2_ITEMS + (('DLM', '', 'TAB', 'tab'),),
                data=((1500.0, 10.0), (1500.5, 11.0))), (SAME, SAME)),
    'DLM TAB with space data': (
        V2 + b'DLM .  TAB : tab\n' + W + C + b'~A\n1500.0 10\n1500.5 11\n', None,
        read_as(context={**SPACE, 'delimiter': 'tab'}, version_section=V2_ITEMS + (('DLM', '', 'TAB', 'tab'),),
                data=((1500.0, 10.0), (1500.5, 11.0))), (SAME, SAME)),
    'DLM twice is read with the first': (
        V2 + b'DLM. TAB : t\nDLM. SPACE : s\n' + W + C + A, None,
        read_as(context={**SPACE, 'delimiter': 'tab'}, version_section=V2_ITEMS + (('DLM', '', 'TAB', 't'), ('DLM', '', 'SPACE', 's'))),
        (SAME, SAME)),
    'DLM written space': (V2 + b'DLM .  space : s\n' + W + C + A, None,
                          ('DLM space is not written SPACE or TAB.' + NO_REPAIR, 'delimiter', 'DLM', None), (REFUSED, REFUSED)),
    'DLM empty': (V2 + b'DLM. : e\n' + W + C + A, None, ('DLM  is not written SPACE or TAB.' + NO_REPAIR, 'delimiter', 'DLM', None),
                  (REFUSED, REFUSED)),
    # --- wrap ---
    'no WRAP line': (b'~Version\nVERS. 2.0 : v\n' + W + C + A, None,
                     ('The ~V section has no WRAP line.' + NO_REPAIR, 'missing-key', 'WRAP', None), (REFUSED, REFUSED)),
    'WRAP twice': (V2 + b'WRAP. NO : again\n' + W + C + A, None,
                   ('The ~V section states WRAP 2 times (NO, NO); none was chosen.' + NO_REPAIR, 'repeated-key', 'WRAP', None),
                   (REFUSED, REFUSED)),
    'WRAP yes is wrapped': (
        V2.replace(b'WRAP.   NO ', b'WRAP.   yes') + W + C + b'~A\n1500.0\n10\n1500.5\n-999.25\n', None,
        read_as(version_section=(V2_ITEMS[0], ('WRAP', '', 'yes', 'one line per depth')), data=((1500.0, 10.0), (1500.5, None))),
        (SAME, SAME)),
    'WRAP MAYBE is unwrapped': (
        V2.replace(b'WRAP.   NO ', b'WRAP.   MAYBE') + W + C + A, None,
        read_as(version_section=(V2_ITEMS[0], ('WRAP', '', 'MAYBE', 'one line per depth'))), (SAME, SAME)),
    'wrapped with 65 curves': (
        WR + W + b'~Curve\n' + b''.join(b'C%d. : c\n' % i for i in range(65)) + b'~A\n' + b' '.join([b'1'] * 65) + b'\n', None,
        ('A wrapped LAS file has 1 to 64 curves; this one has 65.' + NO_REPAIR, 'limit', '~C', None), (REFUSED, REFUSED)),
    # --- sections ---
    'an indented ~A and a titled ~ASCII': (
        V2 + W + C + b'  ~ASCII LOG DATA\n1 2\n', None, read_as(data=((1.0, 2.0),)), (SAME, SAME)),
    'CRLF line ends': ((V2 + W + C + A).replace(b'\n', b'\r\n'), None, read_as(), (SAME, SAME)),
    'comments and blank lines in every section': (
        b'# made by x\n\n' + V2 + b'# c\n\n' + W + b'# c\n' + C + b'\n# c\n' + b'~A\n# c\n1500.0 10\n\n1500.5 11\n', None,
        read_as(data=((1500.0, 10.0), (1500.5, 11.0))), (SAME, SAME)),
    'a ~P section, time values kept whole': (
        V2 + W + C + b'~Parameter\nTIME.  13:45 : logged\nBHT .DEGC 35,5 : temp\nEMPTY. : nothing\nDATE. 12:30:00 : t\n'
        b'A.  x:y : z\n' + A, None,
        read_as(parameters=(('TIME', '', '13:45', 'logged'), ('BHT', 'DEGC', '35,5', 'temp'), ('EMPTY', '', '', 'nothing'),
                            ('DATE', '', '12:30:00', 't'), ('A', '', 'x', 'y : z'))), (SAME, SAME)),
    '~P present and empty': (V2 + W + C + b'~Parameter\n' + A, None, read_as(), (SAME, SAME)),
    'a single-curve file': (V2 + W + b'~Curve\nDEPT.M : d\n~A\n1\n2\n', None,
                            read_as(curves=(('DEPT', 'M', '', 'd'),), data=((1.0,), (2.0,))), (SAME, SAME)),
    'a lowercase ~curve title': (
        V2 + W + b'~curve\nDEPT.M : d\n~A\n1\n', None, ('Section ~curve on line 11' + SECTION, 'section', '~curve', 11), (REFUSED, REFUSED)),
    'empty bytes': (b'', None, ('The file is empty.' + NO_REPAIR, 'empty', None, None), (REFUSED, REFUSED)),
    'no ~ line': (b'hello\n', None, ('This file has no ~ section; it is not read as LAS.' + NO_REPAIR, 'not-las', None, None),
                  (REFUSED, REFUSED)),
    'no ~C section (read_columns)': (V2 + W + A, None, ('The file has no ~C section.' + NO_REPAIR, 'missing-section', '~C', None),
                                     (REFUSED, REFUSED)),
    'a ~C with no curves (read_columns)': (
        V2 + W + b'~Curve\n' + A, None, ('The ~C section declares no curves.' + NO_REPAIR, 'no-curves', '~C', None), (REFUSED, REFUSED)),
    'not UTF-8': (V2 + W + C + b'~A\n1500.0 \xe9\n', None,
                  ('Unsupported LAS: file is not UTF-8. Export a UTF-8 LAS 2.0 copy; no repair was applied.', 'not-utf8', None, None),
                  (REFUSED, REFUSED)),
    # --- header lines ---
    'header forms': (
        V2 + W + b'FLD .   NORTH SEA\nCTRY : NL\n~Curve\n.DEPT.[M] : d\nGR SPEC.GAPI. : g\nRT.OHMM:deep\nRES..OHMM : r\n'
        b'PR.1000 psi : p\nTEMP.DEGC\n~A\n1 2 3 4 5 6\n', None,
        read_as(well=W_ITEMS + (('FLD', '', 'NORTH SEA', ''), ('CTRY', '', 'NL', '')),
                curves=(('DEPT', '[M]', '', 'd'), ('GR SPEC', 'GAPI.', '', 'g'), ('RT', 'OHMM', '', 'deep'), ('RES.', 'OHMM', '', 'r'),
                        ('PR', '1000 psi', '', 'p'), ('TEMP', 'DEGC', '', '')),
                data=((1.0, 2.0, 3.0, 4.0, 5.0, 6.0),)), (SAME, SAME)),
    'a line that is not a header line': (
        V2 + W + b'BADLINE\n' + C + A, None,
        ('Line 11 of the ~W section is not a LAS header line (MNEM.UNIT VALUE : DESCRIPTION).' + NO_REPAIR, 'header-line', '~W', 11),
        (REFUSED, REFUSED)),
    # --- NULL ---
    'NULL -999,25 nulls -999.25': (
        V2 + W.replace(b'-999.2500', b'-999,25') + C + b'~A\n1500.0 10\n1500.5 -999.25\n', None,
        read_as(well=W_ITEMS[:3] + (('NULL', '', '-999,25', 'null'),) + W_ITEMS[4:], null='-999,25', data=((1500.0, 10.0), (1500.5, None))),
        (SAME, SAME)),
    'NULL abc nulls nothing': (
        V2 + W.replace(b'-999.2500', b'abc') + C + A, None,
        read_as(well=W_ITEMS[:3] + (('NULL', '', 'abc', 'null'),) + W_ITEMS[4:], null='abc', data=((1500.0, 10.0), (1500.5, -999.25), (1501.0, 12.0))),
        (SAME, SAME)),
    'NULL inf nulls nothing unwrapped (read_las)': (
        V2 + W.replace(b'-999.2500', b'inf') + C + b'~A\n1500.0 inf\n', None,
        read_as(well=W_ITEMS[:3] + (('NULL', '', 'inf', 'null'),) + W_ITEMS[4:], null='inf', data=((1500.0, math.inf),)),
        (SAME, SAME)),
    'NULL inf nulls inf wrapped': (
        WR + W.replace(b'-999.2500', b'inf') + C + b'~A\n1500.0\ninf\n', None,
        read_as(version_section=WR_ITEMS, well=W_ITEMS[:3] + (('NULL', '', 'inf', 'null'),) + W_ITEMS[4:], null='inf', data=((1500.0, None),)),
        (SAME, SAME)),
    'NULL abc wrapped (read_las)': (
        WR + W.replace(b'-999.2500', b'abc') + C + b'~A\n1500.0\n10\n', None,
        ('NULL abc is not a number.' + NO_REPAIR, 'null', 'NULL', None), (REFUSED, REFUSED)),
    'depth equal to NULL is None (read_columns)': (
        V2 + W + C + b'~A\n-999.2500 10\n1500.5 11\n', None, read_as(data=((None, 10.0), (1500.5, 11.0))),
        (SAME, SAME)),
    'depth equal to NULL wrapped': (
        WR + W + C + b'~A\n-999.25\n10\n', None, read_as(version_section=WR_ITEMS, data=((None, 10.0),)), (SAME, SAME)),
    # --- data ---
    'number spellings': (
        V2 + W + C + '~A\n1500.0 NaN\n1500.5 1,5\n1501.0 inf\n1e3 +5\n.5 5.\n-0.0 ١٢\n'.encode(), None,
        read_as(data=((1500.0, NAN), (1500.5, 1.5), (1501.0, math.inf), (1000.0, 5.0), (0.5, 5.0), (-0.0, 12.0))), (SAME, SAME)),
    'negative zero': (V2 + W + C + b'~A\n-0.0 -0.0\n', None, read_as(data=((-0.0, -0.0),)), (SAME, SAME)),
    'an empty ~A': (V2 + W + C + b'~A\n', None, read_as(data=()), (SAME, SAME)),
    'an empty wrapped ~A': (WR + W + C + b'~A\n', None, ('The wrapped ~A section holds no values.' + NO_REPAIR, 'row-count', '~A', None),
                            (REFUSED, REFUSED)),
    'chr(26) at the end is removed': (V2 + W + C + b'~A\n1500.0 10\n\x1a', None, read_as(data=((1500.0, 10.0),)), (SAME, SAME)),
    'chr(26) wrapped': (WR + W + C + b'~A\n1500.0\n10\n\x1a\n', None,
                        ('Line 17 of the ~A section has a value that is not a number: \x1a.' + NO_REPAIR, 'not-a-number', '~A', 17),
                        (REFUSED, REFUSED)),
    'wrapped 1,5': (WR + W + C + b'~A\n1500.0\n1,5\n', None,
                    ('Line 16 of the ~A section has a value that is not a number: 1,5.' + NO_REPAIR, 'not-a-number', '~A', 16),
                    (REFUSED, REFUSED)),
    'run-on 10-5 splits where not every line has a -': (
        V2 + W + C3 + b'~A\n1500.0 10-5\n1500.5 2 3\n', None, read_as(curves=C3_ITEMS, data=((1500.0, 10.0, -5.0), (1500.5, 2.0, 3.0))),
        (SAME, SAME)),
    'run-on 10-5 across lines': (
        V2 + W + C3 + b'~A\n1500.0 10-5\n1500.5 2\n3\n', None, read_as(curves=C3_ITEMS, data=((1500.0, 10.0, -5.0), (1500.5, 2.0, 3.0))),
        (SAME, SAME)),
    'a - on every line (read_las)': (
        V2 + W + C3 + b'~A\n1500.0 10-5\n1500.5 2-1\n', None,
        ('Every data line holds 2 values; the ~C section declares 3 curves.' + NO_REPAIR, 'row-count', '~A', None),
        (REFUSED, REFUSED)),
    'run-on 1.2.3 and NaN.5 are two NaN': (
        V2 + W + C3 + b'~A\n1500.0 1.2.3\n1500.5 NaN.5\n', None, read_as(curves=C3_ITEMS, data=((1500.0, NAN, NAN), (1500.5, NAN, NAN))),
        (SAME, SAME)),
    'run-on 1.2.3 making every line 3 values (read_columns)': (
        V2 + W + C + b'~A\n1500.0 1.2.3\n', None,
        ('Every data line holds 3 values; the ~C section declares 2 curves.' + NO_REPAIR, 'row-count', '~A', None),
        (REFUSED, REFUSED)),
    'one value too few': (V2 + W + C + b'~A\n1500.0 10\n1500.5\n1501 12\n', None,
                          ('The ~A section has 5 values, which is not a whole number of rows of 2 curves.' + NO_REPAIR, 'row-count', '~A', None),
                          (REFUSED, REFUSED)),
    'text data (read_columns)': (
        V2 + W + C + b'~A\n1500.0 10\n1501.0 abc\n', None,
        ('Line 16 of the ~A section has a value that is not a number: abc.' + NO_REPAIR, 'not-a-number', '~A', 16),
        (REFUSED, REFUSED)),
    'a # note after values (read_columns)': (
        V2 + W + C + b'~A\n1500.0 10 # note\n1500.5 11\n', None,
        ('Line 15 of the ~A section has a value that is not a number: #.' + NO_REPAIR, 'not-a-number', '~A', 15),
        (REFUSED, REFUSED)),
    'a NUL byte (read_columns)': (V2 + W + C + b'~A\n1500.0 10\x00\n', None, ('The file contains binary data.' + NO_REPAIR, 'binary', None, None),
                                  (REFUSED, REFUSED)),
    'a long first row is read by count (read_las)': (
        V2 + W + C + b'~A\n1500.0 10 1500.5\n11\n', None, read_as(data=((1500.0, 10.0), (1500.5, 11.0))), (SAME, SAME)),
    'a short first row is read by count (read_las)': (
        V2 + W + C + b'~A\n1\n2 3 4\n', None, read_as(data=((1.0, 2.0), (3.0, 4.0))), (SAME, SAME)),
    'the first 21 lines 3 values for 2 curves (read_columns)': (  # lasio's look, not every line (S3-D6)
        V2 + W + C + b'~A\n' + b'1 2 3\n' * 21 + b'4\n', None,
        ('Every data line holds 3 values; the ~C section declares 2 curves.' + NO_REPAIR, 'row-count', '~A', None),
        (REFUSED, REFUSED)),
    'every line 3 values for 2 curves (read_columns)': (
        V2 + W + C + b'~A\n1 2 3\n\n4 5 6\n', None,
        ('Every data line holds 3 values; the ~C section declares 2 curves.' + NO_REPAIR, 'row-count', '~A', None),
        (REFUSED, REFUSED)),
    'every line 1 value for 2 curves (read_columns)': (
        V2 + W + C + b'~A\n1\n2\n3\n4\n', None,
        ('Every data line holds 1 values; the ~C section declares 2 curves.' + NO_REPAIR, 'row-count', '~A', None),
        (REFUSED, REFUSED)),
    # --- D-1 to D-5: the SDK and, since D-31, both servers refuse and name what they found (closure Q1) ---
    'D-1 a custom section': (
        V2 + W + C + b'~X custom\nFOO. 1 : f\n' + A, None, ('Section ~X custom on line 14' + SECTION, 'section', '~X custom', 14),
        (REFUSED, REFUSED)),
    'D-1 a ~C_x section': (
        V2 + W + C + b'~C_x\nFOO. 1 : f\n' + A, None, ('Section ~C_x on line 14' + SECTION, 'section', '~C_x', 14), (REFUSED, REFUSED)),
    'D-1 ~Log_Data before ~A in a 2.0 file': (
        V2 + W + C + b'~Log_Data\n1 2\n' + A, None, ('Section ~Log_Data on line 14' + SECTION, 'section', '~Log_Data', 14),
        (REFUSED, REFUSED)),
    'D-2 a lowercase ~version': (
        V2.replace(b'~Version', b'~version') + W + C + A, None, ('Section ~version on line 1' + SECTION, 'section', '~version', 1),
        (REFUSED, REFUSED)),
    'D-2 a lowercase ~well': (
        V2 + W.replace(b'~Well', b'~well') + C + A, None, ('Section ~well on line 4' + SECTION, 'section', '~well', 4), (REFUSED, REFUSED)),
    'D-3 a repeated ~W': (
        V2 + W + b'~Well\nFLD. F : field\n' + C + A, None,
        ('Section ~Well on line 11 repeats the ~W section of line 4; neither was chosen.' + NO_REPAIR, 'repeated-section', '~Well', 11),
        (REFUSED, REFUSED)),
    'D-3 a repeated ~O': (
        V2 + W + C + b'~Other\none\n~Other\ntwo\n' + A, None,
        ('Section ~Other on line 16 repeats the ~O section of line 14; neither was chosen.' + NO_REPAIR, 'repeated-section', '~Other', 16),
        (REFUSED, REFUSED)),
    'D-4 no ~W': (V2 + C + A, None, ('The file has no ~W section.' + NO_REPAIR, 'missing-section', '~W', None), (REFUSED, REFUSED)),
    'D-4 a ~W without NULL': (
        V2 + W.replace(b'NULL.  -999.2500 : null\n', b'') + C + A, None,
        ('The ~W section has no NULL line.' + NO_REPAIR, 'missing-key', 'NULL', None), (REFUSED, REFUSED)),
    'D-4 NULL twice': (
        V2 + W + b'NULL. -1 : again\n' + C + A, None,
        ('The ~W section states NULL 2 times (-999.2500, -1); none was chosen.' + NO_REPAIR, 'repeated-key', 'NULL', None), (REFUSED, REFUSED)),
    'D-5 text before the first section': (
        b'made by x\n' + V2 + W + C + A, None,
        ('Line 1 comes before the first ~ section and is not a comment: made by x' + NO_REPAIR, 'section', None, 1), (REFUSED, REFUSED)),
    # --- declared ---
    'a declaration kept as supplied': (V2 + W + C + A, {'crs': 'EPSG:28992'}, read_as(), (SAME, SAME)),
    'a declaration that is not an object': (V2 + W + C + A, ['crs'], ('Declared context must be an object.' + NO_REPAIR, 'refused', None, None),
                                            None),  # the servers take no LAS declaration (S3-D2)
}
ACCEPTED = [name for name, case in CASES.items() if isinstance(case[2], dict)]
REFUSALS = [name for name, case in CASES.items() if isinstance(case[2], tuple)]


class Version:
    def __init__(self, **attributes): self.__dict__.update(attributes)


def written(tmp_path, raw):
    path = tmp_path / 'input.las'
    path.write_bytes(raw)
    return path


def check(result, declared, expected):
    assert type(result) is Las and result.kind == 'las2/1'
    typed(result.declared, dict(declared or {}), 'declared')
    for field, value in expected.items(): typed(getattr(result, field), value, field)


@pytest.mark.parametrize('name', ACCEPTED)
def test_a_las_file_is_read_whole_with_every_line_and_value(tmp_path, name):
    raw, declared, expected, _ = CASES[name]
    path = written(tmp_path, raw)
    for result in (readers.read(path=path, kind='las2/1', declared=declared), readers.read(Version(path=path, kind='las2/1', declared=declared))):
        check(result, declared, expected)


@pytest.mark.parametrize('name', REFUSALS)
def test_a_las_file_that_cannot_be_read_whole_is_refused_with_its_sentence(tmp_path, name):
    raw, declared, expected, _ = CASES[name]
    with pytest.raises(ReadRefused) as caught: readers.read(path=written(tmp_path, raw), kind='las2/1', declared=declared)
    error = caught.value
    assert (str(error), error.code, error.field, error.row) == expected


# --- parity (S3-D4): the same bytes through the server's two readers ---

def value(v):
    v = v.item() if hasattr(v, 'item') else v
    if v is None or (isinstance(v, float) and math.isnan(v)): return 'nan'
    if v == 0 and math.copysign(1, v) < 0: return '-0'
    return v


def unit(section_parser, text):
    text = text.strip()
    if text.endswith('.'): text = text.strip('.')
    return section_parser('~P').strip_brackets(text)


def sdk_view(result, section_parser):
    view = {}
    for name, letter in (('version_section', '~V'), ('well', '~W'), ('curves', '~C'), ('parameters', '~P')):
        parser = section_parser(letter)
        view[name] = [(m.upper(), unit(section_parser, u), v if letter == '~C' or m.upper() in ('API', 'UWI') else value(parser.num(v)), d)
                      for m, u, v, d in getattr(result, name)]
    view['other'] = '\n'.join(line.strip() for line in (result.other or ())).rstrip('\n')
    view['data'] = [[value(v) for v in row] for row in result.data]
    return view


def las_view(server):
    view = {}
    for name, section in (('version_section', server.version), ('well', server.well), ('curves', server.curves), ('parameters', server.params)):
        view[name] = [(item.original_mnemonic, item.unit, value(item.value), item.descr) for item in section]
    view['other'] = server.other.rstrip('\n')
    view['data'] = [[value(v) for v in row] for row in server.data.tolist()]
    return view


def outcome(call):
    try: return call(), None
    except Exception as error: return None, error


PARITY = [name for name, case in CASES.items() if case[3] is not None]
POLICY = ('an unstated version', 'a BOM: no version is found', 'VERS 1.3', 'LAS 3 data sections', 'a second ~A', 'a comma delimiter')


@pytest.mark.parametrize('name', PARITY)
def test_the_server_readers_agree_or_read_as_each_case_records(name):
    las_reader = pytest.importorskip('asset_connectors.las_reader')
    las_columns = pytest.importorskip('asset_connectors.las_columns')
    from lasio.reader import SectionParser
    raw, declared, expected, (by_las, by_columns) = CASES[name]
    try: ours = las._parse(raw, declared)
    except ReadRefused as refused: ours = refused
    assert isinstance(ours, ReadRefused) == isinstance(expected, tuple), (name, ours)
    theirs, error = outcome(lambda: las_reader.read_las(raw))
    if isinstance(ours, Las): ours_view = sdk_view(ours, SectionParser)
    if by_las == SAME:
        assert error is None, (name, error)
        assert las_view(theirs) == ours_view
        assert dict(ours.context) == las_reader.las_policy(raw) and ours.version == las_reader.stated_version(raw)
    elif by_las == REFUSED:
        assert theirs is None, (name, 'read_las read it')
        if name in POLICY or name.startswith('D-'): assert str(error) == str(ours)  # the E57 policy's, or the SDK's (D-31), words
        if ours.code == 'not-utf8': assert isinstance(error, UnicodeDecodeError)
    else:
        assert error is None, (name, error)
        assert las_view(theirs)['data'] == by_las
    by_las_error = error
    columns, error = outcome(lambda: las_columns.read_columns(raw, max_rows=LAS_ROWS_MAX, max_values=2 ** 24))
    if by_columns == REFUSED:
        assert columns is None, (name, 'read_columns read it')
        if getattr(ours, 'code', None) == 'not-utf8': assert isinstance(error, UnicodeDecodeError)
        elif by_las == REFUSED: assert (type(error), str(error)) == (type(by_las_error), str(by_las_error)), name  # D-31: one refusal
        return
    assert error is None, (name, error)
    data = [[value(v) for v in row] for row in zip(*[list(c) for c in columns.columns])]
    if by_columns == SAME:
        assert data == ours_view['data'] and [c.original_mnemonic for c in columns.header.curves] == [m.upper() for m, *_ in ours.curves]
    else:
        assert data == by_columns


def test_no_server_reader_disagrees_with_the_sdk():
    """D-31 (S3-D9): the five divergences and the splits converged, so no case records a server reading differently from
    the SDK; the names still say which side each split took (`(read_las)`, `(read_columns)`)."""
    def differs(expected, servers):
        refused = isinstance(expected, tuple)
        return any(s not in (SAME, REFUSED) or (s == SAME) == refused for s in servers)
    differing = [name for name in PARITY if differs(CASES[name][2], CASES[name][3])]
    assert differing == []


# --- the real file (T-R4) ---

def test_the_bundled_hon_gt_01_excerpt_is_read_whole_and_in_parity():
    path = Path(ophiolite.__file__).resolve().parent / 'contracts/scientific/v1/fixtures/hon-gt-01-gamma-ray-excerpt.las'
    result = readers.read(path=path, kind='las2/1')
    assert (dict(result.context), result.null, len(result.well)) == (SPACE, '-999.0000', 36)
    assert [(m, u) for m, u, _, _ in result.curves] == [('DEPTH', 'M'), ('GR', 'gAPI')]
    assert (len(result.data), result.data[0], result.data[-1]) == (1551, (2466.0, 57.1748), (2621.0, 133.4287))
    las_reader = pytest.importorskip('asset_connectors.las_reader')
    from lasio.reader import SectionParser
    assert las_view(las_reader.read_las(path.read_bytes())) == sdk_view(result, SectionParser)


# --- limits (T-R5, S3-D10): counted before any value is converted ---

def lines(text, rows):
    return ['~A'] + [text] * rows + ['']


@pytest.mark.parametrize('wrapped', [False, True], ids=['unwrapped', 'wrapped'])
@pytest.mark.parametrize('text,count,rows', [('1', 1, LAS_ROWS_MAX), (' '.join(['1'] * 64), 64, LAS_VALUES // 64)], ids=['rows', 'values'])
def test_a_file_at_the_limits_is_counted_whole(wrapped, text, count, rows):
    subs = las._subs(lines(text, 3), 1, wrapped)
    assert las._counted(lines(text, rows), 1, count, wrapped, subs) == rows * count


def big(text, count, rows, wrapped, tail=b''):
    curves = b''.join(b'C%d. : c\n' % i for i in range(count))
    return (WR if wrapped else V2) + W + b'~Curve\n' + curves + b'~A\n' + (text.encode() + b'\n') * rows + tail


@pytest.mark.parametrize('wrapped', [False, True], ids=['unwrapped', 'wrapped'])
@pytest.mark.parametrize('text,count,rows,sentence', [
    ('1', 1, LAS_ROWS_MAX, 'This LAS file has more than 4,000,000 depth samples; ophiolite.readers reads up to 4,000,000.'),
    (' '.join(['1'] * 64), 64, LAS_VALUES // 64,
     'This LAS file holds more than 16,777,216 values (64 curves); ophiolite.readers reads up to 16,777,216.')], ids=['rows', 'values'])
def test_a_file_past_the_limits_is_refused_before_a_value_is_read(wrapped, text, count, rows, sentence):
    # rows at the bound, then one row of x: the row past it, refused before a value is converted
    with pytest.raises(ReadRefused) as caught: las._parse(big(text, count, rows, wrapped, b' '.join([b'x'] * count) + b'\n'), None)
    assert (str(caught.value), caught.value.code) == (sentence + NO_REPAIR, 'limit')
    las_columns = pytest.importorskip('asset_connectors.las_columns')
    with pytest.raises(las_columns.LASLimitError):
        las_columns.read_columns(big(text, count, rows + 1, wrapped), max_rows=LAS_ROWS_MAX, max_values=LAS_VALUES)


# --- a producer's bytes (T-R7) ---

def test_what_write_curves_writes_is_read_back_whole():
    written_las = write_curves([1500.0, 1500.5, 1501.0], {'GR': ('GAPI', [10.0, None, -0.0])}, depth_unit='m', null_marker=-1234.5,
                               notes=['calc: vsh', 'second note'])
    assert written_las.profile == 'las2/1'
    result = las._parse(written_las.bytes, None)
    typed(result.null, '-1234.5', 'null')
    typed(result.data, ((1500.0, 10.0), (1500.5, None), (1501.0, -0.0)), 'data')
    typed(result.other, (' calc: vsh', ' second note'), 'other')
    typed(result.curves, (('DEPT', 'm', '', 'depth'), ('GR', 'GAPI', '', 'GR')), 'curves')
