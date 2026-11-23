"""E183 s3 C1: a fetch passes the form to the read and keeps the gateway's sentence (strategy
E183-s3-opendtect-read, rev 2 closed: T1.1-T1.3). The SDK's Exchange over ClientTransport against the in-process
gateway, as an OpendTect get fetches: curves named, no output folder.

Every file is SYNTHETIC (test_curve_declaration_gateway.LAS); every sentence is a literal typed here or in the s2c
gateway test, never read from the code under test."""
import json

import pytest
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed, session  # noqa: F401
from test_exchange import client, key, refused
from test_curve_declaration_gateway import DECLARED, LAS, SEND
from test_well_log_read_gateway import DATUM, KIND, WELL, stored_row
from ophiolite.client import CurveSet, WellLogSet

FORM = 'ophiolite.well-log-curve/1'
NOT_VALID = ('The project refused this: a form is read for named curves, as one of ophiolite.well-log-curve/1. '
             'Nothing was sent.')
UNREACHED = 'Could not reach the project. Nothing was changed; for send, run the same command again: it will not publish twice.'


@pytest.fixture
def alice(keyed):
    return client(keyed, key(keyed, 'alice'))


def representations(web):
    """The representation each read asks for from here on."""
    asked = []
    web.c.event_hooks['request'].append(lambda r: asked.append(r.url.path.rsplit('/', 1)[-1]) if '/representations/' in r.url.path else None)
    return asked


def test_t11_a_declared_version_is_fetched_in_the_well_log_form_and_the_held_record_keeps_its_keys(keyed, alice, tmp_path):
    """output=None, as OpendTect fetches. Mutation: the form dropped in ClientTransport.fetch: red (a CurveSet of the
    application curve comes back, `curve:GR` is asked)."""
    info = alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='t11', **SEND)
    ex, asked = alice.exchange(tmp_path / 'w'), representations(keyed)
    got = ex.fetch(info.asset_id, curves=['GR'], form=FORM)
    assert isinstance(got.content, WellLogSet) and got.content._wire_curve_bytes == [stored_row(keyed, info)]
    assert 'curve:GR' not in asked and 'well-log-curve:GR' in asked
    log = got.content.curves[0]
    assert (log.well, log.depth_kind, log.depth_unit, log.depth_datum) == ('SYNTHETIC-W1', 'MD', 'M', 'unknown')
    assert got.facts == {'name': 'Synthetic log', 'number': 1, 'who': 'Alice', 'when': 'just now'}
    got.confirm()
    with_form = ex.held()[info.asset_id]
    plain = alice.exchange(tmp_path / 'v').fetch(info.asset_id, curves=['GR'])
    plain.confirm()
    without = alice.exchange(tmp_path / 'v').held()[info.asset_id]
    assert sorted(with_form) == sorted(without) and with_form['output'] is None and 'selection' not in json.dumps(with_form)


def test_t12_an_undeclared_version_is_cannot_read_here_with_the_gateways_sentence_and_its_revision(keyed, alice, tmp_path):
    """Mutation: the 422 left to _transport_error: red (could-not-reach, the causes lost)."""
    info = alice.upload_las(LAS.encode(), command_id='t12', **SEND)
    ex, asked = alice.exchange(tmp_path / 'w'), representations(keyed)
    cannot = refused('cannot-read-here', lambda: ex.fetch(info.asset_id, curves=['GR'], form=FORM))
    assert cannot.sentence == ' '.join((WELL, KIND, DATUM)) and asked == []
    assert cannot.facts == {'sentence': ' '.join((WELL, KIND, DATUM)), 'reason': 'form', 'name': 'Synthetic log'}
    assert cannot.technical == {'form': FORM, 'status': 422, 'revision': info.revision}
    assert info.asset_id not in ex.held()
    again = alice.exchange(tmp_path / 'w', lock_timeout=0.1).fetch(info.asset_id, curves=['GR'])  # the folder's lock is free
    assert isinstance(again.content, CurveSet) and not isinstance(again.content, WellLogSet) and asked == ['artifact', 'curve:GR']
    again.release()


def test_t13_without_a_form_the_fetch_is_todays_and_a_form_needs_curves_and_a_known_form(keyed, alice, tmp_path):
    info = alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='t13', **SEND)
    ex, asked = alice.exchange(tmp_path / 'w'), representations(keyed)
    got = ex.fetch(info.asset_id, curves=['GR'])
    rows = LAS.split('~ASCII\n')[1].splitlines()
    curve = json.loads(got.content._wire_curve_bytes[0])
    assert type(got.content) is CurveSet and asked == ['artifact', 'curve:GR']
    assert curve['curve'] == 'GR' and curve['values'][:3] == [0.0, None, 30.0] and len(curve['values']) == len(rows)
    got.release()
    lost = refused('could-not-reach', lambda: ex.fetch(info.asset_id, curves=['NOT-A-CURVE']))
    assert lost.sentence == UNREACHED and lost.technical['status'] == 422
    for how in ({'form': FORM}, {'form': 'ophiolite.application-curve/1', 'curves': ['GR']}, {'form': FORM, 'window': {'inline': [1, 2]}}):
        assert refused('not-valid', lambda: ex.fetch(info.asset_id, **how)).sentence == NOT_VALID
