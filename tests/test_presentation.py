"""E104 C2: what was sent or published shows itself in a notebook, with a link back to the Workspace. Literal
expectations; each test names the mutation it catches."""
import importlib.util
from pathlib import Path

import pytest

from ophiolite.exchange import Outcome
from ophiolite.models.api import PublicationReceipt
from ophiolite.presentation import PresentedExchange, PresentedOutcome, PresentedReceipt
from test_repr import visible

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('exchange_fake', HERE / 'helpers/exchange_fake.py')
fake_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(fake_module)
Fake, sha = fake_module.Fake, fake_module.sha

CONTEXT = {'origin': 'https://ws.example', 'project': 'a project', 'family': 'm', 'recipe': None}
URL = 'https://ws.example/project/a%20project/data/m~x%2Fy%3F%23?revision=r%2F1%3F'
SENTENCE = 'Sent Porosity as version 2. Version 1 is kept.'
FACTS, TECHNICAL = {'name': 'Porosity', 'number': 2}, {'asset_id': 'x/y?#', 'revision': 'r/1?', 'command_id': 'c' * 32}
RECEIPT = {'asset_id': 'r' * 64, 'revision': 'b' * 64, 'revision_number': 2, 'profile': 'table/1', 'command_id': 'c-1',
           'derived_from': [{'authority': 'ophiolite', 'key': 'k', 'revision': 'v', 'profile': 'table/1'}], 'method': {'name': 'recomputed'}}
RECEIPT_REPR = ("PublicationReceipt(asset_id='" + 'r' * 64 + "', revision='" + 'b' * 64 + "', revision_number=2, profile='table/1', "
                "derived_from=[Reference(authority='ophiolite', key='k', revision='v', profile='table/1')], "
                "method=MethodRecord(name='recomputed', declared=True, library='', version='', parameters=None, script_sha256=None), command_id='c-1')")
RECEIPT_DUMP = {'asset_id': 'r' * 64, 'revision': 'b' * 64, 'revision_number': 2, 'profile': 'table/1',
                'derived_from': [{'authority': 'ophiolite', 'key': 'k', 'revision': 'v', 'profile': 'table/1'}],
                'method': {'name': 'recomputed', 'declared': True, 'library': '', 'version': '', 'parameters': None, 'script_sha256': None},
                'command_id': 'c-1'}


def outcome(context=CONTEXT, facts=FACTS, sentence=SENTENCE):
    return PresentedOutcome('sent-version', sentence, dict(facts), dict(TECHNICAL), context)


def receipt(context=None):
    plain = PublicationReceipt.model_validate(RECEIPT)
    return PresentedReceipt.present(plain, context)


def test_outcome_shows_name_version_link_copy_and_details():
    raw = outcome()._repr_html_()
    assert '<strong>Porosity</strong><p>Version 2</p>' in raw
    assert '<a href="' + URL + '">Open in Workspace</a>' in raw              # mutation: drawer path /asset/, head revision
    assert '<details><summary>Copy link</summary><input readonly aria-label="Link to this version" value="' + URL + '"></details>' in raw
    assert '<details><summary>Technical details</summary><pre>' in raw
    text = visible(raw)
    assert text == 'Result Porosity Version 2 Open in Workspace Copy link Technical details'   # mutation: details rendered open
    for word in ('x/y?#', 'r/1?', 'c' * 32, 'a project', 'sent-version'):
        assert word not in text


def test_outcome_frozen_to_dict_repr_str():
    o = outcome()
    assert isinstance(o, Outcome)
    assert o.to_dict() == {'outcome': 'sent-version', 'sentence': SENTENCE, 'facts': FACTS, 'technical': TECHNICAL}  # mutation: context in to_dict
    assert repr(o) == "Outcome('sent-version', 'Sent Porosity as version 2. Version 1 is kept.')"                    # mutation: own __repr__
    assert str(o) == SENTENCE


