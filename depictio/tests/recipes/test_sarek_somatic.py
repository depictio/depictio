"""nf-core/sarek 3.10.0: tumours, pairs and the somatic collections.

Two kinds of check.

* The real run: ``~/Data/depictio-nfcore/sarek/3.10.0/somatic_test`` is a sarek
  ``-profile test`` run with ``--tools strelka,mutect2,cnvkit,msisensorpro`` on one patient,
  a normal (``test``, status 0) and a tumour (``test2``, status 1). The recipes run on its
  real files and the assertions are what that run holds. It is a tiny region of chr22: its
  paired VCFs carry a header and no call, so the somatic *parsers* cannot be exercised on it.
* Hand-written VCF lines in the shape Mutect2 and Strelka write them, for the parsers and for
  the rule that no somatic or tumour-only call reaches a germline collection.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe, validate_schema
from depictio.recipes.lib.sarek_units import (
    DESIGN_GERMLINE,
    DESIGN_PAIRED,
    DESIGN_TUMOUR_ONLY,
    design_label,
    split_pair,
    unit_frame,
)
from depictio.recipes.lib.vcf_somatic import somatic_to_long

VERSION = "3.10.0"
RUN = Path.home() / "Data/depictio-nfcore/sarek/3.10.0/somatic_test"
needs_run = pytest.mark.skipif(not RUN.is_dir(), reason="the somatic_test run is not on disk")

# How the template's raw scans read the files (template.yaml).
_VCF_SCAN = dict(
    separator="\x1e",
    has_header=False,
    quote_char=None,
    new_columns=["raw_line"],
    infer_schema_length=0,
)
_TSV_SCAN = dict(separator="\t", has_header=True, infer_schema_length=0)
_VCF_RAW = r"^(?!.*_(?:snpEff|VEP)\.ann\.vcf\.gz$)(?!.*\.g(?:enome)?\.vcf\.gz$).*\.vcf\.gz$"


def _scan(root: Path, pattern: str, kwargs: dict) -> pl.DataFrame | None:
    """The frame a recursive raw scan builds: the files the pattern matches, with their path."""
    rx = re.compile(pattern.replace("/", "\\/"))
    frames = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rx.match(path.name) or ("/" in pattern and rx.match(rel)):
            frames.append(
                pl.read_csv(path, **kwargs).with_columns(pl.lit(rel).alias("source_path"))
            )
    return pl.concat(frames, how="diagonal_relaxed") if frames else None


def _run(ref: str, root: Path = RUN, **sources: pl.DataFrame | None) -> pl.DataFrame:
    return execute_recipe(ref, root, None, extra_sources=sources, pipeline_version=VERSION)


# ---------------------------------------------------------------------------
# The identity model (library)
# ---------------------------------------------------------------------------


def test_a_patients_design_comes_from_the_status_of_its_samples() -> None:
    assert design_label([0, 1]) == DESIGN_PAIRED
    assert design_label([0, 0]) == DESIGN_GERMLINE
    assert design_label([1]) == DESIGN_TUMOUR_ONLY
    # A sheet that never said which sample is a tumour is a germline run.
    assert design_label([None, None]) == DESIGN_GERMLINE


def test_units_are_samples_or_pairs_and_the_hub_says_which_sample_is_a_tumour() -> None:
    hub = pl.DataFrame(
        {"sample_id": ["N", "T", "T2"], "patient": ["P", "P", "Q"], "status": [0, 1, 1]},
        schema={"sample_id": pl.Utf8, "patient": pl.Utf8, "status": pl.Int64},
    )
    units = unit_frame(["N", "T_vs_N", "T2", "Z"], hub).sort("unit")
    assert units.select("unit", "unit_type", "patient", "sample", "normal").rows() == [
        ("N", "germline", "P", "N", None),
        ("T2", "tumour_only", "Q", "T2", None),
        ("T_vs_N", "paired", "P", "T", "N"),
        # A unit the sheet does not describe is germline: the graceful default.
        ("Z", "germline", None, "Z", None),
    ]
    assert split_pair("T_vs_N") == ("T", "N")
    assert split_pair("N") == ("N", None)


# ---------------------------------------------------------------------------
# The real run
# ---------------------------------------------------------------------------


@needs_run
def test_the_hub_gives_the_patient_a_design_and_the_pair_its_callers() -> None:
    hub = _run("nf-core/sarek/samples.py")
    assert hub["sample_id"].to_list() == ["test", "test2"]
    assert hub["patient"].to_list() == ["test", "test"]
    assert hub["status_label"].to_list() == ["Normal", "Tumour"]
    assert hub["design"].to_list() == ["Paired", "Paired"]
    # variantcalled.csv lists strelka on the normal, and mutect2 and strelka on the pair,
    # which count for the tumour.
    assert hub["n_callers"].to_list() == [1, 2]


@needs_run
def test_the_pairs_are_the_design_of_the_samplesheet() -> None:
    pairs = _run("nf-core/sarek/pairs.py", hub=_run("nf-core/sarek/samples.py"))
    assert pairs.rows() == [("test2_vs_test", "test", "test2", "test")]


@needs_run
def test_the_germline_collections_read_the_normals_calls_and_no_pair() -> None:
    hub = _run("nf-core/sarek/samples.py")
    raw = _scan(RUN, _VCF_RAW, _VCF_SCAN)
    assert raw is not None
    # The scan takes every non-gVCF VCF of the run, the pair's included.
    assert {p.split("/")[-1] for p in raw["source_path"].unique()} >= {
        "test.strelka.variants.vcf.gz",
        "test2_vs_test.mutect2.filtered.vcf.gz",
        "test2_vs_test.strelka.somatic_snvs.vcf.gz",
    }
    calls = _run("nf-core/sarek/vcf_variants.py", raw=raw, hub=hub)
    assert set(calls["sample"]) == {"test"}
    assert set(calls["caller"]) == {"strelka"}
    assert calls.height == 8
    assert calls["is_pass"].sum() == 3
    # No Manta or TIDDIT among the run's callers.
    with pytest.raises(Exception, match="structural-variant caller"):
        _run("nf-core/sarek/sv_calls.py", raw=raw, hub=hub)


@needs_run
def test_a_run_whose_paired_callers_found_nothing_has_no_somatic_calls() -> None:
    raw = _scan(RUN, _VCF_RAW, _VCF_SCAN)
    # The paired VCFs of the run are a header and no record: the optional collection is skipped.
    with pytest.raises(Exception, match="somatic_calls"):
        _run("nf-core/sarek/somatic_calls.py", raw=raw, hub=_run("nf-core/sarek/samples.py"))


@needs_run
def test_the_tracks_list_the_pairs_vcfs_beside_both_crams() -> None:
    tracks = _run("nf-core/sarek/tracks.py")
    assert tracks["track_id"].to_list() == [
        "test.strelka",
        "test.alignments",
        "test2_vs_test.mutect2",
        "test2_vs_test.strelka.somatic_indels",
        "test2_vs_test.strelka.somatic_snvs",
        "test2.alignments",
    ]
    by_id = {r["track_id"]: r for r in tracks.to_dicts()}
    # A pair's calls belong to its tumour, so the hub's sample filter reaches them.
    assert by_id["test2_vs_test.mutect2"]["sample_id"] == "test2"
    assert by_id["test2_vs_test.mutect2"]["category"] == "Somatic variants"
    assert by_id["test2_vs_test.mutect2"]["kind"] == "somatic"
    assert by_id["test2_vs_test.mutect2"]["uri"] == (
        "variant_calling/mutect2/test2_vs_test/test2_vs_test.mutect2.filtered.vcf.gz"
    )
    assert by_id["test2.alignments"]["uri"] == "preprocessing/recalibrated/test2/test2.recal.cram"
    assert by_id["test.strelka"]["category"] == "Small variants"
    # The files and their indexes are all under the run, so nothing is dropped.
    for row in tracks.to_dicts():
        index = ".crai" if row["format"] == "cram" else ".tbi"
        assert (RUN / (row["uri"] + index)).is_file(), row["uri"]


@needs_run
def test_copy_number_is_one_profile_per_unit_on_the_most_specific_called_file() -> None:
    hub = _run("nf-core/sarek/samples.py")
    segments = _scan(RUN, r"^.*cnvkit/[^/]+/[^/]+\.(?:somatic\.|germline\.)?call\.cns$", _TSV_SCAN)
    bins = _scan(RUN, r"^.*cnvkit/[^/]+/[^/]+\.cnr$", _TSV_SCAN)
    cnv = _run("nf-core/sarek/cnv_segments.py", segments=segments, bins=bins, hub=hub)
    called = cnv.filter(pl.col("segment") == "segment").sort("unit")
    assert called.select(
        "unit", "unit_type", "sample", "normal", "call_source", "copy_number"
    ).rows() == [
        ("test", "germline", "test", None, "germline", 0),
        ("test2_vs_test", "paired", "test2", "test", "somatic", 0),
    ]
    assert called["log2"].to_list() == pytest.approx([-2.55295, -1.97487])
    # CNVkit writes a log2 of about -18 for a bin without coverage: floored, not drawn at -18.
    assert cnv["log2"].min() == pytest.approx(-3.0)
    assert set(cnv.filter(pl.col("segment") == "bin")["call_source"]) == {"bins"}


def _segments(*rows: tuple) -> pl.DataFrame:
    """A cnv_segments frame: (unit, chrom, start, end, log2, row type) per row."""
    return pl.DataFrame(
        [
            (u, "paired", "P1", u.split("_vs_")[0], u.split("_vs_")[1], c, s, e, v, kind, "somatic")
            for u, c, s, e, v, kind in rows
        ],
        schema={
            "unit": pl.Utf8,
            "unit_type": pl.Utf8,
            "patient": pl.Utf8,
            "sample": pl.Utf8,
            "normal": pl.Utf8,
            "chrom": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "log2": pl.Float64,
            "segment": pl.Utf8,
            "call_source": pl.Utf8,
        },
        orient="row",
    )


def test_the_copy_number_summary_adds_up_the_megabases_past_each_cut_off() -> None:
    mb = 1_000_000
    segments = _segments(
        # chr1: 60 Mb gained, 40 Mb neutral; chr2: 20 Mb lost; chr3: 5 Mb of 100 Mb gained
        ("T_vs_N", "chr1", 0, 60 * mb, 0.8, "segment"),
        ("T_vs_N", "chr1", 60 * mb, 100 * mb, 0.1, "segment"),
        ("T_vs_N", "chr2", 0, 20 * mb, -0.9, "segment"),
        ("T_vs_N", "chr2", 20 * mb, 100 * mb, 0.0, "segment"),
        ("T_vs_N", "chr3", 0, 5 * mb, 0.5, "segment"),
        ("T_vs_N", "chr3", 5 * mb, 100 * mb, -0.2, "segment"),
        # a bin is the evidence, not the call: it is not summed
        ("T_vs_N", "chr1", 0, 2000, 3.0, "bin"),
    )
    out = _run("nf-core/sarek/cnv_summary.py", segments=segments)
    assert out.height == 1
    row = out.row(0, named=True)
    assert (row["unit"], row["sample"], row["normal"]) == ("T_vs_N", "T", "N")
    assert row["n_segments"] == 6
    assert (row["n_gains"], row["n_losses"]) == (2, 1)
    assert row["covered_mb"] == pytest.approx(300)
    assert (row["gained_mb"], row["lost_mb"], row["altered_mb"]) == pytest.approx((65, 20, 85))
    assert row["fga_pct"] == pytest.approx(85 / 300 * 100)
    assert row["gained_pct"] + row["lost_pct"] == pytest.approx(row["fga_pct"])
    # chr1 (60%) and chr2 (20%) are altered; chr3 (5%) is under a tenth of its length.
    assert (row["contigs"], row["altered_contigs"]) == (3, 2)
    assert (row["max_log2"], row["min_log2"]) == pytest.approx((0.8, -0.9))


def test_the_copy_number_summary_is_one_row_per_unit_and_needs_a_called_segment() -> None:
    mb = 1_000_000
    two = _segments(
        ("A_vs_N", "chr1", 0, 10 * mb, 0.9, "segment"),
        ("B_vs_M", "chr1", 0, 10 * mb, 0.0, "segment"),
    )
    out = _run("nf-core/sarek/cnv_summary.py", segments=two)
    assert out["unit"].to_list() == ["A_vs_N", "B_vs_M"]
    assert out["fga_pct"].to_list() == pytest.approx([100.0, 0.0])
    only_bins = _segments(("A_vs_N", "chr1", 0, 2000, 0.9, "bin"))
    with pytest.raises(Exception, match="cnv_summary"):
        _run("nf-core/sarek/cnv_summary.py", segments=only_bins)


@needs_run
def test_the_real_run_has_a_summary_for_each_of_its_two_profiles() -> None:
    hub = _run("nf-core/sarek/samples.py")
    segments = _scan(RUN, r"^.*cnvkit/[^/]+/[^/]+\.(?:somatic\.|germline\.)?call\.cns$", _TSV_SCAN)
    cnv = _run("nf-core/sarek/cnv_segments.py", segments=segments, bins=None, hub=hub)
    out = _run("nf-core/sarek/cnv_summary.py", segments=cnv)
    # Each profile is one segment of chr22 with a deep loss: the whole of what was called.
    assert out["unit"].to_list() == ["test", "test2_vs_test"]
    assert out["fga_pct"].to_list() == pytest.approx([100.0, 100.0])
    assert out["n_losses"].to_list() == [1, 1]


@needs_run
def test_msi_is_one_score_per_pair_read_from_the_summary_only() -> None:
    raw = _scan(RUN, r"^(?:.*/)?msisensorpro/([^/]+)/\1$", _TSV_SCAN)
    assert raw is not None and raw["source_path"].to_list() == [
        "variant_calling/msisensorpro/test2_vs_test/test2_vs_test"
    ]
    msi = _run("nf-core/sarek/msi.py", raw=raw, hub=_run("nf-core/sarek/samples.py"))
    assert msi.rows() == [("test2_vs_test", "paired", "test", "test2", "test", 1, 0, 0.0)]


# ---------------------------------------------------------------------------
# Callers' own records (hand-written, in the shape the callers write)
# ---------------------------------------------------------------------------


def _line(*fields: str) -> str:
    return "\t".join(fields)


def _raw(*files: tuple[str, list[str]]) -> pl.DataFrame:
    rows = [(line, path) for path, lines in files for line in lines]
    return pl.DataFrame(rows, schema={"raw_line": pl.Utf8, "source_path": pl.Utf8}, orient="row")


MUTECT_PAIR = "variant_calling/mutect2/T_vs_N/T_vs_N.mutect2.filtered.vcf.gz"
STRELKA_SNV = "variant_calling/strelka/T_vs_N/T_vs_N.strelka.somatic_snvs.vcf.gz"
STRELKA_INDEL = "variant_calling/strelka/T_vs_N/T_vs_N.strelka.somatic_indels.vcf.gz"
MUTECT_ALONE = "variant_calling/mutect2/T2/T2.mutect2.filtered.vcf.gz"
GERMLINE = "variant_calling/strelka/N/N.strelka.variants.vcf.gz"
MANTA_PAIR = "variant_calling/manta/T_vs_N/T_vs_N.manta.somatic_sv.vcf.gz"

_MUTECT_HEADER = [
    "##fileformat=VCFv4.2",
    "##normal_sample=P_N",
    "##tumor_sample=P_T",
    _line("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", "P_N", "P_T"),
]


def _mutect_pair() -> tuple[str, list[str]]:
    return (
        MUTECT_PAIR,
        [
            *_MUTECT_HEADER,
            _line(
                "chr1",
                "100",
                ".",
                "A",
                "G",
                ".",
                "PASS",
                "DP=50;TLOD=12.5",
                "GT:AD:AF:DP",
                "0/0:48,2:0.04:50",
                "0/1:30,20:0.4:50",
            ),
            _line(
                "chr1",
                "150",
                ".",
                "C",
                "T",
                ".",
                "weak_evidence",
                "DP=20;TLOD=2.1",
                "GT:AD:AF:DP",
                "0/0:20,0:0.0:20",
                "0/1:9,1:0.1:10",
            ),
        ],
    )


def _strelka_snv() -> tuple[str, list[str]]:
    return (
        STRELKA_SNV,
        [
            "##source=strelka",
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
                "NORMAL",
                "TUMOR",
            ),
            _line(
                "chr2",
                "200",
                ".",
                "A",
                "G",
                ".",
                "PASS",
                "SOMATIC;QSS=30;SomaticEVS=7.5",
                "DP:FDP:SDP:SUBDP:AU:CU:GU:TU",
                "30:0:0:0:30,30:0,0:0,0:0,0",
                "40:0:0:0:20,20:0,0:20,20:0,0",
            ),
        ],
    )


def _strelka_indel() -> tuple[str, list[str]]:
    return (
        STRELKA_INDEL,
        [
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
                "NORMAL",
                "TUMOR",
            ),
            _line(
                "chr3",
                "300",
                ".",
                "AT",
                "A",
                ".",
                "PASS",
                "SOMATIC;SomaticEVS=9.1",
                "DP:DP2:TAR:TIR:TOR",
                "30:30:30,30:0,0:0,0",
                "40:40:30,30:10,10:0,0",
            ),
        ],
    )


def _mutect_alone() -> tuple[str, list[str]]:
    return (
        MUTECT_ALONE,
        [
            _line("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", "Q_T2"),
            _line(
                "chr1",
                "100",
                ".",
                "A",
                "G",
                ".",
                "PASS",
                "DP=60;TLOD=20",
                "GT:AD:AF:DP",
                "0/1:36,24:0.4:60",
            ),
            _line(
                "chr4",
                "400",
                ".",
                "G",
                "C",
                ".",
                "PASS",
                "DP=30;TLOD=8",
                "GT:AD:AF:DP",
                "0/1:21,9:0.3:30",
            ),
        ],
    )


def _germline() -> tuple[str, list[str]]:
    return (
        GERMLINE,
        [
            _line("chr1", "100", ".", "A", "G", "50", "PASS", ".", "GT:AD:DP", "0/1:25,25:50"),
            _line("chr9", "900", ".", "T", "C", "50", "PASS", ".", "GT:AD:DP", "0/1:25,25:50"),
        ],
    )


def _hub() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample_id": ["N", "T", "T2"],
            "patient": ["P", "P", "Q"],
            "sex": ["XX", "XX", "XY"],
            "status": [0, 1, 1],
        },
        schema={"sample_id": pl.Utf8, "patient": pl.Utf8, "sex": pl.Utf8, "status": pl.Int64},
    )


def _mixed_raw() -> pl.DataFrame:
    return _raw(
        _germline(),
        _mutect_pair(),
        _strelka_snv(),
        _strelka_indel(),
        _mutect_alone(),
        (
            MANTA_PAIR,
            [
                _line(
                    "chr5",
                    "500",
                    "MantaDEL",
                    "A",
                    "<DEL>",
                    "9",
                    "PASS",
                    "END=900;SVTYPE=DEL;SVLEN=-400",
                    "GT",
                    "0/1",
                )
            ],
        ),
    )


def test_mutect2_pair_reads_the_tumour_column_the_header_names() -> None:
    calls = somatic_to_long(_raw(_mutect_pair())).sort("pos")
    assert calls.select("unit", "caller", "chrom", "pos", "is_pass").rows() == [
        ("T_vs_N", "mutect2", "chr1", 100, True),
        ("T_vs_N", "mutect2", "chr1", 150, False),
    ]
    assert calls["tumour_vaf"].to_list() == pytest.approx([0.4, 0.1])
    assert calls["normal_vaf"].to_list() == pytest.approx([0.04, 0.0])
    assert calls["tumour_dp"].to_list() == [50, 10]
    assert calls["normal_dp"].to_list() == [50, 20]
    assert calls["score"].to_list() == pytest.approx([12.5, 2.1])
    assert calls["variant_key"][0] == "chr1:100:A:G"


def test_a_header_with_the_tumour_first_is_followed_not_assumed() -> None:
    swapped = [
        "##normal_sample=P_N",
        "##tumor_sample=P_T",
        _line(
            "#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", "P_T", "P_N"
        ),
        _line(
            "chr1",
            "100",
            ".",
            "A",
            "G",
            ".",
            "PASS",
            "DP=50",
            "GT:AD:AF:DP",
            "0/1:30,20:0.4:50",
            "0/0:48,2:0.04:50",
        ),
    ]
    calls = somatic_to_long(_raw((MUTECT_PAIR, swapped)))
    assert calls["tumour_vaf"].to_list() == pytest.approx([0.4])
    assert calls["normal_vaf"].to_list() == pytest.approx([0.04])


def test_strelka_snv_fraction_is_the_alt_bases_tier1_count_over_the_four() -> None:
    call = somatic_to_long(_raw(_strelka_snv())).row(0, named=True)
    assert (call["caller"], call["variant_type"], call["is_pass"]) == ("strelka", "SNP", True)
    assert call["tumour_vaf"] == pytest.approx(0.5)  # G: 20 of A 20 + G 20
    assert call["normal_vaf"] == pytest.approx(0.0)
    assert (call["tumour_dp"], call["normal_dp"]) == (40, 30)
    assert call["score"] == pytest.approx(7.5)


def test_strelka_indel_fraction_is_tir_over_tir_plus_tar() -> None:
    call = somatic_to_long(_raw(_strelka_indel())).row(0, named=True)
    assert call["variant_type"] == "INDEL"
    assert call["tumour_vaf"] == pytest.approx(0.25)  # TIR 10 of TIR 10 + TAR 30
    assert call["normal_vaf"] == pytest.approx(0.0)
    assert call["tumour_dp"] == 40


def test_files_no_parser_covers_are_left_out_rather_than_guessed() -> None:
    other_pair = (
        "variant_calling/freebayes/T_vs_N/T_vs_N.freebayes.vcf.gz",
        [_line("chr1", "10", ".", "A", "G", "9", "PASS", ".", "GT:AD", "0/0:9,0", "0/1:5,5")],
    )
    unfiltered = (MUTECT_PAIR.replace(".filtered", ""), _mutect_pair()[1])
    sv = _mixed_raw().filter(pl.col("source_path") == MANTA_PAIR)
    assert somatic_to_long(_raw(other_pair, unfiltered)).is_empty()
    assert somatic_to_long(sv).is_empty()


def test_the_somatic_recipe_keeps_pairs_and_lone_tumours_and_no_germline_unit() -> None:
    out = _run_recipe("somatic_calls.py", raw=_mixed_raw(), hub=_hub())
    assert out.group_by("unit_type", "unit").len().sort("unit").rows() == [
        ("tumour_only", "T2", 2),
        ("paired", "T_vs_N", 4),
    ]
    paired = out.filter(pl.col("unit") == "T_vs_N")
    assert set(paired["caller"]) == {"mutect2", "strelka"}
    assert set(paired["sample"]) == {"T"} and set(paired["normal"]) == {"N"}
    assert set(paired["patient"]) == {"P"}
    alone = out.filter(pl.col("unit") == "T2")
    assert set(alone["sample"]) == {"T2"} and alone["normal"].null_count() == alone.height
    assert alone["normal_vaf"].null_count() == alone.height
    assert alone.sort("pos")["tumour_vaf"].to_list() == pytest.approx([0.4, 0.3])
    assert set(alone["patient"]) == {"Q"}


def test_no_somatic_or_tumour_only_call_reaches_a_germline_collection() -> None:
    raw, hub = _mixed_raw(), _hub()
    germline = _run_recipe("vcf_variants.py", raw=raw, hub=hub)
    assert set(germline["sample"]) == {"N"}
    assert germline.height == 2
    # Nor the structural variants of a pair.
    with pytest.raises(Exception, match="structural-variant caller"):
        _run_recipe("sv_calls.py", raw=raw, hub=hub)
    # A tumour sample's own VCF stays out as well, whatever the caller.
    assert "T2" not in set(germline["sample"])


def test_a_germline_only_run_keeps_every_unit_in_the_germline_table() -> None:
    hub = _hub().filter(pl.col("sample_id") == "N")
    out = _run_recipe("vcf_variants.py", raw=_raw(_germline()), hub=hub)
    assert out.height == 2
    with pytest.raises(Exception, match="somatic_calls"):
        _run_recipe("somatic_calls.py", raw=_raw(_germline()), hub=hub)


def _run_recipe(name: str, **sources: pl.DataFrame) -> pl.DataFrame:
    ref = f"nf-core/sarek/{name}"
    module = load_recipe(ref, VERSION)
    out = module.transform(sources)
    validate_schema(out, module.OUTPUT_SCHEMA, ref, getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None))
    return out


def _pairs() -> pl.DataFrame:
    return _run_recipe("pairs.py", hub=_hub())


def test_the_pairs_of_a_sheet_are_every_tumour_against_the_normal_of_its_patient() -> None:
    pairs = _pairs()
    # T2 has no normal in its patient: tumour-only, no pair.
    assert pairs.rows() == [("T_vs_N", "P", "T", "N")]
    with pytest.raises(ValueError, match="no tumour/normal pair"):
        load_recipe("nf-core/sarek/pairs.py", VERSION).transform(
            {"hub": _hub().filter(pl.col("status") == 0)}
        )


def test_the_comparison_flags_a_somatic_call_the_normal_also_carries_as_germline() -> None:
    raw, hub = _mixed_raw(), _hub()
    somatic = _run_recipe("somatic_calls.py", raw=raw, hub=hub)
    germline = _run_recipe("vcf_variants.py", raw=raw, hub=hub)
    out = _run_recipe("somatic_vs_germline.py", somatic=somatic, germline=germline, pairs=_pairs())
    assert set(out["unit"]) == {"T_vs_N"} and out.height == 4
    shared = out.filter(pl.col("in_germline"))
    # chr1:100 A>G is a PASS germline call of N and a PASS Mutect2 call of the pair.
    assert shared.select("caller", "variant_key", "germline_callers").rows() == [
        ("mutect2", "chr1:100:A:G", 1)
    ]
    mutect = out.filter((pl.col("caller") == "mutect2") & (pl.col("pos") == 100)).row(0, named=True)
    # The paired call wrote the normal's fraction itself, so it wins over the germline call's.
    assert mutect["normal_vaf_source"] == "paired call"
    assert mutect["normal_vaf"] == pytest.approx(0.04)
    assert set(out.filter(~pl.col("in_germline"))["germline_callers"]) == {0}
    assert set(out["patient"]) == {"P"} and set(out["sample"]) == {"T"}
    # The label that colours the scatter says the same thing as the flag.
    assert set(shared["origin"]) == {"Also in the normal's germline calls"}
    assert set(out.filter(~pl.col("in_germline"))["origin"]) == {
        "Not in the normal's germline calls"
    }


def test_the_normal_fraction_falls_back_to_the_matching_germline_call() -> None:
    germline = pl.DataFrame(
        [("N", "strelka", "chr1:5:A:G", True, 0.48)],
        schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "variant_key": pl.Utf8,
            "is_pass": pl.Boolean,
            "vaf": pl.Float64,
        },
        orient="row",
    )
    somatic = _run_recipe("somatic_calls.py", raw=_mixed_raw(), hub=_hub()).head(0)
    somatic = pl.concat(
        [
            somatic,
            pl.DataFrame(
                {
                    "unit": ["T_vs_N"],
                    "unit_type": ["paired"],
                    "patient": ["P"],
                    "sample": ["T"],
                    "normal": ["N"],
                    "caller": ["mutect2"],
                    "chrom": ["chr1"],
                    "pos": [5],
                    "ref": ["A"],
                    "alt": ["G"],
                    "variant_key": ["chr1:5:A:G"],
                    "variant_type": ["SNP"],
                    "qual": [None],
                    "score": [3.0],
                    "filter_status": ["PASS"],
                    "is_pass": [True],
                    "tumour_vaf": [0.3],
                    "tumour_dp": [40],
                    "normal_vaf": [None],
                    "normal_dp": [None],
                },
                schema=somatic.schema,
            ),
        ]
    )
    out = _run_recipe("somatic_vs_germline.py", somatic=somatic, germline=germline, pairs=_pairs())
    row = out.row(0, named=True)
    assert (row["normal_vaf"], row["normal_vaf_source"], row["in_germline"]) == (
        pytest.approx(0.48),
        "germline call",
        True,
    )


def test_patient_counts_are_distinct_pass_variants_of_the_normal_and_of_the_pair() -> None:
    raw, hub = _mixed_raw(), _hub()
    somatic = _run_recipe("somatic_calls.py", raw=raw, hub=hub)
    germline = _run_recipe("vcf_variants.py", raw=raw, hub=hub)
    out = _run_recipe("patient_call_counts.py", somatic=somatic, germline=germline, pairs=_pairs())
    # Patient Q is tumour-only: no pair, so not listed. P: 2 germline PASS calls; the pair has
    # 3 PASS records (Mutect2 chr1:100, Strelka chr2:200 and chr3:300; chr1:150 is filtered).
    assert out.rows() == [("P", "Germline (normal)", 2), ("P", "Somatic (pair)", 3)]
