"""E104 C2: what was sent or published shows itself in a notebook, with a link back to the Workspace. Literal
expectations; each test names the mutation it catches."""
import importlib.util
from pathlib import Path

import pytest

from ophiolite.exchange import Outcome
from ophiolite.models.api import PublicationReceipt
from ophiolite.presentation import PresentedExchange, PresentedOutcome, PresentedReceipt, publication_recipe
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
    # E104 C8: text to select, not an input; JupyterLab 4.6.4's sanitizer disables an input in an untrusted output
    assert '<details><summary>Copy link</summary><pre>' + URL + '</pre></details>' in raw
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
    assert '<pre>' + url + '</pre></details>' in raw                          # mutation: copied text not escaped


def test_identifier_shaped_name_falls_back():
    raw = outcome(facts={'name': 'abc' + '0123456789abcdef' * 2, 'number': 2})._repr_html_()
    assert '<strong>an item</strong>' in raw                                  # mutation: skip _human


def test_receipt_frozen_and_private_context():
    r = receipt(CONTEXT | {'recipe': publication_recipe(name='Porosity', from_=[('k', 'v')], method={'name': 'recomputed'})})
    assert isinstance(r, PublicationReceipt)
    assert repr(r) == RECEIPT_REPR                                            # mutation: bare subclass prints its own name
    assert r.model_dump() == RECEIPT_DUMP                                     # mutation: context as an extra
    raw = r._repr_html_()
    url = 'https://ws.example/project/a%20project/data/m~' + 'r' * 64 + '?revision=' + 'b' * 64
    assert '<strong>Porosity</strong><p>Version 2</p><a href="' + url + '">Open in Workspace</a>' in raw
    assert visible(raw) == 'Result Porosity Version 2 Open in Workspace Copy link Send again Technical details'


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


# -- "Send again" for a publication (E104 C3): executed against a recording client; the gateway lane runs it for real --------

class Recording:
    def __init__(self): self.calls = []
    def publish_derived(self, written, **arguments): self.calls.append((written, arguments)); return 'receipt'


def published(**changes):
    arguments = dict(name='Rock & "Sand"', from_=[('k', 'v'), ('k2', 'v2')], method={'name': 'recomputed', 'parameters': {'a': 1}},
                     of_entity={'well': 'W-1'}); arguments.update(changes)
    return receipt(CONTEXT | {'recipe': publication_recipe(**arguments)}), arguments


def receipt_line(r):
    found = re.search(r'<summary>Send again</summary><p>.*?</p><pre>(.*?)</pre>', r._repr_html_(), re.S)
    return _html.unescape(found.group(1)) if found else None


def test_the_publication_line_names_every_argument_and_the_next_version():
    r, _ = published()
    client, scope = Recording(), {}
    text = receipt_line(r)
    exec('result = ' + text, {'client': client, 'new_written': 'NEW'}, scope)
    (written, arguments), = client.calls
    minted = arguments['command_id']
    assert written == 'NEW' and arguments == {'name': 'Rock & "Sand"', 'from_': [['k', 'v'], ['k2', 'v2']],
                                              'method': {'name': 'recomputed', 'parameters': {'a': 1}}, 'of_entity': {'well': 'W-1'},
                                              'command_id': minted, 'new_version_of': 'r' * 64, 'expected_parent': 'b' * 64}
    # mutations: of_entity dropped; expected_parent or new_version_of left out; the receipt's own command id reused
    assert re.fullmatch('[0-9a-f]{32}', minted) and minted != 'c-1'
    assert receipt_line(r) == text                                           # mutation: minted per render
    assert minted not in visible(r._repr_html_())


def test_the_publication_line_is_a_snapshot():
    from_, method, of_entity = [('k', 'v')], {'name': 'recomputed'}, {'well': 'W-1'}
    r, _ = published(from_=from_, method=method, of_entity=of_entity)
    from_.append(('x', 'y')); method['name'] = 'changed'; of_entity['well'] = 'W-2'  # mutation: snapshot by reference
    text = receipt_line(r)
    assert "from_=[['k', 'v']], method={'name': 'recomputed'}, of_entity={'well': 'W-1'}" in text


def test_no_publication_line_for_data_that_is_not_plain():
    r, _ = published(of_entity={'when': float('inf')})
    assert receipt_line(r) is None and 'publish_derived' not in r._repr_html_()


# -- "Run again" (E112 s3): runs and recipes on this computer; the rendered line is executed, never matched as text alone --

import json
import shutil

