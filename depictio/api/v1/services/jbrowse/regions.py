"""Genomic regions of a genome browser tile: the picker, the next / previous step, the density.

The regions are the rows of the ``locus_from`` collections (peaks, DE genes,
variants...). ``source_frame`` turns one collection into a common shape so that
several of them (and several samples or runs) can be merged, sorted, searched,
stepped through and binned together. Everything here is pure polars: reading
the collections and the filters is the endpoint's job.

Chromosome names are compared with the ``chr`` prefix ignored (``chr1`` = ``1``,
``M`` = ``MT``), because collections and assemblies rarely agree on it.

The common shape (``source_frame``): ``chrom`` (str), ``start`` <= ``end``
(int, null when unreadable), ``score`` (the ``sort_by`` cell), ``label``,
``sample``, ``run``, ``source`` (the source's name), ``x:<column>`` (the
picker's ``columns``), ``s:<column>`` (``search_columns`` only) and, on the
primary source with a ``mate``, ``_mchrom`` / ``_mstart`` / ``_mend``.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

MAX_DENSITY_TRACKS = 64
MAX_MERGED_SAMPLES = 10

#: Columns of the common shape a sort may name directly (merged rows add counts).
NORMALISED_SORT_COLUMNS = ("chrom", "start", "end", "score", "label", "sample", "run", "source")
MERGED_SORT_COLUMNS = ("n_rows", "n_samples")

_BASE_COLUMNS = ("chrom", "start", "end", "score", "label", "sample", "run", "source")

# ---------------------------------------------------------------------------
# Chromosome names
# ---------------------------------------------------------------------------


def canonical_chrom(name: Any) -> str:
    """``name`` without a leading ``chr`` / ``Chr`` / ``CHR``; ``M`` and ``MT`` are one."""
    s = str(name).strip()
    if s[:3].lower() == "chr":
        s = s[3:]
    return "MT" if s in ("M", "MT") else s


def canonical_expr(col: pl.Expr) -> pl.Expr:
    """``canonical_chrom`` as an expression."""
    s = col.cast(pl.Utf8).str.strip_chars().str.replace(r"^(?i:chr)", "")
    return pl.when(s.is_in(["M", "MT"])).then(pl.lit("MT")).otherwise(s)


def chrom_index(chrom_order: list[str]) -> dict[str, int]:
    """Position of each canonical chromosome name in ``chrom_order`` (first wins)."""
    out: dict[str, int] = {}
    for i, name in enumerate(chrom_order):
        out.setdefault(canonical_chrom(name), i)
    return out


def chrom_name_variants(values: Any) -> list[str]:
    """``values`` plus the spellings of the same chromosomes with and without ``chr``."""
    items = values if isinstance(values, list | tuple) else [values]
    out: dict[str, None] = {}
    for v in items:
        if v is None:
            continue
        out[str(v)] = None
        canon = canonical_chrom(v)
        spellings = [canon, f"chr{canon}"]
        if canon == "MT":
            spellings += ["M", "chrM", "MT", "chrMT"]
        for s in spellings:
            out[s] = None
    return list(out)


def _natural_rank(canonical_names: set[str]) -> dict[str, int]:
    """Karyotype order: 1, 2, ... 22, X, Y, MT, then anything else by name."""
    special = {"X": 0, "Y": 1, "MT": 2}

    def key(name: str) -> tuple[int, int, str]:
        if name.isdigit():
            return (0, int(name), "")
        if name in special:
            return (1, special[name], "")
        return (2, 0, name)

    return {name: i for i, name in enumerate(sorted(canonical_names, key=key))}


def _rank_expr(df: pl.DataFrame, column: str, canonical: bool = False) -> pl.Expr:
    """Karyotype rank of the chromosome in ``column`` (null for a null name)."""
    uniq = df[column].drop_nulls().unique().to_list() if column in df.columns else []
    names = {str(c) if canonical else canonical_chrom(c) for c in uniq}
    expr = pl.col(column) if canonical else canonical_expr(pl.col(column))
    return expr.replace_strict(_natural_rank(names), default=None, return_dtype=pl.Int64)


# ---------------------------------------------------------------------------
# The common shape of a source
# ---------------------------------------------------------------------------


def _col(df: pl.DataFrame, name: str | None) -> pl.Expr:
    return pl.col(name) if name and name in df.columns else pl.lit(None)


def _int(expr: pl.Expr) -> pl.Expr:
    return expr.cast(pl.Float64, strict=False).cast(pl.Int64, strict=False)


def _span(df: pl.DataFrame, chrom_c: str | None, start_c: str | None, end_c: str | None):
    """``(chrom, lo, hi)`` expressions; ``lo`` / ``hi`` are null unless both ends read."""
    start = _int(_col(df, start_c))
    end = _int(_col(df, end_c)) if end_c else start
    unreadable = start.is_null() | end.is_null()
    null = pl.lit(None, dtype=pl.Int64)
    lo = pl.when(unreadable).then(null).otherwise(pl.min_horizontal(start, end))
    hi = pl.when(unreadable).then(null).otherwise(pl.max_horizontal(start, end))
    return _col(df, chrom_c).cast(pl.Utf8), lo, hi


def extra_columns(spec: dict[str, Any]) -> list[str]:
    """The ``columns`` the picker shows, each once."""
    return list(dict.fromkeys(spec.get("columns") or []))


def search_only_columns(spec: dict[str, Any]) -> list[str]:
    """The ``search_columns`` that are not already shown as ``columns``."""
    shown = set(extra_columns(spec))
    return [c for c in dict.fromkeys(spec.get("search_columns") or []) if c not in shown]


def source_frame(df: pl.DataFrame, spec: dict[str, Any], is_primary: bool = False) -> pl.DataFrame:
    """One ``locus_from`` collection in the common shape (see the module docstring).

    A column the collection lacks reads as null, so a mistyped column degrades to
    rows without coordinates (no locus) rather than failing the whole listing.
    """
    chrom, lo, hi = _span(
        df, spec.get("chrom_column"), spec.get("start_column"), spec.get("end_column")
    )
    exprs: dict[str, pl.Expr] = {
        "chrom": chrom,
        "start": lo,
        "end": hi,
        "score": _col(df, spec.get("sort_by")),
        "label": _col(df, spec.get("label_column")).cast(pl.Utf8),
        "sample": _col(df, spec.get("sample_column")).cast(pl.Utf8),
        "run": _col(df, spec.get("run_column")).cast(pl.Utf8),
        "source": pl.lit(str(spec.get("name") or spec.get("data_collection_tag") or "")),
    }
    for c in extra_columns(spec):
        exprs[f"x:{c}"] = _col(df, c)
    for c in search_only_columns(spec):
        exprs[f"s:{c}"] = _col(df, c)
    mate = spec.get("mate") if is_primary else None
    if mate:
        mchrom, mlo, mhi = _span(
            df, mate.get("chrom_column"), mate.get("start_column"), mate.get("end_column")
        )
        exprs.update({"_mchrom": mchrom, "_mstart": mlo, "_mend": mhi})
    # with_columns, not select: a frame with no usable column must keep its height.
    staged = df.with_columns(**{f"__{k}": v for k, v in exprs.items()})
    return staged.select(**{k: pl.col(f"__{k}") for k in exprs})


def union_frames(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """The frames of several sources one under the other (source order kept)."""
    if len(frames) == 1:
        return frames[0]
    try:
        return pl.concat(frames, how="diagonal_relaxed")
    except Exception:  # noqa: BLE001 - extras of incompatible types: compare them as text
        text = [
            f.with_columns(
                [pl.col(c).cast(pl.Utf8) for c in f.columns if c.startswith(("x:", "s:", "score"))]
            )
            for f in frames
        ]
        return pl.concat(text, how="diagonal_relaxed")


def _ensure(df: pl.DataFrame) -> pl.DataFrame:
    """``df`` with every column of the common shape (null when absent)."""
    missing = [c for c in _BASE_COLUMNS if c not in df.columns]
    return df.with_columns([pl.lit(None).alias(c) for c in missing]) if missing else df


def _drop_internal(df: pl.DataFrame, extra: list[str]) -> pl.DataFrame:
    return df.drop([c for c in extra if c in df.columns])


# ---------------------------------------------------------------------------
# Sorting and searching
# ---------------------------------------------------------------------------


def normalised_name(spec: dict[str, Any], column: str) -> str | None:
    """The column of the common shape a raw column of ``spec`` is read into."""
    pairs = (
        (spec.get("chrom_column"), "chrom"),
        (spec.get("start_column"), "start"),
        (spec.get("end_column"), "end"),
        (spec.get("sort_by"), "score"),
        (spec.get("label_column"), "label"),
        (spec.get("sample_column"), "sample"),
        (spec.get("run_column"), "run"),
    )
    for raw, norm in pairs:
        if raw and raw == column:
            return norm
    if column in extra_columns(spec):
        return f"x:{column}"
    return None


def sortable_columns(specs: list[dict[str, Any]], merged: bool = False) -> list[str]:
    """Every name a sort accepts: the common-shape names and the sources' raw columns."""
    names = list(NORMALISED_SORT_COLUMNS) + (list(MERGED_SORT_COLUMNS) if merged else [])
    for spec in specs:
        for raw in (
            spec.get("chrom_column"),
            spec.get("start_column"),
            spec.get("end_column"),
            spec.get("sort_by"),
            spec.get("label_column"),
            spec.get("sample_column"),
            spec.get("run_column"),
            *extra_columns(spec),
        ):
            if raw:
                names.append(raw)
    return list(dict.fromkeys(names))


