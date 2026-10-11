"""E62a: a table read as measurements over time.

A project administrator describes a table as a series once (in the Workspace); everyone who may read the table then
reads the series through their own read of it: `client.source(id).series(name)` for a connected table (your own
selection, at its reviewed revision), `client.read_data(asset, revision).series(name)` for a kept table at that exact
revision. The server answers the view, `ophiolite.series-view/1`: one point per calendar month, each a figure (exact
decimal text, zero included) or a gap (`reported-gap`: the table has the month without a figure; `absent`: no row for
the month). Nothing is copied or stored by reading it.

Figures stay exact. `to_frame()` gives `Decimal` values built from the text; `to_frame(values="float")` gives floats and
records the loss in `frame.attrs`. Totals and averages follow the series rules (`contracts/series/v1/series-rules.json`,
the same file the server and the browser execute): a volume is added up, a rate is averaged weighted by the days of each
month and never added up; a total across gaps is refused unless asked for (and then labelled partial); a result that is
not exact is refused, never rounded.
"""
import calendar
import json
import re
from decimal import Context, Decimal, Inexact, Rounded
from fractions import Fraction
from importlib.resources import files

from .errors import Refused, VerificationFailed

_CONTRACTS = files('ophiolite').joinpath('contracts', 'series', 'v1')
RULES = json.loads(_CONTRACTS.joinpath('series-rules.json').read_text(encoding='utf-8'))
INPUT_DIGITS, CONTEXT_DIGITS = RULES['bounds']['input_digits'], RULES['bounds']['context_digits']
VALUE = re.compile(r'-?(0|[1-9][0-9]*)(\.[0-9]+)?')
MONTH = re.compile(r'(\d{4})-(\d\d)-01')


class SeriesRefused(Refused):
    """A refusal of the series rules: `rule` names it, the message is the rules file's sentence."""
    code = 'series-refused'

    def __init__(self, rule, **values):
        self.rule, self.values = rule, values
        super().__init__(RULES['sentences'][rule].format(**values), details={'rule': rule, **values})


def vectors():
    """The shared literal expectations every implementation executes (`series-vectors.json`)."""
    return json.loads(_CONTRACTS.joinpath('series-vectors.json').read_text(encoding='utf-8'))


# --- exact numbers (the rules' arithmetic, as the server's) ----------------------------------------------------------

def _plain(number):
    text = format(number, 'f')
    return text[1:] if re.fullmatch(r'-0(\.0+)?', text) else text


def _digits(text):
    return sum(c.isdigit() for c in text)


def canonical_value(text):
    """TEXT when it is a canonical decimal (no exponent, no leading zeros, no negative zero, at most 40 digits)."""
    if not isinstance(text, str) or not VALUE.fullmatch(text) or re.fullmatch(r'-0(\.0+)?', text):
        raise SeriesRefused('not-canonical', value=text)
    if _digits(text) > INPUT_DIGITS: raise SeriesRefused('too-large')
    return text


def canonical_float(value):
    """A float's canonical text: its shortest round-trip text, exponent expanded, at least one fractional digit."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float('inf'), float('-inf')):
        raise SeriesRefused('not-canonical', value=repr(value))
    text = _plain(Decimal(repr(float(value))))
    text = text if '.' in text else text + '.0'
    if _digits(text) > INPUT_DIGITS: raise SeriesRefused('too-large')
    return text


def exact_sum(values):
    """The exact sum of canonical texts; refused beyond 80 digits (the context traps rounding, never rounds)."""
    context, total = Context(prec=CONTEXT_DIGITS, traps=[Inexact, Rounded]), Decimal(0)
    try:
        for text in values: total = context.add(total, Decimal(canonical_value(text)))
    except (Inexact, Rounded):
        raise SeriesRefused('not-exact') from None
    return _plain(total) if values else '0'


def month_days(month):
    return calendar.monthrange(int(month[:4]), int(month[5:7]))[1]


def _scale(text):
    return len(text.split('.')[1]) if '.' in text else 0


def exact_fraction(fraction, at_least):
    rest = fraction.denominator
    for prime in (2, 5):
        while rest % prime == 0: rest //= prime
    if rest != 1: raise SeriesRefused('not-finite', fraction='%d/%d' % (fraction.numerator, fraction.denominator))
    places = 0
    while (fraction * 10 ** places).denominator != 1: places += 1
    places = max(places, at_least)
    scaled = fraction.numerator * 10 ** places // fraction.denominator
    magnitude = str(abs(scaled)).rjust(places + 1, '0')
    if len(magnitude.lstrip('0') or '0') > CONTEXT_DIGITS: raise SeriesRefused('not-exact')
    text = ('-' if scaled < 0 else '') + (magnitude[:-places] + '.' + magnitude[-places:] if places else magnitude)
    return _plain(Decimal(text))


def weighted_average(points):
    """[(month 'YYYY-MM', canonical text)] averaged with each month weighted by its days; exact or refused."""
    if not points: raise SeriesRefused('no-figures')
    weights = sum(month_days(m) for m, _ in points)
    total = sum(Fraction(Decimal(canonical_value(v))) * month_days(m) for m, v in points)
    return exact_fraction(total / weights, max(_scale(v) for _, v in points))


def year(kind, number, points):
    """Calendar year NUMBER of POINTS [(month, value or None, state or None)]: a volume's total when all 12 months have a
    figure, else incomplete (no total); a rate's average weighted by days, labelled partial with fewer than 12 figures."""
    figures = [(m[:7], v) for m, v, s in points if s is None and v is not None and m[:4] == str(number)]
    if kind == 'volume':
        if len(figures) != 12:
            return {'incomplete': len(figures), 'sentence': RULES['sentences']['incomplete'].format(year=number, count=len(figures))}
        return {'total': exact_sum([v for _, v in figures])}
    return {'average': weighted_average(figures), 'partial': len(figures) != 12}


