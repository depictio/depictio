"""taxpasta profiles widened into one column per NCBI rank, for sunburst and sankey.

The long ``taxpasta_profiles`` frame identifies a taxon by id, name and its own rank -
enough for a stacked bar, not enough for a hierarchy: a sunburst needs the whole
lineage of a taxon side by side in one row, and a Pavian-style sankey needs the same
thing to build its flows. taxpasta itself only emits a lineage when the pipeline
passes ``--add-lineage``, which nf-core/taxprofiler does not.

The ancestry is instead read back out of the kraken-style reports the pipeline writes
anyway. Those reports are *indented*: each line's name is prefixed with two spaces per
level, so walking the file with a stack recovers every taxon's parents. Two families
carry the indentation:

    kraken2      6 fields   pct, clade_reads, taxon_reads, rank_code, taxid, name
    krakenuniq   9 fields   %, reads, taxReads, kmers, dup, cov, taxID, rank, taxName

(centrifuge's report is flat, so it contributes nothing here and is simply skipped.)
One lineage table is built from every report in the run and joined onto the profiles
by taxonomy id, which is why a profiler whose database uses different identifiers
(kmcp in the 2.0.1 megatest) resolves to ``unresolved`` rather than to a lineage.

Three fills, deliberately distinct so the rings do not lie:

* reads the profiler could not classify at all (taxonomy id 0) get ``unclassified``
  at every rank, so the kraken2 unclassified share is one visible flow off the root
  rather than a silent absence;
* a taxon no report named gets ``unresolved`` at every rank;
* a rank missing inside an otherwise known lineage (no phylum between domain and
  class, say) carries its nearest known ancestor forward, which keeps the arc
  attached to the right branch instead of pooling it with every other gap.

``root`` is a constant column on purpose: it is the single node a Pavian sankey fans
out from, and it is not offered as a filter anywhere.

Output (one row per profiler x database x sample x taxon, the same grain as
``taxpasta_profiles``):
    profiler, database, profiler_db, sample, platform, taxonomy_id, name, rank,
    root, superkingdom, phylum, class, order, family, genus, species,
    count, rel_abundance
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="profiles", dc_ref="taxpasta_profiles"),
    RecipeSource(
        ref="reports",
        # `**/`: the profiler and database directories sit at whatever depth the
        # pipeline publishes them; a glob pinned to one depth would match nothing
        # and silently stamp `unresolved` on every rank.
        glob_pattern="**/*.report.txt",
        format="csv",
        # One column per line: \x1f never occurs in a kraken-style report, so the
        # reader cannot split the row and the recipe owns the tab handling. The
        # indentation is the payload here, so nothing is stripped on the way in.
        read_kwargs={
            "has_header": False,
            "separator": "\x1f",
            "quote_char": None,
            "new_columns": ["line"],
            "truncate_ragged_lines": True,
            "infer_schema_length": 0,
        },
        optional=True,
    ),
]

RANKS: tuple[str, ...] = (
    "superkingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
)

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "profiler": pl.Utf8,
    "database": pl.Utf8,
    "profiler_db": pl.Utf8,
    "sample": pl.Utf8,
    "platform": pl.Utf8,
    "taxonomy_id": pl.Utf8,
    "name": pl.Utf8,
    "rank": pl.Utf8,
    "root": pl.Utf8,
    **{rank: pl.Utf8 for rank in RANKS},
    "count": pl.Float64,
    "rel_abundance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# kraken2 rank codes. A trailing digit marks an intermediate level (`D1` = a clade
# between domain and phylum); it collapses onto its parent rank, and levels outside
# the seven canonical ranks simply do not open a new ring.
_RANK_CODES = {
    "U": "unclassified",
    "R": "root",
    "D": "superkingdom",
    "K": "kingdom",
    "P": "phylum",
    "C": "class",
    "O": "order",
    "F": "family",
    "G": "genus",
    "S": "species",
}

ROOT = "root"
UNCLASSIFIED = "unclassified"
UNRESOLVED = "unresolved"


def _report_lineages(reports: pl.DataFrame | None) -> dict[str, dict[str, str]]:
    """taxonomy id -> {rank: name} for every taxon the indented reports place."""
    lineages: dict[str, dict[str, str]] = {}
    if reports is None or reports.is_empty() or "line" not in reports.columns:
        return lineages

    # The glob concatenates every report end to end. No file boundary is needed:
    # every kraken-style report opens at depth 0 (the unclassified / root lines),
    # and truncating the stack to the current depth empties it there anyway.
    stack: list[tuple[str, str]] = []
    for raw in reports["line"].to_list():
        if raw is None:
            continue
        line = raw.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) == 6:
            taxid, rank_field, name_field, kraken2 = fields[4], fields[3], fields[5], True
        elif len(fields) == 9:
            taxid, rank_field, name_field, kraken2 = fields[6], fields[7], fields[8], False
        else:
            continue
        taxid = taxid.strip()
        if not taxid.isdigit():
            continue

        depth = (len(name_field) - len(name_field.lstrip(" "))) // 2
        name = name_field.strip()
        if kraken2:
            rank = _RANK_CODES.get(rank_field.strip().rstrip("0123456789"), "unknown")
        else:
            rank = rank_field.strip().lower()
            if rank == "no rank":
                rank = "unknown"

        while len(stack) > depth:
            stack.pop()
        stack.append((rank, name))

        if taxid in lineages:
            continue
        lineage: dict[str, str] = {}
        for ancestor_rank, ancestor_name in stack:
            if ancestor_rank in RANKS and ancestor_rank not in lineage:
                lineage[ancestor_rank] = ancestor_name
        lineages[taxid] = lineage
    return lineages


def _widen(
    taxonomy_ids: list[str],
    ranks: list[str],
    lineages: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """Fill the seven rank columns for every profile row."""
    columns: dict[str, list[str]] = {rank: [] for rank in RANKS}
    for taxid, own_rank in zip(taxonomy_ids, ranks, strict=True):
        if own_rank == UNCLASSIFIED or taxid in {"0", ""}:
            for rank in RANKS:
                columns[rank].append(UNCLASSIFIED)
            continue
        lineage = lineages.get(taxid)
        if not lineage:
            for rank in RANKS:
                columns[rank].append(UNRESOLVED)
            continue
        carried = UNRESOLVED
        for rank in RANKS:
            carried = lineage.get(rank, carried)
            columns[rank].append(carried)
    return columns


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join each profile row to the lineage its taxonomy id sits in."""
    profiles = sources["profiles"]
    if profiles is None or profiles.is_empty():
        raise ValueError("taxpasta lineage: the taxpasta profiles collection is empty")
    required = {"taxonomy_id", "rank", "rel_abundance"}
    missing = sorted(required - set(profiles.columns))
    if missing:
        raise ValueError(f"taxpasta lineage: the profiles are missing column(s) {missing}")

    lineages = _report_lineages(sources.get("reports"))
    if not lineages:
        raise ValueError(
            "taxpasta lineage: no kraken2 / krakenuniq report yielded a lineage, so every "
            "rank would be 'unresolved'; a run without those reports should not declare this "
            "(optional) collection"
        )
    taxonomy_ids = [str(v) if v is not None else "" for v in profiles["taxonomy_id"].to_list()]
    own_ranks = [str(v) if v is not None else "" for v in profiles["rank"].to_list()]
    widened = _widen(taxonomy_ids, own_ranks, lineages)

    return (
        profiles.with_columns(
            pl.lit(ROOT, dtype=pl.Utf8).alias("root"),
            *[pl.Series(rank, values, dtype=pl.Utf8) for rank, values in widened.items()],
        )
        .select(*EXPECTED_SCHEMA)
        .sort(["profiler", "database", "sample", "rel_abundance"], descending=[False] * 3 + [True])
    )
