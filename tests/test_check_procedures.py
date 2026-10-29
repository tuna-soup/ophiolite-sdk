"""E110 slice 2 (C5, D7, D9, M5, M7, 2-M5): a check a team's procedure reported, published on purpose from its run folder
with `ophiolite checks publish`, and read back in words. The route answers are written by hand in the shapes of the
Platform's operation models (the Platform's tests/test_check_procedures.py proves the route); the words are literals
from the strategy (row 27, D7). Mutations, each red here: accept counts on a not-compared report (M5), send the
report as an E96 record, word a report as "Checked against"."""
import json

import pytest

from ophiolite import checks
from ophiolite.errors import Refused
from test_cli_checks import Recorded, refusal, run

AT = 1792746000.0  # 23 October 2026 09:00 UTC
DIGEST = 'a' * 64
SUBJECT = {'kind': 'result', 'asset_id': 'tops-1', 'revision': 'r1'}
REFERENCE = {'kind': 'project-version', 'asset_id': 'tops-ref', 'revision': 'r2'}


def report(**changed):
    found = {'kind': 'procedure-report', 'subject': SUBJECT, 'procedure_digest': DIGEST, 'reference': REFERENCE, 'settings': {'tolerance_m': 0.5},
             'outcome': 'differed', 'counts': {'compared': 24, 'differed': 3}}
    found.update(changed)
    return found


def stored(body, **changed):
    """What the server answers for a published report (StoredReport)."""
    found = {'id': 'check-1', 'schema': 'ophiolite.check/1', 'variant': 'procedure-report', 'subject': body['subject'],
             'procedure': {'digest': body['procedure_digest'], 'label': 'Tops vs reference well', 'version_label': None, 'version_number': 2},
             'reference': body['reference'], 'settings': {'tolerance_m': 0.5, 'names': 'folded'}, 'settings_digest': 'b' * 64, 'outcome': body['outcome'],
             'counts': body.get('counts'), 'reason': 'reported_not_compared' if body['outcome'] == 'not_compared' else None, 'witness': 'claimed',
             'recorded_by': {'id': 'marit', 'kind': 'person'}, 'command_id': body['command_id'], 'at': AT}
    found.update(changed)
    return found


def folder(tmp_path, name='run-1', **changed):
    where = tmp_path / name
    where.mkdir()
    (where / 'check.json').write_text(json.dumps(report(**changed)))
    return where


def test_publish_sends_the_report_on_purpose_and_says_ophiolite_did_not_repeat_it(tmp_path):
    folder(tmp_path)
    client = Recorded({'publish': lambda body: stored(body)})
    text, payload = run(client, 'publish', str(tmp_path))
    assert text == 'Published 1 reported check; Ophiolite did not repeat it.'
    (_, op, body, retry), = client.calls
    assert op == 'publish' and retry and 'record' not in body and 'files' not in body  # mutation (send it as an E96 record): red
    assert {k: v for k, v in body.items() if k != 'command_id'} == report() and body['command_id'].startswith('report-')
    assert checks.publish_body(tmp_path / 'run-1')['command_id'] == body['command_id']  # the same folder, the same command (a retry)


def test_the_report_reads_reported_by_with_the_procedure_and_never_checked():
    body = {**report(), 'command_id': 'report-1'}
    lines = checks.record_lines(stored(body), {'marit': 'Anna'})
    assert lines == ['Reported check by Anna with Tops vs reference well version 2: differed.', '3 of 24 differed.', 'Ophiolite did not repeat this check.']
    assert not any('Checked' in line for line in lines)
    malformed = stored(body, procedure={'digest': DIGEST, 'label': 'tops_vs_ref_v2', 'version_label': 'rc_7f3a9b', 'version_number': 2}, counts=None, outcome='passed')
    assert checks.record_lines(malformed, {}) == ['Reported check by a project member with a procedure version 2: passed.', 'Ophiolite did not repeat this check.']
    labelled = stored(body, procedure={'digest': DIGEST, 'label': 'Tops vs reference well', 'version_label': 'Spring release', 'version_number': 2})
    assert checks.record_lines(labelled, {'marit': 'Anna'})[0] == 'Reported check by Anna with Tops vs reference well version Spring release: differed.'


