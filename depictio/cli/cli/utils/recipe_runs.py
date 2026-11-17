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

import os
from collections.abc import Callable
from dataclasses import dataclass, field

import polars as pl

from depictio.cli.cli.utils.delta_versioning import RUN_ID_COLUMN
from depictio.cli.cli.utils.recipe_scopes import RecipeScope
from depictio.cli.cli.utils.run_roots import RunRoot, filter_frame_to_run


def unreachable_runs(runs: list[RunRoot]) -> list[RunRoot]:
    """Runs whose local folder is not on this host (an unmounted share, another
    machine). A recipe reading them finds no inputs, exactly as for a run the
    pipeline step skipped, so a full rewrite would drop their rows unnoticed.
    A remote root is read over the network and is never flagged here."""
    return [r for r in runs if not r.root.is_remote and not os.path.isdir(r.root.location)]


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
    run_tags: set[str] | None = None,
    **kwargs,
) -> PerRunResult:
    """Run ``execute`` (``depictio.recipes.execute_recipe``) on every run.

    A run that lacks one of the recipe's own input files (``source_missing``)
    is skipped when the project has several runs: that pipeline step did not
    run there. Any other failure, or a missing input with a single run, is
    raised, so a collection never silently loses a run.

    ``run_tags`` are all the project's runs when ``runs`` is only some of
    them (an --attach-run computes the new ones alone): the rows of the
    others are still another run's, never shared ones.
    """
    if not runs:
        raise ValueError("execute_per_run needs at least one run")
    run_tags = run_tags or {r.tag for r in runs}
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
            if len(runs) == 1 and len(run_tags) == 1:
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


# ── recomputed over every run ───────────────────────────────────────────────


