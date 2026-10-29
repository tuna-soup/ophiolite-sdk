"""E122 s3b C2: a same-bytes question prints as the server served it, after "Needs your decision - ", in the row and in
the text; a reader the gateway did not show the earlier path gets the sentence without it (the SDK adds nothing). The
SDK never composes the sentence (mutation: the line rebuilt from `reason_code` -> red)."""
from ophiolite.upload_runs import Report

COUNTS = {'waiting': 0, 'reading': 0, 'added': 0, 'already_here': 2, 'needs_decision': 1, 'not_read': 0, 'not_supported': 0, 'cancelled': 0,
          'needs_procedure': 0, 'converting': 0, 'converted': 0}
NAMED = 'Same bytes as `Logs/C.las`. Is this the same file? Confirm it, add it as a new file, or skip it.'
HIDDEN = 'Same bytes as an earlier file of this source. Is this the same file? Confirm it, add it as a new file, or skip it.'


def view(sentence):
    item = {'path': 'Logs/R.las', 'state': 'needs-decision', 'reason_code': 'same-bytes', 'sentence': sentence, 'asset_id': None,
            'kind': 'Well log (LAS)', 'role': 'primary', 'read': None, 'ordinal': 2}
    return {'run_id': 'f' * 64, 'state': 'closed', 'label': 'Needs your decision', 'folder_name': 'Logs', 'files': 3, 'settings': {},
            'counts': COUNTS, 'items': [item]}


def test_the_named_question_prints_as_served():
    report = Report(view(NAMED))
    assert report.rows()[0]['reason'] == NAMED
    assert '  Logs/R.las: Needs your decision - ' + NAMED in report.text().splitlines()


def test_the_questions_are_counted_as_served_and_a_view_without_the_count_reads_0():
    """C3: `changes.proposals`, served by the gateway; an earlier gateway serves no count."""
    changes = {'unchanged': 2, 'changed': 0, 'new': 0, 'sentence': 'Compared with the last send of Petrel export: 2 unchanged, 0 changed, 0 new.'}
    assert Report({**view(NAMED), 'changes': {**changes, 'proposals': 1}}).proposals == 1
    assert Report({**view(NAMED), 'changes': changes}).proposals == 0
    assert Report(view(NAMED)).proposals == 0


def test_the_hidden_question_prints_without_a_path():
    report = Report(view(HIDDEN))
    assert '  Logs/R.las: Needs your decision - ' + HIDDEN in report.text().splitlines()
    assert 'C.las' not in report.text()