def test_list_words_a_report_beside_e96_records():
    body = {**report(), 'command_id': 'report-1'}
    first, second = stored(body), stored(body, id='check-2', outcome='passed', counts={'compared': 24, 'differed': 0}, at=AT + 60)
    answer = {'records': [first, second], 'groups': [{'key': 'k', 'latest': second, 'earlier': [first], 'disagreement': True}]}
    assert checks.list_lines(answer, {'marit': 'Anna'}) == ['Checks disagree: differed on 23 October 09:00, passed on 23 October 09:01.',
                                                           'Reported check by Anna with Tops vs reference well version 2: passed.', '0 of 24 differed.',
                                                           'Ophiolite did not repeat this check.']


@pytest.mark.parametrize('changed, sentence', [
    ({'counts': {'compared': True, 'differed': 1}}, 'Not published: counts are two whole numbers of at least 0: how many were compared and how many differed.'),
    ({'counts': {'compared': 24, 'differed': -1}}, 'Not published: counts are two whole numbers of at least 0: how many were compared and how many differed.'),
    ({'counts': {'compared': 24.5, 'differed': 3}}, 'Not published: counts are two whole numbers of at least 0: how many were compared and how many differed.'),
    ({'counts': {'compared': 24}}, 'Not published: counts are two whole numbers of at least 0: how many were compared and how many differed.'),
    ({'counts': {'compared': 24, 'differed': 3, 'missing': 1}}, 'Not published: counts are two whole numbers of at least 0: how many were compared and how many differed.'),
    ({'counts': {'compared': 3, 'differed': 4}}, 'Not published: more differed than were compared.'),
    ({'outcome': 'passed', 'counts': {'compared': 24, 'differed': 2}}, 'Not published: none differed exactly when the check passed.'),
    ({'outcome': 'differed', 'counts': {'compared': 24, 'differed': 0}}, 'Not published: none differed exactly when the check passed.'),
    ({'outcome': 'not_compared', 'counts': {'compared': 0, 'differed': 0}}, 'Not published: nothing was compared, so no counts are reported.'),
    ({'outcome': 'checked'}, 'Not published: the outcome must be passed, differed or not compared.'),
    ({'witness': 'server'}, 'Not published: the check folder does not hold a procedure report.'),
])
def test_a_report_the_rules_refuse_is_refused_here_and_nothing_is_sent(tmp_path, changed, sentence):
    folder(tmp_path, **changed)
    client = Recorded({'publish': lambda body: pytest.fail('sent')})
    with pytest.raises(Refused) as refused: run(client, 'publish', str(tmp_path))
    assert str(refused.value) == sentence and client.calls == []  # mutation (accept counts when nothing was compared): sent


def test_counts_the_rules_allow(tmp_path):
    for n, changed in enumerate(({'outcome': 'passed', 'counts': {'compared': 0, 'differed': 0}}, {'outcome': 'not_compared', 'counts': None},
                                 {'outcome': 'differed', 'counts': None})):
        assert checks.report_body(report(**changed))['outcome'] == changed['outcome'], n


def test_a_server_refusal_keeps_the_servers_sentence_for_the_catalogue_and_the_settings(tmp_path):
    folder(tmp_path)
    for field, words in (('kind', 'This check procedure is not in this project.'), ('schema', 'Allowed difference is outside its allowed range.')):
        client = Recorded({'publish': refusal(400, field, words)})
        with pytest.raises(Exception) as refused: run(client, 'publish', str(tmp_path))
        assert str(refused.value) == words and refused.value.details['field'] == field
    client = Recorded({'publish': refusal(403, 'permission')})
    with pytest.raises(Exception) as refused: run(client, 'publish', str(tmp_path))
    assert str(refused.value) == 'Publishing checks needs permission. Ask a project administrator.'


# --- running a check procedure on this computer (C5 run half: D9, M5, M7, 2-M2, 2-M4) --------------------------------
# The project is test_deliver's in-memory stand-in; the check is a real check procedure run in its own child process.
# Mutations, each red here: publish from run (M7), read the head instead of @N (2-M4), copy the child's stdout into
# check.json, accept counts the rules refuse (M5), take a file where the procedure reads a project version (2-M2).