def merge_wide(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Runs' wide tables (one column per sample) as one.

    Joined on the columns every run has (the feature: id, taxonomy, ...); the
    rest are samples, and a feature absent from a run counts 0 in its samples.
    A string-typed sample column (read with ``infer_schema_length=0``) gets
    ``"0"``.
    """
    if len(frames) <= 1:
        return frames[0] if frames else pl.DataFrame()
    shared = [c for c in frames[0].columns if all(c in f.columns for f in frames[1:])]
    if not shared:
        raise ValueError("the runs' wide tables share no column to join them on")
    out = frames[0]
    for frame in frames[1:]:
        right = frame.select(
            [pl.col(c).cast(out.schema[c]) if c in shared else pl.col(c) for c in frame.columns]
        )
        out = out.join(right, on=shared, how="full", coalesce=True, nulls_equal=True)
    fills = []
    for column in out.columns:
        if column in shared:
            continue
        dtype = out.schema[column]
        if dtype.is_numeric():
            fills.append(pl.col(column).fill_null(0))
        elif dtype == pl.String:
            fills.append(pl.col(column).fill_null("0"))
    return out.with_columns(fills) if fills else out


def combine_runs(frames: list[pl.DataFrame], how: str) -> pl.DataFrame | None:
    """One source read from several runs, put back together (see recipe_scopes)."""
    frames = [f for f in frames if f is not None]
    if not frames:
        return None
    if how == "wide":
        return merge_wide(frames)
    stacked = frames[0] if len(frames) == 1 else pl.concat(frames, how="diagonal_relaxed")
    return stacked.unique(maintain_order=True) if how == "unique" else stacked


def _split_by_run(frame: pl.DataFrame, run_tags: list[str]) -> list[pl.DataFrame]:
    """A stacked wide collection, back into one table per run, each without
    the other runs' (all-null) columns."""
    if RUN_ID_COLUMN not in frame.columns:
        return [frame]
    out = []
    for tag in run_tags:
        part = frame.filter(pl.col(RUN_ID_COLUMN).cast(pl.String) == tag)
        if part.is_empty():
            continue
        out.append(part.drop([*_other_runs_columns(part, frame), RUN_ID_COLUMN]))
    return out or [frame.drop(RUN_ID_COLUMN)]


_SAMPLE_COLUMNS = ("sample", "sample_id", "ID", "Sample", "sample_name")


def _sample_column(frame: pl.DataFrame, prefer: str | None = None) -> str | None:
    """The column of ``frame`` that names a sample, if any: ``prefer`` (the
    scope's declared one) first, then the usual names."""
    if prefer and prefer in frame.columns:
        return prefer
    return next((c for c in _SAMPLE_COLUMNS if c in frame.columns), None)


def _sample_runs(
    file_sources: dict[str, dict[str, pl.DataFrame]],
    refs: dict[str, RefFrame],
    prefer: str | None = None,
) -> dict[str, str]:
    """Which run each sample belongs to, read off the runs' inputs. A sample
    found in several runs belongs to none. ``prefer`` is the scope's sample
    column, looked for first, for a recipe whose samples are named by a column
    (``run_id``) that no other recipe uses that way."""
    seen: dict[str, set[str]] = {}

    def note(sample, tag):
        if sample is not None:
            seen.setdefault(str(sample), set()).add(tag)

    for per_run in file_sources.values():
        for tag, frame in per_run.items():
            if frame is None:
                continue
            column = _sample_column(frame, prefer)
            if column:
                for value in frame[column].unique().to_list():
                    note(value, tag)
            # A wide table: its sample columns are its non-shared columns.
            for name in frame.columns:
                note(name, tag)
    for ref in refs.values():
        frame = ref.frame
        if frame is None or RUN_ID_COLUMN not in frame.columns:
            continue
        column = _sample_column(frame, prefer)
        if column:
            pairs = frame.select(
                pl.col(column).cast(pl.String), pl.col(RUN_ID_COLUMN).cast(pl.String)
            )
            for sample, tag in pairs.unique().iter_rows():
                if tag is not None:
                    note(sample, tag)
    return {sample: next(iter(tags)) for sample, tags in seen.items() if len(tags) == 1}


@dataclass
class AggregateResult:
    frame: pl.DataFrame
    ran: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def execute_aggregate(
    execute: Callable[..., pl.DataFrame],
    resolve: Callable[[RunRoot], dict[str, pl.DataFrame]],
    recipe_name: str,
    runs: list[RunRoot],
    refs: dict[str, RefFrame],
    params: dict[str, str] | None,
    scope: RecipeScope,
    source_missing: type[Exception],
    **kwargs,
) -> AggregateResult:
    """Run ``execute`` once over every run (a recipe that mixes samples).

    ``resolve`` reads a run's file sources. A run without them is skipped,
    and is said so; none with them raises ``source_missing``. The runs' file
    sources and the ``dc_ref`` inputs (unfiltered, every run's rows) are put
    back together by ``scope.combine``. Each output row gets the run of its
    sample (``scope.sample_column``), or none when it aggregates several.
    """
    result = AggregateResult(frame=pl.DataFrame())
    per_source: dict[str, dict[str, pl.DataFrame]] = {}
    for run in runs:
        try:
            resolved = resolve(run)
        except source_missing as exc:
            result.skipped[run.tag] = str(exc)
            continue
        result.ran.append(run.tag)
        for ref, frame in resolved.items():
            per_source.setdefault(ref, {})[run.tag] = frame
    if not result.ran:
        reasons = "; ".join(f"{tag}: {why}" for tag, why in result.skipped.items())
        raise source_missing(f"Recipe {recipe_name} found its inputs in no run ({reasons})")

    combine = scope.combine
    sources = {
        ref: combine_runs(list(frames.values()), combine.get(ref, "rows"))
        for ref, frames in per_source.items()
    }
    run_order = [r.tag for r in runs]
    extra: dict[str, pl.DataFrame | None] = {}
    for ref, value in refs.items():
        frame = value.frame
        if frame is not None and combine.get(ref) == "wide":
            frame = merge_wide(_split_by_run(frame, run_order))
        elif frame is not None and value.from_recipe and RUN_ID_COLUMN in frame.columns:
            frame = frame.drop(RUN_ID_COLUMN)
        extra[ref] = frame

    first = next(r for r in runs if r.tag in result.ran)
    out = execute(
        recipe_name,
        first.root,
        extra_sources=extra or None,
        params=params,
        sources=sources,
        **kwargs,
    )
    sample_column = scope.sample_column
    if sample_column and sample_column in out.columns:
        owner = _sample_runs(per_source, refs, sample_column)
        run_of = (
            pl.col(sample_column)
            .cast(pl.String)
            .replace_strict(owner, default=None, return_dtype=pl.String)
        )
    else:
        run_of = pl.lit(None, dtype=pl.String)
    result.frame = out.with_columns(run_of.alias(RUN_ID_COLUMN))
    return result
