"""nf-core/pairgenomealign recipes on small synthetic outputs.

The template reads the per-pair summaries LAST writes next to each alignment
(``<target>___<query>.o2o.tsv``, ``.o2o.matrix.txt``, ``.train.tsv``), the
optional PSL export, the assembly-scan JSON and the ``seqtk cutN`` BEDs. These
tests pin the keys the dashboard joins on (the query split off the pair id, the
genome off the file name), the matrix summary, empty gap BEDs and the hub.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe

T = "T1_target"
PAIRS = {"Q1": f"{T}___Q1", "Q2": f"{T}___Q2"}

MATRIX = """# format: matrix
# blocks: 10
# columns_analyzed: 1000
# P_acgt: 0.1
# JC69_acgt: 0.11
# F81_acgt: 0.11
# K80_acgt: 0.12
# T92_acgt: 0.13
\tA\tC\tG\tT\tN\t-
A\t200\t5\t20\t5\t0\t10
C\t5\t200\t5\t20\t0\t10
G\t20\t5\t200\t5\t0\t10
T\t5\t20\t5\t200\t0\t10
N\t0\t0\t0\t0\t0\t0
-\t4\t4\t4\t4\t0\t0
"""

ASSEMBLY_JSON = """{
    "sample": "genome.fna.gz",
    "total_contig": 12,
    "total_contig_length": 5000,
    "n50_contig_length": 900,
    "contig_percent_c": "20.50",
    "contig_percent_g": "21.00",
    "contig_percent_n": "0.10"
}
"""


def _psl_line(t_name: str, t_start: int, t_end: int, q_name: str, matches: int, strand: str) -> str:
    fields = [matches, 10, 0, 0, 0, 0, 0, 0, strand, q_name, 10000, 100, 100 + t_end - t_start,
              t_name, 20000, t_start, t_end, 1, f"{t_end - t_start},", "100,", f"{t_start},"]  # fmt: skip
    return "\t".join(str(f) for f in fields)


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    aln = tmp_path / "alignment"
    aln.mkdir()
    header = "Sample\tTotalAlignmentLength\tPercentIdentity\tPercentIdentityNoGaps\tTargetSequences\tTargetLength\tQuerySequences\tQueryLength\n"
    for i, pair in enumerate(PAIRS.values(), 1):
        (aln / f"{pair}.o2o.tsv").write_text(
            header + f"{pair}\t{500 * i}\t{90 - i}\t{95 - i}\t2\t1000\t3\t2000\n"
        )
        (aln / f"{pair}.o2o.matrix.txt").write_text(MATRIX)
        (aln / f"{pair}.train.tsv").write_text(
            "id\tsubstitution_percent_identity\tlast -t\tlast -a\tlast -A\tlast -b\tlast -B\tlast -S\n"
            f"{pair}.train\t{80 + i}\t4.3\t26\t26\t1\t1\t1\n"
        )
    lines = [
        _psl_line("chr1", 0, 400, "chr1", 300, "+"),
        _psl_line("chr2", 100, 150, "s9", 40, "-"),
    ]
    with gzip.open(aln / f"{PAIRS['Q1']}.psl.gz", "wt") as fh:
        fh.write("\n".join(lines) + "\n")
    (tmp_path / "assemblyscan").mkdir()
    (tmp_path / "assemblyscan" / "Q1.json").write_text(ASSEMBLY_JSON)
    (tmp_path / "cutn").mkdir()
    (tmp_path / "cutn" / "Q1.bed").write_text("s1\t10\t110\ns1\t500\t600\ns2\t0\t10000\n")
    (tmp_path / "cutn" / "Q2.bed").write_text("")  # a gap-free assembly
    return tmp_path


def test_identity_splits_the_pair_id_and_derives_coverage(run_dir: Path) -> None:
    df = execute_recipe("last/split_identity.py", run_dir)
    assert df["query"].to_list() == ["Q1", "Q2"]
    assert df["target"].unique().to_list() == [T]
    row = df.row(0, named=True)
    assert row["target_aligned_pct"] == pytest.approx(50.0)
    assert row["query_aligned_pct"] == pytest.approx(25.0)


def test_matrix_summarises_substitutions_and_spectrum(run_dir: Path) -> None:
    row = execute_recipe("last/split_matrix.py", run_dir).row(0, named=True)
    assert row["query"] == "Q1" and row["blocks"] == 10 and row["k80_distance"] == 0.12
    assert row["identical_columns"] == 800
    assert row["transitions"] == 80 and row["transversions"] == 40
    assert row["ts_tv_ratio"] == pytest.approx(2.0)
    assert row["query_gap_columns"] == 40 and row["target_gap_columns"] == 16
    spectrum = [v for k, v in row.items() if k.endswith("_pct")]
    assert sum(spectrum) == pytest.approx(100.0, abs=0.01)  # each share is rounded


def test_train_params_drop_the_train_suffix(run_dir: Path) -> None:
    df = execute_recipe("last/train_params.py", run_dir)
    assert df["query"].to_list() == ["Q1", "Q2"]
    assert df["deletion_open_cost"].to_list() == [26, 26]


def test_synteny_links_prefix_query_names_and_class_orientation(run_dir: Path) -> None:
    df = execute_recipe("last/synteny_links.py", run_dir)
    assert df["query"].unique().to_list() == ["Q1"]
    assert df["chrom_b"].to_list() == ["q:chr1", "q:s9"]
    assert df["category"].to_list() == ["same strand", "inverted"]
    assert df["pos_a"].to_list() == [200, 125]
    assert df["rank"].to_list() == [1, 2]


def test_assembly_stats_parse_the_pretty_json(run_dir: Path) -> None:
    row = execute_recipe("assemblyscan/stats.py", run_dir).row(0, named=True)
    assert row["genome"] == "Q1" and row["contigs"] == 12 and row["n50"] == 900
    assert row["gc_pct"] == pytest.approx(41.5)
    assert row["l50"] is None  # absent key reads as null


def test_gap_recipes_skip_an_empty_bed(run_dir: Path) -> None:
    gaps = execute_recipe("seqtk/cutn_gaps.py", run_dir)
    assert gaps.to_dicts() == [
        {"genome": "Q1", "gaps": 3, "gap_bp": 10200, "sequences_with_gaps": 2,
         "median_gap_bp": 100.0, "max_gap_bp": 10000}
    ]  # fmt: skip
    lengths = execute_recipe("seqtk/cutn_gap_lengths.py", run_dir)
    assert lengths["gaps"].sum() == 3
    assert set(lengths["gap_length_bp"].to_list()) == {100, 10000}


def test_hub_fills_gap_free_genomes_and_joins_the_design(run_dir: Path) -> None:
    module = load_recipe("nf-core/pairgenomealign/genomes.py")
    frames = {
        "last_split_identity": execute_recipe("last/split_identity.py", run_dir),
        "last_split_matrix": execute_recipe("last/split_matrix.py", run_dir),
        "assemblyscan_stats": execute_recipe("assemblyscan/stats.py", run_dir),
        "seqtk_cutn_gaps": execute_recipe("seqtk/cutn_gaps.py", run_dir),
        "metadata": pl.DataFrame({"sample": ["Q1", "Q2"], "clade": ["a", "b"]}),
    }
    hub = module.transform({s.ref: frames.get(s.dc_ref) for s in module.SOURCES})
    assert hub["genome"].to_list() == ["Q1", "Q2"]
    assert hub["gaps"].to_list() == [3, 0]
    assert hub["clade"].to_list() == ["a", "b"]
    assert hub["n50"].to_list() == [900, None]

    bare = module.transform(
        {s.ref: (frames[s.dc_ref] if s.ref == "identity" else None) for s in module.SOURCES}
    )
    assert bare.columns == list(module.EXPECTED_SCHEMA)
    assert bare["gaps"].null_count() == 2
