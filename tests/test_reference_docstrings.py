"""The docstrings the generated Python reference shows name no epic and no decision (ophiolite-66, 26 Nov 2026).

The site's reference pages copy docstrings verbatim from the pinned release: each name of `ophiolite.__all__`, every
public member of a class among them (its bases' included), and for a module the names it exports. Planning ids belong
in `#` comments. This test reads the same docstrings at run time, so it covers a superset of what the pages show.
Mutation: an epic or decision id put back into any of them (`tools.py`'s module docstring was the first found)."""
import inspect
import re

import pytest

import ophiolite

PLANNING = re.compile(r'\b(?:E[0-9]{1,3}[a-z]?|D[0-9]{1,3})\b')


def function_of(value):
    if isinstance(value, property): return value.fget
    if isinstance(value, (classmethod, staticmethod)): return value.__func__
    return value


def members(cls):
    """(qualified name, docstring) for each public member of CLS and its bases, as CLS resolves it."""
    for name in sorted(dir(cls)):
        if name.startswith('_'): continue
        value = function_of(inspect.getattr_static(cls, name))
        if callable(value) or isinstance(value, property): yield '%s.%s' % (cls.__name__, name), value.__doc__ or ''


def shown():
    """(where, docstring) for everything the reference shows."""
    for name in ophiolite.__all__:
        value = getattr(ophiolite, name)
        yield name, value.__doc__ or ''
        if inspect.isclass(value):
            yield from members(value)
        elif inspect.ismodule(value):
            for exported in getattr(value, '__all__', ()):
                yield '%s.%s' % (name, exported), getattr(value, exported).__doc__ or ''


def test_the_reference_shows_some_docstrings():
    found = dict(shown())
    assert {'Client', 'Client.tool_register', 'tools', 'tools.Stopped', 'AsyncClient.configure'} <= set(found)
    assert len(found) > 500


@pytest.mark.parametrize('where,doc', sorted(shown()), ids=lambda value: value if '\n' not in str(value) and len(str(value)) < 80 else '')
def test_no_docstring_the_reference_shows_names_an_epic_or_a_decision(where, doc):
    assert not PLANNING.search(doc), '%s: %s' % (where, PLANNING.search(doc).group(0))
