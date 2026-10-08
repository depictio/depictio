"""P20: ``RecipeSource.source_path`` hands each row the file it came from.

rnafusion's per-sample fusion tables carry no sample column; a recipe declaring
``source_path`` can derive it from ``<tool>/<sample>.<tool>.fusions.tsv``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from depictio.models.models.transforms import RecipeSource
from depictio.recipes import RecipeError, resolve_sources


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_glob_source_gets_per_file_path_and_recipe_derives_sample(tmp_path: Path) -> None:
    _write(tmp_path / "arriba" / "S1.arriba.fusions.tsv", "gene1\tgene2\nA\tB\nC\tD\n")
    _write(tmp_path / "arriba" / "S2.arriba.fusions.tsv", "gene1\tgene2\nE\tF\n")
    module = SimpleNamespace(
        SOURCES=[
            RecipeSource(
                ref="arriba",
                glob_pattern="arriba/*.arriba.fusions.tsv",
                format="TSV",
                source_path="source_path",
            )
        ]
    )

    df = resolve_sources(module, tmp_path)["arriba"]

    assert df["source_path"].to_list() == [
        "arriba/S1.arriba.fusions.tsv",
        "arriba/S1.arriba.fusions.tsv",
        "arriba/S2.arriba.fusions.tsv",
    ]
    # What a recipe does with it.
    sample = df.select(pl.col("source_path").str.extract(r"([^/]+)\.arriba\.fusions\.tsv$"))
    assert sample.to_series().to_list() == ["S1", "S1", "S2"]


def test_single_file_source_gets_constant_path(tmp_path: Path) -> None:
    _write(tmp_path / "summary" / "run.csv", "a,b\n1,2\n")
    module = SimpleNamespace(
        SOURCES=[RecipeSource(ref="s", path="summary/run.csv", format="csv", source_path="file")]
    )
    df = resolve_sources(module, tmp_path)["s"]
    assert df.columns == ["a", "b", "file"]
    assert df["file"].to_list() == ["summary/run.csv"]


def test_source_path_absent_by_default(tmp_path: Path) -> None:
    _write(tmp_path / "x.csv", "a\n1\n")
    module = SimpleNamespace(SOURCES=[RecipeSource(ref="s", path="x.csv", format="csv")])
    assert resolve_sources(module, tmp_path)["s"].columns == ["a"]


def test_source_path_refuses_to_shadow_a_real_column(tmp_path: Path) -> None:
    _write(tmp_path / "x.csv", "sample,a\nS1,1\n")
    module = SimpleNamespace(
        SOURCES=[RecipeSource(ref="s", path="x.csv", format="csv", source_path="sample")]
    )
    with pytest.raises(RecipeError, match="already exists"):
        resolve_sources(module, tmp_path)
