"""A key first seen after the hundredth report is still a column."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from depictio.recipes import execute_recipe
from depictio.recipes.lib.nanoplot import RAW_LINE_COL, SOURCE_PATH_COL


def test_late_keys_are_not_dropped_by_schema_inference(tmp_path: Path) -> None:
    paths: list[str] = []
    lines: list[str] = []
    for i in range(101):
        path = f"nanoplot/fastq/s{i:03d}/NanoStats.txt"
        text = ["General summary:", "Number of reads:\t10.0"]
        if i == 100:
            text += ["Top 5 longest reads and their mean basecall quality score", "1:\t16679 (5.5)"]
        for line in text:
            paths.append(path)
            lines.append(line)
    raw = pl.DataFrame({SOURCE_PATH_COL: paths, RAW_LINE_COL: lines})

    out = execute_recipe("nanoplot/nanostats.py", tmp_path, extra_sources={"raw": raw})
    last = out.filter(pl.col("sample") == "s100").row(0, named=True)
    assert last["longest_read_length"] == 16679.0
    assert out["n_reads"].to_list() == [10.0] * 101
