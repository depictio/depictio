"""Multi-report uniformity checks for a MultiQC data collection.

When a user uploads multiple MultiQC reports to one DC (replace or append), the
processor currently merges them by union: ``samples.extend``,
``modules.extend``, ``plots.update``. If the reports were produced with
different module sets or MultiQC versions, the merge silently drops modules
for half the samples and produces half-populated figures with no warning.

This module checks that all reports in a DC share the same shape — same
modules, same plot keys, same MultiQC major.minor — and raises
``HTTPException(422)`` with a structured payload pointing at the specific
mismatch.

Pure function: no I/O. The caller passes in metadata dicts (typically pulled
from the ``multiqc_collection`` after ``process_data_collection_helper``
returns) and gets either a clean return or a 422.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from fastapi import HTTPException

from depictio.api.v1.configs.logging_init import logger


def _report_label(report: Mapping[str, Any]) -> str:
    """Best-effort short identifier for error messages."""
    for key in ("report_name", "original_file_path", "s3_location", "id", "_id"):
        v = report.get(key)
        if v:
            return str(v)
    return "<unknown>"


def _coerce_metadata(report: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one report's metadata to a flat dict regardless of input shape.

    ``report`` may be either a raw mongo doc (with nested ``metadata`` subdoc)
    or an already-flat dict (e.g. from a ``MultiQCMetadata`` ``model_dump()``).
    Returns ``{modules, plots, samples, multiqc_version, _label}``.
    """
    nested = report.get("metadata")
    metadata: Mapping[str, Any] = nested if isinstance(nested, Mapping) else report
    return {
        "modules": list(metadata.get("modules") or []),
        "plots": dict(metadata.get("plots") or {}),
        "samples": list(metadata.get("samples") or []),
        "multiqc_version": report.get("multiqc_version") or metadata.get("multiqc_version"),
        "_label": _report_label(report),
    }


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)")


def _major_minor(version: str | None) -> tuple[int, int] | None:
    """Extract ``(major, minor)`` from a version string; ``None`` on bad input."""
    if not version:
        return None
    m = _VERSION_RE.match(str(version))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _flat_plot_ids(plots: Mapping[str, Any]) -> set[str]:
    """Flatten a MultiQC ``plots`` dict into ``{"<module>::<plot>"}`` identifiers.

    The shape returned by ``multiqc.list_plots()`` is
    ``{module: [plot_name_or_{plot_name: [variants]}, ...]}``. Comparing only the
    top-level module keys (the previous implementation) misses the
    ``plots_mismatch`` case where two reports both list e.g. ``fastqc`` as the
    module but one is missing a specific plot like "Adapter Content". Flattening
    surfaces that.
    """
    out: set[str] = set()
    for module, items in plots.items():
        if not isinstance(items, (list, tuple)):
            continue
        for item in items:
            if isinstance(item, str):
                out.add(f"{module}::{item}")
            elif isinstance(item, Mapping):
                for k in item.keys():
                    out.add(f"{module}::{k}")
    return out


def _raise_mismatch(kind: str, summary: str, details: dict[str, Any]) -> None:
    raise HTTPException(
        status_code=422,
        detail={
            "code": "multiqc_report_mismatch",
            "kind": kind,
            "summary": summary,
            "details": details,
        },
    )


def validate_multiqc_reports_uniform(reports: Iterable[Mapping[str, Any]]) -> None:
    """Assert the reports are structurally compatible. Raises ``HTTPException(422)``.

    Checks (in order):
      1. **modules** — every report has the same ``set(modules)``.
      2. **plots** — every report has the same ``set(plots.keys())``.
      3. **multiqc_version** — every report shares the same major.minor (patch
         differences are logged but not raised; missing version is ignored).
      4. **samples** — no sample name appears in two reports.

    A single report (or zero) passes trivially.
    """
    normalized = [_coerce_metadata(r) for r in reports]
    if len(normalized) <= 1:
        return

    # 1. modules
    baseline_modules = set(normalized[0]["modules"])
    baseline_label = normalized[0]["_label"]
    for entry in normalized[1:]:
        modules = set(entry["modules"])
        if modules != baseline_modules:
            added = sorted(modules - baseline_modules)
            removed = sorted(baseline_modules - modules)
            _raise_mismatch(
                kind="modules",
                summary=(f"Module set differs between '{baseline_label}' and '{entry['_label']}'."),
                details={
                    "baseline_report": baseline_label,
                    "compared_report": entry["_label"],
                    "added_in_compared": added,
                    "removed_in_compared": removed,
                },
            )

    # 2. plot identities (module + plot name). Top-level keys alone aren't
    #    enough — two reports can both list "fastqc" as the module while one
    #    is missing an individual plot ("Adapter Content"), which the merge
    #    would silently drop.
    baseline_plots = _flat_plot_ids(normalized[0]["plots"])
    for entry in normalized[1:]:
        plots = _flat_plot_ids(entry["plots"])
        if plots != baseline_plots:
            added = sorted(plots - baseline_plots)
            removed = sorted(baseline_plots - plots)
            _raise_mismatch(
                kind="plots",
                summary=(f"Plot set differs between '{baseline_label}' and '{entry['_label']}'."),
                details={
                    "baseline_report": baseline_label,
                    "compared_report": entry["_label"],
                    "added_in_compared": added,
                    "removed_in_compared": removed,
                },
            )

    # 3. multiqc_version (major.minor strict; patch diff logs only)
    baseline_mm = _major_minor(normalized[0]["multiqc_version"])
    for entry in normalized[1:]:
        entry_mm = _major_minor(entry["multiqc_version"])
        if baseline_mm is None or entry_mm is None:
            continue
        if baseline_mm != entry_mm:
            _raise_mismatch(
                kind="version",
                summary=(
                    f"MultiQC version differs between '{baseline_label}' "
                    f"({normalized[0]['multiqc_version']}) and '{entry['_label']}' "
                    f"({entry['multiqc_version']})."
                ),
                details={
                    "baseline_report": baseline_label,
                    "baseline_version": normalized[0]["multiqc_version"],
                    "compared_report": entry["_label"],
                    "compared_version": entry["multiqc_version"],
                },
            )
        # Patch-level differences are tolerated but logged so anomalies surface.
        if normalized[0]["multiqc_version"] != entry["multiqc_version"]:
            logger.info(
                f"MultiQC patch-version drift between '{baseline_label}' "
                f"({normalized[0]['multiqc_version']}) and '{entry['_label']}' "
                f"({entry['multiqc_version']}) — same major.minor, proceeding."
            )

    # 4. sample uniqueness across reports
    sample_owners: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for entry in normalized:
        for sample in entry["samples"]:
            sample_str = str(sample)
            if sample_str in sample_owners and sample_owners[sample_str] != entry["_label"]:
                duplicates.setdefault(sample_str, [sample_owners[sample_str]]).append(
                    entry["_label"]
                )
            else:
                sample_owners[sample_str] = entry["_label"]
    if duplicates:
        first = next(iter(duplicates.items()))
        sample, owners = first
        _raise_mismatch(
            kind="samples",
            summary=(
                f"Sample '{sample}' appears in multiple reports: {', '.join(sorted(set(owners)))}."
            ),
            details={
                "duplicate_samples": {k: sorted(set(v)) for k, v in duplicates.items()},
            },
        )
