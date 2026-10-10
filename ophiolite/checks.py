"""E96: checks against a reference. Publish the check records the conformance scientific mode produces, list the checks
of a result or of an implementation, and compare a result with a file you trust (the comparison is kept for you only).

`ophiolite checks publish | list | compare | publishers` prints these in words; a refusal's sentence never names a
field path, which is in `--json` (`error.field`) instead. The sentences are a closed copy keyed by the server's field."""
import base64
import datetime
import hashlib
import json
from pathlib import Path

from .errors import OphioliteError, PermissionRefused, Refused

PERMISSION = 'Publishing checks needs permission. Ask a project administrator.'
GRANTING = 'Only a project administrator can change who may publish checks.'
SAVED_HERE = 'Saved on this result only.'
NOT_REPEATED = 'Ophiolite did not repeat this check.'
REPEATED = 'Ophiolite repeated this and got slightly different numbers.'
ONLY_THIS = 'This shows these numbers on this data only.'
NOT_RECORDED = 'Not recorded'
PUBLISH_REFUSED = {
    'permission': PERMISSION,
    'schema': 'Not published: the check does not have the shape of a check record.',
    'publisher': 'Not published: a check is published by the credential that sends it.',
    'tolerance': 'Not published: the allowed difference is not a number of at least 0 in the compared unit.',
    'size': 'Not published: a file of the check is larger than 2 MiB.',
    'fixture.digest': 'Not published: the fixture file does not match the recorded file.',
    'reference.digest': 'Not published: the reference file does not match the recorded file.',
    'output.digest': 'Not published: the output file is not what this release produces from the fixture.',
    'rights': 'Not published: the reference does not say under which licence and from which source it is used.',
    'release.digest': 'Not published: the check was made for release %s, not the release this server runs.',
    'implementation.script_sha256': 'Not published: the check names other code than this server runs for the calculation.',
    'outcome': 'Not published: the recorded outcome is not what the server\'s comparison gives.',
    'timeout': 'Not published: the server did not finish the check in time. Nothing was saved.',
    'capacity': 'Not published: the server is busy. Try again.',
    'request': 'Not published: this command id was used for another request.',
    'interpretation': 'Not published: the grid comes with declarations no reader reads.',
}
COMPARE_REFUSED = {
    'limit': 'You have saved 20 comparisons on this result. Ask a project administrator to review them.',
    'size': 'Not compared: the file is larger than 2 MB.',
    'tolerance': 'Not compared: the allowed difference is not a number of at least 0 in the compared unit.',
    'schema': 'Not compared: a grid needs its coordinate system, units and datum confirmed (--interpretation).',
    'interpretation': 'Not compared: the confirmed declarations are not ones a reader reads.',
    'timeout': 'Not compared: the server did not finish in time. Nothing was saved.',
    'capacity': 'Not compared: the server is busy. Try again.',
    'request': 'Not compared: this command id was used for another comparison.',
}
REFERENCE = {'independent-computation': 'an independent calculation', 'reference-file': 'a reference file', 'external-package': 'an external package'}
OUTCOME = {'passed': 'passed', 'differed': 'differed', 'not_compared': 'not compared'}
REASON = {  # a check's reference, as the story says it
    'axis_mismatch': 'The depth samples differ; nothing is resampled.',
    'unit_mismatch': 'The units differ; nothing is converted.',
    'context_mismatch': 'The recorded conditions of the values differ.',
    'shape_mismatch': 'The grids have different sizes.',
    'another_kind': 'The reference is a file of another kind.',
    'declarations_missing': 'The reference does not say how to read its values.',
    'declarations_incompatible': 'The reference is declared differently; nothing is converted.',
    'unreadable': 'The reference could not be read.',
    'too_large': 'The reference is larger than 2 MB.',
    'empty': 'The reference has no values.',
    'no_such_curve': 'The reference has no such curve.',
}
FILE_REASON = {  # your file, as `checks compare` says it
    'axis_mismatch': 'Not compared: the depth samples differ; nothing is resampled.',
    'unit_mismatch': 'Not compared: the file gives the curve in another unit than the result; nothing is converted.',
    'context_mismatch': 'Not compared: the recorded conditions of the values differ.',
    'shape_mismatch': 'Not compared: the grids have different sizes.',
    'declarations_missing': 'Not compared: the file does not say how to read its values. Confirm the coordinate system, units and datum.',
    'declarations_incompatible': 'Not compared: the file is confirmed differently from this result; nothing is converted.',
    'too_large': 'Not compared: the file is larger than 2 MB.',
    'empty': 'Not compared: the file has no values.',
}
UNIT_WORDS = {'m': 'metres', 'ft': 'feet', 'ms': 'milliseconds', 's': 'seconds'}


