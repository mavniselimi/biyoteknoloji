# -*- coding: utf-8 -*-
"""The suite runs offline, and that is enforced rather than hoped for.

The suite is written to need no network. Nothing was checking it. A test that
quietly fetched a live source would pass wherever an index is reachable and
fail where a release is built, and the failure would arrive months later as
"it works on my machine".
"""

from __future__ import annotations

import socket
import unittest

from pgx.verification.offline import (
    NetworkAccessRefused,
    install_offline_guard,
    is_loopback,
    offline_guard_installed,
    remove_offline_guard,
)
from pgx.verification.profiles import PROFILES


class TestTheGuardRefusesTheOutsideWorld(unittest.TestCase):

    def setUp(self):
        install_offline_guard()
        self.addCleanup(remove_offline_guard)

    def test_a_remote_address_is_refused(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with self.assertRaises(NetworkAccessRefused):
                client.connect(("93.184.216.34", 80))

    def test_a_hostname_is_refused_before_it_is_even_resolved(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with self.assertRaises(NetworkAccessRefused):
                client.connect(("pypi.org", 443))

    def test_connect_ex_is_guarded_too(self):
        """The quieter half of the socket API, and the one a library reaching
        for a non-blocking connection would use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with self.assertRaises(NetworkAccessRefused):
                client.connect_ex(("93.184.216.34", 80))

    def test_the_refusal_says_why(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with self.assertRaises(NetworkAccessRefused) as raised:
                client.connect(("example.invalid", 80))
        self.assertIn("offline", str(raised.exception))

    def test_loopback_stays_open(self):
        """The ASGI and browser suites legitimately talk to 127.0.0.1.
        Refusing that would replace a real check with a broken one."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect(listener.getsockname())

    def test_the_guard_can_be_removed(self):
        self.assertTrue(offline_guard_installed())
        remove_offline_guard()
        self.assertFalse(offline_guard_installed())
        install_offline_guard()

    def test_installing_twice_does_not_capture_the_guard_as_the_original(self):
        """Otherwise removal would leave the guard permanently installed."""
        install_offline_guard()
        install_offline_guard()
        remove_offline_guard()
        self.assertFalse(offline_guard_installed())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            # Now unguarded: this fails to connect, but not with our error.
            try:
                client.settimeout(0.01)
                client.connect(("127.0.0.1", 1))
            except NetworkAccessRefused:  # pragma: no cover - the bug
                self.fail("the guard survived its own removal")
            except OSError:
                pass
        install_offline_guard()


class TestWhatCountsAsLocal(unittest.TestCase):

    def test_loopback_addresses(self):
        for address in (("127.0.0.1", 80), ("127.0.0.53", 53), ("::1", 80),
                        ("localhost", 8000)):
            with self.subTest(address=address):
                self.assertTrue(is_loopback(address))

    def test_remote_addresses(self):
        for address in (("8.8.8.8", 53), ("pypi.org", 443),
                        ("192.168.1.10", 80), ("2001:4860:4860::8888", 443)):
            with self.subTest(address=address):
                self.assertFalse(is_loopback(address))

    def test_a_unix_socket_path_cannot_leave_the_host(self):
        self.assertTrue(is_loopback("/var/run/something.sock"))

    def test_an_unrecognised_shape_is_refused(self):
        """The safe default for a guard is no."""
        for address in (None, 42, (), (None, 80)):
            with self.subTest(address=address):
                self.assertFalse(is_loopback(address))


class TestEveryProfileRunsOffline(unittest.TestCase):

    def test_no_profile_opts_out(self):
        for profile in PROFILES:
            with self.subTest(profile=profile.name):
                self.assertTrue(
                    profile.offline,
                    "%s would run with the network reachable" % profile.name)
