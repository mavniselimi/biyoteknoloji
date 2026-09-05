# -*- coding: utf-8 -*-
"""SYNTHETIC WP-11 fixtures. TEST ONLY. NOT CLINICAL DATA.

Everything under this package describes a world that does not exist: an
approved curation protocol, an unquarantined evidence build, a published
dataset, and five actors holding roles. None of that is true of this
repository, and none of the values here is a scientific claim.

The fixtures exist because the successful path has to be exercisable. The
alternative would be to change the real protocol's approval state or the real
evidence build's quarantine so a test could pass, which would be a lie about
the science rather than a test fixture.

This directory is under ``tests/``, which the production registry's default
root (``data/rulesets``) does not reach. A test cannot make the real registry
executable by accident.
"""