def sort_keys(
    df: pl.DataFrame, specs: list[dict[str, Any]], column: str, merged: bool = False
) -> list[pl.Expr] | None:
    """Sort expressions for ``column``, or None when no source reads such a column.

    The common-shape names (``chrom``, ``start``, ``end``, ``score``, ``label``,
    ``sample``, ``run``, ``source``, and ``n_rows`` / ``n_samples`` when merged)
    win; any other name is a raw column, read from each source that has it.
    ``chrom`` sorts in karyotype order, then by start.
    """
    if column in NORMALISED_SORT_COLUMNS or (merged and column in MERGED_SORT_COLUMNS):
        names = {column}
        by_source = {}
    else:
        by_source = {
            str(s.get("name") or s.get("data_collection_tag") or ""): normalised_name(s, column)
            for s in specs
        }
        by_source = {k: v for k, v in by_source.items() if v}
        if not by_source:
            return None
        names = set(by_source.values())
    if len(names) == 1:
        name = next(iter(names))
        if name == "chrom":
            return [_rank_expr(df, "chrom"), pl.col("start")]
        return [pl.col(name) if name in df.columns else pl.lit(None).alias(name)]
    # Sources read it from different columns: compare the cells as text.
    expr: pl.Expr = pl.lit(None, dtype=pl.Utf8)
    for source, name in by_source.items():
        if name in df.columns:
            expr = (
                pl.when(pl.col("source") == source).then(pl.col(name).cast(pl.Utf8)).otherwise(expr)
            )
    return [expr.alias("_sort")]


