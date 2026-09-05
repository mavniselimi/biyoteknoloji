# -*- coding: utf-8 -*-
"""Named subsets of the suite, and what each one is allowed to conclude.

A profile is a selection plus a contract. The selection says which tests run;
the contract says how many must run, how often, whether the run is allowed to
touch the network, and whether a failure blocks a release. The contract is the
half that matters: a selection alone can be satisfied by running nothing.

``minimum_tests`` exists for exactly that reason. Every profile declares a floor
that a healthy tree comfortably clears, and a run below it is an ERROR rather
than a pass. It is the cheapest defence against the failure mode where a
selector stops matching - a package is renamed, a category rule changes - and
the profile silently starts verifying an empty set at full speed.

``repeats`` is bounded on purpose. The full suite is 5,600 tests and takes four
minutes; running it three times to produce a flakiness claim would cost twelve
minutes to learn something a documented critical subset answers in seconds. So
the ``flaky`` profile repeats a named list, and the list is in this file where
it can be reviewed rather than inferred from a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from pgx.verification.errors import ProfileError
from pgx.verification.model import Category, Criticality

__all__ = [
    "PROFILE_REGISTRY_VERSION",
    "Profile",
    "PROFILES",
    "FLAKY_SUBSET_MODULES",
    "profile_named",
    "profile_names",
]

PROFILE_REGISTRY_VERSION = "pgx-wp19-profiles/1"

#: The subset the flaky and reproducibility profiles repeat. Chosen for three
#: properties: every module is on the P0 critical path, every one is fully
#: deterministic by design, and none of them needs a database, a browser or a
#: network. A module that is *meant* to vary has no place here - it would
#: manufacture a flaky report that says nothing about stability.
#: The modules the WP-20 invariant registry names, flattened. Derived from the
#: safety map rather than typed again, so a registry that gains an invariant
#: gains a profile entry without anybody remembering to add one.
def _safety_modules() -> Tuple[str, ...]:
    from pgx.verification.requirements import SAFETY_INVARIANT_MAP
    return tuple(sorted({module
                         for modules in SAFETY_INVARIANT_MAP.values()
                         for module in modules}))


SAFETY_INVARIANT_MODULES: Tuple[str, ...] = _safety_modules()

FLAKY_SUBSET_MODULES: Tuple[str, ...] = (
    "tests.safety.test_assessment_safety",
    "tests.safety.test_coverage_safety",
    "tests.unit.application.test_assessment_determinism",
    "tests.unit.domain.test_hashing",
    "tests.unit.domain.test_immutability",
    "tests.unit.engine.test_truth_matrix",
    "tests.unit.reporting.test_determinism",
    "tests.unit.rules.test_deterministic_artifacts",
    "tests.unit.snapshots.test_content_identity",
    "tests.unit.test_claims",
    "tests.unit.validation.test_separation",
)


@dataclass(frozen=True)
class Profile:
    """One named execution profile."""

    name: str
    description: str
    #: Categories to include. Empty means "every category".
    categories: Tuple[Category, ...] = ()
    #: Categories to remove after inclusion. Applied second.
    exclude_categories: Tuple[Category, ...] = ()
    #: Restrict to these module selectors. Empty means "no module restriction".
    modules: Tuple[str, ...] = ()
    #: Restrict to this criticality. ``None`` means "any".
    criticality: object = None
    #: A failing run of a required profile blocks a release.
    required: bool = True
    #: Fewer tests than this is an ERROR, never a pass.
    minimum_tests: int = 1
    #: How many times to run. Above one, differences between runs are flakiness.
    repeats: int = 1
    #: Refuse non-loopback network connections for the duration.
    offline: bool = True
    #: Run the whole tree through ``unittest discover`` rather than by test id.
    #: Only the ``full`` profile does this, so that the profile a release is
    #: judged on is byte-for-byte the command in the documentation.
    discover: bool = False
    note: str = ""

    def as_document(self) -> Dict[str, object]:
        return {
            "categories": [category.value for category in self.categories],
            "criticality": (None if self.criticality is None
                            else self.criticality.value),
            "description": self.description,
            "discover": self.discover,
            "exclude_categories": [category.value
                                   for category in self.exclude_categories],
            "minimum_tests": self.minimum_tests,
            "modules": list(self.modules),
            "name": self.name,
            "note": self.note,
            "offline": self.offline,
            "repeats": self.repeats,
            "required": self.required,
        }


#: Slow or environment-bound categories. ``fast`` removes these; nothing else
#: does, and the list is named so the removal is one decision rather than four.
_SLOW_OR_BOUND: Tuple[Category, ...] = (
    Category.POSTGRESQL_INTEGRATION,
    Category.MIGRATION,
    Category.ASGI_RUNTIME,
    Category.BROWSER_E2E,
    Category.LEGACY_REGRESSION,
)


PROFILES: Tuple[Profile, ...] = (
    Profile(
        name="fast",
        description="Everything that needs no database, no browser and no "
                    "ASGI server. The profile a developer runs before pushing.",
        exclude_categories=_SLOW_OR_BOUND,
        minimum_tests=3000,
        note="Excluding a category here does not mark it verified. The "
             "excluded categories are reported by `full` and by the gate "
             "status, where their real state - executed or BLOCKED - is said.",
    ),
    Profile(
        name="p0",
        description="Every test the inventory marks P0_CRITICAL, whatever "
                    "category it is in.",
        criticality=Criticality.P0_CRITICAL,
        minimum_tests=3000,
        note="Includes the PostgreSQL tests, which will report BLOCKED where "
             "no server is reachable. That is the point: a critical profile "
             "that quietly dropped them would look healthier than it is.",
    ),
    Profile(
        name="runtime",
        description="The ASGI application and the browser end-to-end suite - "
                    "the parts that need a real server or a real browser.",
        categories=(Category.ASGI_RUNTIME, Category.BROWSER_E2E),
        minimum_tests=40,
        note="Skips here are permitted and classified: the ASGI suite carries "
             "an inverted skip that stands down when the framework is present.",
    ),
    Profile(
        name="database",
        description="PostgreSQL integration and the migration lifecycle.",
        categories=(Category.POSTGRESQL_INTEGRATION, Category.MIGRATION),
        required=False,
        minimum_tests=60,
        note="Not required, because no PostgreSQL exists in every environment "
             "and a required profile that cannot run would make every release "
             "blocked for a reason unrelated to the software. Its real state "
             "is reported by the gate status as BLOCKED, which is not a pass.",
    ),
    Profile(
        name="full",
        description="The whole suite, discovered exactly as the documented "
                    "command discovers it.",
        discover=True,
        minimum_tests=5000,
        note="`python -m unittest discover -s tests -p 'test_*.py' -t .` and "
             "this profile must find the same tests. If they ever disagree, "
             "the inventory is describing a different suite than the one that "
             "runs, and every other number here is suspect.",
    ),
    Profile(
        name="validation",
        description="WP-18's partition suite and WP-21's benchmark suite - "
                    "everything that decides which cases may be counted and "
                    "what a metric may say about them.",
        modules=("tests.unit.validation", "tests.unit.benchmark",
                 "tests.integration.validation"),
        minimum_tests=350,
        note="Passing this is not a validation result. It says the partition "
             "holds and the arithmetic is right; the repository still has "
             "zero holdout cases and no benchmarked release, which is what "
             "`pgx-benchmark gate-status` reports and no profile can change.",
    ),
    Profile(
        name="safety",
        description="Every test module the WP-20 invariant registry names - "
                    "the safe controls for all twelve safety invariants.",
        modules=SAFETY_INVARIANT_MODULES,
        minimum_tests=300,
        note="This profile runs the invariants' *safe* controls. It does not "
             "run their negative controls, and passing it is therefore NOT "
             "the safety gate: a detector that accepted its mutant would pass "
             "here and fail `pgx-safety check`. The gate is WP-20's, and its "
             "measured state is reported by the WP-19 gate status rather than "
             "inferred from this profile.",
    ),
    Profile(
        name="expert-review",
        description="WP-22's blind review suite: the state machine, the "
                    "blinding structure, the authorisation boundary, the "
                    "append-only records and the rendered reviewer workflow.",
        modules=("tests.unit.expert_review",
                 "tests.unit.web.test_expert_review_flow"),
        minimum_tests=150,
        note="Passing this says the software records a blind review "
             "correctly. It is not an expert review and does not become one: "
             "every test here runs against a TEST-ONLY approved protocol "
             "constructed inside the suite, because the real protocol is a "
             "draft that no code path can approve. The repository still has "
             "zero expert-holdout cases, zero named reviewers and zero "
             "completed reviews, which is what `pgx-expert-review "
             "gate-status` reports and no profile can change.",
    ),
    Profile(
        name="security",
        description="WP-23's authentication, session, RBAC, CSRF, rate-limit "
                    "and governed-audit suite.",
        modules=("tests.unit.security", "tests.unit.audit"),
        minimum_tests=180,
        note="Passing this says the security software behaves as its tests "
             "describe. It is not a penetration test, a security audit or a "
             "certification, and it says nothing about whether any "
             "deployment is configured: this repository has no database, no "
             "Argon2 package, no HTTPS termination and no user account, "
             "which is what `pgx-security gate-status` reports and no "
             "profile can change.",
    ),
    Profile(
        name="deployment",
        description="WP-24's composition, container, packaging, CI and "
                    "honest-reporting suite.",
        modules=("tests.unit.deployment",),
        minimum_tests=120,
        note="Passing this says the deployment software behaves as its tests "
             "describe. It is not a deployment. This repository has no "
             "container runtime, no package index, no PostgreSQL server, no "
             "built image, no staging endpoint and no CI run, which is what "
             "`pgx-deploy release-validation` reports and no profile can "
             "change.",
    ),
    Profile(
        name="ths6",
        description="WP-25's evidence pack: registries, gate matrix, "
                    "Definition of Done, demo preflight, pack integrity and "
                    "the CLI.",
        modules=("tests.unit.ths6",),
        minimum_tests=100,
        note="Passing this says the evidence pack software behaves as its "
             "tests describe. It is not THS 6. This repository has no "
             "approved source, no published dataset, no executable ruleset, "
             "no validation case, no completed expert review, no database "
             "and no deployment, which is what `pgx-ths6 status` reports "
             "with all six gates BLOCKED, and no profile can change it.",
    ),
    Profile(
        name="reproducibility",
        description="The deterministic critical subset, run twice, with the "
                    "two result sets compared byte for byte.",
        modules=FLAKY_SUBSET_MODULES,
        repeats=2,
        minimum_tests=200,
        note="Two runs answer 'is this deterministic'. Three answer 'is this "
             "flaky', which is what the `flaky` profile is for.",
    ),
    Profile(
        name="flaky",
        description="The same deterministic critical subset, run three times, "
                    "with any test that did not agree with itself reported.",
        modules=FLAKY_SUBSET_MODULES,
        repeats=3,
        minimum_tests=200,
        note="A test that passes twice and fails once is reported as flaky, "
             "not as a majority pass. Durations and timestamps are excluded "
             "from the comparison, so a slow run is never a difference.",
    ),
)

_BY_NAME: Mapping[str, Profile] = {profile.name: profile
                                   for profile in PROFILES}


def profile_names() -> Tuple[str, ...]:
    """Every profile name, in registry order."""
    return tuple(profile.name for profile in PROFILES)


def profile_named(name: str) -> Profile:
    """The profile called ``name``.

    Raises rather than falling back to a default: a typo that silently ran
    ``fast`` instead of ``full`` would produce a green result for a profile
    nobody executed.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise ProfileError(
            "unknown profile %r; known profiles are %s"
            % (name, ", ".join(profile_names()))) from None
