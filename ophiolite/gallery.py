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

`colleague()` (E105b) is a second project member's client for a notebook that shows both sides of sharing: the one a
harness bound with `use(client, colleague=...)`, else, outside synthetic mode, `OPHIOLITE_COLLEAGUE_ACCESS_KEY` for
the same address and project; otherwise None and the notebook says what it would show.

`pack()` (E129 e) is the one start of a pack notebook, which reads a downloaded starter pack and no project: it
returns the folder `OPHIOLITE_PACK` names, after blocking the process's network.
"""
import atexit
import os

from .errors import Refused

_bound = None
_colleague = None
_synthetic = None


def use(client, colleague=None):
    """Make `connect()` return this client and `colleague()` that one (None forgets them)."""
    global _bound, _colleague
    _bound, _colleague = client, colleague
    return client


def colleague():
    """A second project member's client, or None (see the module text)."""
    from .auth import Credential
    from .client import Client
    if _bound is not None or synthetic(): return _colleague
    key, project = os.environ.get('OPHIOLITE_COLLEAGUE_ACCESS_KEY'), os.environ.get('OPHIOLITE_PROJECT')
    return Client(os.environ['OPHIOLITE_URL'], project, Credential.bearer(key, source='environment')) if key and project else None


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
                  'Put the configuration.json from Connect → Use Python in this folder and run: ophiolite login (or ophiolite login --key-stdin), '
                  'or set OPHIOLITE_ACCESS_KEY; unset OPHIOLITE_URL to use the synthetic server.')


PACK_WITH_URL = 'This notebook reads the starter pack folder only; unset OPHIOLITE_URL.'
PACK_UNSET = 'Set OPHIOLITE_PACK to the folder of a starter pack you downloaded.'
BLOCKED = 'network blocked: this notebook reads the pack folder only'


def pack():
    """E129 (e) D3: the folder of the starter pack a pack notebook reads (`OPHIOLITE_PACK`), after this process's
    network is blocked: from then on `socket.socket` (but for local Unix sockets), `socket.create_connection` and
    `socket.getaddrinfo` refuse. `OPHIOLITE_URL` set as well is refused, as is no `OPHIOLITE_PACK`."""
    from pathlib import Path
    if os.environ.get('OPHIOLITE_URL'): raise Refused(PACK_WITH_URL)
    folder = os.environ.get('OPHIOLITE_PACK')
    if not folder: raise Refused(PACK_UNSET)
    _block()
    return Path(folder)


def _block():
    import socket
    if getattr(socket.socket, '_ophiolite_blocked', False): return
    real = socket.socket

    class Blocked(real):
        _ophiolite_blocked = True

        def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
            if fileno is None and family != getattr(socket, 'AF_UNIX', None): raise Refused(BLOCKED)  # the default (-1) is AF_INET
            super().__init__(family, type, proto, fileno)

    def refused(*args, **kwargs): raise Refused(BLOCKED)
    socket.socket, socket.create_connection, socket.getaddrinfo = Blocked, refused, refused


def _stop():
    global _synthetic
    if _synthetic is not None:
        context, _, client = _synthetic; _synthetic = None
        try: client.close()
        finally: context.__exit__(None, None, None)
