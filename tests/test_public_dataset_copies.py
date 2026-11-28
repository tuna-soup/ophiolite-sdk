"""E212 s1 C5 (T5a-T5e): every copy of an original restored from a public dataset carries its licence and credits. An
export's citation takes the dataset's licence as linked and names its credits in a null licence's notice; a download is
saved with `<file>.NOTICE.txt`, or not at all. The link literals are synthetic (the shape describe answers as
`public_dataset`, ophiolite.public-dataset-link/1). T5f (restored wells carry the credits) is not here: the table import
takes no attribution (logs/c5-stop.md); T5g/T5h (OpendTect) are dropped from this slice."""
import hashlib
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from ophiolite import Client, Credential, client as client_module, export_citation
from ophiolite.errors import Incompatible, Refused

DESCRIPTORS = Path(__file__).resolve().parents[1] / 'ophiolite' / 'contracts' / 'descriptors' / 'v1' / 'descriptors.py'  # the SDK's synced copy
OBJECT_A, OBJECT_B = 'a' * 64, 'b' * 64
LAS = b'~Version\n VERS. 2.0:\n WRAP. NO:\n~Well\n NULL. -999.25:\n~Curve\n DEPT.M:\n GR.gAPI:\n~A\n100 0\n101 30\n'
MEMBER = hashlib.sha256(LAS).hexdigest()


def link(dataset='synthetic-a', spdx=None, statements=('Contains synthetic wells A, used under synthetic terms A.',), obj=OBJECT_A, notice=None):
    source = {'name': 'Synthetic terms A (no SPDX identifier)', 'spdx': spdx, 'url': 'https://example.org/synthetic/terms-a',
              'redistribution': 'allowed', 'attribution': 'required', **({'notice': notice} if notice else {})}
    return {'schema': 'ophiolite.public-dataset-link/1', 'dataset': dataset, 'object_sha256': obj, 'member_sha256': MEMBER,
            'sources': [{'osd_record': 'synthetic/source-a', 'licence': source}],
            'licence': {'spdx': spdx, 'redistribution': 'allowed', 'attribution': 'required', 'share_alike': False},
            'statements': list(statements), 'linked_at': 1764000000.0, 'run': 'run-1'}


class Read:
    def __init__(self, descriptor): self._wire_descriptor = descriptor


def items(*descriptors):
    return [({'asset_id': 'x%d' % n, 'revision': 'r', 'curves': []}, Read(d)) for n, d in enumerate(descriptors)]


LISTED_CC = {'acquisition': {'listed_in': {'licence': {'spdx': 'CC-BY-4.0', 'redistribution': 'allowed', 'share_alike': False}}}}


def contract():
    from ophiolite.bundle import _descriptors_contract
    return _descriptors_contract()


# --- T5a: one linked log: the citation's licence and notice are the link's ------------------------------------------------

def test_one_linked_file_takes_the_links_licence_and_credits():
    open_link = link(spdx='CC-BY-4.0')
    assert export_citation.licences(items({'public_dataset': open_link})) == [open_link['licence']]
    assert export_citation.licence_of(items({'public_dataset': open_link})) == ({'spdx': 'CC-BY-4.0'}, None)
    closed = link()
    licence, notice = export_citation.licence_of(items({'public_dataset': closed}))
    assert licence is None and notice == closed['statements'][0] + ' ' + contract().MIXED  # a licence that is not an open one
    block = export_citation.complete({'title': 'T', 'description': 'D'}, creators=[{'name': 'Org', 'kind': 'organisation'}],
                                     publisher='Org', licence=licence, notice=notice)
    assert export_citation.check(block)['notice'] == notice
    assert export_citation.licence_of(items({})) == (None, contract().UNSTATED)  # no link: as before


# --- T5b: linked and unlinked together: the contract's rule kept, the credits first ----------------------------------------

def test_a_mixed_selection_keeps_the_rule_and_names_the_credits():
    closed = link()
    assert export_citation.licence_of(items({'public_dataset': closed}, LISTED_CC)) == (None, closed['statements'][0] + ' ' + contract().MIXED)
    assert export_citation.licence_of(items({'public_dataset': closed}, {})) == (None, closed['statements'][0] + ' ' + contract().UNSTATED)


# --- T5c: two datasets: both credits, each once ----------------------------------------------------------------------------

def test_two_datasets_give_both_credits_once_each():
    a = link(statements=('Credit A1.', 'Credit A2.'))
    b = link(dataset='synthetic-b', statements=('Credit B.', 'Credit A1.'), obj=OBJECT_B)
    _, notice = export_citation.licence_of(items({'public_dataset': a}, {'public_dataset': b}, {'public_dataset': a}))
    assert notice == 'Credit A1. Credit A2. Credit B. ' + contract().MIXED


def test_credits_over_the_notice_bound_are_refused():
    many = link(statements=tuple('Credit %03d %s.' % (n, 'x' * 280) for n in range(4)))
    with pytest.raises(Refused) as refused:
        export_citation.licence_of(items({'public_dataset': many}))
    assert refused.value.code == 'citation-notice'


