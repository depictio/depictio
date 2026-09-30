"""Exon and CDS blocks of every transcript in a run's GTF/GFF annotations.

A GTF says what an isoform looks like and nothing else does: the counts tables
say how much of it there is, the BAMs say which reads support it, but the exon
boundaries live only here. This recipe turns the nine-column annotation into
the long frame the `transcript_structure` kind binds, one row per drawn block.

Input: the ``gtf_transcripts_raw`` data collection, declared by the template as::

    config:
      type: Table
      metatype: Aggregate
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*\\.gtf(\\.gz)?$'}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          comment_prefix: "#"
          quote_char: null
          new_columns: ["seqname", "source", "feature", "start", "end",
                        "score", "strand", "frame", "attributes"]
          include_file_paths: "source_path"
          infer_schema_length: 0
          truncate_ragged_lines: true

The scan is what carries the file name (``include_file_paths``); the sample of
a per-sample GTF is written nowhere else, and a run-level annotation (bambu's
``extended_annotations.gtf``) is reported as ``all_samples``, the same name the
per-run aggregations use elsewhere in the catalog. A pipeline that publishes
more than one annotation per sample narrows that regex to the one it means:
nf-core/rnaseq writes ``<sample>.transcripts.gtf`` and ``<sample>.coverage.gtf``
side by side, and scanning both would draw each isoform twice.

Output schema (one row per exon / CDS block):
    transcript_id : Utf8       isoform the block belongs to
    gene_id : Utf8            gene the isoform belongs to
    gene_name : Utf8           readable symbol, falling back to gene_id
    chrom : Utf8              sequence the block sits on
    start : Int64              block start, 1-based inclusive as the GTF writes it
    end : Int64                block end, inclusive
    feature : Utf8             "exon" or "CDS"
    strand : Utf8              "+" or "-"
    transcript_class : Utf8    known / NIC / NNC / novel / other, see below
    sample : Utf8              file the block was read from
    expression : Float64       TPM, else FPKM, else coverage; null when absent

`transcript_class` is read from whichever novelty attribute the writer left:
gffcompare's ``class_code``, bambu's ``novel`` flag, or a ``transcript_type`` /
``transcript_biotype``. A reference annotation carries none of the three and
every transcript then reads `known`, which is the truth about it.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

#: Data-collection tag the template must scan the raw annotations into (see the
#: module docstring). Any pipeline reusing this recipe declares a DC with this tag.
RAW_DC_TAG = "gtf_transcripts_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="gtf", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "transcript_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "feature": pl.Utf8,
    "strand": pl.Utf8,
    "transcript_class": pl.Utf8,
    "sample": pl.Utf8,
    "expression": pl.Float64,
}

SOURCE_PATH_COL = "source_path"

#: The two block features a transcript is drawn from. UTRs are left out on
#: purpose: they overlap the exons that already carry them, so drawing both
#: would double every terminal block.
_EXON = "exon"
_CDS = "CDS"

#: Feature names, lower-cased, that mean "this row describes the whole
#: transcript" rather than one of its blocks. GTF writes `transcript`, GFF3
#: writes `mRNA`. These rows carry the per-transcript expression.
_TRANSCRIPT_FEATURES = ("transcript", "mrna")

#: gffcompare class codes, collapsed onto the four labels the renderer badges.
#: `=` and `c` match a reference transcript, `j`-family isoforms reuse known
#: junctions (novel in catalogue), `o`/`s` overlap without reusing them (novel
#: not in catalogue), and the rest sit off the reference entirely.
_CLASS_CODE_LABELS: dict[str, str] = {
    "=": "known",
    "c": "known",
    "j": "NIC",
    "k": "NIC",
    "m": "NIC",
    "n": "NIC",
    "e": "NIC",
    "o": "NNC",
    "s": "NNC",
    "i": "novel",
    "u": "novel",
    "x": "novel",
    "y": "novel",
    "p": "novel",
}

#: Values a boolean-ish novelty attribute (bambu's `novel`) uses for true.
_TRUE_VALUES = ("true", "TRUE", "True", "1", "yes", "YES", "Y")

#: Trailing dot-separated tokens of an annotation file name that name the
#: output rather than the sample. `strip_stage_suffixes` handles the alignment
#: stages on top of these; these are the annotation-specific ones.
_ANNOTATION_TOKENS = frozenset({"gtf", "gff", "gff3", "gz", "transcripts", "annotated", "combined"})

#: File stems that are a run-level annotation, not a sample's own.
_RUN_LEVEL_STEMS = frozenset(
    {"extended_annotations", "unextended_annotations", "novel_annotations"}
)

#: Reported for a run-level annotation, matching the `all_samples.*` naming the
#: per-run aggregations already use in this catalog.
_RUN_LEVEL_SAMPLE = "all_samples"


def _sample_from_path(source_path: str) -> str:
    """Sample id of an annotation file, from its name alone."""
    tokens = Path(str(source_path).replace("\\", "/")).name.split(".")
    while len(tokens) > 1 and tokens[-1].lower() in _ANNOTATION_TOKENS:
        tokens.pop()
    stem = ".".join(tokens)
    if stem.lower() in _RUN_LEVEL_STEMS:
        return _RUN_LEVEL_SAMPLE
    return strip_stage_suffixes(stem)


def _attr(key: str) -> pl.Expr:
    """One attribute of the ninth column, in either GTF or GFF3 spelling.

    GTF writes ``key "value";`` and GFF3 writes ``key=value;``. Anchoring on a
    separator is what stops ``gene_id`` from also matching ``ref_gene_id``.
    """
    gtf = pl.col("attributes").str.extract(rf'(?:^|;)\s*{key}\s+"([^"]*)"', 1)
    gff3 = pl.col("attributes").str.extract(rf"(?:^|;)\s*{key}=([^;]*)", 1)
    return pl.coalesce([gtf, gff3])


def _novelty() -> pl.Expr:
    """The first novelty label any of the three attribute families provides."""
    class_code = _attr("class_code")
    novel = pl.coalesce([_attr("novel"), _attr("novelTranscript")])
    return pl.coalesce(
        [
            # `replace_strict` maps a null to its default, so the code has to be
            # known-present before it is mapped or every reference GTF would read
            # "other" instead of falling through to the next attribute.
            pl.when(class_code.is_not_null())
            .then(class_code.replace_strict(_CLASS_CODE_LABELS, default="other"))
            .otherwise(None),
            pl.when(novel.is_in(_TRUE_VALUES))
            .then(pl.lit("novel"))
            .when(novel.is_not_null())
            .then(pl.lit("known"))
            .otherwise(None),
            pl.coalesce([_attr("transcript_type"), _attr("transcript_biotype")]),
        ]
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Long exon / CDS blocks with their transcript, gene, class and expression."""
    raw = sources["gtf"]
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "gtf_transcripts: no 'source_path' column, the raw DC must scan with "
            "include_file_paths: source_path (the sample is only in the file name)"
        )

    samples = {
        path: _sample_from_path(path) for path in raw[SOURCE_PATH_COL].unique().to_list() if path
    }
    # `_feature` first, on its own pass: the GFF3 fallbacks below read it, and
    # expressions inside one `with_columns` all see the frame as it came in.
    parsed = raw.with_columns(
        pl.col(SOURCE_PATH_COL).replace_strict(samples, default="unknown").alias("sample"),
        pl.col("feature").str.to_lowercase().alias("_feature"),
    )
    is_transcript_line = pl.col("_feature").is_in(_TRANSCRIPT_FEATURES)
    parsed = parsed.with_columns(
        # GTF names the transcript on every line. GFF3 does not: a transcript
        # line carries its own `ID` and its blocks point at it with `Parent`,
        # which is how StringTie's own coverage GFF and most reference
        # annotations are written.
        pl.coalesce(
            [
                _attr("transcript_id"),
                pl.when(is_transcript_line).then(_attr("ID")).otherwise(_attr("Parent")),
            ]
        ).alias("transcript_id"),
        pl.coalesce(
            [
                _attr("gene_id"),
                _attr("geneID"),
                pl.when(is_transcript_line).then(_attr("Parent")).otherwise(None),
            ]
        ).alias("gene_id"),
        pl.coalesce([_attr("gene_name"), _attr("ref_gene_name"), _attr("Name")]).alias("gene_name"),
        _novelty().alias("transcript_class"),
        # Expression as the writer spelled it. StringTie puts TPM and FPKM on
        # the transcript line and only a coverage figure on the exons, so they
        # are tried in that order and the transcript line wins the join below.
        pl.coalesce([_attr("TPM"), _attr("FPKM"), _attr("cov"), _attr("coverage")])
        .cast(pl.Float64, strict=False)
        .alias("_expression"),
    ).filter(pl.col("transcript_id").is_not_null())

    blocks = parsed.filter(pl.col("_feature").is_in([_EXON, _CDS.lower()]))
    if blocks.is_empty():
        raise ValueError(
            "gtf_transcripts: no exon or CDS rows in the scanned annotations; "
            f"features seen: {sorted(parsed['_feature'].unique().to_list())[:10]}"
        )

    # Per-transcript facts, taken off the `transcript` / `mRNA` line when the
    # writer emitted one. A GFF3 block carries only its `Parent`, so the gene,
    # the symbol, the class and the expression all have to come down from there.
    transcript_lines = (
        parsed.filter(pl.col("_feature").is_in(_TRANSCRIPT_FEATURES))
        .select(
            "sample",
            "transcript_id",
            pl.col("gene_id").alias("_tx_gene_id"),
            pl.col("gene_name").alias("_tx_gene_name"),
            pl.col("_expression").alias("_tx_expression"),
            pl.col("transcript_class").alias("_tx_class"),
        )
        .unique(subset=["sample", "transcript_id"], keep="first")
    )
    blocks = blocks.join(transcript_lines, on=["sample", "transcript_id"], how="left")

    gene_id = pl.coalesce([pl.col("gene_id"), pl.col("_tx_gene_id"), pl.col("transcript_id")]).cast(
        pl.Utf8
    )
    out = blocks.select(
        pl.col("transcript_id").cast(pl.Utf8),
        gene_id.alias("gene_id"),
        pl.coalesce([pl.col("gene_name"), pl.col("_tx_gene_name"), gene_id])
        .cast(pl.Utf8)
        .alias("gene_name"),
        pl.col("seqname").cast(pl.Utf8).alias("chrom"),
        # A GTF block is written low-to-high whatever the strand, but a writer
        # that puts start above end must not make the block vanish downstream.
        pl.min_horizontal(
            pl.col("start").cast(pl.Int64, strict=False), pl.col("end").cast(pl.Int64, strict=False)
        ).alias("start"),
        pl.max_horizontal(
            pl.col("start").cast(pl.Int64, strict=False), pl.col("end").cast(pl.Int64, strict=False)
        ).alias("end"),
        pl.when(pl.col("_feature") == _CDS.lower())
        .then(pl.lit(_CDS))
        .otherwise(pl.lit(_EXON))
        .alias("feature"),
        # A GFF3 may leave the strand unknown (`.`); anything that is not minus
        # is drawn pointing right, so it is normalised to plus here.
        pl.when(pl.col("strand") == "-").then(pl.lit("-")).otherwise(pl.lit("+")).alias("strand"),
        pl.coalesce([pl.col("_tx_class"), pl.col("transcript_class")])
        .fill_null("known")
        .cast(pl.Utf8)
        .alias("transcript_class"),
        pl.col("sample").cast(pl.Utf8),
        pl.coalesce([pl.col("_tx_expression"), pl.col("_expression")])
        .cast(pl.Float64)
        .alias("expression"),
    ).filter(pl.col("start").is_not_null() & pl.col("end").is_not_null())

    return out.sort(["sample", "chrom", "gene_id", "transcript_id", "start"]).select(
        list(EXPECTED_SCHEMA)
    )
