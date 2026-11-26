"""E192 s2 C1: `upload_data(..., made_for=)` and `publish_derived(..., made_for=)` send the exact versions a file was
made for, only when given, checked before anything is sent; such an upload goes in one request; a project whose
release does not record made_for is said in one sentence, every other refusal unchanged. Each test names its mutation."""
import base64
import json

import httpx
import pytest

from ophiolite import Client
from ophiolite.errors import Refused, ValidationFailed
from ophiolite.publish import derive_request, upload_metadata
from ophiolite.writers import WrittenOriginal

DESIGN = ('synthetic-design', 'd' * 64)
MODEL = ('synthetic-model', 'e' * 64)
PARENT = ('synthetic-parent', 'f' * 64)
COMMON = dict(filename='tops.csv', name='Top', attribution='Synthetic test', audience=['alice'], rights_confirmed=True, profile='points-csv/1')
PLAIN = {'project_id': 'p', 'command_id': 'plain', 'filename': 'tops.csv', 'name': 'Top', 'attribution': 'Synthetic test', 'audience': ['alice'],
         'rights_confirmed': True, 'well_notes': '', 'profile': 'points-csv/1'}
WIRE = [{'asset_id': 'synthetic-design', 'revision': 'd' * 64}, {'asset_id': 'synthetic-model', 'revision': 'e' * 64}]
WRITTEN = WrittenOriginal(b'name,md\nTop A,1000\n', 'points-csv/1', {}, 'derived.csv')
METHOD = {'name': 'synthetic'}
UNRECORDED = "This project's release does not record what a version was made for."
SHAPE = 'Name between 1 and 32 exact versions it was made for, each once, none that it was made from.'


class Key:
    kind = 'delegate'
    def headers(self, url, project): return {'Authorization': 'Bearer key'}
    def discovery_headers(self, url): return {'Authorization': 'Bearer key'}


def header(extra):
    return json.loads(base64.b64decode(extra['X-Ophiolite-Upload']))