def sort_calls(df: pl.DataFrame, keys: list[pl.Expr], descending: bool) -> pl.DataFrame:
    """``df`` ordered by ``keys`` (the first one descending when asked), nulls last, stable."""
    return df.sort(
        keys,
        descending=[descending] + [False] * (len(keys) - 1),
        nulls_last=True,
        maintain_order=True,
    )


def search_mask(df: pl.DataFrame, specs: list[dict[str, Any]], needle: str) -> pl.Expr:
    """Rows whose label or ``search_columns`` (those of their own source) contain ``needle``.

    Case-insensitive substring match.
    """
    text = needle.strip().lower()
    if not text:
        return pl.lit(True)
    result: pl.Expr = pl.lit(False)
    for spec in specs:
        cols = ["label"]
        for c in spec.get("search_columns") or []:
            name = normalised_name(spec, c)
            cols.append(name if name and name.startswith("x:") else f"s:{c}")
        hits = [
            pl.col(c)
            .cast(pl.Utf8)
            .str.to_lowercase()
            .str.contains(text, literal=True)
            .fill_null(False)
            for c in dict.fromkeys(cols)
            if c in df.columns
        ]
        if not hits:
            continue
        source = str(spec.get("name") or spec.get("data_collection_tag") or "")
        result = pl.when(pl.col("source") == source).then(pl.any_horizontal(hits)).otherwise(result)
    return result


