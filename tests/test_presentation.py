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
    r = receipt(CONTEXT | {'recipe': {'call': 'publish_derived', 'arguments': {'name': 'Porosity'}}})
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


# -- "Send again" (E104 C3): the rendered line is executed against the fake project, never matched as text alone ----------

import html as _html
import re

from ophiolite import exchange as _exchange

V1, V2, V3, V4 = b'porosity v1', b'porosity v2', b'porosity v3', b'porosity v4'
ARGS = dict(name='Porosity', profile='table/1', how='recomputed', based_on=['poro'], of='poro')


def folder(tmp_path, fake=None):
    fake = fake or Fake()
    if 'poro' not in fake.items: fake.add('poro', V1, name='Porosity')
    e = PresentedExchange(fake, tmp_path / 'w', origin='https://ws.example', clock=lambda: 1300.0)
    e.get('poro', output=tmp_path / 'o')
    return fake, e


def line(result):
    found = re.search(r'<summary>Send again</summary><p>.*?</p><pre>(.*?)</pre>', result._repr_html_(), re.S)
    return _html.unescape(found.group(1)) if found else None


def run(text, e, data):
    scope = {'ex': e, 'new_file': data}
    exec('result = ' + text, scope)
    return scope['result']


def publishes(fake): return [c for c in fake.calls if c[0] == 'publish']


def test_the_line_refuses_once_the_folder_holds_a_newer_version(tmp_path):
    fake, e = folder(tmp_path)
    sent = e.send(V2, **ARGS)                                                # poro version 2
    old = line(sent)
    assert old == ("ex.send(new_file, name='Porosity', profile='table/1', how='recomputed', based_on=['poro'], of='poro', "
                   "expected='%s')" % sha(V2))
    fake.add('poro', V3, name='Porosity', by='Bob Example', at=1250.0); e.get('poro', output=tmp_path / 'o')
    before = len(publishes(fake))
    with pytest.raises(_exchange.REFUSALS['newer-version-exists']):
        run(old, e, V4)                                                      # mutation: line without expected -> version 4 added
    assert len(publishes(fake)) == before


def test_each_result_offers_the_next_version(tmp_path):
    fake, e = folder(tmp_path)
    two = e.send(V2, **ARGS)
    three = run(line(two), e, V3)
    assert (three.outcome, three.facts['number']) == ('sent-version', 3) and publishes(fake)[-1][2] == sha(V2)  # transmitted parent
    four = run(line(three), e, V4)
    assert (four.outcome, four.facts['number']) == ('sent-version', 4) and publishes(fake)[-1][2] == sha(V3)
    assert line(four) == line(three).replace(sha(V3), sha(V4))               # the same shape one version later


def test_a_new_item_line_sends_another_new_item_with_its_declarations(tmp_path):
    fake, e = folder(tmp_path)
    seen = []; publish = fake.publish
    fake.publish = lambda data, request, resolved, command_id: (seen.append(request), publish(data, request, resolved, command_id))[1]
    first = e.send(V2, name='Rock & "Sand"', profile='table/1', how='recomputed', based_on=['poro'], declare={'unit': 'm'}, extra={'k': [1, 2]})
    text = line(first)
    assert 'of=' not in text and 'expected=' not in text and SEND_NEW_TEXT in first._repr_html_()
    assert "<pre>ex.send(new_file, name=&#x27;Rock &amp; &quot;Sand&quot;&#x27;," in first._repr_html_()  # mutation: line not escaped
    again = run(text, e, V3)
    assert again.outcome == 'sent-new' and again.technical['asset_id'] != first.technical['asset_id']
    assert seen[-1]['declare'] == {'unit': 'm'} and seen[-1]['extra'] == {'k': [1, 2]}  # mutation: either dropped
    assert fake.items[again.technical['asset_id']]['name'] == 'Rock & "Sand"'          # quote and ampersand survive


SEND_NEW_TEXT = 'It sends another new item.'


def test_the_line_is_a_snapshot_of_the_call(tmp_path):
    fake, e = folder(tmp_path)
    based_on, declare, extra = ['poro'], {'unit': 'm'}, {'k': [1]}
    sent = e.send(V2, **{**ARGS, 'based_on': based_on, 'declare': declare, 'extra': extra})
    based_on.append('other'); declare['unit'] = 'ft'; extra['k'].append(2)   # mutation: snapshot by reference
    assert line(sent) == ("ex.send(new_file, name='Porosity', profile='table/1', how='recomputed', based_on=['poro'], of='poro', "
                          "declare={'unit': 'm'}, extra={'k': [1]}, expected='%s')" % sha(V2))


@pytest.mark.parametrize('extra', [{'long': 'x' * 4096}, {'when': float('nan')}, {'object': object()}],
                         ids=['over-4096-characters', 'not-finite', 'not-plain-data'])
def test_no_line_when_it_cannot_be_shown_whole(extra):
    o = PresentedOutcome('sent-version', SENTENCE, dict(FACTS), {'asset_id': 'poro', 'revision': 'r'},
                         {**CONTEXT, 'recipe': {'call': 'send', 'arguments': {**ARGS, 'extra': extra}}})
    raw = o._repr_html_()
    assert 'Send again' not in raw and 'ex.send' not in raw and '...' not in raw
