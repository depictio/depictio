"""Snakemake connector for the run-provenance registry.

Snakemake has no equivalent of nf-core's ``pipeline_info/``: there is no
standard file that names the pipeline and its release. So this connector is
deliberately weaker than the Nextflow one — it recognises the workflow's
footprint (``.snakemake/`` metadata, a ``Snakefile``) and then reads what
identity it can from the project's config file, falling back to the directory
name.

Registered at import with ``priority = 50``, below Nextflow: a Nextflow run
staged inside a Snakemake project should still resolve as Nextflow, which has
the stronger, unambiguous signal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from depictio.models.logging import logger
from depictio.models.models.run_info import WorkflowRunInfo, register_run_info_reader

ENGINE = "snakemake"

_METADATA_DIR = ".snakemake"

# Both the flat layout and the recommended `workflow/` layout.
_SNAKEFILES: tuple[str, ...] = ("Snakefile", "workflow/Snakefile")

_CONFIG_FILES: tuple[str, ...] = (
    "config.yaml",
    "config.yml",
    "config/config.yaml",
    "config/config.yml",
)

# Keys a project might use to name itself, most explicit first.
_NAME_KEYS: tuple[str, ...] = ("pipeline", "name", "workflow")

# Per-rule conda environments Snakemake materialises under .snakemake/conda/.
_CONDA_ENV_GLOBS: tuple[str, ...] = ("conda/*.yaml", "conda/*.yml")


def _first_existing(run_dir: Path, relatives: tuple[str, ...]) -> Path | None:
    for relative in relatives:
        candidate = run_dir / relative
        if candidate.is_file():
            return candidate
    return None


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        loaded = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(f"Snakemake run-info: could not parse {path}: {exc}")
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _tools_from_conda_envs(metadata_dir: Path) -> set[str]:
    """Tool names from the ``dependencies:`` of every materialised conda env.

    Entries look like ``bioconda::fastqc=0.12.1`` or ``samtools=1.19``; the
    channel prefix and the version pin are both dropped, leaving the tool name.
    A nested ``pip:`` mapping is skipped — it lists Python distributions, not
    the workflow's tools.
    """
    tools: set[str] = set()
    for pattern in _CONDA_ENV_GLOBS:
        for env_path in sorted(metadata_dir.glob(pattern)):
            try:
                env = yaml.safe_load(env_path.read_text()) or {}
            except (OSError, yaml.YAMLError) as exc:
                logger.warning(f"Snakemake run-info: could not parse {env_path}: {exc}")
                continue
            if not isinstance(env, dict):
                continue
            for dependency in env.get("dependencies") or []:
                if not isinstance(dependency, str):
                    continue  # e.g. {"pip": [...]}
                spec = dependency.split("::", 1)[-1]
                name = spec.split("=", 1)[0].strip().lower()
                if name:
                    tools.add(name)
    return tools


class SnakemakeRunInfoReader:
    """Recognise a Snakemake workflow directory."""

    name = ENGINE
    priority = 50

    def read(self, run_dir: Path) -> WorkflowRunInfo | None:
        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            return None

        metadata_dir = run_dir / _METADATA_DIR
        snakefile = _first_existing(run_dir, _SNAKEFILES)
        # Recognition rests on the two signals unique to Snakemake. A bare
        # `config.yaml` is far too common to identify an engine on its own, so
        # it contributes identity but never recognition.
        if not metadata_dir.is_dir() and snakefile is None:
            return None

        config_path = _first_existing(run_dir, _CONFIG_FILES)
        config = _load_config(config_path)

        pipeline_name: str | None = None
        for key in _NAME_KEYS:
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                pipeline_name = value.strip()
                break
        if pipeline_name is None:
            pipeline_name = run_dir.resolve().name or None

        version = config.get("version")
        pipeline_version = str(version).strip() if version not in (None, "") else None

        tools = _tools_from_conda_envs(metadata_dir) if metadata_dir.is_dir() else set()

        extra: dict[str, Any] = {}
        if config_path is not None:
            extra["config_path"] = str(config_path)
        if snakefile is not None:
            extra["snakefile_path"] = str(snakefile)

        return WorkflowRunInfo(
            engine=ENGINE,
            pipeline_name=pipeline_name,
            pipeline_version=pipeline_version,
            tools_executed=tools,
            extra=extra,
        )


register_run_info_reader(SnakemakeRunInfoReader())