TEXT_FILTER_OPS = ("contains", "notContains", "equals", "notEqual", "startsWith", "endsWith")
NUMBER_FILTER_OPS = (
    "equals",
    "notEqual",
    "greaterThan",
    "greaterThanOrEqual",
    "lessThan",
    "lessThanOrEqual",
    "inRange",
)


def column_filter_mask(
    df: pl.DataFrame,
    specs: list[dict[str, Any]],
    filters: list[dict[str, Any]],
    merged: bool = False,
) -> pl.Expr:
    """Rows passing every column filter of the region picker (AG Grid's own ops).

    Each filter is ``{"column", "kind": "text" | "number", "op", "value",
    "value_to"}``; ``column`` takes the names a sort takes. Text compares the
    cell as lower-case text; number casts it to float (a cell that is not a
    number fails). ``chrom`` compares the name, not the karyotype rank.
    """
    result: pl.Expr = pl.lit(True)
    for f in filters:
        column = f["column"]
        if column == "chrom" and "chrom" in df.columns:
            cell: pl.Expr = pl.col("chrom")
        else:
            keys = sort_keys(df, specs, column, merged=merged)
            if not keys:
                continue
            cell = keys[0]
        op, value = f["op"], f["value"]
        if f["kind"] == "text":
            text = cell.cast(pl.Utf8).str.to_lowercase()
            needle = str(value).lower()
            expr = {
                "contains": lambda: text.str.contains(needle, literal=True),
                "notContains": lambda: ~text.str.contains(needle, literal=True),
                "equals": lambda: text == needle,
                "notEqual": lambda: text != needle,
                "startsWith": lambda: text.str.starts_with(needle),
                "endsWith": lambda: text.str.ends_with(needle),
            }[op]()
        else:
            num = cell.cast(pl.Float64, strict=False)
            v = float(value)
            expr = {
                "equals": lambda: num == v,
                "notEqual": lambda: num != v,
                "greaterThan": lambda: num > v,
                "greaterThanOrEqual": lambda: num >= v,
                "lessThan": lambda: num < v,
                "lessThanOrEqual": lambda: num <= v,
                "inRange": lambda: (num >= v) & (num <= float(f["value_to"])),
            }[op]()
        result = result & expr.fill_null(False)
    return result


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_regions(df: pl.DataFrame, descending: bool = True) -> pl.DataFrame:
    """Overlapping regions of one source (across samples and runs) joined into one row each.

    Sources are never merged together: a copy-number segment spans megabases and
    would swallow every variant under it, so each omics layer keeps its own stops.
    Within a source, regions are ordered by karyotype and start; a row opens a new
    region when its start is past the largest end so far on its chromosome. The
    merged rows come back in genome order (karyotype, start), sources interleaved. A merged row spans the
    union (``chrom`` of the best row), takes the best ``score`` (largest when
    ``descending`` else smallest, null without scores) and the other cells (label,
    columns, mate, source) of the row holding it. ``n_rows``, ``n_samples``,
    ``samples`` (at most 10), and ``sources`` describe what was joined; ``sample``
    and ``run`` stay set only when every row agrees. Rows without coordinates are
    left out.
    """
    base = _ensure(df).filter(
        pl.col("chrom").is_not_null() & pl.col("start").is_not_null() & pl.col("end").is_not_null()
    )
    base = base.with_columns(_c=canonical_expr(pl.col("chrom")))
    base = base.with_columns(_r=_rank_expr(base, "_c", canonical=True))
    base = base.sort(["source", "_r", "start"], nulls_last=True, maintain_order=True)
    previous_end = pl.col("end").cum_max().shift(1).over(["source", "_c"])
    new_region = previous_end.is_null() | (pl.col("start") > previous_end)
    base = base.with_columns(_g=new_region.cast(pl.Int64).cum_sum())

    # The row index is the tie-break: `maintain_order` alone does not keep equal
    # (or all-null) scores in row order on every Polars version, so the "first
    # label" of a region without scores flipped to the last one on 1.33.
    base = base.with_row_index("_i")
    best = (
        base.sort(["score", "_i"], descending=[descending, False], nulls_last=True)
        .group_by("_g", maintain_order=True)
        .first()
    )
    joined = base.group_by("_g", maintain_order=True).agg(
        pl.col("start").min().alias("_lo"),
        pl.col("end").max().alias("_hi"),
        pl.len().alias("n_rows"),
        pl.col("sample").drop_nulls().unique(maintain_order=True).alias("_samples"),
        pl.col("run").drop_nulls().unique(maintain_order=True).alias("_runs"),
        pl.col("source").unique(maintain_order=True).alias("sources"),
    )
    out = best.join(joined, on="_g", how="left")
    one_sample = pl.col("_samples").list.len() == 1
    one_run = pl.col("_runs").list.len() == 1
    out = out.with_columns(
        start=pl.col("_lo"),
        end=pl.col("_hi"),
        n_samples=pl.col("_samples").list.len().cast(pl.Int64),
        samples=pl.col("_samples").list.head(MAX_MERGED_SAMPLES),
        sample=pl.when(one_sample).then(pl.col("_samples").list.first()).otherwise(None),
        run=pl.when(one_run).then(pl.col("_runs").list.first()).otherwise(None),
    )
    out = out.sort(["_r", "start", "_g"], nulls_last=True)
    return _drop_internal(out, ["_c", "_r", "_g", "_i", "_lo", "_hi", "_samples", "_runs"])


