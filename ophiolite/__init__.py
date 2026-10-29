"""Preview scientific client. Local import never initializes credentials or transport."""
from ._version import __version__


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
        from . import oauth_app
        return getattr(oauth_app, name)
    if name in ('Client', 'CurveSet', 'Credential'):
        from . import client
        return getattr(client, name)
    raise AttributeError(name)
