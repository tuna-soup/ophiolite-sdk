"""E183 s2c C1: the SDK reads a well log in its own shape (strategy E183-s2-curve-declaration, rev 2 closed: T1.2,
T1.4, T1.5, T1.6; T1.1 and T1.3 against the gateway are tests/gateway/test_well_log_read_gateway.py).

Every answer is SYNTHETIC: the capture fixture's descriptor and curve, with a well log written here from them by a
test-local mapping, and header entries typed here. Each verifier case is rehashed (the normalized row's bytes and digest
recomputed) so only the named invariant fails; each asserts its own sentence."""
import copy
import hashlib
import json
import math

import httpx
import pytest
from ophiolite import Client, Credential
from ophiolite.client import CurveSet, WellLogSet
from ophiolite.errors import AxisMismatch, Refused, VerificationFailed
from ophiolite.scientific import WellLog

FORM = 'ophiolite.well-log-curve/1'
ENTRIES = [{'section': 'V', 'mnemonic': 'VERS', 'unit': '', 'value': '2.0', 'description': 'LAS version'},
           {'section': 'W', 'mnemonic': 'WELL', 'unit': '', 'value': 'SYNTHETIC-M1', 'description': 'Not an observed well'},
           {'section': 'C', 'mnemonic': 'GR', 'unit': 'gAPI', 'value': '', 'description': 'Gamma ray'}]


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def well_log(curve, *, well='SYNTHETIC-W1', kind='MD', datum='unknown', entries=ENTRIES, withheld=0):
    """The test's own mapping of an application curve onto the well log shape (the strategy's field list)."""
    c = json.loads(curve) if isinstance(curve, bytes) else curve
    context, reader = c['context'], c['interpretation']
    return {'schema': FORM,
            'strict': {'well': well, 'mnemonic': c['curve'], 'unit': c['unit'], 'unit_status': 'declared', 'depth_kind': kind,
                       'depth_unit': context['depth_unit'], 'depth_datum': datum, 'depth': list(c['axis']), 'values': list(c['values']),
                       'missing_value_marker': context['missing_value_marker'],
                       'reading': {'reader': reader['reader'], 'lasio_version': reader['lasio_version'], 'mapping': reader['mapping'],
                                   'null_policy': reader['null_policy'], 'parsing_policy': reader['parsing_policy'],
                                   'depth_index': context['depth_index'], 'missing_value_policy': context['missing_value_policy'],
                                   'depth_reference': context['depth_reference']}},
            'as_received': {'source': c['source'], 'source_sha256': c['source_sha256'], 'entries': copy.deepcopy(entries),
                            'entries_total': len(entries) + withheld, 'entries_withheld': withheld}}


