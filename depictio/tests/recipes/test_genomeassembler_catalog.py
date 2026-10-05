"""The catalog outputs added for nf-core/genomeassembler: BUSCO, Merqury,
GenomeScope, jellyfish and QUAST's reference-based report."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe

GENOMESCOPE_V1 = """GenomeScope version 1.0
k = 21

property                      min               max
Heterozygosity                0.05%             0.06%
Genome Haploid Length         1,000,000 bp      1,100,000 bp
Genome Repeat Length          200,000 bp        220,000 bp
Genome Unique Length          800,000 bp        880,000 bp
Model Fit                     96.9%             98.5%
Read Error Rate               0.33%             0.33%
"""

GENOMESCOPE_V2 = """GenomeScope version 2.0
input file = reads.histo
p = 2
k = 31

property                      min               max
Homozygous (aa)               98.8%             98.9%
Heterozygous (ab)             1.1%              1.2%
Genome Haploid Length         NA bp             2,000,000 bp
Genome Repeat Length          500,000 bp        510,000 bp
Genome Unique Length          1,500,000 bp      1,490,000 bp
Model Fit                     90%               95%
Read Error Rate               0.2%              0.2%
"""


@pytest.mark.parametrize(
    ("path", "label"),
    [
        ("s1/QC/BUSCO/s1_assembly-lineage_odb10-busco.batch_summary.txt", "s1_assembly"),
        ("s1/QC/BUSCO/s1_links-lineage_odb10-busco.batch_summary.txt", "s1_links"),
        ("run/s1_ragtag-euk-busco/batch_summary.txt", "s1_ragtag"),
    ],
)
def test_busco_run_label(path: str, label: str) -> None:
    module = load_recipe("busco/batch_summary.py")
    assert module.run_label(path) == label


def test_merqury_error_trough_is_the_first_rise() -> None:
    module = load_recipe("merqury/copy_number_composition.py")
    assert module.error_trough([1, 2, 3, 4, 5], [900, 300, 50, 80, 400]) == 3
    # A histogram that never turns up drops only the singletons.
    assert module.error_trough([1, 2, 3], [9, 5, 1]) == 1


@pytest.mark.parametrize("text", [GENOMESCOPE_V1, GENOMESCOPE_V2])
def test_genomescope_parses_both_layouts(text: str) -> None:
    module = load_recipe("genomescope/summary.py")
    row = module.parse_summary("reads", text.splitlines())

    assert row["read_set"] == "reads"
    assert row["k"] in (21, 31)
    assert row["heterozygosity_max"] is not None
    assert row["haploid_length_max"] in (1_100_000, 2_000_000)
    assert row["repeat_fraction"] == pytest.approx(
        100.0 * row["repeat_length_max"] / row["haploid_length_max"]
    )
    if row["k"] == 31:
        assert row["ploidy"] == 2
        assert row["haploid_length_min"] is None
        assert row["heterozygosity_min"] == pytest.approx(1.1)


def test_genomescope_read_set_name() -> None:
    module = load_recipe("genomescope/summary.py")
    assert module.read_set_name("a/genomescope/reads_x_genomescope.txt") == "reads_x"
    assert module.read_set_name("a/reads_y/summary.txt") == "reads_y"


def test_jellyfish_main_peak_skips_the_error_slope() -> None:
    module = load_recipe("jellyfish/histogram.py")
    # The error k-mers at multiplicity 1 outnumber the peak at 5.
    assert module.main_peak([1, 2, 3, 4, 5, 6], [10000, 400, 100, 300, 900, 200]) == 5
    assert module.read_set_name("x/histo/reads_hist.tsv") == "reads"


def test_quast_reference_report_needs_a_reference() -> None:
    module = load_recipe("quast/reference_report.py")
    raw = pl.DataFrame(
        {
            "Assembly": ["s1_assembly"],
            "# contigs": ["3"],
            "N50": ["1000"],
            "source_path": ["s1/QC/QUAST/s1_assembly/transposed_report.tsv"],
        }
    )
    with pytest.raises(ValueError, match="declare this collection optional"):
        module.transform({"reports": raw})
