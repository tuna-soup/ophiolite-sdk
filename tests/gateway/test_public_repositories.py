"""E60 C6, in-process gateway lane: `client.public_repositories` against the real gateway routes with NLOG enabled and
its recorded exchanges replayed (Connectors `tests/fixtures/repositories/nlog`; nothing reaches the network). Search keeps
the service's order, `include` chooses what comes in, the refusals carry the workspace's sentences, and a result
derived from an NLOG file lists NLOG in its attribution."""
import pytest
from test_in_process_publish import web, shared, app, service, client  # noqa: F401 (fixtures)
from ophiolite.errors import PermissionRefused, Unavailable
from ophiolite.public_repositories import RepositoryAdministratorsOnly, RepositoryNotEnabled, RepositoryRateLimited
from ophiolite.writers import WrittenOriginal

HON = ['HON-GT-01', 'HON-GT-01-S1', 'HON-GT-01-S2', 'HON-GT-02']


def enable(monkeypatch, enabled=('nlog',), slow_down=False):
    """The gateway's public repositories with NLOG's recorded answers (with SLOW_DOWN, NLOG answers 429 with an hour to wait)."""
    from asset_connectors.repositories.limiter import Limiter
    from project_gateway import public_repositories
    from asset_connectors.repositories.transport import Response
    from project_gateway.tests.test_public_repositories import Edited
    init = public_repositories.PublicRepositories.__init__

    class Slow:
        sent = []
        def send(self, method, url, body=None, headers=None, limit=0): return Response(429, {'retry-after': '3600'}, b'')

    def replayed(self, runs, entities, **kw):
        init(self, runs, entities, setting={'enabled': list(enabled)}, transport=Slow() if slow_down else Edited(), limiter=Limiter(sleep=lambda s: None, spacing=0),
             sleep=lambda s: None)
    monkeypatch.setattr(public_repositories.PublicRepositories, '__init__', replayed)


@pytest.fixture
def nlog(monkeypatch, request):
    enable(monkeypatch)
    return request.getfixturevalue('web')


def test_search_keeps_the_services_order_and_nothing_is_kept(nlog):
    alice = client(nlog, 'alice', 'delegate')
    rows = alice.public_repositories.search('nlog', name='HON-GT')
    assert [r['code'] for r in rows] == HON
    assert not any(r['in_project'] for r in rows)
    assert [e.name for e in alice.entities()] == []
    services = alice.public_repositories.catalogue()['services']
    assert [s['service'] for s in services] == ['nlog'] and 'tops' in services[0]['include']


def test_include_tops_brings_in_tops_only(nlog):
    alice = client(nlog, 'alice', 'delegate')
    preview = alice.public_repositories.preview('nlog', ['HON-GT-02'])
    assert [i['code'] for i in preview] == ['HON-GT-02'] and preview[0]['tops']
    report = alice.public_repositories.bring_in('nlog', ['HON-GT-02'], include=['tops'], audience=['alice'], command_id='c6-tops')
    assert report.ok and report.not_read == [] and report.state == 'closed', report.text()
    assert [(r['kind'], r['result']) for r in report.rows()] == [('Well tops (CSV)', 'Added')]
    assert [i['path'].split('/')[0] for i in report.items] == ['HON-GT-02']
    assert [e.name for e in alice.entities()] == ['HON-GT-02']  # the well is named by NLOG's own code
    assert alice.public_repositories.search('nlog', name='HON-GT-02')[0]['in_project'] is True
    check = alice.public_repositories.check('nlog')
    assert check['sentence'] == 'Nothing has changed at NLOG.' and [f['state'] for f in check['files']] == ['unchanged']


def test_only_an_administrator_brings_data_in(nlog):
    bob = client(nlog, 'bob', 'delegate')
    with pytest.raises(RepositoryAdministratorsOnly) as refused:
        bob.public_repositories.bring_in('nlog', ['HON-GT-02'], include=['tops'], audience=[])
    assert str(refused.value) == 'Only a project administrator can add data from NLOG.'


def test_a_repository_that_is_not_switched_on_says_so(monkeypatch, request):
    enable(monkeypatch, enabled=())
    alice = client(request.getfixturevalue('web'), 'alice', 'delegate')
    for call in (lambda r: r.search('nlog', name='HON-GT'), lambda r: r.bring_in('nlog', ['HON-GT-02'], include=['tops'], audience=['alice'])):
        with pytest.raises(RepositoryNotEnabled) as refused: call(alice.public_repositories)
        assert str(refused.value) == 'NLOG is not switched on for this Ophiolite installation. Ask the person who runs it to allow NLOG.'
        assert refused.value.server_message == 'This public repository is not enabled on this deployment.'


def test_a_rate_limited_search_says_slow_down(monkeypatch, request):
    enable(monkeypatch, slow_down=True)
    alice = client(request.getfixturevalue('web'), 'alice', 'delegate')
    with pytest.raises(RepositoryRateLimited) as refused: alice.public_repositories.search('nlog', name='HON-GT')
    assert str(refused.value) == 'NLOG asked Ophiolite to slow down. Search again later.' and refused.value.status == 503


