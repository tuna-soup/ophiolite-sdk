"""E126a acceptance 4: Client.find_log over assets(): AND filters, deterministic order, declared quantities only, no renaming."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from ophiolite import Client, Credential
from ophiolite.errors import Refused
from ophiolite.testing import synthetic_server

PREFIX = '/api/v1/projects/p/scientific-assets'


def log(ident, name, curves, count, operations=('read', 'export', 'use-as-input')):
    return {'asset_id': ident, 'revision': 'r-' + ident, 'name': name, 'origin': 'retained-capture', 'authority': 'fixture', 'profile': 'las2/1',
            'custodian': 'ophiolite:managed', 'curves': list(curves), 'sample_count': count, 'allowed_operations': list(operations)}


# Served in an order opposite to the expected one, over two pages, with Alpha's asset id (y1) after Beta's (b1, b2), so the
# sort, the name tie key and the asset-id tie key each carry a result.
PAGES = [[log('z9', 'Zeta', ['GR'], 5), log('b2', 'Beta', ['GR', 'RHOB'], 500), log('n0', 'Unknown count', ['GR'], None),
          log('tops', 'Tops', [], 900), log('ro', 'Read only', ['GR', 'NPHI'], 9000, ('read', 'export'))],
         [log('b1', 'Beta', ['GR', 'RHOB'], 500), log('y1', 'Alpha', ['gr', 'DT'], 500), log('q1', 'Quantity', ['GRC'], 7)]]
QUANTITIES = {('y1', 'gr'): ('Gamma Ray', 'suggested'), ('q1', 'GRC'): ('Gamma Ray', 'declared'), ('b1', 'GR'): ('Bulk Density', 'declared')}


@pytest.fixture
def catalogue(monkeypatch):
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        inner = server.handler
        def handler(method, path, body, headers):
            parts = urlsplit(path)
            if method == 'GET' and parts.path == PREFIX:
                page = 1 if parse_qs(parts.query).get('cursor') == ['next'] else 0
                return 200, {'items': PAGES[page], 'next_cursor': 'next' if page == 0 else None}
            return inner(method, path, body, headers)
        server.handler = handler
        described = []
        def describe(asset, revision, curve):
            described.append((asset, curve)); quantity, status = QUANTITIES.get((asset, curve), (None, None))
            return SimpleNamespace(scientific=SimpleNamespace(quantity=quantity, quantity_status=status))
        monkeypatch.setattr(alice, 'describe', describe)
        yield alice, described


def test_the_synthetic_log_is_found_by_its_curve():
    with synthetic_server() as server, Client(server.url, 'p', Credential.bearer('oph_api_alice')) as alice:
        assert alice.find_log(curves=['GR'])['asset_id'] == 'curve-a'
        with pytest.raises(Refused, match=r"No log you may use-as-input matches curves \['RHOB'\]\."): alice.find_log(curves=['RHOB'])


def test_the_largest_log_wins_and_ties_resolve_by_name_then_asset_id(catalogue):
    alice, _ = catalogue
    assert alice.find_log(curves=['GR'])['asset_id'] == 'y1'  # 500 rows each: Alpha before Beta; Read only (9000) cannot be used as input
    assert alice.find_log(curves=['GR', 'RHOB'])['asset_id'] == 'b1'  # Beta twice: asset id b1 before b2; two curves AND
    assert alice.find_log(curves=['GR'], operation='read')['asset_id'] == 'ro'
    assert alice.find_log(curves=['GR'], name='Unknown count')['asset_id'] == 'n0'
    assert alice.find_log(name='Zeta')['asset_id'] == 'z9' and alice.find_log()['asset_id'] == 'y1'  # a log has curves: Tops (900) is not one


def test_a_curve_matches_whatever_its_case_and_is_never_renamed(catalogue):
    alice, _ = catalogue
    found = alice.find_log(curves=['dt'])
    assert found['asset_id'] == 'y1' and found['curves'] == ['gr', 'DT'] and found == PAGES[1][1]


def test_names_match_exactly(catalogue):
    alice, _ = catalogue
    with pytest.raises(Refused, match=r"No log you may use-as-input matches curves \['GR'\] and name 'alpha'\."): alice.find_log(curves=['GR'], name='alpha')


def test_only_a_declared_quantity_matches_and_reads_stop_at_the_first_match(catalogue):
    alice, described = catalogue
    assert alice.find_log(quantity='Gamma Ray')['asset_id'] == 'q1'  # a1's gr is only suggested
    assert described == [('y1', 'gr'), ('y1', 'DT'), ('b1', 'GR'), ('b1', 'RHOB'), ('b2', 'GR'), ('b2', 'RHOB'), ('q1', 'GRC')]
    described.clear()
    assert alice.find_log(curves=['GR', 'RHOB'], quantity='Bulk Density', name='Beta')['asset_id'] == 'b1' and described == [('b1', 'GR')]
    with pytest.raises(Refused, match=r"No log you may use-as-input matches curves \['DT'\] and quantity 'Gamma Ray'\."):
        alice.find_log(curves=['DT'], quantity='Gamma Ray')


def test_an_unknown_operation_is_refused(catalogue):
    alice, _ = catalogue
    with pytest.raises(Refused, match='Choose read, export or use-as-input.'): alice.find_log(curves=['GR'], operation='write')
