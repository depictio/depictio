"""nf-core/quantms recipes: the short run label and the share of runs per protein group."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema


def _design() -> pl.DataFrame:
    rows = [
        ("1", "1", "run_alpha_long_file_name_1.raw", "label free sample", "1"),
        ("1", "1", "run_alpha_long_file_name_2.raw", "label free sample", "2"),
        ("1", "1", "run_beta_long_file_name_1.raw", "label free sample", "3"),
        (None, None, None, None, None),
        ("Sample", "MSstats_Condition", "MSstats_BioReplicate", None, None),
        ("1", "CT=A;QY=1", "1", None, None),
        ("2", "CT=A;QY=1", "2", None, None),
        ("3", "CT=A;QY=2", "1", None, None),
    ]
    return pl.DataFrame(
        {f"c{i}": [r[i] for r in rows] for i in range(5)},
        schema={f"c{i}": pl.Utf8 for i in range(5)},
    )


@pytest.mark.no_db
def test_hub_carries_a_short_run_label() -> None:
    module = load_recipe("nf-core/quantms/samples.py")
    out = module.transform({"design": _design(), "config": None, "sdrf": None})
    validate_schema(out, module.OUTPUT_SCHEMA, "samples", module.OPTIONAL_OUTPUT_SCHEMA)
    labels = dict(zip(out["run_id"].to_list(), out["run_label"].to_list(), strict=True))
    assert labels == {
        "run_alpha_long_file_name_1": "1 #1",
        "run_alpha_long_file_name_2": "1 #2",
        "run_beta_long_file_name_1": "2 #1",
    }
    assert max(len(v) for v in labels.values()) < 10


@pytest.mark.no_db
def test_protein_summary_gives_the_share_of_runs() -> None:
    module = load_recipe("nf-core/quantms/protein_summary.py")
    rows = [("r1", "P1"), ("r2", "P1"), ("r3", "P1"), ("r1", "P2"), ("r2", "P2"), ("r1", "P3")]
    proteins = pl.DataFrame(
        {
            "run_id": [r[0] for r in rows],
            "protein_group": [r[1] for r in rows],
            "protein_name": ["n"] * len(rows),
            "genes": ["g"] * len(rows),
            "intensity": [1000.0] * len(rows),
            "log2_intensity": [10.0] * len(rows),
        }
    )
    out = module.transform({"proteins": proteins, "precursors": None})
    validate_schema(out, module.OUTPUT_SCHEMA, "quantms_protein_summary", None)
    share = dict(zip(out["protein_group"].to_list(), out["detected_pct"].to_list(), strict=True))
    assert share == {"P1": 100.0, "P2": 66.67, "P3": 33.33}
    assert out.filter(pl.col("detected_pct") == 100.0)["detection"].to_list() == ["All runs"]
