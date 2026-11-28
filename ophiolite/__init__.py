"""Preview scientific client. Local import never initializes credentials or transport."""
from typing import TYPE_CHECKING

from ._version import __version__

if TYPE_CHECKING:  # E217 s0 (D9): what __getattr__ serves, named for a type checker; at run time each still loads lazily
    from . import oauth_app as oauth_app, tools as tools
    from ._deprecation import OphioliteDeprecationWarning as OphioliteDeprecationWarning
    from .account import Account as Account, connect as connect
    from .aio import AsyncClient as AsyncClient
    from .auth import Credential as Credential
    from .client import Client as Client, CurveSet as CurveSet
    from .oauth_app import OAuthApp as OAuthApp
    from .osdu import kinds as kinds, profiles_for as profiles_for
    from .procedures import (compared as compared, delivered as delivered, not_delivered as not_delivered, procedure as procedure,
                             refused as refused, unknown as unknown)
    from .scientific import Descriptor as Descriptor
    from .sync import Checkpoint as Checkpoint, ResyncRequired as ResyncRequired, Sync as Sync
    from .tools import tool as tool
    from .writers import WrittenOriginal as WrittenOriginal
del TYPE_CHECKING  # dir(ophiolite) stays as it was

# E163 s1: what `from ophiolite import *` and an editor show; each name is still served lazily by __getattr__.
# Left out but still served: __contracts__ (a dunder), procedure (D78: `tool` is the word) and oauth_app (its
# submodule of the same name replaces it as an attribute once imported).
__all__ = ['Client', 'Credential', 'CurveSet', 'AsyncClient', 'Descriptor', 'connect', 'Account', 'Sync', 'Checkpoint',
           'ResyncRequired', 'tool', 'tools', 'compared', 'delivered', 'refused', 'not_delivered', 'unknown',
           'WrittenOriginal', 'OAuthApp', 'OphioliteDeprecationWarning', 'kinds', 'profiles_for']


def __dir__():
    return sorted(set(globals()) | set(__all__) | {'__contracts__', 'procedure', 'oauth_app'})


def __getattr__(name):
    if name == 'AsyncClient':
        from .aio import AsyncClient
        return AsyncClient
    if name == 'Descriptor':
        from .scientific import Descriptor
        return Descriptor
    if name == '__contracts__':
        from .models.invariants import registry
        index, _ = registry()
        return {'registry_version': index['version'], 'entries': [
            {'id': row['id'], 'lifecycle': row['lifecycle']}
            for group in ('schemas', 'profiles') for row in index[group]]}
    if name in ('connect', 'Account'):  # E27
        from . import account
        return getattr(account, name)
    if name in ('Sync', 'Checkpoint', 'ResyncRequired'):  # E28
        from . import sync
        return getattr(sync, name)
    if name == 'procedure':  # E105a: the decorator that marks a procedure's entry function
        from .procedures import procedure
        return procedure
    if name == 'tool':  # E131 s1 (D78): the decorator that marks a tool's entry (the same mark as `procedure`)
        from .tools import tool
        return tool
    if name == 'tools':  # E131 s1: the module, also reachable as `import ophiolite.tools`
        import importlib
        return importlib.import_module('.tools', __name__)
    if name == 'compared':  # E110 (D9): what a check's entry returns
        from .procedures import compared
        return compared
    if name in ('delivered', 'refused', 'not_delivered', 'unknown'):  # E109 (D3): what a send's entry and its reconcile return
        from . import procedures
        return getattr(procedures, name)
    if name == 'WrittenOriginal':  # E30b
        from .writers import WrittenOriginal
        return WrittenOriginal
    if name in ('OAuthApp', 'oauth_app'):  # E33: colleagues sign in to your application's server
        import importlib  # E163 s1: `from . import oauth_app` asks this function for `oauth_app` first and never returns
        return getattr(importlib.import_module('.oauth_app', __name__), name)
    if name == 'OphioliteDeprecationWarning':  # E148: a server answered a deprecated route
        from ._deprecation import OphioliteDeprecationWarning
        return OphioliteDeprecationWarning
    if name in ('kinds', 'profiles_for'):  # E168 s1: the export matrix's OSDU kinds, read from the packaged table
        from . import osdu
        return getattr(osdu, name)
    if name in ('Client', 'CurveSet', 'Credential'):
        from . import client
        return getattr(client, name)
    raise AttributeError(name)
