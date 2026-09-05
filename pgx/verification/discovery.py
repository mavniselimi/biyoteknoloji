# -*- coding: utf-8 -*-
"""Enumerating the tests that exist, without running them.

Discovery answers one question: *what tests are in this tree?* It uses
``unittest``'s own loader rather than a syntax-tree scan, because the loader is
what the runner uses, and an inventory built from a different enumeration than
the one that executes is an inventory that can disagree with reality.

Two properties are load-bearing.

**Deterministic.** The same tree yields the same identifiers in the same order
on every call. The loader's own order depends on directory iteration, so the
result is sorted here rather than relied upon.

**Total.** Discovery reports load errors as first-class entries instead of
letting a module that fails to import vanish. A test file with a syntax error
is otherwise indistinguishable from a test file that does not exist, and the
second is a much smaller problem than the first.
"""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pgx.verification.errors import DiscoveryError

__all__ = [
    "DEFAULT_START_DIRECTORY",
    "DEFAULT_PATTERN",
    "DiscoveredTest",
    "Discovery",
    "discover",
    "flatten",
]

#: Where the suite lives, relative to the repository root.
DEFAULT_START_DIRECTORY = "tests"

#: The pattern the project has always used. Kept in one place so the CLI, the
#: inventory and the runner cannot drift apart on it.
DEFAULT_PATTERN = "test_*.py"

#: unittest represents an unimportable module as a synthetic test whose id
#: begins with one of these. They are results about the loader, not about the
#: software, and are separated out rather than counted as tests.
_LOADER_FAILURE_PREFIXES = ("unittest.loader._FailedTest",
                            "unittest.loader.ModuleImportFailure")


@dataclass(frozen=True)
class DiscoveredTest:
    """One test the loader found, identified the way the runner names it."""

    #: ``tests.unit.domain.test_hashing.TestCanonicalJson.test_it_sorts_keys``
    test_id: str
    #: ``tests.unit.domain.test_hashing``
    module: str
    #: ``TestCanonicalJson``
    cls: str
    #: ``test_it_sorts_keys``
    method: str

    @property
    def package(self) -> str:
        """``tests/unit/domain`` - the directory, in dotted form."""
        return self.module.rsplit(".", 1)[0] if "." in self.module else ""

    @property
    def relative_path(self) -> str:
        """``tests/unit/domain/test_hashing.py``."""
        return self.module.replace(".", os.sep) + ".py"


@dataclass(frozen=True)
class Discovery:
    """Everything one enumeration of the tree found."""

    tests: Tuple[DiscoveredTest, ...]
    #: Modules the loader could not import, as ``(module, message)``. Never
    #: silently dropped: a module that fails to import contributes zero tests,
    #: and zero tests is what a deleted file also contributes.
    load_failures: Tuple[Tuple[str, str], ...]
    start_directory: str
    pattern: str

    @property
    def count(self) -> int:
        return len(self.tests)

    @property
    def modules(self) -> Tuple[str, ...]:
        return tuple(sorted({test.module for test in self.tests}))

    def by_id(self) -> Dict[str, DiscoveredTest]:
        return {test.test_id: test for test in self.tests}

    def ids(self) -> Tuple[str, ...]:
        return tuple(test.test_id for test in self.tests)


def flatten(suite: unittest.TestSuite) -> List[unittest.TestCase]:
    """Every leaf test case in ``suite``, depth first.

    ``unittest.TestSuite`` is a tree of suites and cases; iterating it yields
    the next level, not the leaves. Written out rather than borrowed from a
    private helper so it cannot change under a Python upgrade.
    """
    found: List[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            found.extend(flatten(item))
        else:
            found.append(item)
    return found


def _split(test_id: str) -> Tuple[str, str, str]:
    """``module``, ``class``, ``method`` from a unittest identifier."""
    parts = test_id.rsplit(".", 2)
    if len(parts) != 3:
        return (test_id, "", "")
    return (parts[0], parts[1], parts[2])


def discover(root: str,
             start_directory: str = DEFAULT_START_DIRECTORY,
             pattern: str = DEFAULT_PATTERN,
             top_level: Optional[str] = None) -> Discovery:
    """Enumerate the tests under ``start_directory`` inside ``root``.

    ``root`` is the repository root, and ``top_level`` defaults to it, which is
    what makes ``tests.unit.x`` the module name rather than ``unit.x``. Every
    consumer of an identifier - the inventory, the matrix, the runner, the
    committed artifacts - depends on that spelling, so it is fixed here.
    """
    start = os.path.join(root, *start_directory.split("/"))
    if not os.path.isdir(start):
        raise DiscoveryError("no such start directory: %s" % start_directory)

    loader = unittest.TestLoader()
    try:
        suite = loader.discover(start, pattern=pattern,
                                top_level_dir=top_level or root)
    except Exception as exc:  # pragma: no cover - loader-level catastrophe
        raise DiscoveryError("discovery failed under %s: %s"
                             % (start_directory, exc)) from exc

    tests: List[DiscoveredTest] = []
    failures: List[Tuple[str, str]] = []
    for case in flatten(suite):
        test_id = case.id()
        if test_id.startswith(_LOADER_FAILURE_PREFIXES):
            failures.append((test_id.rsplit(".", 1)[-1],
                             _failure_message(case)))
            continue
        module, cls, method = _split(test_id)
        tests.append(DiscoveredTest(test_id, module, cls, method))

    # Sorted, so the artifact does not change because a filesystem enumerated
    # its directory entries in a different order.
    tests.sort(key=lambda test: test.test_id)
    duplicates = _duplicate_ids(test.test_id for test in tests)
    if duplicates:
        raise DiscoveryError(
            "duplicate test identifiers found, so results cannot be attributed "
            "to a single test: %s" % ", ".join(sorted(duplicates)))
    return Discovery(tuple(tests), tuple(sorted(failures)),
                     start_directory, pattern)


def _failure_message(case: unittest.TestCase) -> str:
    """The import error unittest wrapped in a synthetic failing test."""
    exception = getattr(case, "_exception", None)
    if exception is None:
        return "module failed to import"
    return "%s: %s" % (type(exception).__name__, exception)


def _duplicate_ids(ids: Iterable[str]) -> Sequence[str]:
    seen: Dict[str, int] = {}
    for value in ids:
        seen[value] = seen.get(value, 0) + 1
    return [value for value, count in seen.items() if count > 1]
