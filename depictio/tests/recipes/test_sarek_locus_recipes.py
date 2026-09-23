"""sarek 3.10.0 pipeline-local recipes added for the wave 2 locus section.

Each is exercised on a few hand-built rows shaped like its source collection,
and checked against its own EXPECTED_SCHEMA through `validate_schema`, which is
what ingest enforces.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema

VERSION = "3.10.0"


def _run(name: str, sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    module = load_recipe(f"nf-core/sarek/{name}", VERSION)
    out = module.transform(sources)
    validate_schema(out, module.EXPECTED_SCHEMA, name, getattr(module, "OPTIONAL_SCHEMA", None))
    return out


def _sections() -> pl.DataFrame:
    rows = [
        ("S1", "hc", "substitution", None, "C>T", 30),
        ("S1", "hc", "substitution", None, "G>A", 30),
        ("S1", "hc", "substitution", None, "A>C", 20),
        ("S1", "hc", "substitution", None, "T>C", 20),
        ("S1", "manta", "substitution", None, "C>T", 0),
        ("S1", "hc", "indel_length", -2.0, None, 10),
        ("S1", "hc", "indel_length", 1.0, None, 30),
        ("S1", "hc", "indel_length", 45.0, None, 10),
        ("S1", "manta", "indel_length", 60.0, None, 5),
        ("S1", "hc", "quality", 30.0, None, 99),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "sample": pl.Utf8,
            "caller": pl.Utf8,
            "section": pl.Utf8,
            "bin": pl.Float64,
            "label": pl.Utf8,
            "count": pl.Int64,
        },
        orient="row",
    )


def test_substitution_spectrum_folds_strands_and_drops_empty_callsets():
    out = _run("substitution_spectrum.py", {"sections": _sections()})
    assert out["caller"].unique().to_list() == ["hc"]
    by_class = dict(zip(out["substitution_class"], out["fraction"], strict=True))
    assert by_class["C>T"] == pytest.approx(0.6)  # C>T + G>A folded together
    assert by_class["T>G"] == pytest.approx(0.2)  # A>C folded onto T>G
    assert set(out.filter(pl.col("mutation_class") == "transition")["substitution_class"]) == {
        "C>T",
        "T>C",
    }


def test_indel_spectrum_keeps_the_window_and_the_full_denominator():
    out = _run("indel_spectrum.py", {"sections": _sections()})
    assert out["caller"].unique().to_list() == ["hc"]  # manta has nothing within 20 bp
    assert out["length"].to_list() == [-2, 1]
    assert out["fraction"].sum() == pytest.approx(0.8)  # the 45 bp event stays in the total
    assert out.filter(pl.col("length") < 0)["indel_class"].to_list() == ["deletion"]


def test_mosdepth_targets_keeps_one_row_per_primary_target():
    raw = pl.DataFrame(
        {
            "chrom": ["chr17", "chr17", "chrUn_KI270742v1"],
            "start": ["100", "500", "1"],
            "end": ["300", "900", "50"],
            "coverage": ["30.5", "12.0", "4.0"],
            "source_path": ["/r/NA1.recal.regions.bed.gz"] * 3,
        }
    )
    out = _run("mosdepth_targets.py", {"regions": raw})
    assert out.height == 2
    assert out["sample_stage"].unique().to_list() == ["NA1 (recal)"]
    assert out["target_bp"].to_list() == [200, 400]
    assert out["chrom"].to_list() == ["chr17", "chr17"]


def test_mosdepth_windows_renames_onto_the_shared_coordinate_names():
    regions = pl.DataFrame(
        {
            "chromosome": ["chr17"],
            "position": [7_000_000],
            "end": [8_000_000],
            "value": [95.5],
            "sample": ["NA1"],
            "stage": ["recal"],
            "sample_stage": ["NA1 (recal)"],
            "n_targets": [120],
        }
    )
    out = _run("mosdepth_windows.py", {"regions": regions})
    assert out.columns[:4] == ["chrom", "pos", "end", "depth"]
    assert out.row(0) == (
        "chr17",
        7_000_000,
        8_000_000,
        95.5,
        "NA1",
        "recal",
        "NA1 (recal)",
        120,
    )


def test_callset_qc_joins_the_three_sources_and_drops_snv_free_callsets():
    summary = pl.DataFrame(
        {
            "sample": ["S1", "S1"],
            "caller": ["hc", "manta"],
            "n_records": [100, 10],
            "n_snps": [90, 0],
            "snp_fraction": [0.9, 0.0],
            "n_multiallelic_sites": [2, 0],
        }
    )
    tstv = pl.DataFrame({"sample": ["S1", "S1"], "caller": ["hc", "manta"], "ts_tv": [2.5, 0.0]})
    variants = pl.DataFrame(
        {
            "sample": ["S1"] * 4,
            "caller": ["hc"] * 4,
            "is_pass": [True, True, True, False],
            "gt": ["0/1", "0/1", "1/1", "0/1"],
            "dp": [10, 20, 30, 40],
            "vaf": [0.4, 0.5, 1.0, 0.1],
        }
    )
    out = _run("callset_qc.py", {"summary": summary, "tstv": tstv, "variants": variants})
    assert out["callset"].to_list() == ["S1 / hc"]
    row = out.row(0, named=True)
    assert row["pass_pct"] == pytest.approx(75.0)
    assert row["het_hom_ratio"] == pytest.approx(2.0)
    assert row["median_het_vaf"] == pytest.approx(0.45)
    assert row["multiallelic_pct"] == pytest.approx(2.0)
