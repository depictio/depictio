"""Genome-browser track manifest: one row per track file the run published.

nf-core/viralrecon names every per-sample output after the sample of the
MultiQC summary (``multiqc/summary_variants_metrics_mqc.csv``, the file the
``summary_metrics`` collection reads), so the manifest is spelled out from that
list rather than globbed: for each sample the called variants (a bgzipped VCF)
and the primer-trimmed alignments (a BAM), each as a row of its own keyed on
the sample.

Each file has a few homes, by route. The first one the run holds is used:
- variants: the snpEff-annotated VCF first (``variants/ivar/snpeff/``, then
  ``variants/bcftools/snpeff/``: its ``ANN`` field colours the browser's calls
  by effect), else the plain one (``variants/ivar/``, ``variants/bcftools/``),
  else ``artic_minion/<S>.pass.vcf.gz`` (nanopore);
- alignments: ``variants/bowtie2/<S>.ivar_trim.sorted.bam`` (illumina),
  ``artic_minion/<S>.primertrimmed.rg.sorted.bam`` (nanopore).

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): one block per sample, its variants then its alignments. The first block
is the sample holding the run's best supported call (the highest ``call_score``
of ``variants_long``, the call the browser opens on), so the reads sit under the
first call; the other samples follow in the order of the summary.

The manifest holds no colour of its own: a colour column would win over the
dashboard's palette. The tile colours the tracks by ``lineage`` instead, the
column the dashboard's ``category_colors`` keys, so a sample keeps the hue the
plots give its lineage.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder, on the
  first (snpEff ivar / bowtie2) layout;
- otherwise the rows whose file is present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a
  tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<sample_id>.<kind>`, unique per file
    sample_id : Utf8    the sample (links to `summary_metrics`)
    kind : Utf8         variants / alignments
    format : Utf8       vcf / bam
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    lineage : Utf8      Pangolin lineage of the sample ("Unassigned" without one)
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="multiqc/summary_variants_metrics_mqc.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
    # Only its best supported call is read, to open the reads of that call's sample.
    RecipeSource(
        ref="variants",
        dc_ref="variants_long",
        optional=True,
        input_schema={"sample": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "lineage": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

# kind -> (format, candidate paths in order of preference, category, name)
_VARIANTS = (
    "variants",
    "vcf",
    (
        "variants/ivar/snpeff/{s}.snpeff.vcf.gz",
        "variants/bcftools/snpeff/{s}.snpeff.vcf.gz",
        "variants/ivar/{s}.vcf.gz",
        "variants/bcftools/{s}.vcf.gz",
        "artic_minion/{s}.pass.vcf.gz",
    ),
    "Variants",
    "{s} variants",
)
_ALIGNMENTS = (
    "alignments",
    "bam",
    (
        "variants/bowtie2/{s}.ivar_trim.sorted.bam",
        "artic_minion/{s}.primertrimmed.rg.sorted.bam",
    ),
    "Alignments",
    "{s} reads",
)


def _top_call_sample(variants: pl.DataFrame | None, samples: list[str]) -> str | None:
    """The sample of the best supported call (``call_score``), None without calls."""
    if variants is None or variants.is_empty() or "sample" not in variants.columns:
        return None
    rank = next((c for c in ("call_score", "AF") if c in variants.columns), None)
    if rank is None:
        return None
    best = (
        variants.filter(pl.col(rank).is_not_null() & pl.col("sample").is_in(samples))
        .sort([rank, "sample"], descending=[True, False])
        .head(1)
    )
    return str(best["sample"][0]) if best.height else None


def _lineages(summary: pl.DataFrame) -> dict[str, str]:
    """Sample -> Pangolin lineage of the summary; "Unassigned" where it holds none."""
    col = next((c for c in summary.columns if "lineage" in c.lower()), None)
    out: dict[str, str] = {}
    for row in summary.to_dicts():
        sample = str(row["Sample"]).strip() if row.get("Sample") is not None else ""
        if not sample:
            continue
        value = str(row[col]).strip() if col and row.get(col) is not None else ""
        out[sample] = "Unassigned" if value in ("", "NA") else value
    return out


def transform(sources: dict[str, pl.DataFrame | None], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every sample of the summary."""
    summary = sources["summary"]
    # A UTF-8 BOM would stay glued to the first header.
    summary = summary.rename({c: c.lstrip("﻿").strip() for c in summary.columns})
    if "Sample" not in summary.columns:
        raise ValueError(
            "viralrecon tracks: summary_variants_metrics_mqc.csv lacks a Sample column"
        )

    samples = [
        s
        for s in dict.fromkeys(str(v).strip() for v in summary["Sample"].to_list() if v is not None)
        if s
    ]

    # The sample holding the best supported call leads, so its reads open under it.
    top = _top_call_sample(sources.get("variants"), samples)
    if top is not None:
        samples = [top, *[s for s in samples if s != top]]
    lineage = _lineages(summary)

    def uri_for(sample_id: str, candidates: tuple[str, ...]) -> str:
        """The first candidate the run holds; the first one when none (or in place)."""
        paths = [c.format(s=sample_id) for c in candidates]
        if context is None or context.reads_in_place:
            return paths[0]
        return next((p for p in paths if context.exists(p)), paths[0])

    rows: list[dict] = []
    for sample_id in samples:
        for kind, fmt, candidates, category, name in (_VARIANTS, _ALIGNMENTS):
            rows.append(
                {
                    "track_id": f"{sample_id}.{kind}",
                    "sample_id": sample_id,
                    "kind": kind,
                    "format": fmt,
                    "uri": uri_for(sample_id, candidates),
                    "name": name.format(s=sample_id),
                    "lineage": lineage.get(sample_id, "Unassigned"),
                    "category": category,
                }
            )

    if (
        context is not None
        and not context.reads_in_place
        and any(context.exists(r["uri"]) for r in rows)
    ):
        rows = [r for r in rows if context.exists(r["uri"])]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
