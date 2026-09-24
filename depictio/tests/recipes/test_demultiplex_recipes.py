"""nf-core/demultiplex recipes: bcl2fastq and BCL Convert parity, index-swap classes, library hub.

The same run (one lane, two libraries on a dual index, Undetermined reads with
a swapped pair, a foreign pair and a poly-G pair) is written once as a
bcl2fastq Stats.json and once as BCL Convert Reports CSVs. Both routes feed
the same template collections, so they must agree on the schema and on the
numbers a tile reads.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from depictio.recipes import load_recipe

RUN = "/data/run/L001/Stats/Stats.json"
REPORTS = "/data/210101_RUN/Reports"

STATS = {
    "Flowcell": "FC1",
    "ConversionResults": [
        {
            "LaneNumber": 1,
            "TotalClustersRaw": 1200,
            "TotalClustersPF": 1000,
            "Yield": 200000,
            "DemuxResults": [
                {
                    "SampleId": "libA",
                    "SampleName": "libA",
                    "IndexMetrics": [
                        {"IndexSequence": "AAAA+CCCC", "MismatchCounts": {"0": 540, "1": 60}}
                    ],
                    "NumberReads": 600,
                    "Yield": 120000,
                    "ReadMetrics": [
                        {
                            "ReadNumber": 1,
                            "Yield": 60000,
                            "YieldQ30": 54000,
                            "QualityScoreSum": 2100000,
                        },
                        {
                            "ReadNumber": 2,
                            "Yield": 60000,
                            "YieldQ30": 48000,
                            "QualityScoreSum": 1980000,
                        },
                    ],
                },
                {
                    "SampleId": "libB",
                    "SampleName": "libB",
                    "IndexMetrics": [
                        {"IndexSequence": "GGTT+TTGG", "MismatchCounts": {"0": 200, "1": 0}}
                    ],
                    "NumberReads": 200,
                    "Yield": 40000,
                    "ReadMetrics": [
                        {
                            "ReadNumber": 1,
                            "Yield": 20000,
                            "YieldQ30": 18000,
                            "QualityScoreSum": 700000,
                        },
                        {
                            "ReadNumber": 2,
                            "Yield": 20000,
                            "YieldQ30": 16000,
                            "QualityScoreSum": 660000,
                        },
                    ],
                },
            ],
            "Undetermined": {
                "NumberReads": 200,
                "Yield": 40000,
                "ReadMetrics": [
                    {"ReadNumber": 1, "Yield": 20000, "YieldQ30": 14000, "QualityScoreSum": 600000},
                    {"ReadNumber": 2, "Yield": 20000, "YieldQ30": 12000, "QualityScoreSum": 560000},
                ],
            },
        }
    ],
    "UnknownBarcodes": [
        {
            "Lane": 1,
            "Barcodes": {"AAAA+TTGG": 90, "CATG+GTAC": 60, "GGGG+GGGG": 30},
        }
    ],
}


def _raw_lines(text: str, path: str) -> pl.DataFrame:
    """What the text-scan DC hands a recipe: one line per row plus its file."""
    lines = text.splitlines()
    return pl.DataFrame({"raw": lines, "source_path": [path] * len(lines)})


def _stats_raw() -> pl.DataFrame:
    return _raw_lines(json.dumps(STATS, indent=2), RUN)


def _csv(text: str, name: str) -> pl.DataFrame:
    df = pl.read_csv(text.encode(), infer_schema_length=0)
    return df.with_columns(pl.lit(f"{REPORTS}/{name}").alias("source_path"))


def _bclconvert_sources() -> dict[str, pl.DataFrame]:
    demux = _csv(
        "Lane,SampleID,Index,# Reads,# Perfect Index Reads,# One Mismatch Index Reads\n"
        "1,libA,AAAA-CCCC,600,540,60\n"
        "1,libB,GGTT-TTGG,200,200,0\n"
        "1,Undetermined,,200,0,0\n",
        "Demultiplex_Stats.csv",
    )
    quality = _csv(
        "Lane,SampleID,index,index2,ReadNumber,Yield,YieldQ30,QualityScoreSum\n"
        "1,libA,AAAA,CCCC,1,60000,54000,2100000\n"
        "1,libA,AAAA,CCCC,2,60000,48000,1980000\n"
        "1,libB,GGTT,TTGG,1,20000,18000,700000\n"
        "1,libB,GGTT,TTGG,2,20000,16000,660000\n"
        "1,Undetermined,,,1,20000,14000,600000\n"
        "1,Undetermined,,,2,20000,12000,560000\n",
        "Quality_Metrics.csv",
    )
    unknown = _csv(
        "Lane,index,index2,# Reads\n1,AAAA,TTGG,90\n1,CATG,GTAC,60\n1,GGGG,GGGG,30\n",
        "Top_Unknown_Barcodes.csv",
    )
    return {"demux": demux, "quality": quality, "unknown": unknown}


def _run(recipe: str, sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    module = load_recipe(recipe)
    out = module.transform(sources)
    assert dict(out.schema) == dict(module.EXPECTED_SCHEMA), recipe
    return out


@pytest.mark.parametrize(
    "output", ["demux_stats", "lane_summary", "read_quality", "unknown_barcodes"]
)
def test_bcl2fastq_and_bclconvert_write_the_same_schema(output: str) -> None:
    bcl2 = load_recipe(f"bcl2fastq/{output}.py").EXPECTED_SCHEMA
    bclc = load_recipe(f"bclconvert/{output}.py").EXPECTED_SCHEMA
    assert dict(bcl2) == dict(bclc)


def test_demux_stats_agree_between_demultiplexers() -> None:
    a = _run("bcl2fastq/demux_stats.py", {"stats": _stats_raw()}).sort("sample")
    b = _run("bclconvert/demux_stats.py", _bclconvert_sources()).sort("sample")
    assert a["sample"].to_list() == b["sample"].to_list() == ["Undetermined", "libA", "libB"]
    assert a["reads"].to_list() == b["reads"].to_list() == [200, 600, 200]
    assert a["pct_of_lane"].to_list() == pytest.approx(b["pct_of_lane"].to_list())
    assert a["pct_of_lane"].to_list() == pytest.approx([20.0, 60.0, 20.0])
    assert a["pct_q30"].to_list() == pytest.approx(b["pct_q30"].to_list())
    lib_a = a.filter(pl.col("sample") == "libA").row(0, named=True)
    assert lib_a["index"] == "AAAA+CCCC"
    assert lib_a["pct_perfect_index"] == pytest.approx(90.0)
    assert a.filter(pl.col("is_undetermined"))["sample"].to_list() == ["Undetermined"]


def test_lane_summary_reports_the_undetermined_share() -> None:
    a = _run("bcl2fastq/lane_summary.py", {"stats": _stats_raw()})
    b = _run("bclconvert/lane_summary.py", _bclconvert_sources())
    for df in (a, b):
        row = df.row(0, named=True)
        assert row["lane_label"] == "Lane 1"
        assert row["n_libraries"] == 2
        assert row["undetermined_reads"] == 200
        assert row["pct_undetermined"] == pytest.approx(20.0)
    assert a.row(0, named=True)["pct_pf"] == pytest.approx(1000 / 1200 * 100)
    # BCL Convert reports no raw cluster count.
    assert b.row(0, named=True)["pct_pf"] is None


def test_unknown_barcodes_are_classed_by_the_indexes_in_use() -> None:
    expected = {
        "AAAA+TTGG": "Both indexes in use",
        "CATG+GTAC": "Neither index in use",
        "GGGG+GGGG": "Poly-G or N index",
    }
    for recipe, sources in (
        ("bcl2fastq/unknown_barcodes.py", {"stats": _stats_raw()}),
        ("bclconvert/unknown_barcodes.py", _bclconvert_sources()),
    ):
        out = _run(recipe, sources)
        got = dict(zip(out["barcode"].to_list(), out["swap_class"].to_list(), strict=True))
        assert got == expected, recipe
        top = out.filter(pl.col("rank") == 1).row(0, named=True)
        assert top["barcode"] == "AAAA+TTGG"
        assert top["pct_of_undetermined"] == pytest.approx(45.0)


def test_classify_single_sided_swaps() -> None:
    classify = load_recipe("bcl2fastq/unknown_barcodes.py").classify
    used_i7, used_i5 = {"AAAA"}, {"CCCC"}
    assert classify("AAAA", "GTAC", used_i7, used_i5)[2] == "Only i7 in use"
    assert classify("CATG", "CCCC", used_i7, used_i5)[2] == "Only i5 in use"
    assert classify("ANAA", "CCCC", used_i7, used_i5)[2] == "Poly-G or N index"


def test_library_hub_without_metadata_falls_back_to_one_group() -> None:
    demux = _run("bcl2fastq/demux_stats.py", {"stats": _stats_raw()})
    hub = load_recipe("nf-core/demultiplex/libraries.py").transform(
        {"demux": demux, "qc": None, "metadata": None}
    )
    assert sorted(hub["sample"].to_list()) == ["libA", "libB"]
    assert hub["__no_group__"].unique().to_list() == ["All libraries"]
    by = {r["sample"]: r for r in hub.iter_rows(named=True)}
    # An even share of 800 assigned reads over two libraries is 400.
    assert by["libA"]["pct_of_expected"] == pytest.approx(150.0)
    assert by["libB"]["pct_of_expected"] == pytest.approx(50.0)


def test_library_hub_passes_metadata_through_as_text() -> None:
    demux = _run("bcl2fastq/demux_stats.py", {"stats": _stats_raw()})
    metadata = pl.DataFrame(
        {"library": ["libA", "libB"], "group": ["g1", "g2"], "input_ng": [1, 100]}
    )
    hub = load_recipe("nf-core/demultiplex/libraries.py").transform(
        {"demux": demux, "qc": None, "metadata": metadata}
    )
    by = {r["sample"]: r for r in hub.iter_rows(named=True)}
    assert by["libA"]["group"] == "g1"
    assert by["libB"]["input_ng"] == "100"
    assert "__no_group__" not in hub.columns
