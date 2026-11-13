"""E171 s1 (supervisor ruling of 11 Nov; replaces E70d's deferred gateway test 8): a person's send through the real
gateway and ClientTransport names the folder that sent it, on the derive route and on the upload route alike, and the
project records that folder as holding the version it added (`how='sent'`, in E69's transaction). The read
`exchange/holders` then serves that copy to its person as `you`, with the SDK's application word.

Mutations: `holder` dropped from the request on either route (ClientTransport.publish) -> that case has no `sent`
record; the gateway's append removed (publications.py or las_uploads.held_locked) -> that case has no `sent` record."""
import pytest

from test_exchange import two_keys, both_routes, points, client  # noqa: F401 (fixture)
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from test_access_key_chain import keyed  # noqa: F401


@pytest.mark.parametrize('route', ['derive', 'upload'])
def test_a_send_records_the_sending_folder_as_holding_the_version_it_added(two_keys, route, monkeypatch):
    web, ka, kb, a, b, parent, item, v1 = two_keys
    from project_gateway import held_copies
    # The keyed fixture maps an access key's native token to its owner for the publications' platform only (native
    # authentication does it in a deployment); the read's membership check is given the same mapping.
    monkeypatch.setattr(held_copies, 'reader', lambda platform, project, token, own=held_copies.reader: own(web.a.sources.platform, project, token))
    seen = both_routes(web)
    v = points(3)
    of = item if route == 'derive' else parent
    over = {'rights_confirmed': True} if route == 'upload' else {}
    done = a.send(v.bytes, name='Picked points' if route == 'upload' else 'Porosity points', profile=v.profile, declare=v.declared,
                  how='picked again', based_on=[of], of=of, **over)
    assert done.outcome == 'sent-version', done.sentence
    holder = a._load()['holder_id']
    ((called, header),) = seen
    assert called == route and (header['holder'], header['application']) == (holder, 'script')
    rows = web.a.journal.db.execute("SELECT actor, holder, item, revision, number, how, application FROM held_copy_events "
                                    "WHERE how='sent' AND item=? AND revision=?", (of, done.technical['revision'])).fetchall()
    assert [tuple(r) for r in rows] == [('alice', holder, of, done.technical['revision'], 2, 'sent', 'script')]
    page = client(web, ka)._post('exchange', 'holders', {'item': of})
    (mine,) = [r for r in page['rows'] if r['version']['revision'] == done.technical['revision']]
    assert (mine['person']['shown'], mine['application'], mine['version']['how'], mine['state']) == ('you', 'script', 'sent', 'current')