import ophiolite
from ophiolite import procedures, recipe_runs
from ophiolite.presentation import NO_LINE, PresentedRecipe, PresentedRun
from test_recipe_runs import GRID, RECIPE, SET, SET2, world  # noqa: F401 (s2's fake project, a fixture)

BUNDLE = Path(ophiolite.__file__).resolve().parent / 'contracts/procedures/v1/fixtures/bundles/depth-shift'
SHIFTED = 'name,md\nTop Chalk,1003\nBase Chalk,1202.5\n'  # 1000.5 and 1200 shifted by 2.5 m (7-M5): literals, not the first run's output
RUN_TEXT = 'Result Shift tops by a fixed depth Ran Shift tops by a fixed depth, version 1, on this computer: made Well tops (CSV). Nothing was published.'


def again(result, summary='Run again'):
    found = re.search(r'<summary>' + summary + r'</summary><p>.*?</p><pre>(.*?)</pre>', result._repr_html_(), re.S)
    return _html.unescape(found.group(1)) if found else None


def shifting(tmp_path):
    """The depth-shift bundle in a folder whose name holds a quote, and a tops file with its declarations."""
    folder = shutil.copytree(BUNDLE, tmp_path / "Ann's shift", ignore=shutil.ignore_patterns('__pycache__'))
    (tmp_path / 'in').mkdir()
    (tmp_path / 'in/tops.csv').write_text('name,md\nTop Chalk,1000.5\nBase Chalk,1200\n')
    (tmp_path / 'in/other.csv').write_text('name,md\nTop Chalk,1.0\n')
    (tmp_path / 'in/tops.json').write_text(json.dumps({'depth_unit': 'm', 'depth_basis': 'md'}))
    return folder


def ran(tmp_path):
    folder = shifting(tmp_path)
    inputs, settings = {'tops': [tmp_path / 'in/tops.csv']}, ['shift=2.5']
    result = procedures.run(folder, tmp_path / 'out', inputs, kinds={'tops': 'well-tops-csv/1'}, declared={'tops': tmp_path / 'in/tops.json'},
                            settings=settings)
    inputs['tops'][0] = tmp_path / 'in/other.csv'; settings[0] = 'shift=9'  # the caller's objects change after the call (7-M4)
    return folder, result


def execute(line, output):
    scope = {'procedures': procedures, 'new_output': output}
    exec('result = ' + line, scope)
    return scope['result']


def test_the_run_again_line_runs_the_same_version_on_the_inputs_it_ran_with(tmp_path):
    # mutations: the line built from the caller's live objects (other.csv, shift=9); a path written with %s or '%s' (the quote)
    folder, result = ran(tmp_path)
    line = again(result)
    assert result.again == line  # the notebook's way to the same text
    second = execute(line, tmp_path / 'again')
    assert (tmp_path / 'out/shifted.csv').read_text() == SHIFTED and (tmp_path / 'again/shifted.csv').read_text() == SHIFTED
    assert second['run']['inputs'] == result['run']['inputs'] and second['run']['settings'] == result['run']['settings']
    assert line.startswith('procedures.run(%r, new_output, inputs=' % str(folder.resolve())) and line.endswith(
        ", settings=['shift=2.5'], expected_digest=%r)" % result['run']['procedure']['digest'])


def test_the_run_again_line_refuses_once_the_procedure_changed(tmp_path):
    # mutation: no expected_digest in the line -> the edited procedure runs
    folder, result = ran(tmp_path)
    (folder / 'procedure.py').write_text((folder / 'procedure.py').read_text() + '\n# edited\n')
    with pytest.raises(procedures.NotRun) as error: execute(again(result), tmp_path / 'again')
    assert error.value.code == 'changed-before-run' and not (tmp_path / 'again').exists()


def test_a_run_is_still_its_dict_and_its_card_shows_words_only(tmp_path):
    folder, result = ran(tmp_path)
    plain = json.loads(json.dumps(result))
    assert type(result) is PresentedRun and result == plain and json.dumps(result) == json.dumps(dict(result))
    raw = result._repr_html_()
    assert visible(raw) == RUN_TEXT + ' Run again Technical details'  # mutation: a path, the digest or the raw sentence shown
    for hidden in (result['run']['procedure']['digest'], str(tmp_path), 'well-tops-csv/1', 'shifted.csv'):
        assert hidden not in visible(raw) and hidden in _html.unescape(raw)


