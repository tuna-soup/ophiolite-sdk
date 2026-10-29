"""E112 s0: the step x kind pairs `ophiolite procedures new` can start, and what every other pair says.

The listed pairs are written out here (not read from pairs.json) so that an edit to the list fails this file."""
import copy
import json
import re

import jsonschema
import pytest

from ophiolite import procedure_templates as templates, procedures
from test_procedures_frozen import answer

SIX = ('points', 'mesh', 'grid', 'las', 'well-location', 'wavelet')
ALL_FILES = SIX + ('well-tops', 'deviation', 'fault-sticks', 'model-section', 'time-depth')
LISTED = frozenset([('read', w) for w in ALL_FILES] + [('source', w) for w in ALL_FILES]
                   + [('process', w) for w in ALL_FILES + ('seismic-section',)]
                   + [('send', w) for w in ALL_FILES + ('seismic-section', 'residual')]
                   + [('check', 'well-tops'), ('check', 'deviation')])
WORDS = {'points-csv/1': 'points', 'mesh-text/1': 'mesh', 'esri-ascii-grid/1': 'grid', 'well-tops-csv/1': 'well-tops',
         'deviation-csv/1': 'deviation', 'opendtect-faultsticks/1': 'fault-sticks', 'las2/1': 'las',
         'well-location/1': 'well-location', 'wavelet-text/1': 'wavelet', 'model-section-text/1': 'model-section',
         'seismic-section-text/1': 'seismic-section', 'time-depth-csv/1': 'time-depth', 'well-set/1': 'well-set',
         'well-residual/1': 'residual'}
STEPS = ('read', 'source', 'process', 'send', 'check')


def words(pairs):
    return frozenset((step, templates.word(kind)) for step, kind in pairs)


def test_the_listed_pairs_are_these_49():
    assert len(LISTED) == 49 and words(templates.listed()) == LISTED


def test_every_step_and_kind_is_listed_or_refused_with_a_sentence():
    doc = templates.pairs()
    refused = {(row['step'], templates.word(row['kind'])) for row in doc['refused']}
    assert len(refused) == 21 and refused | LISTED == {(s, w) for s in STEPS for w in WORDS.values()} and not refused & LISTED
    for row in doc['refused']:
        said = row['sentence']
        assert said and said.endswith('.') and len(said) <= 200 and '/' not in said and said == templates.refusal(row['step'], row['kind'])


def test_the_words_and_rules_agree_with_the_packaged_procedure_rules():
    rules = json.loads(templates.RULES.read_text())
    assert {k: v['word'] for k, v in templates.pairs()['kinds'].items()} == WORDS
    assert templates.pairs()['rules_version'] == rules['rules_version'] == procedures.contract().RULES_VERSION
    lists = {'read': 'read_source_kinds', 'source': 'read_source_kinds', 'process': 'process_kinds', 'send': 'send_kinds'}
    for step, kind in templates.listed():
        if step in lists: assert kind in rules[lists[step]], (step, kind)


@pytest.mark.parametrize('step,word,sentence', [
    ('read', 'seismic-section', 'Synthetic sections are made in Ophiolite; they cannot be read from a file.'),
    ('source', 'residual', 'Residual results are made in Ophiolite by the residual procedure; they cannot be read from a file.'),
    ('process', 'residual', 'Residual results have one fixed procedure shape; start from the reference procedure for residuals at wells instead.'),
    ('send', 'well-set', 'Well sets are chosen in Ophiolite; a procedure can use one as an input but cannot read, make or send one.'),
    ('check', 'mesh', 'There is no check template for mesh yet; check templates compare well tops and deviation surveys.'),
])
def test_the_refusal_sentences(step, word, sentence):
    assert templates.refusal(step, word) == sentence


def test_kinds_by_word_or_profile_and_the_default_labels():
    assert templates.resolve_kind('well-tops') == templates.resolve_kind('well-tops-csv/1') == 'well-tops-csv/1'
    assert templates.resolve_kind('nothing') is None and templates.resolve_kind('Well-Tops') is None
    assert templates.refusal('read', 'well-tops') is None and templates.refusal('check', 'well-tops-csv/1') is None
    assert templates.refusal('read', 'deviation') is None  # E112 s1: every listed pair has a start
    assert templates.refusal('process', 'deviation') is None and templates.refusal('process', 'seismic-section') is None  # s1p
    assert templates.default_label('read', 'well-tops-csv/1') == 'Read well tops (CSV)'
    assert templates.default_label('source', 'las2/1') == 'Read LAS 2.0 well log file from a system'


