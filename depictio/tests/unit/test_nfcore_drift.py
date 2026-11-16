"""Offline tests for scripts/nfcore_drift.py: the template run on two releases' outputs.

The pure comparisons are tested on their own; one end-to-end test builds two run
folders the way an upgrade changes them (a renamed file, a renamed column, a
new column family, a flipped sign, a new output folder) and checks that every
change is reported, and that an unchanged run reports nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import polars as pl
import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "nfcore_drift.py"


@pytest.fixture(scope="module")
def nfd() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nfcore_drift", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["nfcore_drift"] = module
    spec.loader.exec_module(module)
    return module


# -- pure comparisons ----------------------------------------------------------


def test_a_column_replaced_in_place_is_a_rename(nfd: ModuleType) -> None:
    removed, added, renamed = nfd.header_changes(
        ["ID", "Kingdom", "Phylum", "S1"], ["ID", "Domain", "Phylum", "S1", "x_confidence"]
    )
    assert renamed == [("Kingdom", "Domain")]
    assert removed == []
    assert added == ["x_confidence"]


def test_a_new_column_family_is_named(nfd: ModuleType) -> None:
    findings = nfd._compare_header(
        "dc.src",
        ["ID", "Phylum", "S1", "S2"],
        ["ID", "Phylum", "S1", "S2", "domain_confidence", "phylum_confidence", "class_confidence"],
        [],
    )
    assert any("*_confidence" in f.hint for f in findings)


def test_a_removed_column_the_recipe_names_is_an_error(nfd: ModuleType) -> None:
    findings = nfd._compare_header(
        "dc.src", ["ID", "Kingdom", "S1"], ["ID", "S1"], [], text='pl.col("Kingdom")'
    )
    assert [f.level for f in findings] == ["error"]
    plain = nfd._compare_header("dc.src", ["ID", "Kingdom", "S1"], ["ID", "S1"], [])
    assert [f.level for f in plain] == ["warn"]


def test_a_header_of_data_values_is_summarised(nfd: ModuleType) -> None:
    old = ["index"] + [f"Bacteria;Bacteria;Taxon{i}" for i in range(20)]
    new = ["index"] + [f"Bacteria;Taxon{i}" for i in range(20)]
    findings = nfd._compare_header("dc.src", old, new, [])
    assert len(findings) == 1 and findings[0].level == "info"
    assert "columns are data" in findings[0].message


def test_rename_candidate_prefers_the_same_folder(nfd: ModuleType) -> None:
    old = {"qiime2/rel/rel-table-ASV_with-DADA2-tax.tsv", "qiime2/rel/rel-table-2.tsv"}
    new = {
        "qiime2/rel/rel-table-ASV_with-DADA2-sbdi-gtdb-tax.tsv",
        "qiime2/rel/rel-table-2.tsv",
        "other/rel-table-ASV_with-DADA2-tax.txt",
    }
    assert nfd.rename_candidates("qiime2/rel/rel-table-ASV_with-DADA2-tax.tsv", old, new)[0] == (
        "qiime2/rel/rel-table-ASV_with-DADA2-sbdi-gtdb-tax.tsv"
    )


def _schema(props: dict) -> dict:
    return {"$defs": {"g": {"properties": props}}}


def test_schema_diff_finds_renames_defaults_and_new_skips(nfd: ModuleType) -> None:
    old = _schema(
        {
            "FW_primer": {"type": "string", "description": "Forward primer sequence"},
            "skip_qiime": {"type": "boolean", "default": False},
            "run_qualimap": {"type": "boolean", "default": True},
            "pacbio": {"type": "boolean", "description": "PacBio data"},
        }
    )
    new = _schema(
        {
            "primer_fwd": {"type": "string", "description": "Forward primer sequence"},
            "skip_qiime": {"type": "boolean", "default": False},
            "run_qualimap": {"type": "boolean", "default": False},
            "skip_chopper": {"type": "boolean", "default": False},
        }
    )
    findings = {
        f.subject: f for f in nfd.compare_schemas(old, new, read_by_template={"run_qualimap"})
    }
    assert "primer_fwd" in findings["FW_primer"].message
    assert findings["pacbio"].message == "removed"
    assert findings["run_qualimap"].level == "error"  # a rule reads it, its default flipped
    assert findings["skip_chopper"].level == "warn"
    assert "primer_fwd" not in findings  # reported once, as the rename


def test_run_params_diff_reads_nested_values_and_groups_them(nfd: ModuleType) -> None:
    old = {
        "outdir": "s3://a",
        "db": {"x": {"taxlevels": "Domain,Kingdom,Phylum", "citation": "A"}},
        "db2": {"x": {"taxlevels": "Domain,Kingdom,Phylum"}},
    }
    new = {
        "outdir": "s3://b",
        "db": {"x": {"taxlevels": "Domain,Phylum", "citation": "B"}},
        "db2": {"x": {"taxlevels": "Domain,Phylum"}},
    }
    findings = nfd.compare_run_params(old, new)
    assert len(findings) == 1
    assert findings[0].subject == "db.x.taxlevels (+1 like it)"


def test_paired_rows_that_anticorrelate_are_a_flipped_sign(nfd: ModuleType) -> None:
    ids = [f"g{i}" for i in range(60)]
    values = [float(i - 30) for i in range(60)]
    a = pl.DataFrame({"gene": ids, "contrast": ["T-C"] * 60, "lfc": values})
    b = pl.DataFrame({"gene": ids, "contrast": ["T-C"] * 60, "lfc": [-v for v in values]})
    findings = nfd._paired_values("dc", a, b)
    assert len(findings) == 1 and "anti-correlated" in findings[0].message
    assert nfd._paired_values("dc", a, a) == []


# -- end to end on two run folders --------------------------------------------

TEMPLATE_YAML = """
template:
  template_id: "test/drift/1.0.0"
  description: "Two collections an upgrade can break"
  version: "1.0.0"
  variables:
    - name: "DATA_ROOT"
      description: "Run directory"
      required: true
  dashboards: []
