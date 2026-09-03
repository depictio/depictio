"""nf-core / Nextflow connector: read a run's provenance from ``pipeline_info/``.

Registers itself with the generic run-info registry (``run_info.py``) so callers
go through ``read_run_info`` and never depend on this engine directly.

Source priority (formats grounded on real nf-core runs):
  1. ``pipeline_info/nf_core_*_software_mqc_versions.yml`` — its ``Workflow:``
     section gives ``nf-core/<pipeline>: <version>`` **and** ``Nextflow: <version>``
     in one file; the other sections are the executed tools.
  2. fallback ``software_versions.yml`` (executed tools only).
  3. ``pipeline_info/params_*.json`` (or ``nf-params.json``) — the run parameters.
  4. fallback manifest in ``nextflow.config`` (only present when pointing at a
     pipeline checkout, not a results dir).

Tolerant by design: a missing ``pipeline_info/`` (e.g. a curated run subset) yields
``None`` rather than an error, so callers fall back to filename-based recognition.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from depictio.models.models.run_info import WorkflowRunInfo, register_run_info_reader

_MANIFEST_RE = {
    "name": re.compile(r"""name\s*=\s*['"]([^'"]+)['"]"""),
    "version": re.compile(r"""version\s*=\s*['"]([^'"]+)['"]"""),
    "homePage": re.compile(r"""homePage\s*=\s*['"]([^'"]+)['"]"""),
}


def _find_first(run_dir: Path, *globs: str) -> Path | None:
    """First file matching any of ``globs`` (recursive), or None."""
    for pattern in globs:
        for path in sorted(run_dir.rglob(pattern)):
            if path.is_file():
                return path
    return None


def _parse_versions_yaml(path: Path, info: WorkflowRunInfo) -> None:
    """Fill identity / Nextflow version / tools from a *_software_mqc_versions.yml."""
    import yaml

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return
    if not isinstance(data, dict):
        return
    info.software_versions_path = str(path)
    tools: set[str] = set()
    for section, versions in data.items():
        if not isinstance(versions, dict):
            continue
        if str(section).lower() == "workflow":
            for key, value in versions.items():
                if str(key).lower() == "nextflow":
                    info.engine_version = str(value)
                else:
                    info.pipeline_name = str(key)
                    info.pipeline_version = str(value).lstrip("v")
        else:
            tools.update(str(tool).lower() for tool in versions)
    if tools:
        info.tools_executed = tools


def _parse_params_json(path: Path, info: WorkflowRunInfo) -> None:
    """Fill the run parameters from a params_*.json / nf-params.json."""
    try:
        data = json.loads(path.read_text())
    except Exception:
        return
    if isinstance(data, dict):
        info.params = data
        info.params_json_path = str(path)


def _parse_manifest(run_dir: Path, info: WorkflowRunInfo) -> None:
    """Fallback identity from a ``nextflow.config`` manifest block (checkout only).

    ``nextflowVersion`` is intentionally ignored — it is a constraint
    (``!>=25.04.3``), not the runtime version.
    """
    config = _find_first(run_dir, "nextflow.config")
    if config is None:
        return
    try:
        text = config.read_text()
    except Exception:
        return
    if (m := _MANIFEST_RE["name"].search(text)) and not info.pipeline_name:
        info.pipeline_name = m.group(1)
    if (m := _MANIFEST_RE["version"].search(text)) and not info.pipeline_version:
        info.pipeline_version = m.group(1).lstrip("v")
    if (m := _MANIFEST_RE["homePage"].search(text)) and not info.homepage:
        info.homepage = m.group(1)


def read_nextflow_run_info(run_dir: str | Path) -> WorkflowRunInfo | None:
    """Read an nf-core/Nextflow run's provenance, or None if nothing recognised."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return None

    info = WorkflowRunInfo(engine="nextflow")

    versions = _find_first(
        run_dir, "nf_core_*_software_mqc_versions.yml", "*_software_mqc_versions.yml"
    )
    if versions is not None:
        _parse_versions_yaml(versions, info)

    if not info.tools_executed:
        # Reuse the catalog's reader for the legacy per-process file.
        from depictio.models.components.advanced_viz.catalog import read_software_versions

        info.tools_executed = read_software_versions(run_dir)

    params = _find_first(run_dir, "params_*.json", "nf-params.json", "nf_params.json")
    if params is not None:
        _parse_params_json(params, info)

    if not info.pipeline_name:
        _parse_manifest(run_dir, info)

    for attr, pattern in (
        ("execution_report_path", "execution_report*.html"),
        ("execution_trace_path", "execution_trace*.txt"),
        ("pipeline_dag_path", "pipeline_dag*"),
    ):
        match = _find_first(run_dir, pattern)
        if match is not None:
            setattr(info, attr, str(match))

    has_signal = any(
        (
            info.pipeline_name,
            info.engine_version,
            info.tools_executed,
            info.params,
            info.execution_report_path,
            info.execution_trace_path,
        )
    )
    return info if has_signal else None


class _NextflowReader:
    """Connector entry for the run-info registry."""

    name = "nextflow"
    priority = 100  # most specific / self-describing → tried first

    def read(self, run_dir: Path) -> WorkflowRunInfo | None:
        return read_nextflow_run_info(run_dir)


register_run_info_reader(_NextflowReader())
