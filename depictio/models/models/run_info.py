"""Engine-agnostic workflow-run provenance.

A results directory produced by a workflow engine carries enough breadcrumbs to
say *what produced it*: which engine, which pipeline, which version, which tools
ran. This module defines the neutral shape of that answer (``WorkflowRunInfo``),
a reader protocol so each engine gets its own connector, and a tiny registry
that dispatches a directory to the highest-priority connector that recognises
it.

The split matters because the consumers are engine-agnostic: the CLI uses the
result to auto-select a bundled template for ``depictio-cli run --data-root``,
and nothing in that path should know about Nextflow specifically. Adding
Snakemake, WDL or CWL support is then a new connector module plus one entry in
``_CONNECTOR_MODULES`` — no change here and no change in the CLI.

This module stays pure and offline: it reads no files itself, performs no
network access, and imports no recipe/catalog machinery. The connectors are
imported lazily, on first use, so importing the models package does not pull
their (heavier) dependencies in.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from depictio.models.logging import logger


class WorkflowRunInfo(BaseModel):
    """What a workflow engine's output directory says about the run that made it.

    Every field is optional: connectors are best-effort readers of whatever the
    engine happened to write, and a partially-identified run is far more useful
    than no answer at all. ``extra`` is the escape hatch for engine-specific
    details that do not deserve a first-class field (e.g. the raw, un-normalised
    version string).
    """

    model_config = ConfigDict(extra="forbid")

    engine: str | None = None
    """Workflow engine that produced the directory, e.g. ``"nextflow"``."""

    pipeline_name: str | None = None
    """Fully-qualified pipeline id, e.g. ``"nf-core/ampliseq"``."""

    pipeline_version: str | None = None
    """Normalised, comparable release, e.g. ``"2.16.0"`` (see connectors)."""

    engine_version: str | None = None
    """Engine runtime version, e.g. Nextflow ``"25.10.0"``."""

    run_name: str | None = None
    homepage: str | None = None

    params: dict = Field(default_factory=dict)
    """The run's parameters, as the engine recorded them."""

    tools_executed: set[str] = Field(default_factory=set)
    """Lowercased names of the tools the run actually executed."""

    software_versions_path: str | None = None
    params_json_path: str | None = None
    execution_report_path: str | None = None
    execution_trace_path: str | None = None
    pipeline_dag_path: str | None = None

    extra: dict = Field(default_factory=dict)

    @property
    def short_name(self) -> str | None:
        """Pipeline name without its namespace: ``nf-core/ampliseq`` -> ``ampliseq``."""
        if not self.pipeline_name:
            return None
        return self.pipeline_name.rsplit("/", 1)[-1]

    def template_ids(self) -> list[str]:
        """Candidate bundled-template ids for this run, most specific first.

        The normalised version comes first (``nf-core/ampliseq/2.16.0``), then
        the raw string the engine actually wrote if it differs
        (``nf-core/ampliseq/v2.16.0-g3d5c7e5``) — a template directory could in
        principle be named either way.

        Deliberately never yields the version-less ``nf-core/ampliseq``: that id
        resolves to the *latest* shipped template, which is exactly the wrong
        answer for an old run. Choosing a substitute when no version matches is
        the caller's decision, not this list's.
        """
        if not self.pipeline_name:
            return []
        raw = self.extra.get("pipeline_version_raw")
        ids: list[str] = []
        for version in (self.pipeline_version, raw):
            if not version:
                continue
            candidate = f"{self.pipeline_name}/{version}"
            if candidate not in ids:
                ids.append(candidate)
        return ids


@runtime_checkable
class RunInfoReader(Protocol):
    """One engine's reader: recognise a run directory and describe it.

    ``priority`` orders connectors when a directory carries more than one
    engine's footprint (a Nextflow run staged inside a Snakemake project, say).
    Higher wins.
    """

    name: str
    priority: int

    def read(self, run_dir: Path) -> WorkflowRunInfo | None:
        """Return the run's provenance, or None if this engine doesn't recognise it."""
        ...


# Connector modules imported lazily on first dispatch; importing one registers
# its reader as a side effect. Adding an engine is a new module plus one line.
_CONNECTOR_MODULES: tuple[str, ...] = (
    "depictio.models.models.nextflow",
    "depictio.models.models.snakemake",
)

_READERS: list[RunInfoReader] = []


def register_run_info_reader(reader: RunInfoReader) -> None:
    """Register (or replace) a reader, keeping the list sorted by descending priority.

    Idempotent by ``reader.name`` so a module re-imported under a different path
    — or a test registering a stub twice — cannot install duplicates.
    """
    global _READERS
    _READERS = [r for r in _READERS if r.name != reader.name]
    _READERS.append(reader)
    _READERS.sort(key=lambda r: (-r.priority, r.name))


def _load_connectors() -> None:
    """Import the bundled connectors so they self-register. Best-effort."""
    for module in _CONNECTOR_MODULES:
        try:
            importlib.import_module(module)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Run-info connector {module!r} failed to import: {exc}")


def registered_readers() -> list[RunInfoReader]:
    """Every registered reader, highest priority first."""
    _load_connectors()
    return list(_READERS)


def read_run_info(run_dir: str | Path) -> WorkflowRunInfo | None:
    """Identify the workflow run that produced ``run_dir``.

    Tries each registered connector by descending priority and returns the first
    non-None answer. A connector that raises is logged and skipped so one broken
    engine reader cannot mask the others.
    """
    path = Path(run_dir)
    for reader in registered_readers():
        try:
            info = reader.read(path)
        except Exception as exc:
            logger.warning(f"Run-info reader {reader.name!r} failed on {path}: {exc}")
            continue
        if info is not None:
            logger.debug(f"Run-info reader {reader.name!r} recognised {path}")
            return info
    return None
