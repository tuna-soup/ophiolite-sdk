"""E122 s3a C2 (D3): the report prints the items sentence the server served, after the files sentence, verbatim; a
gateway that serves no `elements`, or null, adds no line. The sentence here is one the SDK could not compose itself
(mutation: the line rebuilt from the counts -> red)."""
from ophiolite.upload_runs import Report

COUNTS = {'waiting': 0, 'reading': 0, 'added': 1, 'already_here': 0, 'needs_decision': 0, 'not_read': 0, 'not_supported': 0, 'cancelled': 0,
          'needs_procedure': 0, 'converting': 0, 'converted': 0}
FILES = 'Compared with the last send of Petrel export: 0 unchanged, 0 changed, 1 new.'
SERVED = 'Seven items, served by the gateway: 2 unchanged, 1 changed, 4 new.'


def view(**changes):
    return {'run_id': 'f' * 64, 'state': 'closed', 'label': 'Finished', 'folder_name': 'Survey', 'files': 1, 'settings': {}, 'counts': COUNTS,
            'items': [{'path': 'Survey/a.las', 'state': 'added', 'sentence': None, 'asset_id': 'a' * 64, 'kind': 'Well log (LAS)', 'role': 'primary', 'read': None}],
            'changes': {'unchanged': 0, 'changed': 0, 'new': 1, 'sentence': FILES, **changes}}


def lines(report):
    return report.text().splitlines()[1:3]


def test_the_items_sentence_follows_the_files_sentence_as_served():
    served = {'unchanged': 2, 'changed': 1, 'new': 4, 'files': 1, 'sentence': SERVED}
    assert lines(Report(view(elements=served))) == [FILES, SERVED]


def test_a_gateway_without_the_items_adds_no_line():
    assert lines(Report(view())) == [FILES]
    assert lines(Report(view(elements=None))) == [FILES]
