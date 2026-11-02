"""E120 s7: `story.lines(page, states)` puts the root version's outcome lines after the root's own lines (after its
verdict lines), in the Workspace result page's words; without states, or with the root on a later page, the lines are
the frozen ones. The page is the frozen story page; the states are shaped as `outcomes/states` serves them."""
import copy
import json
from pathlib import Path

from ophiolite import story

FIX = Path(__file__).parent / 'fixtures/story'
PAGE = json.loads((FIX / 'story-page.json').read_text())
LINES = (FIX / 'story-lines.txt').read_text().splitlines()


def state(state, line, outcome='o-1', label='Tops within 5 m', version=1, **more):
    return {'outcome_id': outcome, 'label': label, 'version': version, 'state': state, 'reason': None, 'check_id': None, 'line': line,
            'earlier_publications': [], 'earlier_versions': [], **more}


def added(page, states):
    printed = story.lines(page, {'outcomes': states})
    root = next(n for n in page['nodes'] if n['id'] == page['root'])
    at = 1 + len(story.details(root, {}))
    assert printed[:at] + printed[at + len(printed) - len(LINES):] == LINES  # nothing else moved
    return printed[at:at + len(printed) - len(LINES)]


def test_without_states_the_lines_are_the_frozen_ones():
    assert story.lines(PAGE) == story.lines(PAGE, None) == story.lines(PAGE, {'outcomes': []}) == LINES


def test_an_accepted_line_is_the_servers():
    assert added(PAGE, [state('accepted', 'Accepted on 30 October 2026 under Tops within 5 m version 1')]) == [
        '  Accepted on 30 October 2026 under Tops within 5 m version 1']


def test_a_rejected_line_reads_as_the_workspace_words_it_and_its_rows_stay_the_servers():
    rows = 'B1 top 2 is 5.0001 m from the crossing'
    assert added(PAGE, [state('rejected', 'Rejected under Tops within 5 m version 1: ' + rows)]) == [
        '  Fails the outcome "Tops within 5 m", declared at version 1 (a change to its rule makes a new version): ' + rows]


def test_a_not_checked_line_names_its_outcome_and_the_earlier_lines_follow():
    found = state('not_checked', 'Not checked: Not evaluated', earlier_versions=['Accepted under version 1; published before version 2'])
    assert added(PAGE, [found]) == ['  Tops within 5 m: Not checked: Not evaluated', '  Accepted under version 1; published before version 2']


def test_a_claim_reads_delivered_under_its_outcome_and_an_agents_names_its_person():
    page = copy.deepcopy(PAGE)
    root = next(n for n in page['nodes'] if n['id'] == page['root'])
    root['outcomes'] = [{'outcome_id': 'o-1', 'label': 'Tops within 5 m', 'version': 1, 'state': 'confirmed', 'person': 'u-anna', 'agent': 'a-1',
                         'line': 'delivered to Team database, confirmed 30 October 2026', 'by': None},
                        {'outcome_id': 'o-2', 'label': 'Other', 'version': 1, 'state': 'claimed', 'person': 'u-anna', 'agent': None,
                         'line': 'claimed for delivery to Team database; no delivery reported yet', 'by': None}]
    page['display'] = {**(page.get('display') or {}), 'member_names': {**((page.get('display') or {}).get('member_names') or {}), 'u-anna': 'Anna'}}
    printed = story.lines(page, {'outcomes': [state('accepted', 'Accepted on 30 October 2026 under Tops within 5 m version 1'),
                                              state('not_checked', 'Not checked: Not evaluated', outcome='o-2', label='Other')]})
    at = printed.index('  Accepted on 30 October 2026 under Tops within 5 m version 1')
    assert printed[at:at + 4] == ['  Accepted on 30 October 2026 under Tops within 5 m version 1',
                                  '  Delivered as Tops within 5 m version 1: delivered to Team database, confirmed 30 October 2026 (by an agent for Anna).',
                                  '  Other: Not checked: Not evaluated',
                                  '  Delivered as Other version 1: allowed to be delivered; no delivery reported yet.']
    assert 'claimed' not in '\n'.join(printed)


def test_a_root_on_a_later_page_adds_nothing():
    page = copy.deepcopy(PAGE)
    page['nodes'] = [n for n in page['nodes'] if n['id'] != page['root']]
    assert story.lines(page, {'outcomes': [state('accepted', 'Accepted on 30 October 2026 under Tops within 5 m version 1')]}) == story.lines(page)
