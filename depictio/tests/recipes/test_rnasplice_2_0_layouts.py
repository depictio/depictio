"""nf-core/rnasplice 2.0.0 renamed its splicing tables and turned two signs around.

- DEXSeq (exon usage and DTU): ``DEXSeqResults.<contrast>.csv|tsv`` became
  ``<contrast>.dexseq.results.tsv`` (``perGeneQValue`` → ``.dexseq.gene_qvalues``),
  and the exon tables became tab-separated. The fold column still names its
  ratio (``log2fold_<A>_<B>``), which 2.0 turned to treatment over control.
- SUPPA2: ``<contrast>_local_diffsplice.dpsi`` became ``local_<contrast>.dpsi``,
  and the control now comes first in SUPPA's header (treatment minus control).
- rMATS: ``<contrast>/rmats_post/`` became ``rmats/<contrast>[_paired]/``.

Every recipe must give the same contrast name and the same treatment-minus-
control sign on both layouts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.recipes import execute_recipe


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# Treatment T is up against control C in contrast T-C.
_BINS_HEADER = "groupID\tfeatureID\texonBaseMean\tpvalue\tpadj\tC\tT\t{fold}\n"


def _dexseq_exon(root: Path, layout: str) -> None:
    if layout == "1.x":
        # 1.x: CSV, the fold column is control over treatment.
        _write(
            root,
            "star_salmon/dexseq_exon/results/DEXSeqResults.T-C.csv",
            "groupID,featureID,exonBaseMean,pvalue,padj,C,T,log2fold_C_T\nG1,E001,10,0.0001,0.001,1,2,-1.5\n",
        )
        _write(
            root,
            "star_salmon/dexseq_exon/results/perGeneQValue.T-C.csv",
            "groupID,padj\nG1,0.002\n",
        )
    else:
        # 2.0: TSV, the fold column is treatment over control.
        _write(
            root,
            "star_salmon/dexseq_exon/results/T-C.dexseq.results.tsv",
            _BINS_HEADER.format(fold="log2fold_T_C") + "G1\tE001\t10\t0.0001\t0.001\t1\t2\t1.5\n",
        )
        _write(
            root,
            "star_salmon/dexseq_exon/results/T-C.dexseq.gene_qvalues.tsv",
            "groupID\tpadj\nG1\t0.002\n",
        )
        # The DTU tables share the names: they must not be read as exon bins.
        _write(
            root,
            "star_salmon/dexseq_dtu/results/dexseq/T-C.dexseq.results.tsv",
            _BINS_HEADER.format(fold="log2fold_T_C") + "G9\tTX9\t10\t0.4\t0.5\t1\t1\t0.1\n",
        )


@pytest.mark.parametrize("layout", ["1.x", "2.0"])
def test_dexseq_exon_reads_both_layouts_treatment_over_control(tmp_path: Path, layout) -> None:
    _dexseq_exon(tmp_path, layout)

    df = execute_recipe("dexseq/exon_genes.py", tmp_path)

    assert df["contrast"].to_list() == ["T-C"]
    assert df["gene_id"].to_list() == ["G1"]
    assert df["log2fc"].to_list() == [1.5]
    assert df["direction"].to_list() == ["up"]


def test_dexseq_dtu_names_the_contrast_of_a_2_0_table(tmp_path: Path) -> None:
    base = "star_salmon/dexseq_dtu/results/dexseq/"
    _write(
        tmp_path,
        base + "T-C.dexseq.results.tsv",
        _BINS_HEADER.format(fold="log2fold_T_C") + "G1\tTX1\t10\t0.0001\t0.001\t1\t2\t1.5\n",
    )
    _write(tmp_path, base + "T-C.dexseq.gene_qvalues.tsv", "groupID\tpadj\nG1\t0.002\n")

    df = execute_recipe(
        "dexseq/dtu.py",
        tmp_path,
        overrides={
            "transcripts": "star_salmon/dexseq_dtu/**/*.dexseq.results.tsv",
            "genes": "star_salmon/dexseq_dtu/**/*.dexseq.gene_qvalues.tsv",
        },
    )

    assert df["contrast"].unique().to_list() == ["T-C"]
    assert df["log2fc"].to_list() == [1.5]


_EVENT = "G1;SE:chr1:100-200:300-400:+"


@pytest.mark.parametrize(
    ("rel", "header", "raw"),
    [
        # 1.x: treatment first in the header, SUPPA's second minus first is C - T.
        ("salmon/suppa/diffsplice/per_local_event/T-C_local_diffsplice.dpsi", "T-C", -0.4),
        # 2.0: control first, so already T - C.
        ("salmon/suppa/diffsplice/per_local_event/local_T-C.dpsi", "local_C-local_T", 0.4),
    ],
)
def test_suppa_sign_follows_the_header(tmp_path: Path, rel, header, raw) -> None:
    _write(tmp_path, rel, f"{header}_dPSI\t{header}_p-val\n{_EVENT}\t{raw}\t0.001\n")

    df = execute_recipe(
        "suppa/local_events.py",
        tmp_path,
        overrides={"events": "salmon/**/*.dpsi"},
    )

    assert df["contrast"].to_list() == ["T-C"]
    assert df["dpsi"].to_list() == [pytest.approx(0.4)]
    assert df["direction"].to_list() == ["up"]


_RMATS = (
    "ID\tGeneID\tgeneSymbol\tchr\tstrand\texonStart_0base\texonEnd\tupstreamES\tupstreamEE\t"
    "downstreamES\tdownstreamEE\tID\tIJC_SAMPLE_1\tSJC_SAMPLE_1\tIJC_SAMPLE_2\tSJC_SAMPLE_2\t"
    "IncFormLen\tSkipFormLen\tPValue\tFDR\tIncLevel1\tIncLevel2\tIncLevelDifference\n"
    '1\t"G1"\t"GENE1"\tchr1\t+\t100\t200\t50\t60\t300\t400\t1\t40,40\t2,2\t3,3\t40,40\t'
    "129\t39\t0.0001\t0.001\t0.9,0.9\t0.1,0.1\t0.8\n"
)


@pytest.mark.parametrize(
    "rel",
    [
        "star_salmon/rmats/T-C/rmats_post/SE.MATS.JCEC.txt",
        "star_salmon/rmats/T-C_paired/SE.MATS.JCEC.txt",
    ],
)
def test_rmats_contrast_drops_the_paired_suffix(tmp_path: Path, rel) -> None:
    _write(tmp_path, rel, _RMATS)

    df = execute_recipe("rmats/events.py", tmp_path)

    assert df["contrast"].unique().to_list() == ["T-C"]


def test_samples_hub_reads_a_raw_input_sheet(tmp_path: Path) -> None:
    """2.0 publishes no validated sheet: the --input one has no single_end and
    repeats a sample per sequencing run."""
    _write(
        tmp_path,
        "input/samplesheet.csv",
        "sample,fastq_1,fastq_2,strandedness,condition\n"
        "S1,a_1.fq.gz,a_2.fq.gz,reverse,T\n"
        "S1,b_1.fq.gz,b_2.fq.gz,reverse,T\n"
        "S2,c_1.fq.gz,,reverse,C\n",
    )

    df = execute_recipe(
        "nf-core/rnasplice/samples.py",
        tmp_path,
        overrides={"sheet": str(tmp_path / "input/samplesheet.csv")},
        extra_sources={},
    )

    assert df["sample"].to_list() == ["S1", "S2"]
    assert df["read_type"].to_list() == ["paired-end", "single-end"]
    assert df["runs"].to_list()[0] == 2