def test_a_result_derived_from_an_nlog_log_lists_nlog_in_its_attribution(nlog):
    from project_gateway.tests.test_derivation_readback import PROFILES
    alice, bob = client(nlog, 'alice', 'delegate'), client(nlog, 'bob', 'delegate')
    alice.public_repositories.bring_in('nlog', ['HON-GT-02'], include=['logs'], audience=['bob'], command_id='c6-logs')
    [(asset, revision)] = nlog.a.journal.db.execute("SELECT asset_id,revision FROM repository_copies WHERE code='HON-GT-02' AND kind='log'").fetchall()
    raw, declared = PROFILES['points-csv/1']
    receipt = alice.publish_derived(WrittenOriginal(raw, 'points-csv/1', declared or {}), name='From NLOG', from_=[(asset, revision)], command_id='c6-derive',
                                    method={'name': 'Gridded with scipy', 'library': 'scipy', 'version': '1.14.1', 'parameters': {'cell': 10}})
    told = alice.public_repositories.attribution(receipt)
    assert told.services == ['nlog'] and [r['document']['retained_revision'] for r in told.records] == [revision]
    assert told.text().startswith('Source: NLOG.NL') and told.lines[0]['terms_url'] == 'https://www.nlog.nl/en/disclaimer'
    plain = alice.publish_derived(WrittenOriginal(raw, 'points-csv/1', declared or {}), name='Mine', from_=[receipt], command_id='c6-plain',
                                  method={'name': 'Copied', 'library': 'none', 'version': '1', 'parameters': {}})
    assert alice.public_repositories.attribution(plain).services == ['nlog']  # the attribution follows the result
    with pytest.raises((PermissionRefused, Unavailable)) as refused: bob.public_repositories.attribution(receipt)  # not shared with bob
    assert 'NLOG' not in str(refused.value)


# --- features from another service (C5c; follow-up C6f) ---------------------------------------------------------------

def enable_features(monkeypatch, incomplete=False):
    """The gateway's public repositories with PDOK switched on and its recorded exchanges replayed (asked with the page size
    the recording used); the one link that was not recorded is answered by the labelled SYNTHETIC terminal page, or, when
    INCOMPLETE, finds the service unreachable (Platform `test_public_repositories_features`, Codex r7 ruling 1)."""
    from asset_connectors.repositories import ogc
    from asset_connectors.repositories.limiter import Limiter
    from project_gateway import public_repositories
    from project_gateway.tests.test_public_repositories import Edited
    from project_gateway.tests.test_public_repositories_features import Hosts, Pdok
    monkeypatch.setattr(ogc.OgcFeatures.__init__, '__defaults__', (2, ogc.CAP))
    init = public_repositories.PublicRepositories.__init__
    transport = Hosts(**{'api.pdok.nl': Pdok(incomplete=incomplete), 'www.nlog.nl': Edited(), 'www.gdngeoservices.nl': Edited()})

    def replayed(self, runs, entities, **kw):
        init(self, runs, entities, setting={'enabled': ['nlog', 'pdok']}, transport=transport, limiter=Limiter(sleep=lambda s: None, spacing=0),
             sleep=lambda s: None)
    monkeypatch.setattr(public_repositories.PublicRepositories, '__init__', replayed)
    return transport


PDOK = 'https://api.pdok.nl/kadaster/brk-bestuurlijke-gebieden/ogc/v1'
PDOK_LICENCE = 'https://creativecommons.org/licenses/by/4.0/deed.nl'


def test_features_import_lands_one_feature_set_with_the_licence_the_service_states(monkeypatch, request):
    enable_features(monkeypatch)
    w = request.getfixturevalue('web')
    alice = client(w, 'alice', 'delegate')
    preview = alice.public_repositories.features_preview(PDOK, 'provinciegebied')
    assert preview['can_bring_in'] is True and preview['licence']['href'] == PDOK_LICENCE
    services = {s['service']: s for s in alice.public_repositories.catalogue()['services']}
    assert services['pdok']['kind'] == 'features' and services['pdok']['boreholes_per_run'] is None
    report = alice.public_repositories.features_import(PDOK, ['provinciegebied'], crs='OGC:CRS84', audience=['alice'], command_id='c6f-pdok')
    assert report.ok and report.state == 'closed', report.text()
    assert [(c['id'], c['count'], c['capped']) for c in report.collections] == [('provinciegebied', 5, False)]  # 4 recorded + 1 synthetic
    assert report.licence['href'] == PDOK_LICENCE and report.licence['where'] == 'landing'
    assert 'Licence: ' + PDOK_LICENCE in report.text()
    assert [e.name for e in alice.entities()] == []  # no well (hard gate A)


def test_a_features_import_that_cannot_be_read_whole_is_refused_in_words(monkeypatch, request):
    from ophiolite.public_repositories import FeaturesNotRead
    enable_features(monkeypatch, incomplete=True)
    alice = client(request.getfixturevalue('web'), 'alice', 'delegate')
    with pytest.raises(FeaturesNotRead) as refused:
        alice.public_repositories.features_import(PDOK, ['provinciegebied'], crs='OGC:CRS84', audience=['alice'])
    assert str(refused.value) == 'The service stopped answering before the whole collection was read. Nothing was read; try again later.'


def test_an_address_that_is_not_approved_and_a_member_who_is_not_an_administrator_are_refused(monkeypatch, request):
    from ophiolite.public_repositories import FeaturesNotApproved
    enable_features(monkeypatch)
    w = request.getfixturevalue('web')
    alice, bob = client(w, 'alice', 'delegate'), client(w, 'bob', 'delegate')
    with pytest.raises(FeaturesNotApproved) as refused: alice.public_repositories.collections('https://elsewhere.example.test/ogc')
    assert str(refused.value).startswith('This address is not approved on this installation.')
    with pytest.raises(RepositoryAdministratorsOnly) as refused:
        bob.public_repositories.features_import(PDOK, ['provinciegebied'], crs='OGC:CRS84', audience=[])
    assert str(refused.value) == 'Only a project administrator can add features from this service.'
