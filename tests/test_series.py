"""E62a C4: a declared series read in Python and on the command line.

The Field A and Field B answers are the views the Connectors' `series_view.build` gives for two synthetic tables
(`tests/fixtures/series/record.py`; no real field's figures). The gateway serves `series/view` with that code. The
expected values are literals summed by hand from the synthetic CSV text. The rules and vectors are the contract snapshot's (`ophiolite/contracts/series/v1/`), executed
here through the SDK's own arithmetic, as the Platform, the Connectors and the browser execute them.
"""
import copy
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from ophiolite import series as S
from ophiolite.errors import Refused, VerificationFailed
from test_sources import client, selection

HERE = Path(__file__).parent / 'fixtures' / 'series'
FIELD_A = json.loads((HERE / 'field-a-view.json').read_text())
FIELD_B = json.loads((HERE / 'field-b-view.json').read_text())
VECTORS = S.vectors()
CONNECT_FIRST = 'Connect to this table first.'


class Gateway:
    """sources/list and series/*, counted; ANSWERS maps an operation to its answer (or an httpx.Response)."""

    def __init__(self, answers, profile='table/1'):
        self.answers, self.calls, self.bodies = answers, [], []
        reference = {'authority': 'sql', 'key': 'production', 'revision': 'r' * 64, 'profile': profile}
        self.selection = selection({'manifest': {'reference': reference}}, profile=profile, name='production')

    def __call__(self, request):
        area, operation = request.url.path.rsplit('/', 2)[-2:]
        self.calls.append(area + '/' + operation); self.bodies.append(json.loads(request.content))
        if (area, operation) == ('sources', 'list'): return httpx.Response(200, json={'selections': [self.selection], 'scope': 's'})
        answer = self.answers.get(operation)
        if answer is None: return httpx.Response(404, json={'code': 'NOT_FOUND', 'message': 'unknown'})
        return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)


def read(answer=FIELD_A, name='Field A - Oil, monthly volume'):
    gateway = Gateway({'view': answer})
    with client(gateway) as c:
        return c.source('s1').series(name), gateway


