"""E147 s2 C3 (strategy E147-s2-export-descriptors D1-D4, C3): `Client.export(citation=)` and `ophiolite export --title`.

The person gives the words; the creators are the persons each selected version's story root names (the captured
production pages, tests/fixtures/story-made-kinds.json, never the synthetic server's labels), the publisher is the
project's organisation from discovery, the licence the files' one open licence or a notice. Every served story page
carries one more readable node, made by dave, and names dave and erin: neither may become a creator (X-9).

    a  creators: the hand list and the boundaries, on the captured pages
    b  an export against the synthetic server: publisher, date, licence, version, the organisation alone (R-3)
    c  refusals: the given keys before any request, no organisation before any data read, discovery unavailable,
       a missing description
    d  the CLI: flags, the uncited line and JSON unchanged, the cited line, codes only with --details or --json
"""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import pytest
from ophiolite import cli, export_citation
from ophiolite.auth import Credential
from ophiolite.bundle import DescriptorRefused, open_bundle
from ophiolite.client import Client
from ophiolite.errors import Refused, Unavailable
from ophiolite.testing import synthetic_server

CAPTURED = json.loads((Path(__file__).parent / 'fixtures/story-made-kinds.json').read_text())
NAMES = dict(CAPTURED['member_names'], dave='Dave Example', erin='Erin Example')
DAVE = {'asset_id': 'other', 'revision': 'f' * 64, 'made': dict(CAPTURED['made']['upload'], by='dave', at='2020-01-01T00:00:00Z')}
ORGANISATIONS = [{'id': 'org-1', 'name': 'First Survey'}, {'id': 'org-2', 'name': 'Synthetic Survey Organisation'},
                 {'id': 'org-3', 'name': 'Third Survey'}]


def made(kind, **changes):
    return dict(CAPTURED['made'][kind], **changes)


def page(asset, revision, made_, names=None):
    """A results/story page at limit=1 as the gateway serves it: the root node, dave's node and the names."""
    return {'schema': 'ophiolite.story/1', 'root': 'n1', 'nodes': [{'asset_id': asset, 'revision': revision, 'made': made_}, DAVE],
            'restricted': False, 'next_cursor': None, 'continue_from': None, 'display': {'member_names': dict(NAMES, **(names or {}))}}


def pages(*mades):
    return [(('a%d' % i, 'r%d' % i), page('a%d' % i, 'r%d' % i, m)) for i, m in enumerate(mades)]


def people(*names): return [{'name': n, 'kind': 'person'} for n in names]


# ---- a. creators ------------------------------------------------------------------------------------------------------

def test_a_the_captured_kinds_give_the_captured_creators():
    for kind, person in CAPTURED['creator'].items():
        found = export_citation.creators(pages(made(kind)), 'Org')
        assert found == (people(NAMES[person]) if person else [{'name': 'Org', 'kind': 'organisation'}]), kind


def test_a_two_versions_are_cited_by_date_and_a_declared_one_adds_no_one():
    found = export_citation.creators(pages(made('upload', at='2026-11-05T09:00:00Z'), made('executed-person', at='2026-11-04T09:00:00Z'),
                                           made('executed-agent'), made('declared')), 'Org')
    assert found == people('Bob Example', 'Carol Example', 'Alice Example')


