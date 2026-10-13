"""Which server paths a browser-triggered ingestion may read.

A browser trigger makes the ingestion worker read whatever paths a project
names, and outside public mode any authenticated user can create a project and
name any path: another group's run directory on a shared volume, or the keys
the worker has mounted. The operator therefore lists the directories that hold
ingestible data in ``DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS``, and nothing
outside them is read. An empty list allows nothing.

Every comparison goes through ``os.path.realpath``, so neither ``..`` nor a
symlink can step outside a root. The check runs three times: when the trigger
is requested, inside the task before any read, and over the files the scan
registered, which is what catches a symlink planted inside an allowed root.

Paths never leave this module in a refusal shown to a non-admin: whether a
given server path exists is itself what an attacker probing it wants to learn.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable

from depictio.api.v1.configs.config import settings

#: The setting's environment variable, named in every refusal so an operator
#: reading one knows what to change.
ALLOWED_ROOTS_ENV = "DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS"

# ``{VAR}`` placeholders, as ``resolve_local_images_path`` in the CLI expands them.
_ENV_PLACEHOLDER = re.compile(r"\{([A-Z0-9_]+)\}")


def allowed_roots() -> list[str]:
    """The configured roots, resolved. Empty when none are set."""
    configured = settings.ingestion.allowed_data_roots
    if isinstance(configured, str):  # pragma: no cover - normalised by the settings model
        configured = configured.split(",")
    return [os.path.realpath(os.path.expanduser(r.strip())) for r in configured if r.strip()]


def is_within_roots(path: str, roots: Iterable[str]) -> bool:
    """Whether ``path`` resolves inside one of ``roots`` (already resolved)."""
    resolved = os.path.realpath(path)
    for root in roots:
        try:
            if os.path.commonpath([root, resolved]) == root:
                return True
        except ValueError:  # pragma: no cover - mixed drives on Windows
            continue
    return False


def _expand_image_path(value: str) -> str:
    """``local_images_path`` the way the CLI's image upload reads it.

    An unset variable is left in place: the upload refuses it anyway, and the
    literal path it leaves is what gets checked.
    """
    for name in _ENV_PLACEHOLDER.findall(value):
        env_value = os.environ.get(name)
        if env_value:
            value = value.replace(f"{{{name}}}", env_value)
    return os.path.expanduser(value)


def project_read_paths(project: dict) -> list[str]:
    """Every server path a server-side ingestion of ``project`` reads directly.

    The data locations a scan walks, the file a single-file scan reads, and the
    directory an image collection uploads from. Taken from the raw project
    document, so the endpoint and the task check the same thing.
    """
    paths: list[str] = []
    for workflow in project.get("workflows") or []:
        if not isinstance(workflow, dict):
            continue
        location = workflow.get("data_location") or {}
        paths += location.get("locations") or []
        paths += location.get("attached_locations") or []
        for dc in workflow.get("data_collections") or []:
            config = (dc or {}).get("config") or {}
            scan = config.get("scan") or {}
            if str(scan.get("mode") or "").lower() == "single":
                filename = (scan.get("scan_parameters") or {}).get("filename")
                if filename:
                    paths.append(filename)
            images = (config.get("dc_specific_properties") or {}).get("local_images_path")
            if images:
                paths.append(_expand_image_path(str(images)))
    return [str(p) for p in paths if p]


def paths_outside_roots(paths: Iterable[str], roots: list[str]) -> list[str]:
    """The entries of ``paths`` that resolve outside every root."""
    return [p for p in paths if not is_within_roots(p, roots)]


def roots_refusal(project: dict) -> tuple[str | None, list[str]]:
    """Why a server-side ingestion of ``project`` may not run, and the paths at fault.

    Returns ``(None, [])`` when it may. The message never names a path; a
    caller appends the returned ones for an admin only.
    """
    roots = allowed_roots()
    if not roots:
        return (
            "This server has no directories it may ingest from: set "
            f"{ALLOWED_ROOTS_ENV} to enable browser-triggered ingestion.",
            [],
        )
    outside = paths_outside_roots(project_read_paths(project), roots)
    if not outside:
        return None, []
    return (
        f"{len(outside)} of this project's data path(s) are outside the directories "
        f"this server may ingest from ({ALLOWED_ROOTS_ENV}).",
        outside,
    )