# --- T5d: a null SPDX id: no licence, the source's own notice named; the descriptors name no SPDX address -------------------

def test_a_null_spdx_names_the_sources_notice_and_no_spdx_address(monkeypatch):
    stated = link(notice='Synthetic notice: credit the synthetic publisher.')
    licence, notice = export_citation.licence_of(items({'public_dataset': stated}))
    assert licence is None and 'Synthetic notice: credit the synthetic publisher.' in notice
    monkeypatch.setattr(sys, 'dont_write_bytecode', True)  # no __pycache__ in the contract snapshot (sync_contracts --check)
    spec = importlib.util.spec_from_file_location('platform_descriptors', DESCRIPTORS)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert not (DESCRIPTORS.parent / '__pycache__').exists()
    assert module._licence({'licence': {'spdx': None}}) is module.MISSING
    assert module._licence({'licence': None}) is module.MISSING
    assert module._licence({'licence': {'spdx': 'CC-BY-4.0'}}) == module.SPDX + 'CC-BY-4.0'


# --- T5e: a download is saved with its NOTICE, or not at all ---------------------------------------------------------------

def deployment(described):
    """A deployment holding LAS as one revision's original; the LAS describe needs a curve (422 without one)."""
    digest = hashlib.sha256(LAS).hexdigest()

    def handler(request):
        path = request.url.path
        if path.endswith('/representations/artifact'):
            first, last = (int(x) for x in request.headers['range'].removeprefix('bytes=').split('-'))
            part = LAS[first:last + 1]
            return httpx.Response(206, content=part, headers={'content-range': 'bytes %d-%d/%d' % (first, first + len(part) - 1, len(LAS)),
                                                              'x-content-sha256': digest})
        if request.url.params.get('curve') != 'GR': return httpx.Response(422, json={'detail': 'Choose a value curve'})
        return httpx.Response(200, json=described)
    return httpx.MockTransport(handler)


def download(described, tmp_path):
    with httpx.Client(transport=deployment(described)) as http:
        return Client('http://localhost', 'p', Credential.bearer('synthetic-token'), http).download_original('a1', 'r1', tmp_path / 'log.las')


def test_a_linked_download_is_saved_with_its_notice(tmp_path):
    linked = link(spdx='CC-BY-4.0')
    saved = download({'public_dataset': linked}, tmp_path)
    assert saved.read_bytes() == LAS
    notice = (tmp_path / 'log.las.NOTICE.txt').read_text(encoding='utf-8')
    assert notice == export_citation.notice_text(linked)
    assert 'public dataset synthetic-a' in notice and 'Licence: CC-BY-4.0' in notice and linked['statements'][0] in notice and MEMBER in notice
    assert sorted(p.name for p in tmp_path.iterdir()) == ['log.las', 'log.las.NOTICE.txt']


def test_an_unlinked_download_has_no_notice(tmp_path):
    download({}, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['log.las']


WELLS = b'{"rows": []}'  # a kept wells table's original: a profile the scientific routes do not serve


def unserved(refusal):
    """A deployment holding WELLS as one revision's original; its describe refuses with REFUSAL (422)."""
    digest = hashlib.sha256(WELLS).hexdigest()

    def handler(request):
        if request.url.path.endswith('/representations/artifact'):
            return httpx.Response(206, content=WELLS, headers={'content-range': 'bytes 0-%d/%d' % (len(WELLS) - 1, len(WELLS)), 'x-content-sha256': digest})
        return httpx.Response(422, json={'code': 'incompatible-context', 'error': refusal})
    return httpx.MockTransport(handler)


def test_an_original_of_an_unserved_profile_is_saved_without_a_notice(tmp_path):
    """Mutation: the unserved-profile refusal raised again (the kept wells original is not saved)."""
    with httpx.Client(transport=unserved('This scientific route serves registered profiles only')) as http:
        saved = Client('http://localhost', 'p', Credential.bearer('synthetic-token'), http).download_original('a1', 'r1', tmp_path / 'wells.json')
    assert saved.read_bytes() == WELLS and sorted(p.name for p in tmp_path.iterdir()) == ['wells.json']


def test_another_describe_refusal_still_leaves_nothing_saved(tmp_path):
    """Mutation: every 422 of the describe taken as 'no notice' (a refusal of another kind passes silently)."""
    with httpx.Client(transport=unserved('Choose a value curve')) as http, pytest.raises(Incompatible):
        Client('http://localhost', 'p', Credential.bearer('synthetic-token'), http).download_original('a1', 'r1', tmp_path / 'wells.json')
    assert list(tmp_path.iterdir()) == []


def test_a_notice_that_cannot_be_written_leaves_nothing_saved(tmp_path, monkeypatch):
    def full(destination, text): raise OSError(28, 'No space left on device')
    monkeypatch.setattr(client_module, 'save_text', full)
    with pytest.raises(Refused) as refused:
        download({'public_dataset': link()}, tmp_path)
    assert 'was not saved' in str(refused.value)
    assert list(tmp_path.iterdir()) == []
