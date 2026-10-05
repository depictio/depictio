"""Substitution matrix and evolutionary distances of each one-to-one genome alignment.

``last-split`` writes ``<target>___<query>.o2o.matrix.txt`` next to the
alignment: a header of ``# key: value`` lines (number of alignment blocks,
columns analysed, and five distance estimates computed on the A/C/G/T columns:
the raw p-distance and the JC69, F81, K80 and T92 model corrections) followed by
a 6 x 6 count table, target letters in rows and query letters in columns, with
``N`` and the gap ``-`` as the last two letters.

The recipe keeps the header numbers and summarises the table into what a reader
compares genomes by: identical and substituted A/C/G/T columns, transitions
against transversions (their ratio falls as saturation sets in with divergence),
gap columns on either side, and the substitution spectrum, the share of each of
the 12 directed substitutions among all substitutions (``A_to_G_pct`` is a
target A aligned to a query G). The spectrum columns are what the heatmap binds.

The file carries no pair id, so it is read off the file name.

Output columns:
    pair, target, query, blocks, columns_analyzed, p_distance, jc69_distance,
    f81_distance, k80_distance, t92_distance, identical_columns,
    substituted_columns, transitions, transversions, ts_tv_ratio,
    target_gap_columns, query_gap_columns, <X>_to_<Y>_pct (12 columns)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.genome_pairs import pair_from_path, split_pair

_SOURCE_PATH = "_source_path"
_SUFFIX = ".o2o.matrix.txt"
_BASES = ("A", "C", "G", "T")
_TRANSITIONS = {("A", "G"), ("G", "A"), ("C", "T"), ("T", "C")}
_SPECTRUM = [f"{a}_to_{b}_pct" for a in _BASES for b in _BASES if a != b]
_DISTANCES = {
    "P_acgt": "p_distance",
    "JC69_acgt": "jc69_distance",
    "F81_acgt": "f81_distance",
    "K80_acgt": "k80_distance",
    "T92_acgt": "t92_distance",
}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="matrix",
        glob_pattern="alignment/*.o2o.matrix.txt",
        format="CSV",
        source_path=_SOURCE_PATH,
        # One line per row: the unit separator never occurs, so the whole line
        # lands in the single `raw` column, tabs included.
        read_kwargs={
            "separator": "\x1f",
            "has_header": False,
            "new_columns": ["raw"],
            "quote_char": None,
            "infer_schema_length": 0,
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "pair": pl.Utf8,
    "target": pl.Utf8,
    "query": pl.Utf8,
    "blocks": pl.Int64,
    "columns_analyzed": pl.Int64,
    "p_distance": pl.Float64,
    "jc69_distance": pl.Float64,
    "f81_distance": pl.Float64,
    "k80_distance": pl.Float64,
    "t92_distance": pl.Float64,
    "identical_columns": pl.Int64,
    "substituted_columns": pl.Int64,
    "transitions": pl.Int64,
    "transversions": pl.Int64,
    "ts_tv_ratio": pl.Float64,
    "target_gap_columns": pl.Int64,
    "query_gap_columns": pl.Int64,
    **{col: pl.Float64 for col in _SPECTRUM},
}


def _to_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _sig3(value: float | None) -> float | None:
    """Three significant digits: the distances span 1e-4 to 1, a fixed decimal count cannot."""
    return float(f"{value:.3g}") if value is not None else None


def _to_int(value: str | None) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None


def _parse(lines: list[str]) -> dict[str, object]:
    """One matrix file (its lines, in order) to one output row, minus the keys."""
    header: dict[str, str] = {}
    letters: list[str] = []
    counts: dict[tuple[str, str], int] = {}
    for line in lines:
        if line.startswith("#"):
            key, _, value = line.lstrip("#").partition(":")
            header[key.strip()] = value.strip()
            continue
        fields = line.split("\t")
        if not letters:
            letters = [f.strip() for f in fields[1:]]
            continue
        row = fields[0].strip()
        for col, value in zip(letters, fields[1:], strict=False):
            counts[(row, col)] = _to_int(value) or 0

    identical = sum(counts.get((b, b), 0) for b in _BASES)
    pairs = [(a, b) for a in _BASES for b in _BASES if a != b]
    substituted = sum(counts.get(p, 0) for p in pairs)
    transitions = sum(counts.get(p, 0) for p in _TRANSITIONS)
    transversions = substituted - transitions
    out: dict[str, object] = {
        "blocks": _to_int(header.get("blocks")),
        "columns_analyzed": _to_int(header.get("columns_analyzed")),
        **{dst: _sig3(_to_float(header.get(src))) for src, dst in _DISTANCES.items()},
        "identical_columns": identical,
        "substituted_columns": substituted,
        "transitions": transitions,
        "transversions": transversions,
        "ts_tv_ratio": round(transitions / transversions, 3) if transversions else None,
        # A target letter against a query gap: the query lacks the base there.
        "query_gap_columns": sum(counts.get((b, "-"), 0) for b in _BASES),
        # A query letter against a target gap: the query carries an insertion.
        "target_gap_columns": sum(counts.get(("-", b), 0) for b in _BASES),
    }
    for (a, b), col in zip(pairs, _SPECTRUM, strict=True):
        out[col] = round(counts.get((a, b), 0) / substituted * 100.0, 3) if substituted else None
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["matrix"].filter(pl.col("raw").is_not_null())
    rows: list[dict[str, object]] = []
    for (path,), group in df.group_by(_SOURCE_PATH, maintain_order=True):
        rows.append({_SOURCE_PATH: path, **_parse(group["raw"].to_list())})
    if not rows:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    body_schema = {k: v for k, v in EXPECTED_SCHEMA.items() if k not in ("pair", "target", "query")}
    parsed = pl.DataFrame(rows, schema={_SOURCE_PATH: pl.Utf8, **body_schema})
    parsed = parsed.with_columns(*split_pair(pair_from_path(_SOURCE_PATH, _SUFFIX)))
    return parsed.select(list(EXPECTED_SCHEMA)).unique("pair", keep="first").sort("query")
