"""The three somatic copy-number recipes, on the tools' documented formats.

There is no somatic nf-core/sarek run on disk (3.10.0 publishes germline only;
the `test_full` profile that runs CNVkit, ASCAT and Control-FREEC has to be
launched by hand), so the inputs here are written from the published column
contracts rather than sampled from a run:

* CNVkit "File formats": ``.cnr`` = chromosome, start, end, gene, depth, log2,
  weight; ``.cns`` = chromosome, start, end, gene, log2, depth, probes, weight,
  with cn / baf added by ``cnvkit call``.
* ASCAT ``ascat.output$segments`` -> ``.cnvs.txt`` = sample, chr, startpos,
  endpos, nMajor, nMinor; ``.purityploidy.txt`` = AberrantCellFraction, Ploidy.
* Control-FREEC "Output files": ``_ratio.txt`` = Chromosome, Start, Ratio,
  MedianRatio, CopyNumber, plus BAF, estimatedBAF, Genotype, UncertaintyOfGT
  when a SNV file was supplied.

Each test runs the recipe through ``execute_recipe`` (so the engine's own
schema checkpoint applies) and then validates the canonical ``cnv_profile``
binding against the produced schema, which is the contract the renderer reads.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.models.components.advanced_viz.configs import CnvProfileConfig
from depictio.models.components.advanced_viz.schemas import validate_binding
from depictio.recipes import execute_recipe
from depictio.recipes.lib.cnv_profile import LOG2_FLOOR

CNV_PROFILE_BINDING = CnvProfileConfig(
    sample_col="sample",
    chrom_col="chrom",
    start_col="start",
    end_col="end",
    log2_col="log2",
    baf_col="baf",
    copy_number_col="copy_number",
    segment_col="segment",
    label_col="label",
)


def _polars_schema_name(df: pl.DataFrame) -> dict[str, str]:
    return {name: str(dtype) for name, dtype in df.schema.items()}


def _assert_canonical(result: pl.DataFrame) -> None:
    """The produced frame satisfies the cnv_profile binding, roles and dtypes."""
    errors = validate_binding(CNV_PROFILE_BINDING, _polars_schema_name(result))
    assert errors == [], f"binding errors: {errors}"
    assert set(result["segment"].unique().to_list()) <= {"bin", "segment"}


# ---------------------------------------------------------------------------
# CNVkit: .cnr bins + .cns segments folded into one table
# ---------------------------------------------------------------------------


def _cnr(sample: str, n_bins: int = 6) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "chromosome": ["chr1"] * n_bins,
            "start": [i * 1000 for i in range(n_bins)],
            "end": [i * 1000 + 999 for i in range(n_bins)],
            "gene": ["-", "MYC", "-", "-", "PTEN", "-"][:n_bins],
            "depth": [40.0 + i for i in range(n_bins)],
            "log2": [0.02, 0.61, 0.58, -0.04, -1.15, -1.09][:n_bins],
            "weight": [0.9] * n_bins,
            "source_path": [f"variant_calling/cnvkit/{sample}/{sample}.cnr"] * n_bins,
        }
    )


def _cns(sample: str, *, called: bool) -> pl.DataFrame:
    frame = {
        "chromosome": ["chr1", "chr1", "chr1"],
        "start": [0, 1000, 4000],
        "end": [999, 3999, 5999],
        "gene": ["-", "MYC", "PTEN"],
        "log2": [0.02, 0.6, -1.12],
        "depth": [40.0, 45.0, 22.0],
        "probes": [1, 3, 2],
        "weight": [0.9, 2.7, 1.8],
        "source_path": [f"variant_calling/cnvkit/{sample}/{sample}.call.cns"] * 3,
    }
    if called:
        frame["cn"] = [2, 3, 1]
        frame["baf"] = [0.5, 0.34, 0.02]
    return pl.DataFrame(frame)


def test_cnvkit_folds_bins_and_segments(tmp_path):
    result = execute_recipe(
        "cnvkit/cnv_profile.py",
        tmp_path,
        extra_sources={"bins": _cnr("TUMOUR1"), "segments": _cns("TUMOUR1", called=True)},
    )
    _assert_canonical(result)

    assert result["sample"].unique().to_list() == ["TUMOUR1"]
    counts = dict(result.group_by("segment").len().iter_rows())
    assert counts == {"bin": 6, "segment": 3}

    segments = result.filter(pl.col("segment") == "segment").sort("start")
    assert segments["copy_number"].to_list() == [2, 3, 1]
    assert segments["label"].to_list() == ["CN 2", "CN 3", "CN 1"]
    assert segments["baf"].to_list() == [0.5, 0.34, 0.02]

    # The gene annotation becomes the hover label; CNVkit's intergenic filler
    # does not.
    bins = result.filter(pl.col("segment") == "bin").sort("start")
    assert bins["label"].to_list() == [None, "MYC", None, None, "PTEN", None]
    assert bins["depth"].to_list()[0] == pytest.approx(40.0)


def test_cnvkit_without_call_still_renders(tmp_path):
    """A plain `cnvkit segment` run has neither cn nor baf and still binds."""
    result = execute_recipe(
        "cnvkit/cnv_profile.py",
        tmp_path,
        extra_sources={"bins": _cnr("TUMOUR1"), "segments": _cns("TUMOUR1", called=False)},
    )
    _assert_canonical(result)
    segments = result.filter(pl.col("segment") == "segment")
    assert segments["copy_number"].null_count() == segments.height
    assert segments["baf"].null_count() == segments.height
    assert segments["label"].to_list() == [None, "MYC", "PTEN"]


def test_cnvkit_accepts_bins_alone(tmp_path):
    """The segments source is optional: the evidence track renders on its own."""
    result = execute_recipe(
        "cnvkit/cnv_profile.py", tmp_path, extra_sources={"bins": _cnr("TUMOUR1")}
    )
    _assert_canonical(result)
    assert result["segment"].unique().to_list() == ["bin"]


def test_cnvkit_needs_the_scanned_path(tmp_path):
    bins = _cnr("TUMOUR1").drop("source_path")
    with pytest.raises(Exception, match="include_file_paths"):
        execute_recipe("cnvkit/cnv_profile.py", tmp_path, extra_sources={"bins": bins})


def test_cnvkit_decimates_bins_but_never_segments(tmp_path, monkeypatch):
    """Over the cap the bins are averaged into windows; the calls survive whole."""
    import depictio.recipes.lib.cnv_profile as cnv_lib

    monkeypatch.setattr(cnv_lib, "DEFAULT_MAX_BINS", 3)
    n = 12
    bins = pl.DataFrame(
        {
            "chromosome": ["chr1"] * n,
            "start": [i * 1000 for i in range(n)],
            "end": [i * 1000 + 999 for i in range(n)],
            "gene": ["-"] * n,
            "depth": [30.0] * n,
            "log2": [float(i) for i in range(n)],
            "weight": [1.0] * n,
            "source_path": ["variant_calling/cnvkit/TUMOUR1/TUMOUR1.cnr"] * n,
        }
    )
    result = execute_recipe(
        "cnvkit/cnv_profile.py",
        tmp_path,
        extra_sources={"bins": bins, "segments": _cns("TUMOUR1", called=True)},
    )
    kept = result.filter(pl.col("segment") == "bin")
    assert kept.height <= 3
    # The window keeps the span it covers, and its log2 is the window mean.
    first = kept.sort("start").row(0, named=True)
    assert first["start"] == 0
    assert first["end"] == 3999
    assert first["log2"] == pytest.approx(1.5)
    assert result.filter(pl.col("segment") == "segment").height == 3


# ---------------------------------------------------------------------------
# ASCAT: allele-specific segments, purity and ploidy
# ---------------------------------------------------------------------------


def _ascat_segments(*, with_sample_column: bool) -> pl.DataFrame:
    frame = {
        "chr": ["chr1", "chr1", "chr2", "chr2"],
        "startpos": [1, 500_001, 1, 200_001],
        "endpos": [500_000, 900_000, 200_000, 400_000],
        # balanced diploid, a 3+1 gain, copy-neutral LOH (2+0), a full loss
        "nMajor": [1, 3, 2, 0],
        "nMinor": [1, 1, 0, 0],
        "source_path": ["variant_calling/ascat/TUMOUR1/TUMOUR1.cnvs.txt"] * 4,
    }
    if with_sample_column:
        frame["sample"] = ["TUMOUR1"] * 4
    return pl.DataFrame(frame)


def test_ascat_segments_derive_log2_and_baf(tmp_path):
    result = execute_recipe(
        "ascat/cnv_segments.py",
        tmp_path,
        extra_sources={"segments": _ascat_segments(with_sample_column=True)},
    )
    _assert_canonical(result)
    assert result["segment"].unique().to_list() == ["segment"]

    by_pos = result.sort(["chrom", "start"])
    assert by_pos["copy_number"].to_list() == [2, 4, 2, 0]
    assert by_pos["log2"].to_list() == pytest.approx([0.0, 1.0, 0.0, LOG2_FLOOR])
    # Copy-neutral LOH: total copy number does not move, the BAF does.
    assert by_pos["baf"].to_list() == pytest.approx([0.5, 0.25, 0.0, None], nan_ok=True)
    assert by_pos["label"].to_list() == ["1+1", "3+1", "2+0", "0+0"]


def test_ascat_recovers_the_sample_from_the_path(tmp_path):
    result = execute_recipe(
        "ascat/cnv_segments.py",
        tmp_path,
        extra_sources={"segments": _ascat_segments(with_sample_column=False)},
    )
    assert result["sample"].unique().to_list() == ["TUMOUR1"]


def test_ascat_purity_ploidy(tmp_path):
    raw = pl.DataFrame(
        {
            "AberrantCellFraction": [0.62],
            "Ploidy": [2.84],
            "source_path": ["variant_calling/ascat/TUMOUR1/TUMOUR1.purityploidy.txt"],
        }
    )
    result = execute_recipe("ascat/purity_ploidy.py", tmp_path, extra_sources={"purityploidy": raw})
    assert result.to_dicts() == [{"sample": "TUMOUR1", "purity": 0.62, "ploidy": 2.84}]


# ---------------------------------------------------------------------------
# Control-FREEC: ratio windows plus the segments their MedianRatio runs encode
# ---------------------------------------------------------------------------


def _freec_ratio(*, with_baf: bool) -> pl.DataFrame:
    # Six 50 kb windows on one chromosome: two neutral, two gained, two lost.
    # MedianRatio is the segment value Control-FREEC writes on every window.
    frame = {
        "Chromosome": ["chr1"] * 6,
        "Start": [1, 50_001, 100_001, 150_001, 200_001, 250_001],
        "Ratio": [1.02, 0.97, 1.48, 1.52, 0.48, 0.52],
        "MedianRatio": [1.0, 1.0, 1.5, 1.5, 0.5, 0.5],
        "CopyNumber": [2, 2, 3, 3, 1, 1],
        "source_path": ["variant_calling/controlfreec/TUMOUR1/TUMOUR1_ratio.txt"] * 6,
    }
    if with_baf:
        frame["BAF"] = [0.49, 0.51, 0.33, 0.34, -1.0, 0.02]
        frame["estimatedBAF"] = [0.5, 0.5, 0.333, 0.333, -1.0, 0.0]
        frame["Genotype"] = ["AB", "AB", "AAB", "AAB", "-", "A"]
        frame["UncertaintyOfGT"] = [0.0, 0.0, 0.1, 0.1, -1.0, 0.0]
    return pl.DataFrame(frame)


def test_controlfreec_windows_and_recovered_segments(tmp_path):
    result = execute_recipe(
        "controlfreec/cnv_ratio.py", tmp_path, extra_sources={"ratio": _freec_ratio(with_baf=True)}
    )
    _assert_canonical(result)

    counts = dict(result.group_by("segment").len().iter_rows())
    assert counts == {"bin": 6, "segment": 3}

    segments = result.filter(pl.col("segment") == "segment").sort("start")
    assert segments["copy_number"].to_list() == [2, 3, 1]
    assert segments["label"].to_list() == ["CN 2", "CN 3", "CN 1"]
    # The window size is measured off the data, so a segment ends at the last
    # window it covers.
    assert segments["start"].to_list() == [1, 100_001, 200_001]
    assert segments["end"].to_list() == [100_000, 200_000, 300_000]
    assert segments["log2"].to_list() == pytest.approx([0.0, 0.5849625007, -1.0])

    bins = result.filter(pl.col("segment") == "bin").sort("start")
    # Control-FREEC's -1 sentinel is a missing BAF, not a BAF of -1.
    assert bins["baf"].to_list()[4] is None


def test_controlfreec_without_baf(tmp_path):
    result = execute_recipe(
        "controlfreec/cnv_ratio.py", tmp_path, extra_sources={"ratio": _freec_ratio(with_baf=False)}
    )
    _assert_canonical(result)
    assert result["baf"].null_count() == result.height


def test_controlfreec_floors_a_homozygous_deletion(tmp_path):
    raw = pl.DataFrame(
        {
            "Chromosome": ["chr1", "chr1"],
            "Start": [1, 50_001],
            "Ratio": [0.0, 0.0],
            "MedianRatio": [0.0, 0.0],
            "CopyNumber": [0, 0],
            "source_path": ["variant_calling/controlfreec/TUMOUR1/TUMOUR1_ratio.txt"] * 2,
        }
    )
    result = execute_recipe("controlfreec/cnv_ratio.py", tmp_path, extra_sources={"ratio": raw})
    assert result["log2"].unique().to_list() == [LOG2_FLOOR]


def test_controlfreec_needs_the_scanned_path(tmp_path):
    raw = _freec_ratio(with_baf=False).drop("source_path")
    with pytest.raises(Exception, match="include_file_paths"):
        execute_recipe("controlfreec/cnv_ratio.py", tmp_path, extra_sources={"ratio": raw})
