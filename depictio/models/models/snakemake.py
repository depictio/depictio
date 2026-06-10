"""Snakemake connector: read a run's provenance from its working directory.

Reference template for additional connectors. Snakemake has no canonical
self-describing manifest like nf-core's ``pipeline_info/`` (identity/version are
best-effort), so recognition keys off the engine's footprint (``.snakemake/``,
``Snakefile``, ``config.yaml``) and the dashboard composition (catalog file
recognition) remains the primary driver.

Registers itself with the generic run-info registry (``run_info.py``).
"""

from __future__ import annotations

from pathlib import Path

from depictio.models.models.run_info import WorkflowRunInfo, register_run_info_reader

# Files whose presence identifies a Snakemake working directory.
_SNAKEFILES = ("Snakefile", "workflow/Snakefile")
_CONFIGS = ("config.yaml", "config.yml", "config/config.yaml", "config/config.yml")


def _looks_like_snakemake(run_dir: Path) -> bool:
    if (run_dir / ".snakemake").is_dir():
        return True
    return any((run_dir / rel).is_file() for rel in (*_SNAKEFILES, *_CONFIGS))


def _load_config(run_dir: Path) -> tuple[dict, Path | None]:
    import yaml

    for rel in _CONFIGS:
        path = run_dir / rel
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text()) or {}
            except Exception:
                return {}, path
            return (data if isinstance(data, dict) else {}), path
    return {}, None


def _conda_tools(run_dir: Path) -> set[str]:
    """Best-effort tool names from ``.snakemake/conda/*.yaml`` env definitions."""
    import yaml

    tools: set[str] = set()
    conda_dir = run_dir / ".snakemake" / "conda"
    if not conda_dir.is_dir():
        return tools
    for env in sorted(conda_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(env.read_text()) or {}
        except Exception:
            continue
        for dep in data.get("dependencies", []) if isinstance(data, dict) else []:
            # dependencies are "tool=version" strings (or dicts like {pip: [...]}).
            if isinstance(dep, str):
                tools.add(dep.split("=", 1)[0].split("::")[-1].strip().lower())
    return tools


def read_snakemake_run_info(run_dir: str | Path) -> WorkflowRunInfo | None:
    """Read a Snakemake run's provenance, or None if the dir isn't a Snakemake run."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir() or not _looks_like_snakemake(run_dir):
        return None

    config, _ = _load_config(run_dir)
    pipeline_name = None
    for key in ("pipeline", "name", "workflow"):
        value = config.get(key)
        if isinstance(value, str) and value:
            pipeline_name = value
            break
    if not pipeline_name:
        pipeline_name = run_dir.name

    version = config.get("version")
    pipeline_version = str(version).lstrip("v") if version is not None else None

    return WorkflowRunInfo(
        engine="snakemake",
        pipeline_name=pipeline_name,
        pipeline_version=pipeline_version,
        params=config,
        tools_executed=_conda_tools(run_dir),
    )


class _SnakemakeReader:
    """Connector entry for the run-info registry."""

    name = "snakemake"
    priority = 50  # below nf-core (less self-describing)

    def read(self, run_dir: Path) -> WorkflowRunInfo | None:
        return read_snakemake_run_info(run_dir)


register_run_info_reader(_SnakemakeReader())
