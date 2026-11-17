"""Which backend serves this instance, from its configuration."""

from __future__ import annotations

from typing import Any

from depictio.models.storage.base import StorageBackend
from depictio.models.storage.registry import backend_class

#: Backend used when a configuration names none: every instance before #1358.
DEFAULT_BACKEND = "s3"


def _backend_name(cfg: Any) -> str:
    for name in (
        getattr(getattr(cfg, "storage", None), "backend", None),
        getattr(cfg, "storage_backend", None),
    ):
        if isinstance(name, str) and name:
            return name
    return DEFAULT_BACKEND


def _backend_config(cfg: Any, name: str) -> Any:
    """The per-backend section of ``cfg``: ``settings.<name>`` or ``CLI_config.<name>_storage``.

    A bare backend section (``S3DepictioCLIConfig``) is accepted as is.
    """
    # The CLI spelling first: a ``CLIConfig`` (or a stand-in for one) never
    # has the server's attribute, and the server's ``Settings`` has no ``_storage``.
    for attr in (f"{name}_storage", name):
        section = getattr(cfg, attr, None)
        if section is not None:
            return section
    if hasattr(cfg, "bucket"):
        return cfg
    raise ValueError(f"configuration has no '{name}' storage section")


def instance_storage(cfg: Any, *, fail_fast: bool = False) -> StorageBackend:
    """The backend for the instance's own bucket.

    ``cfg`` is the server ``settings``, a ``CLIConfig`` (CLI and Celery), or a
    backend section itself. The backend comes from ``DEPICTIO_STORAGE_BACKEND``
    (``settings.storage.backend`` / ``CLIConfig.storage_backend``), ``s3`` when
    unset. Building one is cheap: clients are created on first use.
    """
    name = _backend_name(cfg)
    cls = backend_class(name)
    return cls(_backend_config(cfg, name), fail_fast=fail_fast)
