"""Generic, pluggable workflow run-provenance layer.

A run directory produced by *any* workflow engine (Nextflow/nf-core, Snakemake,
Galaxy via RO-Crate, CWL, …) is described by a single engine-agnostic model,
``WorkflowRunInfo``. Each engine ships a **connector** — a small reader that
recognises its own artefacts and returns a ``WorkflowRunInfo`` (or ``None``).

Connectors self-register via ``register_run_info_reader``; ``read_run_info``
iterates them by descending priority and returns the first hit. Adding support
for a new system is therefore: create a module with a reader, call
``register_run_info_reader(...)`` at import time, and list the module in
``_CONNECTOR_MODULES`` — **no change to any caller** (compose / run / templates).

Pure + offline by contract (like ``catalog.read_software_versions``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class WorkflowRunInfo(BaseModel):
    """Engine-agnostic provenance for a single workflow run directory."""

    model_config = ConfigDict(extra="forbid")

    engine: str | None = None  # "nextflow" | "snakemake" | "galaxy" | …
    pipeline_name: str | None = None  # e.g. "nf-core/ampliseq" (may carry a catalog prefix)
    pipeline_version: str | None = None  # e.g. "2.16.0" (leading "v" stripped)
    engine_version: str | None = None  # runtime engine version, e.g. Nextflow "24.04.4"
    run_name: str | None = None
    homepage: str | None = None
    params: dict = Field(default_factory=dict)
    tools_executed: set[str] = Field(default_factory=set)

    # Standard artefact paths kept for reference / later provenance parsing.
    software_versions_path: str | None = None
    params_json_path: str | None = None
    execution_report_path: str | None = None
    execution_trace_path: str | None = None
    pipeline_dag_path: str | None = None

    # Connector-specific metadata that doesn't fit the common schema.
    extra: dict = Field(default_factory=dict)

    @property
    def short_name(self) -> str | None:
        """Pipeline name without the catalog prefix (``nf-core/ampliseq`` → ``ampliseq``)."""
        if self.pipeline_name and "/" in self.pipeline_name:
            return self.pipeline_name.split("/", 1)[1]
        return self.pipeline_name

    def template_ids(self) -> list[str]:
        """Candidate template ids to try, most specific first.

        Versions may carry a leading ``v`` (``v3.16.0``) while template folders
        are unprefixed (``2.16.0``), so both spellings are offered.
        """
        if not (self.pipeline_name and self.pipeline_version):
            return []
        raw = self.pipeline_version
        stripped = raw.lstrip("v")
        versions = [raw] if raw == stripped else [stripped, raw]
        return [f"{self.pipeline_name}/{v}" for v in versions]


@runtime_checkable
class RunInfoReader(Protocol):
    """A connector that recognises one engine's run artefacts.

    ``read`` must be self-contained recognition: return ``None`` when the
    directory is not a run of this engine, otherwise a populated
    ``WorkflowRunInfo``. Higher ``priority`` readers are tried first.
    """

    name: str
    priority: int

    def read(self, run_dir: Path) -> WorkflowRunInfo | None: ...


# Connector modules imported (once) to trigger their self-registration. Listing a
# new module here is the only wiring needed to add an engine.
_CONNECTOR_MODULES: tuple[str, ...] = (
    "depictio.models.models.nextflow",
    "depictio.models.models.snakemake",
)

_READERS: list[RunInfoReader] = []
_LOADED = False


def register_run_info_reader(reader: RunInfoReader) -> None:
    """Register a connector (idempotent by ``name``); kept sorted by priority desc."""
    global _READERS
    _READERS = [r for r in _READERS if r.name != reader.name]
    _READERS.append(reader)
    _READERS.sort(key=lambda r: r.priority, reverse=True)


def _ensure_readers_loaded() -> None:
    """Import connector modules so they self-register (lazy, avoids import cycles)."""
    global _LOADED
    if _LOADED:
        return
    import importlib

    for module in _CONNECTOR_MODULES:
        try:
            importlib.import_module(module)
        except Exception:
            # A broken/optional connector must not break detection for the others.
            continue
    _LOADED = True


def registered_readers() -> list[RunInfoReader]:
    """The connectors currently registered (priority order). Mainly for tests."""
    _ensure_readers_loaded()
    return list(_READERS)


def read_run_info(run_dir: str | Path) -> WorkflowRunInfo | None:
    """Detect the engine of ``run_dir`` and read its provenance, or ``None``.

    Tries each registered connector by descending priority; the first one that
    recognises the directory wins.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return None
    _ensure_readers_loaded()
    for reader in _READERS:
        try:
            info = reader.read(run_dir)
        except Exception:
            continue
        if info is not None:
            return info
    return None
