"""nf-core/isoseq recipes (catalog pbccs/*, isoseq/*, tama/* and the sample hub).

Small synthetic outputs in the shapes the pipeline writes: chunked pbcopper JSON
reports, TAMA merge BED12 + membership table, TAMA collapse reports and a
reference GTF. These tests pin what the dashboard depends on: chunks summed
back into libraries and samples, the read support chained from merge to
collapse, one isoform per SQANTI-style category, the reference lanes of the
structure view, and a hub that survives a run without CCS reports.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

BED_COLUMNS = [
    "chrom", "chrom_start", "chrom_end", "name", "score", "strand", "thick_start",
    "thick_end", "item_rgb", "block_count", "block_sizes", "block_starts",
]  # fmt: skip


def _pb_report(report_id: str, attrs: dict[str, int]) -> str:
    return json.dumps(
        {
            "attributes": [
                {"id": k, "name": k.split(".")[-1], "value": v} for k, v in attrs.items()
            ],
            "id": report_id,
            "title": report_id,
        },
        indent=4,
    )


def _ccs(zmws: int, passed: int, few: int) -> str:
    return _pb_report(
        "ccs_processing",
        {
            "ccs_processing.zmw_input": zmws,
            "ccs_processing.zmw_passed_yield": passed,
            "ccs_processing.zmw_filtered_yield": zmws - passed,
            "ccs_processing.zmw_filtered_too_few_passes": few,
            "ccs_processing.zmw_filtered_poor_snr": zmws - passed - few,
            "ccs_processing.zmw_filtered_draft_failure": 0,
        },
    )


@pytest.fixture
def reads_dir(tmp_path: Path) -> Path:
    ccs = tmp_path / "01_PBCCS"
    ccs.mkdir()
    (ccs / "S_0.chunk1.report.json").write_text(_ccs(100, 80, 15))
    (ccs / "S_0.chunk2.report.json").write_text(_ccs(100, 70, 20))
    (ccs / "S_1.chunk1.report.json").write_text(_ccs(50, 40, 10))
    refine = tmp_path / "03_ISOSEQ_REFINE"
    refine.mkdir()
    # A refine report matches **/*.report.json too: the CCS recipes must skip it.
    (refine / "S_0.chunk1.filter_summary.report.json").write_text(
        _pb_report(
            "isoseq_refine",
            {"num_reads_fl": 60, "num_reads_flnc": 57, "num_reads_flnc_polya": 3},
        )
    )
    (refine / "S_0.chunk1.report.csv").write_text(
        "id,strand,fivelen,threelen,polyAlen,insertlen,primer\n"
        "r1,+,30,26,0,150,p\nr2,+,30,26,0,1050,p\nr3,+,30,26,0,1080,p\nr4,+,30,26,0,20000,p\n"
    )
    return tmp_path


def test_ccs_chunks_sum_into_libraries_and_samples(reads_dir: Path) -> None:
    out = execute_recipe("pbccs/zmw_yield.py", reads_dir)
    rows = {r["library"]: r for r in out.to_dicts()}
    assert set(rows) == {"S_0", "S_1"}
    assert {r["sample"] for r in rows.values()} == {"S"}
    assert rows["S_0"]["chunks"] == 2
    assert rows["S_0"]["zmw_input"] == 200
    assert rows["S_0"]["zmw_passed"] == 150
    assert rows["S_0"]["pct_passed"] == pytest.approx(75.0)
    assert rows["S_0"]["too_few_passes"] == 35


def test_ccs_outcomes_stack_to_100_percent(reads_dir: Path) -> None:
    out = execute_recipe("pbccs/zmw_outcomes.py", reads_dir)
    per_library = out.group_by("library").agg(pl.col("pct_of_input").sum())
    assert per_library["pct_of_input"].to_list() == pytest.approx([100.0, 100.0])
    # Filters that removed nothing anywhere are dropped.
    assert "zmw_filtered_draft_failure" not in out["outcome"].to_list()
    assert "Passed" in out["outcome"].to_list()


def test_refine_summary_and_insert_length(reads_dir: Path) -> None:
    refine = execute_recipe("isoseq/refine_summary.py", reads_dir).to_dicts()
    assert refine == [
        {
            "sample": "S",
            "library": "S_0",
            "fl_reads": 60,
            "flnc_reads": 57,
            "flnc_polya_reads": 3,
            "chimeric_reads": 3,
            "pct_flnc": pytest.approx(95.0),
            "pct_polya": round(100.0 * 3 / 57, 2),
        }
    ]
    lengths = execute_recipe("isoseq/insert_length.py", reads_dir)
    assert dict(zip(lengths["length_bp"], lengths["reads"], strict=True)) == {
        100: 1,
        1000: 2,
        15000: 1,
    }
    assert lengths["cumulative_pct"].max() == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# TAMA transcriptome
# ---------------------------------------------------------------------------

# Reference: gene gA (+) with tA1 (introns 201-299, 401-499) and tA2
# (intron 151-299); gene gB (-) at 2000-3000.
GTF_ROWS = [
    ("tA1", "gA", "+", [(100, 200), (300, 400), (500, 600)]),
    ("tA2", "gA", "+", [(100, 150), (300, 400)]),
    ("tB1", "gB", "-", [(2000, 2100), (2900, 3000)]),
]

# Query isoforms: (transcript, gene, strand, exons, expected category, expected gene).
QUERIES = [
    ("G1.1", "G1", "+", [(100, 200), (300, 400), (500, 600)], "FSM", "gA"),
    ("G1.2", "G1", "+", [(300, 400), (500, 600)], "ISM", "gA"),
    ("G1.3", "G1", "+", [(100, 150), (300, 400), (500, 600)], "NIC", "gA"),
    ("G1.4", "G1", "+", [(100, 200), (310, 400)], "NNC", "gA"),
    ("G1.5", "G1", "+", [(120, 180)], "genic", "gA"),
    ("G2.1", "G2", "+", [(2050, 2080)], "antisense", "gB"),
    ("G3.1", "G3", "+", [(5000, 5100)], "intergenic", None),
]


def _gtf(rows: list[tuple]) -> str:
    lines = []
    for tid, gid, strand, exons in rows:
        for s, e in exons:
            attrs = f'gene_id "{gid}"; transcript_id "{tid}"; gene_name "{gid.upper()}";'
            lines.append(f"1\tref\texon\t{s}\t{e}\t.\t{strand}\t.\t{attrs}")
    return "\n".join(lines) + "\n"


def _bed_row(tid: str, gid: str, strand: str, exons: list[tuple[int, int]]) -> list[str]:
    start = exons[0][0] - 1
    end = exons[-1][1]
    sizes = ",".join(str(e - s + 1) for s, e in exons)
    starts = ",".join(str(s - 1 - start) for s, _ in exons)
    return ["1", str(start), str(end), f"{gid};{tid}", "40", strand, str(start), str(end),
            "0,0,0", str(len(exons)), sizes, starts]  # fmt: skip


@pytest.fixture
def tama_dir(tmp_path: Path) -> tuple[Path, pl.DataFrame]:
    merge = tmp_path / "09_GSTAMA_MERGE"
    merge.mkdir()
    collapse = tmp_path / "07_GSTAMA_COLLAPSE"
    collapse.mkdir()
    (tmp_path / "ULTRA_INDEX").mkdir()
    (tmp_path / "ULTRA_INDEX" / "genome.gtf").write_text(_gtf(GTF_ROWS))
    bed_rows = [_bed_row(t, g, s, ex) for t, g, s, ex, *_ in QUERIES]
    # G1.1 merges two collapse models (3 + 4 reads); every other isoform one (1 read).
    merge_lines = ["\t".join([*r[:3], f"{r[3].split(';')[1]};S_0.chunk1_collapsed.bed_C{i}.1", *r[4:]])
                   for i, r in enumerate(bed_rows)]  # fmt: skip
    merge_lines.append(
        "\t".join([*bed_rows[0][:3], "G1.1;S_0.chunk2_collapsed.bed_C0.1", *bed_rows[0][4:]])
    )
    (merge / "S_merge.txt").write_text("\n".join(merge_lines) + "\n")
    report = "transcript_id\tnum_clusters\thigh_coverage\n"
    (collapse / "S_0.chunk1_trans_report.txt").write_text(
        report + "".join(f"C{i}.1\t{3 if i == 0 else 1}\t100\n" for i in range(len(bed_rows)))
    )
    (collapse / "S_0.chunk2_trans_report.txt").write_text(report + "C0.1\t4\t100\n")
    bed = pl.DataFrame(bed_rows, schema=dict.fromkeys(BED_COLUMNS, pl.Utf8), orient="row")
    bed = pl.concat(
        [
            bed.with_columns(pl.lit("09_GSTAMA_MERGE/S.bed").alias("source_path")),
            # A per-chunk collapse BED and the pooled merge must both be ignored.
            bed.with_columns(
                pl.lit("07_GSTAMA_COLLAPSE/S_0.chunk1_collapsed.bed").alias("source_path")
            ),
            bed.with_columns(pl.lit("gstama/all_samples.bed").alias("source_path")),
        ]
    )
    return tmp_path, bed


def test_transcripts_categories_genes_and_support(tama_dir: tuple[Path, pl.DataFrame]) -> None:
    root, bed = tama_dir
    out = execute_recipe("tama/transcripts.py", root, extra_sources={"bed": bed})
    assert out.height == len(QUERIES)
    rows = {r["transcript_id"]: r for r in out.to_dicts()}
    for tid, _gid, _strand, exons, category, gene in QUERIES:
        row = rows[tid]
        assert row["sample"] == "S"
        assert row["structural_category"] == category, tid
        assert row["gene_id"] == (gene or f"S:{tid.split('.')[0]}"), tid
        assert row["start"] == exons[0][0] and row["end"] == exons[-1][1]
        assert row["exons"] == len(exons)
    assert rows["G1.1"]["ref_transcript_id"] == "tA1"
    assert rows["G1.1"]["gene_name"] == "GA"
    assert rows["G1.1"]["read_support"] == 7
    assert rows["G1.1"]["source_models"] == 2
    assert rows["G1.4"]["known_junctions"] == 0
    assert rows["G1.3"]["known_junctions"] == 2


def test_transcripts_without_reference_are_unclassified(
    tama_dir: tuple[Path, pl.DataFrame],
) -> None:
    root, bed = tama_dir
    (root / "ULTRA_INDEX" / "genome.gtf").unlink()
    out = execute_recipe("tama/transcripts.py", root, extra_sources={"bed": bed})
    assert set(out["structural_category"]) == {"unclassified"}
    assert out.filter(pl.col("transcript_id") == "G1.1")["gene_id"].item() == "S:G1"


def test_blocks_genes_composition_and_hub(tama_dir: tuple[Path, pl.DataFrame]) -> None:
    root, bed = tama_dir
    tx = execute_recipe("tama/transcripts.py", root, extra_sources={"bed": bed})
    blocks = execute_recipe(
        "tama/transcript_blocks.py", root, extra_sources={"transcripts": tx, "bed": bed}
    )
    reference = blocks.filter(pl.col("sample") == "reference")
    # Reference lanes for the genes the run found (gA, and gB through the
    # antisense isoform), never for an intergenic isoform.
    assert set(reference["transcript_id"]) == {"tA1", "tA2", "tB1"}
    assert set(reference["transcript_class"]) == {"reference"}
    assert blocks.filter(pl.col("transcript_id") == "G1.1")["expression"].to_list() == [7.0] * 3

    genes = execute_recipe("tama/genes.py", root, extra_sources={"transcripts": tx})
    ga = genes.filter(pl.col("gene_id") == "gA").to_dicts()[0]
    assert ga["isoforms"] == 5
    assert ga["novel_isoforms"] == 2
    assert ga["gene_status"] == "annotated"
    assert ga["top_category"] == "FSM"
    assert genes.filter(pl.col("gene_id") == "S:G3")["gene_status"].item() == "novel"

    comp = execute_recipe("tama/category_composition.py", root, extra_sources={"transcripts": tx})
    assert comp.group_by("level").agg(pl.col("pct").sum())["pct"].to_list() == pytest.approx(
        [100.0, 100.0]
    )

    # A run started from mapping has no CCS / refine reports: the hub keeps the
    # sample with null funnel columns rather than failing.
    hub = execute_recipe("nf-core/isoseq/samples.py", root, extra_sources={"transcripts": tx})
    row = hub.to_dicts()[0]
    assert row["sample"] == "S"
    assert row["isoforms"] == len(QUERIES)
    assert row["zmw_input"] is None and row["flnc_pct"] is None
    assert row["collapsed_reads"] == 13

    design = pl.DataFrame({"sample": ["S"], "tissue": ["T1"]})
    with_design = execute_recipe(
        "nf-core/isoseq/samples.py", root, extra_sources={"transcripts": tx, "metadata": design}
    )
    assert with_design["tissue"].to_list() == ["T1"]
    # The factors open the summary table, right after the sample.
    assert with_design.columns[:3] == ["sample", "tissue", "libraries"]