name: "Drift test"
workflows:
  - name: "wf"
    engine: {name: "nextflow"}
    data_collections:
      - data_collection_tag: "stats"
        description: "Per-sample stats"
        config:
          type: "Table"
          scan:
            mode: "single"
            scan_parameters:
              filename: "{DATA_ROOT}/tables/stats.tsv"
          dc_specific_properties:
            format: "TSV"
            polars_kwargs: {separator: "\\t"}
      - data_collection_tag: "events"
        description: "SUPPA events"
        config:
          type: "Table"
          source: "transformed"
          transform:
            recipe: "suppa/local_events.py"
"""


def _run(root: Path, *, renamed: bool, flipped: bool, extra: bool) -> Path:
    (root / "tables").mkdir(parents=True)
    (root / "suppa").mkdir()
    name = "stats_v2.tsv" if renamed else "stats.tsv"
    top = "Domain" if renamed else "Kingdom"
    rows = "\n".join(f"S{i}\tBacteria\t{100 + i}" for i in range(40))
    (root / "tables" / name).write_text(f"sample\t{top}\treads\n{rows}\n")
    sign = -1 if flipped else 1
    events = "\n".join(
        f"G{i};SE:chr1:{100 + i}-{200 + i}:{300 + i}-{400 + i}:+\t{sign * (i - 20) / 40:.3f}\t0.01"
        for i in range(40)
    )
    (root / "suppa" / "T-C_local_diffsplice.dpsi").write_text(f"T-C_dPSI\tT-C_p-val\n{events}\n")
    if extra:
        (root / "newtool").mkdir()
        (root / "newtool" / "result.tsv").write_text("a\tb\n1\t2\n")
    return root


@pytest.fixture
def template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    from depictio.cli.cli.utils import templates as templates_mod

    tdir = tmp_path / "template"
    tdir.mkdir()
    (tdir / "template.yaml").write_text(TEMPLATE_YAML)
    monkeypatch.setattr(templates_mod, "locate_template", lambda _tid: tdir / "template.yaml")
    return "test/drift/1.0.0"


def test_an_unchanged_run_reports_nothing(nfd: ModuleType, template: str, tmp_path: Path) -> None:
    old = _run(tmp_path / "old", renamed=False, flipped=False, extra=False)
    new = _run(tmp_path / "new", renamed=False, flipped=False, extra=False)

    findings, _ = nfd.diff_runs(template, str(old), str(new))

    assert findings == []


def test_an_upgrade_is_described_change_by_change(
    nfd: ModuleType, template: str, tmp_path: Path
) -> None:
    old = _run(tmp_path / "old", renamed=False, flipped=False, extra=False)
    new = _run(tmp_path / "new", renamed=True, flipped=True, extra=True)

    findings, lines = nfd.diff_runs(template, str(old), str(new))
    text = "\n".join(lines)

    lost = [f for f in findings if f.subject == "stats" and f.layer == "files"]
    assert lost and lost[0].level == "error"
    assert "stats_v2.tsv" in lost[0].hint
    assert any(f.layer == "tables" and "anti-correlated" in f.message for f in findings)
    assert any(f.layer == "outputs" and f.subject == "newtool/" for f in findings)
    assert "## Differential ingestion" in text
