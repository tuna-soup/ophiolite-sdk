"""E105b C7 (row 16): the gallery notebook `share-a-procedure`, cell by cell as published, against the real procedure
routes of an in-process gateway with two access keys: alice (a project administrator) adds and enables the procedure;
bob, her colleague, is shown the trust question, trusts it as himself and runs it from the project."""
import contextlib
import io
import json
import os
from pathlib import Path

import pytest
try:
    from project_gateway.tests.procedure_world import actions, rows
    from project_gateway.tests.real_credentials import ORIGIN, project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from ophiolite import Client, Credential, gallery

NOTEBOOK = Path(__file__).resolve().parents[2] / 'notebooks/share-a-procedure/notebook.ipynb'


def run_live(alice, bob, workdir):
    """Every code cell of the published notebook, in order, in one namespace; returns (namespace, printed text)."""
    cells = [''.join(c['source']) for c in json.loads(NOTEBOOK.read_text())['cells'] if c['cell_type'] == 'code']
    here, printed, namespace = os.getcwd(), io.StringIO(), {'__name__': '__main__'}
    gallery.use(alice, colleague=bob)
    try:
        os.chdir(workdir)
        with contextlib.redirect_stdout(printed):
            for i, code in enumerate(cells): exec(compile(code, 'share-a-procedure.ipynb#cell%d' % i, 'exec'), namespace)
    finally:
        os.chdir(here); gallery.use(None)
    return namespace, printed.getvalue()


def test_the_notebook_adds_enables_and_its_colleague_trusts_once_and_runs(world, tmp_path):
    alice, bob = (Client(ORIGIN, 'p', Credential.bearer(world.key(person)), world.c) for person in ('alice', 'bob'))
    folder = tmp_path / 'notebook'; folder.mkdir()  # the world keeps its own state in tmp_path
    ns, printed = run_live(alice, bob, folder)
    added, name = ns['added'], ns['manifest']['name']
    assert (added['state'], added['added_by'], added['mine']) == ('private', 'alice', True) and name.startswith('shift-')
    assert 'It is private: you and the project administrators see it until an administrator enables it for everyone.' in printed
    assert 'Enabled for everyone in this project.' in printed
    assert 'was registered by alice and enabled on ' in printed and added['digest'] in printed  # the question bob is shown
    assert rows(world, 'SELECT principal,principal_kind FROM procedure_trust WHERE digest=?', added['digest']) == [('bob', 'person')]
    assert len(actions(world, 'trust')) == 1
    assert ns['theirs']['run']['procedure'] == {**ns['mine']['run']['procedure'], 'digest': added['digest']}
    assert 'Same shifted tops as on your computer: [1003.0, 1202.5]' in printed
    assert sorted(p.name for p in folder.iterdir()) == ['share-a-procedure.png']  # nothing else lands in the notebook's folder
