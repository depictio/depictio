"""ORF calls from Ribo-TISH and RiboCode meet on one chrom:strand:stop key."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema


def _tish(rows: list[tuple[str, str, str, str, str]]) -> pl.DataFrame:
    """rows = (sample, Tid, GenomePos, TisType, RiboPvalue); one stop per transcript."""
    return pl.DataFrame(
        {
            "Gid": ["GENE1"] * len(rows),
            "Tid": [r[1] for r in rows],
            "Symbol": ["SYM1"] * len(rows),
            "GeneType": ["protein_coding"] * len(rows),
            "GenomePos": [r[2] for r in rows],
            "Stop": ["900"] * len(rows),
            "StartCodon": ["ATG"] * len(rows),
            "TisType": [r[3] for r in rows],
            "AALen": ["100"] * len(rows),
            "RiboPvalue": [r[4] for r in rows],
            "FrameQvalue": ["0.01"] * len(rows),
            "source_path": [f"orf_predictions/ribotish/{r[0]}_pred.txt" for r in rows],
        }
    )


@pytest.mark.no_db
def test_ribotish_collapses_start_sites_onto_the_stop_key():
    raw = _tish(
        [
            # Two starts of one ORF on the plus strand: the annotated start wins.
            ("lib1", "T1", "chr1:100-1000:+", "Extended", "0.001"),
            ("lib1", "T1", "chr1:200-1000:+", "Annotated", "0.01"),
            # Minus strand: the stop sits at the low end, shifted to 1-based.
            ("lib1", "T2", "chr2:500-900:-", "uORF", "0.02"),
        ]
    )
    module = load_recipe("ribotish/orfs.py")
    out = module.transform({"pred": raw})
    validate_schema(out, module.EXPECTED_SCHEMA, "ribotish_orfs", None)

    rows = {r["orf_id"]: r for r in out.to_dicts()}
    assert set(rows) == {"chr1:+:1000", "chr2:-:501"}
    plus = rows["chr1:+:1000"]
    assert plus["orf_class"] == "Annotated CDS"
    assert plus["start_sites"] == 2
    assert rows["chr2:-:501"]["orf_class"] == "Upstream ORF"
    assert out["sample"].unique().to_list() == ["lib1"]


@pytest.mark.no_db
def test_orf_overlap_flags_each_caller():
    def orfs(ids: list[str], klass: str, samples: list[str]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "sample": samples,
                "orf_id": ids,
                "gene_id": ["GENE1"] * len(ids),
                "gene_name": ["SYM1"] * len(ids),
                "gene_type": ["protein_coding"] * len(ids),
                "orf_class": [klass] * len(ids),
                "aa_length": [100] * len(ids),
            }
        )

    tish = orfs(["a:+:1", "a:+:1", "b:-:5"], "Annotated CDS", ["l1", "l2", "l1"])
    code = orfs(["b:-:5", "c:+:9"], "Upstream ORF", ["l1", "l1"])
    module = load_recipe("nf-core/riboseq/orf_overlap.py")
    out = module.transform({"ribotish": tish, "ribocode": code})
    validate_schema(out, module.EXPECTED_SCHEMA, "orf_overlap", None)

    rows = {r["orf_id"]: r for r in out.to_dicts()}
    assert (rows["a:+:1"]["ribotish"], rows["a:+:1"]["ribocode"]) == (1, 0)
    assert rows["a:+:1"]["ribotish_libraries"] == 2
    assert (rows["b:-:5"]["ribotish"], rows["b:-:5"]["ribocode"]) == (1, 1)
    assert rows["b:-:5"]["annotated_cds"] == 1  # either caller calling it annotated counts
    assert (rows["c:+:9"]["ribotish"], rows["c:+:9"]["ribocode"]) == (0, 1)

    # One caller absent: the other still fills the table.
    only = module.transform({"ribotish": tish})
    assert only["ribocode"].sum() == 0
    assert only.height == 2
