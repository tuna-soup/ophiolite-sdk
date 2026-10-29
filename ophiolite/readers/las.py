"""E128 s3: las2/1 read whole.

What the platform reads (`asset_connectors.las_reader.read_las` and `las_columns.read_columns`, the E57 `las_policy` set)
is read here, with every header line kept as written: LAS 1.2, 2.0 and 3.0 in the LAS 2 layout (~V, ~W, ~C, ~P, ~O and
one last ~A), delimited by spaces or tabs, wrapped rows read by the curve count. The policy is the server's, with its
sentences. The header-line forms and the data substitutions are lasio's (evidence 4 of the s3 strategy), so a value is
split where the server splits it. Where lasio would drop content or invent a value (a custom, lowercase or repeated
section, a default or ambiguous NULL, text before the first section), the file is refused and the sentence names what
was found (S3-D9, D-1 to D-5; D-31). Standard library only.
"""
import math
import re

from .results import Las
from .tables import _refuse

VERSIONS = {1.2: '1.2', 2.0: '2.0', 3.0: '3.0'}
DELIMITERS = {'': 'space', 'SPACE': 'space', 'TAB': 'tab'}
LAS2_SECTIONS = 'VWCPOA'
HEADERS = {'V': 'version_section', 'W': 'well', 'C': 'curves', 'P': 'parameters'}
EXEMPT_12 = ('STRT', 'STOP', 'STEP', 'NULL')  # value:descr in a LAS 1.2 ~W; every other line is descr:value
LAS_ROWS_MAX, LAS_VALUES = 4_000_000, 2 ** 24  # the most any deployment reads (project_gateway/limits.py), S3-D10
WRAPPED_CURVES = 64
COMMA_DECIMAL = re.compile(r'(\d),(\d)')
# lasio's default read substitutions (lasio.defaults.READ_SUBS, MIT; also las_columns.SUBS), in order: the comma decimal
# mark, run-on '-' (dropped when every sampled line holds a '-') and run-on '.' (two NaN values).
RUN_ON_HYPHEN = (re.compile(r'(\d)-(\d)'), r'\1 -\2')
SUBS = [(COMMA_DECIMAL, r'\1.\2'), RUN_ON_HYPHEN, (re.compile(r'-?\d*\.\d*\.\d*|NaN[\.-]\d+'), ' NaN NaN ')]
UTF8 = 'Unsupported LAS: file is not UTF-8. Export a UTF-8 LAS 2.0 copy; no repair was applied.'
LAYOUT = ('Unsupported LAS: this file uses LAS 3.0 data sections (such as ~Log_Data with its definitions), which are not '
          'read; LAS files with one ~ASCII data section are. No conversion was applied.')

# The header-line forms of lasio 0.32 (lasio.reader.configure_metadata_patterns; MIT License, Copyright (c) 2013-2020
# Kent Inverarity and contributors; see THIRD_PARTY.md): name.unit value : description, with its special cases.
NAME, NAME_DOTS, NAME_NO_PERIOD = r'\.?(?P<name>[^.]*)\.', r'\.?(?P<name>[^.].*[.])\.', r'(?P<name>[^:]*):'
UNIT = r'(?P<unit>([0-9]+\s)?[^\s]*)'
VALUE, VALUE_TO_END, VALUE_NO_COLON = r'(?P<value>.*):', r'(?P<value>.*)', r'(?P<value>[^:]*)'
VALUE_TIME = r'(?P<value>.*?)(?:(?<!( [0-2][0-3]| hh| HH)):(?!([0-5][0-9]|mm|MM)))'
DESCRIPTION = r'(?P<descr>.*)'


def _server(sentence, code, field=None):
    """A refusal in the server's own words (the E57 policy, the upload's UTF-8 rule): no suffix is added."""
    from . import ReadRefused
    raise ReadRefused(sentence, code=code, field=field)


def _header_value(lines, mnemonic):
    for line in lines:
        match = re.match(r'\s*%s\s*\.[^\s:]*\s*([^:]*)(:|$)' % mnemonic, line, re.I)  # the colon is optional
        if match: return match.group(1).strip()
    return None


