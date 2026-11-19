"""A one-line-per-row scan is read back in each file's own line order.

A raw text collection is scanned with each row's line number in its file
(``source_line``). A Delta table does not promise to keep the order its rows
were written in, so the recipe engine puts each file's lines back in that
order before a recipe reads them, then drops the column.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import polars as pl
import pytest
import yaml

import depictio.recipes as recipes
from depictio.models.models.transforms import RecipeSource
from depictio.recipes import SOURCE_LINE_COLUMN, in_file_order

PROJECTS = Path(recipes.__file__).resolve().parents[1] / "projects"


def scan(*files: tuple[str, list[str]], run: str | None = None) -> pl.DataFrame:
    """The rows a template's raw scan gives, files in this order."""
    frame = pl.concat(
        [
            pl.DataFrame(
                {
                    SOURCE_LINE_COLUMN: list(range(1, len(lines) + 1)),
                    "raw": lines,
                    "source_path": path,
                },
                schema_overrides={SOURCE_LINE_COLUMN: pl.UInt32},
            )
            for path, lines in files
        ]
    )
    return frame.with_columns(depictio_run_id=pl.lit(run)) if run else frame


ALN = ("a.aln", [">s1", "AAAA", ">s2", "CCCC"])
HMM = ("b.hmm", ["HMMER3/f", "NAME b", "//"])


def test_a_scan_in_order_is_only_stripped_of_its_line_numbers():
    raw = scan(ALN, HMM)
    assert in_file_order(raw).equals(raw.drop(SOURCE_LINE_COLUMN))


def test_a_rotated_file_gets_its_lines_back_in_order():
    raw = scan(ALN, HMM)
    # File a split over two written batches that came back swapped.
    stored = pl.concat([raw.slice(2, 5), raw.slice(0, 2)])
    assert in_file_order(stored).equals(raw.drop(SOURCE_LINE_COLUMN))


def test_files_stay_where_their_first_line_was():
    raw = scan(HMM, ALN)
    stored = pl.concat([raw.slice(1, 1), raw.slice(0, 1), raw.slice(2, 5)])
    back = in_file_order(stored)
    assert back["source_path"].unique(maintain_order=True).to_list() == ["b.hmm", "a.aln"]
    assert back.equals(raw.drop(SOURCE_LINE_COLUMN))


def test_a_file_shared_by_two_runs_is_put_in_order_per_run():
    one, two = scan(ALN, run="run_1"), scan(ALN, run="run_2")
    stored = pl.concat([one.slice(2, 2), two, one.slice(0, 2)])
    back = in_file_order(stored)
    assert back.filter(pl.col("depictio_run_id") == "run_1").equals(one.drop(SOURCE_LINE_COLUMN))
    assert back.filter(pl.col("depictio_run_id") == "run_2").equals(two.drop(SOURCE_LINE_COLUMN))


def test_rows_no_scan_numbered_are_left_where_they_are():
    # Rows written before scans numbered their lines merge in as nulls.
    raw = scan(ALN).with_columns(pl.lit(None, dtype=pl.UInt32).alias(SOURCE_LINE_COLUMN))
    stored = raw.reverse()
    assert in_file_order(stored).equals(stored.drop(SOURCE_LINE_COLUMN))


@pytest.mark.parametrize("frame", [None, pl.DataFrame({"raw": ["x"], "source_path": "a"})])
def test_a_frame_without_line_numbers_is_returned_as_is(frame):
    assert in_file_order(frame) is frame


def test_a_recipe_reads_its_raw_source_in_file_order(monkeypatch, tmp_path):
    seen: dict[str, pl.DataFrame] = {}
    module = ModuleType("fake_raw_recipe")
    module.SOURCES = [  # type: ignore[attr-defined]
        RecipeSource(
            ref="alignments",
            dc_ref="famsa_alignment_raw",
            input_schema={"raw": pl.Utf8, "source_path": pl.Utf8},
        )
    ]
    module.OUTPUT_SCHEMA = {"n": pl.Int64}  # type: ignore[attr-defined]

    def transform(sources):
        seen.update(sources)
        return pl.DataFrame({"n": [sources["alignments"].height]})

    module.transform = transform  # type: ignore[attr-defined]
    monkeypatch.setattr(recipes, "load_recipe", lambda name, version=None: module)

    raw = scan(ALN, HMM)
    stored = pl.concat([raw.slice(3, 4), raw.slice(0, 3)])
    recipes.execute_recipe("fake/raw.py", tmp_path, extra_sources={"alignments": stored})
    assert seen["alignments"].equals(raw.drop(SOURCE_LINE_COLUMN))


def _raw_scans(node):
    """Every ``polars_kwargs`` of a one-line-per-row scan in a template."""
    if isinstance(node, dict):
        kwargs = node.get("polars_kwargs")
        if isinstance(kwargs, dict) and kwargs.get("separator") == "\x1f":
            yield kwargs
        for value in node.values():
            yield from _raw_scans(value)
    elif isinstance(node, list):
        for value in node:
            yield from _raw_scans(value)


TEMPLATES = sorted(PROJECTS.rglob("template.yaml"))


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: str(p.relative_to(PROJECTS)))
def test_every_raw_scan_numbers_its_lines(template):
    for kwargs in _raw_scans(yaml.safe_load(template.read_text())):
        assert kwargs.get("include_file_paths") == "source_path", kwargs
        assert kwargs.get("row_index_name") == SOURCE_LINE_COLUMN, kwargs
        assert kwargs.get("row_index_offset") == 1, kwargs
