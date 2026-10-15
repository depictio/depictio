"""`nf-core/proteinfamilies/samples.py`: the sample hub is the run's samplesheet.

proteinfamilies does not publish the sheet it ran on, so the hub reads the file
named by METADATA_FILE. The `mode` column is derived from the sheet's content (a row
that names existing HMMs to extend is an update), never from the sample names, and
every other sheet column rides along under a sanitised name.
"""

from __future__ import annotations

from pathlib import Path

from depictio.recipes import execute_recipe

RECIPE = "nf-core/proteinfamilies/samples.py"

# The sample names carry the words "create" and "update" on purpose: none may decide the mode.
_SHEET = """sample,fasta,existing_hmms_to_update,existing_msas_to_update,Design Group
update_a,https://example.org/data/extra.faa,https://example.org/data/hmms.tar.gz,https://example.org/data/msas.tar.gz,case
create_b,https://example.org/data/input_small.faa,,,control
"""


def _run(tmp_path: Path, sheet: str) -> list[dict]:
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / "samplesheet.csv").write_text(sheet)
    out = execute_recipe(RECIPE, tmp_path)
    return out.to_dicts()


def test_mode_comes_from_the_existing_hmms_not_from_the_sample_name(tmp_path: Path) -> None:
    rows = {r["sample"]: r for r in _run(tmp_path, _SHEET)}
    assert rows["update_a"]["mode"] == "update"
    assert rows["create_b"]["mode"] == "create"


def test_paths_are_reduced_to_file_names_and_extra_columns_survive(tmp_path: Path) -> None:
    rows = {r["sample"]: r for r in _run(tmp_path, _SHEET)}
    assert rows["update_a"]["fasta"] == "extra.faa"
    assert rows["update_a"]["existing_hmms_to_update"] == "hmms.tar.gz"
    assert rows["update_a"]["existing_msas_to_update"] == "msas.tar.gz"
    assert rows["create_b"]["existing_hmms_to_update"] is None
    # A design column is kept under a sanitised name, so GROUP_COL can name it.
    assert rows["update_a"]["Design_Group"] == "case"
    assert rows["create_b"]["Design_Group"] == "control"


def test_sheet_without_the_update_columns_is_all_create(tmp_path: Path) -> None:
    rows = _run(tmp_path, "sample,fasta\ns1,a.faa\ns2,b.faa\n")
    assert [r["sample"] for r in rows] == ["s1", "s2"]
    assert {r["mode"] for r in rows} == {"create"}
    assert all(r["existing_hmms_to_update"] is None for r in rows)


def test_tab_separated_sheet_is_split(tmp_path: Path) -> None:
    rows = _run(tmp_path, "sample\tfasta\nS1\ta.faa\n")
    assert rows[0]["sample"] == "S1"
    assert rows[0]["fasta"] == "a.faa"
