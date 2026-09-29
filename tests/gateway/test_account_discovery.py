"""E27 C8: Account.projects() against the in-process gateway for a delegate and a capability-3 grant."""
import pytest
from test_in_process_publish import web, shared, app, service
from ophiolite import Credential
from ophiolite.account import Account


def test_a_bound_credential_discovers_exactly_its_project(web, service):
    from project_gateway.application_access import ApplicationAccess
    from project_gateway.tests.test_one_api_matrix import claims_for
    delegate = Account('https://workspace.example', Credential.bearer('oph_api_alice:read'), web.c)
    assert [p['id'] for p in delegate.projects()] == ['p']
    api = ApplicationAccess(service)
    row = api.request({'project_id': 'p', 'scopes': ['read'], 'label': 'Notebook', 'capability': 3}, 'alice', claims_for('alice'))
    api.browser('approve', {'id': row['id'], 'confirmation_code': row['confirmation_code']}, 'alice')
    grant = Account('https://workspace.example', Credential.bearer('provider-alice', grant=row['id']), web.c)
    assert [p['id'] for p in grant.projects()] == ['p'] and isinstance(grant.organizations(), list)
    assert list(grant.client('p').assets()) is not None  # the discovered project opens through the ordinary client
