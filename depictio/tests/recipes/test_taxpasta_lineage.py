"""The kraken-style reports are found at whatever depth a pipeline publishes them.

A glob pinned to two directory levels matched nothing on a flat layout, and the
recipe then stamped ``unresolved`` on all seven ranks without a word. Now the
glob is recursive and a run whose reports resolve no lineage at all fails loudly.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.catalog.taxpasta import lineage
from depictio.recipes import execute_recipe

_REPORT = (
    " 10.00\t100\t100\tU\t0\tunclassified\n"
    " 90.00\t900\t0\tR\t1\troot\n"
    " 90.00\t900\t0\tD\t2\t  Bacteria\n"
    " 80.00\t800\t0\tP\t1224\t    Pseudomonadota\n"
    " 70.00\t700\t700\tG\t561\t      Escherichia\n"
)


def _profiles() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "profiler": ["kraken2"] * 2,
            "database": ["db"] * 2,
            "profiler_db": ["kraken2 db"] * 2,
            "sample": ["S1"] * 2,
            "platform": ["ILLUMINA"] * 2,
            "taxonomy_id": ["561", "0"],
            "name": ["Escherichia", "unclassified"],
            "rank": ["genus", "unclassified"],
            "count": [700.0, 100.0],
            "rel_abundance": [0.7, 0.1],
        }
    )


@pytest.mark.parametrize("depth", ["", "kraken2/", "kraken2/db/"])
def test_reports_resolve_at_any_depth(tmp_path: Path, depth: str) -> None:
    report_dir = tmp_path / depth
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "S1_db.kraken2.report.txt").write_text(_REPORT)

    out = execute_recipe(
        "taxpasta/lineage.py", tmp_path, extra_sources={"profiles": _profiles()}
    ).sort("taxonomy_id")
    by_taxid = {row["taxonomy_id"]: row for row in out.iter_rows(named=True)}
    assert by_taxid["561"]["superkingdom"] == "Bacteria"
    assert by_taxid["561"]["phylum"] == "Pseudomonadota"
    assert by_taxid["561"]["genus"] == "Escherichia"
    assert by_taxid["0"]["genus"] == lineage.UNCLASSIFIED


def test_no_lineage_at_all_is_an_error_not_seven_unresolved_columns() -> None:
    with pytest.raises(ValueError, match="no kraken2 / krakenuniq report"):
        lineage.transform({"profiles": _profiles(), "reports": None})
