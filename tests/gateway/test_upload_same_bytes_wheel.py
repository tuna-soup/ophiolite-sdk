"""E122 s3b C2, through the installed SDK against the in-process gateway: (a) a complete named send with C renamed asks
about the renamed file and prints the served sentence; (b) `decide(..., 'same-item')` and the send again make it the
same element, unchanged, and a further send asks nothing; (d) `decide(..., 'add-new')` adds it as new and C is gone
(COUNTS.md of `tests/fixtures/e122s3b`). Mutation: the SDK drops `choice` 'same-item' -> the gateway refuses -> red."""
from test_in_process_publish import web, shared, app, service  # noqa: F401 (fixtures)
from project_gateway.tests.test_source_gone import C, FOLDER, NAME

import ophiolite

ORIGIN = 'https://workspace.example'
R = 'renamed/' + C.split('/')[-1]
ASKED = 'Same bytes as `Survey/%s`. Is this the same file? Confirm it, add it as a new file, or skip it.' % C


def folder(tmp_path, files):
    root = tmp_path / 'Survey'
    if root.exists(): __import__('shutil').rmtree(root)
    for path, raw in files:
        (root / path).parent.mkdir(parents=True, exist_ok=True); (root / path).write_bytes(raw)
    return root


def sent(web, root):
    runs = ophiolite.Client(ORIGIN, 'p', ophiolite.Credential.bearer('oph_api_alice:read,write'), web.c).upload_runs
    return runs, runs.upload(str(root), attribution='NLOG.NL', rights_confirmed=True, audience=(), new=True, source_name=NAME, send='complete')


def asked(web, tmp_path):
    """The first send of A, B, C, then A, B and C renamed to R: the report with R's question."""
    _, first = sent(web, folder(tmp_path, FOLDER))
    assert first.ok
    root = folder(tmp_path, [FOLDER[0], FOLDER[1], (R, dict(FOLDER)[C])])
    runs, report = sent(web, root)
    return runs, root, report


def test_a_rename_is_asked_and_confirmed_through_the_installed_sdk(web, tmp_path):
    runs, root, report = asked(web, tmp_path)
    assert '  Survey/%s: Needs your decision - %s' % (R, ASKED) in report.text().splitlines()
    assert report.view['changes']['sentence'] == 'Compared with the last send of Petrel export: 2 unchanged, 0 changed, 0 new.'
    assert report.proposals == 1
    ordinal = next(i['ordinal'] for i in report.items if i['path'] == 'Survey/' + R)
    runs.decide(report.run_id, [ordinal], 'same-item')
    done = runs.send(report.run_id, runs.open(str(root)))
    assert [i['state'] for i in done.items] == ['already-here'] * 3
    assert done.view['changes']['sentence'] == 'Compared with the last send of Petrel export: 3 unchanged, 0 changed, 0 new.'
    assert done.view['scope']['sentence'] == 'This complete send of Petrel export finished: nothing is gone from the source.'
    _, again = sent(web, root)
    assert [i['state'] for i in again.items] == ['already-here'] * 3 and again.view['scope']['gone'] == 0


def test_a_rename_added_as_new_through_the_installed_sdk(web, tmp_path):
    runs, root, report = asked(web, tmp_path)
    ordinal = next(i['ordinal'] for i in report.items if i['path'] == 'Survey/' + R)
    runs.decide(report.run_id, [ordinal], 'add-new')
    done = runs.send(report.run_id, runs.open(str(root)))
    assert done.view['changes']['sentence'] == 'Compared with the last send of Petrel export: 2 unchanged, 0 changed, 1 new.'
    assert [g['path'] for g in done.view['scope']['gone_files']] == ['Survey/' + C]
