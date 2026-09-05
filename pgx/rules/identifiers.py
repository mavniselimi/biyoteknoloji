# -*- coding: utf-8 -*-
"""Rule and ruleset identities (WP-11).

Extends WP-02's typed-identifier family rather than inventing a parallel one.
``ComputableRuleId`` and ``RulesetVersionId`` already exist in
:mod:`pgx.domain.identifiers` and are re-exported here so a reader of this
package finds them where they expect; the two new types are added beside them.

**Identity is never derived from content.** ``EntityId.new()`` mints a random
UUID and that is the only way a rule or ruleset comes into existence. A UUID5
derived from a rule's condition would look convenient and would be wrong: two
scientifically distinct rules that happened to normalise to the same text would
collide on one row, and a corrected rule would silently inherit the identity -
and therefore the approvals - of the rule it replaced. WP-02 restricts UUID5
derivation to ``SourceRegistryEntryId`` for exactly this reason, and WP-11 does
not widen it.

**Version lineage is explicit.** A ``RuleFamilyId`` names the scientific
question a rule answers; ``rule_version`` numbers the successive answers to it.
A change to a validated rule's condition or outcome is a new version in the
same family, never an edit, so the approval that was given to version 2 cannot
be read as covering version 3.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import ClassVar

from pgx.domain.errors import InvalidIdentifierError
from pgx.domain.identifiers import (ComputableRuleId, EntityId,
                                    RulesetPublicId, RulesetVersionId,
                                    require_id)

__all__ = [
    "ComputableRuleId",
    "RuleFamilyId",
    "RulesetBuildId",
    "RulesetPublicId",
    "RulesetVersionId",
    "require_id",
]


@dataclass(frozen=True, slots=True)
class RuleFamilyId(EntityId):
    """Stable identity of one rule's version lineage.

    Every version of a rule shares its family. "Is this the current answer to
    that question?" is answered by family plus version; "was this exact content
    approved?" is answered by the content hash. Keeping the two separate is
    what lets a rule be superseded without pretending the old one never
    existed.
    """

    entity_name: ClassVar[str] = "rule family"


@dataclass(frozen=True, slots=True)
class RulesetBuildId(EntityId):
    """Identity of one build attempt of one ruleset.

    A ruleset may be built more than once - a build can fail validation, or be
    re-run to confirm determinism - and each attempt is a separate record with
    its own log. The build identity is operational; the *semantic* identity of
    what was built is the ruleset hash, and the two must not be confused.
    """

    entity_name: ClassVar[str] = "ruleset build"
