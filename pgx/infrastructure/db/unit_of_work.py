# -*- coding: utf-8 -*-
"""Transaction boundary and commit-time invariant validation (WP-02, WP-03).

Repositories stage work; this class decides the outcome. Two behaviours matter:

* **Rollback by default.** Leaving the context without calling :meth:`commit`
  rolls back, so a forgotten commit cannot leave a half-written aggregate.
* **Cross-row validation before commit.** Some invariants cannot be expressed
  as a single-row ``CHECK``. The clearest example is ``SAFETY-INV-006``: a
  ``VALIDATED`` rule must have at least one ``rule_evidence`` row, which is a
  fact about two tables. PostgreSQL could enforce this with a deferred
  constraint trigger; WP-02 enforces it here instead, and
  ``docs/architecture/wp02-domain-and-db.md`` records exactly which layer owns
  which invariant so nothing is reported as "database enforced" when it is not.

A second rule enforced here, ``SAFETY-INV-003``: a ``VALIDATED`` rule may only
point at a ``CURATED`` interpretation. Promoting a rule above the review status
of its own interpretation would make the curation workflow decorative.
"""

from __future__ import annotations

from types import TracebackType
from typing import Optional, Type

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from pgx.domain.errors import LifecycleError, TraceabilityError
from pgx.infrastructure.db.models import (
    ComputableRuleORM,
    CuratedInterpretationORM,
    RuleEvidenceORM,
)
from pgx.infrastructure.db.assessments import (
    SqlAlchemyAssessmentRepository,
)
from pgx.infrastructure.db.repositories import (
    SqlAlchemyActiveReleaseRepository,
    SqlAlchemyAuditEventRepository,
    SqlAlchemyDatasetVersionRepository,
    SqlAlchemyDrugRepository,
    SqlAlchemyEvidenceRepository,
    SqlAlchemyGeneRepository,
    SqlAlchemyInterpretationRepository,
    SqlAlchemyReleaseBundleRepository,
    SqlAlchemyRuleRepository,
    SqlAlchemyRulesetVersionRepository,
    SqlAlchemySoftwareVersionRepository,
    SqlAlchemySourceRegistryRepository,
)

__all__ = ["SqlAlchemyUnitOfWork"]


class SqlAlchemyUnitOfWork:
    """Own one session and one transaction.

    Usage::

        with SqlAlchemyUnitOfWork(session_factory) as uow:
            uow.genes.add(gene)
            uow.commit()
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Optional[Session] = None
        self._committed = False

    # -- context management ---------------------------------------------

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        self._committed = False
        self.source_registry = SqlAlchemySourceRegistryRepository(self._session)
        self.genes = SqlAlchemyGeneRepository(self._session)
        self.drugs = SqlAlchemyDrugRepository(self._session)
        self.evidence = SqlAlchemyEvidenceRepository(self._session)
        self.interpretations = SqlAlchemyInterpretationRepository(self._session)
        self.rules = SqlAlchemyRuleRepository(self._session)
        # WP-03 release registry.
        self.software_versions = SqlAlchemySoftwareVersionRepository(self._session)
        self.dataset_versions = SqlAlchemyDatasetVersionRepository(self._session)
        self.ruleset_versions = SqlAlchemyRulesetVersionRepository(self._session)
        self.releases = SqlAlchemyReleaseBundleRepository(self._session)
        self.active_release = SqlAlchemyActiveReleaseRepository(self._session)
        self.audit = SqlAlchemyAuditEventRepository(self._session)
        # WP-14. Append-only: the repository offers no update and no delete,
        # and migration 0009 installs triggers refusing both, so an assessment
        # committed here cannot be edited afterwards by anything.
        self.assessments = SqlAlchemyAssessmentRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        try:
            if not self._committed:
                self.rollback()
        finally:
            if self._session is not None:
                self._session.close()
                self._session = None

    # -- transaction control --------------------------------------------

    @property
    def session(self) -> Session:
        """The active session. Raises when used outside the context."""
        if self._session is None:
            raise RuntimeError(
                "SqlAlchemyUnitOfWork must be used as a context manager: "
                "`with SqlAlchemyUnitOfWork(factory) as uow:`")
        return self._session

    def commit(self) -> None:
        """Validate cross-row invariants, then commit.

        Raises:
            TraceabilityError: a VALIDATED rule has no evidence link.
            LifecycleError: a VALIDATED rule points at an interpretation that is
                not CURATED.
        """
        session = self.session
        session.flush()
        self._validate_cross_row_invariants(session)
        session.commit()
        self._committed = True

    def rollback(self) -> None:
        """Discard staged work."""
        if self._session is not None:
            self._session.rollback()

    # -- commit-time invariants -----------------------------------------

    @staticmethod
    def _validate_cross_row_invariants(session: Session) -> None:
        """Reject states no single-row CHECK constraint can catch."""
        # SAFETY-INV-006: a VALIDATED rule must cite evidence.
        evidence_count = (
            select(func.count(RuleEvidenceORM.evidence_record_id))
            .where(RuleEvidenceORM.rule_id == ComputableRuleORM.id)
            .correlate(ComputableRuleORM)
            .scalar_subquery()
        )
        unbacked = session.execute(
            select(ComputableRuleORM.id)
            .where(ComputableRuleORM.status == "VALIDATED")
            .where(evidence_count == 0)
            .order_by(ComputableRuleORM.id)
        ).scalars().all()
        if unbacked:
            raise TraceabilityError(
                "VALIDATED rule(s) %s have no rule_evidence row. Every calculated "
                "finding must be traceable to evidence (SAFETY-INV-006), so a "
                "validated rule without evidence may not be committed."
                % ", ".join(str(rule_id) for rule_id in unbacked))

        # SAFETY-INV-003: a VALIDATED rule needs a CURATED interpretation.
        uncurated = session.execute(
            select(ComputableRuleORM.id)
            .join(CuratedInterpretationORM,
                  CuratedInterpretationORM.id == ComputableRuleORM.interpretation_id)
            .where(ComputableRuleORM.status == "VALIDATED")
            .where(CuratedInterpretationORM.status != "CURATED")
            .order_by(ComputableRuleORM.id)
        ).scalars().all()
        if uncurated:
            raise LifecycleError(
                "VALIDATED rule(s) %s are attached to an interpretation that is not "
                "CURATED. A rule may not outrank the review status of the "
                "interpretation it derives from (SAFETY-INV-003)."
                % ", ".join(str(rule_id) for rule_id in uncurated))
