"""Workspace page addresses (E104). One builder for every link the SDK shows; the plug-in keeps its own copy of the
grammar and agrees with it through a literal table, not by import.

E45's page grammar: `/project/<p>/data/<family>~<id>`, where `s~` is a connected selection (always its current
version, so it never carries a revision), `a~` a Workspace item (a map or a curve the Workspace holds) and `m~` stored
data (a well log or typed data, including the results a send or a publication creates). No `tab` until E98 merges."""
from urllib.parse import quote
from ._core import origin as _origin
from .errors import Refused

FAMILIES = ('s', 'a', 'm')
FAMILY_OF_KIND = {'external-scalar-map': 'a', 'external-curve': 'a', 'derived': 'm', 'uploaded': 'm'}


def family_of(kind):
    """The page family of an item kind; a kind without a page has no link."""
    if kind not in FAMILY_OF_KIND: raise Refused('This item has no Workspace page.')
    return FAMILY_OF_KIND[kind]


def item_url(origin, project, family, item, revision=None):
    """The Workspace page of `item` in `project`, at `revision` when the family keeps versions."""
    if family not in FAMILIES: raise Refused('This item has no Workspace page.')
    for value in (project, item):
        if not isinstance(value, str) or not value: raise Refused('Name the project and the item.')
    if revision is not None and (family == 's' or not isinstance(revision, str) or not revision):
        raise Refused('A connected selection always shows its current version.' if family == 's' else 'Name the version.')
    url = _origin(origin) + '/project/' + quote(project, safe='') + '/data/' + family + '~' + quote(item, safe='')
    return url + ('?revision=' + quote(revision, safe='') if revision is not None else '')
