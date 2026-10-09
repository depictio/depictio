"""A zero-byte pipeline output (a step that wrote nothing) holds no rows: skip it.

SEACR writes an empty bed for a library with no peaks. A File cannot have size
zero and polars cannot parse a file with no header, so one such file used to fail
the scan, or the recipe reading it.
"""

from pathlib import Path

import pytest

from depictio.cli.cli.utils.scan import scan_single_file
from depictio.models.models.transforms import RecipeSource
from depictio.recipes import RecipeError, _resolve_glob_source


def _write(tmp_path: Path) -> tuple[Path, Path]:
    filled = tmp_path / "a.peaks.bed"
    filled.write_text("chr1\t10\t20\n")
    empty = tmp_path / "b.peaks.bed"
    empty.touch()
    return filled, empty


def test_scan_registers_no_file_for_an_empty_output(tmp_path: Path) -> None:
    _, empty = _write(tmp_path)
    # Returns before it touches the run, the collection or the permissions.
    result = scan_single_file(
        str(empty),
        run=None,  # type: ignore[arg-type]
        data_collection=None,  # type: ignore[arg-type]
        permissions=None,  # type: ignore[arg-type]
        existing_files={},
        update_files=False,
        skip_regex=True,
    )
    assert result is None


def test_recipe_glob_skips_an_empty_file(tmp_path: Path) -> None:
    _write(tmp_path)
    source = RecipeSource(
        ref="peaks", glob_pattern="*.peaks.bed", format="tsv", read_kwargs={"has_header": False}
    )
    assert _resolve_glob_source(tmp_path, source).height == 1


def test_recipe_glob_with_only_empty_files_still_fails(tmp_path: Path) -> None:
    (tmp_path / "b.peaks.bed").touch()
    source = RecipeSource(ref="peaks", glob_pattern="*.peaks.bed", format="tsv")
    with pytest.raises(RecipeError, match="were empty"):
        _resolve_glob_source(tmp_path, source)
