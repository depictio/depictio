"""The runs of a workflow, as the recipes and the single-file scan see them.

A workflow's ``data_location.locations`` are its runs: a ``flat`` location is
one run named after its directory, a ``sequencing-runs`` location holds one run
per sub-directory matching ``runs_regex``. The recursive scan registers runs
under exactly these tags (``scan.flat_run_tag`` and the run sub-directory
name), so every collection a run feeds carries the same ``depictio_run_id``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from depictio.cli.cli.utils.delta_versioning import RUN_ID_COLUMN

if TYPE_CHECKING:
    from depictio.cli.cli.utils.data_root import DataRoot


@dataclass(frozen=True)
class RunRoot:
    """One run: its tag, the root a recipe reads it from, and its location."""

    tag: str
    root: DataRoot
    location: str


def flat_run_tag(location: str) -> str:
    """The run a ``structure: flat`` location is registered as: its directory's name."""
    return os.path.basename(os.path.normpath(location))


def single_scan_tag(dc_tag: str) -> str:
    """The run tag of a single file that belongs to no run in particular."""
    return f"{dc_tag}-single-file-scan"


def iter_run_roots(data_location, CLI_config=None) -> list[RunRoot]:
    """Every run of ``data_location``, in location order.

    Raises ``ValueError`` for a location no :class:`DataRoot` can list (see
    ``data_root_for``).
    """
    from depictio.cli.cli.utils.data_root import data_root_for

    if data_location is None:
        return []
    locations = [str(loc) for loc in (getattr(data_location, "locations", None) or [])]
    structure = getattr(data_location, "structure", None)
    runs_regex = getattr(data_location, "runs_regex", None)
    runs: list[RunRoot] = []
    for location in locations:
        base = data_root_for(location, CLI_config)
        if structure == "sequencing-runs" and runs_regex:
            names = base.runs(runs_regex)
            if names:
                runs.extend(RunRoot(name, base.scoped(name), location) for name in names)
                continue
            # A location without run folders reads as one run, as the recipes
            # always treated it.
        runs.append(RunRoot(flat_run_tag(location), base, location))
    return runs


def single_file_run_tag(
    dc_tag: str,
    file_path: str,
    location: str | None,
    structure: str | None,
    runs_regex: str | None,
) -> str:
    """The run a single file bound to ``location`` belongs to.

    A flat location is one run, so its file is that run's wherever it lives.
    Under ``sequencing-runs`` the file is a run's only when it sits inside one
    of the location's run folders; a file at the location's top (a samplesheet
    for all its runs) belongs to none. No location (a file shared by several
    runs, or a collection declared project-wide) belongs to none either.
    """
    import re

    if location is None:
        return single_scan_tag(dc_tag)
    if structure != "sequencing-runs" or not runs_regex:
        return flat_run_tag(location)
    real_file = os.path.realpath(file_path)
    real_location = os.path.realpath(location)
    rel = os.path.relpath(real_file, real_location)
    first = rel.split(os.sep, 1)[0]
    if rel.startswith("..") or first == rel or not re.match(runs_regex, first):
        return single_scan_tag(dc_tag)
    return first


def filter_frame_to_run(df: pl.DataFrame, run_tag: str, run_tags: set[str]) -> pl.DataFrame:
    """The rows of ``df`` a recipe running on ``run_tag`` should see.

    A row tagged with another of the project's runs is left out. A row tagged
    with no run of the project (a file shared by every run, a URL or manifest
    collection) is kept for every run, and a frame without the column passes
    whole.
    """
    if RUN_ID_COLUMN not in df.columns:
        return df
    col = pl.col(RUN_ID_COLUMN).cast(pl.String)
    others = sorted(run_tags - {run_tag})
    if not others:
        return df
    return df.filter(~col.is_in(others) | col.is_null())
