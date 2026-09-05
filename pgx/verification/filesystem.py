# -*- coding: utf-8 -*-
"""Whether a sealed tree is genuinely refused to an ordinary writer.

WP-06 seals a raw snapshot by setting every file to ``0o444``. The test that
proved it did two things at once: it asserted the mode bits, and it asserted
that appending raised ``PermissionError``. On a normal account both hold. As
``uid 0`` the second does not - the kernel exempts the superuser from mode-bit
checks - so the suite failed for a reason that had nothing to do with the
snapshot being mutable.

The wrong repairs are easy to name. Deleting the mutation attempt leaves the
mode bits asserted and nothing else. Skipping whenever the assertion is
inconvenient hides the case where a tree really is writable. Relaxing to
"PermissionError or success" asserts nothing at all.

What this module does instead is separate two questions the old test conflated,
and it is careful about a third that is easy to get wrong.

1. **Are the mode bits right?** ``denies_all_writers`` answers this from the
   bits alone: no write bit for owner, group or other. Always answerable
   wherever ``chmod`` sticks, and never skipped there. It is a stricter check
   than ``== 0o444``, because it is the property that is actually meant.

2. **Is a writer subject to those bits refused?** Answered by an attempt. When
   the current user is subject to mode bits the attempt is made directly. When
   it is not - running as root - the attempt is made by a genuinely
   unprivileged forked child.

3. **Was the attempt able to tell the difference?** This is the subtle one. A
   child running as ``nobody`` is refused by a ``0o644`` file too, because it
   is not the owner. An attempt like that reports ``REFUSED`` for a tree that
   its owner could rewrite at will, which is exactly the false confidence this
   module exists to prevent. So an attempt is only ``discriminating`` when the
   writer is the file's **owner** - the strictest reader of the bits, and the
   account that would actually do the accidental rewrite.

To make the root case discriminating, ``may_take_ownership`` lets the probe
hand a **test-created temporary file** to the unprivileged account for the
duration of the attempt and hand it back afterwards. That flag defaults to
``False`` and is passed only by tests that built the tree themselves. Nothing
here chmods or chowns a production artifact to make an assertion pass: the only
permissions this module changes belong to probe files it created, or to a file
the caller has explicitly declared to be its own scratch.

The probe never writes. It opens for append and closes; a zero-byte append
leaves content and modification time untouched.
"""

from __future__ import annotations

import errno
import io
import os
import stat
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

try:  # pragma: no cover - present on POSIX, absent on Windows
    import pwd
except ImportError:  # pragma: no cover - Windows
    pwd = None  # type: ignore[assignment]

__all__ = [
    "MutationOutcome",
    "MutationAttempt",
    "chmod_is_honoured",
    "denies_all_writers",
    "mode_bits_restrict_current_user",
    "unprivileged_account",
    "attempt_append_here",
    "attempt_append_as_owner_unprivileged",
    "attempt_unprivileged_mutation",
    "file_mode",
]

#: Accounts tried, in order, when privileges must be dropped. A candidate whose
#: uid or gid is 0 is rejected: an account named ``nobody`` that happened to be
#: the superuser would produce a confident and completely wrong ``REFUSED``.
_UNPRIVILEGED_CANDIDATES: Tuple[str, ...] = ("nobody", "nfsnobody", "daemon")

#: The write bits, for owner, group and other together.
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH

# Child exit codes. Small integers because that is all a process can return,
# and named because a bare 2 in a waitpid status is unreadable.
_CHILD_REFUSED = 0
_CHILD_PERMITTED = 1
_CHILD_UNREACHABLE = 2
_CHILD_SETUP_FAILED = 3


class MutationOutcome(str, Enum):
    """What an attempt to mutate a sealed artifact produced."""

    #: The operating system refused the write.
    REFUSED = "REFUSED"
    #: The write was permitted.
    PERMITTED = "PERMITTED"
    #: No meaningful attempt could be made here.
    NOT_ATTEMPTABLE = "NOT_ATTEMPTABLE"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class MutationAttempt:
    """The result of one mutation attempt, and how much it is worth.

    ``method`` and ``writer_is_owner`` are part of the evidence, not decoration.
    ``REFUSED`` by a non-owner is a much weaker claim than ``REFUSED`` by the
    owner, and the two are never reported the same way.
    """

    outcome: MutationOutcome
    #: ``direct`` | ``dropped-privileges`` | ``none``
    method: str
    detail: str
    #: Whether the writing process owned the file. Only an owner's refusal
    #: proves the bits deny writing rather than merely denying strangers.
    writer_is_owner: bool = False

    @property
    def discriminating(self) -> bool:
        """True when this attempt could have told a writable tree apart.

        An attempt that would have said ``REFUSED`` either way tells the caller
        nothing, and callers must not treat it as if it did.
        """
        return (self.outcome is not MutationOutcome.NOT_ATTEMPTABLE
                and self.writer_is_owner)


