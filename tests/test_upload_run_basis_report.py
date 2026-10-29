"""E123 S3a C2 (D4): the report prints the basis sentences the server served, after the files and scope sentences, in
the served order and verbatim; a gateway that serves no `basis` (the setting off, a shared reader, an older gateway)
adds no line. The sentences here are ones the SDK could not compose itself (mutation: the line rebuilt from the plan
-> red).

E123 S6 C1: the report lists the served blocks and proposals (`Report.basis`), the conflicts, and under each block or
proposal sentence the files it means. Every view here is a literal the gateway could serve (synthetic paths, D-7)."""
import json

import httpx

from ophiolite import Client, Credential
from ophiolite.upload_runs import BasisBlock, Report

COUNTS = {'waiting': 0, 'reading': 0, 'added': 0, 'already_here': 0, 'needs_decision': 2, 'not_read': 0, 'not_supported': 0, 'cancelled': 0}
BLOCK = 'Two maps, served by the gateway, share coordinate system EPSG:23031.'
PROPOSAL = 'Served: these two outlines say nothing of their basis. Do they share one?'
ITEM = {'state': 'needs-decision', 'sentence': 'Say what the values in this file mean.', 'asset_id': None, 'kind': 'Map features (GeoJSON)', 'role': 'primary', 'read': None}


def view(**extra):
    return {'run_id': 'f' * 64, 'state': 'closed', 'label': 'Finished with files not added', 'folder_name': 'Maps', 'files': 2, 'settings': {}, 'counts': COUNTS,
            'items': [{'path': 'Maps/a.geojson', **ITEM}, {'path': 'Maps/b.geojson', **ITEM}], **extra}


def test_the_basis_sentences_follow_the_scope_sentence_as_served():
    basis = {'grouping': {}, 'sentences': [{'target': 'block-1', 'sentence': BLOCK}, {'target': 'proposal-2', 'sentence': PROPOSAL}]}
    lines = Report(view(scope={'sentence': 'Nothing is gone.'}, basis=basis)).text().splitlines()
    assert lines[1:4] == ['Nothing is gone.', BLOCK, PROPOSAL]
    assert lines[4:] == Report(view()).text().splitlines()[1:]


def test_a_gateway_without_basis_adds_no_line():
    plain = Report(view()).text().splitlines()
    assert len(plain) == 3 and plain[1].startswith('  Maps/a.geojson: ')
    assert Report(view(basis=None)).text().splitlines() == plain
    assert Report(view(basis={'grouping': {}, 'sentences': []})).text().splitlines() == plain


FOUR = 'These 4 files state no basis. Do they share one?'
SEVEN = 'These 7 files share coordinate system EPSG:23031.'
CONFLICT = 'Maps/a.txt states coordinate system EPSG:23031; the answer for its group was EPSG:4326.'


def served(paths=('Maps/a.txt', 'Maps/b.txt'), **extra):
    """A whole UploadRun view (the contract's required fields) whose files all need a decision."""
    counts = dict(COUNTS, needs_decision=len(paths))
    items = [{'ordinal': n, 'path': p, 'bytes': 10, 'sha256': '0' * 64, 'role': 'primary', 'state': 'needs-decision', 'kind': 'Petrel points',
              'sentence': 'Say what the values in this file mean.', 'asset_id': None, 'read': None} for n, p in enumerate(paths)]
    return {'run_id': 'f' * 64, 'project_id': 'p', 'state': 'closed', 'label': 'Finished with files not added', 'folder_name': 'Maps',
            'files': len(paths), 'settings': {}, 'counts': counts, 'items': items, **extra}


def grouping(blocks=(), proposals=(), states=None, questions=(), conflicts=()):
    return {'schema': 'ophiolite.basis-groups/1', 'plan': {'members': [], 'blocks': list(blocks), 'proposals': list(proposals), 'singles': []},
            'decisions': [], 'answers': [], 'resolved': {'proposals': dict(states or {}), 'per_member': {}, 'conflicts': list(conflicts), 'questions': list(questions)}}


def block(id, members, stated): return {'id': id, 'state': 'stated', 'members': list(members), 'stated': stated, 'asks': []}


def proposal(id, members): return {'id': id, 'folder': 'Maps', 'members': list(members), 'asks': ['crs'], 'stated': {m: {} for m in members}, 'not_applicable': {}}


