"""rnafusion's breakpoint pairs: the catalog's Arriba links plus the index and a browser rank.

The genome browser opens on the first call of ``arriba_fusion_links`` ordered by
``rank_score``. That single column has to put the highest Fusion Indication Index
first and, among the many fusions tied on it, the call with the most reads.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from depictio.recipes import execute_recipe

TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/rnafusion/4.1.3/template.yaml"

_HEADER = (
    "#gene1\tgene2\tstrand1(gene/fusion)\tstrand2(gene/fusion)\tbreakpoint1\tbreakpoint2\t"
    "site1\tsite2\ttype\tsplit_reads1\tsplit_reads2\tdiscordant_mates\tcoverage1\tcoverage2\t"
    "confidence\treading_frame\n"
)


def _call(g1: str, g2: str, split: int, mates: int, conf: str = "high") -> str:
    return (
        f"{g1}\t{g2}\t+/+\t+/+\tchr1:100:+\tchr2:200:+\tCDS\tCDS\ttranslocation\t"
        f"{split}\t0\t{mates}\t10\t10\t{conf}\tin-frame\n"
    )


def _consensus(rows: list[tuple[str, str, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": [r[0] for r in rows],
            "fusion": [r[1] for r in rows],
            "fii": [r[2] for r in rows],
        }
    )


def _evidence(rows: list[tuple[str, str, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": [r[0] for r in rows],
            "fusion": [r[1] for r in rows],
            "supporting_reads": [r[2] for r in rows],
        },
        schema={"sample": pl.Utf8, "fusion": pl.Utf8, "supporting_reads": pl.Int64},
    )


def _run(
    tmp_path: Path,
    calls: str,
    consensus: pl.DataFrame | None,
    evidence: pl.DataFrame | None = None,
) -> pl.DataFrame:
    (tmp_path / "arriba").mkdir()
    (tmp_path / "arriba" / "S1.arriba.fusions.tsv").write_text(_HEADER + calls, encoding="utf-8")
    extra = {}
    if consensus is not None:
        extra["consensus"] = consensus
    if evidence is not None:
        extra["evidence"] = evidence
    return execute_recipe("nf-core/rnafusion/breakpoint_links.py", tmp_path, extra_sources=extra)


def test_the_index_orders_first_and_the_reads_break_ties(tmp_path: Path) -> None:
    calls = (
        _call("AAA", "BBB", 5, 5)  # tied on the index, 10 reads
        + _call("CCC", "DDD", 40, 10)  # tied on the index, 50 reads
        + _call("EEE", "FFF", 900, 100)  # lower index, far more reads
    )
    consensus = _consensus(
        [("S1", "AAA--BBB", 1.0), ("S1", "CCC--DDD", 1.0), ("S1", "EEE--FFF", 0.167)]
    )
    df = _run(tmp_path, calls, consensus).sort("rank_score", descending=True)
    assert df["label"].to_list() == ["CCC--DDD", "AAA--BBB", "EEE--FFF"]
    assert df["fii"].to_list() == [1.0, 1.0, 0.167]
    assert df["rank_score"].dtype == pl.Int64
    assert df["rank_score"].n_unique() == 3


def test_the_reads_of_every_caller_break_ties_before_the_arriba_weight(tmp_path: Path) -> None:
    calls = (
        _call("AAA", "BBB", 50, 0)  # Arriba saw more, but the callers together saw less
        + _call("CCC", "DDD", 5, 0)
        + _call("CCC", "DDD", 3, 0)  # a second breakpoint of the same fusion
    )
    consensus = _consensus([("S1", "AAA--BBB", 1.0), ("S1", "CCC--DDD", 1.0)])
    evidence = _evidence([("S1", "AAA--BBB", 60), ("S1", "CCC--DDD", 400), ("S1", "CCC--DDD", 100)])
    df = _run(tmp_path, calls, consensus, evidence).sort("rank_score", descending=True)
    assert df["label"].to_list() == ["CCC--DDD", "CCC--DDD", "AAA--BBB"]
    # Within the fusion, its own breakpoints follow their read weight.
    assert df["weight"].to_list() == [5, 3, 50]
    assert df["rank_score"].n_unique() == 3


def test_keeps_the_catalog_columns_and_adds_two(tmp_path: Path) -> None:
    df = _run(tmp_path, _call("AAA", "BBB", 3, 4), _consensus([("S1", "AAA--BBB", 0.5)]))
    assert df.columns == [
        "sample",
        "label",
        "chrom_a",
        "pos_a",
        "chrom_b",
        "pos_b",
        "weight",
        "category",
        "confidence",
        "fii",
        "rank_score",
    ]
    assert df["weight"].to_list() == [7]
    assert df["rank_score"].to_list() == [500 * 1_000_000 * 1_000_000 + 7]


def test_a_call_the_consensus_does_not_list_ranks_last(tmp_path: Path) -> None:
    calls = _call("AAA", "BBB", 1, 0) + _call("CCC", "DDD", 90, 9)
    df = _run(tmp_path, calls, _consensus([("S1", "AAA--BBB", 0.167)]))
    unlisted = df.filter(pl.col("label") == "CCC--DDD")
    assert unlisted["fii"].to_list() == [0.0]
    assert df.sort("rank_score", descending=True)["label"].to_list()[0] == "AAA--BBB"


def test_the_consensus_is_optional(tmp_path: Path) -> None:
    df = _run(tmp_path, _call("AAA", "BBB", 2, 1), None)
    assert df["fii"].to_list() == [0.0]
    assert df["rank_score"].to_list() == [3]


def test_template_binds_the_recipe_and_documents_the_new_columns() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    dcs = {
        dc["data_collection_tag"]: dc for wf in raw["workflows"] for dc in wf["data_collections"]
    }
    links = dcs["arriba_fusion_links"]
    assert links["config"]["transform"]["recipe"] == "nf-core/rnafusion/breakpoint_links.py"
    described = links["config"]["dc_specific_properties"]["columns_description"]
    assert {"fii", "rank_score"} <= set(described)
    order = [dc for wf in raw["workflows"] for dc in wf["data_collections"]]
    tags = [dc["data_collection_tag"] for dc in order]
    # The recipe reads the consensus, which therefore comes first.
    assert tags.index("fusion_consensus") < tags.index("arriba_fusion_links")