def test_a_check_run_reads_project_versions_so_its_card_says_why_there_is_no_line(tmp_path):
    from ophiolite import procedure_templates as templates, writers
    templates.make(tmp_path / 'check', 'check', 'well-tops')
    paths = []
    for name in ('data', 'reference'):
        written = writers.write_tops([{'name': 'NU', 'md': 1203.5}], depth_unit='m', depth_basis='same-as-log')
        (tmp_path / (name + '.csv')).write_bytes(written.bytes)
        paths.append(procedures.ProjectInput(str(tmp_path / (name + '.csv')), 'well-tops-csv/1', written.declared, name + '-item', name[0] * 64))
    result = procedures.run(tmp_path / 'check', tmp_path / 'out', {'data': [paths[0]], 'reference': [paths[1]]})
    raw, text = result._repr_html_(), visible(result._repr_html_())
    assert again(result) is None and NO_LINE['project'] in text and 'version 1, on this computer: passed. Nothing was published.' in text
    assert 'ophiolite checks publish out' not in text and 'ophiolite checks publish out' in raw  # the command: Technical details only


@pytest.mark.parametrize('change, why', [(lambda call: call.update(declared={'tops': object()}), 'plain'),
                                         (lambda call: call.update(settings=['note=' + 'x' * 4096]), 'long'),
                                         (lambda call: None, None)])
def test_a_run_with_an_argument_that_is_not_plain_or_too_long_has_no_line_and_says_why(tmp_path, change, why):
    # mutation: the reason left out (a card with no line and no word why)
    folder, result = ran(tmp_path)
    call = dict(result._call); change(call)
    card = PresentedRun.present(dict(result), call, 'Shift tops by a fixed depth')
    assert (again(card) is None) == (why is not None)
    assert (NO_LINE[why] in visible(card._repr_html_())) if why else not any(s in card._repr_html_() for s in NO_LINE.values())


# recipes: s2's fake project (`world`); the line never carries yes, set_aside or wait (s3-D2)

def recipe(w, **kw):
    inputs = {'selection': SET, 'surface': GRID, 'team_db': str(w.db)}
    result = recipe_runs.run(w, w.recipe, w.work, inputs, **kw)
    inputs['selection'] = SET2  # the caller's dict changes after the call
    return result


def test_a_finished_recipe_runs_again_with_its_inputs_and_asks_again_about_trust(world):
    # mutations: yes carried into the line; the line built from the caller's live dict (SET2)
    result = recipe(world, yes=True)
    line = again(result)
    assert line == 'recipe_runs.run(client, %r, new_work, inputs=%r)' % (str(world.recipe), {'selection': SET, 'surface': GRID, 'team_db': str(world.db)})
    exec(line, {'recipe_runs': recipe_runs, 'client': world, 'new_work': world.tmp / 'again-3'})
    bound = json.loads((world.tmp / 'again-3/journal.json').read_text())['bindings']
    assert bound['selection']['text'] == SET and world.residual_seen[-1]['yes'] is False and len(world.residual_seen) == 2


def test_a_recipe_card_shows_steps_in_words_and_a_line_only_when_finished(world):
    # mutation: the line shown for every recipe state
    doc = json.loads(json.dumps(RECIPE))
    doc['name'] = 'residual-report-2'  # identifier-shaped: not shown
    ids = {'run': 'r-1a', 'publish': 'p-2b', 'states': 's-3c', 'send': 'd-4d'}
    for step in doc['steps']:
        step['id'] = ids[step['id']]
        for value in step['with'].values():
            if isinstance(value, dict) and 'from' in value: value['from'] = ids[value['from']]
    world.recipe.write_text(json.dumps(doc))
    world.residual_plan = ['untrusted']
    failed = recipe(world)
    text = visible(failed._repr_html_())
    assert again(failed) is None and text == ('Result A recipe Stopped at step 1 of 4 (Residual report). Run the same command again to continue. '
                                              '1. Residual report: Needs attention 2. Publish the result: Waiting 3. Outcome states: Waiting '
                                              '4. Deliver: Waiting Technical details')
    for hidden in list(ids.values()) + ['residual-report-2', 'residuals', 'not trusted', 'failed', str(world.work)]:
        assert hidden not in text  # mutation: the step id or kind put in the step line
    world.plan['deliver'] = ['unknown']
    unknown = recipe(world, yes=True)
    assert unknown['state'] == 'unknown' and again(unknown) is None and 'Run the same command again to ask again.' in visible(unknown._repr_html_())
    aside = recipe(world, set_aside='d-4d')
    assert aside['state'] == 'finished' and again(aside) is not None and '4. Deliver: Set aside' in visible(aside._repr_html_())
    assert type(aside) is PresentedRecipe and aside == json.loads(json.dumps(aside))


def test_a_send_card_still_says_send_again(tmp_path):
    _, e = folder(tmp_path)
    assert line(e.send(V2, **ARGS)) is not None  # the summary "Send again" (7-P1)
