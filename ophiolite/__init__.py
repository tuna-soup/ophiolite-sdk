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
    if name in ('Client', 'CurveSet', 'Credential'):
        from . import client
        return getattr(client, name)
    raise AttributeError(name)
