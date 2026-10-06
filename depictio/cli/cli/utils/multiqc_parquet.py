"""What a MultiQC report holds, read straight off its ``multiqc.parquet`` with polars.

The composer needs every (module, plot) pair a report carries, in report order,
before anything is ingested and without the ``multiqc`` package (an optional
extra of the ``depictio`` install). The parquet's ``run_metadata`` row already
lists them: a JSON ``modules`` column of ``{anchor, name, sections: [{name,
anchor, plot_anchor}]}``. A section with a ``plot_anchor`` is a plot, named the
way ingestion names it (``section.name or section.anchor``, see
``multiqc_processor.extract_multiqc_metadata``), so a component built from these
pairs resolves against what ingestion records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from depictio.cli.cli_logging import logger


@dataclass(frozen=True)
class MultiQCPlot:
    module: str  # module anchor, the component's selected_module
    module_name: str  # display name, e.g. "FastQC"
    plot: str  # section name, the component's selected_plot


def parquet_plots(path: str | Path) -> list[MultiQCPlot]:
    """Every plot the report holds, module by module in report order; [] if unreadable."""
    import polars as pl

    try:
        frame = pl.read_parquet(path, columns=["type", "modules"])
    except Exception as exc:
        logger.warning(f"Could not read the MultiQC report {path}: {exc}")
        return []
    raw = frame.filter(pl.col("type") == "run_metadata")["modules"].drop_nulls().to_list()
    plots: list[MultiQCPlot] = []
    seen: set[tuple[str, str]] = set()
    for blob in raw[:1]:
        try:
            modules = json.loads(blob) if isinstance(blob, str) else blob
        except ValueError:
            continue
        for module in modules or []:
            if not isinstance(module, dict) or not module.get("anchor"):
                continue
            anchor = str(module["anchor"])
            for section in module.get("sections") or []:
                if not isinstance(section, dict) or not section.get("plot_anchor"):
                    continue
                name = str(section.get("name") or section.get("anchor") or "")
                if not name or (anchor, name) in seen:
                    continue
                seen.add((anchor, name))
                plots.append(MultiQCPlot(anchor, str(module.get("name") or anchor), name))
    return plots


def parquet_has_general_stats(path: str | Path) -> bool:
    """Whether the report carries a General Statistics table."""
    from depictio.cli.cli.utils.multiqc_processor import _parquet_has_general_stats

    return bool(_parquet_has_general_stats(str(path)))
