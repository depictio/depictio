"""The `gtf/transcripts` recipe, on the shapes real annotations come in.

The recipe reads a raw data collection rather than a glob (the sample of a
per-sample GTF is only in its file name, and only a scan carries that), so each
test here builds the frame that DC's ``polars_kwargs`` produce and injects it as
``extra_sources``. `test_matches_a_real_stringtie_scan` does the same thing the
other way round: it writes a real StringTie excerpt to disk and scans it with
exactly the kwargs the template declares, so a drift between the documented
scan and the parsing would fail here rather than on a run.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.models.components.advanced_viz.configs import TranscriptStructureConfig
from depictio.models.components.advanced_viz.schemas import validate_binding
from depictio.recipes import execute_recipe

RECIPE = "gtf/transcripts.py"

#: Columns the raw DC declares, in order (see the recipe's module docstring).
RAW_COLUMNS = [
    "seqname",
    "source",
    "feature",
    "start",
    "end",
    "score",
    "strand",
    "frame",
    "attributes",
]

#: The scan the template must declare. Kept here so the test exercises the
#: documented kwargs rather than a convenient approximation of them.
SCAN_KWARGS: dict = {
    "separator": "\t",
    "has_header": False,
    "comment_prefix": "#",
    "quote_char": None,
    "new_columns": RAW_COLUMNS,
    "include_file_paths": "source_path",
    "infer_schema_length": 0,
    "truncate_ragged_lines": True,
}


def _raw(rows: list[tuple], source_path: str) -> pl.DataFrame:
    """A raw scan frame: nine string columns plus the file the line came from."""
    frame = pl.DataFrame(
        [list(map(str, r)) for r in rows],
        schema={c: pl.Utf8 for c in RAW_COLUMNS},
        orient="row",
    )
    return frame.with_columns(pl.lit(source_path).alias("source_path"))


def _gtf_attrs(**kwargs: str) -> str:
    return "; ".join(f'{k} "{v}"' for k, v in kwargs.items()) + ";"


def _run(raw: pl.DataFrame, tmp_path: Path) -> pl.DataFrame:
    return execute_recipe(RECIPE, tmp_path, extra_sources={"gtf": raw})


# ---------------------------------------------------------------------------
# StringTie (rnaseq): GTF attributes, per-sample file names, TPM on the
# transcript line only.
# ---------------------------------------------------------------------------


def _stringtie_rows(tpm: str) -> list[tuple]:
    tx = _gtf_attrs(gene_id="YAL001C", transcript_id="YAL001C", ref_gene_name="TFC3", TPM=tpm)
    exon1 = _gtf_attrs(
        gene_id="YAL001C", transcript_id="YAL001C", exon_number="1", ref_gene_name="TFC3", cov="0.0"
    )
    exon2 = _gtf_attrs(
        gene_id="YAL001C", transcript_id="YAL001C", exon_number="2", ref_gene_name="TFC3", cov="0.0"
    )
    return [
        ("I", "StringTie", "transcript", 147594, 151166, "1000", "-", ".", tx),
        ("I", "StringTie", "exon", 147594, 151006, "1000", "-", ".", exon1),
        ("I", "StringTie", "exon", 151097, 151166, "1000", "-", ".", exon2),
    ]


def test_stringtie_blocks_carry_sample_and_transcript_expression(tmp_path: Path) -> None:
    raw = pl.concat(
        [
            _raw(_stringtie_rows("817.8"), "/data/stringtie/WT_REP1.transcripts.gtf"),
            _raw(_stringtie_rows("142.3"), "/data/stringtie/WT_REP2.transcripts.gtf"),
        ]
    )
    result = _run(raw, tmp_path)

    # The `transcript` line is metadata, not a block: only the exons are drawn.
    assert result.height == 4
    assert result["feature"].unique().to_list() == ["exon"]
    assert sorted(result["sample"].unique().to_list()) == ["WT_REP1", "WT_REP2"]
    assert result["gene_name"].unique().to_list() == ["TFC3"]
    assert result["strand"].unique().to_list() == ["-"]
    # TPM lives on the transcript line; every block of that transcript gets it.
    by_sample = dict(zip(result["sample"].to_list(), result["expression"].to_list(), strict=True))
    assert by_sample["WT_REP1"] == pytest.approx(817.8)
    assert by_sample["WT_REP2"] == pytest.approx(142.3)
    # No novelty attribute anywhere: a reference annotation is known, not "other".
    assert result["transcript_class"].unique().to_list() == ["known"]


def test_matches_a_real_stringtie_scan(tmp_path: Path) -> None:
    """The documented scan kwargs parse a real StringTie file header and all."""
    gtf = tmp_path / "stringtie" / "RAP1_UNINDUCED_REP1.transcripts.gtf"
    gtf.parent.mkdir(parents=True)
    gtf.write_text(
        "# stringtie RAP1_UNINDUCED_REP1.markdup.sorted.bam --rf -G genome_gfp.gtf\n"
        "# StringTie version 2.2.3\n"
        'I\tensembl\ttranscript\t2480\t2707\t.\t+\t.\tgene_id "YAL067W-A"; '
        'transcript_id "YAL067W-A"; ref_gene_name "YAL067W-A"; cov "0.0"; '
        'FPKM "0.000000"; TPM "0.000000";\n'
        'I\tensembl\texon\t2480\t2707\t.\t+\t.\tgene_id "YAL067W-A"; '
        'transcript_id "YAL067W-A"; exon_number "1"; ref_gene_name "YAL067W-A"; cov "0.0";\n'
    )
    raw = pl.scan_csv(str(gtf), **SCAN_KWARGS).collect()
    assert raw.height == 2  # the two banner lines are comments, not rows

    result = _run(raw, tmp_path)
    assert result.height == 1
    row = result.row(0, named=True)
    assert row["sample"] == "RAP1_UNINDUCED_REP1"
    assert (row["chrom"], row["start"], row["end"]) == ("I", 2480, 2707)
    assert row["transcript_id"] == "YAL067W-A"
    assert row["expression"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Novelty: gffcompare class codes, bambu's flag, a biotype as the last resort.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("class_code", "expected"),
    [("=", "known"), ("c", "known"), ("j", "NIC"), ("o", "NNC"), ("u", "novel"), ("?", "other")],
)
def test_gffcompare_class_codes_collapse_onto_four_labels(
    class_code: str, expected: str, tmp_path: Path
) -> None:
    attrs = _gtf_attrs(gene_id="G1", transcript_id="T1", class_code=class_code)
    raw = _raw(
        [
            ("chr1", "gffcompare", "transcript", 100, 900, ".", "+", ".", attrs),
            ("chr1", "gffcompare", "exon", 100, 200, ".", "+", ".", attrs),
        ],
        "/data/gffcompare/S1.annotated.gtf",
    )
    assert _run(raw, tmp_path)["transcript_class"].to_list() == [expected]


def test_bambu_novel_flag_and_run_level_file_name(tmp_path: Path) -> None:
    novel = _gtf_attrs(gene_id="ENSG1", transcript_id="tx.1", novel="TRUE")
    known = _gtf_attrs(gene_id="ENSG1", transcript_id="ENST1", novel="FALSE")
    raw = _raw(
        [
            ("1", "bambu", "exon", 1000, 1200, ".", "+", ".", novel),
            ("1", "bambu", "exon", 1000, 1200, ".", "+", ".", known),
        ],
        "/data/bambu/extended_annotations.gtf",
    )
    result = _run(raw, tmp_path)
    # A run-level annotation names no sample, so it reports the whole run.
    assert result["sample"].unique().to_list() == ["all_samples"]
    assert dict(
        zip(result["transcript_id"].to_list(), result["transcript_class"].to_list(), strict=True)
    ) == {"tx.1": "novel", "ENST1": "known"}


def test_biotype_is_the_last_resort_for_the_class(tmp_path: Path) -> None:
    attrs = _gtf_attrs(gene_id="G1", transcript_id="T1", transcript_biotype="lncRNA")
    raw = _raw([("chr1", "ensembl", "exon", 10, 40, ".", "+", ".", attrs)], "/data/ref/S1.gtf")
    assert _run(raw, tmp_path)["transcript_class"].to_list() == ["lncRNA"]


# ---------------------------------------------------------------------------
# GFF3 spelling, CDS blocks, and the guards.
# ---------------------------------------------------------------------------


def test_gff3_attributes_and_cds_blocks(tmp_path: Path) -> None:
    attrs = "ID=exon1;Parent=T1;gene_id=G1;transcript_id=T1;gene_name=ACME"
    raw = _raw(
        [
            ("chr2", "ensembl", "mRNA", 100, 900, ".", ".", ".", attrs),
            ("chr2", "ensembl", "exon", 100, 300, ".", ".", ".", attrs),
            ("chr2", "ensembl", "CDS", 150, 300, ".", ".", "0", attrs),
            ("chr2", "ensembl", "five_prime_UTR", 100, 149, ".", ".", ".", attrs),
        ],
        "/data/ref/sampleA.gff3",
    )
    result = _run(raw, tmp_path)

    # UTR rows are dropped: they overlap the exon that already carries them.
    assert sorted(result["feature"].to_list()) == ["CDS", "exon"]
    assert result["gene_name"].unique().to_list() == ["ACME"]
    assert result["sample"].unique().to_list() == ["sampleA"]
    # An unknown GFF3 strand still has to point somewhere.
    assert result["strand"].unique().to_list() == ["+"]


def test_gff3_id_and_parent_name_the_transcript(tmp_path: Path) -> None:
    """A GFF3 that names nothing `transcript_id` still resolves its blocks.

    This is StringTie's own `*.coverage.gtf` and most reference annotations: the
    transcript line carries `ID`, its blocks point back with `Parent`, and the
    gene is the transcript's own `Parent`.
    """
    raw = _raw(
        [
            (
                "I",
                "ensembl",
                "transcript",
                2480,
                2707,
                ".",
                "+",
                ".",
                "ID=YAL067W-A;Parent=GENE1;gene_name=SEO1;coverage=0.16",
            ),
            ("I", "ensembl", "exon", 2480, 2707, ".", "+", ".", "Parent=YAL067W-A"),
        ],
        "/data/stringtie/WT_REP1.coverage.gtf",
    )
    row = _run(raw, tmp_path).row(0, named=True)
    assert row["transcript_id"] == "YAL067W-A"
    assert row["gene_id"] == "GENE1"
    assert row["gene_name"] == "SEO1"
    assert row["expression"] == pytest.approx(0.16)
    # The file name says which stringtie output it is, so the sample keeps it.
    assert row["sample"] == "WT_REP1.coverage"


def test_reversed_coordinates_do_not_lose_the_block(tmp_path: Path) -> None:
    attrs = _gtf_attrs(gene_id="G1", transcript_id="T1")
    raw = _raw([("chr1", "x", "exon", 900, 100, ".", "-", ".", attrs)], "/data/ref/S1.gtf")
    row = _run(raw, tmp_path).row(0, named=True)
    assert (row["start"], row["end"]) == (100, 900)


def test_missing_source_path_is_an_explicit_failure(tmp_path: Path) -> None:
    attrs = _gtf_attrs(gene_id="G1", transcript_id="T1")
    raw = _raw([("chr1", "x", "exon", 10, 40, ".", "+", ".", attrs)], "/data/S1.gtf").drop(
        "source_path"
    )
    with pytest.raises(ValueError, match="source_path"):
        _run(raw, tmp_path)


def test_an_annotation_with_no_blocks_says_so(tmp_path: Path) -> None:
    attrs = _gtf_attrs(gene_id="G1", transcript_id="T1")
    raw = _raw([("chr1", "x", "gene", 10, 40, ".", "+", ".", attrs)], "/data/S1.gtf")
    with pytest.raises(ValueError, match="no exon or CDS rows"):
        _run(raw, tmp_path)


# ---------------------------------------------------------------------------
# The binding the catalog declares.
# ---------------------------------------------------------------------------


def test_output_satisfies_the_transcript_structure_binding(tmp_path: Path) -> None:
    raw = _raw(_stringtie_rows("12.5"), "/data/stringtie/WT_REP1.transcripts.gtf")
    result = _run(raw, tmp_path)
    config = TranscriptStructureConfig(
        transcript_id_col="transcript_id",
        gene_id_col="gene_id",
        chrom_col="chrom",
        start_col="start",
        end_col="end",
        feature_col="feature",
        strand_col="strand",
        sample_col="sample",
        gene_name_col="gene_name",
        transcript_class_col="transcript_class",
        expression_col="expression",
    )
    schema = {name: str(dtype) for name, dtype in result.schema.items()}
    assert validate_binding(config, schema) == []
