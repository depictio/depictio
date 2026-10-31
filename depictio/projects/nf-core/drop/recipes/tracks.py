"""Genome-browser track manifest: the alignments and genotypes the sample sheet points at.

nf-core/drop publishes tables, not track files: its outputs are R objects and
result tables, with no bigWig and no alignment of its own. What a genome browser
can show beside the outlier calls is the *input* of the run, the RNA alignment of
each sample (``RNA_BAM_FILE``, with its index) and, for samples with a DNA genotype,
the VCF the mono-allelic analysis read (``DNA_VCF_FILE``). The manifest is spelled
out from the sample sheet, one row per sample and file; samples that arrive as
external counts have no alignment and so no row.

A path of the sheet is read in one of three ways:
- ``https://`` or ``s3://``: read in place as written;
- a path under DATA_ROOT, relative or found there by its file name: uploaded at
  ingestion (or read in place under ``TRACKS_URI`` when it is set);
- any other path (an absolute path of the pipeline's machine): kept as written.

Row order is what the browser opens on (``initial_tracks`` shows the first rows): the
alignment of the sample holding the strongest call (the first gene the browser steps to,
the top ``significance`` of ``outlier_genes``) so ``show_junctions`` draws the splice arcs
over the reads of that call, then that sample's genotypes, then the alignment of the first
sample of each other group, then the remaining genotypes and alignments, the first sample
of each group before the second. A VCF shared by several samples is listed once per
sample so each sample's picker finds it.

The sample's group (``drop_group``) is a column of the manifest under its own name and
the manifest has no colour column: the tile colours its tracks by ``drop_group``
(``color_by``), which takes its colours from the dashboard's ``category_colors``, the
same as the filters, the cards and the navigator's lanes.

Sources:
    hub     ``samples`` (this template's ``samples.py``): the samples and their group
    sheet   the run's sample sheet (the template repoints it at ``{SAMPLESHEET}``)
    genes   ``outlier_genes`` (optional): its strongest gene names the sample whose
            alignment opens first

Output schema:
    track_id : Utf8     `<sample>.<kind>`, unique per file
    sample : Utf8       the sample the file belongs to (links to the hub)
    drop_group : Utf8   the sample's primary group (the hub's)
    kind : Utf8         alignments / genotypes
    format : Utf8       bam / vcf
    uri : Utf8          the file, as read (see above)
    index_uri : Utf8    its index (BAI, TBI), empty when the sheet names none
    name : Utf8         track label shown in the browser
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="hub",
        dc_ref="samples",
        input_schema={"sample": pl.Utf8, "drop_group": pl.Utf8},
    ),
    RecipeSource(
        ref="sheet",
        path="input/samplesheet.tsv",
        format="tsv",
        input_schema={"RNA_ID": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
    # Only its strongest gene is read, to open the reads of that gene's sample.
    RecipeSource(
        ref="genes",
        dc_ref="outlier_genes",
        optional=True,
        input_schema={"sample": pl.Utf8, "significance": pl.Float64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "drop_group": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "index_uri": pl.Utf8,
    "name": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}


def _cell(record: dict, column: str) -> str:
    value = record.get(column)
    text = "" if value is None else str(value).strip()
    return "" if text in ("NA", "nan") else text


def _locate(path: str, context) -> str:
    """Where the file is read from: a URL as written, a file under the root by its path or name."""
    if not path or "://" in path:
        return path
    if not path.startswith("/") and context is not None and context.exists(path):
        return path
    if context is not None:
        name = path.rsplit("/", 1)[-1]
        hits = context.glob(f"**/{name}")
        if hits:
            return hits[0]
    return path


def _present(uri: str, context) -> bool:
    """A remote or absolute file cannot be checked; a relative one must be under the root."""
    if not uri or "://" in uri or uri.startswith("/"):
        return True
    return context is None or context.exists(uri)


def _top_sample(genes: pl.DataFrame | None, groups: dict[str, str]) -> str | None:
    """The sample of the strongest gene (the browser's first stop), ties by name; None without genes."""
    if genes is None or genes.is_empty() or "significance" not in genes.columns:
        return None
    ranked = genes.filter(
        pl.col("significance").is_not_null() & pl.col("sample").is_in(list(groups))
    )
    if "chrom" in ranked.columns:
        ranked = ranked.filter(pl.col("chrom").is_not_null())
    best = ranked.sort(["significance", "sample"], descending=[True, False]).head(1)
    return best["sample"][0] if best.height else None


def transform(sources: dict[str, pl.DataFrame | None], context=None) -> pl.DataFrame:
    """Spell out the alignment and the genotype file of every sample of the sheet."""
    groups = {r["sample"]: r["drop_group"] for r in sources["hub"].to_dicts()}
    records = [r for r in sources["sheet"].to_dicts() if _cell(r, "RNA_ID") in groups]

    # The first sample of each group before the second.
    seen: dict[str, int] = {}
    rank: dict[str, int] = {}
    for rec in records:
        sample = _cell(rec, "RNA_ID")
        seen[groups[sample]] = seen.get(groups[sample], 0) + 1
        rank[sample] = seen[groups[sample]]
    records.sort(key=lambda r: rank[_cell(r, "RNA_ID")])

    def row(
        rec: dict, kind: str, fmt: str, file_col: str, index_col: str, label: str, category: str
    ):
        sample = _cell(rec, "RNA_ID")
        uri = _locate(_cell(rec, file_col), context)
        if not uri:
            return None
        return {
            "track_id": f"{sample}.{kind}",
            "sample": sample,
            "drop_group": groups[sample],
            "kind": kind,
            "format": fmt,
            "uri": uri,
            "index_uri": _locate(_cell(rec, index_col), context),
            "name": f"{sample} {label}",
            "category": category,
        }

    genotypes = [
        r
        for rec in records
        if (
            r := row(
                rec, "genotypes", "vcf", "DNA_VCF_FILE", "DNA_TBI_FILE", "genotypes", "Variants"
            )
        )
    ]
    alignments = [
        r
        for rec in records
        if (
            r := row(
                rec, "alignments", "bam", "RNA_BAM_FILE", "RNA_BAI_FILE", "alignments", "Alignments"
            )
        )
    ]

    # Opening rows: the reads and the genotypes of the strongest call's sample, then the
    # reads of the first sample of every other group; the rest follows.
    top = _top_sample(sources.get("genes"), groups)
    reads_first = next((r for r in alignments if r["sample"] == top), None) or (
        alignments[0] if alignments else None
    )
    opening_sample = reads_first["sample"] if reads_first else top
    head: list[dict] = [reads_first] if reads_first else []
    head += [r for r in genotypes if r["sample"] == opening_sample][:1]
    seen_groups = {groups[opening_sample]} if opening_sample in groups else set()
    for r in alignments:
        if r["drop_group"] not in seen_groups:
            seen_groups.add(r["drop_group"])
            head.append(r)
    taken = {r["track_id"] for r in head}
    rows = [
        *head,
        *[r for r in genotypes if r["track_id"] not in taken],
        *[r for r in alignments if r["track_id"] not in taken],
    ]

    if context is not None and not context.reads_in_place:
        kept = [r for r in rows if _present(r["uri"], context)]
        if any("://" not in r["uri"] and not r["uri"].startswith("/") for r in kept):
            rows = kept
    for i, r in enumerate(rows, start=1):
        r["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
