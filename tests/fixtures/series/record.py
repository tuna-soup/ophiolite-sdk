"""Record the series/view answers the SDK tests read (E62a). All figures here are synthetic: they are made by the
formulas below and describe no real field. Run this from an Ophiolite Connectors checkout's environment:

    PYTHONPATH=<connectors>/src python tests/fixtures/series/record.py

The views are built by the Connectors' own `series_view.build`, which is the code the gateway serves `series/view` with.
It reads two synthetic tables with E58a's `read_table`, each as a kept table at the SHA-256 of its CSV, which is the
revision a kept table answers.

- Field A. A year-and-month table with two fields, so that the row filter is exercised. The oil volume of Field A in
  MillSm3 runs from March 2015 to January 2024. It starts at zero in its first month, and November and December 2023
  have no row.
- Field B. A time, value and state table running from January 2014 to December 2025, with no unit stated. January 2014
  is reported without a figure, and the months the field is shut in are zero.

It writes field-a-view.json and field-b-view.json beside this script."""
import hashlib
import json
import math
from pathlib import Path

from asset_connectors import series_view
from asset_connectors.table_files import read_table

HERE = Path(__file__).resolve().parent
FIELD_A = {'name': 'Field A - Oil, monthly volume', 'subject': {'kind': 'asset', 'asset_id': 'kept-field-a'},
           'confirmed': {'columns_digest': 'a' * 64, 'interpretation_sha256': 'b' * 64},
           'rows': {'column': 'field', 'equals': 'Field A'}, 'range': None,
           'when': {'from': 'year-month', 'year': 'year', 'month': 'month'},
           'measure': {'column': 'oil_net_millsm3', 'kind': 'volume', 'unit': 'MillSm3'}, 'zone': 'Not stated',
           'about': {'kind': 'name', 'text': 'Field A'}}
FIELD_B = {'name': 'Field B - Oil', 'subject': {'kind': 'asset', 'asset_id': 'kept-field-b'},
           'confirmed': {'columns_digest': 'a' * 64, 'interpretation_sha256': 'b' * 64}, 'rows': None, 'range': None,
           'when': {'from': 'column', 'column': 'time', 'period': 'month'},
           'measure': {'column': 'value', 'kind': 'volume', 'unit': 'Not stated'}, 'zone': 'Not stated',
           'about': {'kind': 'name', 'text': 'Field B'}}
SHUT_IN = {(2018, 9), (2019, 5), (2019, 6), (2025, 5)}


def field_a_csv():
    lines = ['field,year,month,oil_net_millsm3']
    for i in range(107):
        year, month = 2015 + (i + 2) // 12, (i + 2) % 12 + 1
        if (year, month) in ((2023, 11), (2023, 12)): continue
        value = 0.0 if i == 0 else 0.42 * math.exp(-0.018 * i) * (1 + 0.06 * ((i * 7) % 5 - 2) / 2)
        lines.append('Field A,%d,%d,%.5f' % (year, month, value))
        lines.append('Field Z,%d,%d,%.5f' % (year, month, 0.1 + 0.001 * i))
    return ('\n'.join(lines) + '\n').encode()


def field_b_csv():
    lines = ['time,value,state']
    for i in range(144):
        year, month = 2014 + i // 12, i % 12 + 1
        if i == 0: lines.append('2014-01-01,,reported-gap'); continue
        value = 0 if (year, month) in SHUT_IN else round(52000 * math.exp(-0.026 * i) * (1 + 0.08 * math.sin(i)))
        lines.append('%d-%02d-01,%d,figure' % (year, month, value))
    return ('\n'.join(lines) + '\n').encode()


def record(raw, declaration, out):
    _, data, _ = read_table(raw)
    revision = hashlib.sha256(raw).hexdigest()
    view = series_view.build(data, declaration, revision, 1)
    (HERE / out).write_text(json.dumps({'view': view, 'revision': revision}, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    record(field_a_csv(), FIELD_A, 'field-a-view.json')
    record(field_b_csv(), FIELD_B, 'field-b-view.json')
