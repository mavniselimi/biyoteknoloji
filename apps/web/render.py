"""The template environment, and the one way a page is produced.

Four properties, each set here so no template has to remember it.

**Autoescaping is unconditional.** Not selected by file extension, not
switchable per template. Every value a view model carries came from an API
response, and some of those values - a case label, a source label on an
evidence link - originated outside this system.

**Undefined is an error.** A template that names a field the view model does
not carry raises rather than rendering an empty string. A silently blank cell
where a governed code belongs is exactly the failure this whole layer exists
to prevent, and it is invisible in review.

**The environment is sandboxed.** Templates here are written in this
repository and reviewed, so the sandbox is not defending against a hostile
template author; it is defending against the day someone adds a template
feature that walks an object graph, and it costs nothing today.

**The template list is fixed.** :data:`TEMPLATE_NAMES` is the whole set. A
name outside it is refused before the loader is asked, so a page name assembled
from a request cannot reach the filesystem.

Jinja2 is imported lazily. It is present in the environment this was built in -
so the tests really render, really scan the resulting HTML and really parse its
structure - but a deployment that installs only the API extra can still import
this module, and gets a clear refusal rather than an ImportError at start-up.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Tuple

from apps.web import DEFAULT_LOCALE
from apps.web.claim_gate import PageSafetyError, require_safe_page

__all__ = [
    "TEMPLATE_DIR",
    "TEMPLATE_NAMES",
    "TemplateNotAllowedError",
    "TemplateRuntimeUnavailable",
    "environment",
    "jinja2_available",
    "render_page",
    "render_template",
]

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "templates")

#: Every template this build ships. The route table names one of these and
#: nothing else; :func:`render_template` refuses anything not on the list.
TEMPLATE_NAMES: Tuple[str, ...] = (
    "base.html",
    "home.html",
    "login.html",
    "cases.html",
    "case_detail.html",
    "assessment.html",
    # Wave 4B. The candidate track's own result page. A separate template
    # rather than the governed one with extra rows: the two describe answers
    # under different authorities, and a reader has to be able to tell which
    # is in front of them.
    "candidate_assessment.html",
    "evidence.html",
    "validation.html",
    "expert_review.html",
    "system.html",
    "error.html",
    "_status_pair.html",
    "_provenance.html",
    "_warning.html",
)


class TemplateNotAllowedError(Exception):
    """A template name outside the fixed allowlist was requested."""


class TemplateRuntimeUnavailable(Exception):
    """Jinja2 is not installed, so no page can be rendered."""


def jinja2_available() -> bool:
    """Whether a template can actually be rendered in this environment."""
    try:
        import jinja2  # noqa: F401
    except ImportError:
        return False
    return True


def _require_jinja():
    try:
        import jinja2
        from jinja2.sandbox import SandboxedEnvironment
    except ImportError as error:  # pragma: no cover - environment dependent
        raise TemplateRuntimeUnavailable(
            "Jinja2 is not installed in this environment, so no page can be "
            "rendered. Install the 'web' extra.") from error
    return jinja2, SandboxedEnvironment


def _guard(name: str) -> str:
    if name not in TEMPLATE_NAMES:
        raise TemplateNotAllowedError(
            "%r is not a template this build ships; the allowlist is %s"
            % (name, ", ".join(TEMPLATE_NAMES)))
    return name


def environment(*, directory: Optional[str] = None) -> Any:
    """Build the one environment every page is rendered in.

    A fresh environment per call rather than a module-level singleton: a
    cached environment caches compiled templates, and a test that edits a
    template and renders again would silently get the old one.
    """
    jinja2, SandboxedEnvironment = _require_jinja()

    class _AllowlistLoader(jinja2.FileSystemLoader):
        """A loader that refuses a name outside the allowlist.

        The guard is here as well as in :func:`render_template` because
        ``{% extends %}`` and ``{% include %}`` reach the loader directly, and
        a template that included a path assembled from data would otherwise
        bypass the check at the entry point.
        """

        def get_source(self, env, template):  # type: ignore[override]
            return super().get_source(env, _guard(template))

    env = SandboxedEnvironment(
        loader=_AllowlistLoader(directory or TEMPLATE_DIR,
                                encoding="utf-8"),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        auto_reload=False,
        keep_trailing_newline=True,
    )
    # No filters, tests or globals are added. Anything a template needs is
    # computed by a view model and arrives as data; a filter would be a place
    # for presentation logic to grow where the fact-preservation check cannot
    # see it.
    env.globals.clear()
    return env


def render_template(name: str, context: Mapping[str, Any], *,
                    directory: Optional[str] = None) -> str:
    """Render one allowlisted template. No safety gate; see :func:`render_page`.

    Separated from the gate so a test can render a deliberately unsafe page and
    assert that the gate blocks it. Production never calls this directly.
    """
    env = environment(directory=directory)
    template = env.get_template(_guard(name))
    return template.render(**dict(context))


def render_page(name: str, context: Mapping[str, Any], *,
                directory: Optional[str] = None) -> str:
    """Render one page and refuse to return it if it is not safe.

    Raises:
        TemplateNotAllowedError: the name is not on the allowlist.
        TemplateRuntimeUnavailable: Jinja2 is not installed.
        PageSafetyError: the rendered page carries a prohibited claim or
            unsafe markup. Nothing is returned - a caller cannot accidentally
            deliver a page the gate rejected, because there is no partial
            result to deliver.
    """
    html = render_template(name, context, directory=directory)
    require_safe_page(html)
    return html