def _version_lines(text):
    match = re.search(r'(?ims)^[ \t]*~V[^\r\n]*[\r\n]+(.*?)(?=^[ \t]*~)', text)
    return match.group(1).splitlines() if match else []


def _policy(text):
    """las_reader.las_policy and stated_version: ({version, layout, delimiter}, the VERS text as written). VERS is read
    by float(), as the server reads it (S3-D8)."""
    sections = [m.group(1) for m in re.finditer(r'(?m)^[ \t]*~([^\r\n]*)', text)]
    if not sections: _refuse('This file has no ~ section; it is not read as LAS.', 'not-las')
    version_lines = _version_lines(text)
    stated = _header_value(version_lines, 'VERS')
    try: version = VERSIONS.get(float(stated)) if stated is not None else None
    except ValueError: version = None
    if version is None:
        _server('Unsupported LAS: version %s is not read; LAS 1.2, 2.0 and 3.0 files are. No conversion was applied.'
                % (stated or 'not stated'), 'version', 'VERS')
    names = [s.strip() for s in sections]
    if version == '3.0' and any(not n or n[0].upper() not in LAS2_SECTIONS or '|' in n or '_' in n.split()[0] for n in names) \
            or sum(n[:1].upper() == 'A' for n in names) != 1 or names[-1][:1].upper() != 'A':
        _server(LAYOUT, 'layout')
    dlm = (_header_value(version_lines, 'DLM') or '').upper()
    if dlm not in DELIMITERS:
        _server('Unsupported LAS: the data are delimited by %s; LAS files delimited by spaces or tabs are read. No '
                'conversion was applied.' % dlm, 'delimiter', 'DLM')
    return {'version': version, 'layout': 'las2', 'delimiter': DELIMITERS[dlm]}, stated


def _split(line, section, number):
    """(mnemonic, unit, value, description) of one stripped header line, split where lasio splits it; unit as written."""
    name, unit, value, descr = NAME, UNIT, VALUE, DESCRIPTION
    colon = line.find(':')
    if colon >= 0 and '.' not in line[:colon]: name, value, descr, unit = NAME_NO_PERIOD, VALUE_TO_END, '', ''
    if colon < 0:
        value, descr = VALUE_NO_COLON, ''
        if '..' in line and section == 'C': name = NAME_DOTS
    elif re.search(r'[^ ]\.\.', line) and section == 'C' and line.find('..') < line.rfind(':'): name = NAME_DOTS
    patterns = ([name + unit + (VALUE_TIME if value == VALUE else value) + descr] if section == 'P' else []) + [name + unit + value + descr]
    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            parts = match.groupdict()
            return tuple(parts.get(key, '').strip() for key in ('name', 'unit', 'value', 'descr'))
    _refuse(f'Line {number} of the ~{section} section is not a LAS header line (MNEM.UNIT VALUE : DESCRIPTION).',
            'header-line', '~' + section, number)


def _number(text):
    """A finite float after lasio's comma decimal mark, or None."""
    try: value = float(COMMA_DECIMAL.sub(r'\1.\2', text))
    except ValueError: return None
    return value if math.isfinite(value) else None


def _sections(lines):
    """{letter: (first line index, end index)} for the six LAS 2 sections, refusing any other title, a repeat and a
    non-comment line before the first title (S3-D3 step 5)."""
    titles = [(index, line.strip()) for index, line in enumerate(lines) if line.lstrip(' \t').startswith('~')]
    for index in range(titles[0][0]):
        text = lines[index].strip()
        if text and not text.startswith('#'):
            _refuse(f'Line {index + 1} comes before the first ~ section and is not a comment: {text}', 'section', None, index + 1)
    found, at = {}, {}
    for position, (index, title) in enumerate(titles):
        letter = title[1:2]
        if letter not in LAS2_SECTIONS or (letter in 'CP' and '_' in title):
            _refuse(f'Section {title} on line {index + 1} is not a LAS 2 section; LAS files with the ~V, ~W, ~C, ~P, ~O '
                    'and ~A sections are read.', 'section', title, index + 1)
        if letter in found:
            _refuse(f'Section {title} on line {index + 1} repeats the ~{letter} section of line {at[letter]}; neither was '
                    'chosen.', 'repeated-section', title, index + 1)
        end = titles[position + 1][0] if position + 1 < len(titles) else len(lines)
        found[letter], at[letter] = (index + 1, end), index + 1
    for letter in 'WC':
        if letter not in found: _refuse(f'The file has no ~{letter} section.', 'missing-section', '~' + letter)
    return found


