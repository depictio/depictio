"""anota2seq tables: long form for the volcano, one regulatory mode per gene."""

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
    validate_schema(out, module.EXPECTED_SCHEMA, "regulation", None)

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
    validate_schema(out, module.EXPECTED_SCHEMA, "results", None)

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
