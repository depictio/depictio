"""The nf-core/hlatyping project recipes: the sample hub and the read QC.

The pipeline does not publish its samplesheet, so the hub reads the vendored or
user-given sheet and adds every sample OptiType typed. These tests pin the
derived columns the dashboard groups and filters by (sequencing type, input
format, read layout, runs), that a sample typed but missing from the sheet
still gets a row, and that the read QC attaches FastQC's read files to their
sample (longest hub id first) and joins OptiType's read support.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe

SHEET = (
    "sample,fastq_1,fastq_2,bam,seq_type\n"
    "DNA1,https://example.org/d1_R1.fastq.gz,https://example.org/d1_R2.fastq.gz,,dna\n"
    "DNA1_CAT,/data/a_1.part_001.fastq.gz,/data/a_2.part_001.fastq.gz,,dna\n"
    "DNA1_CAT,/data/a_1.part_002.fastq.gz,/data/a_2.part_002.fastq.gz,,dna\n"
    "RNA1,/data/r_1.fastq.gz,,,rna\n"
    "BAM1,,,/data/x.bam,DNA\n"
)

FASTQC = (
    "Sample\tFilename\tTotal Sequences\t%GC\ttotal_deduplicated_percentage\tavg_sequence_length"
    "\tbasic_statistics\tper_sequence_gc_content\tadapter_content\n"
    "DNA1_1\td1_R1.gz\t1000.0\t50.0\t90.0\t101.0\tpass\tfail\tpass\n"
    "DNA1_2\td1_R2.gz\t990.0\t51.0\t91.0\t101.0\tpass\twarn\tpass\n"
    "DNA1_CAT_1\ta_1.gz\t1000.0\t50.0\t90.0\t101.0\tpass\tpass\tpass\n"
    "DNA1_CAT_2\ta_2.gz\t1000.0\t50.0\t90.0\t101.0\tpass\tpass\tpass\n"
    "RNA1\tr_1.gz\t400.0\t60.0\t80.0\t75.0\tpass\tfail\twarn\n"
    "BAM1_1\tx_1.gz\t200.0\t52.0\t85.0\t100.0\tpass\tpass\tpass\n"
    "BAM1_2\tx_2.gz\t200.0\t52.0\t85.0\t100.0\tpass\tpass\tpass\n"
)

RESULT = "\tA1\tA2\tB1\tB2\tC1\tC2\tReads\tObjective\n0\tA*02:01\tA*11:01\tB*44:02\tB*07:02\tC*05:01\tC*07:02\t{reads}\t1.0\n"


def _typed(root: Path, sample: str, reads: float = 50.0) -> None:
    folder = root / "optitype" / sample
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sample}_result.tsv").write_text(RESULT.format(reads=reads))


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.csv").write_text(SHEET)
    for sample in ("DNA1", "DNA1_CAT", "RNA1", "BAM1"):
        _typed(tmp_path, sample)
    (tmp_path / "multiqc" / "multiqc_data").mkdir(parents=True)
    (tmp_path / "multiqc" / "multiqc_data" / "multiqc_fastqc.txt").write_text(FASTQC)
    return tmp_path


def test_samples_derive_the_design_columns(run_dir: Path) -> None:
    out = execute_recipe("nf-core/hlatyping/samples.py", run_dir)
    assert out.columns[:6] == [
        "sample",
        "seq_type",
        "input_format",
        "read_layout",
        "runs",
        "input_files",
    ]
    rows = {r["sample"]: r for r in out.iter_rows(named=True)}
    assert set(rows) == {"DNA1", "DNA1_CAT", "RNA1", "BAM1"}
    assert rows["DNA1"]["seq_type"] == "DNA"
    assert rows["DNA1"]["read_layout"] == "Paired-end"
    assert rows["DNA1"]["input_files"] == "d1_R1.fastq.gz, d1_R2.fastq.gz"
    assert rows["DNA1_CAT"]["runs"] == 2
    assert rows["RNA1"]["seq_type"] == "RNA"
    assert rows["RNA1"]["read_layout"] == "Single-end"
    assert rows["BAM1"]["input_format"] == "BAM"
    assert rows["BAM1"]["read_layout"] == "From BAM"
    assert rows["BAM1"]["seq_type"] == "DNA"


def test_a_typed_sample_missing_from_the_sheet_still_gets_a_row(run_dir: Path) -> None:
    _typed(run_dir, "EXTRA")
    out = execute_recipe("nf-core/hlatyping/samples.py", run_dir)
    extra = out.filter(pl.col("sample") == "EXTRA").row(0, named=True)
    assert extra["seq_type"] == "Not stated"
    assert extra["runs"] == 0


def test_samples_without_a_sheet_list_the_typed_samples(tmp_path: Path) -> None:
    _typed(tmp_path, "S1")
    _typed(tmp_path, "S2")
    out = execute_recipe("nf-core/hlatyping/samples.py", tmp_path)
    assert out["sample"].to_list() == ["S1", "S2"]
    assert set(out["seq_type"]) == {"Not stated"}


def test_samples_read_a_tab_separated_sheet(run_dir: Path) -> None:
    (run_dir / "input" / "samplesheet.csv").write_text(SHEET.replace(",", "\t"))
    out = execute_recipe("nf-core/hlatyping/samples.py", run_dir)
    assert out.height == 4
    assert set(out["seq_type"]) == {"DNA", "RNA"}


def _read_qc(run_dir: Path) -> pl.DataFrame:
    samples = execute_recipe("nf-core/hlatyping/samples.py", run_dir)
    summary = execute_recipe("optitype/summary.py", run_dir)
    return execute_recipe(
        "nf-core/hlatyping/read_qc.py",
        run_dir,
        extra_sources={"samples": samples, "typing": summary},
    )


def test_read_qc_attaches_read_files_to_the_longest_sample(run_dir: Path) -> None:
    out = _read_qc(run_dir)
    owner = dict(zip(out["read_key"], out["sample"], strict=True))
    read = dict(zip(out["read_key"], out["read"], strict=True))
    assert owner["DNA1_1"] == "DNA1"
    assert owner["DNA1_CAT_1"] == "DNA1_CAT"
    assert read["DNA1_CAT_2"] == "Read 2"
    assert (owner["RNA1"], read["RNA1"]) == ("RNA1", "Single-end")
    assert owner["BAM1_2"] == "BAM1"


def test_read_qc_reads_fastqc_status_and_the_typing_share(run_dir: Path) -> None:
    out = _read_qc(run_dir)
    rows = {r["read_key"]: r for r in out.iter_rows(named=True)}
    assert rows["DNA1_1"]["fastqc_status"] == "Fail"
    assert rows["DNA1_2"]["fastqc_status"] == "Warn"
    assert rows["DNA1_CAT_1"]["fastqc_status"] == "Pass"
    assert (rows["RNA1"]["fastqc_fail"], rows["RNA1"]["fastqc_warn"]) == (1, 1)
    assert rows["DNA1_1"]["pct_duplicates"] == pytest.approx(10.0)
    # 50 typing reads over the larger read file of the pair (1000 reads).
    assert rows["DNA1_2"]["typing_reads"] == 50
    assert rows["DNA1_2"]["typing_share"] == pytest.approx(0.05)
    assert rows["RNA1"]["typing_share"] == pytest.approx(0.125)
    # The hub's design columns travel with each read file.
    assert rows["RNA1"]["seq_type"] == "RNA"
    assert "input_files" not in out.columns


def test_read_qc_without_typing_keeps_the_fastqc_numbers(run_dir: Path) -> None:
    samples = execute_recipe("nf-core/hlatyping/samples.py", run_dir)
    out = execute_recipe(
        "nf-core/hlatyping/read_qc.py", run_dir, extra_sources={"samples": samples}
    )
    assert out.height == 7
    assert out["typing_reads"].null_count() == 7


def test_attach_keeps_an_unknown_name() -> None:
    attach = load_recipe("nf-core/hlatyping/read_qc.py").attach
    assert attach("OTHER_1", {"S1"}) == ("OTHER", "Read 1")
    assert attach("OTHER", {"S1"}) == ("OTHER", "Single-end")