def file_mode(path: str) -> int:
    """The permission bits of ``path``, with the file-type bits removed."""
    return stat.S_IMODE(os.stat(path).st_mode)


def denies_all_writers(path: str) -> bool:
    """True when no write bit is set for owner, group or other.

    This is the representation half of the invariant, and it is checkable
    everywhere ``chmod`` is honoured, with no privilege question attached.
    """
    return (file_mode(path) & _WRITE_BITS) == 0


def chmod_is_honoured(directory: str) -> bool:
    """True when this filesystem keeps a ``chmod`` it was given.

    Some network mounts accept the call and ignore it. Asserting a mode there
    fails for a reason that has nothing to do with the code under test, which
    is the one case where skipping is the honest answer.
    """
    handle, probe = tempfile.mkstemp(prefix="chmod-probe-", dir=directory)
    os.close(handle)
    try:
        os.chmod(probe, 0o444)
        return file_mode(probe) == 0o444
    finally:
        _discard(probe)


def attempt_append_here(path: str) -> MutationOutcome:
    """Try to open ``path`` for append in this process, and close it again.

    Nothing is written, so a permitted attempt leaves the file byte-identical
    and its modification time unchanged. The handle is closed on both paths -
    the original test leaked one every time it failed, which is how a
    ``ResourceWarning`` ended up in the suite output.
    """
    try:
        handle = io.open(path, "ab")
    except PermissionError:
        return MutationOutcome.REFUSED
    except OSError as exc:  # pragma: no cover - platform dependent
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
            return MutationOutcome.REFUSED
        raise
    handle.close()
    return MutationOutcome.PERMITTED


def mode_bits_restrict_current_user(directory: str) -> bool:
    """True when a ``0o444`` file this user owns refuses *this* user.

    False for root on POSIX and for most accounts on Windows. This is the
    question the old test assumed the answer to. The probe file is created by
    this process, so it is owned by it, which makes the answer the owner's.
    """
    handle, probe = tempfile.mkstemp(prefix="restrict-probe-", dir=directory)
    os.close(handle)
    try:
        os.chmod(probe, 0o444)
        if file_mode(probe) != 0o444:
            return False
        return attempt_append_here(probe) is MutationOutcome.REFUSED
    finally:
        _discard(probe)


def unprivileged_account() -> Optional[Tuple[str, int, int]]:
    """A non-root account this process could drop to, or ``None``."""
    if pwd is None or not hasattr(os, "fork") or not hasattr(os, "setuid"):
        return None
    for name in _UNPRIVILEGED_CANDIDATES:
        try:
            record = pwd.getpwnam(name)
        except KeyError:
            continue
        if record.pw_uid != 0 and record.pw_gid != 0:
            return (name, record.pw_uid, record.pw_gid)
    return None


def attempt_append_as_owner_unprivileged(path: str) -> MutationAttempt:
    """Hand ``path`` to an unprivileged account and let it try to append.

    Only for a file the caller created as scratch. Ownership is transferred
    before the attempt and restored after it, in a ``finally``, so an
    interrupted probe cannot leave a test file owned by ``nobody``. The mode
    bits are never touched - transferring ownership is what makes the attempt
    *discriminating*, and changing the bits would make it meaningless.

    ``UNREACHABLE`` is reported separately from ``REFUSED``: if the account
    cannot traverse to the file, the refusal came from the path rather than
    from the file, and calling that evidence of immutability would be wrong.
    """
    account = unprivileged_account()
    if account is None:
        return MutationAttempt(
            MutationOutcome.NOT_ATTEMPTABLE, "none",
            "no non-root account is available to drop privileges to")
    if os.geteuid() != 0:
        return MutationAttempt(
            MutationOutcome.NOT_ATTEMPTABLE, "none",
            "privileges can only be dropped by a privileged process")

    name, uid, gid = account
    before = os.stat(path)
    try:
        os.chown(path, uid, gid)
    except OSError:
        return MutationAttempt(
            MutationOutcome.NOT_ATTEMPTABLE, "none",
            "ownership of the probe file could not be transferred to %s" % name)
    try:
        code = _forked_append(path, uid, gid)
    finally:
        try:
            os.chown(path, before.st_uid, before.st_gid)
        except OSError:  # pragma: no cover - only if the tree vanished
            pass

    if code == _CHILD_REFUSED:
        return MutationAttempt(
            MutationOutcome.REFUSED, "dropped-privileges",
            "an unprivileged owner was refused the append", True)
    if code == _CHILD_PERMITTED:
        return MutationAttempt(
            MutationOutcome.PERMITTED, "dropped-privileges",
            "an unprivileged owner was permitted to append", True)
    if code == _CHILD_UNREACHABLE:
        return MutationAttempt(
            MutationOutcome.NOT_ATTEMPTABLE, "dropped-privileges",
            "the unprivileged account cannot traverse to the path, so its "
            "refusal would say nothing about the file", False)
    return MutationAttempt(
        MutationOutcome.NOT_ATTEMPTABLE, "dropped-privileges",
        "privileges could not be dropped to %s" % name, False)


