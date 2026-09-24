"""smrnaseq recipes: mirtop expression, the sample hub, miRDeep2 result parsing."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema

# The scan the template's mirdeep2_results_raw DC declares: one text line per
# row, the file path alongside, exactly what the CLI hands the recipe.
_RAW_SCAN = {
    "separator": "\x1f",
    "has_header": False,
    "quote_char": None,
    "new_columns": ["raw"],
    "include_file_paths": "source_path",
    "infer_schema_length": 0,
}

_ANNOT = {
    "UID": ["u1", "u2", "u3", "u4"],
    "Read": ["AAA", "AAC", "CCC", "GGG"],
    "miRNA": ["mir-a", "mir-a", "mir-b", "mir-c"],
    "Variant": ["NA", "iso_3p:-1", "NA", "NA"],
}


def _joined() -> pl.DataFrame:
    return pl.DataFrame(
        {**_ANNOT, "s1": [60, 20, 20, 0], "s2": [10, 0, 90, 0]},
        schema_overrides={"s1": pl.Int64, "s2": pl.Int64},
    )


def _counts(metadata: pl.DataFrame | None = None) -> pl.DataFrame:
    module = load_recipe("mirtop/mirna_counts.py")
    out = module.transform({"joined": _joined(), "metadata": metadata})
    validate_schema(out, module.EXPECTED_SCHEMA, "mirtop_mirna_counts", None)
    return out


@pytest.mark.no_db
def test_mirna_counts_sum_isomirs_and_normalise_per_library():
    out = _counts()
    rows = {(r["sample"], r["mirna"]): r for r in out.to_dicts()}
    # A miRNA with no read in any sample is dropped.
    assert {m for _, m in rows} == {"mir-a", "mir-b"}
    a1 = rows[("s1", "mir-a")]
    assert a1["reads"] == 80
    assert a1["isomirs"] == 2
    assert a1["reference_pct"] == pytest.approx(75.0)
    assert a1["cpm"] == pytest.approx(800_000.0)
    assert rows[("s2", "mir-a")]["isomirs"] == 1
    assert out.width == 7  # no design columns without a metadata table


@pytest.mark.no_db
def test_mirna_counts_carry_the_design_when_given():
    metadata = pl.DataFrame({"sample": ["s1", "s2"], "condition": ["x", "y"], "reads": ["1", "2"]})
    out = _counts(metadata)
    assert "condition" in out.columns
    # A design column named like an output column never overwrites it.
    assert out.schema["reads"] == pl.Int64
    assert dict(out.select("sample", "condition").unique().iter_rows()) == {"s1": "x", "s2": "y"}


@pytest.mark.no_db
def test_sample_hub_without_optional_sources_or_design():
    module = load_recipe("nf-core/smrnaseq/samples.py")
    hub = module.transform({"counts": _counts(), "composition": None, "predictions": None})
    validate_schema(hub, module.EXPECTED_SCHEMA, "samples", None)
    assert hub["sample"].to_list() == ["s1", "s2"]
    s1 = hub.row(0, named=True)
    assert s1["mirna_reads"] == 100
    assert s1["mirnas_detected"] == 2
    assert s1["reference_isoform_pct"] == pytest.approx(80.0)
    assert s1["mirna_pct"] is None and s1["novel_candidates"] is None


@pytest.mark.no_db
def test_sample_hub_with_composition_predictions_and_design():
    counts = _counts(pl.DataFrame({"sample": ["s1", "s2"], "condition": ["x", "y"]}))
    composition = pl.DataFrame(
        {
            "sample": ["s1", "s1", "s1", "s1"],
            "rank": ["RNA type", "RNA type", "Clade", "Clade"],
            "taxon": ["miRNA", "rRNA", "Clade A", "Clade B"],
            "abundance": [70.0, 30.0, 9.0, 1.0],
            "percent": [70.0, 30.0, 90.0, 10.0],
        }
    )
    predictions = pl.DataFrame(
        {"sample": ["s1", "s1", "s2"], "category": ["novel", "known", "known"]}
    )
    module = load_recipe("nf-core/smrnaseq/samples.py")
    hub = module.transform(
        {"counts": counts, "composition": composition, "predictions": predictions}
    )
    rows = {r["sample"]: r for r in hub.to_dicts()}
    assert rows["s1"]["mirna_pct"] == pytest.approx(70.0)
    assert rows["s1"]["top_clade"] == "Clade A"
    assert rows["s1"]["novel_candidates"] == 1
    assert rows["s2"]["known_recovered"] == 1
    assert rows["s2"]["condition"] == "y"


_SCORE_HEADER = (
    "miRDeep2 score\tnovel miRNAs reported by miRDeep2\tnovel miRNAs, estimated false positives"
    "\tnovel miRNAs, estimated true positives\tknown miRNAs in species\tknown miRNAs in data"
    "\tknown miRNAs detected by miRDeep2\testimated signal-to-noise\texcision gearing"
)
_CALL_TAIL = (
    "\trfam alert\ttotal read count\tmature read count\tloop read count\tstar read count"
    "\tsignificant randfold p-value\t{mirbase}\texample miRBase miRNA with the same seed"
    "\tUCSC browser\tNCBI blastn\tconsensus mature sequence\tconsensus star sequence"
    "\tconsensus precursor sequence\tprecursor coordinate"
)


def _call(cid: str, score: str, mirbase: str, coord: str, star: str = "2") -> str:
    return (
        f"{cid}\t{score}\t51 +/- 42%\t-\t16\t14\t0\t{star}\tyes\t{mirbase}\t-\t-\t-"
        f"\taaagagaagc\tgccaucuccu\taaagagaagcuuuugccaucuccu\t{coord}"
    )


def _result_file(tmp_path: Path, sample: str, novel_start: int) -> Path:
    lines = [
        _SCORE_HEADER,
        "10\t1\t1 +/- 1\t0 +/- 0 (37 +/- 49%)\t2656\t988\t396 (40%)\t36.8\t2",
        "0\t34\t77 +/- 8\t0 +/- 0 (0 +/- 0%)\t2656\t988\t719 (73%)\t2.9\t2",
        "",
        "",
        "novel miRNAs predicted by miRDeep2",
        "provisional id\tmiRDeep2 score\testimated probability that the miRNA candidate is a"
        " true positive" + _CALL_TAIL.format(mirbase="miRBase miRNA"),
        _call("8_1", "9.2", "-", f"8:{novel_start}..{novel_start + 57}:-"),
        "",
        "mature miRBase miRNAs detected by miRDeep2",
        "tag id\tmiRDeep2 score\testimated probability that the miRNA is a true positive"
        + _CALL_TAIL.format(mirbase="mature miRBase miRNA"),
        _call("X_2", "116395.7", "mir-a", "X:100..170:-"),
        "",
        "#miRBase miRNAs not detected by miRDeep2",
        "mir-z\t",
    ]
    path = tmp_path / f"result_{sample}.csv"
    path.write_text("\n".join(lines) + "\n")
    return path


def _raw(tmp_path: Path) -> pl.DataFrame:
    files = [_result_file(tmp_path, "s1", 1000), _result_file(tmp_path, "s2", 1010)]
    return pl.concat([pl.scan_csv(f, **_RAW_SCAN).collect() for f in files])


@pytest.mark.no_db
def test_mirdeep2_predictions_parse_both_blocks(tmp_path: Path):
    module = load_recipe("mirdeep2/predictions.py")
    out = module.transform({"results": _raw(tmp_path)})
    validate_schema(out, module.EXPECTED_SCHEMA, "mirdeep2_predictions", None)
    assert out.height == 4
    assert sorted(out["sample"].unique().to_list()) == ["s1", "s2"]
    assert out.filter(pl.col("category") == "novel").height == 2
    known = out.filter(pl.col("category") == "known").row(0, named=True)
    assert known["mirbase_mirna"] == "mir-a"
    assert known["score"] == pytest.approx(116395.7)
    assert known["true_positive_pct"] == pytest.approx(51.0)
    assert (known["chromosome"], known["start"], known["end"], known["strand"]) == (
        "X",
        100,
        170,
        "-",
    )


@pytest.mark.no_db
def test_mirdeep2_score_summary_reads_the_cutoff_table(tmp_path: Path):
    module = load_recipe("mirdeep2/score_summary.py")
    out = module.transform({"results": _raw(tmp_path)})
    validate_schema(out, module.EXPECTED_SCHEMA, "mirdeep2_score_summary", None)
    s1 = out.filter(pl.col("sample") == "s1").sort("score_cutoff")
    assert s1["score_cutoff"].to_list() == [0.0, 10.0]
    top = s1.row(1, named=True)
    assert top["novel_reported"] == 1
    assert top["known_detected"] == 396
    # Recomputed from the counts (396 of 988 in data), not the rounded "(40%)".
    assert top["known_detected_pct"] == pytest.approx(396 * 100 / 988)
    assert top["signal_to_noise"] == pytest.approx(36.8)


@pytest.mark.no_db
def test_mirdeep2_novel_precursors_merge_overlapping_calls(tmp_path: Path):
    predictions = load_recipe("mirdeep2/predictions.py").transform({"results": _raw(tmp_path)})
    module = load_recipe("mirdeep2/novel_precursors.py")
    out = module.transform({"predictions": predictions})
    validate_schema(out, module.EXPECTED_SCHEMA, "mirdeep2_novel_precursors", None)
    # The two samples' novel calls overlap on one strand: one precursor.
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["samples_detected"] == 2
    assert row["calls"] == 2
    assert (row["start"], row["end"]) == (1000, 1067)
    # UCSC-style locus for the record card's genome browser link.
    assert row["genome_position"] == "chr8:1000-1067"
