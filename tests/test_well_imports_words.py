"""E42a C6: a well import in words — every skipped row with its reason, the rows located otherwise, and the reason a
paused import gives; a dry run says nothing was kept."""
import pytest

from ophiolite import cli
from ophiolite.errors import Refused, VerificationFailed
from ophiolite.well_imports import CODES, WellImports, words

COUNTS = {'accepted': 2, 'planned': 0, 'created': 1, 'already_here': 1, 'skipped': 12}


def answer(**change):
    skipped = [{'ordinal': i, 'row_key': 'W-%d' % i, 'codes': ['coordinate-missing']} for i in range(10)]
    return {'id': 'i1', 'project_id': 'p', 'state': 'complete-with-skipped', 'words': 'Finished with skipped rows', 'reason': None,
            'initiator': 'alice', 'connection_id': 'sql', 'key': 'w', 'release_id': 'r1', 'approved_by': 'alice', 'approved_at': 1, 'created_at': 1,
            'updated_at': 2, 'counts': COUNTS, 'identity_authority': 'nlog', 'audience': [], 'mapping': {}, 'input_revision': 'v', 'preview_digest': 'd',
            'skipped': skipped, 'possible_duplicates': [], 'already_here': [], 'superseded': [], **change}


def test_words_prefer_the_server_sentence_then_each_code():
    assert words({'reason': 'Location evidence withdrawn or changed', 'codes': ['x']}) == 'Location evidence withdrawn or changed'
    assert words({'codes': ['id-missing', 'not-numeric']}) == 'It has no identifier; a coordinate is not a number'
    assert words({'codes': ['a-new-code']}) == 'A-new-code' and words({'codes': []}) == 'Skipped'
    assert all(text and not text.endswith('.') for text in CODES.values())


def test_a_result_lists_every_listed_row_and_counts_the_rest():
    lines = cli._result(answer()).splitlines()
    assert lines[0] == 'Finished with skipped rows: 1 added, 1 already here, 12 skipped.' and lines[1] == 'Skipped rows:'
    assert lines[2:12] == ['  W-%d: A coordinate is missing' % i for i in range(10)] and lines[12] == '  and 2 more'
    unnamed = cli._result(answer(skipped=[{'ordinal': 4, 'row_key': None, 'codes': ['id-missing']}], counts={**COUNTS, 'skipped': 1}))
    assert unnamed.splitlines()[-1] == '  row 4 (no identifier): It has no identifier'


def test_a_paused_import_gives_its_reason_and_a_finished_one_its_superseded_rows():
    paused = cli._result(answer(state='resumable', words='Ready to resume', reason='Check again: the map feed did not answer', skipped=[]))
    assert paused.splitlines() == ['Ready to resume: 1 added, 1 already here, 12 skipped.', 'Check again: the map feed did not answer']
    assert 'Check again' not in cli._result(answer(reason='Check again: x'))  # a finished import gives no stale reason
    superseded = [{'ordinal': 1, 'row_key': 'W-1', 'well': None, 'reason': 'Located by a newer assertion'}]
    lines = cli._result(answer(skipped=[], counts={**COUNTS, 'skipped': 0}, superseded=superseded)).splitlines()
    assert lines[1:] == ['Located by other evidence:', '  W-1: Located by a newer assertion']


def test_a_dry_run_says_nothing_was_kept():
    review = {'source_name': 'Wells', 'key': 'w', 'counts': {'rows': 3, 'create': 2, 'already_here': 0, 'skipped': 1, 'possible_duplicates': 0},
              'skipped': [{'ordinal': 2, 'row_key': 'W-3', 'codes': ['coordinate-missing']}]}
    assert cli._reviewed(review).splitlines() == ['Dry run, nothing was kept. Wells (w): 3 rows; 2 would be added, 0 already here, 1 skipped, 0 possible duplicates.',
                                                  'Rows that would be skipped:', '  W-3: A coordinate is missing']


class Fake:
    def __init__(self, answers): self.answers, self.sent = list(answers), []
    def _post(self, area, operation, body, **options):
        self.sent.append((area, operation, body)); return self.answers.pop(0)


def test_start_needs_the_reviewed_preview_and_answers_are_checked():
    with pytest.raises(Refused): WellImports(Fake([])).start('sql', 'w', {}, preview_digest='')
    with pytest.raises(VerificationFailed): WellImports(Fake([{'state': 'importing'}])).status('i1')


def test_run_stops_when_paused_and_does_not_step_again():
    paused = answer(state='needs-review', words='Needs review', reason='No longer visible to you, 1 well: W-1', skipped=[], counts={**COUNTS, 'skipped': 0})
    fake = Fake([answer(state='importing', words='Importing', skipped=[], counts={**COUNTS, 'skipped': 0}), paused])
    seen = []
    assert WellImports(fake).run('i1', progress=seen.append) == paused and len(seen) == 2 and [s[1] for s in fake.sent] == ['step', 'step']