def _items(lines, section, span, version):
    start, end = span
    items = []
    for index in range(start, end):
        line = lines[index].strip()
        if not line or line.startswith('#'): continue
        mnemonic, unit, value, descr = _split(line, section, index + 1)
        if section == 'W' and version == 1.2 and mnemonic.upper() not in EXEMPT_12: value, descr = descr, value
        items.append((mnemonic, unit, value, descr))
    return tuple(items)


def _values(items, mnemonic):
    """The values of the lines named `mnemonic` (lasio upper-cases mnemonics; a repeated one is renamed `NULL:1`,
    `NULL:2`, so lasio then finds none of them)."""
    return [item[2] for item in items if item[0].upper() == mnemonic]


def _one(items, mnemonic, section):
    found = _values(items, mnemonic)
    if len(found) > 1:
        _refuse(f'The ~{section} section states {mnemonic} {len(found)} times ({", ".join(found)}); none was chosen.',
                'repeated-key', mnemonic)
    if not found: _refuse(f'The ~{section} section has no {mnemonic} line.', 'missing-key', mnemonic)
    return found[0]


def _limit(values, count):
    rows = values // count
    if rows > LAS_ROWS_MAX:
        _refuse(f'This LAS file has more than {LAS_ROWS_MAX:,} depth samples; ophiolite.readers reads up to {LAS_ROWS_MAX:,}.', 'limit')
    if rows * count > LAS_VALUES:
        _refuse(f'This LAS file holds more than {LAS_VALUES:,} values ({count} curves); ophiolite.readers reads up to {LAS_VALUES:,}.', 'limit')


def _inspect(lines, start, subs):
    """lasio's inspect_data_section over the first data lines (at most 21, comments aside): (the one value count they
    all hold, or None; whether every one holds a '-')."""
    counts, hyphens = [], 0
    end = len(lines) - (lines[-1] == '')  # the text after the last line break is not a line to lasio
    for position, index in enumerate(range(start, end)):
        line = lines[index].strip()
        hyphens += '-' in line
        if line.startswith('#'): continue
        for pattern, sub in subs: line = pattern.sub(sub, line)
        counts.append(len(line.split()))
        if position >= 20: break
    return (counts[0] if counts and len(set(counts)) == 1 else None), hyphens == len(counts)


def _subs(lines, start, wrapped):
    """The substitutions read_las applies: none to a wrapped file; lasio's three, without run-on '-' when every
    sampled line holds a '-' (S3-D6)."""
    if wrapped: return []
    return [s for s in SUBS if s is not RUN_ON_HYPHEN] if _inspect(lines, start, SUBS)[1] else SUBS


def _tokens(lines, start, wrapped, subs):
    """(line number, tokens) of each data line: blank and # lines skipped; an unwrapped line takes the substitutions
    and loses chr(26), as read_las does; a wrapped line is split as read_las splits it."""
    for index in range(start, len(lines)):
        line = lines[index].strip()
        if not line or line.startswith('#'): continue
        if not wrapped:
            for pattern, sub in subs: line = pattern.sub(sub, line)
            line = line.replace(chr(26), '')
            if not line: continue
        yield index + 1, line.split()