def test_a_boundaries():
    many = [made('upload', by='p%02d' % n) for n in range(65)]
    names = {'p%02d' % n: 'Person %02d' % n for n in range(65)}
    paged = lambda ms: [(('a%d' % i, 'r'), page('a%d' % i, 'r', m, names)) for i, m in enumerate(ms)]
    assert len(export_citation.creators(paged(many[:64]), 'Org')) == 64
    with pytest.raises(Refused) as refused: export_citation.creators(paged(many), 'Org')
    assert refused.value.message == ('A citation names at most 64 creators; these versions were made by 65 people. Export fewer '
                                     'versions, or export without a title.')
    # one person on two versions appears once, at their earlier date
    assert export_citation.creators(pages(made('upload', at='2026-11-05T10:00:00Z'), made('executed-person', at='2026-11-05T09:00:00Z'),
                                          made('upload', at='2026-11-05T08:00:00Z')), 'Org') == people('Alice Example', 'Bob Example')
    # two ids with one name are two creators
    assert export_citation.creators([(('a', 'r'), page('a', 'r', made('upload'), {'alice': 'Sam'})),
                                     (('b', 'r'), page('b', 'r', made('executed-person'), {'bob': 'Sam'}))], 'Org') == people('Sam', 'Sam')
    # an equal date keeps selection order; no date goes last
    assert export_citation.creators(pages(made('executed-person'), made('upload')), 'Org') == people('Bob Example', 'Alice Example')
    assert export_citation.creators(pages(made('upload', at=None), made('executed-person')), 'Org') == people('Bob Example', 'Alice Example')
    # a departed member is named by the name the answer keeps; an unnamed person is left out, never named by the id
    assert export_citation.creators([(('a', 'r'), page('a', 'r', made('upload'), {'alice': 'Alice (left)'}))], 'Org') == people('Alice (left)')
    unnamed = {k: v for k, v in NAMES.items() if k != 'alice'}
    found = export_citation.creators([(('a', 'r'), dict(page('a', 'r', made('upload')), display={'member_names': unnamed}))], 'Org')
    assert found == [{'name': 'Org', 'kind': 'organisation'}]


# ---- b. an export against the synthetic server -------------------------------------------------------------------------

class Frozen(datetime):
    """2026-11-05 23:30 at UTC-2: the UTC date is 2026-11-06."""
    @classmethod
    def now(cls, tz=None):
        instant = datetime(2026, 11, 6, 1, 30, tzinfo=timezone.utc)
        return instant.astimezone(tz) if tz else instant.astimezone(timezone(timedelta(hours=-2))).replace(tzinfo=None)


CC_BY = {'name': 'Creative Commons Attribution 4.0', 'spdx': 'CC-BY-4.0', 'redistribution': 'allowed', 'attribution': 'required'}
LISTED = {'format': 'osd.manifest/1', 'catalogue_url': 'https://catalogue.example', 'collection_id': 'synthetic--wells',
          'record_id': 'synthetic/well-logs', 'access': 'anonymous', 'asset_key': 'gr.las', 'sha256': '0' * 64, 'licence': CC_BY}


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(export_citation, '_clock', Frozen)
    with citing_server() as server: yield server


@contextmanager
def citing_server():
    """The synthetic server, with discovery (the project in the second of three organisations, on page 2) and the story
    root of its log as the captured executed-person page."""
    with synthetic_server() as server:
        inner, state = server.handler, {'root': made('executed-person'), 'organization_id': 'org-2', 'discovery': 200, 'calls': []}
        d = server.template_descriptor
        def handler(method, path, body, headers):
            route = unquote(urlsplit(path).path); state['calls'].append(route)
            if route == '/api/v1/projects/list':
                if state['discovery'] != 200: return state['discovery'], {'error': 'Service is busy.'}
                if not json.loads(body or b'{}').get('cursor'):
                    return 200, {'projects': [{'id': 'elsewhere', 'name': 'E', 'role': 'member', 'can_administer': False, 'organization_id': 'org-1'}],
                                 'next_cursor': 'two'}
                return 200, {'projects': [{'id': 'p', 'name': 'P', 'role': 'member', 'can_administer': False,
                                           'organization_id': state['organization_id']}], 'next_cursor': None}
            if route == '/api/v1/projects/organizations': return 200, {'organizations': ORGANISATIONS}
            if route.endswith('/entities/list'): return 200, {'entities': [], 'next_cursor': None, 'untransformed': 0}  # no wells to carry
            if route.endswith('/results/story'):
                asked = json.loads(body)
                assert asked['limit'] == 1
                return 200, page(asked['asset_id'], asked['revision'], state['root'])
            return inner(method, path, body, headers)
        server.handler = handler
        server.state = state
        server.selection = [(d['asset_id'], d['revision'], ['GR'])]
        yield server


def alice(server, http=None):
    return Client(server.url, 'p', Credential.bearer('oph_api_alice'), http)


WORDS = {'title': 'Synthetic gamma ray', 'description': 'One synthetic gamma ray log.'}


