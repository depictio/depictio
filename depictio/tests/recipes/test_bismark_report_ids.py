"""One library, one id, on every Bismark report and on every route.

``--skip_trimming`` drops the ``_val_1`` token and ``--skip_deduplication`` the
``.deduplicated`` one from the file names. Every bismark recipe must strip what
is there and keep what is not, so the alignment, deduplication, splitting and
M-bias reports of one library agree on its id and the cross-DC ``sample`` links
resolve. The M-bias parser is shared, so its two series labels are pinned too.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

_ALIGN = (
    "Sequence pairs analysed in total:\t1000\n"
    "Number of paired-end alignments with a unique best hit:\t800\n"
    "Mapping efficiency:\t80.0 %\n"
    "Sequence pairs with no alignments under any condition:\t150\n"
    "Sequence pairs did not map uniquely:\t50\n"
)
_DEDUP = (
    "Total number of alignments analysed in x.bam:\t800\n"
    "Total number duplicated alignments removed:\t80 (10.00%)\n"
    "Total count of deduplicated leftover sequences: 720\n"
)
_SPLIT = "".join(
    f"Total methylated C's in {c} context:\t100\n"
    f"Total C to T conversions in {c} context:\t50\n"
    f"C methylated in {c} context:\t66.7%\n"
    for c in ("CpG", "CHG", "CHH")
)
_MBIAS = "".join(
    f"{c} context ({r})\n"
    "================\n"
    "position\tcount methylated\tcount unmethylated\t% methylation\tcoverage\n"
    "1\t10\t90\t10.0\t100\n"
    "2\t20\t80\t20.0\t100\n\n"
    for c in ("CpG", "CHG", "CHH")
    for r in ("R1", "R2")
)


def _lines(reports: dict[str, str]) -> pl.DataFrame:
    """The raw line scan: one row per line, tagged with the file it came from."""
    paths: list[str] = []
    lines: list[str] = []
    for path, text in reports.items():
        for line in text.splitlines():
            paths.append(path)
            lines.append(line)
    return pl.DataFrame({"source_path": paths, "line": lines})


def test_alignment_ids_agree_with_and_without_trimming(tmp_path: Path) -> None:
    out = execute_recipe(
        "bismark/alignment_summary.py",
        tmp_path,
        extra_sources={
            "lines": _lines(
                {
                    "a/SRR1_1_bismark_bt2_PE_report.txt": _ALIGN,
                    "a/SRR2_1_val_1_bismark_hisat2_PE_report.txt": _ALIGN,
                    "a/SRR3_bismark_bt2_SE_report.txt": _ALIGN,
                }
            )
        },
    )
    assert out["sample"].to_list() == ["SRR1", "SRR2", "SRR3"]
    assert out["mapping_efficiency_pct"].to_list() == [80.0] * 3


def test_deduplication_ids_agree_with_and_without_trimming(tmp_path: Path) -> None:
    out = execute_recipe(
        "bismark/deduplication_summary.py",
        tmp_path,
        extra_sources={
            "lines": _lines(
                {
                    "a/SRR1_1_bismark_bt2_pe.deduplication_report.txt": _DEDUP,
                    "a/SRR2_1_val_1_bismark_bt2_pe.deduplication_report.txt": _DEDUP,
                }
            )
        },
    )
    assert out["sample"].to_list() == ["SRR1", "SRR2"]


def test_splitting_report_ids_survive_skip_deduplication(tmp_path: Path) -> None:
    out = execute_recipe(
        "bismark/methylation_context_summary.py",
        tmp_path,
        extra_sources={
            "lines": _lines(
                {
                    "a/SRR1_1_bismark_bt2_pe_splitting_report.txt": _SPLIT,
                    "a/SRR2_1_val_1_bismark_bt2_pe.deduplicated_splitting_report.txt": _SPLIT,
                }
            )
        },
    )
    assert out["sample"].unique().sort().to_list() == ["SRR1", "SRR2"]
    assert out.height == 6


def test_mbias_ids_and_series_on_both_recipes(tmp_path: Path) -> None:
    lines = _lines(
        {
            "a/SRR1_1_bismark_bt2_pe.M-bias.txt": _MBIAS,
            "a/SRR2_1_val_1_bismark_bt2_pe.deduplicated.M-bias.txt": _MBIAS,
        }
    )
    cpg = execute_recipe("bismark/mbias_curve.py", tmp_path, extra_sources={"lines": lines})
    assert cpg["sample"].unique().sort().to_list() == ["SRR1", "SRR2"]
    assert cpg["series"].unique().sort().to_list() == ["SRR1 R1", "SRR1 R2", "SRR2 R1", "SRR2 R2"]
    assert cpg.height == 2 * 2 * 2  # samples x reads x positions, CpG only

    every = execute_recipe(
        "bismark/mbias_all_contexts.py", tmp_path, extra_sources={"lines": lines}
    )
    assert every["context"].unique().sort().to_list() == ["CHG", "CHH", "CpG"]
    assert "SRR1 CHH R2" in every["series"].to_list()
    assert every.height == 2 * 3 * 2 * 2


def test_summary_report_strips_untrimmed_bam_names(tmp_path: Path) -> None:
    header = [
        "File",
        "Total Reads",
        "Aligned Reads",
        "Unaligned Reads",
        "Ambiguously Aligned Reads",
        "Duplicate Reads (removed)",
        "Unique Reads (remaining)",
        "Total Cs",
        "Methylated CpGs",
        "Unmethylated CpGs",
        "Methylated chgs",
        "Unmethylated chgs",
        "Methylated CHHs",
        "Unmethylated CHHs",
    ]
    counts = [
        "1000",
        "800",
        "150",
        "50",
        "80",
        "720",
        "5000",
        "300",
        "200",
        "10",
        "990",
        "5",
        "995",
    ]
    (tmp_path / "bismark_summary_report.txt").write_text(
        "\t".join(header)
        + "\n"
        + "\t".join(["SRR1_1_bismark_bt2_pe.bam", *counts])
        + "\n"
        + "\t".join(["SRR2_1_val_1_bismark_bt2_pe.bam", *counts])
        + "\n"
    )
    out = execute_recipe("bismark/summary_report.py", tmp_path)
    assert out["sample"].sort().to_list() == ["SRR1", "SRR2"]
