"""E217 s0 (D7): the docstrings a reader meets on Client, CurveSet and AsyncClient.

Every public name defined on Client, CurveSet and AsyncClient themselves, every public name Client inherits from its
mixins (C7a), and each of the three classes, has a docstring whose first line is one sentence ending in a period; no
docstring names an epic (epic numbers live in `#` comments). AsyncClient's names (C7) are its own coroutines, the ones
aio.py attaches (functools.wraps gives each its Client method's docstring) and the ones it refuses (`_sync_only` gives
each a docstring); what it inherits unchanged is checked on Client. The `tool_*` twins are left out: tools.py writes
their docstring from the `procedure_*` name they call, and the twins test checks that it does. A journey-list name (D8)
of Client's surface also has a non-empty Returns section and, when it takes any argument, a Parameters section that
names every one; the journey list is the documents' `client.<name>(` calls, made on Client, so AsyncClient's names are
held to the first-sentence rule only. Example sections are extracted by `examples()` and type-checked against the
installed wheel by test_typing_examples.py, after PREAMBLE (D6); an attached coroutine's copy of its Client method's
Example is checked once, on Client.
"""
import inspect
import re
import textwrap

import pytest

from ophiolite import aio
from ophiolite.aio import AsyncClient
from ophiolite.client import Client, CurveSet
from ophiolite.tools import VERBS, ToolClient

# D8: the 60 distinct `client.<name>(` calls in ophiolite-sdk/README.md, ophiolite-sdk/docs/sdk-guide.md,
# web/docs/src/content/docs/guides/*.md and web/docs/src/content/docs/reference/sdk.md, recounted by hand at lane open
# (unchanged) and frozen here
JOURNEY = frozenset('''
assets associations audience browse change_coordinates change_units create_entity dependents download_original
entities entity exchange export export_corpus export_file export_slices export_trajectories extent find_log
grant_own_ai_use grants history import_bundle import_storage iter_window layouts lineage new_data_defaults
of_entity preview_change provenance publish publish_derived read read_data read_many read_slice read_window
recover remake remake_save search served_limits set_audience set_new_data_defaults share source sources
start_sample story sync template templates upload upload_data upload_las well_imports wells what_changed
work_folder
'''.split())
CLASSES = (Client, CurveSet, AsyncClient)
EPIC = re.compile(r'\bE[0-9]{2,3}[a-z]?\b')
HEADER = re.compile(r'^([A-Z][a-z]+)\n-+\n', re.M)
PREAMBLE = 'import ophiolite\n\nclient: ophiolite.Client\n\n'
# the docstrings that carry an Example; one lost fails here rather than going unchecked
EXAMPLED = {'Client', 'Client.assets', 'Client.find_log', 'Client.history', 'Client.read', 'Client.read_data', 'CurveSet'}


def function_of(value):
    """The function a docstring sits on: a property's getter, a class or static method's function."""
    if isinstance(value, property): return value.fget
    if isinstance(value, (classmethod, staticmethod)): return value.__func__
    return value


def defined(cls):
    """The public names CLS defines itself (none inherited), each with its function."""
    return {name: function_of(value) for name, value in vars(cls).items() if not name.startswith('_') and callable(function_of(value))}


MIXINS = Client.__mro__[1:-1]  # every class Client mixes in, in its own order (object left out)
TWINS = {'tool_' + verb for verb in VERBS}


def inherited():
    """{name: the mixin that defines it}: each public name Client inherits and does not define, as Client resolves it
    (the first mixin in its order), the `tool_*` twins left out."""
    found = {}
    for mixin in MIXINS:
        for name in defined(mixin):
            if name not in vars(Client) and name not in found and name not in TWINS: found[name] = mixin
    return found


CHECKED = ([(cls, None) for cls in CLASSES] + [(cls, name) for cls in CLASSES for name in defined(cls)]
           + [(mixin, name) for name, mixin in inherited().items()])


def docstring(cls, name):
    return (cls.__doc__ if name is None else defined(cls)[name].__doc__) or ''


def sections(doc):
    """(the text before the first section, {section: its body}) of a numpy-style docstring."""
    parts = HEADER.split(inspect.cleandoc(doc))
    return parts[0], {title: body.strip('\n') for title, body in zip(parts[1::2], parts[2::2])}


def named(body):
    """The parameter names a Parameters section documents: each entry starts at the margin, `name` or `name : type`."""
    return {word.strip().lstrip('*') for line in body.splitlines() if line and not line[0].isspace() for word in line.split(' : ')[0].split(',')}


def label(cls, name):
    return cls.__name__ + ('' if name is None else '.' + name)