def test_b_a_cited_export_names_the_maker_the_organisation_the_utc_date_and_a_notice(served, tmp_path):
    with alice(served) as client: opened = client.export(served.selection, tmp_path / 'b', citation=WORDS)
    citation = opened.manifest['citation']
    assert citation == {'schema': 'ophiolite.citation/1', **WORDS, 'published': '2026-11-06', 'creators': people('Bob Example'),
                        'publisher': {'name': 'Synthetic Survey Organisation'}, 'licence': None,
                        'notice': 'No open licence is recorded for every file of this bundle; ask the publisher before reusing it.',
                        'doi': None, 'descriptors': ['ro-crate-metadata.json', 'croissant.json', 'datacite.json']}
    assert opened.manifest['bundle_version'] == '2.15.0' and open_bundle(tmp_path / 'b').unlisted == []
    assert 'version' not in json.loads((tmp_path / 'b/datacite.json').read_text())
    assert served.state['calls'].count('/api/v1/projects/list') == 2  # both discovery pages


def test_b_a_version_is_written_into_all_three_descriptors(served, tmp_path):
    with alice(served) as client: client.export(served.selection, tmp_path / 'b', citation=dict(WORDS, version='1.0.0'))
    load = lambda name: json.loads((tmp_path / 'b' / name).read_text())
    crate = next(n for n in load('ro-crate-metadata.json')['@graph'] if n['@id'] == './')
    assert (crate['version'], load('croissant.json')['version'], load('datacite.json')['version']) == ('1.0.0', '1.0.0', '1.0.0')


def test_b_a_catalogue_file_under_one_open_licence_gives_its_spdx(served, tmp_path):
    served.template_descriptor['acquisition'] = {'kind': 'user-upload', 'filename': 'gr.las', 'attribution': 'Example', 'well_notes': '',
                                                 'identity': 'alice', 'uploaded_at': 1.0, 'rights': 'confirmed', 'listed_in': LISTED}
    with alice(served) as client: opened = client.export(served.selection, tmp_path / 'b', citation=WORDS)
    assert opened.manifest['citation']['licence'] == {'spdx': 'CC-BY-4.0'} and 'notice' not in opened.manifest['citation']


def test_b_with_no_person_the_organisation_is_the_creator(served, tmp_path):
    served.state['root'] = made('declared')
    with alice(served) as client: opened = client.export(served.selection, tmp_path / 'b', citation=WORDS)
    assert opened.manifest['citation']['creators'] == [{'name': 'Synthetic Survey Organisation', 'kind': 'organisation'}]


def test_b_discovery_goes_through_the_client_s_own_transport_and_the_client_stays_usable(served, tmp_path):
    sent = []
    http = httpx.Client(timeout=60, follow_redirects=False, trust_env=False, event_hooks={'request': [lambda r: sent.append(r.url.path)]})
    with alice(served, http) as client:
        client.export(served.selection, tmp_path / 'b', citation=WORDS)
        assert {'/api/v1/projects/list', '/api/v1/projects/organizations'} <= set(sent)
        assert client.read(*served.selection[0]).artifact  # not closed by the export
    http.close()


# ---- c. refusals --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('extra', ['creators', 'licence'])
def test_c_a_given_fact_is_refused_before_any_request(served, tmp_path, extra):
    with alice(served) as client:
        with pytest.raises(Refused) as refused: client.export(served.selection, tmp_path / 'b', citation=dict(WORDS, **{extra: []}))
    assert refused.value.message == export_citation.GIVEN == ('The citation of an export takes title, description and version; the writer '
                                                              'adds creators, publisher, licence and date from the records.')
    assert served.state['calls'] == [] and not (tmp_path / 'b').exists()


def test_c_no_organisation_is_refused_before_any_data_read(served, tmp_path):
    served.state['organization_id'] = None
    with alice(served) as client:
        with pytest.raises(Refused) as refused: client.export(served.selection, tmp_path / 'b', citation=WORDS)
    assert refused.value.message == ('A citation names its publisher: this project is not in an organisation you belong to. '
                                     'Export without a title.')
    assert all(c.startswith('/api/v1/projects/') and '/scientific-assets' not in c and '/results/' not in c for c in served.state['calls'])
    assert not (tmp_path / 'b').exists()


