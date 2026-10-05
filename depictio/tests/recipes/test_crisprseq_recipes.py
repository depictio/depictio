"""nf-core/crisprseq (targeted) recipes on small synthetic CIGAR-parser outputs.

Two libraries edited with one guide, a third with another. The tests pin what
the dashboards read: the sample id taken from the file name, the classified-read
denominator shared by the rates and the allele shares, deletion coverage
expanded over the deleted bases, the dominant base as the substitution
reference, and the per-guide means where a library without an indel counts as
zero.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

SHEET = (
    "sample,fastq_1,fastq_2,reference,protospacer,template\n"
    "L1,L1.fq.gz,,ACGTACGTAC,gggtttaaaccc,\n"
    "L2,L2.fq.gz,,ACGTACGTAC,GGGTTTAAACCC,\n"
    "L3,L3.fq.gz,,ACGTACGTACGT,CCCAAATTTGGG,TTTT\n"
)

READS_HEADER = (
    '"","Raw reads","Merged reads","Quality filtered reads","Clustered reads","Aligned reads"'
)
EDITS_HEADER = (
    '"","Wt","Template-based","Delins","Ins_inframe","Ins_outframe","Dels_inframe","Dels_outframe"'
)
QC_HEADER = (
    '"","Wt passing filter","Wt NOT passing filter","Indels NOT passing filter",'
    '"Above error & in pick","NOT above error & in pick","NOT above error & NOT in pick",'
    '"Above error & NOT in pick"'
)
INDEL_HEADER = (
    '"","Modification","Start","Length","Ids","above_error_rate","in_pick","freq","Perc",'
    '"patterns","pre_ins_nt","ins_nt","post_ins_nt","sample","cut_site","aligned_reads",'
    '"wt_reads","t_reads"'
)


def _indel(i: int, sample: str, mod: str, start: int, length: int, pick: str = "TRUE") -> str:
    return (
        f'"{i}","{mod}",{start},{length},"{sample}.{i}",TRUE,{pick},1,1,"NHEJ",NA,NA,NA,'
        f'"{sample}",100," 10 (100%)",6,0'
    )


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.csv").write_text(SHEET)
    cigar = tmp_path / "cigar"
    cigar.mkdir()
    clon = tmp_path / "clonality"
    clon.mkdir()
    # L1: 10 classified reads, 6 WT, 3 frameshift deletions, 1 in-frame insertion.
    # L2: 10 classified reads, all WT. L3: 20 reads, 10 WT, 10 frameshift deletions.
    edits = {
        "L1": (6, 0, 0, 1, 0, 0, 3),
        "L2": (10, 0, 0, 0, 0, 0, 0),
        "L3": (10, 0, 0, 0, 0, 0, 10),
    }
    for s, counts in edits.items():
        (cigar / f"{s}_edits.csv").write_text(
            EDITS_HEADER + "\n" + f'"{s}",' + ",".join(map(str, counts)) + "\n"
        )
        (cigar / f"{s}_reads-summary.csv").write_text(
            READS_HEADER + "\n" + f'"{s}","20","0.0","100.0"," 20","50.0"\n'
        )
        (cigar / f"{s}_QC-indels.csv").write_text(QC_HEADER + "\n" + f'"{s}",6,0,2,3,1,0,0\n')
        (cigar / f"{s}_cutSite.json").write_text("[100]\n")
        (clon / f"{s}_edits_classified.csv").write_text(
            ",Sample,Wt,Classification,clonality,Class_Conf,Total Reads,% Wt,% Outframe\n"
            f"0,{s},6,Het NHEJ,Clonal,0.9,10,60.0,30.0\n"
        )
    (cigar / "L1_indels.csv").write_text(
        "\n".join(
            [
                INDEL_HEADER,
                _indel(1, "L1", "del", 99, 2),
                _indel(2, "L1", "del", 99, 2),
                _indel(3, "L1", "del", 99, 2),
                _indel(4, "L1", "ins", 101, 3, pick="FALSE"),
            ]
        )
        + "\n"
    )
    (cigar / "L3_indels.csv").write_text(
        "\n".join([INDEL_HEADER, *[_indel(i, "L3", "del", 100, 1) for i in range(10)]]).replace(
            ",6,0", ",10,0"
        )
        + "\n"
    )
    subs = '"","pos","percentage","nucleotide"\n'
    for s in edits:
        subs_rows = ['"1",99,100,"A"', '"2",100,90,"C"', '"3",100,6,"T"', '"4",100,4,"-"']
        if s == "L1":
            subs_rows.append('"5",101,100,"-"')
        (cigar / f"{s}_subs-perc.csv").write_text(subs + "\n".join(subs_rows) + "\n")
    return tmp_path


def test_samples_guide_and_template(run_dir: Path) -> None:
    out = execute_recipe("nf-core/crisprseq/samples.py", run_dir)
    assert out["sample"].to_list() == ["L1", "L2", "L3"]
    assert out["guide"].to_list() == ["GGGTTTAAACCC", "GGGTTTAAACCC", "CCCAAATTTGGG"]
    assert out["has_template"].to_list() == ["no", "no", "yes"]
    assert out["amplicon_length"].to_list() == [10, 10, 12]
    assert "reference" not in out.columns and "fastq_1" not in out.columns


def test_edit_summary_rates(run_dir: Path) -> None:
    out = execute_recipe("crisprseq/edit_summary.py", run_dir)
    l1 = out.filter(pl.col("sample") == "L1").row(0, named=True)
    assert l1["classified_reads"] == 10
    assert l1["edited_pct"] == pytest.approx(40.0)
    assert l1["frameshift_pct"] == pytest.approx(30.0)
    assert l1["frameshift_of_indels_pct"] == pytest.approx(75.0)
    assert l1["clustered_reads"] == 20 and l1["aligned_pct"] == pytest.approx(50.0)
    assert l1["indels_failing_filter"] == 2
    l2 = out.filter(pl.col("sample") == "L2").row(0, named=True)
    assert l2["frameshift_of_indels_pct"] is None


def test_outcomes_sum_to_hundred(run_dir: Path) -> None:
    out = execute_recipe("crisprseq/edit_outcomes.py", run_dir)
    totals = out.group_by("sample").agg(pl.col("pct").sum())["pct"].to_list()
    assert totals == [pytest.approx(100.0)] * 3
    assert out.filter(pl.col("sample") == "L1").height == 7


def test_indels_and_profiles(run_dir: Path) -> None:
    indels = execute_recipe("crisprseq/indels.py", run_dir)
    top = indels.filter((pl.col("sample") == "L1") & (pl.col("rank") == 1)).row(0, named=True)
    assert (top["indel_type"], top["size"], top["offset"], top["reads"]) == ("Deletion", -2, -1, 3)
    # 3 of L1's 10 classified reads (6 WT + 4 indel reads).
    assert top["pct_reads"] == pytest.approx(30.0)
    assert top["allele"] == "Deletion 2 bp at -1"
    ins = indels.filter((pl.col("sample") == "L1") & (pl.col("indel_type") == "Insertion"))
    assert ins["peak"].item() == "Outside the main peak"
    assert ins["frame"].item() == "In-frame"

    sizes = execute_recipe("crisprseq/indel_sizes.py", run_dir, extra_sources={"indels": indels})
    assert dict(
        zip(*sizes.filter(pl.col("sample") == "L1")[["size", "pct_reads"]], strict=True)
    ) == {
        -2: pytest.approx(30.0),
        3: pytest.approx(10.0),
    }

    prof = execute_recipe(
        "crisprseq/cut_site_profile.py", run_dir, extra_sources={"indels": indels}
    )
    l1 = prof.filter(pl.col("sample") == "L1").sort("offset")
    # The 2 bp deletion at offset -1 covers -1 and 0; the insertion sits at +1.
    assert l1["offset"].to_list() == [-1, 0, 1]
    assert l1["deletion_pct"].to_list() == [pytest.approx(30.0), pytest.approx(30.0), 0.0]
    assert l1["insertion_pct"].to_list() == [0.0, 0.0, pytest.approx(10.0)]


def test_substitutions_reference_and_gap(run_dir: Path) -> None:
    out = execute_recipe("crisprseq/substitutions.py", run_dir)
    at_cut = out.filter((pl.col("sample") == "L1") & (pl.col("offset") == 0)).row(0, named=True)
    assert at_cut["reference_nt"] == "C"
    assert at_cut["substitution_pct"] == pytest.approx(6.0)
    assert at_cut["gap_pct"] == pytest.approx(4.0)


def test_samples_without_reference_column(tmp_path: Path) -> None:
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.csv").write_text(
        "sample,protospacer,template\nL1,GGG,\nL2,CCC,TTTT\n"
    )
    out = execute_recipe("nf-core/crisprseq/samples.py", tmp_path)
    assert "amplicon_length" not in out.columns
    assert out["has_template"].to_list() == ["no", "yes"]


def test_guide_tables(run_dir: Path) -> None:
    samples = execute_recipe("nf-core/crisprseq/samples.py", run_dir)
    summary = execute_recipe("crisprseq/edit_summary.py", run_dir)
    outcomes = execute_recipe("crisprseq/edit_outcomes.py", run_dir)
    indels = execute_recipe("crisprseq/indels.py", run_dir)
    clon = execute_recipe("crisprseq/clonality.py", run_dir)
    extra = {
        "samples": samples,
        "summary": summary,
        "outcomes": outcomes,
        "indels": indels,
        "clonality": clon,
    }
    guides = execute_recipe("nf-core/crisprseq/guide_summary.py", run_dir, extra_sources=extra)
    g1 = guides.filter(pl.col("guide") == "GGGTTTAAACCC").row(0, named=True)
    assert g1["libraries"] == 2
    assert g1["median_edited_pct"] == pytest.approx(20.0)
    assert g1["dominant_indel_size"] == -2
    assert g1["classification_mix"] == "Het NHEJ 2"
    assert g1["edit_class"] == "Moderate editing"
    assert guides.columns[:3] == ["guide", "edit_class", "libraries"]

    gsizes = execute_recipe("nf-core/crisprseq/guide_indel_sizes.py", run_dir, extra_sources=extra)
    g1_sizes = gsizes.filter(pl.col("guide") == "GGGTTTAAACCC")
    # L1 has 30% at -2, L2 has no indel (zero): median 15, quartiles 7.5 and 22.5.
    at = g1_sizes.filter(pl.col("size") == -2).row(0, named=True)
    assert at["median_pct_reads"] == pytest.approx(15.0)
    assert (at["q1_pct_reads"], at["q3_pct_reads"]) == (pytest.approx(7.5), pytest.approx(22.5))
    assert at["libraries_with_signal"] == 1
    assert g1_sizes["size"].to_list() == list(range(-2, 4))

    gprof = execute_recipe(
        "nf-core/crisprseq/guide_cut_site_profile.py", run_dir, extra_sources=extra
    )
    g1_prof = gprof.filter(pl.col("guide") == "GGGTTTAAACCC")
    assert g1_prof.height == 201
    assert g1_prof.filter(pl.col("offset") == 0)["median_deletion_pct"].item() == pytest.approx(
        15.0
    )

    galleles = execute_recipe("nf-core/crisprseq/guide_alleles.py", run_dir, extra_sources=extra)
    top = galleles.filter((pl.col("guide") == "GGGTTTAAACCC") & (pl.col("rank") == 1))
    top = top.row(0, named=True)
    # 3 reads of the 20 classified reads of L1 and L2 pooled.
    assert (top["allele"], top["libraries"], top["reads"]) == ("Deletion 2 bp at -1", 1, 3)
    assert top["pct_reads"] == pytest.approx(15.0)

    gout = execute_recipe("nf-core/crisprseq/guide_outcomes.py", run_dir, extra_sources=extra)
    wt = gout.filter((pl.col("guide") == "GGGTTTAAACCC") & (pl.col("outcome") == "Wild type"))
    assert wt["pct"].item() == pytest.approx(80.0)

    gsubprof = execute_recipe(
        "nf-core/crisprseq/guide_substitution_profile.py", run_dir, extra_sources=extra
    )
    # Named apart from ``guide`` so a guide picker on the profile narrows nothing else.
    assert "guide" not in gsubprof.columns
    g1_sub = gsubprof.filter(pl.col("profile_guide") == "GGGTTTAAACCC")
    at_cut = g1_sub.filter(pl.col("offset") == 0).row(0, named=True)
    assert at_cut["mean_substitution_pct"] == pytest.approx(6.0)
    assert at_cut["median_substitution_pct"] == pytest.approx(6.0)
    assert at_cut["mean_gap_pct"] == pytest.approx(4.0)
    assert at_cut["libraries"] == 2
    # L1 alone reaches offset +1 (its amplicon edge, a gap in every read): one of
    # the guide's two libraries is under the coverage floor, so the offset is left out.
    assert g1_sub["offset"].to_list() == [-1, 0]

    gsubs = execute_recipe(
        "nf-core/crisprseq/guide_substitutions.py",
        run_dir,
        extra_sources={"profile": gsubprof},
    )
    assert gsubs.filter(pl.col("guide") == "GGGTTTAAACCC")["0"].item() == pytest.approx(6.0)
    assert "-20" in gsubs.columns and "+20" in gsubs.columns
