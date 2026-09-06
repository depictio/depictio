"""taxpasta standardised profiles -> one long cross-profiler abundance table.

taxpasta (``taxpasta standardise`` / ``taxpasta merge``) writes one WIDE table per
profiler x database: a ``taxonomy_id`` column plus one count column per sample, named
after the profiler report file taxpasta consumed. Nothing inside the file says which
profiler or database produced it, and the recipe framework concatenates a glob source
without recording the filename, so the provenance is reconstructed from the column
name itself:

* the **sample** is the longest sample id from the samplesheet that prefixes the name;
* the **database** is the longest ``db_name`` from the database sheet found in it;
* the **profiler** is read from the report suffix first (``.kraken2.report``,
  ``.bracken``, ...) and only then from the database sheet's ``tool`` column. Suffix
  first is what keeps ``<sample>_bracken-db.bracken.kraken2.report`` attributed to
  kraken2 rather than to bracken, whose database it ran against.

Both sheets are optional: without them the suffix table alone drives the profiler and
the remaining tokens are stripped heuristically.

taxpasta only emits ``name`` / ``rank`` columns when the pipeline passed
``--add-name`` / ``--add-rank``; when it did not, an optional ``names`` source (a
taxonomy_id -> name/rank lookup harvested from the profiler reports) fills them in.
Unresolved ids keep a ``taxid <id>`` placeholder so a tile never renders blank labels.

Output (one row per profiler x database x sample x taxon, zero counts dropped):
    profiler, database, profiler_db, sample, platform,
    taxonomy_id, name, rank, count, rel_abundance
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profiles", glob_pattern="taxpasta/*.tsv", format="tsv"),
    RecipeSource(ref="databases", dc_ref="database_sheet", optional=True),
    RecipeSource(ref="samples", dc_ref="samplesheet", optional=True),
    RecipeSource(ref="names", dc_ref="taxon_names", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "profiler": pl.Utf8,
    "database": pl.Utf8,
    "profiler_db": pl.Utf8,
    "sample": pl.Utf8,
    "platform": pl.Utf8,
    "taxonomy_id": pl.Utf8,
    "name": pl.Utf8,
    "rank": pl.Utf8,
    "count": pl.Float64,
    "rel_abundance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# Report-file suffix -> profiler, longest first so `.kraken2.report` wins over
# `.report`. This is taxpasta's own input naming, not a pipeline layout.
_PROFILER_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    (".kraken2.kraken2.report", "kraken2"),
    (".krakenuniq.report", "krakenuniq"),
    (".kraken2.report", "kraken2"),
    (".metaphlan_profile", "metaphlan"),
    (".ganon_report", "ganon"),
    (".kaijutable", "kaiju"),
    (".centrifuge", "centrifuge"),
    (".metaphlan", "metaphlan"),
    (".abundances", "metacache"),
    (".sylphmpa", "sylph"),
    (".diamond", "diamond"),
    (".bracken", "bracken"),
    (".motus", "motus"),
    (".kmcp", "kmcp"),
)

# Columns taxpasta may add next to the counts (``--add-name`` and friends).
_ANNOTATION_COLUMNS = ("name", "rank", "lineage", "id_lineage", "rank_lineage")

_UNKNOWN = "unknown"
# taxpasta reads MEGAN6/MALT through the rma6 file, which is named after the raw
# reads, so those column names carry neither a profiler suffix nor a database
# token. When the database sheet declares a `malt` tool, the leftovers are its.
_RMA_PROFILER = "megan6"
_RMA_TOOL = "malt"


def _sample_ids(samples: pl.DataFrame | None) -> list[str]:
    """Sample identifiers from the samplesheet, longest first."""
    if samples is None or samples.is_empty():
        return []
    col = next((c for c in ("sample", "sampleID", "sample_id", "id") if c in samples.columns), None)
    if col is None:
        return []
    ids = [str(v) for v in samples[col].drop_nulls().unique().to_list() if str(v)]
    return sorted(ids, key=len, reverse=True)


def _platforms(samples: pl.DataFrame | None) -> pl.DataFrame | None:
    """sample -> instrument_platform, when the samplesheet carries one."""
    if samples is None or samples.is_empty():
        return None
    id_col = next(
        (c for c in ("sample", "sampleID", "sample_id", "id") if c in samples.columns), None
    )
    plat_col = next(
        (c for c in ("instrument_platform", "platform") if c in samples.columns),
        None,
    )
    if id_col is None or plat_col is None:
        return None
    return (
        samples.select(
            pl.col(id_col).cast(pl.Utf8).alias("sample"),
            pl.col(plat_col).cast(pl.Utf8).alias("platform"),
        )
        .drop_nulls("sample")
        .unique(subset=["sample"])
    )


def _databases(databases: pl.DataFrame | None) -> tuple[list[str], dict[str, str]]:
    """(db_names longest-first, db_name -> tool) from the database sheet."""
    if databases is None or databases.is_empty():
        return [], {}
    name_col = next((c for c in ("db_name", "database", "name") if c in databases.columns), None)
    tool_col = next((c for c in ("tool", "profiler") if c in databases.columns), None)
    if name_col is None:
        return [], {}
    rows = databases.select(
        pl.col(name_col).cast(pl.Utf8).alias("db"),
        (pl.col(tool_col).cast(pl.Utf8) if tool_col else pl.lit(None, dtype=pl.Utf8)).alias("tool"),
    ).drop_nulls("db")
    mapping = {r["db"]: (r["tool"] or _UNKNOWN) for r in rows.iter_rows(named=True)}
    return sorted(mapping, key=len, reverse=True), mapping


def _parse_stem(
    stem: str,
    sample_ids: list[str],
    db_names: list[str],
    db_tools: dict[str, str],
) -> tuple[str, str, str]:
    """Split one taxpasta count-column name into (sample, database, profiler)."""
    profiler = next((p for suffix, p in _PROFILER_BY_SUFFIX if stem.endswith(suffix)), None)
    database = next((db for db in db_names if db in stem), None)

    sample = next((s for s in sample_ids if stem.startswith(s)), None)
    if sample is None:
        # No samplesheet: cut the stem at whichever provenance token appears first.
        cut = len(stem)
        if database is not None:
            cut = min(cut, stem.find(database))
        for suffix, _ in _PROFILER_BY_SUFFIX:
            at = stem.find(suffix)
            if at != -1:
                cut = min(cut, at)
        sample = stem[:cut].rstrip("._-") or stem

    if profiler is None and database is not None:
        profiler = db_tools.get(database)
    if profiler is None and database is None and _RMA_TOOL in db_tools.values():
        # MEGAN6/MALT: the column is named after the reads, not after a report.
        profiler = _RMA_PROFILER
        database = next((db for db, tool in db_tools.items() if tool == _RMA_TOOL), None)
    if database is None and profiler is not None:
        # Some profilers (krakenuniq) name their report after the reads only. The
        # database is unambiguous whenever the sheet declares a single one for the tool.
        candidates = [db for db, tool in db_tools.items() if tool == profiler]
        if len(candidates) == 1:
            database = candidates[0]

    return sample, database or _UNKNOWN, profiler or _UNKNOWN


def _name_lookup(names: pl.DataFrame | None) -> pl.DataFrame | None:
    """taxonomy_id -> (name, rank), one row per id."""
    if names is None or names.is_empty():
        return None
    if "taxonomy_id" not in names.columns:
        return None
    have_name = "name" in names.columns
    have_rank = "rank" in names.columns
    if not have_name and not have_rank:
        return None
    return (
        names.select(
            pl.col("taxonomy_id").cast(pl.Utf8),
            (pl.col("name").cast(pl.Utf8) if have_name else pl.lit(None, dtype=pl.Utf8)).alias(
                "ref_name"
            ),
            (pl.col("rank").cast(pl.Utf8) if have_rank else pl.lit(None, dtype=pl.Utf8)).alias(
                "ref_rank"
            ),
        )
        .drop_nulls("taxonomy_id")
        .unique(subset=["taxonomy_id"], keep="first")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt every taxpasta table into one long profiler x sample x taxon frame."""
    wide = sources["profiles"]
    if "taxonomy_id" not in wide.columns:
        raise ValueError("taxpasta profiles: no `taxonomy_id` column in the merged tables")

    index_cols = ["taxonomy_id"] + [c for c in _ANNOTATION_COLUMNS if c in wide.columns]
    count_cols = [c for c in wide.columns if c not in index_cols]
    if not count_cols:
        raise ValueError("taxpasta profiles: the merged tables carry no per-sample count columns")

    long = (
        wide.with_columns(pl.col(c).cast(pl.Float64, strict=False) for c in count_cols)
        .unpivot(
            index=index_cols,
            on=count_cols,
            variable_name="column_stem",
            value_name="count",
        )
        .drop_nulls("count")
        .filter(pl.col("count") > 0)
        .with_columns(pl.col("taxonomy_id").cast(pl.Utf8))
    )
    if long.is_empty():
        raise ValueError("taxpasta profiles: every merged table was empty or all-zero")

    sample_ids = _sample_ids(sources.get("samples"))
    db_names, db_tools = _databases(sources.get("databases"))
    parsed = {
        stem: _parse_stem(stem, sample_ids, db_names, db_tools)
        for stem in long["column_stem"].unique().to_list()
    }
    provenance = pl.DataFrame(
        {
            "column_stem": list(parsed),
            "sample": [v[0] for v in parsed.values()],
            "database": [v[1] for v in parsed.values()],
            "profiler": [v[2] for v in parsed.values()],
        },
        schema={
            "column_stem": pl.Utf8,
            "sample": pl.Utf8,
            "database": pl.Utf8,
            "profiler": pl.Utf8,
        },
    )

    long = long.join(provenance, on="column_stem", how="left").drop("column_stem")

    platforms = _platforms(sources.get("samples"))
    if platforms is not None:
        long = long.join(platforms, on="sample", how="left")
    else:
        long = long.with_columns(pl.lit(_UNKNOWN).alias("platform"))

    lookup = _name_lookup(sources.get("names"))
    if lookup is not None:
        long = long.join(lookup, on="taxonomy_id", how="left")
    else:
        long = long.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("ref_name"),
            pl.lit(None, dtype=pl.Utf8).alias("ref_rank"),
        )

    own_name = pl.col("name").cast(pl.Utf8) if "name" in index_cols else pl.lit(None, dtype=pl.Utf8)
    own_rank = pl.col("rank").cast(pl.Utf8) if "rank" in index_cols else pl.lit(None, dtype=pl.Utf8)

    return (
        long.with_columns(
            own_name.fill_null(pl.col("ref_name"))
            .fill_null(pl.format("taxid {}", pl.col("taxonomy_id")))
            .alias("name"),
            own_rank.fill_null(pl.col("ref_rank")).fill_null(pl.lit(_UNKNOWN)).alias("rank"),
            pl.col("platform").fill_null(pl.lit(_UNKNOWN)),
            pl.format("{} / {}", pl.col("profiler"), pl.col("database")).alias("profiler_db"),
        )
        .with_columns(
            (pl.col("count") / pl.col("count").sum().over(["profiler", "database", "sample"]))
            .cast(pl.Float64)
            .alias("rel_abundance")
        )
        .select(
            "profiler",
            "database",
            "profiler_db",
            "sample",
            "platform",
            "taxonomy_id",
            "name",
            "rank",
            "count",
            "rel_abundance",
        )
        .sort(["profiler", "database", "sample", "count"], descending=[False, False, False, True])
    )