def field(error):
    """The field a check refusal names (the server's `field`), or None."""
    return (getattr(error, 'details', None) or {}).get('field')


def in_words(error, sentences, number=None):
    """A check refusal in this command's sentence; the category, code, field and request id stay on the error."""
    if not isinstance(error, OphioliteError): return error
    name = field(error)
    if name not in sentences: return error  # a refused credential (no field) keeps its own sign-in sentence
    text = sentences[name] % (number or 'another release') if '%s' in sentences[name] else sentences[name]
    return type(error)(text, status=error.status, code=error.code, details=error.details, remedy=error.remedy, docs=error.docs,
                       request_id=error.request_id, server_message=error.server_message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def command_for(prefix, body):
    """The same request gets the same command id, so sending it again answers the record already saved."""
    return prefix + hashlib.sha256(canonical(body)).hexdigest()[:64 - len(prefix)]


def b64(raw):
    return base64.b64encode(raw).decode('ascii')


def folders(path):
    """The check directories under `path`: `path` itself when it holds a check.json, else each child that does."""
    path = Path(path)
    if (path / 'check.json').is_file(): return [path]
    found = sorted(p for p in path.iterdir() if (p / 'check.json').is_file()) if path.is_dir() else []
    if not found: raise Refused('No check.json in %s or in a folder inside it.' % path)
    return found


def one_file(folder, stem):
    found = sorted(folder.glob(stem + '.*'))
    if len(found) != 1: raise Refused('%s needs exactly one %s file.' % (folder.name, stem))
    return found[0].read_bytes()


def publish_body(folder):
    """The publish request for one check directory: the record, its three files and the executable request."""
    folder = Path(folder)
    try:
        record = json.loads((folder / 'check.json').read_text())
        request = json.loads((folder / 'request.json').read_text()) if (folder / 'request.json').is_file() else None
        interpretation = json.loads((folder / 'interpretation.json').read_text()) if (folder / 'interpretation.json').is_file() else None
    except ValueError: raise Refused('%s: check.json, request.json or interpretation.json is not JSON.' % folder.name) from None
    body = {'record': record, 'files': {'fixture': b64(one_file(folder, 'fixture')), 'reference': b64(one_file(folder, 'reference')),
                                        'output': b64((folder / 'output.json').read_bytes())}}
    if request is not None: body['request'] = request
    if interpretation is not None: body['interpretation'] = interpretation
    return {'command_id': command_for('check-', body), **body}


def las_curves(raw):
    """[(mnemonic, unit)] of a LAS file's curves after the depth axis; [] when it is not a LAS file."""
    try: text = raw.decode('ascii', errors='replace')
    except Exception: return []
    found, section = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('~'): section = stripped[1:2].upper(); continue
        if section == 'C' and stripped and not stripped.startswith('#') and '.' in stripped:
            name, rest = stripped.split('.', 1)
            rest = rest.split(':', 1)[0]
            found.append((name.strip(), '' if rest[:1].isspace() else rest.split()[0] if rest.split() else ''))
    return found[1:]


class CheckClient:
    """Mixed into `Client` (uses its `_post`)."""

    def check_publish(self, folder):
        """Publish one check directory (check.json, fixture.*, reference.*, output.json, request.json); the stored record.
        The server repeats the calculation when it runs this implementation and release ("checked by the server");
        otherwise the record is stored as reported. A refusal names its field in `error.details['field']`."""
        body = publish_body(folder)
        number = (body['record'].get('subject') or {}).get('release_number')
        try: return self._post('checks', 'publish', body, retry=True)
        except OphioliteError as error: raise in_words(error, PUBLISH_REFUSED, number) from None

    def check_list(self, *, asset=None, revision=None, implementation=None, version=None):
        """The checks of an exact result version (with your own comparisons) or of an implementation and version:
        {records, groups}; each group has its latest record, the earlier ones and whether they disagree."""
        if (asset is None) == (implementation is None): raise Refused('Name a result (asset and revision) or an implementation.')
        subject = ({'kind': 'result', 'asset_id': asset, 'revision': revision} if asset is not None
                   else {'kind': 'implementation', 'id': implementation, 'version': version})
        return self._post('checks', 'list', {'subject': subject}, retry=True)

    def check_compare(self, asset, revision, file, *, curve=None, tolerance=None, interpretation=None, file_name=None, command_id=None):
        """Compare an exact result version with a file you trust; the comparison is saved on this result for you (and
        administrators who read it), never as a check of the method. `tolerance` is a number in the compared unit, a
        dict ({kind: absolute, value, unit} or {kind: relative, value}) or None for exactly equal."""
        raw = Path(file).read_bytes() if isinstance(file, (str, Path)) else bytes(file)
        name = file_name or (Path(file).name if isinstance(file, (str, Path)) else None)
        if isinstance(tolerance, (int, float)) and not isinstance(tolerance, bool):
            unit = dict(las_curves(raw)).get(curve) if curve else None
            if unit is None and interpretation: unit = interpretation.get('value_unit')
            if not unit: raise Refused('Give the unit of the allowed difference (the file does not say it).')
            tolerance = {'kind': 'absolute', 'value': tolerance, 'unit': unit}
        body = {'asset_id': asset, 'revision': revision, 'files': {'file': b64(raw)}, **({'curve': curve} if curve else {}),
                **({'file_name': name[:200]} if name else {}), **({'tolerance': tolerance} if tolerance is not None else {}),
                **({'interpretation': interpretation} if interpretation is not None else {})}
        body = {'command_id': command_id or command_for('compare-', body), **body}
        try: return self._post('checks', 'compare', body, retry=True)
        except OphioliteError as error: raise in_words(error, COMPARE_REFUSED) from None

    def check_publishers(self, action='list', principal=None, *, kind='person'):
        """Who may publish checks besides the project's administrators: {publishers: [{principal, kind, granted_by, at}]}.
        `grant` and `revoke` (administrators only) name a person or a workload client id."""
        body = {'action': action, **({'principal': principal, 'kind': kind} if action != 'list' else {})}
        try: return self._post('checks', 'publishers', body)
        except PermissionRefused as error:
            if error.stage: raise  # a refused credential keeps its own sign-in sentence
            raise PermissionRefused(GRANTING, status=error.status, code=error.code, details=error.details, request_id=error.request_id) from None


# --- words -------------------------------------------------------------------------------------------------------------

def plain(number):
    number = float('%.10g' % number)  # 30.0004 - 30.0 reads 0.0004
    text = format(number, 'f').rstrip('0').rstrip('.') if number else '0'
    if float(text) != number: text = format(number, '.17f').rstrip('0').rstrip('.')
    return text


def day(at):
    t = datetime.datetime.fromtimestamp(at, datetime.timezone.utc)
    return '%d %s %d' % (t.day, t.strftime('%B'), t.year)


def moment(at):
    t = datetime.datetime.fromtimestamp(at, datetime.timezone.utc)
    return '%d %s %s' % (t.day, t.strftime('%B'), t.strftime('%H:%M'))


def unit_of(limit, fallback=None):
    found = limit.get('unit') if limit and limit.get('kind') == 'absolute' else fallback
    return (' ' + UNIT_WORDS.get(found, found)) if found else ''


def bound(limit):
    if limit is None or limit['value'] == 0: return 'Exactly equal'
    if limit['kind'] == 'relative': return 'Within %s %%' % plain(limit['value'] * 100)
    return 'Within %s%s' % (plain(limit['value']), unit_of(limit))


def places(record):
    return 'cells' if record.get('rules_id') == 'grid-compare/1' else 'depths'


def outcome_lines(record):
    """The sentences after a record's first: the bound, the largest difference, or the reason it was not compared."""
    limit = record.get('tolerance')
    if record['outcome'] == 'passed': return [bound(limit) + '.']
    if record['outcome'] == 'not_compared': return [REASON.get(record.get('reason'), 'The values could not be compared.')]
    d = record.get('differences') or {}
    if d.get('largest') is None: first = 'Values are missing at %d of %d %s.' % (d.get('count', 0), d.get('total', 0), places(record))
    else: first = 'Largest difference %s%s, at %d of %d %s.' % (plain(d['largest']), unit_of(limit), d.get('count', 0), d.get('total', 0), places(record))
    text = bound(limit)
    return [first, 'Allowed: ' + text[0].lower() + text[1:] + '.']


def record_lines(record, names=None):
    """A witnessed, reported or personal record in words: never "Checked against" for one the server did not repeat."""
    fixture = (record.get('fixture') or {}).get('display_name') or NOT_RECORDED
    if record['witness'] == 'personal':
        return ['Compared with a file on %s: %s.' % (day(record['at']), OUTCOME[record['outcome']])] + outcome_lines(record) + [SAVED_HERE]
    if record['witness'] == 'claimed':
        who = (names or {}).get(record['recorded_by']['id']) or 'a project member'
        return ['Reported check by %s: %s on %s.' % (who, OUTCOME[record['outcome']], fixture),
                REPEATED if record.get('server_output_digest') else NOT_REPEATED]
    reference = record['reference']
    first = 'Checked against %s (version %s) on %s' % (REFERENCE.get(reference['kind'], 'a reference'), reference['version'], fixture)
    if record['outcome'] == 'not_compared': return [first + ': not compared.'] + outcome_lines(record)
    lines = [first + ', %s: %s.' % (day(record['at']), OUTCOME[record['outcome']])] + outcome_lines(record)
    return lines + [ONLY_THIS] if record['outcome'] == 'passed' else lines


def list_lines(answer, names=None, earlier=False):
    """`checks list` as lines: each group's latest record, a disagreement, earlier records (with --earlier) and your
    comparisons with files."""
    out = []
    for group in answer['groups']:
        rows = [group['latest']] + list(group['earlier'])
        if group['disagreement']:
            ordered = sorted(rows, key=lambda r: r['at'])
            out.append('Checks disagree: ' + ', '.join('%s on %s' % (OUTCOME[r['outcome']], moment(r['at'])) for r in ordered) + '.')
        out += record_lines(group['latest'], names)
        if earlier and group['earlier']:
            out.append('Earlier checks:')
            for r in group['earlier']: out += ['  ' + line for line in record_lines(r, names)]
    personal = [r for r in answer['records'] if r['witness'] == 'personal']
    if personal:
        out.append('Compared with files:')
        for r in sorted(personal, key=lambda r: -r['at']): out += ['  ' + line for line in record_lines(r, names)]
    return out or ['Not checked against a reference.']


def compare_lines(found, curve=None, method=None, unit=None):
    """`checks compare` as lines: the outcome against your file, saved on this result only, never a check of the method."""
    limit = found.get('tolerance')
    if found['outcome'] == 'passed': first = ['The values match exactly.' if limit is None or limit['value'] == 0 else bound(limit) + '.']
    elif found['outcome'] == 'differed':
        d = found.get('differences') or {}
        if d.get('largest') is None: text = 'Values are missing at %d of %d %s' % (d.get('count', 0), d.get('total', 0), places(found))
        else: text = 'Differs by at most %s%s, at %d of %d %s' % (plain(d['largest']), unit_of(limit, unit), d.get('count', 0), d.get('total', 0), places(found))
        where = d.get('changed_range')
        if where and all(isinstance(v, (int, float)) for v in where) and where[0] != where[1]: text += ' (between %s and %s)' % (plain(where[0]), plain(where[1]))
        first = [text + '.']
    else:
        reason = found.get('reason')
        if found.get('sentence'): first = [found['sentence']]
        elif reason == 'unreadable': first = ['Not compared: the file could not be read as %s.' % ('a grid' if places(found) == 'cells' else 'a well log')]
        elif reason == 'no_such_curve': first = ['Not compared: the file has no curve called %s.' % (curve or 'that name')]
        else: first = [FILE_REASON.get(reason, 'Not compared: the values could not be compared.')]
        if found.get('fields'): first.append('Declarations concerned: %s.' % ', '.join(found['fields']))
    return first + [SAVED_HERE, 'This is not a check of %s.' % (method or 'the method that made this result')]


def published_line(stored):
    """"Published 2 checks for Ophiolite 2026.10.60: 2 checked by the server." for the records one publish stored."""
    numbers = sorted({r['subject'].get('release_number') for r in stored if r['subject'].get('release_number')})
    server = sum(r['witness'] == 'server' for r in stored)
    parts = ['%d checked by the server' % server] if server else []
    if len(stored) - server: parts.append('%d reported, not repeated by the server' % (len(stored) - server))
    return 'Published %d check%s%s: %s.' % (len(stored), '' if len(stored) == 1 else 's',
                                            ' for Ophiolite ' + ', '.join(numbers) if numbers else '', ', '.join(parts))


def publisher_line(entry, names=None, verb='can'):
    who = (names or {}).get(entry['principal']) or entry['principal']
    return '%s %s publish checks for this project.' % (who, verb)