def test_plain_outcome_has_no_rich_output():
    assert not hasattr(Outcome('sent-version', SENTENCE, FACTS, TECHNICAL), '_repr_html_')


def test_no_context_no_link():
    for raw in (outcome(context=None)._repr_html_(), receipt()._repr_html_()):
        assert '<a' not in raw and '<input' not in raw and 'Technical details' in raw


def test_name_escaped():
    raw = outcome(facts={'name': 'Rock & "Sand"', 'number': 2})._repr_html_()  # passes _human ('x' is a contract term)
    assert '<strong>Rock &amp; &quot;Sand&quot;</strong>' in raw             # mutation: name not escaped


def test_technical_json_escaped():
    raw = outcome(sentence='Sent <b>Porosity</b>.')._repr_html_()
    assert '<b>' not in raw and 'Sent &lt;b&gt;Porosity&lt;/b&gt;.' in raw  # mutation: technical JSON not escaped


def test_link_attributes_escaped():
    raw = outcome(context={**CONTEXT, 'origin': 'https://a&b"c.example'})._repr_html_()
    url = 'https://a&amp;b&quot;c.example/project/a%20project/data/m~x%2Fy%3F%23?revision=r%2F1%3F'
    assert '<a href="' + url + '">' in raw                                    # mutation: href not escaped
    assert 'value="' + url + '"></details>' in raw                            # mutation: value not escaped


def test_identifier_shaped_name_falls_back():
    raw = outcome(facts={'name': 'abc' + '0123456789abcdef' * 2, 'number': 2})._repr_html_()
    assert '<strong>an item</strong>' in raw                                  # mutation: skip _human


def test_receipt_frozen_and_private_context():
    r = receipt(CONTEXT | {'recipe': {'name': 'Porosity'}})
    assert isinstance(r, PublicationReceipt)
    assert repr(r) == RECEIPT_REPR                                            # mutation: bare subclass prints its own name
    assert r.model_dump() == RECEIPT_DUMP                                     # mutation: context as an extra
    raw = r._repr_html_()
    url = 'https://ws.example/project/a%20project/data/m~' + 'r' * 64 + '?revision=' + 'b' * 64
    assert '<strong>Porosity</strong><p>Version 2</p><a href="' + url + '">Open in Workspace</a>' in raw
    assert visible(raw) == 'Result Porosity Version 2 Open in Workspace Copy link Technical details'


class Boom:
    def __getattr__(self, name): raise AssertionError('no request while rendering: ' + name)


def test_presented_exchange_send_links_the_sent_version(tmp_path):
    fake = Fake(); fake.add('poro', b'porosity v1', name='Porosity')
    e = PresentedExchange(fake, tmp_path / 'w', origin='https://ws.example', clock=lambda: 1300.0)
    e.get('poro', output=tmp_path / 'o')
    sent = e.send(b'porosity v2', name='Porosity', profile='table/1', how='recomputed', based_on=['poro'], of='poro')
    assert type(sent) is PresentedOutcome and sent.sentence == 'Sent Porosity as version 2. Version 1 is kept.'
    e.transport = Boom(); fake.__class__ = Boom                               # no request while rendering
    raw = sent._repr_html_()
    url = 'https://ws.example/project/p/data/m~' + sent.technical['asset_id'] + '?revision=' + sha(b'porosity v2')
    assert '<a href="' + url + '">Open in Workspace</a>' in raw              # mutation: family a (a Workspace item)


def test_presented_exchange_without_origin_has_no_link(tmp_path):
    fake = Fake(); fake.add('poro', b'porosity v1', name='Porosity')
    e = PresentedExchange(fake, tmp_path / 'w', clock=lambda: 1300.0)
    e.get('poro', output=tmp_path / 'o')
    raw = e.send(b'porosity v2', name='Porosity', profile='table/1', how='recomputed', based_on=['poro'], of='poro')._repr_html_()
    assert '<a' not in raw and '<strong>Porosity</strong><p>Version 2</p>' in raw
