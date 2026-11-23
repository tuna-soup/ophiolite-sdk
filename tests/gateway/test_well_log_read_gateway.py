"""E183 s2c C1: the SDK reads a well log in its own shape from the in-process gateway (strategy
E183-s2-curve-declaration, rev 2 closed: T1.1 routing, T1.3 causes).

Every file is SYNTHETIC (test_curve_declaration_gateway.LAS and the Platform's synthetic long file); every sentence is a
literal typed here, never read from the code under test."""
import json

import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from test_curve_declaration_gateway import DECLARED, LAS, SEND
from ophiolite.client import WellLogSet
from ophiolite.errors import Refused, Unavailable

FORM = 'ophiolite.well-log-curve/1'
WELL = "The well is not declared; it is not read from the file's header."
KIND = 'The depth kind is not declared.'
DATUM = "The depth datum is not declared; 'unknown' may be declared, a header value is not used."
UNIT = 'The value unit is not declared.'
SAMPLES = ('This curve has more than 100,000 samples and is read in sections; the well log form holds a curve of up to '
           '100,000 samples.')


def asked(web):
    """The paths of every request the SDK makes from here on."""
    paths = []
    web.c.event_hooks['request'].append(lambda request: paths.append(request.url.path))
    return paths


def stored_row(web, info):
    from project_gateway.scientific_api import ScientificAPI
    spec = {'project_id': 'p', 'asset_id': info.asset_id, 'revision': info.revision, 'curve': 'GR', 'representation': 'well-log-curve:GR'}
    return ScientificAPI(web.a).call('representation', spec, 'alice')[0]


def test_t11_the_form_read_routes_to_the_well_log_row_and_never_the_application_curve(web):
    """C2: the old `curve:GR` representation is made unavailable while the form is valid; the form read succeeds and
    equals the stored row; the read without form fails. Mutation: read(form=) reading the old representation: red."""
    alice = client(web, 'alice', 'delegate')
    info = alice.upload_las(LAS.encode(), curve_declaration=DECLARED, command_id='routing', **SEND)

    def unavailable(request):
        if request.url.path.endswith('/representations/curve:GR'): raise ConnectionRefusedError('the application curve is unavailable')
    web.c.event_hooks['request'].append(unavailable)
    got = alice.read(info.asset_id, info.revision, ['GR'], form=FORM)
    assert isinstance(got, WellLogSet)
    assert got._wire_curve_bytes == [stored_row(web, info)]
    log = got.curves[0]
    assert (log.well, log.depth_kind, log.depth_datum, log.depth_unit, log.unit) == ('SYNTHETIC-W1', 'MD', 'unknown', 'M', 'gAPI')
    rows = LAS.split('~ASCII\n')[1].splitlines()
    assert log.depth == [float(r.split()[0]) for r in rows] and log.values[:3] == [0.0, None, 30.0]
    # nothing is read from the header: its well, datum and depth unit are not the declaration
    assert 'HEADER-WELL-9' not in (log.well, log.depth_datum) and log.depth_unit != 'FT'
    assert log.header.entries_total == len(log.header.entries) + log.header.entries_withheld > 0
    with pytest.raises((Unavailable, ConnectionRefusedError)): alice.read(info.asset_id, info.revision, ['GR'])


def refused(web, alice, info):
    paths = asked(web)
    with pytest.raises(Refused) as caught: alice.read(info.asset_id, info.revision, ['GR'], form=FORM)
    assert not any('/representations/' in p for p in paths)  # nothing falls back, nothing else is asked
    assert caught.value.status == 422 and caught.value.server_message == caught.value.message
    return caught.value.message


def test_t13_an_undeclared_upload_is_refused_with_every_cause_in_order(web):
    """Mutation: fall back to the old read on a 422: red."""
    alice = client(web, 'alice', 'delegate')
    info = alice.upload_las(LAS.encode(), command_id='undeclared', **SEND)
    assert refused(web, alice, info) == ' '.join((WELL, KIND, DATUM))
    assert len(alice.read(info.asset_id, info.revision, ['GR']).curves[0].values) > 0  # the curve stays readable


def test_t13_a_blank_value_unit_is_refused_with_its_sentence(web):
    alice = client(web, 'alice', 'delegate')
    raw = LAS.replace('GR.gAPI : gamma', 'GR. : gamma').encode()
    info = alice.upload_las(raw, curve_declaration=DECLARED, command_id='blank-unit', **SEND)
    assert refused(web, alice, info) == UNIT


def test_t13_a_curve_read_in_sections_is_refused_with_the_samples_cause(web):
    from project_gateway.tests.test_large_las import las
    alice = client(web, 'alice', 'delegate')
    info = alice.upload_las(las(100_001), curve_declaration=DECLARED, command_id='long', **SEND)
    assert refused(web, alice, info) == SAMPLES