def allowed(kind, operation):
    """Raise the rules' refusal unless OPERATION (total, average, compare, year) is allowed for KIND."""
    verdict = RULES['operations'][kind][operation]
    if verdict != 'allowed': raise SeriesRefused(verdict)


def _words(month):
    return '%s %s' % (calendar.month_name[int(month[5:7])], month[:4])


# --- the view -------------------------------------------------------------------------------------------------------

def _checked(answer):
    """The answer of series/view, checked before anything is exposed: its schema, months in order and once each, every
    figure canonical, the counts those points give."""
    try:
        view, revision = answer['view'], answer['revision']
        points = view['points']
        ok = view['schema'] == 'ophiolite.series-view/1' and isinstance(revision, str) and view['kind'] in ('volume', 'rate')
        months = [p['t'] for p in points]
        ok = ok and all(MONTH.fullmatch(t) for t in months) and months == sorted(set(months))
        ok = ok and all(('v' in p) != ('s' in p) and p.get('s') in (None, 'reported-gap', 'absent') for p in points)
        for p in points:
            if 'v' in p: canonical_value(p['v'])
        counts = {'figures': sum('v' in p for p in points), 'reported_gaps': sum(p.get('s') == 'reported-gap' for p in points),
                  'absent': sum(p.get('s') == 'absent' for p in points)}
        ok = ok and counts == view['counts']
    except (KeyError, TypeError, SeriesRefused):
        ok = False
    if not ok: raise VerificationFailed('The series answered outside its documented shape; nothing was read.')
    return view, revision


def read(client, operation, body):
    """series/OPERATION; a refusal the series rules name (a member with no selection of the table, a table that changed
    or whose meaning changed since the series was described) is raised as that rule's SeriesRefused, in its words."""
    from .errors import OphioliteError
    try:
        return client._post('series', operation, body, retry=True)
    except OphioliteError as error:
        if error.code in RULES['sentences'] and '{' not in RULES['sentences'][error.code]:
            refused = SeriesRefused(error.code)
            refused.status, refused.request_id, refused.server_message = error.status, error.request_id, getattr(error, 'server_message', None)
            raise refused from None
        raise