def ask(target, item, reason=None): return {'target': target, 'item': item, 'members': [target], 'reason': reason, 'suggested': None}


def said(*pairs): return [{'target': t, 'sentence': s} for t, s in pairs]


TWO_AND_TWO = served(basis={'grouping': grouping(
    blocks=[block('block-z', ['Maps/c.txt', 'Maps/a.txt', 'Maps/b.txt'], {'crs': 'EPSG:23031'}),
            block('block-a', ['Maps/f.txt', 'Maps/e.txt'], {'units.xy': 'm', 'crs': 'EPSG:4326'})],
    proposals=[proposal('proposal-z', ['Maps/h.txt', 'Maps/g.txt']), proposal('proposal-a', ['Maps/k.txt', 'Maps/j.txt'])],
    states={'proposal-z': 'proposed', 'proposal-a': 'declined'},
    questions=[ask('block-a', 'vertical_datum'), ask('Maps/k.txt', 'crs')]),
    'sentences': said(('proposal-z', 'These 2 files state no basis. Do they share one?'), ('block-a', 'These 2 files share map unit m.'))})

REFUSED = served(basis={'grouping': grouping(
    proposals=[proposal('proposal-1', ['Maps/a.txt', 'Maps/b.txt', 'Maps/c.txt'])], states={'proposal-1': 'confirmed'},
    questions=[ask('proposal-1', 'vertical_datum'), ask('Maps/b.txt', 'crs', 'This file takes only EPSG:23031 for coordinate system.'),
               ask('Maps/z.txt', 'units.xy'), ask('Maps/c.txt', 'vertical_datum')]), 'sentences': []})

DECLINED = served(basis={'grouping': grouping(
    proposals=[proposal('proposal-1', ['Maps/a.txt', 'Maps/b.txt', 'Maps/c.txt'])], states={'proposal-1': 'declined'},
    questions=[ask('Maps/a.txt', 'crs'), ask('Maps/a.txt', 'units.xy'), ask('Maps/b.txt', 'crs'), ask('Maps/z.txt', 'units.z'), ask('Maps/c.txt', 'vertical_datum')]),
    'sentences': []})

UNKNOWN = served(future={'anything': 1}, basis={'grouping': {**grouping(
    blocks=[block('block-1', ['Maps/a.txt', 'Maps/b.txt'], {'units.velocity': 'm/s', 'crs': 'EPSG:23031'})],
    questions=[ask('block-1', 'units.velocity')],
    conflicts=[{'path': 'Maps/a.txt', 'item': 'units.velocity', 'stated': 'm/s', 'answered': 'ft/s'}]), 'future': True}, 'sentences': []})

UNRESOLVED = served(basis={'grouping': {**grouping(proposals=[proposal('proposal-1', ['Maps/a.txt', 'Maps/b.txt'])]), 'resolved': None},
                           'sentences': said(('proposal-1', 'These 2 files state no basis. Do they share one?'))})

WITH_CONFLICT = served(basis={'grouping': grouping(
    blocks=[block('block-1', ['Maps/a.txt', 'Maps/b.txt'], {'crs': 'EPSG:4326'})],
    conflicts=[{'path': 'Maps/a.txt', 'item': 'crs', 'stated': 'EPSG:23031', 'answered': 'EPSG:4326'}]), 'sentences': []})


def test_blocks_then_proposals_each_in_served_order_with_their_files_in_served_order():
    assert Report(TWO_AND_TWO).basis == (
        BasisBlock('block-z', 'block', 'stated', ('Maps/c.txt', 'Maps/a.txt', 'Maps/b.txt'), {'coordinate system': 'EPSG:23031'}, (), ''),
        BasisBlock('block-a', 'block', 'stated', ('Maps/f.txt', 'Maps/e.txt'), {'map unit': 'm', 'coordinate system': 'EPSG:4326'},
                   ('vertical datum',), 'These 2 files share map unit m.'),
        BasisBlock('proposal-z', 'proposal', 'proposed', ('Maps/h.txt', 'Maps/g.txt'), {}, (), 'These 2 files state no basis. Do they share one?'),
        BasisBlock('proposal-a', 'proposal', 'declined', ('Maps/k.txt', 'Maps/j.txt'), {}, ('coordinate system',), ''))


