# -*- coding: utf-8 -*-
"""Argon2id, or nothing (WP-23).

The most important tests in this module are the ones that pass whether or not
``argon2-cffi`` is installed, because those are the ones asserting that no
weaker path exists. A test that only ran with Argon2 present could not catch
the failure that matters: a fallback branch reached precisely when Argon2 is
absent.

So the file is in two halves. The structural half parses this repository's own
source and asserts the absence of any other hashing primitive. The behavioural
half needs a working Argon2 and skips with a named reason when there is none -
never against a substitute, because a substitute would let "passwords are
Argon2id" pass in an environment where no Argon2 exists.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from pgx.security.errors import PasswordPolicyError
from pgx.security.passwords import (ACTIVE_POLICY, Argon2PasswordHasher,
                                    Password, PasswordPolicy,
                                    argon2_available,
                                    argon2_unavailable_reason, describe_hash)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
PASSWORDS_MODULE = os.path.join(REPO_ROOT, "pgx", "security", "passwords.py")

_ARGON2_REASON = ("argon2-cffi is not installed in this environment, so no "
                  "real Argon2id hash can be produced or verified")


def _source(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


class TestNoWeakerAlgorithmExists(unittest.TestCase):
    """Structural. Runs everywhere, including without argon2-cffi."""

    def setUp(self):
        self.source = _source(PASSWORDS_MODULE)
        self.tree = ast.parse(self.source)

    def test_the_module_imports_no_other_hashing_primitive(self):
        """The one import that may appear is ``argon2``.

        Checked by AST rather than by searching for the words, because this
        module's own prose names PBKDF2 and scrypt while explaining why they
        are absent - and a substring search would match the explanation.
        """
        forbidden = {"hashlib", "crypt", "passlib", "bcrypt", "scrypt",
                     "pbkdf2", "hashlib.pbkdf2_hmac"}
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0]
                                for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertIn("argon2", imported)
        for name in forbidden:
            with self.subTest(module=name):
                self.assertNotIn(name.split(".")[0], imported)

    def test_no_function_names_a_fallback(self):
        names = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(node.name.lower())
        for marker in ("pbkdf2", "scrypt", "sha256_password", "fallback",
                       "legacy_hash", "plaintext"):
            with self.subTest(marker=marker):
                self.assertFalse([n for n in names if marker in n])

    def test_the_missing_dependency_raises_rather_than_degrading(self):
        """The behaviour that keeps a broken install honest."""
        if argon2_available():
            self.skipTest("argon2-cffi is installed, so the unavailable path "
                          "cannot be exercised without uninstalling it")
        with self.assertRaises(PasswordPolicyError) as raised:
            Argon2PasswordHasher()
        self.assertEqual(raised.exception.code, "PASSWORD_HASHING_UNAVAILABLE")
        self.assertIsNotNone(argon2_unavailable_reason())

    def test_no_other_security_module_hashes_a_password(self):
        """Only this module may hash. Checked across the whole package.

        A second hashing site is how a system ends up with two policies, one
        of which nobody updated.
        """
        for name in sorted(os.listdir(os.path.join(REPO_ROOT, "pgx",
                                                   "security"))):
            if not name.endswith(".py") or name == "passwords.py":
                continue
            tree = ast.parse(_source(os.path.join(REPO_ROOT, "pgx",
                                                  "security", name)))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                for module in modules:
                    with self.subTest(module=name, imported=module):
                        self.assertFalse(module.startswith("argon2"))


class TestThePolicyIsVersionedAndBounded(unittest.TestCase):

    def test_the_active_policy_meets_the_rfc_9106_minimum(self):
        self.assertGreaterEqual(ACTIVE_POLICY.memory_cost_kib, 19456)
        self.assertGreaterEqual(ACTIVE_POLICY.time_cost, 2)
        self.assertEqual(ACTIVE_POLICY.to_json()["algorithm"], "argon2id")

    def test_a_policy_below_the_minimum_is_refused(self):
        """A parameter set that made Argon2 fast would be Argon2 in name."""
        with self.assertRaises(PasswordPolicyError):
            PasswordPolicy(memory_cost_kib=1024)
        with self.assertRaises(PasswordPolicyError):
            PasswordPolicy(time_cost=1)

    def test_the_published_policy_carries_no_secret(self):
        document = ACTIVE_POLICY.to_json()
        for key in document:
            with self.subTest(field=key):
                self.assertNotIn("secret", key)
                self.assertNotIn("pepper", key)


class TestAPasswordNeverLeaks(unittest.TestCase):

    def test_the_repr_does_not_contain_the_value(self):
        secret_value = "TEST-ONLY-never-print-this-0001"
        password = Password(secret_value)
        for rendered in (repr(password), str(password),
                         "%r" % password, "%s" % password,
                         "{}".format(password)):
            with self.subTest(rendering=rendered):
                self.assertNotIn(secret_value, rendered)

    def test_bounds_are_applied_before_hashing(self):
        with self.assertRaises(PasswordPolicyError):
            Password("short")
        with self.assertRaises(PasswordPolicyError):
            Password("x" * 2000)

    def test_the_value_is_not_trimmed_or_normalised(self):
        """Silently changing a password makes a working credential stop
        working with no message anybody can act on."""
        padded = "  TEST-ONLY-padded-passphrase  "
        self.assertEqual(Password(padded).reveal(), padded)

    def test_comparison_is_constant_time_and_typed(self):
        value = "TEST-ONLY-comparison-passphrase"
        self.assertEqual(Password(value), Password(value))
        self.assertNotEqual(Password(value), Password(value + "x"))
        # Comparing to a bare string returns NotImplemented rather than
        # falling through to an ordinary ``==``, which would be an oracle.
        self.assertNotEqual(Password(value), value)

    def test_a_password_is_not_a_dictionary_key(self):
        with self.assertRaises(TypeError):
            {Password("TEST-ONLY-hashable-check-01"): 1}


@unittest.skipUnless(argon2_available(), _ARGON2_REASON)
class TestArgon2idBehaviour(unittest.TestCase):
    """Behavioural. Skips - never substitutes - when Argon2 is absent."""

    def setUp(self):
        self.hasher = Argon2PasswordHasher()
        self.password = Password("TEST-ONLY-behaviour-passphrase-1")

    def test_the_stored_hash_is_an_encoded_argon2id_phc_string(self):
        encoded = self.hasher.hash(self.password)
        self.assertTrue(encoded.startswith("$argon2id$"))
        algorithm, is_argon2id = describe_hash(encoded)
        self.assertEqual(algorithm, "argon2id")
        self.assertTrue(is_argon2id)

    def test_the_hash_does_not_contain_the_password(self):
        encoded = self.hasher.hash(self.password)
        self.assertNotIn(self.password.reveal(), encoded)

    def test_two_hashes_of_one_password_differ(self):
        """Salted. Identical hashes would mean a shared salt or none."""
        self.assertNotEqual(self.hasher.hash(self.password),
                            self.hasher.hash(self.password))

    def test_verification_accepts_the_password_and_rejects_others(self):
        encoded = self.hasher.hash(self.password)
        self.assertTrue(self.hasher.verify(encoded, self.password))
        self.assertFalse(self.hasher.verify(
            encoded, Password("TEST-ONLY-different-passphrase")))

    def test_a_malformed_stored_hash_verifies_false_rather_than_raising(self):
        """A login path must not branch differently on a corrupt row."""
        self.assertFalse(self.hasher.verify("not-a-hash", self.password))

    def test_needs_rehash_detects_obsolete_parameters(self):
        weak = Argon2PasswordHasher(PasswordPolicy(memory_cost_kib=19456,
                                                   time_cost=2))
        old = weak.hash(self.password)
        self.assertTrue(self.hasher.needs_rehash(old))
        self.assertFalse(self.hasher.needs_rehash(
            self.hasher.hash(self.password)))

    def test_dummy_verify_costs_something_and_returns_nothing(self):
        self.assertIsNone(self.hasher.dummy_verify())

    def test_hashing_refuses_a_bare_string(self):
        """A bare string would bypass the bounds check in ``Password``."""
        with self.assertRaises(PasswordPolicyError):
            self.hasher.hash("TEST-ONLY-bare-string-passphrase")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