def broken(change):
    doc = copy.deepcopy(json.loads(templates.PAIRS.read_text()))
    change(doc)
    return doc


@pytest.mark.parametrize('change', [
    lambda d: d.update(rules_version='0.0.1'),
    lambda d: d['kinds'].pop('well-set/1'),
    lambda d: d['kinds']['las2/1'].update(word='points'),
    lambda d: d['listed'].pop(),
    lambda d: d['listed'].append(dict(d['listed'][0])),
    lambda d: d['listed'].append({'step': 'read', 'kind': 'well-set/1'}),
    lambda d: d.update(refused=[r for r in d['refused'] if (r['step'], r['kind']) != ('read', 'well-set/1')],
                       listed=d['listed'] + [{'step': 'read', 'kind': 'well-set/1'}]),
    lambda d: d['refused'][0].update(sentence='Use las2/1 instead.'),
    lambda d: d.update(extra=1),
])
def test_the_loader_refuses_a_list_that_disagrees(change):
    rules = json.loads(templates.RULES.read_text())
    templates._check(broken(lambda d: None), rules)
    with pytest.raises(templates.PairsError): templates._check(broken(change), rules)


def test_the_schema_itself_refuses_extra_keys_and_unknown_steps():
    schema = json.loads(templates.SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    valid = jsonschema.Draft202012Validator(schema)
    assert not list(valid.iter_errors(templates.pairs()))
    for change in (lambda d: d.update(extra=1), lambda d: d['listed'][0].update(extra=1),
                   lambda d: d['refused'][0].update(extra=1), lambda d: d['kinds']['las2/1'].update(extra=1),
                   lambda d: d['listed'][0].update(step='publish'), lambda d: d['refused'][0].update(sentence='')):
        assert list(valid.iter_errors(broken(change))), change


@pytest.mark.parametrize('argv,sentence', [
    (['--step', 'check', '--kind', 'mesh'], 'There is no check template for mesh yet'),
    (['--step', 'read', '--kind', 'nothing'], 'There is no kind called "nothing". Kinds: deviation, fault-sticks'),
    (['--step', 'process', '--kind', 'well-residual/1', '--label', 'Mine'], 'the reference procedure for residuals at wells'),
])
def test_a_pair_without_a_start_exits_2_and_makes_no_folder(tmp_path, monkeypatch, argv, sentence):
    said = answer(tmp_path, ['new', '{tmp}/fresh', *argv], monkeypatch)
    assert said['exit'] == 2 and sentence in said['stderr'] and not said['stdout'] and not (tmp_path / 'fresh').exists()
    said = answer(tmp_path, ['new', '{tmp}/fresh', *argv, '--json'], monkeypatch)
    assert said['exit'] == 2 and sentence in json.loads(said['stdout'])['error']['message'] and not (tmp_path / 'fresh').exists()


LABELS = {'read': 'Read well tops (CSV)', 'source': 'Read well tops (CSV) from a system', 'process': 'Make well tops (CSV)',
          'send': 'Send well tops (CSV)', 'check': 'Check well tops (CSV)'}


@pytest.mark.parametrize('step', [s for s in STEPS if s != 'process'])
@pytest.mark.parametrize('kind', [[], ['--kind', 'well-tops'], ['--kind', 'well-tops-csv/1']])
def test_well_tops_makes_a_working_start_with_a_default_label(tmp_path, monkeypatch, kind, step):
    said = answer(tmp_path, ['new', '{tmp}/fresh', '--step', step, *kind], monkeypatch)
    assert said['exit'] == 0 and said['stdout'].startswith('Created fresh with procedure.json and procedure.py.')
    manifest = json.loads((tmp_path / 'fresh/procedure.json').read_text())
    assert (manifest['label'], manifest['step'], manifest['name']) == (LABELS[step], step, 'fresh') and procedures.validate(tmp_path / 'fresh')['valid']
    assert json.loads((tmp_path / 'fresh/template.json').read_text())['kind'] == 'well-tops-csv/1' and (tmp_path / 'fresh/tests/test_procedure.py').is_file()


def test_procedures_new_keeps_its_positional_form_and_takes_a_kind(tmp_path):
    assert procedures.new(tmp_path / 'tops', 'read', 'Read our tops')['valid']
    assert json.loads((tmp_path / 'tops/procedure.json').read_text())['label'] == 'Read our tops'
    assert procedures.new(tmp_path / 'logs', 'source', kind='las')['valid']
    assert json.loads((tmp_path / 'logs/procedure.json').read_text())['label'] == 'Read LAS 2.0 well log file from a system'
    assert procedures.new(tmp_path / 'shift', 'process', 'Shift tops', kind='well-tops')['valid']  # E112 s1p
    assert json.loads((tmp_path / 'shift/template.json').read_text())['step'] == 'process'
    assert json.loads((tmp_path / 'shift/procedure.json').read_text())['label'] == 'Shift tops'


PROCESS_LABELS = {'points': 'Make point set (CSV)', 'mesh': 'Make triangulated surface (text)', 'grid': 'Make horizon grid (ESRI ASCII)',
                  'las': 'Make LAS 2.0 well log file', 'well-location': 'Make well location (JSON)', 'wavelet': 'Make wavelet (text)',
                  'well-tops': 'Make well tops (CSV)', 'deviation': 'Make deviation survey (CSV)', 'fault-sticks': 'Make fault sticks (OpendTect)',
                  'model-section': 'Make rock model section (text)', 'time-depth': 'Make time-depth table (CSV)', 'seismic-section': 'Make seismic section (text)'}


@pytest.mark.parametrize('word', sorted(PROCESS_LABELS))
def test_process_kinds_make_a_start_from_the_command(tmp_path, monkeypatch, word):
    # E112 s1p (1-M4): every process kind makes a working start from the command, with its default label
    said = answer(tmp_path, ['new', '{tmp}/fresh', '--step', 'process', '--kind', word], monkeypatch)
    assert said['exit'] == 0 and said['stdout'].startswith('Created fresh with procedure.json and procedure.py.')
    manifest = json.loads((tmp_path / 'fresh/procedure.json').read_text())
    assert (manifest['label'], manifest['step'], [i['slot'] for i in manifest['inputs']]) == (PROCESS_LABELS[word], 'process', ['data'])
    assert procedures.validate(tmp_path / 'fresh')['valid'] and (tmp_path / 'fresh/tests/test_procedure.py').is_file()


def test_process_with_no_kind_keeps_e105a_s_start(tmp_path, monkeypatch):
    # ruling 25 Oct: the amendment refuses a process x kind pair; `new --step process` alone is E105a's frozen start
    said = answer(tmp_path, ['new', '{tmp}/fresh', '--step', 'process'], monkeypatch)
    assert said['exit'] == 0 and said['stdout'].startswith('Created fresh with procedure.json and procedure.py.')
    assert sorted(p.name for p in (tmp_path / 'fresh').iterdir()) == ['procedure.json', 'procedure.py']
    manifest = json.loads((tmp_path / 'fresh/procedure.json').read_text())
    assert (manifest['label'], [i['slot'] for i in manifest['inputs']], [o['role'] for o in manifest['outputs']]) == ('Make well tops (CSV)', ['tops'], ['tops'])
    assert 'raise NotImplementedError("Write what this procedure does.")' in (tmp_path / 'fresh/procedure.py').read_text()
    assert procedures.new(tmp_path / 'api', 'process', 'Shift tops')['valid'] and procedures.validate(tmp_path / 'fresh')['valid']


def test_a_label_given_is_kept(tmp_path, monkeypatch):
    said = answer(tmp_path, ['new', '{tmp}/fresh', '--step', 'read', '--kind', 'well-tops', '--label', 'Shift tops'], monkeypatch)
    assert said['exit'] == 0 and json.loads((tmp_path / 'fresh/procedure.json').read_text())['label'] == 'Shift tops'
    assert not re.search(r'[a-z0-9-]+/[0-9]+', said['stdout'].replace(str(tmp_path), ''))
