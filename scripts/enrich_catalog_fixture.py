"""Grow a catalog fixture to several samples, so its preview shows what the component does.

A catalog fixture is a small, real sample of an output's table. Taken from one run, it
often holds one sample: a stacked bar per sample draws one bar, a PCA one point, a
per-sample profile one line, and the preview no longer shows what the figure is for.
This copies the real sample's rows under new sample names, with seeded noise, the way
the catalog's other enriched fixtures were made ("copies with seeded noise").

Each new sample gets one multiplicative shift per numeric column (so samples really
differ: a PCA separates them, a composition changes) and a smaller per-row noise on
top. Integer columns stay integers, values keep the sign and the bounds of the
original column (a fraction stays in [0, 1], a percentage in [0, 100]), and
``--sum-to`` re-normalises a composition within each sample.

Usage:
    python scripts/enrich_catalog_fixture.py depictio/catalog/cellranger/cluster_summary.tsv \\
        --sample-col sample --samples 6 [--keep n_cells_total] [--sum-to pct_cells=100] \\
        [--sum-by rank] [--names S1,S2,...] [--shift 0.25] [--noise 0.08] [--seed 0] [--dry-run]

Then say so in the output's YAML, above ``fixture:``:
    # The fixture is enriched synthetically from N real rows (copies with seeded noise), so the preview shows several samples.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import polars as pl

NUMERIC = (pl.Float32, pl.Float64, pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64)


def next_names(real: list[str], total: int) -> list[str]:
    """Names for the new samples, continuing the real ones' numbering where they have one."""
    taken = set(real)
    out: list[str] = []
    base = real[-1]
    m = re.search(r"(\d+)(?!.*\d)", base)
    k = int(m.group(1)) if m else 1
    while len(real) + len(out) < total:
        k += 1
        if m:
            width = len(m.group(1))
            name = base[: m.start(1)] + str(k).zfill(width) + base[m.end(1) :]
        else:
            name = f"{base}_{k}"
        if name not in taken:
            taken.add(name)
            out.append(name)
    return out


def read(path: Path) -> pl.DataFrame:
    sep = "," if path.suffix == ".csv" else "\t"
    return pl.read_csv(path, separator=sep, infer_schema_length=10000)


def write(df: pl.DataFrame, path: Path) -> None:
    sep = "," if path.suffix == ".csv" else "\t"
    df.write_csv(path, separator=sep)


def bounds(values: np.ndarray, name: str) -> tuple[float | None, float | None]:
    """Bounds a jittered value must respect: its sign, and [0, 1] / [0, 100] when it looks like one."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, None
    lo = 0.0 if finite.min() >= 0 else None
    hi = None
    if lo == 0.0 and finite.max() <= 1.0 and re.search(r"frac|ratio|rate|prop|share|fraction|^p_|pval|padj|qval", name, re.I):
        hi = 1.0
    elif lo == 0.0 and finite.max() <= 100.0 and re.search(r"pct|percent|%", name, re.I):
        hi = 100.0
    return lo, hi


def enrich(
    df: pl.DataFrame,
    sample_col: str,
    total: int,
    *,
    names: list[str] | None,
    keep: set[str],
    shift: float,
    noise: float,
    seed: int,
    sum_to: dict[str, float],
    sum_by: list[str] | None = None,
) -> pl.DataFrame:
    real = [str(s) for s in df[sample_col].unique(maintain_order=True).to_list()]
    if len(real) >= total:
        return df
    new = names[: total - len(real)] if names else next_names(real, total)
    rng = np.random.default_rng(seed)
    numeric = [c for c, t in df.schema.items() if t in NUMERIC and c != sample_col and c not in keep]
    frames = [df]
    for i, name in enumerate(new):
        source = df.filter(pl.col(sample_col).cast(pl.Utf8) == real[i % len(real)])
        cols = {}
        for c in numeric:
            v = source[c].cast(pl.Float64).to_numpy().copy()
            factor = np.exp(rng.normal(0.0, shift)) * np.exp(rng.normal(0.0, noise, size=v.size))
            out = v * factor
            lo, hi = bounds(df[c].cast(pl.Float64).to_numpy(), c)
            if lo is not None or hi is not None:
                out = np.clip(out, lo, hi)
            if df.schema[c] not in (pl.Float32, pl.Float64):
                out = np.rint(out)
            cols[c] = pl.Series(c, out).cast(df.schema[c], strict=False)
        copy = source.with_columns(
            pl.lit(name).cast(df.schema[sample_col], strict=False).alias(sample_col), *cols.values()
        )
        frames.append(copy)
    out = pl.concat(frames, how="vertical_relaxed")
    groups = [sample_col, *(sum_by or [])]
    for col, target in sum_to.items():
        total_per = pl.col(col).sum().over(groups)
        out = out.with_columns((pl.col(col) / total_per * target).round(4).alias(col))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fixture", type=Path)
    ap.add_argument("--sample-col", required=True)
    ap.add_argument("--samples", type=int, default=6, help="Total samples wanted (real ones included)")
    ap.add_argument("--names", default="", help="Comma-separated names for the new samples")
    ap.add_argument("--keep", default="", help="Comma-separated numeric columns copied unchanged (positions, ids)")
    ap.add_argument("--shift", type=float, default=0.25, help="Per-sample log-normal shift (sd)")
    ap.add_argument("--noise", type=float, default=0.08, help="Per-row log-normal noise (sd)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sum-to", action="append", default=[], help="COL=TOTAL, re-normalised per sample")
    ap.add_argument("--sum-by", default="", help="Extra comma-separated columns the --sum-to groups by (e.g. rank)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    df = read(a.fixture)
    if a.sample_col not in df.columns:
        print(f"{a.fixture}: no column {a.sample_col!r}", file=sys.stderr)
        return 2
    sum_to = {k: float(v) for k, v in (s.split("=", 1) for s in a.sum_to)}
    out = enrich(
        df,
        a.sample_col,
        a.samples,
        names=[n for n in a.names.split(",") if n] or None,
        keep={k for k in a.keep.split(",") if k},
        shift=a.shift,
        noise=a.noise,
        seed=a.seed,
        sum_to=sum_to,
        sum_by=[c for c in a.sum_by.split(",") if c],
    )
    real_rows = df.height
    print(f"{a.fixture}: {df[a.sample_col].n_unique()} -> {out[a.sample_col].n_unique()} samples, {real_rows} real rows -> {out.height}")
    if not a.dry_run:
        write(out, a.fixture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
