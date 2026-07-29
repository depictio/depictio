"""CLI env-flag names must not squat on an API settings namespace.

The CLI opts its perf features in via raw ``os.getenv`` while the API declares
its config as pydantic-settings models, each owning an ``env_prefix``. Those two
namespaces are invisible to each other, so a CLI flag can silently occupy the
env var a settings field would generate.

That is not hypothetical: ``DEPICTIO_MULTIQC_PRERENDER`` (CLI, "build figures at
ingest") sat one underscore from ``DEPICTIO_MULTIQC_PRERENDER_DIR`` (API, "where
the disk store lives") inside ``MultiQCPrerenderConfig``'s ``DEPICTIO_MULTIQC_``
prefix. Adding the obvious ``prerender: bool`` field to that model would have
made the CLI's ingest flag drive an unrelated API setting, with nothing raising
— pydantic-settings simply never collects a prefixed var matching no field, so
the collision is silent until the field appears.

This test derives both sides from the source so a newly added flag or field is
covered without anyone remembering to update a list.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_settings import BaseSettings

from depictio.api.v1.configs import settings_models

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CLI_ROOT = _REPO_ROOT / "depictio" / "cli"

# os.getenv("DEPICTIO_…") / os.environ.get("DEPICTIO_…") / os.environ["DEPICTIO_…"]
_ENV_READ = re.compile(r"""os\.(?:getenv|environ\.get)\(\s*["'](DEPICTIO_[A-Z0-9_]+)["']""")
_ENV_INDEX = re.compile(r"""os\.environ\[\s*["'](DEPICTIO_[A-Z0-9_]+)["']\s*\]""")


def _cli_env_flags() -> set[str]:
    """Every DEPICTIO_* env var the shipped CLI reads (excluding its own venv)."""
    found: set[str] = set()
    for path in _CLI_ROOT.rglob("*.py"):
        if ".venv" in path.parts or "site-packages" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        found.update(_ENV_READ.findall(text))
        found.update(_ENV_INDEX.findall(text))
    return found


# The root ``Settings`` model owns ``DEPICTIO_`` — the whole project namespace —
# so "sits inside a settings prefix" is only meaningful for the sub-namespaces
# below it (DEPICTIO_MULTIQC_, DEPICTIO_S3_, …).
_ROOT_PREFIX = "DEPICTIO_"

# Deliberately shared between CLI and API: DEPICTIO_CONTEXT selects the runtime
# context (api / dash / cli) and is *meant* to be the same var on both sides.
_INTENTIONALLY_SHARED = {"DEPICTIO_CONTEXT"}


def _settings_classes():
    """The BaseSettings subclasses declared in settings_models (not the import)."""
    return [
        attr
        for attr in vars(settings_models).values()
        if isinstance(attr, type) and issubclass(attr, BaseSettings) and attr is not BaseSettings
    ]


def _settings_env_names() -> dict[str, str]:
    """Map every env var the API settings models generate -> declaring class."""
    names: dict[str, str] = {}
    for attr in _settings_classes():
        prefix = attr.model_config.get("env_prefix") or ""
        for field in attr.model_fields:
            names[f"{prefix}{field}".upper()] = attr.__name__
    return names


def test_cli_reads_some_env_flags():
    """Guard the guard: a broken regex would make the real test vacuously pass."""
    assert _cli_env_flags(), "found no DEPICTIO_* env reads in the CLI — regex likely broken"


def test_settings_models_declare_env_names():
    assert _settings_env_names(), "found no BaseSettings env names — introspection likely broken"


def test_no_cli_flag_collides_with_a_settings_field():
    settings_names = _settings_env_names()
    collisions = {
        flag: settings_names[flag]
        for flag in _cli_env_flags() - _INTENTIONALLY_SHARED
        if flag in settings_names
    }
    assert not collisions, (
        "CLI env flag(s) collide with an API settings field, which would couple "
        "unrelated CLI and API behaviour through one env var: "
        + ", ".join(f"{flag} (declared by {cls})" for flag, cls in sorted(collisions.items()))
        + ". Rename the CLI flag (e.g. DEPICTIO_INGEST_*) or read it from the settings model."
    )


def test_no_cli_flag_shadows_a_settings_prefix_namespace():
    """Also reject a CLI flag sitting *inside* a settings prefix but matching no
    field yet — the state DEPICTIO_MULTIQC_PRERENDER was in. It does not break
    anything today, but it is the exact shape that becomes a silent collision
    the moment someone adds the matching field."""
    prefixes = {
        (attr.model_config.get("env_prefix") or "").upper(): attr.__name__
        for attr in _settings_classes()
        # Only sub-namespaces: the root DEPICTIO_ belongs to every var by design.
        if len(attr.model_config.get("env_prefix") or "") > len(_ROOT_PREFIX)
    }
    squatters = {
        flag: owner
        for flag in _cli_env_flags() - _INTENTIONALLY_SHARED
        for prefix, owner in prefixes.items()
        if flag.startswith(prefix)
    }
    assert not squatters, (
        "CLI env flag(s) sit inside an API settings env_prefix: "
        + ", ".join(f"{flag} (prefix owned by {cls})" for flag, cls in sorted(squatters.items()))
        + ". Move them to a CLI-owned prefix such as DEPICTIO_INGEST_*."
    )