def client(handler):
    return Client('http://localhost', 'p', Key(), httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_made_for_is_on_the_wire_only_when_given():
    """Mutation: `made_for_field` always returns {'made_for': ...} (the plain request gains a null) → red."""
    value, extra = upload_metadata('p', 'plain', **COMMON)
    assert value == PLAIN and header(extra) == PLAIN
    value, extra = upload_metadata('p', 'plain', made_for=[{'asset_id': DESIGN[0], 'revision': DESIGN[1]}, MODEL], **COMMON)
    assert header(extra) == {**PLAIN, 'made_for': WIRE}
    body, extra = derive_request('p', WRITTEN, name='Shifted', from_=[PARENT], method=METHOD, command_id='c1')
    assert 'made_for' not in body and 'made_for' not in header(extra)
    body, extra = derive_request('p', WRITTEN, name='Shifted', from_=[PARENT], method=METHOD, command_id='c1', made_for=[DESIGN, list(MODEL)])
    assert header(extra)['made_for'] == WIRE and header(extra)['derived_from'] == [{'asset_id': 'synthetic-parent', 'revision': 'f' * 64}]


@pytest.mark.parametrize('made_for', [
    [],                                                                       # none
    [('synthetic-%d' % i, '%064x' % i) for i in range(33)],                   # 33
    [{'asset_id': DESIGN[0], 'revision': DESIGN[1]}, DESIGN],                 # the same version as dict and tuple
    [(DESIGN[0], 'D' * 64)],                                                  # not a revision
    [(DESIGN[0], 'd' * 63)],
    [{'asset_id': DESIGN[0], 'revision': DESIGN[1], 'name': 'Design'}],       # an extra key
    [{'asset_id': DESIGN[0]}],
    [('', DESIGN[1])],
    ['synthetic-design'],                                                     # a name, not a version
    'synthetic-design',
    [(DESIGN[0], DESIGN[1], 'x')],
])
def test_a_malformed_made_for_is_refused_before_anything_is_sent(made_for):
    """Mutation: each check of `made_for_field` removed in turn (bounds, distinct, keys, revision pattern) → red."""
    with pytest.raises(ValidationFailed) as refused: upload_metadata('p', 'plain', made_for=made_for, **COMMON)
    assert refused.value.args[0] == [SHAPE] or SHAPE in str(refused.value)
    with pytest.raises(ValidationFailed): derive_request('p', WRITTEN, name='Shifted', from_=[PARENT], method=METHOD, command_id='c1', made_for=made_for)


def test_thirty_two_are_taken():
    many = [('synthetic-%d' % i, '%064x' % i) for i in range(32)]
    assert len(upload_metadata('p', 'plain', made_for=many, **COMMON)[0]['made_for']) == 32


def test_a_parent_is_never_also_what_the_file_was_made_for():
    """Mutation: the overlap with `from_` not checked → the derive is built (s1 would refuse it on the server)."""
    with pytest.raises(ValidationFailed): derive_request('p', WRITTEN, name='Shifted', from_=[PARENT], method=METHOD, command_id='c1', made_for=[DESIGN, PARENT])


def limits(seen, upload_bytes):
    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith('/capabilities/describe'):
            return httpx.Response(200, json={'limits': {'upload_bytes': upload_bytes, 'file_bytes': 64 * 1024 * 1024}})
        return httpx.Response(500, json={'error': 'not expected here'})
    return handler


@pytest.mark.parametrize('as_path', [False, True])
def test_a_file_above_the_single_request_limit_with_made_for_is_refused_without_an_upload_or_session(tmp_path, as_path):
    """A cold capability cache: the limits are read (allowed), then nothing else. Mutation: the guard in `_send` removed
    → `las-uploads/begin` is requested."""
    raw = b'x' * (8 * 1024 * 1024 + 1)
    source = raw
    if as_path: (tmp_path / 'big.csv').write_bytes(raw); source = tmp_path / 'big.csv'
    seen = []
    with client(limits(seen, 8 * 1024 * 1024)) as c:
        with pytest.raises(Refused) as refused:
            c.upload_data(source, made_for=[DESIGN], command_id='c1', **{k: v for k, v in COMMON.items() if k != 'filename'})
    assert str(refused.value) == 'A file sent with what it was made for goes in one request, up to 8 MB.'
    assert [p.rsplit('/', 2)[-2:] for p in seen] == [['capabilities', 'describe']]


@pytest.mark.parametrize('as_path', [False, True])
def test_a_file_at_the_served_limit_goes_in_one_request(tmp_path, as_path):
    """The other side of the boundary: a served limit above SINGLE takes the file in one request with its made_for."""
    raw = b'x' * (8 * 1024 * 1024 + 1)
    source = raw
    if as_path: (tmp_path / 'big.csv').write_bytes(raw); source = tmp_path / 'big.csv'
    seen, uploads = [], []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith('/capabilities/describe'):
            return httpx.Response(200, json={'limits': {'upload_bytes': len(raw), 'file_bytes': 64 * 1024 * 1024}})
        uploads.append(json.loads(base64.b64decode(request.headers['x-ophiolite-upload'])))
        return httpx.Response(400, json={'error': 'Synthetic stop.', 'code': 'INVALID_ARGUMENT'})
    with client(handler) as c:
        with pytest.raises(Refused): c.upload_data(source, made_for=[DESIGN], command_id='c1', **{k: v for k, v in COMMON.items() if k != 'filename'})
    assert seen[-1].endswith('/las-uploads/upload') and uploads[0]['made_for'] == WIRE[:1]


def refusing(body):
    def handler(request):
        if request.url.path.endswith('/capabilities/describe'):
            return httpx.Response(200, json={'limits': {'upload_bytes': 1024, 'file_bytes': 1024}})
        return httpx.Response(400, json=body)
    return handler


STUB = {'error': 'This deployment cannot record what this file was made for yet.', 'code': 'INVALID_ARGUMENT',
        'reason': 'made-for-not-recorded', 'field': 'made_for'}
BEFORE = {'error': 'Invalid request fields: made_for', 'code': 'INVALID_ARGUMENT'}
OTHER = {'error': 'Invalid request fields: made_for.0.revision', 'code': 'INVALID_ARGUMENT'}


@pytest.mark.parametrize('call', ['upload', 'derive'])
def test_a_release_that_does_not_record_made_for_is_said_in_one_sentence(call):
    """E192 s0's stub reason and the unknown field of a release before s0. Mutation: `made_for_refused` returns the
    error unchanged → the server's own words."""
    for body in (STUB, BEFORE):
        with client(refusing(body)) as c, pytest.raises(Refused) as refused:
            if call == 'upload': c.upload_data(b'name,md\n', made_for=[DESIGN], command_id='c1', **{k: v for k, v in COMMON.items() if k != 'filename'})
            else: c.publish_derived(WRITTEN, name='Shifted', from_=[PARENT], method=METHOD, command_id='c1', made_for=[DESIGN])
        assert str(refused.value) == UNRECORDED and refused.value.status == 400


@pytest.mark.parametrize('call', ['upload', 'derive'])
def test_every_other_refusal_keeps_its_words(call):
    """Mutation: a broad match (any 400, or any sentence naming made_for) → these read as the release sentence. A
    request without made_for keeps the server's words even for the stub's reason."""
    cases = [(OTHER, [DESIGN]), ({'error': 'Synthetic refusal.', 'code': 'INVALID_ARGUMENT'}, [DESIGN]), (STUB, None), (BEFORE, None)]
    for body, made_for in cases:
        with client(refusing(body)) as c, pytest.raises(Refused) as refused:
            if call == 'upload': c.upload_data(b'name,md\n', made_for=made_for, command_id='c1', **{k: v for k, v in COMMON.items() if k != 'filename'})
            else: c.publish_derived(WRITTEN, name='Shifted', from_=[PARENT], method=METHOD, command_id='c1', made_for=made_for)
        assert UNRECORDED not in str(refused.value)


def test_send_again_carries_made_for():
    """Mutation: `made_for` dropped from `publish_again`'s order (or from the recipe) → the line forgets it."""
    from ophiolite.presentation import publication_recipe, publish_again
    recipe = publication_recipe(name='Shifted', from_=[PARENT], method=METHOD, made_for=WIRE)
    line = publish_again(recipe['arguments'], 'synthetic-result', 'a' * 64, 'c2')
    assert line == ("client.publish_derived(new_written, name='Shifted', from_=[['synthetic-parent', '%s']], method={'name': 'synthetic'}, "
                    "made_for=[['synthetic-design', '%s'], ['synthetic-model', '%s']], command_id='c2', new_version_of='synthetic-result', "
                    "expected_parent='%s')" % ('f' * 64, 'd' * 64, 'e' * 64, 'a' * 64))
    plain = publication_recipe(name='Shifted', from_=[PARENT], method=METHOD)
    assert 'made_for' not in plain['arguments']