from ophiolite import cli, procedures  # noqa: E402
from ophiolite.exchange import ClientTransport, Exchange  # noqa: E402
from test_deliver import REV1, V1, Project, folder_of  # noqa: E402

PLANTED = 'e110-planted-token-7d4f'
REF, REF_V1 = 'f' * 64, 'name,md\nNU,0\nNM,221.5\nNL,240\n'
CHECK = '''from pathlib import Path

import ophiolite
from ophiolite import procedure


@procedure
def check(inputs, settings, reference):
    print('%s')
    mode = settings['mode']
    if mode == 'dict': return {'outcome': 'passed'}
    if mode == 'too_many': return ophiolite.compared('differed', compared=3, differed=4)
    if mode == 'counted_nothing': return ophiolite.compared('not_compared', compared=0, differed=0)
    rows = lambda path: dict(line.split(',') for line in Path(path).read_text().splitlines()[1:])
    mine, theirs = rows(inputs['data'][0].path), rows(reference.path)
    differed = sum(1 for name, md in mine.items() if theirs.get(name) != md)
    return ophiolite.compared('passed' if differed == 0 else 'differed', compared=len(mine), differed=differed)
''' % PLANTED


def check_manifest(source='version'):
    reference = {'slot': 'reference', 'label': 'Reference tops', 'class': 'reference', 'from': source}
    if source == 'version': reference.update(kinds=['well-tops-csv/1'], cardinality='one')
    return {'schema': 'ophiolite.procedure/1', 'name': 'team/tops-vs-reference' + ('-file' if source == 'file' else ''), 'label': 'Tops vs reference well', 'version': 1,
            'step': 'check', 'inputs': [{'slot': 'data', 'label': 'Tops to check', 'class': 'version', 'kinds': ['well-tops-csv/1'], 'cardinality': 'one'}, reference],
            'outputs': [{'role': 'comparison', 'label': 'Comparison', 'class': 'comparison'}],
            'settings': [{'key': 'mode', 'label': 'What the check does', 'type': 'choice', 'default': 'compare',
                          'choices': [{'value': v, 'label': v.replace('_', ' ')} for v in ('compare', 'dict', 'too_many', 'counted_nothing')]}],
            'entry': 'procedure:check'}


class Counted(Project):
    """test_deliver's project, counting every call; a publication call is never answered."""
    def _post(self, area, operation, body, **options):
        self.calls = getattr(self, 'calls', []) + [(area, operation)]
        return super()._post(area, operation, body, **options)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('OPHIOLITE_PROCEDURE_CACHE', str(tmp_path / 'cache'))
    monkeypatch.chdir(tmp_path)
    w = Counted(tmp_path)
    w.add_item('tops-ref', 'Reference', [(REF, REF_V1)])
    w.folder = folder_of(tmp_path / 'procedures', check_manifest(), CHECK)
    w.digest = w.register(w.folder)
    w.work = tmp_path / '.ophiolite-held'
    return w


def ran(w, *more, items=('data=Tops@1',), reference='Reference@1', name='team/tops-vs-reference'):
    argv = ['procedures', 'run', '--from-project', name, '--output', str(w.root / 'run-1')] + [a for i in items for a in ('--item', i)]
    argv += (['--reference', reference] if reference else []) + list(more)
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out): payload = cli._catalogue(cli.parser().parse_args(argv), w)
    return out.getvalue().strip(), payload


def test_a_run_on_held_v2_checks_v1_exactly_and_publishes_nothing(project):
    w = project
    Exchange(ClientTransport(w), w.work).get('tops-a', output=w.root / 'got')  # this folder holds v2, the head
    before = (w.work / 'held.json').read_bytes()
    text, payload = ran(w)
    assert text == 'Ran Tops vs reference well, version 1, on this computer: differed. Nothing was published; to report it to the project, run: ophiolite checks publish run-1'
    report = json.loads((w.root / 'run-1' / 'check.json').read_text())
    assert report == {'kind': 'procedure-report', 'subject': {'kind': 'result', 'asset_id': 'tops-a', 'revision': REV1}, 'procedure_digest': w.digest,
                      'reference': {'kind': 'project-version', 'asset_id': 'tops-ref', 'revision': REF}, 'settings': {'mode': 'compare'},
                      'outcome': 'differed', 'counts': {'compared': 3, 'differed': 1}}  # v1's three picks, not the head's four (2-M4)
    assert (w.work / 'held.json').read_bytes() == before
    assert not [c for c in w.calls if c[0] == 'checks'] and ('checks', 'publish') not in w.calls  # M7: a run publishes nothing
    assert sorted(p.name for p in (w.root / 'run-1').iterdir()) == ['check.json', 'log.txt', 'run.json']


