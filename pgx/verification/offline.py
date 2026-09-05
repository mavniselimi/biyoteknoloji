# -*- coding: utf-8 -*-
"""Refusing the network for the duration of a verification run.

The suite is written to need no network. That is a property nothing was
checking: a test that quietly fetched a live source would pass in an
environment with an index and fail in the one where a release is built, and the
failure would arrive months later as "it works on my machine".

So a verification run installs a guard. Outbound connections to anything that
is not loopback raise. Loopback stays open because the ASGI and browser suites
legitimately talk to a server on ``127.0.0.1``, and refusing that would replace
a real check with a broken one.

The guard is deliberately at ``socket.socket.connect``. Patching a higher layer
- ``httpx``, ``urllib`` - would guard only the libraries somebody remembered,
and the thing being guarded against is precisely the call nobody remembered.
"""

from __future__ import annotations

import socket
from typing import Any, Callable, Optional, Tuple

__all__ = [
    "NetworkAccessRefused",
    "install_offline_guard",
    "remove_offline_guard",
    "is_loopback",
    "offline_guard_installed",
]


class NetworkAccessRefused(RuntimeError):
    """A test attempted a connection the offline guard refused."""


#: Hostnames and addresses that stay reachable. Loopback only.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", ""})

_original_connect: Optional[Callable[..., Any]] = None
_original_connect_ex: Optional[Callable[..., Any]] = None


def is_loopback(address: Any) -> bool:
    """Whether ``address`` names the local machine.

    Unix-domain sockets pass a string path and are always allowed: they cannot
    leave the host. Anything whose shape is unrecognised is refused, because
    the safe default for a guard is to say no.
    """
    if isinstance(address, (str, bytes)):
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    return host.startswith("127.") or host == "::ffff:127.0.0.1"


def offline_guard_installed() -> bool:
    """Whether the guard is currently in place."""
    return _original_connect is not None


def install_offline_guard() -> None:
    """Refuse non-loopback connections until ``remove_offline_guard``.

    Idempotent: installing twice would capture the guard as the original and
    make removal impossible.
    """
    global _original_connect, _original_connect_ex
    if _original_connect is not None:
        return
    _original_connect = socket.socket.connect
    _original_connect_ex = socket.socket.connect_ex

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        _refuse_unless_local(address)
        return _original_connect(self, address)  # type: ignore[misc]

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        _refuse_unless_local(address)
        return _original_connect_ex(self, address)  # type: ignore[misc]

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]


def remove_offline_guard() -> None:
    """Put the real socket methods back."""
    global _original_connect, _original_connect_ex
    if _original_connect is None:
        return
    socket.socket.connect = _original_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _original_connect_ex  # type: ignore[method-assign]
    _original_connect = None
    _original_connect_ex = None


def _refuse_unless_local(address: Any) -> None:
    if is_loopback(address):
        return
    raise NetworkAccessRefused(
        "the verification run refused a connection to %r: the suite is "
        "required to run offline, and a test that reaches a live source "
        "cannot be reproduced where a release is built" % (address,))