def _counted(lines, start, count, wrapped, subs):
    """The number of data values, refused past the limits before any value is converted (S3-D10). Unwrapped, a file
    whose data lines all hold one count other than the curve count is refused: lasio then reads that many columns,
    inventing or emptying curves (S3-D5)."""
    values, counts = 0, set()
    for _, tokens in _tokens(lines, start, wrapped, subs):
        values += len(tokens)
        counts.add(len(tokens))
        _limit(values, count)
    sampled = None if wrapped else _inspect(lines, start, subs)[0]
    if not wrapped and ((len(counts) == 1 and counts != {count}) or sampled not in (None, count)):
        n = sampled if sampled not in (None, count) else next(iter(counts))
        _refuse(f'Every data line holds {n} values; the ~C section declares {count} curves.', 'row-count', '~A')
    return values


def _data(lines, start, count, wrapped, null):
    subs = _subs(lines, start, wrapped)
    _counted(lines, start, count, wrapped, subs)
    values = []
    for number, tokens in _tokens(lines, start, wrapped, subs):
        for token in tokens:
            try: value = float(token)
            except ValueError: _refuse(f'Line {number} of the ~A section has a value that is not a number: {token}.', 'not-a-number', '~A', number)
            values.append(None if value == null else value)
    if wrapped and not values: _refuse('The wrapped ~A section holds no values.', 'row-count', '~A')
    if len(values) % count:
        _refuse(f'The ~A section has {len(values)} values, which is not a whole number of rows of {count} curves.', 'row-count', '~A')
    return tuple(tuple(values[i:i + count]) for i in range(0, len(values), count))


def _parse(raw, declared):
    """The Las of `raw` (bytes) read whole, with `declared` as supplied; ReadRefused when it cannot be."""
    declared = declared or {}  # as read_typed: a falsy declaration is none
    if not isinstance(declared, dict): _refuse('Declared context must be an object.')
    if not raw: _refuse('The file is empty.', 'empty')
    try: text = raw.decode('utf-8')  # no BOM is stripped: the servers then find no version (S3 evidence 5, B1)
    except UnicodeDecodeError: _server(UTF8, 'not-utf8')
    context, stated = _policy(text)
    if '\x00' in text: _refuse('The file contains binary data.', 'binary')
    lines = [line[:-1] if line.endswith('\r') else line for line in text.split('\n')]
    found = _sections(lines)
    version_items = _items(lines, 'V', found['V'], None)
    version = float(context['version'])
    # lasio reads ~W in the 2.0 order when it precedes ~V, or when VERS is repeated (renamed VERS:1, VERS:2; S3-D9)
    if found['W'][0] < found['V'][0] or len(_values(version_items, 'VERS')) > 1: version = 2.0
    header = {HEADERS[letter]: _items(lines, letter, found[letter], version) if letter != 'V' else version_items
              for letter in 'VWCP' if letter in found}
    wrap = _one(version_items, 'WRAP', 'V')  # twice: both servers fail on the renamed key (S3-D9)
    dlm = _values(version_items, 'DLM')
    if len(dlm) == 1 and dlm[0] not in ('SPACE', 'TAB'):  # lasio looks the one value up as written; twice, it is skipped
        _refuse(f'DLM {dlm[0]} is not written SPACE or TAB.', 'delimiter', 'DLM')
    null = _one(header['well'], 'NULL', 'W')  # missing or twice: refused, as the upload refuses (S3-D9 D-4)
    count = len(header['curves'])
    wrapped = wrap.upper() == 'YES'
    if wrapped:  # read_las compares with float(NULL) over every column
        try: number = float(COMMA_DECIMAL.sub(r'\1.\2', null))
        except ValueError: _refuse(f'NULL {null} is not a number.', 'null', 'NULL')
    else: number = _number(null)  # lasio nulls with a finite number only; otherwise nothing is null
    if not count: _refuse('The ~C section declares no curves.', 'no-curves', '~C')
    if wrapped and count > WRAPPED_CURVES: _refuse(f'A wrapped LAS file has 1 to {WRAPPED_CURVES} curves; this one has {count}.', 'limit', '~C')
    other = tuple(lines[slice(*found['O'])]) if 'O' in found else None
    data = _data(lines, found['A'][0], count, wrapped, number)
    return Las(kind='las2/1', declared=dict(declared), context=context, version=stated, version_section=version_items,
               well=header['well'], curves=header['curves'], parameters=header.get('parameters', ()), other=other,
               null=null, data=data)