def _forked_append(path: str, uid: int, gid: int) -> int:
    """Fork, drop to ``uid``/``gid``, attempt the append, return an exit code.

    The child calls ``os._exit`` so inherited stdio buffers are not flushed a
    second time and no cleanup handler belonging to the parent's test run fires
    in a process that is about to disappear.
    """
    pid = os.fork()
    if pid == 0:  # pragma: no cover - the child never returns to the runner
        code = _CHILD_SETUP_FAILED
        try:
            try:
                os.setgroups([])
            except OSError:
                pass
            os.setgid(gid)
            os.setuid(uid)
            if os.geteuid() != uid or os.geteuid() == 0:
                os._exit(_CHILD_SETUP_FAILED)
            try:
                os.stat(path)
            except OSError:
                os._exit(_CHILD_UNREACHABLE)
            code = (_CHILD_REFUSED
                    if attempt_append_here(path) is MutationOutcome.REFUSED
                    else _CHILD_PERMITTED)
        except BaseException:
            code = _CHILD_SETUP_FAILED
        os._exit(code)

    _, status = os.waitpid(pid, 0)
    if not os.WIFEXITED(status):  # pragma: no cover - signal path
        return _CHILD_SETUP_FAILED
    return os.WEXITSTATUS(status)


def attempt_unprivileged_mutation(path: str,
                                  probe_directory: Optional[str] = None,
                                  may_take_ownership: bool = False
                                  ) -> MutationAttempt:
    """Attempt the mutation in whatever way is actually meaningful here.

    Order matters and is the whole design:

    1. If mode bits restrict this user, attempt directly. This process created
       nothing and owns nothing it should not; it is simply subject to the
       bits, which is the common case on a developer machine and in CI. The
       attempt is discriminating when this process owns the file.
    2. Otherwise, if ``may_take_ownership`` and privileges can be dropped,
       attempt as a real unprivileged **owner**. This is the root case, and it
       converts what used to be a failure into an executed assertion.
    3. Otherwise report ``NOT_ATTEMPTABLE`` with the reason. Windows, a root
       process looking at a production artifact it must not chown, and
       restricted containers land here - a narrow, named capability gap rather
       than a claim.

    ``probe_directory`` is where the capability probe writes its own scratch
    file. It defaults to the directory holding ``path``, which is usually
    read-only once sealed, so callers testing a sealed tree pass a writable
    directory outside it. The probe never writes inside the sealed tree.

    ``may_take_ownership`` must be passed only for a file the caller created as
    scratch. It is never true for a committed artifact.
    """
    directory = probe_directory or os.path.dirname(os.path.abspath(path))
    try:
        restricted = mode_bits_restrict_current_user(directory)
    except OSError:
        restricted = False
    if restricted:
        outcome = attempt_append_here(path)
        return MutationAttempt(
            outcome, "direct",
            "this user is subject to mode bits and the append was %s"
            % ("refused" if outcome is MutationOutcome.REFUSED
               else "permitted"),
            _owned_by_current_user(path))
    if not may_take_ownership:
        return MutationAttempt(
            MutationOutcome.NOT_ATTEMPTABLE, "none",
            "this user is not subject to mode bits, and taking ownership of "
            "the file to arrange an unprivileged attempt was not permitted",
            False)
    return attempt_append_as_owner_unprivileged(path)


def _owned_by_current_user(path: str) -> bool:
    """Whether this process's effective uid owns ``path``."""
    try:
        return os.stat(path).st_uid == os.geteuid()
    except (OSError, AttributeError):  # pragma: no cover - platform dependent
        return False


def _discard(path: str) -> None:
    """Remove a probe file this module created, restoring write access first."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    try:
        os.unlink(path)
    except OSError:
        pass