def made(values, kind='volume', unit='MillSm3', zone='Not stated', months=None):
    """A view answer over VALUES (None: absent) from January 2017, as the server answers one."""
    months = months or ['%04d-%02d-01' % (2017 + i // 12, i % 12 + 1) for i in range(len(values))]
    points = [{'t': t, 'v': v} if v is not None else {'t': t, 's': 'absent'} for t, v in zip(months, values)]
    view = {**copy.deepcopy(FIELD_A['view']), 'kind': kind, 'unit': unit, 'zone': zone, 'points': points,
            'counts': {'figures': sum(v is not None for v in values), 'reported_gaps': 0, 'absent': sum(v is None for v in values)}}
    return S.Series({'view': view, 'revision': 'f' * 64})


# --- the FIELD_A view ------------------------------------------------------------------------------------------------

def test_the_field_a_series_reads_through_your_own_selection_as_a_frame_of_decimals():
    series, gateway = read()
    assert gateway.calls == ['sources/list', 'series/view']
    assert gateway.bodies[1] == {'project_id': 'p', 'subject': {'kind': 'table', 'connection_id': 'sql', 'key': 'production'},
                                 'name': 'Field A - Oil, monthly volume', 'selection_id': 's1'}
    frame = series.to_frame()
    assert len(frame) == 107 and str(frame.index.dtype).startswith('datetime64') and frame.index[0].isoformat() == '2015-03-01T00:00:00'
    assert frame.index[-1].isoformat() == '2024-01-01T00:00:00' and (frame.index.day == 1).all()
    assert list(frame['state']).count('absent') == 2 and list(frame.index[frame['state'] == 'absent'].strftime('%Y-%m')) == ['2023-11', '2023-12']
    assert frame.loc['2016-08-01', 'value'] == Decimal('0.32784') and isinstance(frame.loc['2017-01-01', 'value'], Decimal)
    assert frame.loc['2015-03-01', 'value'] == Decimal('0.0') and (frame['state'] == 'figure').sum() == 105
    assert {k: frame.attrs[k] for k in ('kind', 'unit', 'zone', 'revision', 'declaration_version')} == \
        {'kind': 'volume', 'unit': 'MillSm3', 'zone': 'Not stated', 'revision': FIELD_A['revision'], 'declaration_version': 1}
    assert frame.attrs['transformations'] == []
    lossy = series.to_frame(values='float')
    assert lossy.loc['2016-08-01', 'value'] == 0.32784 and lossy.attrs['transformations'] == \
        ['values as float: lossy; the exact figures are the decimal text of the series']
    assert series.reading('2017-03') == 'March 2017, 0.28085 MillSm3' and series.reading('2023-11') == 'November 2023, no row for this month'


def test_years_totals_and_the_gap_sentence():
    series, _ = read()
    years = series.by('year')
    assert years[2017] == '3.08681' and years[2023] == '2023: incomplete (10 of 12 months)' and years[2015] == '2015: incomplete (10 of 12 months)'
    with pytest.raises(S.SeriesRefused) as refused: series.total()
    assert str(refused.value.message) == '2 months have no figure (2023-11 to 2023-12). Ask for the total of the months that have figures, or fill them yourself.'
    total = series.total(allow_gaps=True)
    assert total == Decimal('19.57723') and str(total) == '19.57723' and total.partial
    with pytest.raises(S.SeriesRefused, match='^A volume is added up over a period, not averaged'): series.average()
    with pytest.raises(Refused, match='use by\\("year"\\)'): series.by('quarter')


def test_a_rate_is_never_added_up_and_units_are_never_mixed():
    rate = made(['1.0', '2.0'], kind='rate', unit='Sm3/d', months=['2023-01-01', '2023-02-01'])
    with pytest.raises(S.SeriesRefused) as refused: rate.total()  # mutation: the rules file's refusal for rates ignored
    assert (refused.value.rule, refused.value.message) == ('rate-total', 'A rate cannot be added up. Add volumes, or ask for an average.')
    assert rate.by('year')[2023] == 'This average is 87/59, which has no exact decimal form; it is not rounded.'
    leap = made(['0.0', '3.0'], kind='rate', unit='Sm3/d', months=['2024-01-01', '2024-02-01'])
    assert leap.by('year')[2024] == '1.45 (partial)' and leap.average() == Decimal('1.45')
    field_b = S.Series(FIELD_B)
    field_a, _ = read()
    with pytest.raises(S.SeriesRefused) as refused: S.compare(field_a, field_b)
    assert refused.value.message == 'The unit of one series is not stated, so it cannot be combined with a series that states one.'
    with pytest.raises(S.SeriesRefused) as refused: S.compare(field_a, made(['1.0'], unit='BillSm3'))
    assert refused.value.message == 'These series use different units (MillSm3 and BillSm3). Ophiolite does not convert them here; declare one unit or convert the numbers yourself.'
    assert list(S.compare(field_a, made(['1.0'], months=['2017-03-01'])).loc['2017-03-01']) == [Decimal('0.28085'), Decimal('1.0')]
    with pytest.raises(Refused) as refused: S.compare(field_a, made(['1.0'], kind='rate', unit='MillSm3'))  # mutation: kind check dropped
    assert refused.value.message == 'A volume and a rate are not the same thing, so they are not compared here.'
    with pytest.raises(S.SeriesRefused) as refused: S.compare(field_a, made(['1.0'], zone='Europe/Oslo'))
    assert refused.value.rule == 'zones'


def test_the_field_b_series_keeps_its_unit_unstated_and_its_reported_gap():
    field_b = S.Series(FIELD_B)
    assert (len(field_b), field_b.unit, field_b.counts) == (144, 'Not stated', {'figures': 143, 'reported_gaps': 1, 'absent': 0})
    assert field_b.reading('2014-01') == 'January 2014, reported without a figure' and field_b.reading('2015-08') == 'August 2015, 32110 unit not stated'
    assert field_b.by('year')[2015] == '399182' and field_b.total(allow_gaps=True) == Decimal('1896095')


# --- the shared vectors and the adversarial decimals, through the SDK --------------------------------------------------

@pytest.mark.parametrize('vector', VECTORS['canonical'], ids=lambda v: v['raw'])
def test_canonical_vectors(vector):
    if 'refused' in vector:
        with pytest.raises(S.SeriesRefused) as refused: S.canonical_float(float(vector['raw']))
        assert refused.value.rule == vector['refused']
    else:
        assert S.canonical_float(float(vector['raw'])) == vector['text'] == S.exact_sum([vector['text']])


def run(section, vector):
    return {'values': lambda: S.canonical_value(vector['text']), 'sum': lambda: S.exact_sum(vector['values']),
            'average': lambda: S.weighted_average([tuple(p) for p in vector['points']]), 'days': lambda: S.month_days(vector['month']),
            'rules': lambda: S.RULES['operations'][vector['kind']][vector['operation']],
            'year': lambda: S.year(vector['kind'], vector['year'], [tuple(p) for p in vector['points']])}[section]()


@pytest.mark.parametrize('section, vector', [(s, v) for s in ('values', 'sum', 'average', 'days', 'rules', 'year') for v in VECTORS[s]])
def test_every_vector(section, vector):
    if 'refused' in vector:
        with pytest.raises(S.SeriesRefused) as refused: run(section, vector)
        assert refused.value.rule == vector['refused']
    else:
        assert run(section, vector) == vector.get('expect', vector.get('text'))


def test_every_section_of_the_vectors_is_executed():
    assert set(VECTORS) == {'schema', 'description', 'canonical', 'values', 'sum', 'average', 'days', 'rules', 'year'}


def test_adversarial_decimals_are_exact_or_refused():
    huge = made(['1234567890123456789012345678.1', '0.0000000000000000000000000001'])
    assert str(huge.total()) == '1234567890123456789012345678.1000000000000000000000000001'
    assert str(made(['0.1'] * 10).total()) == '1.0'
    nines = made(['9' * 40] * 11 + ['0.' + '0' * 38 + '1'])
    with pytest.raises(S.SeriesRefused, match='^This result needs more than 80 digits'): nines.total()
    assert str(made(['2.28530', '0.00000']).total()) == '2.28530'
    with pytest.raises(VerificationFailed): made(['1' * 41])  # over the input bound: the answer is not the documented view


def test_the_rules_and_vectors_are_the_platform_documents():
    from importlib.resources import files
    root = files('ophiolite').joinpath('contracts', 'series', 'v1')
    assert hashlib.sha256(root.joinpath('series-rules.json').read_bytes()).hexdigest() == '9a13b991bb2164e9479a21be7cbe485f922887217a9b9929544f1cdc004bf0a7'
    assert hashlib.sha256(root.joinpath('series-vectors.json').read_bytes()).hexdigest() == 'c74265c4c578f5613b531607f1dab1596e95e1278352e6e5e4f307c9927418b2'


# --- refusals and checks -------------------------------------------------------------------------------------------

def test_a_member_without_a_selection_is_told_to_connect_and_an_altered_view_is_refused():
    refusal = httpx.Response(422, json={'error': CONNECT_FIRST, 'code': 'connect-first', 'message': CONNECT_FIRST, 'remedy': 'r',
                                        'docs': '/docs/reference/errors/#connect-first', 'request_id': 'req_1'})
    gateway = Gateway({'view': refusal})
    with client(gateway) as c, pytest.raises(Refused) as raised: c.source('s1').series('Field A - Oil, monthly volume')
    assert raised.value.message == CONNECT_FIRST
    altered = copy.deepcopy(FIELD_A); altered['view']['counts']['absent'] = 1
    with pytest.raises(VerificationFailed): read(altered)
    altered = copy.deepcopy(FIELD_A); altered['view']['points'][3]['v'] = '1e-3'
    with pytest.raises(VerificationFailed): read(altered)
    altered = copy.deepcopy(FIELD_A); points = altered['view']['points']; points[3], points[4] = points[4], points[3]
    with pytest.raises(VerificationFailed): read(altered)  # mutation: months out of order accepted
    gateway = Gateway({}, profile='sql-wells/1')
    with client(gateway) as c, pytest.raises(Refused, match='Only a SQL table read as a table'): c.source('s1').series('x')
    assert gateway.calls == ['sources/list']


def test_series_list_names_each_series_and_its_version():
    listed = {'series': [{'name': 'Field A - Oil, monthly volume', 'version': 2, 'generation': 2, 'state': 'active', 'declaration': {'name': 'Field A - Oil, monthly volume'}}]}
    gateway = Gateway({'list': listed})
    with client(gateway) as c:
        assert c.source('s1').series_list() == [{'name': 'Field A - Oil, monthly volume', 'version': 2, 'declaration': {'name': 'Field A - Oil, monthly volume'}}]


def test_a_kept_table_reads_its_series_at_its_own_revision():
    from ophiolite.typed import Table
    calls = []

    class Client:
        def _post(self, area, operation, body, **options):
            calls.append((area, operation, body)); return FIELD_A
    table = Table.__new__(Table)
    table._client, table.asset_id, table.revision = Client(), 'kept-field-a', FIELD_A['revision']
    series = table.series('Field A - Oil, monthly volume')
    assert len(series) == 107 and calls == [('series', 'view', {'subject': {'kind': 'asset', 'asset_id': 'kept-field-a'}, 'name': 'Field A - Oil, monthly volume',
                                                               'revision': FIELD_A['revision']})]
    table.revision = 'e' * 64
    with pytest.raises(VerificationFailed): table.series('Field A - Oil, monthly volume')


def test_without_pandas_the_frame_is_refused_in_words(monkeypatch):
    series, _ = read()
    monkeypatch.setitem(sys.modules, 'pandas', None)
    with pytest.raises(Refused, match=r'^Install ophiolite\[pandas\] for DataFrames\.$'): series.to_frame()
    assert series.total(allow_gaps=True) == Decimal('19.57723')  # exact arithmetic needs no pandas


# --- the command line ------------------------------------------------------------------------------------------------

def test_series_read_writes_the_literal_rows(tmp_path):
    from test_cli_subprocess import gateway, run as cli
    gateway_ = Gateway({})
    routes = {'/sources/list': (200, {'selections': [gateway_.selection], 'scope': 's'}), '/series/view': (200, FIELD_A)}
    out = tmp_path / 'field-a.csv'
    with gateway(routes) as server:
        written = cli(tmp_path, 'series', 'read', 's1', 'Field A - Oil, monthly volume', '--out', str(out), url=server.url)
        again = cli(tmp_path, 'series', 'read', 's1', 'Field A - Oil, monthly volume', '--out', str(out), url=server.url)
    assert written.returncode == 0, written.stderr
    lines = out.read_bytes().decode().split('\r\n')
    assert lines[0] == 'month,value,state' and len(lines) == 109 and lines[-1] == ''
    assert lines[1] == '2015-03-01,0.0,figure' and '2016-08-01,0.32784,figure' in lines and '2023-11-01,,absent' in lines
    assert again.returncode != 0 and 'add --force' in again.stderr + again.stdout
