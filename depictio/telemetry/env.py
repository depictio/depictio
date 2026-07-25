"""Environment detection: how was this Depictio started, and on what.

Everything here is deliberately non-identifying. ``platform.system()`` and
``platform.machine()`` are collected; ``platform.node()`` (the hostname) is not,
and must never be added.
"""

import os
import platform
import sys
from typing import Final, Literal

DeploymentKind = Literal["kubernetes", "docker-compose", "docker", "devcontainer", "local"]

#: Env var an operator (or our own Helm chart / compose files) can set to state the
#: deployment kind outright, rather than relying on the heuristics below.
DEPLOYMENT_KIND_ENV: Final[str] = "DEPICTIO_TELEMETRY_DEPLOYMENT_KIND"

#: Accepted values for ``DEPLOYMENT_KIND_ENV``. Documented for operators and
#: asserted against in the tests so this list cannot drift from the branches in
#: :func:`detect_deployment_kind`.
VALID_DEPLOYMENT_KINDS: Final[tuple[str, ...]] = (
    "kubernetes",
    "docker-compose",
    "docker",
    "devcontainer",
    "local",
)

#: Env vars that indicate an automated build. Set by GitHub Actions, GitLab CI,
#: Travis, CircleCI, Jenkins and most others; ``CI`` alone covers the majority.
_CI_ENV_VARS: Final[tuple[str, ...]] = (
    "CI",
    "CONTINUOUS_INTEGRATION",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "BUILDKITE",
    "CIRCLECI",
    "JENKINS_URL",
    "TEAMCITY_VERSION",
    "TF_BUILD",
)


def detect_deployment_kind() -> DeploymentKind:
    """Work out how this process was deployed.

    An explicit ``DEPICTIO_TELEMETRY_DEPLOYMENT_KIND`` always wins — the Helm
    chart sets ``kubernetes`` and the compose files set ``docker-compose``, which
    is more reliable than any heuristic and is the only way to tell those two
    apart (a Helm-deployed pod and a compose container both just look like
    "a container" from the inside).

    The fallbacks exist for hand-rolled deployments that never set the var:

    * ``KUBERNETES_SERVICE_HOST`` is injected into every pod by the kubelet.
    * ``/.dockerenv`` exists in Docker containers but says nothing about whether
      compose orchestrated them, hence the plain ``docker``.
    * Otherwise assume a developer running the API directly.
    """
    # Compared literal-by-literal rather than via a set membership test so the
    # return type narrows to ``DeploymentKind`` without a cast.
    explicit = os.getenv(DEPLOYMENT_KIND_ENV, "").strip().lower()
    if explicit == "kubernetes":
        return "kubernetes"
    if explicit == "docker-compose":
        return "docker-compose"
    if explicit == "docker":
        return "docker"
    if explicit == "devcontainer":
        return "devcontainer"
    if explicit == "local":
        return "local"

    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return "kubernetes"
    if os.getenv("REMOTE_CONTAINERS") or os.getenv("CODESPACES"):
        return "devcontainer"
    if os.path.exists("/.dockerenv"):
        return "docker"
    return "local"


def detect_ci() -> bool:
    """True when running inside an automated build.

    Depictio's own CI boots the API on nearly every workflow run, and users' CI
    pipelines invoke ``depictio-cli`` on every commit. Left uncounted, automation
    would dominate every metric — so this drives a hard suppression in
    :mod:`depictio.telemetry.gates` rather than merely tagging the event.
    """
    return any(os.getenv(var) for var in _CI_ENV_VARS)


def detect_pytest() -> bool:
    """True when running under pytest, or with the dev-mode flag set.

    Mirrors the ``is_testing`` idiom in ``depictio/api/v1/db.py``, which is the
    established way this codebase recognises a test run.
    """
    if os.getenv("DEPICTIO_DEV_MODE", "false").strip().lower() == "true":
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return any("pytest" in arg for arg in sys.argv)


def platform_info() -> dict[str, str]:
    """Non-identifying facts about the host.

    Deliberately excludes ``platform.node()`` (hostname), ``platform.release()``
    (kernel build strings are near-unique on some distros) and anything derived
    from the filesystem.
    """
    return {
        "os": platform.system() or "unknown",
        "arch": platform.machine() or "unknown",
        "python_version": platform.python_version(),
    }
