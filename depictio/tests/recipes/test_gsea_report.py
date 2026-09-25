"""`gsea/report.py`: GSEA's report tables, stacked and labelled from their file names.

The reports are read as text and cast here; a cell GSEA left as ``NA`` must
land as a null, not abort the whole contrast.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe

RECIPE = "gsea/report.py"
KO = "tables/gsea/Condition_genotype_WT_KO/Condition_genotype_WT_KO.gsea_report_for_KO.tsv"
WT = "tables/gsea/Condition_genotype_WT_KO/Condition_genotype_WT_KO.gsea_report_for_WT.tsv"


def _report(path: str, rows: list[dict]) -> pl.DataFrame:
    columns = ["NAME", "SIZE", "ES", "NES", "NOM p-val", "FDR q-val", "FWER p-val", "RANK AT MAX"]
    frame = {c: [str(r[c]) for r in rows] for c in columns}
    frame["LEADING EDGE"] = [r["LEADING EDGE"] for r in rows]
    frame["source_path"] = [path] * len(rows)
    return pl.DataFrame(frame)


def _row(name: str, **cells: object) -> dict:
    base = {
        "NAME": name,
        "SIZE": 40,
        "ES": 0.5,
        "NES": 1.8,
        "NOM p-val": 0.01,
        "FDR q-val": 0.05,
        "FWER p-val": 0.2,
        "RANK AT MAX": 1200,
        "LEADING EDGE": "tags=51%, list=30%, signal=72%",
    }
    base.update(cells)
    return base


def test_an_na_cell_lands_as_a_null_and_the_other_rows_survive(tmp_path: Path) -> None:
    report = pl.concat(
        [
            _report(KO, [_row("SET_A"), _row("SET_B", **{"FDR q-val": "NA", "SIZE": "NA"})]),
            _report(WT, [_row("SET_C", NES=-1.2, **{"RANK AT MAX": "NA"})]),
        ]
    )
    out = execute_recipe(RECIPE, tmp_path, extra_sources={"report": report})

    assert out.height == 3
    by_term = {r["term"]: r for r in out.to_dicts()}
    assert by_term["SET_B"]["fdr_qvalue"] is None
    assert by_term["SET_B"]["size"] is None
    assert by_term["SET_B"]["neg_log10_fdr"] is None
    assert by_term["SET_C"]["rank_at_max"] is None
    assert by_term["SET_A"]["size"] == 40
    assert by_term["SET_A"]["leading_edge_percent"] == 51.0
    assert (by_term["SET_A"]["contrast"], by_term["SET_A"]["phenotype"]) == (
        "Condition_genotype_WT_KO",
        "KO",
    )
    assert by_term["SET_C"]["phenotype"] == "WT"