class Series:
    """One declared series as you read it: `name`, `kind` (volume or rate), `unit` (as the source declares it; "Not
    stated" when it does not), `zone`, `revision` (the table revision read), `declaration_version` and `points`."""

    def __init__(self, answer):
        view, self.revision = _checked(answer)
        self.view = view
        self.name, self.kind, self.unit, self.zone = view['name'], view['kind'], view['unit'], view['zone']
        self.table_revision, self.declaration_version = view['table_revision'], view['declaration_version']
        self.column, self.about, self.counts, self.rows = view['column'], view['about'], view['counts'], view['rows']
        self.points = [dict(p) for p in view['points']]

    def __len__(self):
        return len(self.points)

    def __repr__(self):
        return '<Series %r: %d months, %s, %s, revision %s>' % (self.name, len(self.points), self.kind, self.unit, self.revision[:12])

    def _attrs(self):
        return {'name': self.name, 'kind': self.kind, 'unit': self.unit, 'zone': self.zone, 'revision': self.revision,
                'declaration_version': self.declaration_version, 'column': self.column}

    def to_frame(self, values='decimal'):
        """A DataFrame indexed by month start (`DatetimeIndex`): `value` (`Decimal` from the figure's text, or NA for a gap)
        and `state` ("figure", "reported-gap" or "absent"). `values="float"` gives floats, recorded in
        `frame.attrs["transformations"]` as a loss; the figures of the series never change."""
        try: import pandas as pd
        except ImportError: raise Refused('Install ophiolite[pandas] for DataFrames.') from None
        if values not in ('decimal', 'float'): raise Refused('Use values="decimal" or "float".')
        index = pd.DatetimeIndex([p['t'] for p in self.points], name='month')
        exact = [Decimal(p['v']) if 'v' in p else None for p in self.points]
        column = pd.Series([float(v) if v is not None else float('nan') for v in exact], index=index, dtype='float64') if values == 'float' \
            else pd.Series([v if v is not None else pd.NA for v in exact], index=index, dtype='object')
        frame = pd.DataFrame({'value': column, 'state': pd.Series([p.get('s', 'figure') for p in self.points], index=index, dtype='string')})
        frame.attrs.update(self._attrs())
        frame.attrs['transformations'] = ['values as float: lossy; the exact figures are the decimal text of the series'] if values == 'float' else []
        return frame

    def total(self, allow_gaps=False):
        """The exact total of a volume series as a `Decimal`. A rate is refused; so is a total across months without a
        figure unless `allow_gaps=True`, when the answer is labelled partial (`Total.partial`)."""
        allowed(self.kind, 'total')
        missing = [p['t'][:7] for p in self.points if 'v' not in p]
        if missing and not allow_gaps: raise SeriesRefused('gaps', count=len(missing), first=missing[0], last=missing[-1])
        return Total(exact_sum([p['v'] for p in self.points if 'v' in p]), bool(missing), self.unit)

    def average(self):
        """A rate's average over the series, weighted by the days of each month that has a figure (a `Decimal`); a volume
        is refused."""
        allowed(self.kind, 'average')
        return Decimal(weighted_average([(p['t'][:7], p['v']) for p in self.points if 'v' in p]))

    def by(self, period):
        """Calendar years (`period="year"`): {year: text}: a volume's exact total, or "YYYY: incomplete (n of 12 months)"
        when a month has no figure; a rate's weighted average (partial when fewer than 12 figures); a year that cannot be
        given exactly says why."""
        if period != 'year': raise Refused('Series are read by month, and added up or averaged by calendar year: use by("year").')
        allowed(self.kind, 'year')
        answer = {}
        for number in sorted({int(p['t'][:4]) for p in self.points}):
            points = [(p['t'], p.get('v'), p.get('s')) for p in self.points if p['t'].startswith('%04d-' % number)]
            try: got = year(self.kind, number, points)
            except SeriesRefused as refused: answer[number] = str(refused); continue
            answer[number] = got.get('total') or got.get('sentence') or (got['average'] + (' (partial)' if got['partial'] else ''))
        return answer

    def reading(self, month):
        """The readout of one month in words, the figure as given: "March 2017, 0.25778 MillSm3"."""
        found = [p for p in self.points if p['t'][:7] == month[:7]]
        if not found: raise Refused('%s is not a month of this series.' % month)
        p = found[0]
        unit = 'unit not stated' if self.unit == RULES['unit_not_stated'] else self.unit
        return '%s, %s %s' % (_words(p['t']), p['v'], unit) if 'v' in p else \
            '%s, %s' % (_words(p['t']), 'reported without a figure' if p['s'] == 'reported-gap' else 'no row for this month')

    def rows_csv(self):
        """The literal rows: `month,value,state`, one line per month, the figure exactly as given."""
        return 'month,value,state\r\n' + ''.join('%s,%s,%s\r\n' % (p['t'], p.get('v', ''), p.get('s', 'figure')) for p in self.points)


class Total(Decimal):
    """An exact total; `partial` when months without a figure were left out (asked for with allow_gaps=True)."""

    def __new__(cls, text, partial, unit):
        made = super().__new__(cls, text)
        made.partial, made.unit = partial, unit
        return made

    def __repr__(self):
        return "Total('%s'%s)" % (self, ', partial' if self.partial else '')


def compare(*series):
    """The series side by side by month (a DataFrame, one column of `Decimal` per series), when they may be read
    together: the same kind, units both stated and equal, the same time zone. Otherwise the rules' sentence is raised."""
    if len(series) < 2: raise Refused('Compare two or more series.')
    first = series[0]
    for other in series[1:]:
        allowed(other.kind, 'compare')
        if other.kind != first.kind: raise Refused('A volume and a rate are not the same thing, so they are not compared here.')
        stated = [s.unit != RULES['unit_not_stated'] for s in (first, other)]
        if any(stated) and not all(stated): raise SeriesRefused('unit-not-stated')
        if all(stated) and first.unit != other.unit: raise SeriesRefused('units-differ', first=first.unit, second=other.unit)
        if first.zone != other.zone: raise SeriesRefused('zones')
    import pandas as pd
    frame = pd.concat([s.to_frame()['value'].rename(s.name) for s in series], axis=1)
    frame.attrs.update({'kind': first.kind, 'unit': first.unit, 'zone': first.zone, 'revisions': [s.revision for s in series]})
    return frame
