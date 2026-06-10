"""Read a Nextflow / nf-core run's provenance from its ``pipeline_info/`` artefacts.

Pure + offline (mirrors ``catalog.read_software_versions``): given a run directory,
extract the pipeline identity, version, Nextflow version, run parameters and the
set of executed tools, plus the paths of the standard execution reports. Used to:

  - detect which template (if any) matches a run (``detect_template_from_run_dir``),
  - enrich a generated dashboard (title / workflow_tag / version),
  - persist provenance per run (``WorkflowConfig``).

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

from pydantic import BaseModel, ConfigDict, Field

# Default Nextflow execution-trace columns (parsed in a later increment).
_MANIFEST_RE = {
    "name": re.compile(r"""name\s*=\s*['"]([^'"]+)['"]"""),
    "version": re.compile(r"""version\s*=\s*['"]([^'"]+)['"]"""),
    "homePage": re.compile(r"""homePage\s*=\s*['"]([^'"]+)['"]"""),
}


class NextflowRunInfo(BaseModel):
    """Provenance extracted from a Nextflow/nf-core run directory."""

    model_config = ConfigDict(extra="forbid")

    pipeline_name: str | None = None  # e.g. "nf-core/ampliseq"
    pipeline_version: str | None = None  # e.g. "2.16.0" (leading "v" stripped)
    nextflow_version: str | None = None  # runtime Nextflow version, e.g. "24.04.4"
    run_name: str | None = None
    homepage: str | None = None
    params: dict = Field(default_factory=dict)
    tools_executed: set[str] = Field(default_factory=set)

    # Artefact paths kept for reference / later provenance parsing.
    software_versions_path: str | None = None
    params_json_path: str | None = None
    execution_report_path: str | None = None
    execution_trace_path: str | None = None
    pipeline_dag_path: str | None = None

    @property
    def short_name(self) -> str | None:
        """Pipeline name without the catalog prefix (``nf-core/ampliseq`` → ``ampliseq``)."""
        if self.pipeline_name and "/" in self.pipeline_name:
            return self.pipeline_name.split("/", 1)[1]
        return self.pipeline_name

    def template_ids(self) -> list[str]:
        """Candidate template ids to try, most specific first.

        nf-core versions.yml may carry a leading ``v`` (``v3.16.0``) while template
        folders are unprefixed (``2.16.0``), so both forms are offered.
        """
        if not (self.pipeline_name and self.pipeline_version):
            return []
        raw = self.pipeline_version
        stripped = raw.lstrip("v")
        versions = [raw] if raw == stripped else [stripped, raw]
        return [f"{self.pipeline_name}/{v}" for v in versions]


def _find_first(run_dir: Path, *globs: str) -> Path | None:
    """First file matching any of ``globs`` (recursive), or None."""
    for pattern in globs:
        for path in sorted(run_dir.rglob(pattern)):
            if path.is_file():
                return path
    return None


def _parse_versions_yaml(path: Path, info: NextflowRunInfo) -> None:
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
                    info.nextflow_version = str(value)
                else:
                    info.pipeline_name = str(key)
                    info.pipeline_version = str(value).lstrip("v")
        else:
            tools.update(str(tool).lower() for tool in versions)
    if tools:
        info.tools_executed = tools


def _parse_params_json(path: Path, info: NextflowRunInfo) -> None:
    """Fill the run parameters from a params_*.json / nf-params.json."""
    try:
        data = json.loads(path.read_text())
    except Exception:
        return
    if isinstance(data, dict):
        info.params = data
        info.params_json_path = str(path)


def _parse_manifest(run_dir: Path, info: NextflowRunInfo) -> None:
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


def read_nextflow_run_info(run_dir: str | Path) -> NextflowRunInfo | None:
    """Read a run's Nextflow provenance, or None if no artefact is recognised."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return None

    info = NextflowRunInfo()

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
            info.nextflow_version,
            info.tools_executed,
            info.params,
            info.execution_report_path,
            info.execution_trace_path,
        )
    )
    return info if has_signal else None