def test_c_discovery_unavailable_raises_unavailable_and_writes_nothing(served, tmp_path):
    served.state['discovery'] = 503
    with alice(served) as client:
        with pytest.raises(Unavailable): client.export(served.selection, tmp_path / 'b', citation=WORDS)
    assert list(tmp_path.iterdir()) == []


def test_c_a_missing_description_is_the_contract_s_citation_schema(served, tmp_path):
    with alice(served) as client:
        with pytest.raises(DescriptorRefused) as refused: client.export(served.selection, tmp_path / 'b', citation={'title': 'T'})
    assert refused.value.code == 'citation-schema' and list(tmp_path.iterdir()) == []


# ---- d. the CLI -------------------------------------------------------------------------------------------------------

def run(served, tmp_path, monkeypatch, capsys, *extra):
    config = tmp_path / 'configuration.json'
    config.write_text(json.dumps({'schema': 'ophiolite.local-configuration/1', 'url': served.url, 'project': 'p'}))
    monkeypatch.setattr(cli.Credential, 'from_file', staticmethod(lambda path: Credential.bearer('oph_api_alice')))
    asset, revision, _ = served.selection[0]
    argv = ['export', '--configuration', str(config), '--asset', asset, '--revision', revision, '--curve', 'GR', '--output', str(tmp_path / 'b'), *extra]
    try: cli.entrypoint(argv); status = 0
    except SystemExit as stop: status = stop.code
    out = capsys.readouterr()
    return status, out.out, out.err


@pytest.mark.parametrize('flags', [['--title', 'T'], ['--description', 'D'], ['--version', '1.0.0']])
def test_d_title_and_description_go_together(served, tmp_path, monkeypatch, capsys, flags):
    status, out, err = run(served, tmp_path, monkeypatch, capsys, *flags)
    assert (status, out) == (1, '') and 'A cited export needs --title and --description together' in err
    assert not (tmp_path / 'b').exists()


def test_d_an_uncited_export_says_what_it_said(served, tmp_path, monkeypatch, capsys):
    status, out, _ = run(served, tmp_path, monkeypatch, capsys)
    assert (status, out) == (0, 'Exported 1 exact revision(s) to %s - check it offline with: ophiolite exchange bundle check %s\n' % (tmp_path / 'b', tmp_path / 'b'))
    (tmp_path / 'j').mkdir()
    status, out, _ = run(served, tmp_path / 'j', monkeypatch, capsys, '--json')
    assert json.loads(out) == {'exported': str(tmp_path / 'j/b'), 'revisions': 1}


def test_d_a_cited_export_says_so(served, tmp_path, monkeypatch, capsys):
    status, out, _ = run(served, tmp_path, monkeypatch, capsys, '--title', 'T', '--description', 'D')
    assert (status, out) == (0, 'Exported 1 exact revision(s) to %s with its citation - check it offline with: ophiolite exchange bundle check %s\n'
                             % (tmp_path / 'b', tmp_path / 'b'))
    served.state['root'] = made('declared'); (tmp_path / 'j').mkdir()
    status, out, _ = run(served, tmp_path / 'j', monkeypatch, capsys, '--title', 'T', '--description', 'D')
    assert out.splitlines()[1] == 'No selected version names a person who made it, so the organisation is the creator.'
    (tmp_path / 'k').mkdir()
    status, out, _ = run(served, tmp_path / 'k', monkeypatch, capsys, '--title', 'T', '--description', 'D', '--json')
    assert json.loads(out) == {'exported': str(tmp_path / 'k/b'), 'revisions': 1, 'cited': True}


def test_d_a_refusal_says_its_sentence_and_its_code_only_when_asked(served, tmp_path, monkeypatch, capsys):
    served.state['organization_id'] = None
    status, out, err = run(served, tmp_path, monkeypatch, capsys, '--title', 'T', '--description', 'D')
    assert status == 1 and 'this project is not in an organisation you belong to' in err and 'citation-publisher' not in err + out
    status, out, err = run(served, tmp_path, monkeypatch, capsys, '--title', 'T', '--description', 'D', '--details')
    assert status == 1 and '  code: citation-publisher' in err
    status, out, err = run(served, tmp_path, monkeypatch, capsys, '--title', 'T', '--description', 'D', '--json')
    assert status == 1 and json.loads(out)['error']['code'] == 'citation-publisher'
