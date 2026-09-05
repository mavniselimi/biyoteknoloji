"""WP-19 verification-system tests.

A verifier nobody verifies is a decoration. These tests hold down the
properties that make its output worth reading: that a skip cannot become a
pass, that zero tests cannot be a success, that the five outcomes stay apart,
that stale evidence is rejected, that nothing machine-specific or clinical
reaches a committed artifact, and that the portable immutability check cannot
hide a writable tree.
"""