# ---------------------------------------------------------------------------
# Next / previous region
# ---------------------------------------------------------------------------


def _pick(df: pl.DataFrame, direction: int) -> dict[str, Any]:
    """The row with the smallest start (direction 1) or the largest end (-1); ties: first."""
    idx = df["start"].arg_min() if direction > 0 else df["end"].arg_max()
    return df.row(idx or 0, named=True)


def near_region(
    df: pl.DataFrame, chrom: str, pos: int | float, direction: int, chrom_order: list[str]
) -> dict[str, Any] | None:
    """The region next to ``pos`` on ``chrom``, else the first one on the next chromosome.

    Direction 1: the region with the smallest start past ``pos``; -1: the one with
    the largest end before it. With none left on the chromosome, the first region
    (smallest start; for -1 the largest end) on the next (previous) chromosome of
    ``chrom_order`` that has one. Chromosomes of the data that ``chrom_order`` does
    not list are skipped, and there is no wrap-around: None at either end.
    """
    direction = 1 if direction > 0 else -1
    base = df.filter(
        pl.col("chrom").is_not_null() & pl.col("start").is_not_null() & pl.col("end").is_not_null()
    ).with_columns(_c=canonical_expr(pl.col("chrom")))
    canon = canonical_chrom(chrom)
    same = base.filter(pl.col("_c") == canon)
    cand = same.filter(pl.col("start") > pos) if direction > 0 else same.filter(pl.col("end") < pos)
    if cand.height:
        return {k: v for k, v in _pick(cand, direction).items() if k != "_c"}

    order = chrom_index(chrom_order)
    here = order.get(canon)
    if here is None:
        return None
    base = base.with_columns(
        _i=pl.col("_c").replace_strict(order, default=None, return_dtype=pl.Int64)
    )
    others = base.filter(pl.col("_i") > here if direction > 0 else pl.col("_i") < here)
    if others.height == 0:
        return None
    target = others["_i"].min() if direction > 0 else others["_i"].max()
    row = _pick(others.filter(pl.col("_i") == target), direction)
    return {k: v for k, v in row.items() if k not in ("_c", "_i")}


# ---------------------------------------------------------------------------
# Density
# ---------------------------------------------------------------------------


def bin_size_for(regions: list[dict[str, Any]], bins: int) -> int:
    """One bin size (bp) giving about ``bins`` bins over every region, at least 1."""
    total = sum(max(int(r.get("length") or 0), 0) for r in regions)
    return max(math.ceil(total / max(int(bins), 1)), 1)