def described(d, value, *, facts=True):
    """The descriptor as the gateway answers with the form: its normalized row is the well log's, rehashed."""
    d = copy.deepcopy(d); raw = encode(value); strict = value['strict']
    row = next(r for r in d['representations'] if r['kind'] == 'normalized')
    row.update(id='well-log-curve:' + (strict['mnemonic'] if facts else d['scientific']['curve']), profile=FORM, losses=[], bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    if facts:
        depth = strict['depth']
        d['scientific'].update(curve=strict['mnemonic'], unit=strict['unit'], axis_unit=strict['depth_unit'], sample_count=len(depth),
                               missing_count=strict['values'].count(None),
                               axis_order='insufficient' if len(depth) < 2 else 'increasing')
    return d, raw


def serve(answers, artifact, old=None):
    """answers: {curve: (form descriptor, well log bytes)}; old: (descriptor, curve bytes) for a read without form."""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        path = request.url.path; query = request.url.params
        curve = query.get('curve')
        if path.endswith('/representations/las'): return httpx.Response(200, content=artifact)
        if '/representations/well-log-curve:' in path: return httpx.Response(200, content=answers[curve][1])
        if '/representations/' in path: return httpx.Response(200, content=old[1])
        if 'form' in query: return httpx.Response(200, json=answers[curve][0])
        return httpx.Response(200, json=old[0])
    return calls, httpx.MockTransport(handler)


def read(d, answers, artifact, curves=('GR',), old=None, **options):
    calls, transport = serve(answers, artifact, old)
    with httpx.Client(transport=transport) as http:
        client = Client('http://localhost', d['project_id'], Credential.bearer('synthetic-token'), http)
        return client.read(d['asset_id'], d['revision'], list(curves), **options), calls


@pytest.fixture
def capture(fixture):
    d, curve, artifact = fixture('capture')
    return d, json.loads(curve), artifact


def test_a_form_read_returns_verified_well_logs_with_their_declaration_and_header(capture):
    d, curve, artifact = capture
    value = well_log(curve)
    got, calls = read(d, {'GR': described(d, value)}, artifact, form=FORM)
    assert isinstance(got, WellLogSet) and isinstance(got.curves[0], WellLog)
    log = got.curves[0]
    assert (log.well, log.depth_kind, log.depth_unit, log.depth_datum) == ('SYNTHETIC-W1', 'MD', 'M', 'unknown')
    assert (log.curve, log.unit, log.missing_value_marker) == ('GR', 'gAPI', '-999.25')
    assert log.depth == [100.0, 101.0, 102.0, 103.0, 104.0] and log.values == [0.0, 10.0, None, 30.0, 40.0]
    assert (log.header.entries, log.header.entries_total, log.header.entries_withheld) == (ENTRIES, 3, 0)
    assert log.header.source == curve['source'] and log.header.source_sha256 == curve['source_sha256']
    assert 'form=ophiolite.well-log-curve%2F1' in calls[0]
    assert not any('/representations/curve' in c for c in calls)  # the application curve is never asked for


def rehashed(change):
    def build(d, curve):
        value = well_log(curve); change(value)
        return described(d, value, facts=False)
    return build


def plain_mismatch(d, curve):
    d, raw = described(d, well_log(curve))
    value = json.loads(raw); value['strict']['values'][0] = 1.0
    return d, encode(value)  # not rehashed


def two_entries_over_the_ceiling(value):
    big = {'section': 'O', 'mnemonic': '', 'unit': '', 'value': 'x' * 40000, 'description': ''}
    value['as_received'].update(entries=[big, dict(big)], entries_total=2, entries_withheld=0)


CASES = {
    'source': (rehashed(lambda v: v['as_received']['source'].update(key='another-file')), 'Well log and artifact sources disagree'),
    'source_sha256': (rehashed(lambda v: v['as_received'].update(source_sha256=hashlib.sha256(b'another file').hexdigest())),
                      'Well log and artifact digests disagree'),
    'mnemonic': (rehashed(lambda v: v['strict'].update(mnemonic='SP')), 'The well log names another curve than the one asked for'),
    'reader': (rehashed(lambda v: v['strict']['reading'].update(reader='another.reader/1')), 'Descriptor interpretation disagrees with the well log reader'),
    'facts': (rehashed(lambda v: v['strict'].update(unit='API')), 'Descriptor scientific context disagrees with the well log'),
    'lengths': (rehashed(lambda v: v['strict']['values'].pop()), 'Depth and sample lengths differ'),
    'repeated depth': (rehashed(lambda v: v['strict']['depth'].__setitem__(2, 101.0)), 'The depth axis is not strictly increasing'),
    'withheld': (rehashed(lambda v: v['as_received'].update(entries_withheld=1)), 'entries_withheld must equal entries_total minus the entries kept'),
    'byte ceiling': (rehashed(two_entries_over_the_ceiling), 'The entries kept exceed 65536 bytes'),
    'not finite': (rehashed(lambda v: v['strict']['values'].__setitem__(0, math.inf)), 'Scientific data does not satisfy the declared contract.'),
    'digest': (plain_mismatch, 'Normalized representation unavailable or integrity mismatch'),
}


@pytest.mark.parametrize('case', CASES)
def test_t12_each_invariant_of_the_verifier_refuses_its_own_case(capture, case):
    """C3. Mutation: each check dropped in turn: its case red (the sentence names the check)."""
    d, curve, artifact = capture
    build, sentence = CASES[case]
    form_d, raw = build(d, curve)
    with pytest.raises(VerificationFailed) as caught: read(d, {'GR': (form_d, raw)}, artifact, form=FORM)
    assert caught.value.message == sentence


def test_t12_a_descriptor_that_names_the_application_curve_is_not_a_form_answer(capture):
    d, curve, artifact = capture
    form_d, raw = described(d, well_log(curve))
    next(r for r in form_d['representations'] if r['kind'] == 'normalized')['id'] = 'curve:GR'
    calls, transport = serve({'GR': (form_d, raw)}, artifact)
    with httpx.Client(transport=transport) as http:
        client = Client('http://localhost', d['project_id'], Credential.bearer('synthetic-token'), http)
        with pytest.raises(VerificationFailed) as caught: client.read(d['asset_id'], d['revision'], ['GR'], form=FORM)
    assert caught.value.message == 'The descriptor does not name the well log form of this curve'
    assert len(calls) == 1  # refused before any representation is asked for


def test_another_form_is_refused_here_with_the_gateways_sentence_and_nothing_is_asked(capture):
    d, curve, artifact = capture
    with pytest.raises(Refused) as caught: read(d, {}, artifact, form='ophiolite.application-curve/1')
    assert caught.value.message == 'Ask for the well log form (ophiolite.well-log-curve/1) or for no form.'


def test_a_422_is_refused_with_the_gateways_sentence_and_nothing_falls_back(capture):
    """Mutation: fall back to the read without form on a 422: red (a Refused is expected, and no representation)."""
    d, curve, artifact = capture
    sentence = "The well is not declared; it is not read from the file's header. The depth kind is not declared."
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if 'form' in request.url.params: return httpx.Response(422, json={'code': 'incompatible-context', 'message': sentence})
        return httpx.Response(500)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = Client('http://localhost', d['project_id'], Credential.bearer('synthetic-token'), http)
        with pytest.raises(Refused) as caught: client.read(d['asset_id'], d['revision'], ['GR'], form=FORM)
    assert caught.value.message == caught.value.server_message == sentence and caught.value.status == 422
    assert len(calls) == 1


def test_t14_a_read_without_form_is_unchanged(capture, fixture):
    d, curve, artifact = capture
    raw = fixture('capture')[1]
    got, calls = read(d, {}, artifact, old=(d, raw))
    assert type(got) is CurveSet and not any('form=' in c for c in calls)
    assert got._wire_curve_bytes == [raw] and got._wire_descriptors == [d]
    assert list(got.curves[0].values) == [0.0, 10.0, None, 30.0, 40.0]


def test_t14_strict_interpretation_keeps_its_meaning(capture):
    """A recorded reader that differs from the live one: a warning by default, InterpretationChanged when strict."""
    from ophiolite.errors import InterpretationChanged, InterpretationDiffers
    d, curve, artifact = capture
    form_d, raw = described(d, well_log(curve))
    form_d['recorded_interpretation'] = {**form_d['interpretation'], 'lasio_version': '0.31'}
    form_d['interpretation_evidence'] = 'recorded-differs'
    with pytest.warns(InterpretationDiffers): read(d, {'GR': (form_d, raw)}, artifact, form=FORM)
    with pytest.raises(InterpretationChanged): read(d, {'GR': (form_d, raw)}, artifact, form=FORM, strict_interpretation=True)


def test_t15_the_frame_is_indexed_by_the_declared_kind_and_carries_unit_datum_and_well(capture):
    pytest.importorskip('pandas')
    d, curve, artifact = capture
    got, _ = read(d, {'GR': described(d, well_log(curve, datum='KB'))}, artifact, form=FORM)
    frame, meta = got.to_frame()
    assert frame.index.name == 'MD' and list(frame.index) == [100.0, 101.0, 102.0, 103.0, 104.0]
    assert list(frame.columns) == ['GR'] and math.isnan(frame['GR'].iloc[2]) and frame['GR'].iloc[3] == 30.0
    attrs = frame.attrs['ophiolite']
    assert (attrs['well'], attrs['depth_kind'], attrs['depth_unit'], attrs['depth_datum']) == ('SYNTHETIC-W1', 'MD', 'M', 'KB')
    assert attrs['curves']['GR']['unit'] == 'gAPI' and attrs['curves']['GR']['missing_count'] == 1
    assert meta.depth_unit == 'M' and attrs['contracts']['schema_ids'] == ['ophiolite.scientific-asset/1', FORM]


def test_t15_a_feet_depth_stays_feet_and_a_one_sample_axis_frames(capture):
    pytest.importorskip('pandas')
    d, curve, artifact = capture
    feet = {**curve, 'context': {**curve['context'], 'depth_unit': 'ft'}}
    got, _ = read(d, {'GR': described(d, well_log(feet, kind='TVDSS'))}, artifact, form=FORM)
    frame, meta = got.to_frame()
    assert frame.index.name == 'TVDSS' and meta.depth_unit == 'ft' and list(frame.index) == [100.0, 101.0, 102.0, 103.0, 104.0]
    one = {**curve, 'axis': [100.0], 'values': [None]}
    got, _ = read(d, {'GR': described(d, well_log(one))}, artifact, form=FORM)
    frame, meta = got.to_frame()
    assert list(frame.index) == [100.0] and math.isnan(frame['GR'].iloc[0]) and meta.curves['GR'].sample_count == 1


def pair(d, curve, artifact, **second):
    """GR as declared, and a second curve SP of the same version whose well log differs as `second` says."""
    gr = well_log(curve)
    sp_curve = {**curve, 'curve': 'SP', 'unit': 'mV', **second.pop('changed', {})}
    sp = well_log(sp_curve, **second)
    sp_d = copy.deepcopy(d)
    return read(d, {'GR': described(d, gr), 'SP': described(sp_d, sp)}, artifact, curves=('GR', 'SP'), form=FORM)[0]


@pytest.mark.parametrize('second, reason', [
    (lambda c: {'well': 'SYNTHETIC-W2'}, 'well'),
    (lambda c: {'kind': 'TVD'}, 'kind'),
    (lambda c: {'datum': 'KB'}, 'datum'),
    (lambda c: {'changed': {'context': {**c['context'], 'depth_unit': 'ft'}}}, 'unit'),
    (lambda c: {'changed': {'axis': [100.0, 101.0, 102.5, 103.0, 104.0]}}, 'values'),
])
def test_t16_well_logs_combine_only_when_depth_and_declaration_agree(capture, second, reason):
    """C6. Mutation: each comparison dropped: its case red (a frame is built)."""
    pytest.importorskip('pandas')
    d, curve, artifact = capture
    got = pair(d, curve, artifact, **second(curve))
    with pytest.raises(AxisMismatch) as caught: got.to_frame()
    assert caught.value.reason == reason and caught.value.curves == ('GR', 'SP')
    with pytest.raises(AxisMismatch): got.to_numpy()


def test_t16_equal_well_logs_combine(capture):
    pytest.importorskip('pandas')
    d, curve, artifact = capture
    frame, meta = pair(d, curve, artifact).to_frame()
    assert list(frame.columns) == ['GR', 'SP'] and meta.curves['SP'].unit == 'mV'


def test_t16_old_and_new_forms_are_never_combined(capture, fixture):
    d, curve, artifact = capture
    logs, _ = read(d, {'GR': described(d, well_log(curve))}, artifact, form=FORM)
    old, _ = read(d, {}, artifact, old=(d, fixture('capture')[1]))
    mixed_new = WellLogSet(logs.descriptors + old.descriptors, logs.curves + old.curves, artifact)
    mixed_old = CurveSet(old.descriptors + logs.descriptors, old.curves + logs.curves, artifact)
    sentence = 'Well logs and application curves are not combined in one view; read them with one form.'
    for mixed in (mixed_new, mixed_old):
        with pytest.raises(Refused) as caught: mixed.to_numpy()
        assert caught.value.message == sentence
