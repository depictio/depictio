"""Ribo-seq recipes: anota2seq regulation and long form, Ribo-TISH ORFs and the caller overlap."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema

_ANALYSES = ("translated_mRNA", "total_mRNA", "translation", "buffering")


def _results(rows: dict[str, dict[str, tuple[float, float, float]]]) -> pl.DataFrame:
    """rows[analysis][gene] = (apvEff, apvSlope, apvRvmPAdj), all as strings like the reader."""
    frames = []
    for analysis in _ANALYSES:
        for gene, (eff, slope, padj) in rows.get(analysis, {}).items():
            frames.append(
                {
                    "gene_id": gene,
                    "apvEff": str(eff),
                    "apvSlope": str(slope),
                    "apvRvmP": str(padj / 10),
                    "apvRvmPAdj": str(padj),
                    "source_path": f"translational_efficiency/anota2seq/b_vs_a.{analysis}.anota2seq.results.tsv",
                }
            )
    return pl.DataFrame(frames)


@pytest.mark.no_db
def test_regulation_mode_follows_anota2seq_priority():
    ns = (0.0, 0.5, 0.9)
    raw = _results(
        {
            # G1: translation wins even though total and translated both move.
            "translation": {"G1": (1.0, 0.5, 0.01), "G2": (1.0, 3.0, 0.01), "G3": ns, "G4": ns},
            # G2: translation slope outside [-1, 2], so buffering decides.
            "buffering": {"G1": ns, "G2": (-0.8, 0.0, 0.01), "G3": ns, "G4": ns},
            # G3: both mRNA levels change in the same direction.
            "total_mRNA": {"G1": (1.0, 0.0, 0.01), "G2": ns, "G3": (-1.0, 0.0, 0.01), "G4": ns},
            "translated_mRNA": {
                "G1": (1.0, 0.0, 0.01),
                "G2": ns,
                "G3": (-1.2, 0.0, 0.01),
                "G4": (1.0, 0.0, 0.01),
            },
        }
    )
    genes = pl.DataFrame({"gene_id": ["G1", "G2"], "gene_name": ["ONE", "TWO"]})
    module = load_recipe("anota2seq/regulation.py")
    out = module.transform({"results": raw, "genes": genes})
    validate_schema(out, module.OUTPUT_SCHEMA, "regulation", None)

    rows = {r["gene_id"]: r for r in out.to_dicts()}
    assert rows["G1"]["regulation_mode"] == "translation"
    assert rows["G1"]["direction"] == "up"
    assert rows["G2"]["regulation_mode"] == "buffering"
    assert rows["G2"]["direction"] == "down"
    assert rows["G3"]["regulation_mode"] == "mRNA abundance"
    assert rows["G3"]["direction"] == "down"
    # Only the ribosome-bound level moves and translation is not called.
    assert rows["G4"]["regulation_mode"] == "not regulated"
    assert rows["G4"]["direction"] == "none"
    assert rows["G1"]["gene_name"] == "ONE"
    assert rows["G3"]["gene_name"] == "G3"  # no symbol: falls back to the id
    assert set(out["contrast"]) == {"b_vs_a"}


@pytest.mark.no_db
def test_results_long_form_labels_analyses_and_caps_zero_padj():
    raw = _results(
        {
            "translation": {"G1": (1.0, 0.5, 0.0), "G2": (0.1, 0.5, 0.01)},
            "total_mRNA": {"G1": (-1.0, 0.0, 0.5)},
        }
    )
    module = load_recipe("anota2seq/results.py")
    out = module.transform({"results": raw})
    validate_schema(out, module.OUTPUT_SCHEMA, "results", None)

    assert set(out["analysis"]) == {"Translation", "Total mRNA"}
    g1 = out.filter((pl.col("gene_id") == "G1") & (pl.col("analysis") == "Translation")).row(
        0, named=True
    )
    assert g1["neg_log10_padj"] == module.PADJ_ZERO_NEG_LOG10
    assert g1["direction"] == "up"
    # Below the 1.2-fold effect floor: not significant despite the small padj.
    g2 = out.filter(pl.col("gene_id") == "G2").row(0, named=True)
    assert g2["significant"] is False
    assert g2["direction"] == "not significant"


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
    validate_schema(out, module.OUTPUT_SCHEMA, "ribotish_orfs", None)

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
    validate_schema(out, module.OUTPUT_SCHEMA, "orf_overlap", None)

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
