"""Run a recipe once per run of its workflow (epic #1399).

A recipe reads the files of one run folder. A project holds as many runs as
``data_location.locations`` (and, under ``sequencing-runs``, their run
folders) list, so the recipe runs once per run and the outputs are stacked,
each row tagged with its run in ``depictio_run_id``, like every file-backed
table. With one run the output is what the recipe returns, plus that column.

``dc_ref`` inputs are other collections of the project. Each run sees only its
own rows of a collection tagged per run, and the whole of a collection that
belongs to no run (a file shared by every run). An input that is itself a
recipe output loses its ``depictio_run_id`` column before the recipe sees it:
recipes were written against frames without it, and one that casts every
column to a number would choke on it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import polars as pl

from depictio.cli.cli.utils.delta_versioning import RUN_ID_COLUMN
from depictio.cli.cli.utils.run_roots import RunRoot, filter_frame_to_run


@dataclass(frozen=True)
class RefFrame:
    """A ``dc_ref`` input: the collection's table (None when absent and optional)
    and whether it is a recipe output, whose run column the recipe must not see."""

    frame: pl.DataFrame | None
    from_recipe: bool = False


@dataclass
class PerRunResult:
    frame: pl.DataFrame
    ran: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def _other_runs_columns(frame: pl.DataFrame, whole: pl.DataFrame) -> list[str]:
    """Columns null in every row of this run but filled in another run's.

    Per-run tables stack with ``diagonal_relaxed``: a wide table (one column
    per sample) gains every other run's columns, null in this run's rows. The
    run's own table never had them, and a recipe that reads every column as a
    sample (a PCoA on a taxa x samples matrix) would take them for samples.
    """
    if frame.is_empty():
        return []
    nulls = frame.null_count().row(0, named=True)
    candidates = [c for c, n in nulls.items() if n == frame.height and c != RUN_ID_COLUMN]
    if not candidates:
        return []
    filled = whole.select(candidates).null_count().row(0, named=True)
    return [c for c in candidates if filled[c] < whole.height]


def ref_frames_for_run(
    refs: dict[str, RefFrame], run_tag: str, run_tags: set[str]
) -> dict[str, pl.DataFrame | None]:
    """The ``dc_ref`` inputs one run's recipe sees."""
    out: dict[str, pl.DataFrame | None] = {}
    for ref, value in refs.items():
        frame = value.frame
        if frame is None:
            out[ref] = None
            continue
        whole = frame
        frame = filter_frame_to_run(frame, run_tag, run_tags)
        if len(run_tags) > 1 and frame.height < whole.height:
            frame = frame.drop(_other_runs_columns(frame, whole))
        if value.from_recipe and RUN_ID_COLUMN in frame.columns:
            frame = frame.drop(RUN_ID_COLUMN)
        out[ref] = frame
    return out


def execute_per_run(
    execute: Callable[..., pl.DataFrame],
    recipe_name: str,
    runs: list[RunRoot],
    refs: dict[str, RefFrame],
    params_for: Callable[[RunRoot], dict[str, str] | None],
    source_missing: type[Exception],
    **kwargs,
) -> PerRunResult:
    """Run ``execute`` (``depictio.recipes.execute_recipe``) on every run.

    A run that lacks one of the recipe's own input files (``source_missing``)
    is skipped when the project has several runs: that pipeline step did not
    run there. Any other failure, or a missing input with a single run, is
    raised, so a collection never silently loses a run.
    """
    if not runs:
        raise ValueError("execute_per_run needs at least one run")
    run_tags = {r.tag for r in runs}
    frames: list[pl.DataFrame] = []
    result = PerRunResult(frame=pl.DataFrame())
    for run in runs:
        try:
            frame = execute(
                recipe_name,
                run.root,
                extra_sources=ref_frames_for_run(refs, run.tag, run_tags) or None,
                params=params_for(run),
                **kwargs,
            )
        except source_missing as exc:
            if len(runs) == 1:
                raise
            result.skipped[run.tag] = str(exc)
            continue
        frames.append(frame.with_columns(pl.lit(run.tag).alias(RUN_ID_COLUMN)))
        result.ran.append(run.tag)
    if not frames:
        reasons = "; ".join(f"{tag}: {why}" for tag, why in result.skipped.items())
        raise source_missing(f"Recipe {recipe_name} found its inputs in no run ({reasons})")
    result.frame = frames[0] if len(frames) == 1 else pl.concat(frames, how="diagonal_relaxed")
    return result
