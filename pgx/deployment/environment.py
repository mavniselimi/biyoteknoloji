# -*- coding: utf-8 -*-
"""What this host actually has (WP-24).

Every BLOCKED status in this work package traces back to a finding here, which
is why this module measures rather than declares. It asks whether a container
runtime *answered*, not whether a ``docker`` binary is on ``PATH``; whether a
package index *resolved*, not whether a URL is configured; whether ``argon2``
*imports*, not whether ``pyproject.toml`` requires it.

That distinction has already been earned once in this repository: WP-17's
browser status refuses to call a resolved executable path a browser, because a
package is not a browser and a path is not a process. The same rule applies to
everything below.

Nothing runs at import. Each probe executes when it is called and caches its
own answer for the life of the process, so a command that consults the
container runtime three times does not shell out three times - and, more
importantly, so a probe that failed is not retried in a loop. A package index
that answered 403 once will answer 403 again; asking repeatedly turns a clear
BLOCKED into a slow one.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess  # noqa: S404 - probing local tooling is this module's job
import sys
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DEPLOYMENT_PYTHON_SERIES",
    "PROBE_TIMEOUT_SECONDS",
    "REQUIRED_RUNTIME_MODULES",
    "SUPPORTED_DEPLOYMENT_PYTHON",
    "CapabilityProbe",
    "EnvironmentReport",
    "ToolResult",
    "probe_environment",
]

#: The runtime the deployment image pins. Declared here as well as in the
#: Dockerfile so a test can assert the two agree - a Dockerfile that drifted
#: from the supported series would be discovered by whoever deployed it.
DEPLOYMENT_PYTHON_SERIES = "3.11"

#: The interpreter versions this project is built and tested against. The
#: local interpreter is deliberately *not* the authority: this repository has
#: been developed on 3.10, 3.11 and 3.14 in different shells, and none of
#: those facts says the deployment supports that version.
SUPPORTED_DEPLOYMENT_PYTHON: Tuple[str, ...] = ("3.10", "3.11", "3.12")

#: Bounded, and short. A probe that can hang is a preflight nobody runs.
PROBE_TIMEOUT_SECONDS = 8.0

#: What the *runtime* image must contain for the application to serve
#: authenticated traffic. Not the development set: ruff, mypy, pytest and
#: coverage are absent from a runtime image on purpose.
REQUIRED_RUNTIME_MODULES: Tuple[str, ...] = (
    "argon2", "psycopg", "sqlalchemy", "alembic", "fastapi", "pydantic",
    "uvicorn", "jinja2", "multipart",
)

#: Development and verification tooling. Absence blocks a CI job, never the
#: application.
DEVELOPMENT_MODULES: Tuple[str, ...] = (
    "pytest", "ruff", "mypy", "coverage", "httpx", "playwright", "lxml",
    "hatchling",
)

#: Vulnerability and SBOM tools this project knows how to drive. Order is
#: preference, not ranking: the first one present is used and named in the
#: result, so a report always says which scanner produced it.
SUPPLY_CHAIN_TOOLS: Tuple[str, ...] = ("trivy", "grype", "syft")


@dataclass(frozen=True)
class ToolResult:
    """One external tool, and whether it actually answered.

    ``present`` means a binary was found. ``responsive`` means it ran and
    returned zero. The two are separate because a Docker CLI with no daemon
    behind it is exactly the case that makes an image build fail after a
    pipeline has reported the runtime available.
    """

    name: str
    present: bool
    responsive: bool
    version: Optional[str] = None
    detail: str = ""

    def to_json(self) -> Mapping[str, object]:
        return {"name": self.name, "present": self.present,
                "responsive": self.responsive, "version": self.version,
                "detail": self.detail}


@dataclass(frozen=True)
class EnvironmentReport:
    """A measurement of one host at one moment."""

    python_version: str
    python_series: str
    python_is_supported_for_deployment: bool
    platform_machine: str
    platform_system: str
    modules: Mapping[str, bool]
    tools: Mapping[str, ToolResult]
    package_index_reachable: bool
    package_index_detail: str
    database_url_configured: bool
    container_runtime_available: bool
    #: Names of REQUIRED_RUNTIME_MODULES that are absent here.
    missing_runtime_modules: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def can_build_image(self) -> bool:
        return self.container_runtime_available

    @property
    def can_resolve_dependencies(self) -> bool:
        return self.package_index_reachable

    @property
    def can_build_distributions(self) -> bool:
        """A wheel needs the declared backend, not merely a builder.

        ``setuptools`` being importable does not mean this project can be
        built: ``pyproject.toml`` declares hatchling, and building with a
        different backend would produce a different artifact than any
        deployment would ever install.
        """
        return bool(self.modules.get("hatchling"))

    @property
    def supply_chain_tool(self) -> Optional[str]:
        for name in SUPPLY_CHAIN_TOOLS:
            result = self.tools.get(name)
            if result is not None and result.responsive:
                return name
        return None

    def to_json(self) -> Mapping[str, object]:
        return {
            "python_version": self.python_version,
            "python_series": self.python_series,
            "python_is_supported_for_deployment":
                self.python_is_supported_for_deployment,
            "deployment_python_series": DEPLOYMENT_PYTHON_SERIES,
            "platform_system": self.platform_system,
            "platform_machine": self.platform_machine,
            "modules": dict(sorted(self.modules.items())),
            "missing_runtime_modules": list(self.missing_runtime_modules),
            "tools": {name: dict(result.to_json())
                      for name, result in sorted(self.tools.items())},
            "package_index_reachable": self.package_index_reachable,
            "package_index_detail": self.package_index_detail,
            "database_url_configured": self.database_url_configured,
            "container_runtime_available": self.container_runtime_available,
            "supply_chain_tool": self.supply_chain_tool,
            "note": (
                "Every field is a measurement of the host this ran on. None "
                "of them describes what the software supports, and a "
                "capability absent here is absent here only."),
        }


class CapabilityProbe:
    """Runs the measurements, once each.

    Injectable for tests: ``runner`` replaces the subprocess call and
    ``module_finder`` replaces the import check, so the probe's own logic can
    be exercised without a container runtime and without installing packages.
    """

    def __init__(self, *, environ: Optional[Mapping[str, str]] = None,
                 runner=None, module_finder=None, which=None) -> None:
        self._environ = dict(os.environ if environ is None else environ)
        self._runner = runner or self._default_runner
        self._module_finder = module_finder or self._default_module_finder
        self._which = which or shutil.which
        self._cache: Dict[str, object] = {}

    # -- primitives ------------------------------------------------------

    @staticmethod
    def _default_module_finder(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):  # pragma: no cover - defensive
            return False

    @staticmethod
    def _default_runner(argv: Sequence[str]) -> Tuple[int, str]:
        """Run a probe command. Never raises; returns a code and one line.

        Output is truncated hard. A probe is asking "did this answer", and a
        tool that answered with a page of text has still only answered.
        """
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                list(argv), capture_output=True, text=True,
                timeout=PROBE_TIMEOUT_SECONDS, check=False)
        except FileNotFoundError:
            return 127, "not found"
        except subprocess.TimeoutExpired:
            return 124, "timed out after %.0fs" % PROBE_TIMEOUT_SECONDS
        except OSError as error:  # pragma: no cover - platform dependent
            return 126, type(error).__name__
        text = (completed.stdout or completed.stderr or "").strip()
        return completed.returncode, text.splitlines()[0][:200] if text else ""

    # -- probes ----------------------------------------------------------

    def module_present(self, name: str) -> bool:
        key = "module:%s" % name
        if key not in self._cache:
            self._cache[key] = self._module_finder(name)
        return bool(self._cache[key])

    def tool(self, name: str, version_argv: Sequence[str],
             *, liveness_argv: Optional[Sequence[str]] = None) -> ToolResult:
        """Measure one tool.

        ``liveness_argv`` is what separates "the CLI exists" from "the service
        behind it answered". For Docker that is ``docker info``: the version
        command answers happily with no daemon running, which is precisely the
        false positive this parameter exists to remove.
        """
        key = "tool:%s" % name
        cached = self._cache.get(key)
        if isinstance(cached, ToolResult):
            return cached
        path = self._which(name)
        if path is None:
            result = ToolResult(name=name, present=False, responsive=False,
                                detail="not on PATH")
            self._cache[key] = result
            return result
        code, text = self._runner(list(version_argv))
        version = text if code == 0 else None
        responsive = code == 0
        detail = "" if code == 0 else "version probe exited %d" % code
        if responsive and liveness_argv is not None:
            live_code, live_text = self._runner(list(liveness_argv))
            if live_code != 0:
                responsive = False
                detail = ("the command exists but the service behind it did "
                          "not answer (%s exited %d)"
                          % (liveness_argv[0], live_code))
                if live_text:
                    detail += ": " + live_text
        result = ToolResult(name=name, present=True, responsive=responsive,
                            version=version, detail=detail)
        self._cache[key] = result
        return result

    def package_index_reachable(self) -> Tuple[bool, str]:
        """One attempt, then remember the answer.

        The brief's instruction not to loop on index failures is enforced by
        the cache rather than by discipline: a second call returns the first
        call's answer, so a command that consults this in a retry loop still
        makes one network attempt.
        """
        key = "index"
        cached = self._cache.get(key)
        if isinstance(cached, tuple):
            return cached  # type: ignore[return-value]
        # Deliberately not driven through uv. Whether an index answers is a
        # question about the network, and routing it through a resolver would
        # report a resolver's opinion - a changed subcommand name, a missing
        # binary - as a network finding. The first version of this probe did
        # exactly that and blamed the network for a uv argument error.
        code, text = self._runner(
            ["python3", "-c",
             "import urllib.request,sys\n"
             "try:\n"
             "    urllib.request.urlopen('https://pypi.org/simple/', "
             "timeout=6).read(64)\n"
             "except Exception as error:\n"
             "    sys.stderr.write(type(error).__name__ + ': ' "
             "+ str(error)[:120])\n"
             "    raise SystemExit(1)\n"
             "print('reachable')\n"])
        answer = (code == 0, text if text else "no response")
        self._cache[key] = answer
        return answer  # type: ignore[return-value]

    # -- report ----------------------------------------------------------

    def report(self) -> EnvironmentReport:
        modules = {name: self.module_present(name)
                   for name in tuple(REQUIRED_RUNTIME_MODULES)
                   + DEVELOPMENT_MODULES}
        tools = {
            "docker": self.tool("docker", ["docker", "--version"],
                                liveness_argv=["docker", "info"]),
            "uv": self.tool("uv", ["uv", "--version"]),
            "git": self.tool("git", ["git", "--version"]),
            "pg_dump": self.tool("pg_dump", ["pg_dump", "--version"]),
            "psql": self.tool("psql", ["psql", "--version"]),
        }
        for name in SUPPLY_CHAIN_TOOLS:
            tools[name] = self.tool(name, [name, "--version"])
        reachable, detail = self.package_index_reachable()
        series = "%d.%d" % sys.version_info[:2]
        missing = tuple(name for name in REQUIRED_RUNTIME_MODULES
                        if not modules.get(name))
        return EnvironmentReport(
            python_version=platform.python_version(),
            python_series=series,
            python_is_supported_for_deployment=(
                series in SUPPORTED_DEPLOYMENT_PYTHON),
            platform_machine=platform.machine(),
            platform_system=platform.system(),
            modules=modules,
            tools=tools,
            package_index_reachable=reachable,
            package_index_detail=detail,
            database_url_configured=bool(
                self._environ.get("DATABASE_URL", "").strip()),
            container_runtime_available=tools["docker"].responsive,
            missing_runtime_modules=missing,
        )


def probe_environment(**kwargs: object) -> EnvironmentReport:
    """Measure this host. Convenience over :class:`CapabilityProbe`."""
    return CapabilityProbe(**kwargs).report()  # type: ignore[arg-type]
