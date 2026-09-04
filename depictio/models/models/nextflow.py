"""Nextflow / nf-core connector for the run-provenance registry.

Reads a results directory's ``pipeline_info/`` — the folder every nf-core
pipeline writes — and answers which pipeline, which release, which Nextflow and
which tools produced it. Falls back to a pipeline checkout's ``nextflow.config``
manifest when pointed at a source tree rather than a results directory.

Registered at import with ``priority = 100`` so a directory carrying several
engines' footprints resolves to Nextflow first.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from depictio.models.logging import logger
from depictio.models.models.run_info import WorkflowRunInfo, register_run_info_reader

ENGINE = "nextflow"

# nf-core writes the run's versions YAML under pipeline_info/ under one of three
# names depending on the pipeline's template generation. All three carry the same
# `Workflow:` identity section, so all three are searched, most specific first.
_VERSIONS_GLOBS: tuple[str, ...] = (
    "nf_core_*_software_mqc_versions.yml",
    "*_software_mqc_versions.yml",
    "software_versions.yml",
)

# `-params-file` runs write nf-params.json; nf-core's own launcher writes
# params_<timestamp>.json (one per resume, so the newest name wins).
PARAMS_GLOBS: tuple[str, ...] = ("params*.json", "nf-params.json", "nf_params.json")

_REPORT_GLOB = "execution_report*.html"
_TRACE_GLOB = "execution_trace*.txt"
_DAG_GLOB = "pipeline_dag*"

# The key inside the versions YAML that holds the run's identity rather than a
# process's tool versions.
_WORKFLOW_SECTION = "Workflow"

# A git-describe suffix appended by Nextflow when the pipeline was run from a
# checkout: `v2.16.0-g3d5c7e5`, `v2.13.0dev-ge7bcfda`.
_GIT_DESCRIBE_RE = re.compile(r"-g[0-9a-fA-F]+$")

# `manifest { ... }` block of a pipeline's nextflow.config.
_MANIFEST_BLOCK_RE = re.compile(r"manifest\s*\{(.*?)\n\}", re.DOTALL)


def normalize_pipeline_version(raw: str | None) -> str | None:
    """Reduce an engine-reported version string to a comparable release number.

    Nextflow reports whatever git-describe produced for the checkout it ran, so
    the same 2.16.0 release shows up as ``2.16.0``, ``v2.16.0`` or
    ``v2.16.0-g3d5c7e5``, and a pre-release as ``v2.13.0dev-ge7bcfda``. Bundled
    templates are named after the plain release, so strip, in order: a leading
    ``v``, a trailing git-describe ``-g<sha>``, and a trailing ``dev``.

        v2.16.0-g3d5c7e5     -> 2.16.0
        v2.13.0dev-ge7bcfda  -> 2.13.0
        v2.13.0dev           -> 2.13.0
        2.8.0                -> 2.8.0

    The raw string is never discarded — callers keep it in
    ``WorkflowRunInfo.extra["pipeline_version_raw"]`` so the exact provenance
    survives normalisation.
    """
    if not raw:
        return None
    version = str(raw).strip()
    if version.startswith("v"):
        version = version[1:]
    version = _GIT_DESCRIBE_RE.sub("", version)
    if version.endswith("dev"):
        version = version[: -len("dev")]
    return version or None


def _matching(directory: Path, pattern: str) -> list[Path]:
    """Files matching ``pattern``, oldest first — nf-core names these by timestamp."""
    return sorted(p for p in directory.glob(pattern) if p.is_file())


def _newest(directory: Path, pattern: str) -> Path | None:
    """Last match of ``pattern`` in name order."""
    matches = _matching(directory, pattern)
    return matches[-1] if matches else None


def _newest_matching(directory: Path, patterns: tuple[str, ...]) -> Path | None:
    """First ``_newest`` hit across ``patterns``, in order (most specific first)."""
    for pattern in patterns:
        match = _newest(directory, pattern)
        if match is not None:
            return match
    return None


def params_files_newest_first(directory: Path) -> list[Path]:
    """The run's params JSON files in ``directory``, newest first.

    A resumed run writes one params file per attempt, so a results directory
    routinely holds several and only the last describes the run that produced
    the outputs. Every reader of these files must therefore agree on "newest",
    which is why this is public and shared rather than re-globbed per caller:
    the CLI's template-variable introspection used to take the *first* match and
    so read the parameters of the first, abandoned attempt.

    A list rather than a single path so a caller can fall through to the next
    candidate when the newest file is unparseable, which is what a run killed
    mid-write leaves behind.

    Patterns are tried in order and the first one with any hit wins, so a
    directory holding both shapes never interleaves them.
    """
    for pattern in PARAMS_GLOBS:
        matches = _matching(directory, pattern)
        if matches:
            return list(reversed(matches))
    return []


def _parse_versions_yaml(path: Path) -> tuple[dict[str, Any], set[str]]:
    """Split a versions YAML into its ``Workflow:`` identity and the executed tools.

    nf-core writes ``{PROCESS: {tool: version}}`` plus one ``Workflow:`` section
    holding ``nf-core/<pipeline>: <version>`` and ``Nextflow: <version>``. The
    section is indented two spaces by some template generations and four by
    others, which is why this parses YAML rather than matching lines.
    """
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(f"Nextflow run-info: could not parse {path}: {exc}")
        return {}, set()
    if not isinstance(data, dict):
        return {}, set()

    workflow: dict[str, Any] = {}
    tools: set[str] = set()
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        if str(section) == _WORKFLOW_SECTION:
            workflow = values
            continue
        tools.update(str(tool).lower() for tool in values)
    return workflow, tools


def _identity_from_workflow_section(
    workflow: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """``(pipeline_name, raw_version, engine_version)`` from a ``Workflow:`` section."""
    pipeline_name: str | None = None
    raw_version: str | None = None
    engine_version: str | None = None
    for key, value in workflow.items():
        if str(key).lower() == "nextflow":
            engine_version = str(value)
        elif pipeline_name is None:
            pipeline_name = str(key)
            raw_version = str(value)
    return pipeline_name, raw_version, engine_version


def _manifest_entry(block: str, key: str) -> str | None:
    match = re.search(rf"^\s*{key}\s*=\s*['\"]([^'\"]+)['\"]", block, re.MULTILINE)
    return match.group(1) if match else None


def _identity_from_nextflow_config(
    run_dir: Path,
) -> tuple[str | None, str | None, str | None]:
    """``(name, version, homepage)`` from a pipeline checkout's ``manifest {}`` block.

    Only present when pointed at a pipeline source tree rather than a results
    directory. ``nextflowVersion`` is deliberately ignored: it is a *constraint*
    (``!>=25.04.3``), not the version that actually ran.
    """
    config = run_dir / "nextflow.config"
    if not config.is_file():
        return None, None, None
    try:
        text = config.read_text()
    except OSError as exc:
        logger.warning(f"Nextflow run-info: could not read {config}: {exc}")
        return None, None, None
    block_match = _MANIFEST_BLOCK_RE.search(text)
    if block_match is None:
        return None, None, None
    block = block_match.group(1)
    return (
        _manifest_entry(block, "name"),
        _manifest_entry(block, "version"),
        _manifest_entry(block, "homePage"),
    )


def _read_params(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        logger.warning(f"Nextflow run-info: could not parse {path}: {exc}")
        return {}
    return loaded if isinstance(loaded, dict) else {}


class NextflowRunInfoReader:
    """Recognise a Nextflow/nf-core results directory."""

    name = ENGINE
    priority = 100

    def read(self, run_dir: Path) -> WorkflowRunInfo | None:
        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            return None

        # Where pipeline_info sits depends on the project layout, not on the
        # engine. A "flat" project ingests one run and has it at the top; a
        # "sequencing-runs" project (viralrecon) points DATA_ROOT at the PARENT
        # of several run_*/ directories, each with its own pipeline_info. Looking
        # only at the top level meant every sequencing-runs project came back
        # unidentified, so it got no engine, no pipeline version, no Nextflow
        # version and no tool list, whether the template was auto-detected or
        # given explicitly. The CLI's other two readers of the same directory
        # already fall through to `*/pipeline_info`; this one did not.
        subdirs: list[Path] = []
        pipeline_info = run_dir / "pipeline_info"
        if not pipeline_info.is_dir():
            subdirs = sorted(d for d in run_dir.glob("*/pipeline_info") if d.is_dir())

        versions_path: Path | None = None
        params_path: Path | None = None
        report_path: Path | None = None
        trace_path: Path | None = None
        dag_path: Path | None = None
        workflow: dict[str, Any] = {}
        tools: set[str] = set()

        if pipeline_info.is_dir():
            versions_path = _newest_matching(pipeline_info, _VERSIONS_GLOBS)
            params_path = _newest_matching(pipeline_info, PARAMS_GLOBS)
            report_path = _newest(pipeline_info, _REPORT_GLOB)
            trace_path = _newest(pipeline_info, _TRACE_GLOB)
            dag_path = _newest(pipeline_info, _DAG_GLOB)
            if versions_path is not None:
                workflow, tools = _parse_versions_yaml(versions_path)
        elif subdirs:
            # Identity from the first run that carries one, deterministically:
            # the runs aggregated under one DATA_ROOT are the same pipeline, and
            # the artefact paths have to come from that same run to stay
            # coherent with each other. Tools are the exception and are unioned,
            # because "which tools produced this project" is genuinely the union
            # over the runs it holds: a nanopore run and an illumina run under
            # one project ran different tools, and reporting either alone would
            # be wrong.
            for candidate in subdirs:
                candidate_versions = _newest_matching(candidate, _VERSIONS_GLOBS)
                candidate_workflow: dict[str, Any] = {}
                candidate_tools: set[str] = set()
                if candidate_versions is not None:
                    candidate_workflow, candidate_tools = _parse_versions_yaml(candidate_versions)
                tools.update(candidate_tools)
                if versions_path is not None or not candidate_workflow:
                    continue
                workflow = candidate_workflow
                versions_path = candidate_versions
                pipeline_info = candidate
                params_path = _newest_matching(candidate, PARAMS_GLOBS)
                report_path = _newest(candidate, _REPORT_GLOB)
                trace_path = _newest(candidate, _TRACE_GLOB)
                dag_path = _newest(candidate, _DAG_GLOB)

        pipeline_name, raw_version, engine_version = _identity_from_workflow_section(workflow)
        homepage: str | None = None

        # Fallback identity: a pipeline checkout's manifest block.
        if pipeline_name is None:
            manifest_name, manifest_version, homepage = _identity_from_nextflow_config(run_dir)
            if manifest_name:
                pipeline_name = manifest_name
                raw_version = manifest_version

        # A run directory with none of these is not a Nextflow run as far as we
        # can tell — say so rather than returning a hollow, misleading answer.
        if not any((pipeline_name, versions_path, params_path, report_path, trace_path, dag_path)):
            return None

        # Only when the run wrote no versions YAML we recognise: catalog's reader
        # searches the whole tree for a legacy `software_versions.yml`.
        if not tools:
            from depictio.models.components.advanced_viz.catalog import read_software_versions

            tools = read_software_versions(run_dir)

        params = _read_params(params_path)
        extra: dict[str, Any] = {}
        if raw_version:
            extra["pipeline_version_raw"] = raw_version
        if subdirs:
            # Which run the identity came from, and how many contributed tools.
            # Without this a sequencing-runs project looks identical to a flat
            # one, and there is no way to tell that the version shown describes
            # one run out of several.
            extra["run_subdirs_scanned"] = len(subdirs)
            extra["identity_from_run"] = pipeline_info.parent.name

        run_name = params.get("run_name")
        return WorkflowRunInfo(
            engine=ENGINE,
            pipeline_name=pipeline_name,
            pipeline_version=normalize_pipeline_version(raw_version),
            engine_version=engine_version,
            run_name=str(run_name) if run_name else None,
            homepage=homepage,
            params=params,
            tools_executed=tools,
            software_versions_path=str(versions_path) if versions_path else None,
            params_json_path=str(params_path) if params_path else None,
            execution_report_path=str(report_path) if report_path else None,
            execution_trace_path=str(trace_path) if trace_path else None,
            pipeline_dag_path=str(dag_path) if dag_path else None,
            extra=extra,
        )


register_run_info_reader(NextflowRunInfoReader())
