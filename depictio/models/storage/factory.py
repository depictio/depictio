"""Which backend serves this instance, from its configuration."""

from __future__ import annotations

from typing import Any

from depictio.models.storage.base import StorageBackend, StorageError
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


def cli_storage_fields(settings: Any, *, dump: bool = False) -> dict[str, Any]:
    """The ``CLIConfig`` fields that carry the server's instance storage to the CLI.

    Every ``CLIConfig`` the server builds (Celery ingestion, agent configs) must
    write to the same bucket as the server: ``**cli_storage_fields(settings)``
    next to ``s3_storage``. ``dump=True`` gives plain dicts, for a config built
    as a dict (and maybe serialised) before it is validated.
    """
    name = _backend_name(settings)
    fields: dict[str, Any] = {"storage_backend": name}
    if name != DEFAULT_BACKEND:
        section = _backend_config(settings, name)
        fields[f"{name}_storage"] = section.model_dump() if dump else section
    return fields


def require_s3_instance(cfg: Any, feature: str) -> None:
    """Refuse ``feature`` on an instance whose bucket is not on S3.

    For the code that still speaks boto3 to the instance bucket by design
    (project migration bundles, S3-to-S3 backups): on another backend it would
    read and write a bucket the instance does not use.
    """
    name = _backend_name(cfg)
    if name != "s3":
        raise StorageError(
            f"{feature} needs the instance bucket on S3; this instance stores its data "
            f"on '{name}' (DEPICTIO_STORAGE_BACKEND). Not supported yet (#1358)."
        )


def check_instance_storage(cfg: Any, checks: list[str] | None = None) -> None:
    """Run the instance backend's startup checks; :class:`StorageError` when one fails."""
    instance_storage(cfg).check(checks)


class BackendStorageOptions:
    """Polars / delta-rs options of a non-S3 instance backend, shaped like
    ``PolarsStorageOptions`` where the CLI reads it: ``model_dump()``, and no
    ``aws_access_key_id`` (so no AWS session-token guard applies)."""

    aws_access_key_id: str | None = None

    def __init__(self, options: dict[str, str]) -> None:
        self._options = dict(options)

    def model_dump(self, **_: Any) -> dict[str, str]:
        return dict(self._options)

    def __repr__(self) -> str:
        return f"BackendStorageOptions(keys={sorted(self._options)})"


def instance_polars_options(cfg: Any) -> Any:
    """The storage options the CLI threads through its Delta reads and writes.

    On S3, the ``PolarsStorageOptions`` of the S3 section, as before (looked up at
    call time, so tests can patch ``s3_utils.turn_S3_config_into_polars_storage_options``).
    On another backend, its own options in the same shape.
    """
    name = _backend_name(cfg)
    if name == DEFAULT_BACKEND:
        from depictio.models import s3_utils

        return s3_utils.turn_S3_config_into_polars_storage_options(_backend_config(cfg, name))
    return BackendStorageOptions(instance_storage(cfg).storage_options())
