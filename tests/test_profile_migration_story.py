"""E148 s3 C3 (V1): `ophiolite story` prints "Saved in a newer format from version N." under a moved revision's node and
no `ophiolite.` profile id in its default output; `--json` carries the migration's ids as the server sent them. The page
is the frozen story page with a migration added to its root. Mutation: print the profile id -> the default-output
assertion red."""
import copy
import json
from pathlib import Path

from ophiolite import story
from test_story_client import R, Recorded, run

FIX = Path(__file__).parent / 'fixtures/story'
PAGE = json.loads((FIX / 'story-page.json').read_text())
LINES = (FIX / 'story-lines.txt').read_text().splitlines()
MOVED = {'from_revision': 'e' * 64, 'from_profile': 'ophiolite.point-set/1', 'to_profile': 'ophiolite.point-set/2', 'at': '2026-11-03T10:00:00Z'}


def moved_page():
    page = copy.deepcopy(PAGE)
    next(n for n in page['nodes'] if n['id'] == page['root'])['migration'] = MOVED
    return page


def test_a_moved_revision_reads_saved_in_a_newer_format_and_no_profile_id(capsys):
    page = moved_page()
    c = Recorded({'story': page, 'states': {'asset_id': 'a-shale', 'revision': R, 'outcomes': []}})
    _, out = run(['story', 'a-shale', R], c, capsys)
    added = [line for line in out.splitlines() if line not in LINES]
    assert added == ['  Saved in a newer format from version 1.']
    assert 'ophiolite.' not in out and MOVED['from_revision'] not in out
    payload, out = run(['story', 'a-shale', R, '--json'], c, capsys)
    root = next(n for n in json.loads(out)['nodes'] if n['id'] == page['root'])
    assert root['migration'] == MOVED and payload == page


def test_a_story_without_a_migration_prints_what_it_printed():
    page = copy.deepcopy(PAGE)
    for node in page['nodes']: node['migration'] = None
    assert story.lines(page) == LINES
