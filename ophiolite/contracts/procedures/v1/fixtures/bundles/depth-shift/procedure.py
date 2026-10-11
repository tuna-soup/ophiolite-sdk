"""Shift well tops by a fixed depth (an E105a sample procedure)."""
import csv

from ophiolite import procedure
from ophiolite.writers import write_tops


@procedure
def shift(inputs, settings):
    tops = inputs['tops'][0]
    sign = 1 if settings['mode'] == 'add' else -1
    with open(tops.path, newline='', encoding='utf-8') as handle:
        rows = [{'name': row['name'], 'md': float(row['md']) + sign * settings['shift']} for row in csv.DictReader(handle)]
    return {'shifted': write_tops(rows, depth_unit=tops.declared['depth_unit'], depth_basis=tops.declared['depth_basis'])}
