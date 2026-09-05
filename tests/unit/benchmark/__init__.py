# -*- coding: utf-8 -*-
"""WP-21 tests: metric definitions, benchmark contract, report and feed.

Its own package rather than more modules under ``tests/unit/validation``,
because what these assert is different in kind. WP-18's tests are about
keeping cases apart; these are about the arithmetic and, more often, about the
absence of arithmetic - that a zero denominator produces nothing, that an
unexecuted benchmark produces nothing, and that neither of those is ever a
zero on a page.
"""
