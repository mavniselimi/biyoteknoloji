# -*- coding: utf-8 -*-
"""A whole synthetic interface, composed over the WP-14 synthetic world.

**Nothing here is real.** The cases are the migrated development catalogue,
the assessments are calculated by the real engine over synthetic governed
artifacts, and the principals are test doubles. No page produced from these
fixtures is a pharmacogenomic assessment of anyone, and none may be presented
as one.

The provider is a real :class:`~apps.web.dependencies.WebProvider` over a real
:class:`~apps.web.client.InProcessApiClient`, so a test that goes through it
exercises the actual path: real adapters, real service, real engine, real
contract validation, real templates and the real claim gate.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

from apps.api.provider import ServiceProvider
from apps.web.client import InProcessApiClient, PgxApiClient
from apps.web.config import WebSettings, load_web_settings
from apps.web.dependencies import WebProvider
from apps.web.demo_cases import (DevelopmentCase,
                                 PhenotypeObservationRecord,
                                 parse_catalog)
from apps.web.demo_migration import build_catalog
from apps.web.pages import PageEnvironment
from apps.web.security import CsrfVerifier, StaticTokenCsrfVerifier
from apps.api.security import Principal, Role
from pgx.application.execution_context import (ExecutionChannel,
                                               ExecutionContext)

#: Carried by everything this module builds, so an artifact that escapes a
#: test can be recognised for what it is.
SYNTHETIC_MARKER = "TEST-SYNTHETIC-WP17"

TEST_REQUEST_ID = "11111111-1111-4111-8111-111111111111"

#: A development CSRF token. Not a defence - a single fixed value protects
#: nothing - and refused in production by WebSettings. It exists so the
#: synthetic flow exercises the real verification path rather than skipping it.
TEST_CSRF_TOKEN = "TEST-CSRF-TOKEN-WP17-0001"

DEMO_PRINCIPAL = Principal(actor="TEST-demo-user-1", role=Role.DEMO_USER,
                           authenticated_by="static-token/1")
REVIEWER_PRINCIPAL = Principal(actor="TEST-reviewer-1",
                               role=Role.EXPERT_REVIEWER,
                               authenticated_by="static-token/1")


def test_web_settings(**overrides: Any) -> WebSettings:
    """Settings for a test interface: never production, never connected."""
    from tests.unit.api._support import test_settings

    values = {"PGX_API_ENV": "TEST", "PGX_API_AUTH_MODE": "STATIC_TOKEN",
              "PGX_WEB_LOCALE": "tr"}
    values.update({key: str(value) for key, value in overrides.items()})
    return load_web_settings(values, api=test_settings())


def development_cases() -> Tuple[DevelopmentCase, ...]:
    """The migrated catalogue, built in memory rather than read from disk.

    Built so a test does not depend on the sealed artifact having been
    regenerated, and so the migration itself is exercised on every run.
    """
    return parse_catalog(build_catalog())


def case_by_id(case_id: str) -> DevelopmentCase:
    for case in development_cases():
        if case.case_id == case_id:
            return case
    if case_id == COVERED_FIXTURE_CASE.case_id:
        return COVERED_FIXTURE_CASE
    raise KeyError(case_id)


def _covered_fixture_case() -> DevelopmentCase:
    """A case the synthetic world can actually cover.

    The six migrated cases name real genes - CYP2C19, CYP2D6 and so on -
    because that is what the legacy profiles contain. The WP-14 synthetic
    world's governed ruleset covers ``TESTGENE`` axes, so a migrated case
    assessed against it comes back ``INSUFFICIENT`` with
    ``PHENOTYPE_NOT_PROVIDED``: the axis *is* governed, the profile simply
    says nothing about that gene, so the observation is ``ABSENT``. (It is not
    ``NO_VALIDATED_RULE_FOR_AXIS``, which would mean the opposite - a gene the
    profile does describe and the release does not govern.) That is the
    correct answer and it is worth demonstrating - but a flow that could
    *only* produce it would never exercise a finding, an evidence link or a
    rule trace.

    So this case exists: same contract, same labels, same DEVELOPMENT role,
    genes chosen to match the synthetic ruleset. It lives in the fixtures and
    is deliberately **not** in the shipped catalogue, because the shipped
    catalogue describes what was migrated and this was not migrated from
    anything.
    """
    from tests.fixtures.wp13.synthetic import GENE_1, GENE_2

    return DevelopmentCase(
        case_id="WP17-CASE-FIXTURE-COVERED",
        label="Sentetik kural kümesiyle eşleşen gösterim profili",
        case_role="DEVELOPMENT",
        is_synthetic=True,
        is_validation_evidence=False,
        is_holdout=False,
        observations=tuple(sorted(
            (PhenotypeObservationRecord(gene=GENE_1, value="POOR"),
             PhenotypeObservationRecord(gene=GENE_2, value="POOR")),
            key=lambda item: item.gene)),
        legacy_profile_key=None,
        source_file=None,
        source_file_sha256=None,
        migration_note=("Bu vaka taşınmadı; sentetik kural kümesinin "
                        "kapsadığı eksenleri göstermek için test "
                        "düzeneğinde yazıldı. Yayımlanan katalogda yer "
                        "almaz."),
        demonstrates=("Sentetik sürümün kapsadığı gen-ilaç eksenlerinde "
                      "bulgu üretilen profil."),
        no_pii_assertion=("Bu vaka sentetiktir. Hiçbir gerçek kişiye ait "
                          "veri, tanımlayıcı veya klinik metin içermez."))


#: Built once; a frozen value, so no test can alter it for another.
COVERED_FIXTURE_CASE = _covered_fixture_case()


def synthetic_web_provider(world: Any, *,
                           settings: Optional[WebSettings] = None,
                           with_client: bool = True,
                           with_cases: bool = True,
                           with_csrf: bool = False,
                           api_provider: Optional[ServiceProvider] = None
                           ) -> WebProvider:
    """A web provider over the WP-14 synthetic world.

    Each capability can be withheld, because "this deployment does not have
    one" is a state every page has to answer correctly and is the state this
    repository is actually in.
    """
    from tests.fixtures.wp16.synthetic import synthetic_provider
    from tests.unit.api._support import test_settings

    web_settings = settings or test_settings_web()
    api = api_provider or synthetic_provider(world,
                                             settings=web_settings.api)
    client: PgxApiClient
    if with_client:
        client = InProcessApiClient(api)
    else:
        from apps.web.client import UnavailableApiClient
        client = UnavailableApiClient()

    csrf: CsrfVerifier
    if with_csrf:
        csrf = StaticTokenCsrfVerifier(TEST_CSRF_TOKEN)
    else:
        from apps.web.security import UnconfiguredCsrf
        csrf = UnconfiguredCsrf()

    return WebProvider(
        settings=web_settings,
        client=client,
        csrf=csrf,
        case_catalog=development_cases if with_cases else None)


def synthetic_providers(world: Any, **kwargs: Any
                        ) -> Tuple[WebProvider, ServiceProvider]:
    """Both providers an application needs, composed against one world.

    ``WebProvider`` alone is not enough to serve a page. Every page route is
    guarded by WP-16's ``require_access``, which resolves a principal through
    the API's ``ServiceProvider`` on ``app.state.provider`` - so a test that
    built only the web half got ``SERVICE_NOT_READY`` on every route,
    including the public ones, because FastAPI resolves that dependency
    before the handler decides whether the route is public.

    Returned as a pair rather than hidden inside the web provider: they are
    two objects with two owners, and a caller composing an application has to
    hand both to ``create_web_app``. ``WebProvider`` is frozen and slotted, so
    there is nowhere to smuggle the second one anyway - which is the right
    answer rather than an obstacle.
    """
    from tests.fixtures.wp16.synthetic import synthetic_provider
    from tests.unit.api._support import test_settings

    settings = kwargs.pop("settings", None) or test_settings_web()
    api = kwargs.pop("api_provider", None) or synthetic_provider(
        world, settings=settings.api)
    web = synthetic_web_provider(world, settings=settings, api_provider=api,
                                 **kwargs)
    return web, api


def test_settings_web(**overrides: Any) -> WebSettings:
    """Alias kept short for call sites; see :func:`test_web_settings`."""
    return test_web_settings(**overrides)


def page_environment(**overrides: Any) -> PageEnvironment:
    values = {"environment": "TEST", "request_id": TEST_REQUEST_ID,
              "locale": "tr", "asset_version": "1"}
    values.update(overrides)
    return PageEnvironment(**values)


def execution_context(principal: Principal = DEMO_PRINCIPAL,
                      request_id: str = TEST_REQUEST_ID) -> ExecutionContext:
    return ExecutionContext(actor=principal.actor,
                            role=principal.role.value,
                            channel=ExecutionChannel.API,
                            request_id=request_id,
                            authenticated_by=principal.authenticated_by)
