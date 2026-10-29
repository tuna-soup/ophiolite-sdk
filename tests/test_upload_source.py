"""E122 s1 C4: `upload(source_name=)` and `ophiolite upload --source NAME` name where the files come from; the report
prints the server's `changes.sentence` as served, and a report without one prints what it printed before. E122 s2 C4:
`send` and `scope` (`--complete`, `--incremental`, `--scope`), the served `scope.sentence`, and resume only the same send.
No server."""
import pytest

from ophiolite import cli
from ophiolite.upload_runs import Report, UploadRuns

COUNTS = {'added': 1, 'already_here': 2, 'needs_decision': 0, 'not_read': 0, 'not_supported': 0, 'cancelled': 0, 'waiting': 0, 'reading': 0}


def view(**extra):
    return {'run_id': 'r', 'state': 'closed', 'label': 'Finished', 'folder_name': 'Survey', 'files': 3, 'counts': COUNTS, 'items': [], **extra}


def test_the_served_sentence_is_printed_as_served():
    """Mutation: the SDK words the counts itself -> this unusual sentence is not printed -> FAIL."""
    said = Report(view(changes={'unchanged': 2, 'changed': 1, 'new': 0, 'sentence': 'Synthetic 5 unchanged'})).text()
    assert said == 'Survey - 3 files - Finished. 1 Added, 2 Already here, 0 Needs your decision, 0 Not read, 0 Not supported\nSynthetic 5 unchanged'


def test_a_report_without_a_source_prints_what_it_printed_before():
    assert Report(view()).text() == 'Survey - 3 files - Finished. 1 Added, 2 Already here, 0 Needs your decision, 0 Not read, 0 Not supported'


def test_the_source_name_goes_into_the_start_request_only_when_given(tmp_path, monkeypatch):
    (tmp_path / 'F').mkdir(); (tmp_path / 'F' / 'a.las').write_bytes(b'~V\n')
    started = []
    runs = UploadRuns.__new__(UploadRuns)
    monkeypatch.setattr(UploadRuns, 'unfinished', lambda self, folder, declared=None: None)
    monkeypatch.setattr(UploadRuns, 'defaults', lambda self, *a: {'attribution': 'x', 'audience': []})
    monkeypatch.setattr(UploadRuns, '_call', lambda self, op, body, model=None: started.append(body) or {'run_id': 'r'})
    monkeypatch.setattr(UploadRuns, 'send', lambda self, run, folder, progress=None: Report(view()))
    runs.upload(tmp_path / 'F', rights_confirmed=True, source_name='Petrel export')
    runs.upload(tmp_path / 'F', rights_confirmed=True)
    assert [b.get('source_name') for b in started] == ['Petrel export', None] and 'source_name' not in started[1]


def test_the_command_line_takes_source():
    args = cli.parser().parse_args(['upload', 'F', '--source', 'Petrel export', '--rights-confirmed'])
    assert args.source_name == 'Petrel export'
    assert cli.parser().parse_args(['upload', 'F']).source_name is None


# --- E122 s2 C4 ------------------------------------------------------------------------------------------------------

SCOPE = {'source_name': 'Petrel export', 'send': 'complete', 'scope': None, 'finished': True, 'gone': 1,
         'gone_files': [{'asset_id': 'a', 'path': 'x.las', 'marked': True}], 'sentence': 'Synthetic: x is gone'}


def test_the_served_gone_sentence_is_printed_as_served_under_the_counts():
    """D7. Mutation M13: the SDK words the gone line itself -> this unusual sentence is not printed -> FAIL."""
    said = Report(view(changes={'unchanged': 2, 'changed': 1, 'new': 0, 'sentence': 'Synthetic 5 unchanged'}, scope=SCOPE)).text()
    assert said.splitlines()[1:] == ['Synthetic 5 unchanged', 'Synthetic: x is gone']
    assert Report(view(scope={**SCOPE, 'send': 'incremental', 'sentence': None})).text() == Report(view()).text()


