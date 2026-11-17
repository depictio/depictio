"""nf-core/sarek 3.10.0: the variant-level somatic collections.

Hand-written VCF lines in the shape the callers write them (MuSE, Freebayes on a pair, SnpEff),
for the parsers in ``depictio.recipes.lib.vcf_somatic`` and the four recipes built on them:
``somatic_variants`` (the callers merged), ``somatic_burden`` (per megabase of the target) and
``germline_het_sites`` (the normal's heterozygous sites read in the tumour).
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema
from depictio.recipes.lib.vcf_somatic import annotation_by_variant, joint_het_sites, somatic_to_long

VERSION = "3.10.0"


def _line(*fields: str) -> str:
    return "\t".join(fields)


def _raw(*files: tuple[str, list[str]]) -> pl.DataFrame:
    rows = [(line, path) for path, lines in files for line in lines]
    return pl.DataFrame(rows, schema={"raw_line": pl.Utf8, "source_path": pl.Utf8}, orient="row")


MUSE = "variant_calling/muse/T_vs_N/T_vs_N.muse.vcf.gz"
FREEBAYES_PAIR = "variant_calling/freebayes/T_vs_N/T_vs_N.freebayes.filtered.vcf.gz"
ANN_MUTECT2 = "annotation/mutect2/T_vs_N/T_vs_N.mutect2.filtered.bcftools_filtered.norm.sorted_snpEff.ann.vcf.gz"
ANN_MUSE = "annotation/muse/T_vs_N/T_vs_N.muse.bcftools_filtered.norm.sorted_snpEff.ann.vcf.gz"


def _muse() -> tuple[str, list[str]]:
    return (
        MUSE,
        [
            "##fileformat=VCFv4.1",
            _line(
                "#CHROM",
                "POS",
                "ID",
                "REF",
                "ALT",
                "QUAL",
                "FILTER",
                "INFO",
                "FORMAT",
                "TUMOR",
                "NORMAL",
            ),
            _line(
                "chr1",
                "100",
                ".",
                "A",
                "G",
                ".",
                "PASS",
                "SOMATIC",
                "GT:DP:AD:BQ:SS",
                "0/1:50:30,20:38,36:2",
                "0/0:40:40,0:39,0:.",
            ),
            _line(
                "chr1",
                "300",
                ".",
                "C",
                "T",
                ".",
                "Tier4",
                "SOMATIC",
                "GT:DP:AD:BQ:SS",
                "0/1:13:12,1:38,39:2",
                "0/0:11:11,0:40,0:.",
            ),
        ],
    )


def test_muse_is_read_as_a_pair_with_the_tumour_first() -> None:
    calls = somatic_to_long(_raw(_muse()))
    assert calls["caller"].to_list() == ["muse", "muse"]
    first = calls.row(0, named=True)
    assert first["unit"] == "T_vs_N"
    assert first["is_pass"] is True
    assert first["tumour_vaf"] == pytest.approx(0.4)
    assert first["tumour_dp"] == 50
    assert first["normal_vaf"] == pytest.approx(0.0)
    # A MuSE tier is a confidence class, not PASS.
    assert calls["is_pass"].to_list() == [True, False]


def _freebayes_pair() -> tuple[str, list[str]]:
    header = _line(
        "#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", "P_N", "P_T"
    )
    fmt = "GT:AD:AO:DP"

    def site(pos: str, ref: str, alt: str, normal: str, tumour: str) -> str:
        return _line("chr2", pos, ".", ref, alt, "50", ".", "AB=0.5", fmt, normal, tumour)

    return (
        FREEBAYES_PAIR,
        [
            "##source=freeBayes",
            header,
            site("10", "A", "G", "0/1:15,15:15:30", "0/1:16,14:14:30"),  # kept both copies
            site("20", "C", "T", "0/1:15,15:15:30", "0/1:29,1:1:30"),  # lost the alternate
            site("30", "G", "A", "0/1:15,15:15:30", "1/1:1,29:29:30"),  # lost the reference
            site("40", "G", "A", "1/1:0,30:30:30", "1/1:0,30:30:30"),  # homozygous in the normal
            site("50", "T", "C", "0/1:4,4:4:8", "0/1:15,15:15:30"),  # normal too shallow
            site("60", "AT", "A", "0/1:15,15:15:30", "0/1:15,15:15:30"),  # an indel
        ],
    )


def test_joint_het_sites_keep_the_normals_heterozygous_snvs_with_enough_depth() -> None:
    sites = joint_het_sites(_raw(_freebayes_pair()))
    assert sites["pos"].to_list() == [10, 20, 30]
    assert sites["unit"].unique().to_list() == ["T_vs_N"]
    assert sites["normal_vaf"].to_list() == pytest.approx([0.5, 0.5, 0.5])
    assert sites["tumour_vaf"].to_list() == pytest.approx([14 / 30, 1 / 30, 29 / 30])


def test_joint_het_sites_name_the_columns_by_sample_not_by_position() -> None:
    swapped = _freebayes_pair()
    header = swapped[1][1].replace("P_N\tP_T", "P_T\tP_N")
    lines = [swapped[1][0], header, *swapped[1][2:]]
    sites = joint_het_sites(_raw((FREEBAYES_PAIR, lines)))
    # The first column is now the tumour: the "normal" genotype of each record is the old tumour's.
    assert 10 in sites["pos"].to_list()
    assert sites.filter(pl.col("pos") == 10)["normal_vaf"].item() == pytest.approx(14 / 30)


def test_joint_het_sites_ignore_a_single_sample_callset() -> None:
    single = (
        "variant_calling/freebayes/N/N.freebayes.filtered.vcf.gz",
        [_line("chr1", "5", ".", "A", "G", "1", ".", ".", "GT:DP:AD", "0/1:30:15,15")],
    )
    assert joint_het_sites(_raw(single)).is_empty()


def _ann(
    gene: str, impact: str, consequence: str, hgvs_p: str = "", biotype: str = "protein_coding"
) -> str:
    return f"A|{consequence}|{impact}|{gene}|ENSG_{gene}|transcript|ENST_{gene}|{biotype}|1/2|c.1A>G|{hgvs_p}|||||"


def _annotated() -> pl.DataFrame:
    def rec(pos: str, ann: list[str], ref: str = "A", alt: str = "G") -> str:
        return _line("chr1", pos, ".", ref, alt, ".", "PASS", "ANN=" + ",".join(ann), "GT", "0/1")

    return _raw(
        (
            ANN_MUTECT2,
            [
                rec(
                    "100",
                    [
                        _ann("GENEB", "MODIFIER", "intron_variant"),
                        _ann("GENEA", "MODERATE", "missense_variant", "p.Glu12Gln"),
                        _ann("NCRNA", "HIGH", "stop_gained", "", "lncRNA"),
                        _ann("GENEC", "HIGH", "stop_gained", "p.Gln7*"),
                    ],
                ),
                rec("200", [_ann("", "MODIFIER", "intergenic_region")], "C", "T"),
            ],
        ),
        # The same variant from another caller is annotated once.
        (ANN_MUSE, [rec("100", [_ann("GENEA", "MODERATE", "missense_variant", "p.Glu12Gln")])]),
    )


def test_annotation_keeps_the_worst_impact_and_a_coding_transcript_first() -> None:
    ann = annotation_by_variant(_annotated())
    assert ann.height == 2
    worst = ann.filter(pl.col("variant_key") == "chr1:100:A:G").row(0, named=True)
    assert worst["unit"] == "T_vs_N"
    # HIGH beats MODERATE; of the two HIGH entries the protein-coding transcript wins.
    assert (worst["gene"], worst["impact"], worst["hgvs_p"], worst["aa_pos"]) == (
        "GENEC",
        "HIGH",
        "p.Gln7*",
        7,
    )
    intergenic = ann.filter(pl.col("variant_key") == "chr1:200:C:T").row(0, named=True)
    assert intergenic["gene"] is None
    assert intergenic["impact"] == "MODIFIER"


# ---------------------------------------------------------------------------
# The recipes
# ---------------------------------------------------------------------------


def _calls() -> pl.DataFrame:
    """somatic_vs_germline rows: three PASS variants by one to three callers, plus a filtered call."""
    rows = []

    def add(caller, pos, ref, alt, vtype, passed, tvaf, nvaf, gcallers=0):
        rows.append(
            {
                "unit": "T_vs_N",
                "patient": "P",
                "sample": "T",
                "normal": "N",
                "caller": caller,
                "chrom": "chr1",
                "pos": pos,
                "ref": ref,
                "alt": alt,
                "variant_key": f"chr1:{pos}:{ref}:{alt}",
                "variant_type": vtype,
                "filter_status": "PASS" if passed else "LowEVS",
                "is_pass": passed,
                "tumour_vaf": tvaf,
                "tumour_dp": 100,
                "normal_vaf": nvaf,
                "normal_dp": 60,
                "normal_vaf_source": "paired call",
                "germline_callers": gcallers,
                "in_germline": gcallers > 0,
                "origin": "x",
            }
        )

    add("mutect2", 100, "A", "G", "SNP", True, 0.4, 0.0)  # A>G is T>C on the other strand
    add("strelka", 100, "A", "G", "SNP", True, 0.5, 0.0)
    add("muse", 100, "A", "G", "SNP", True, 0.45, 0.0)
    add("strelka", 200, "C", "T", "SNP", True, 0.2, 0.2, 1)  # a germline-like call, one caller
    add("strelka", 300, "AT", "A", "INDEL", True, 0.3, 0.0)
    add("mutect2", 300, "AT", "A", "INDEL", True, 0.34, 0.08)
    add("strelka", 400, "G", "T", "SNP", False, 0.1, 0.0)  # filtered: not a variant of the pair
    return pl.DataFrame(rows)


def _variants() -> pl.DataFrame:
    module = load_recipe("nf-core/sarek/somatic_variants.py", VERSION)
    out = module.transform({"somatic": _calls(), "annotated": _annotated()})
    validate_schema(out, module.OUTPUT_SCHEMA, "somatic_variants")
    return out


def test_the_callers_are_merged_into_one_row_per_pass_variant() -> None:
    v = _variants().sort("pos")
    assert v["pos"].to_list() == [100, 200, 300]
    first = v.row(0, named=True)
    assert first["callers"] == "muse+mutect2+strelka"
    assert first["n_callers"] == 3
    assert first["support"] == "3 callers"
    assert first["consensus"] is True
    assert first["tumour_vaf"] == pytest.approx(0.45)  # the median of the three
    assert v["consensus"].to_list() == [True, False, True]
    assert v["support"].to_list() == ["3 callers", "1 caller", "2 callers"]


def test_the_normals_fraction_says_clean_trace_or_germline_like() -> None:
    v = _variants().sort("pos")
    assert v["normal_class"].to_list() == [
        "Clean in the normal",
        "Germline-like in the normal",
        "Trace in the normal",
    ]
    assert v.filter(pl.col("pos") == 200)["in_germline"].item() is True


def test_a_substitution_is_named_on_the_pyrimidine_strand() -> None:
    v = _variants().sort("pos")
    assert v["substitution"].to_list() == ["T>C", "C>T", None]


def test_the_candidates_are_ranked_by_impact_then_callers_then_fraction() -> None:
    v = _variants().sort("priority", descending=True)
    # chr1:100 is HIGH (GENEC, protein coding) and three callers agree.
    top = v.row(0, named=True)
    assert (top["gene"], top["impact"], top["annotated"]) == ("GENEC", "HIGH", True)
    assert top["priority"] == 4 * 1000 + 3 * 100 + 45
    rest = v.filter(pl.col("pos") != 100)
    assert rest["annotated"].to_list() == [True, False]
    assert rest["priority"].to_list()[0] > rest["priority"].to_list()[1]


def test_a_pair_that_was_not_annotated_keeps_the_collection_without_genes() -> None:
    module = load_recipe("nf-core/sarek/somatic_variants.py", VERSION)
    out = module.transform({"somatic": _calls(), "annotated": None})
    assert out["gene"].null_count() == out.height
    assert out["annotated"].to_list() == [False] * out.height


def test_somatic_variants_need_a_pass_call() -> None:
    module = load_recipe("nf-core/sarek/somatic_variants.py", VERSION)
    with pytest.raises(ValueError, match="no PASS somatic call"):
        module.transform({"somatic": _calls().filter(~pl.col("is_pass")), "annotated": None})


def test_the_burden_is_per_megabase_of_the_capture_target() -> None:
    module = load_recipe("nf-core/sarek/somatic_burden.py", VERSION)
    targets = pl.DataFrame(
        {"sample": ["T", "T", "N"], "target_bp": [1_000_000, 1_000_000, 5_000_000]}
    )
    out = module.transform({"variants": _variants(), "targets": targets})
    validate_schema(out, module.OUTPUT_SCHEMA, "somatic_burden")
    by_basis = {r["basis"]: r for r in out.to_dicts()}
    assert list(by_basis) == [
        "consensus (2+ callers)",
        "any caller",
        "muse",
        "mutect2",
        "strelka",
    ]
    consensus = by_basis["consensus (2+ callers)"]
    # Two variants (the SNV at 100 and the indel at 300) of the three have two callers or more.
    assert (consensus["variants"], consensus["snvs"], consensus["indels"]) == (2, 1, 1)
    assert consensus["target_mb"] == pytest.approx(2.0)  # the tumour's own two targets
    assert consensus["per_mb"] == pytest.approx(1.0)
    assert by_basis["any caller"]["variants"] == 3
    assert by_basis["strelka"]["variants"] == 3
    assert by_basis["muse"]["variants"] == 1
    # One variant is HIGH impact: a protein-altering variant.
    assert by_basis["any caller"]["protein_altering"] == 1


def test_the_burden_keeps_the_counts_without_a_target_table() -> None:
    module = load_recipe("nf-core/sarek/somatic_burden.py", VERSION)
    out = module.transform({"variants": _variants(), "targets": None})
    assert out["per_mb"].null_count() == out.height
    assert out.filter(pl.col("basis") == "any caller")["variants"].item() == 3


def test_the_het_sites_are_binned_by_what_the_tumour_kept() -> None:
    module = load_recipe("nf-core/sarek/germline_het_sites.py", VERSION)
    pairs = pl.DataFrame(
        {"pair_id": ["T_vs_N"], "patient": ["P"], "tumour": ["T"], "normal": ["N"]}
    )
    out = module.transform({"raw": _raw(_freebayes_pair()), "pairs": pairs})
    validate_schema(out, module.OUTPUT_SCHEMA, "germline_het_sites")
    assert out["pos"].to_list() == [10, 20, 30]
    assert out["allele_state"].to_list() == ["Balanced", "LOH-like", "LOH-like"]
    assert out["chrom_rank"].to_list() == [2, 2, 2]
    assert out["sample"].unique().to_list() == ["T"]


def test_the_het_sites_need_a_pair_genotyped_jointly() -> None:
    module = load_recipe("nf-core/sarek/germline_het_sites.py", VERSION)
    pairs = pl.DataFrame(
        {"pair_id": ["T_vs_N"], "patient": ["P"], "tumour": ["T"], "normal": ["N"]}
    )
    with pytest.raises(ValueError, match="no pair genotyped jointly"):
        module.transform({"raw": _raw(_muse()), "pairs": pairs})
