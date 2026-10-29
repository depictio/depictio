"""Genome-browser track manifest: the HaplotypeCaller VCF and the BAM of every sample.

nf-core/rnavar calls with one caller, HaplotypeCaller, and writes each sample's
callset under ``variant_calling/<S>/``: the filtered VCF
(``<S>.haplotypecaller.filtered.vcf.gz``, FILTER set by VariantFiltration) and
the raw one. The manifest keeps the filtered VCF of every sample, the raw one
when a sample has no filtered twin. The snpEff-annotated twin
(``annotation/<S>/<S>.haplotypecaller.filtered_snpEff.ann.vcf.gz``) comes first
when the run annotated, so the browser can colour the calls by impact.

Rows open on the design and on the reads: the VCF of one representative sample per
group (the groups in the hub's order, the sample holding the run's strongest call
standing for its group), then the duplicate-marked STAR alignment of that sample
(``preprocessing/<S>/<S>.md.bam`` with its ``.bai``, 14 to 21 GB each in a full
run), so the reads sit under the first call and ``show_junctions`` draws the
splice arcs over their coverage on opening. The other samples' VCFs follow, the
other alignments last. A run started from BAM or CRAM has no such file, and a file
whose index is missing is left out of an upload (a bgzipped VCF cannot be read
without its ``.tbi``, a BAM without its ``.bai``).

The design group (the template's ``GROUP_COL``: a cell line, a condition) is a
column of the manifest under its own name, which the tile colours by
(``color_by``): the replicates of a group share a hue, the groups differ, and the
Tracks menu groups the tracks by it. Without a design table the column is the
hub's constant ``__no_group__``.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder;
- otherwise the rows whose file (and index) are present under DATA_ROOT are kept
  and the CLI uploads them at ingestion; a tables-only run, which holds none,
  keeps every row.

Sources:
    hub        ``samples`` (this template's ``samples.py``): the samples and their design group
    variants   ``vcf_variants`` (optional): its highest-QUAL call, the one the browser opens on,
               names the sample whose alignment opens beside the calls

Parameters:
    group_col  the design column the tracks are coloured by (the template's ``GROUP_COL``)

Output schema (the group column is named by ``group_col``):
    track_id : Utf8     `<sample>.haplotypecaller` or `<sample>.alignments`, unique per file
    sample : Utf8       the sample (links to the `samples` hub)
    <group> : Utf8      the sample's design group
    format : Utf8       vcf / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
# The samples of the run; their files are then found under the data root.
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="hub", dc_ref="samples", input_schema={"sample": pl.Utf8}),
    # Only its strongest call is read, to open the reads of that call's sample.
    RecipeSource(
        ref="variants",
        dc_ref="vcf_variants",
        optional=True,
        input_schema={"sample": pl.Utf8, "qual": pl.Float64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}
# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Column the group falls back to when the run has no design table.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All samples"


def _vcf_candidates(sample: str) -> list[str]:
    """Paths the sample's callset may have, preferred first."""
    return [
        f"annotation/{sample}/{sample}.haplotypecaller.filtered_snpEff.ann.vcf.gz",
        f"variant_calling/{sample}/{sample}.haplotypecaller.filtered.vcf.gz",
        f"variant_calling/{sample}/{sample}.haplotypecaller.vcf.gz",
    ]


def _bam(sample: str) -> str:
    return f"preprocessing/{sample}/{sample}.md.bam"


def _top_call_sample(variants: pl.DataFrame | None, groups: dict[str, str]) -> str | None:
    """The sample of the highest-QUAL call, ties by sample name; None without calls."""
    if variants is None or variants.is_empty() or "qual" not in variants.columns:
        return None
    best = (
        variants.filter(pl.col("qual").is_not_null() & pl.col("sample").is_in(list(groups)))
        .sort(["qual", "sample"], descending=[True, False])
        .head(1)
    )
    return best["sample"][0] if best.height else None


def transform(
    sources: dict[str, pl.DataFrame | None],
    context=None,
    params: dict[str, str] | None = None,
) -> pl.DataFrame:
    """List the callset and the alignment of every sample of the hub."""
    if context is None:
        raise ValueError("rnavar tracks: needs the data root to find the VCFs")
    hub = sources["hub"]
    group_col = (params or {}).get("group_col")
    if group_col and group_col in hub.columns and group_col != "sample":
        group = group_col
        groups = {
            r["sample"]: (r[group_col] or NO_GROUP_VALUE) for r in hub.to_dicts() if r["sample"]
        }
    else:
        group = NO_GROUP_COL
        groups = {s: NO_GROUP_VALUE for s in hub["sample"].drop_nulls().to_list()}
    if not groups:
        raise ValueError("rnavar tracks: the sample hub lists no sample")
    # The browser opens on the first rows: one representative sample per group, the
    # groups in the design's order (the hub's), then the other samples by name. The
    # sample of the strongest call (the stepper's first stop) stands for its group.
    ordered = sorted(groups)
    top = _top_call_sample(sources.get("variants"), groups)
    representatives = list(
        {groups[s]: s for s in reversed(ordered)}.values()  # first sample by name per group
    )
    if top is not None:
        representatives = [top if groups[s] == groups[top] else s for s in representatives]
    group_rank = {g: i for i, g in enumerate(dict.fromkeys(groups[s] for s in groups))}
    representatives.sort(key=lambda s: group_rank[groups[s]])
    samples = [*representatives, *[s for s in ordered if s not in representatives]]
    reads_first = top if top is not None else representatives[0]

    def present(path: str, index: str) -> bool:
        return context.exists(path) and context.exists(path + index)

    # Every file the run may hold, the annotated or filtered VCF first.
    vcfs: list[dict[str, str]] = []
    bams: list[dict[str, str]] = []
    for sample in samples:
        common = {"sample": sample, group: groups[sample]}
        candidates = _vcf_candidates(sample)
        uri = next((p for p in candidates if present(p, ".tbi")), candidates[1])
        vcfs.append(
            {
                **common,
                "track_id": f"{sample}.haplotypecaller",
                "format": "vcf",
                "uri": candidates[1] if context.reads_in_place else uri,
                "name": f"{sample} calls",
                "category": "Variants",
            }
        )
        bams.append(
            {
                **common,
                "track_id": f"{sample}.alignments",
                "format": "bam",
                "uri": _bam(sample),
                "name": f"{sample} alignments",
                "category": "Alignments",
            }
        )
    # The representatives' calls, the reads of the strongest call's sample, then
    # the other samples' calls and the other alignments.
    n_rep = len(representatives)
    opening = [b for b in bams if b["sample"] == reads_first]
    rest = [b for b in bams if b["sample"] != reads_first]
    rows = [*vcfs[:n_rep], *opening, *vcfs[n_rep:], *rest]
    if not context.reads_in_place:
        held = [r for r in rows if present(r["uri"], ".tbi" if r["format"] == "vcf" else ".bai")]
        # A tables-only run holds no file: list what the pipeline publishes.
        rows = held or rows
    for i, row in enumerate(rows, start=1):
        row["order"] = i  # type: ignore[assignment]
    schema = {**OUTPUT_SCHEMA, group: pl.Utf8}
    return pl.DataFrame(rows, schema=schema).select(
        "track_id", "sample", group, "format", "uri", "name", "category", "order"
    )