def test_what_the_code_prints_stays_in_the_log_and_never_reaches_check_json(project):
    w = project
    ran(w)
    assert PLANTED not in (w.root / 'run-1' / 'check.json').read_text() and PLANTED not in (w.root / 'run-1' / 'run.json').read_text()
    assert PLANTED in (w.root / 'run-1' / 'log.txt').read_text()


def test_the_run_folder_is_what_checks_publish_sends(project):
    w = project
    ran(w)
    body = checks.publish_body(w.root / 'run-1')
    assert {k: v for k, v in body.items() if k != 'command_id'} == json.loads((w.root / 'run-1' / 'check.json').read_text())
    assert body['command_id'].startswith('report-')


@pytest.mark.parametrize('mode, sentence', [
    ('too_many', 'Not run: the check returned more differed than were compared.'),
    ('counted_nothing', 'Not run: the check returned nothing was compared, so no counts are reported.'),
    ('dict', 'Not run: a check procedure must return ophiolite.compared(outcome, compared, differed).'),
])
def test_a_return_the_rules_refuse_is_refused_here_and_nothing_is_written(project, mode, sentence, capsys):
    w = project
    with pytest.raises(SystemExit): ran(w, '--setting', 'mode=' + mode)
    assert capsys.readouterr().err.strip() == sentence  # M5
    assert not (w.root / 'run-1').exists() and not [c for c in w.calls if c[0] == 'checks']


def test_the_reference_is_given_as_the_procedure_reads_it(project, tmp_path, capsys):
    w = project
    local = tmp_path / 'ref.csv'
    local.write_text(REF_V1)
    for given in (str(local), 'Reference'):  # a file, or a project version without its number, where it reads a version (2-M2)
        with pytest.raises(SystemExit): ran(w, reference=given)
        assert capsys.readouterr().err.strip() == 'Not run: give the reference as --reference FILE or --reference ITEM@N, as Reference tops reads.'
    with pytest.raises(SystemExit): ran(w, items=('data=Tops@7',))
    assert capsys.readouterr().err.strip() == 'Not run: Tops has no version 7 that you can see.'
    assert not (w.root / 'run-1').exists()


def test_a_file_reference_is_named_by_its_file_and_digest(project, tmp_path):
    w = project
    folder = folder_of(tmp_path / 'file-procedures', check_manifest('file'), CHECK)
    digest = w.register(folder)
    local = tmp_path / 'reference-tops.csv'
    local.write_text(REF_V1)
    ran(w, reference=str(local), name='team/tops-vs-reference-file')
    report = json.loads((w.root / 'run-1' / 'check.json').read_text())
    import hashlib
    assert report['reference'] == {'kind': 'file', 'name': 'reference-tops.csv', 'digest': hashlib.sha256(REF_V1.encode()).hexdigest()}
    assert report['procedure_digest'] == digest and report['counts'] == {'compared': 3, 'differed': 1}


def test_a_check_on_a_file_of_this_computer_is_not_run(project, tmp_path):
    local = tmp_path / 'tops.csv'
    local.write_text(V1)
    with pytest.raises(procedures.NotRun) as refused:
        procedures.run(project.folder, tmp_path / 'run-local', {'data': [str(local)], 'reference': [str(local)]},
                       kinds={'data': 'well-tops-csv/1', 'reference': 'well-tops-csv/1'})
    assert str(refused.value) == 'Not run: a check reports on a project version; give Tops to check with --item SLOT=ITEM[@N].'
    assert not (tmp_path / 'run-local').exists()
