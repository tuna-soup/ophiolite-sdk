"""E52: the one connection a gallery notebook makes, so a downloaded notebook runs with only the SDK installed.

    from ophiolite.gallery import connect
    client = connect()

`connect()` returns, in this order:

1. the client bound by `use(client)` (a test harness or your own code chose it);
2. a client of the packaged synthetic server when `OPHIOLITE_URL` is not set, or `OPHIOLITE_TEMPLATE_FIXTURE=1`:
   one synthetic gamma-ray log, publications with versions and their read-back, on a loopback port, nothing real;
3. a client of `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` with the credential `ophiolite login` saved for them (or the
   file `OPHIOLITE_CREDENTIAL` names), else `OPHIOLITE_ACCESS_KEY`, as the templates read them.

When none applies it raises `Refused` with the sentence that says what to set. Importing this module contacts nothing.
"""
import atexit
import os

from .errors import Refused

_bound = None
_synthetic = None


def use(client):
    """Make `connect()` return this client (None forgets it)."""
    global _bound
    _bound = client
    return client


def synthetic():
    """True when `connect()` would use the packaged synthetic server."""
    return _bound is None and (not os.environ.get('OPHIOLITE_URL') or os.environ.get('OPHIOLITE_TEMPLATE_FIXTURE') == '1')


def connect():
    """The client this notebook works with (see the module text for the order)."""
    global _synthetic
    from .auth import Credential, default_path
    from .client import Client
    if _bound is not None: return _bound
    if synthetic():
        if _synthetic is None:
            from .testing import synthetic_server
            context = synthetic_server(); server = context.__enter__()
            client = Client(server.url, 'p', Credential.bearer('oph_api_alice'))
            _synthetic = (context, server, client)
            atexit.register(_stop)
        return _synthetic[2]
    url, project = os.environ['OPHIOLITE_URL'], os.environ.get('OPHIOLITE_PROJECT')
    if not project: raise Refused('Set OPHIOLITE_PROJECT to the project this notebook works in.', 'Copy the project id from the project page.')
    path = os.environ.get('OPHIOLITE_CREDENTIAL') or default_path(url, project)
    if os.environ.get('OPHIOLITE_CREDENTIAL') or os.path.exists(path) or os.path.islink(path):
        return Client(url, project, Credential.from_file(path))
    if 'OPHIOLITE_ACCESS_KEY' in os.environ:
        return Client(url, project, Credential.bearer(os.environ['OPHIOLITE_ACCESS_KEY'], source='environment'))
    raise Refused(f'No saved sign-in for {project} at {url}.',
                  f'Run: ophiolite login --url {url} --project {project}, or set OPHIOLITE_ACCESS_KEY; unset OPHIOLITE_URL to use the synthetic server.')


def _stop():
    global _synthetic
    if _synthetic is not None:
        context, _, client = _synthetic; _synthetic = None
        try: client.close()
        finally: context.__exit__(None, None, None)
