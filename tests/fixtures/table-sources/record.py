"""E50b1: record ADR 0020's worked examples 5a and 5b as the Platform answers them (sources/list and sources/export).

Run from a lane with Platform and Connectors beside this repository and initdb installed:
  PYTHONPATH=../ophiolite-platform/services:../ophiolite-connectors/src:../ophiolite-connectors/tests \
    python tests/fixtures/table-sources/record.py
A throwaway PostgreSQL cluster holds the ADR's tables; the gateway's own Sources saves the declaration, binds and exports.
The answers are written as they come back (no credential, path or host is in them); the clocks are fixed afterwards.
"""
import json
import tempfile
from pathlib import Path

from asset_connectors.sources import Registry
from pg_cluster import Cluster
from project_gateway.jobs import Journal
from project_gateway.sources import Sources

HERE = Path(__file__).parent
EXAMPLES = {
    '5a': ('production', ['CREATE TABLE public.production (well_code text, month date, oil_m3 numeric(12,3), gas_km3 numeric, remarks text NULL)',
                          "INSERT INTO public.production VALUES ('NL-001', '2026-01-01', 1520.250, 310.5, NULL), "
                          "('NL-001', '2026-02-01', 1498.000, 305.0, 'workover'), ('NL-002', '2026-01-01', 87.125, NULL, NULL)"],
           ['well_code', 'month'], {'oil_m3': {'description': None, 'unit': 'm3', 'quantity': None, 'missing': None}}),
    '5b': ('lithology_log', ['CREATE TABLE public.lithology_log (well_code text, top_m float, base_m float, lithology text, note text NULL)',
                             "INSERT INTO public.lithology_log VALUES ('NL-001', 12.5, 40.0, 'clay', 'soft'), ('NL-001', 0.0, 12.5, 'sand', NULL), "
                             "('NL-001', 12.5, 40.0, 'clay', 'soft')"],
           None, {}),
}


def platform(method, body, token):
    return {'user_id': token, 'projects': [{'id': 'p', 'can_administer': True}]}


def fixed(document):
    """Clocks are not part of what the SDK verifies; fixed so a re-recording differs only where the answer does."""
    if isinstance(document, dict):
        return {k: (1.0 if k in ('last_checked', 'next_check', 'checked') else fixed(v)) for k, v in document.items()}
    if isinstance(document, list): return [fixed(v) for v in document]
    return document


def main():
    tmp = Path(tempfile.mkdtemp())
    with Cluster(ssl=False) as cluster:
        for name, (table, statements, key, columns) in EXAMPLES.items():
            cluster.sql(*statements)
            config = {'id': 'nlog', 'name': 'NLOG provinces', 'namespace': 'nlog', 'type': 'postgresql', 'principals': {'alice': 'resolved'},
                      'tables': {table: {'table': table, 'schema': 'public', 'name': table}}, '_credential_resolver': lambda principal: cluster.dsn()}
            (tmp / name).mkdir()
            journal = Journal(tmp / name / 'journal.sqlite')  # its payload store sits beside it, one per example
            s = Sources(platform, journal, Registry({'connections': [config]}))
            body = {'project_id': 'p', 'connection_id': 'nlog', 'key': table, 'profile': 'table/1'}
            schema = s.call('schema', body, 'alice')
            s.call('mapping-save', {**body, 'mapping': {'profile': 'table/1', 'key': key, 'columns': columns, 'coordinates': None,
                                                        'schema_digest': schema['schema_digest']}, 'expected_generation': 0}, 'alice')
            preview = s.call('preview', body, 'alice')
            bound = s.call('bind', {**body, 'preview_digest': preview['preview_digest'], 'acknowledge_unknowns': True}, 'alice')
            answer = {'selection': fixed(next(i for i in s.call('list', {'project_id': 'p'}, 'alice')['selections'] if i['id'] == bound['id'])),
                      'export': s.call('export', {'project_id': 'p', 'id': bound['id']}, 'alice')}
            (HERE / (name + '.json')).write_text(json.dumps(answer, indent=1, sort_keys=True) + '\n')
            journal.close()


if __name__ == '__main__':
    main()
