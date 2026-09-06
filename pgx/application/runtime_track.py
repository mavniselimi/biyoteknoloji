# -*- coding: utf-8 -*-
"""Which release track a deployment runs, chosen once and never inferred.

A deployment of this application runs exactly one of two tracks, and the
difference between them is the difference between "four named people signed
this" and "the project team is trying it out".

``GOVERNED``
    The WP-13 release registry's active pointer, a ``FrozenRuleset`` whose
    every rule carries a WP-10 approval envelope, and a claim boundary that
    reports ``is_approved`` only when the section 11 record is signed. This is
    the default, and it is the default in the strong sense: a deployment that
    says nothing gets it.

``CANDIDATE``
    ``data/releases/active-candidate-release.json``, the candidate ruleset,
    and ``P0_CANDIDATE_CLAIM_BOUNDARY`` - which reports ``is_approved`` as
    ``False`` and says ``PROJECT_TEAM_PROVISIONAL`` wherever it is displayed.

**Three rules, and each one is a way this could go wrong.**

*Chosen, never inferred.* The track comes from ``PGX_RUNTIME_TRACK`` and from
nothing else. It is not derived from which pointer files happen to exist,
because a deployment that silently became a candidate deployment when somebody
dropped a file in ``data/releases/`` is a deployment nobody chose.

*Fails closed on anything unrecognised.* An unset variable means ``GOVERNED``;
a value that is not one of the two names raises. It does not fall back to the
default, because ``PGX_RUNTIME_TRACK=candidat`` is a typo whose safe reading is
"stop", not "run the approved track" and not "run the unapproved one".

*Never both.* Nothing in this module or its callers may serve a request from
one track's release using the other track's boundary. The provider refuses the
governed capabilities in candidate mode and the candidate capabilities in
governed mode, so a route that reached for the wrong one gets a typed 503
rather than an answer assembled from two authorities.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Mapping, Optional

__all__ = [
    "DEFAULT_RUNTIME_TRACK",
    "RUNTIME_TRACK_VARIABLE",
    "RuntimeTrack",
    "RuntimeTrackError",
    "load_runtime_track",
    "parse_runtime_track",
]

#: The one variable that selects the track. Named here so the composition
#: root, the error messages and the documentation cannot disagree about it.
RUNTIME_TRACK_VARIABLE = "PGX_RUNTIME_TRACK"


class RuntimeTrackError(ValueError):
    """An unusable track selection. Never resolved to a default."""


class RuntimeTrack(str, Enum):
    """The release track a deployment serves."""

    GOVERNED = "GOVERNED"
    CANDIDATE = "CANDIDATE"

    def __str__(self) -> str:
        return self.value

    @property
    def is_candidate(self) -> bool:
        return self is RuntimeTrack.CANDIDATE


#: What a deployment that says nothing gets. The approved track, because the
#: unapproved one must be asked for.
DEFAULT_RUNTIME_TRACK = RuntimeTrack.GOVERNED


def parse_runtime_track(value: Optional[str]) -> RuntimeTrack:
    """The track named by ``value``, or the default when nothing is named.

    Raises :class:`RuntimeTrackError` for anything else - including case
    variants and surrounding whitespace beyond a strip, because a deployment
    variable that is nearly right is a deployment nobody has read.
    """
    if value is None:
        return DEFAULT_RUNTIME_TRACK
    text = value.strip()
    if not text:
        return DEFAULT_RUNTIME_TRACK
    for track in RuntimeTrack:
        if text == track.value:
            return track
    raise RuntimeTrackError(
        "%s=%r is not a runtime track; expected one of %s. This is not "
        "resolved to a default: a track nobody spelled correctly is a track "
        "nobody chose."
        % (RUNTIME_TRACK_VARIABLE, value,
           ", ".join(track.value for track in RuntimeTrack)))


def load_runtime_track(environ: Optional[Mapping[str, str]] = None
                       ) -> RuntimeTrack:
    """The track this process runs, read from the environment."""
    source = os.environ if environ is None else environ
    return parse_runtime_track(source.get(RUNTIME_TRACK_VARIABLE))