def density(
    df: pl.DataFrame,
    regions: list[dict[str, Any]],
    bin_size: int,
    group: str = "source",
    source_order: list[str] | None = None,
    max_tracks: int = MAX_DENSITY_TRACKS,
) -> dict[str, Any]:
    """How many regions start in each bin of each region, one track per source / sample / run.

    ``regions`` are ``{refName, length}`` in display order. A track is a source,
    or (``group`` ``sample`` / ``run``) a source's sample / run; a source without
    that column stays one track, and a source with no row at all still gets an
    empty one. Past ``max_tracks`` the busiest are kept, in source order then
    first-seen order. A row on a chromosome the regions do not list is ignored; one
    past the end of its region counts in the last bin. Sample tracks carry the first
    ``run`` seen for the sample.

    Returns ``{"bin_size", "max", "tracks", "truncated"}``; a track is
    ``{"source", "label", "run", "chroms": [{"refName", "counts"}]}``.
    """
    bin_size = max(int(bin_size), 1)
    names = [str(r["refName"]) for r in regions]
    n_bins = [max(math.ceil(max(int(r.get("length") or 0), 0) / bin_size), 1) for r in regions]
    region_of: dict[str, int] = {}
    for i, name in enumerate(names):
        region_of.setdefault(canonical_chrom(name), i)
    group_col = group if group in ("sample", "run") else None

    base = _ensure(df).filter(pl.col("chrom").is_not_null() & pl.col("start").is_not_null())
    base = base.with_columns(
        _ri=canonical_expr(pl.col("chrom")).replace_strict(
            region_of, default=None, return_dtype=pl.Int64
        ),
        _k=(pl.col(group_col) if group_col else pl.lit("")).cast(pl.Utf8).fill_null(""),
        source=pl.col("source").cast(pl.Utf8).fill_null(""),
    ).filter(pl.col("_ri").is_not_null())

    meta = base.group_by(["source", "_k"], maintain_order=True).agg(
        pl.len().alias("_n"), pl.col("run").drop_nulls().first().alias("_run")
    )
    tracks: list[dict[str, Any]] = [
        {
            "source": r["source"],
            "key": r["_k"],
            "total": r["_n"],
            "run": r["_run"] if group_col == "sample" else None,
        }
        for r in meta.iter_rows(named=True)
    ]
    order = list(source_order or [])
    for s in dict.fromkeys(base["source"].to_list()):
        if s not in order:
            order.append(s)
    seen = {t["source"] for t in tracks}
    tracks += [{"source": s, "key": "", "total": 0, "run": None} for s in order if s not in seen]

    busiest = sorted(range(len(tracks)), key=lambda i: -tracks[i]["total"])[:max_tracks]
    kept = [tracks[i] for i in sorted(busiest)]
    truncated = len(tracks) - len(kept)
    rank = {s: i for i, s in enumerate(order)}
    kept.sort(key=lambda t: rank.get(t["source"], len(rank)))  # stable: first-seen inside a source

    lists: dict[tuple[str, str], list[list[int]]] = {
        (t["source"], t["key"]): [[0] * n for n in n_bins] for t in kept
    }
    if kept and base.height:
        keep_keys = pl.DataFrame(
            {"source": [t["source"] for t in kept], "_k": [t["key"] for t in kept]}
        )
        counted = (
            base.join(keep_keys, on=["source", "_k"], how="semi")
            .with_columns(
                _nb=pl.col("_ri").replace_strict(dict(enumerate(n_bins)), return_dtype=pl.Int64)
            )
            .with_columns(
                _bin=pl.min_horizontal(
                    (pl.col("start") // bin_size).clip(lower_bound=0), pl.col("_nb") - 1
                )
            )
            .group_by(["source", "_k", "_ri", "_bin"])
            .len()
        )
        for r in counted.iter_rows(named=True):
            lists[(r["source"], r["_k"])][r["_ri"]][r["_bin"]] += r["len"]

    out_tracks = []
    biggest = 0
    for t in kept:
        per_region = lists[(t["source"], t["key"])]
        biggest = max([biggest, *(max(c) for c in per_region if c)])
        out_tracks.append(
            {
                "source": t["source"],
                "label": t["key"] or t["source"],
                "run": t["run"],
                "chroms": [{"refName": n, "counts": c} for n, c in zip(names, per_region)],
            }
        )
    return {"bin_size": bin_size, "max": biggest, "tracks": out_tracks, "truncated": truncated}