def examples():
    """{'Client.read': code}: the code of each Example section, for test_typing_examples (D6)."""
    found = {}
    for cls, name in CHECKED:
        if name is not None and hasattr(defined(cls)[name], '__wrapped__'): continue  # an attached copy: checked on Client
        body = sections(docstring(cls, name))[1].get('Example')
        if body: found[label(cls, name)] = textwrap.dedent(body).strip() + '\n'
    return found


def test_the_checked_names_are_client_and_curveset_and_what_client_inherits():
    assert len(JOURNEY) == 60
    assert [label(c, n) for c, n in CHECKED if n is not None and c is CurveSet] == ['CurveSet.evidence', 'CurveSet.to_numpy', 'CurveSet.to_frame',
                                                                                    'CurveSet.workspace_url', 'CurveSet.save']
    assert sum(c is Client for c, n in CHECKED) > 100
    names = {n for c, n in CHECKED if c is not AsyncClient}
    public = {n for n in dir(Client) if not n.startswith('_') and callable(function_of(inspect.getattr_static(Client, n)))}
    assert sorted(public - names) == sorted(TWINS)  # every public name of Client is checked, but for the twins
    assert sorted(JOURNEY - names) == []  # every journey name is Client's own or a mixin's
    assert {c.__name__ for c, n in CHECKED if c in MIXINS} == {'Navigation', 'EntityClient', 'LocationClient', 'SourceClient', 'CheckClient',
                                                                'ProcedureClient', 'AccessHistoryClient', 'OutcomeClient', 'VerdictClient',
                                                                'TrajectoryClient', 'RuleResultsClient'}


def test_every_public_name_of_async_client_is_checked():
    own = {n for c, n in CHECKED if c is AsyncClient and n is not None}
    attached = {n for n in own if hasattr(defined(AsyncClient)[n], '__wrapped__')}
    refused = set(aio._SYNC_ONLY) | set(aio._SYNC_ONLY_PROPERTIES)
    # C7, counted at 71000c279: 22 own names (21 coroutines and functions, and the alias aclose), 39 attached, 77 refused;
    # E222 s1 refuses the documents property (78)
    assert (len(own - attached - refused), len(attached), len(own & refused)) == (22, 39, 78)
    assert all(vars(Client)[n] is defined(AsyncClient)[n].__wrapped__ for n in attached)
    names = own | {n for c, n in CHECKED if c is not AsyncClient}  # what AsyncClient inherits unchanged is checked there
    public = {n for n in dir(AsyncClient) if not n.startswith('_') and callable(function_of(inspect.getattr_static(AsyncClient, n)))}
    assert sorted(public - names) == sorted(TWINS - refused)  # the twins AsyncClient does not refuse are Client's own


@pytest.mark.parametrize('verb', VERBS)
def test_each_tool_twin_takes_its_docstring_from_the_checked_procedure_name(verb):
    twin = vars(ToolClient)['tool_' + verb]
    assert twin.__doc__ == f'The tool spelling of `procedure_{verb}` (the same call).'
    assert ('procedure_' + verb) in inherited(), f'procedure_{verb} is not checked'


@pytest.mark.parametrize('cls, name', CHECKED, ids=[label(c, n) for c, n in CHECKED])
def test_each_docstring_opens_with_one_plain_sentence(cls, name):
    doc = docstring(cls, name)
    assert doc.strip(), f'{label(cls, name)} has no docstring'
    first = inspect.cleandoc(doc).splitlines()[0]
    assert first.endswith('.') and not re.search(r'[.!?]\s', first), f'{label(cls, name)}: the first line is not one sentence ending in a period: {first!r}'
    epic = EPIC.search(doc)
    assert epic is None, f'{label(cls, name)}: the docstring names an epic ({epic[0] if epic else ""}); it belongs in a # comment'


JOURNEY_CHECKED = [(c, n) for c, n in CHECKED if n in JOURNEY and c is not AsyncClient]  # D8 lists Client's calls


@pytest.mark.parametrize('cls, name', JOURNEY_CHECKED, ids=[label(c, n) for c, n in JOURNEY_CHECKED])
def test_each_journey_name_says_what_it_takes_and_returns(cls, name):
    found = sections(docstring(cls, name))[1]
    assert found.get('Returns', '').strip(), f'{label(cls, name)} has no Returns'
    taken = list(inspect.signature(defined(cls)[name]).parameters)[1:]  # without self or cls
    if taken:
        assert found.get('Parameters', '').strip(), f'{label(cls, name)} takes {taken} and has no Parameters'
        assert sorted(set(taken) - named(found['Parameters'])) == [], f'{label(cls, name)}: Parameters leaves out some of {taken}'


def test_the_examples_are_where_they_were_written():
    assert set(examples()) == EXAMPLED
