"""A library with no observed effort has no effort multiple, not an infinite one."""

from __future__ import annotations

from pathlib import Path

from depictio.recipes import execute_recipe


def test_zero_observed_effort_yields_a_null_multiple(tmp_path: Path) -> None:
    (tmp_path / "nonpareil").mkdir()
    (tmp_path / "nonpareil" / "nonpareil_all_samples.tsv").write_text(
        "kappa\tC\tLR\tmodelR\tLRstar\tdiversity\n"
        "LIB_A\t0.5\t0.6\t1000.0\t0.99\t4000.0\t17.0\n"
        "LIB_B\t0.5\t0.0\t0.0\t0.99\t4000.0\t17.0\n"
    )
    out = execute_recipe("nonpareil/summary.py", tmp_path).sort("library")
    assert out["effort_multiple"].to_list() == [4.0, None]
