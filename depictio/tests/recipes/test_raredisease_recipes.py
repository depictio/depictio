"""raredisease's genome-track order, ranked-variant order and ranked genotypes.

The browser opens on the first ``initial_tracks`` rows of the manifest, so the proband's
alignment must come right after the research ranked VCF (every ranked variant, the clinical subset
included; the clinical VCF leads only when the run has no research one), then its coverage and its
parents' alignments. The Ranked tab's table reads ``ranked_variants`` in stored order, so that
collection comes out best first.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from depictio.recipes import execute_recipe, load_recipe

_PED = "fam1\tdad\t0\t0\t1\t1\nfam1\tmum\t0\t0\t2\t1\nfam1\tkid\tdad\tmum\t1\t2\n"


def _touch(root: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        index = rel + (
            ".tbi" if rel.endswith(".vcf.gz") else ".bai" if rel.endswith(".bam") else ""
        )
        for path in (rel, index) if index != rel else (rel,):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")


def _trio_files(root: Path) -> None:
    (root / "pedigree").mkdir()
    (root / "pedigree" / "fam1.ped").write_text(_PED, encoding="utf-8")
    _touch(
        root,
        "rank_and_filter/fam1_snv_ranked_clinical.vcf.gz",
        "rank_and_filter/fam1_snv_ranked_research.vcf.gz",
        "call_mobile_elements/fam1_mobile_elements.vcf.gz",
        "repeat_expansions/fam1_repeat_expansion_stranger.vcf.gz",
    )
    for sample in ("dad", "mum", "kid"):
        _touch(
            root,
            f"alignment/{sample}_sorted_md.bam",
            f"qc_bam/{sample}_tidditcov.bw",
            f"annotate_snv/genome/{sample}_rhocallviz/{sample}_rhocallviz.bw",
        )


def test_the_browser_opens_on_the_research_vcf_and_the_proband(tmp_path: Path) -> None:
    _trio_files(tmp_path)
    df = execute_recipe("nf-core/raredisease/tracks.py", tmp_path)
    ids = df["track_id"].to_list()
    assert ids[:3] == ["fam1.ranked_research", "kid.alignment", "kid.coverage"]
    assert df["order"].to_list() == list(range(1, len(ids) + 1))
    # Nothing is dropped by the reorder: 4 family VCFs and 3 tracks of each of 3 samples.
    assert len(ids) == len(set(ids)) == 4 + 3 * 3
    # The rest of the family follows the proband, so a call is read against its parents.
    assert ids[3:5] == ["dad.alignment", "mum.alignment"]
    # The clinical subset stays one menu entry away.
    assert "fam1.ranked_clinical" in ids[5:]


def test_the_parents_come_before_a_sibling(tmp_path: Path) -> None:
    (tmp_path / "pedigree").mkdir()
    # The unaffected sibling is listed before the parents.
    ped = (
        "fam1\tsib\tdad\tmum\t2\t1\n"
        "fam1\tdad\t0\t0\t1\t1\n"
        "fam1\tmum\t0\t0\t2\t1\n"
        "fam1\tkid\tdad\tmum\t1\t2\n"
    )
    (tmp_path / "pedigree" / "fam1.ped").write_text(ped, encoding="utf-8")
    _touch(tmp_path, "rank_and_filter/fam1_snv_ranked_clinical.vcf.gz")
    for sample in ("dad", "mum", "kid", "sib"):
        _touch(tmp_path, f"alignment/{sample}_sorted_md.bam", f"qc_bam/{sample}_tidditcov.bw")
    df = execute_recipe("nf-core/raredisease/tracks.py", tmp_path)
    assert df["track_id"].to_list()[:6] == [
        "fam1.ranked_clinical",
        "kid.alignment",
        "kid.coverage",
        "dad.alignment",
        "mum.alignment",
        "sib.alignment",
    ]


def test_the_proband_is_the_affected_child_not_an_affected_parent(tmp_path: Path) -> None:
    (tmp_path / "pedigree").mkdir()
    # The father is affected too, but the child is the one with declared parents.
    ped = "fam1\tdad\t0\t0\t1\t2\nfam1\tmum\t0\t0\t2\t1\nfam1\tkid\tdad\tmum\t2\t2\n"
    (tmp_path / "pedigree" / "fam1.ped").write_text(ped, encoding="utf-8")
    _touch(tmp_path, "rank_and_filter/fam1_snv_ranked_clinical.vcf.gz")
    for sample in ("dad", "mum", "kid"):
        _touch(tmp_path, f"alignment/{sample}_sorted_md.bam", f"qc_bam/{sample}_tidditcov.bw")
    df = execute_recipe("nf-core/raredisease/tracks.py", tmp_path)
    assert df["track_id"].to_list()[:3] == ["fam1.ranked_clinical", "kid.alignment", "kid.coverage"]


def test_a_run_with_no_affected_sample_opens_on_the_first_sample(tmp_path: Path) -> None:
    (tmp_path / "pedigree").mkdir()
    ped = "fam1\tdad\t0\t0\t1\t1\nfam1\tmum\t0\t0\t2\t1\n"
    (tmp_path / "pedigree" / "fam1.ped").write_text(ped, encoding="utf-8")
    _touch(tmp_path, "rank_and_filter/fam1_snv_ranked_clinical.vcf.gz")
    for sample in ("dad", "mum"):
        _touch(tmp_path, f"alignment/{sample}_sorted_md.bam", f"qc_bam/{sample}_tidditcov.bw")
    df = execute_recipe("nf-core/raredisease/tracks.py", tmp_path)
    assert df["track_id"].to_list()[:3] == ["fam1.ranked_clinical", "dad.alignment", "dad.coverage"]


_HEADER = (
    "##fileformat=VCFv4.2\n"
    '##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations from Ensembl VEP. '
    'Format: Allele|Consequence|IMPACT|SYMBOL|HGVSp">\n'
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tkid\tdad\n"
)


def _record(pos: int, score: str | None, gene: str, hgvs_p: str) -> str:
    info = f"CSQ=A|missense_variant|MODERATE|{gene}|{hgvs_p}"
    if score is not None:
        info += f";RankScore=fam1:{score};RankScoreMinMax=fam1:-17.0:18.0"
    return f"21\t{pos}\t.\tG\tA\t50\tPASS\t{info}\tGT:DP:AD:GQ\t0/1:20:10,10:60\t0/0:20:20,0:60\n"


def test_ranked_variants_come_out_best_first_and_unscored_last(tmp_path: Path) -> None:
    (tmp_path / "rank_and_filter").mkdir()
    vcf = (
        _HEADER
        + _record(100, "3", "GENEA", "p.Ala1Val")
        + _record(200, None, "GENEB", "p.Gly2Asp")
        + _record(300, "9", "GENEC", "p.Leu3Pro")
        + _record(400, "9", "GENED", "p.Ser4Phe")
    )
    with gzip.open(tmp_path / "rank_and_filter" / "fam1_snv_ranked_research.vcf.gz", "wt") as fh:
        fh.write(vcf)
    ranked = execute_recipe("nf-core/raredisease/ranked_variants.py", tmp_path)
    assert ranked["pos"].to_list() == [300, 400, 100, 200]
    assert ranked["rank_score"].to_list() == [9.0, 9.0, 3.0, None]
    assert ranked["call_label"].to_list()[0] == "GENEC p.Leu3Pro"
    # The model's bounds come with the rows it scored (a row it did not reach has none), and
    # every sample's genotype is kept, a reference one included, beside the carriers' calls.
    assert ranked["rank_score_min"].to_list() == [-17.0, -17.0, -17.0, None]
    assert ranked["rank_score_max"].to_list() == [18.0, 18.0, 18.0, None]
    assert set(ranked["genotypes"].to_list()) == {"kid|0/1;dad|0/0"}
    assert set(ranked["calls"].to_list()) == {"kid|0/1|20|60|0.500"}

    genotypes = load_recipe("nf-core/raredisease/ranked_genotypes.py").transform({"ranked": ranked})
    # Only the carrier of each variant gets a row, and it names the variant's gene and change.
    assert genotypes["sample"].unique().to_list() == ["kid"]
    assert set(genotypes["call_label"].to_list()) == {
        "GENEA p.Ala1Val",
        "GENEB p.Gly2Asp",
        "GENEC p.Leu3Pro",
        "GENED p.Ser4Phe",
    }
    assert {"gene", "call_label"} <= set(genotypes.columns)