def test_a_confirmed_proposal_keeps_open_what_one_of_its_files_refused():
    (group,) = Report(REFUSED).basis
    assert (group.state, group.open, group.sentence) == ('confirmed', ('vertical datum', 'coordinate system'), '')


def test_a_declined_proposal_lists_its_files_open_items_once_and_no_others():
    assert Report(DECLINED).basis[0].open == ('coordinate system', 'map unit', 'vertical datum')


def test_a_view_without_a_grouping_lists_nothing_and_unknown_items_pass_through():
    for v in (served(), served(basis=None), served(basis={'sentences': []}), served(basis={'grouping': None, 'sentences': []})):
        assert (Report(v).basis, Report(v).conflicts) == ((), ())
    (group,) = Report(UNRESOLVED).basis
    assert (group.kind, group.state, group.open) == ('proposal', 'proposed', ())
    report = Report(UNKNOWN)
    (group,) = report.basis
    assert (group.stated, group.open) == ({'units.velocity': 'm/s', 'coordinate system': 'EPSG:23031'}, ('units.velocity',))
    assert report.conflicts == (('Maps/a.txt', 'units.velocity', 'm/s', 'ft/s'),)
    before = json.dumps(report.view, sort_keys=True)
    group.stated['coordinate system'] = 'EPSG:4326'
    assert json.dumps(report.view, sort_keys=True) == before and report.basis[0].stated['coordinate system'] == 'EPSG:23031'


def test_the_text_names_each_groups_files_under_its_sentence():
    # the text before this slice, frozen from the S3a SDK's output (not computed by the code under test)
    assert Report(served()).text() == ('Maps - 2 files - Finished with files not added. 0 Added, 0 Already here, 2 Needs your decision, 0 Not read, 0 Not supported\n'
                                       '  Maps/a.txt: Needs your decision - Say what the values in this file mean.\n'
                                       '  Maps/b.txt: Needs your decision - Say what the values in this file mean.')
    four = ['Maps/d.txt', 'Maps/a.txt', 'Maps/c.txt', 'Maps/b.txt']
    lines = Report(served(four, basis={'grouping': grouping(proposals=[proposal('proposal-1', four)], states={'proposal-1': 'proposed'}),
                                       'sentences': said(('proposal-1', FOUR))})).text().splitlines()
    assert lines[1:3] == [FOUR, '    Maps/d.txt, Maps/a.txt, Maps/c.txt and Maps/b.txt'] and lines[3] == '  Maps/d.txt: Needs your decision - Say what the values in this file mean.'
    seven = ['Maps/%s.txt' % n for n in 'gfedcba']
    lines = Report(served(seven, basis={'grouping': grouping(blocks=[block('block-1', seven, {'crs': 'EPSG:23031'})]),
                                        'sentences': said(('block-1', SEVEN), ('Maps/a.txt', CONFLICT))})).text().splitlines()
    assert lines[1:4] == [SEVEN, '    Maps/g.txt, Maps/f.txt, Maps/e.txt, Maps/d.txt, Maps/c.txt and 2 more', CONFLICT]
    assert lines[4] == '  Maps/g.txt: Needs your decision - Say what the values in this file mean.'


def test_conflicts_name_the_file_the_item_in_words_and_both_values():
    assert Report(WITH_CONFLICT).conflicts == (('Maps/a.txt', 'coordinate system', 'EPSG:23031', 'EPSG:4326'),)


def test_the_sdk_reads_the_same_groups_from_the_gateways_answer():
    for v in (TWO_AND_TWO, REFUSED, DECLINED, UNKNOWN, UNRESOLVED, WITH_CONFLICT, served()):
        def gateway(request):
            if request.url.path.endswith('capabilities/describe'): return httpx.Response(200, json={'limits': {'upload_bytes': 1 << 30, 'file_bytes': 1 << 30}})
            assert request.url.path.endswith('upload-runs/status')
            return httpx.Response(200, json=v)
        with httpx.Client(transport=httpx.MockTransport(gateway)) as http:
            report = Client('https://gateway.example', 'p', Credential.bearer('k'), http).upload_runs.status('f' * 64)
        assert (report.basis, report.conflicts) == (Report(v).basis, Report(v).conflicts)