def test_send_and_scope_go_into_the_start_request_only_when_given(tmp_path, monkeypatch):
    (tmp_path / 'F').mkdir(); (tmp_path / 'F' / 'a.las').write_bytes(b'~V\n')
    started, asked = [], []
    runs = UploadRuns.__new__(UploadRuns)
    monkeypatch.setattr(UploadRuns, 'unfinished', lambda self, folder, declared=None: asked.append(declared))
    monkeypatch.setattr(UploadRuns, 'defaults', lambda self, *a: {'attribution': 'x', 'audience': []})
    monkeypatch.setattr(UploadRuns, '_call', lambda self, op, body, model=None: started.append(body) or {'run_id': 'r'})
    monkeypatch.setattr(UploadRuns, 'send', lambda self, run, folder, progress=None: Report(view()))
    runs.upload(tmp_path / 'F', rights_confirmed=True, source_name='Petrel export', send='complete', scope='wells')
    runs.upload(tmp_path / 'F', rights_confirmed=True, source_name='Petrel export')
    runs.upload(tmp_path / 'F', rights_confirmed=True)
    assert [(b.get('send'), b.get('scope')) for b in started] == [('complete', 'wells'), (None, None), (None, None)]
    assert 'send' not in started[1] and 'scope' not in started[1]
    assert asked == [('Petrel export', 'complete', 'wells'), ('Petrel export', 'incremental', None), None]


@pytest.mark.parametrize('argv', [['--complete'], ['--incremental'], ['--scope', 'wells'], ['--complete', '--scope', 'wells']])
def test_complete_incremental_or_scope_without_a_source_is_a_usage_error_before_any_request(argv, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_upload', lambda *a: pytest.fail('a request was prepared'))
    with pytest.raises(SystemExit) as e: cli.main(['upload', 'F', '--rights-confirmed', *argv])
    assert e.value.code == 2 and '--complete, --incremental and --scope go with --source NAME' in capsys.readouterr().err


def test_the_command_line_takes_complete_incremental_and_scope():
    args = cli.parser().parse_args(['upload', 'F', '--source', 'S', '--complete', '--scope', 'wells/las', '--rights-confirmed'])
    assert (args.source_name, args.send, args.scope) == ('S', 'complete', 'wells/las')
    assert cli.parser().parse_args(['upload', 'F', '--source', 'S', '--incremental']).send == 'incremental'
    assert cli.parser().parse_args(['upload', 'F']).send is None
    with pytest.raises(SystemExit): cli.parser().parse_args(['upload', 'F', '--source', 'S', '--complete', '--incremental'])
    assert 'not marked gone' in cli.parser()._subparsers._group_actions[0].choices['upload'].format_help()


LISTING = [{'path': 'a.las', 'bytes': 3, 'sha256': 'f' * 64}]
QUESTION = {'state': 'needs-decision', 'role': 'primary'}


def runs_with(state, block, items=None):
    """An UploadRuns whose one run of folder F is in `state`, its view carrying `block` as `scope` (None: unnamed)."""
    runs = UploadRuns.__new__(UploadRuns)
    rows = [{**f, **(items or {'state': 'added', 'role': 'primary'})} for f in LISTING]
    seen = {'run_id': 'r1', 'state': state, 'label': 'x', 'folder_name': 'F', 'files': 1, 'counts': COUNTS, 'items': rows,
            **({'scope': block} if block else {})}
    runs.list = lambda: [{'run_id': 'r1', 'state': state, 'folder_name': 'F'}]
    runs.status = lambda run_id: Report(seen)
    return runs


class Folder:
    name = 'F'
    def listing(self): return LISTING


NAMED = {'source_name': 'Petrel export', 'send': 'complete', 'scope': None}


@pytest.mark.parametrize('state,items', [('open', None), ('closed', QUESTION)])
@pytest.mark.parametrize('block,declared,resumes', [
    (NAMED, ('Petrel export', 'complete', None), True),
    (NAMED, ('Other export', 'complete', None), False),
    (NAMED, ('Petrel export', 'incremental', None), False),
    (NAMED, ('Petrel export', 'complete', 'wells'), False),
    (NAMED, None, False),
    ({**NAMED, 'send': 'incremental'}, ('Petrel export', 'incremental', None), True),
    ({**NAMED, 'scope': 'wells'}, ('Petrel export', 'complete', 'wells'), True),
    (None, ('Petrel export', 'complete', None), False),
    (None, None, True)])
def test_only_the_same_send_resumes_for_open_runs_and_closed_runs_with_a_question(state, items, block, declared, resumes):
    """D7, R2. Mutation M20: resume by listing only -> the differing cases resume -> FAIL."""
    assert UploadRuns.unfinished(runs_with(state, block, items), Folder(), declared) == ('r1' if resumes else None)


def test_a_closed_run_without_a_question_never_resumes():
    assert UploadRuns.unfinished(runs_with('closed', NAMED), Folder(), ('Petrel export', 'complete', None)) is None
