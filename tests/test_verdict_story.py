"""E132 s1 C3 c: `ophiolite story` prints each verdict line under its node, exactly as the server wrote it (a reason
keeps its newline), and an unresolved author as the server words it ("a project member"). The page is the frozen
story page with two verdicts added to its root. Mutation: print the verdict word instead of the line -> red."""
import copy
import json
from pathlib import Path

from ophiolite import story

FIX = Path(__file__).parent / 'fixtures/story'
PAGE = json.loads((FIX / 'story-page.json').read_text())
LINES = (FIX / 'story-lines.txt').read_text().splitlines()
JUDGED = [{'verdict': 'rejected', 'line': 'Rejected by Anna, 29 October 2026: tops differ\nfrom the published log', 'at': 1793275200.0,
           'person': 'u-anna', 'agent': None, 'current': True},
          {'verdict': 'accepted', 'line': 'Accepted by a project member, 29 October 2026', 'at': 1793275260.0,
           'person': 'u-gone', 'agent': None, 'current': True}]


def test_each_verdict_line_is_printed_verbatim_under_its_node():
    page = copy.deepcopy(PAGE)
    root = next(n for n in page['nodes'] if n['id'] == page['root'])
    root['verdicts'] = JUDGED
    printed = story.lines(page)
    before = story.lines(PAGE)
    assert before == LINES
    added = [line for line in printed if line not in before]
    assert added == ['  Rejected by Anna, 29 October 2026: tops differ\nfrom the published log', '  Accepted by a project member, 29 October 2026']
    assert printed.index(added[0]) < printed.index(added[1]) and 'u-gone' not in '\n'.join(printed)


def test_a_story_without_verdicts_prints_what_it_printed():
    page = copy.deepcopy(PAGE)
    for node in page['nodes']: node['verdicts'] = None
    assert story.lines(page) == LINES
