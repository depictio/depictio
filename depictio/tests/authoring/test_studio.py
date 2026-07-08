"""Tests for the Depictio Studio authoring backend (``depictio/authoring``).

Covers the service-free path end to end: config-by-example, tree/preview,
recognize, and the project export (which must produce a ``project.yaml`` that
validates against ``Project`` and a ``depictio_project.yaml`` written to disk).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.authoring import (
    export_project as export_mod,
)
from depictio.authoring import (
    preview as preview_mod,
)
from depictio.authoring import (
    recognize as recognize_mod,
)
from depictio.authoring import (
    tree as tree_mod,
)
from depictio.authoring.paths import StudioPathError, safe_resolve


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A small fake run tree with two star quant files + a samplesheet."""
    for sample in ("S1", "S2", "S3"):
        d = tmp_path / "star" / sample
        d.mkdir(parents=True)
        (d / "quant.tsv").write_text("gene\tcount\nA\t1\nB\t2\n")
    (tmp_path / "samplesheet.csv").write_text("sample,condition\nS1,ctrl\nS2,treat\n")
    return tmp_path


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def test_safe_resolve_rejects_escape(run_dir: Path) -> None:
    assert safe_resolve(run_dir, "star/S1/quant.tsv").name == "quant.tsv"
    with pytest.raises(StudioPathError):
        safe_resolve(run_dir, "../../etc/passwd")


# --------------------------------------------------------------------------- #
# config-by-example
# --------------------------------------------------------------------------- #
def test_config_by_example_single(run_dir: Path) -> None:
    res = recognize_mod.config_by_example(run_dir, ["star/S1/quant.tsv"])
    assert res["path_glob"] == "**/quant.tsv"
    assert res["match_count"] == 3


def test_config_by_example_anti_unify(run_dir: Path) -> None:
    res = recognize_mod.config_by_example(run_dir, ["star/S1/quant.tsv", "star/S2/quant.tsv"])
    # The varying middle segment collapses; all three siblings match.
    assert res["path_glob"] == "star/S*/quant.tsv"
    assert res["match_count"] == 3
    assert "star/S3/quant.tsv" in res["matched"]


def test_wildcard_token() -> None:
    assert recognize_mod._wildcard_token(["S1.quant", "S2.quant"]) == "S*.quant"
    assert recognize_mod._wildcard_token(["quant.tsv", "quant.tsv"]) == "quant.tsv"


# --------------------------------------------------------------------------- #
# scan-preview (matches + schema agreement)
# --------------------------------------------------------------------------- #
def test_scan_preview_consistent(run_dir: Path) -> None:
    sp = recognize_mod.scan_preview(run_dir, "star/*/quant.tsv")
    assert sp["match_count"] == 3
    assert sp["matched"] == [
        "star/S1/quant.tsv",
        "star/S2/quant.tsv",
        "star/S3/quant.tsv",
    ]
    assert sp["regex"] == recognize_mod.glob_to_pattern("star/*/quant.tsv")
    assert sp["consistent"] is True
    assert sp["mismatches"] == []
    assert sp["schema"] == {"gene": "String", "count": "Int64"}


def test_scan_preview_reports_schema_mismatch(run_dir: Path) -> None:
    # A fourth sibling with a different column set breaks schema agreement.
    odd = run_dir / "star" / "S4"
    odd.mkdir(parents=True)
    (odd / "quant.tsv").write_text("gene\ttpm\nA\t1.5\n")

    sp = recognize_mod.scan_preview(run_dir, "star/*/quant.tsv")
    assert sp["match_count"] == 4
    assert sp["consistent"] is False
    bad = {m["path"] for m in sp["mismatches"]}
    assert "star/S4/quant.tsv" in bad


def test_scan_preview_matches_basename_tree_wide(run_dir: Path) -> None:
    # The CLI scanner matches basenames tree-wide, ignoring directory structure.
    # A file with the same name at a *different* depth must also be reported, or
    # the preview would under-report what `depictio run` actually ingests.
    deep = run_dir / "star" / "extra" / "nested"
    deep.mkdir(parents=True)
    (deep / "quant.tsv").write_text("gene\tcount\nA\t1\n")

    sp = recognize_mod.scan_preview(run_dir, "star/*/quant.tsv")
    # glob is 2-deep, but ingestion matches basename anywhere → the nested one too.
    assert "star/extra/nested/quant.tsv" in sp["matched"]
    assert sp["match_count"] == 4


def test_scan_preview_regex_override(run_dir: Path) -> None:
    # An explicit regex overrides the glob-derived pattern and drives the matches.
    sp = recognize_mod.scan_preview(run_dir, "**/quant.tsv", regex=r"(?s:samplesheet\.csv)\Z")
    assert sp["regex"] == r"(?s:samplesheet\.csv)\Z"
    assert sp["matched"] == ["samplesheet.csv"]


def test_scan_preview_applies_max_depth_and_ignore(run_dir: Path) -> None:
    # A deeply-nested match and one under an ignored directory.
    deep = run_dir / "star" / "deep" / "x"
    deep.mkdir(parents=True)
    (deep / "quant.tsv").write_text("gene\tcount\nA\t1\n")
    snake = run_dir / ".snakemake"
    snake.mkdir()
    (snake / "quant.tsv").write_text("gene\tcount\nA\t1\n")

    base = recognize_mod.scan_preview(run_dir, "**/quant.tsv")
    assert base["match_count"] == 5  # S1, S2, S3, star/deep/x, .snakemake

    # max_depth caps directory levels — star/deep/x/quant.tsv (depth 3) drops out.
    capped = recognize_mod.scan_preview(run_dir, "**/quant.tsv", max_depth=2)
    assert "star/deep/x/quant.tsv" not in capped["matched"]
    assert capped["match_count"] == 4

    # ignore drops any file whose path contains the token.
    filtered = recognize_mod.scan_preview(run_dir, "**/quant.tsv", ignore=[".snakemake"])
    assert not any(".snakemake" in m for m in filtered["matched"])
    assert filtered["match_count"] == 4


def test_scan_preview_sequencing_runs(run_dir: Path) -> None:
    # A sequencing-runs workflow scans only immediate runs_regex subdirs — a file
    # directly under the folder, and one under a non-matching subdir, are excluded
    # (whereas a flat scan of the same folder would include them).
    wfroot = run_dir / "seq"
    for r in ("run_1", "run_2"):
        d = wfroot / r
        d.mkdir(parents=True)
        (d / "metrics.csv").write_text("a,b\n1,2\n")
    (wfroot / "logs").mkdir()
    (wfroot / "logs" / "metrics.csv").write_text("a,b\n1,2\n")
    (wfroot / "metrics.csv").write_text("a,b\n1,2\n")

    seq = recognize_mod.scan_preview(
        run_dir, "**/metrics.csv", subroot="seq", structure="sequencing-runs", runs_regex="run_*"
    )
    assert sorted(seq["matched"]) == ["seq/run_1/metrics.csv", "seq/run_2/metrics.csv"]

    flat = recognize_mod.scan_preview(run_dir, "**/metrics.csv", subroot="seq")
    assert flat["match_count"] == 4  # logs/ + base file included when flat


def test_scan_preview_rejects_escaping_glob(run_dir: Path) -> None:
    with pytest.raises(StudioPathError):
        recognize_mod.scan_preview(run_dir, "../../etc/*")


# --------------------------------------------------------------------------- #
# repo metadata extraction (pure parsers — no network)
# --------------------------------------------------------------------------- #
def test_parse_nextflow_config() -> None:
    from depictio.authoring import metadata as metadata_mod

    cfg = (
        "manifest {\n"
        '  name = "nf-core/rnaseq"\n'
        '  version = "3.14.0"\n'
        '  description = "RNA sequencing analysis pipeline"\n'
        '  homePage = "https://nf-co.re/rnaseq"\n'
        "}\n"
    )
    out = metadata_mod.parse_nextflow_config(cfg)
    assert out["engine"] == "nextflow"
    assert out["name"] == "nf-core/rnaseq"
    assert out["version"] == "3.14.0"
    assert out["description"] == "RNA sequencing analysis pipeline"
    assert out["homepage"] == "https://nf-co.re/rnaseq"


def test_parse_ro_crate() -> None:
    from depictio.authoring import metadata as metadata_mod

    doc = {
        "@graph": [
            {"@id": "ro-crate-metadata.json", "about": {"@id": "./"}},
            {
                "@id": "./",
                "name": "My Workflow",
                "version": "2.1.0",
                "description": "Does science",
                "license": {"@id": "#mit"},
                "author": [{"@id": "#alice"}, {"@id": "#bob"}],
            },
            {"@id": "#mit", "name": "MIT"},
            {"@id": "#alice", "name": "Alice"},
            {"@id": "#bob", "name": "Bob"},
            {
                "@id": "main.nf",
                "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
                "programmingLanguage": {"@id": "#nextflow"},
            },
            {"@id": "#nextflow", "name": "Nextflow"},
        ]
    }
    out = metadata_mod.parse_ro_crate(doc)
    assert out["name"] == "My Workflow"
    assert out["version"] == "2.1.0"
    assert out["engine"] == "nextflow"
    assert out["description"] == "Does science"
    assert out["license"] == "MIT"
    assert out["author"] == "Alice, Bob"


def test_clean_description_strips_html_and_markdown() -> None:
    from depictio.authoring import metadata as metadata_mod

    raw = (
        '<h1><img src="logo.png"></h1>\n'
        "[![badge](b.svg)](https://ci)\n"
        "## Introduction\n"
        "**nf-core/rnaseq** is a [pipeline](https://nf-co.re) for RNA-seq."
    )
    out = metadata_mod._clean_description(raw)
    assert "<" not in out and ">" not in out
    assert "![" not in out and "](" not in out
    assert "nf-core/rnaseq is a pipeline for RNA-seq." in out


def test_fetch_workflow_metadata_offline_nfcore(monkeypatch: pytest.MonkeyPatch) -> None:
    # With no network, an nf-core URL still infers engine + catalog from the owner,
    # and records "nf-core" as the source so the UI reports success (not "nothing").
    from depictio.authoring import metadata as metadata_mod

    monkeypatch.setattr(metadata_mod, "_http_get", lambda url: None)
    monkeypatch.setattr(metadata_mod, "_http_get_data_uri", lambda url, mime="image/png": None)
    out = metadata_mod.fetch_workflow_metadata("https://github.com/nf-core/rnaseq")
    assert out["engine"] == "nextflow"
    assert out["catalog"]["name"] == "nf-core"
    assert out["sources"] == ["nf-core"]


def test_fetch_workflow_metadata_nfcore_logo(monkeypatch: pytest.MonkeyPatch) -> None:
    # The nf-core pipeline logo is fetched from repo assets and inlined; the dark
    # variant falls back to the light one when absent.
    from depictio.authoring import metadata as metadata_mod

    monkeypatch.setattr(metadata_mod, "_http_get", lambda url: None)
    monkeypatch.setattr(
        metadata_mod,
        "_http_get_data_uri",
        lambda url, mime="image/png": "data:image/png;base64,AAAA" if "logo_light" in url else None,
    )
    out = metadata_mod.fetch_workflow_metadata("https://github.com/nf-core/rnaseq")
    assert out["logo"] == "data:image/png;base64,AAAA"
    assert out["logo_dark"] == "data:image/png;base64,AAAA"
    assert "logo" in out["sources"]


def test_fetch_workflow_metadata_rejects_bad_url() -> None:
    from depictio.authoring import metadata as metadata_mod

    with pytest.raises(ValueError):
        metadata_mod.fetch_workflow_metadata("not-a-url")


# --------------------------------------------------------------------------- #
# tree + preview
# --------------------------------------------------------------------------- #
def test_build_tree(run_dir: Path) -> None:
    t = tree_mod.build_tree(run_dir)
    names = {c["name"] for c in t["children"]}
    assert {"star", "samplesheet.csv"} <= names
    sheet = next(c for c in t["children"] if c["name"] == "samplesheet.csv")
    assert sheet["previewable"] is True


def test_preview_file(run_dir: Path) -> None:
    pv = preview_mod.preview_file(run_dir, "samplesheet.csv")
    assert pv["columns"] == ["sample", "condition"]
    assert pv["schema"] == {"sample": "String", "condition": "String"}
    assert pv["format"] == "csv"
    assert pv["n_rows_preview"] == 2


# --------------------------------------------------------------------------- #
# recognize
# --------------------------------------------------------------------------- #
def test_recognize_unknown_file(run_dir: Path) -> None:
    res = recognize_mod.recognize(run_dir, "samplesheet.csv")
    assert res["recognized"] is False
    assert res["config_by_example"]["path_glob"] == "**/samplesheet.csv"


# --------------------------------------------------------------------------- #
# export/project
# --------------------------------------------------------------------------- #
def test_export_project_single_and_recursive(run_dir: Path) -> None:
    from depictio.models.models.projects import Project

    payload = {
        "name": "Studio Test",
        "workflows": [
            {
                "name": "main",
                "data_collections": [
                    {"dc_tag": "samplesheet", "path": "samplesheet.csv", "mode": "single"},
                    {
                        "dc_tag": "quant",
                        "path": "star/S1/quant.tsv",
                        "mode": "recursive",
                        "glob": "star/S*/quant.tsv",
                    },
                ],
            }
        ],
    }
    out = export_mod.export_project(run_dir, payload)

    # depictio_project.yaml was written into the root.
    written = Path(out["written_path"])
    assert written == run_dir / export_mod.PROJECT_YAML_NAME
    assert written.exists()

    # project.yaml validates against the real Project model (permissions are
    # injected by `depictio run`, so add a stub here to exercise full validation).
    import yaml

    proj = yaml.safe_load(out["project_yaml"])
    proj["permissions"] = {"owners": [], "editors": [], "viewers": []}
    validated = Project.model_validate(proj)

    dcs = validated.workflows[0].data_collections
    tags = {dc.data_collection_tag for dc in dcs}
    assert tags == {"samplesheet", "quant"}

    by_tag = {dc.data_collection_tag: dc for dc in dcs}
    assert by_tag["samplesheet"].config.scan.mode == "single"
    assert by_tag["quant"].config.scan.mode == "recursive"


def test_export_project_carries_scan_options(run_dir: Path) -> None:
    """Editable regex + max_depth/ignore round-trip onto ScanRecursive."""
    from depictio.models.models.projects import Project

    payload = {
        "name": "Scan Options",
        "workflows": [
            {
                "name": "main",
                "data_collections": [
                    {
                        "dc_tag": "quant",
                        "path": "star/S1/quant.tsv",
                        "mode": "recursive",
                        "glob": "star/*/quant.tsv",
                        "pattern": r"(?s:quant\.tsv)\Z",
                        "max_depth": 2,
                        "ignore": [".snakemake"],
                    }
                ],
            }
        ],
    }
    out = export_mod.export_project(run_dir, payload)

    import yaml

    proj = yaml.safe_load(out["project_yaml"])
    proj["permissions"] = {"owners": [], "editors": [], "viewers": []}
    validated = Project.model_validate(proj)

    scan = validated.workflows[0].data_collections[0].config.scan
    assert scan.mode == "recursive"
    assert scan.scan_parameters.regex_config.pattern == r"(?s:quant\.tsv)\Z"
    assert scan.scan_parameters.max_depth == 2
    assert scan.scan_parameters.ignore == [".snakemake"]


def test_export_project_multi_workflow(run_dir: Path) -> None:
    """Two workflows, each with its own data_location folder and data collections."""
    from depictio.models.models.projects import Project

    payload = {
        "name": "Multi WF",
        "workflows": [
            {
                "name": "sheets",
                "engine": "python",
                "folder": "",
                "data_collections": [
                    {"dc_tag": "samplesheet", "path": "samplesheet.csv", "mode": "single"}
                ],
            },
            {
                "name": "star_quant",
                "engine": "nextflow",
                "folder": "star",
                "structure": "flat",
                "data_collections": [
                    {
                        "dc_tag": "quant",
                        "path": "star/S1/quant.tsv",
                        "mode": "recursive",
                        "glob": "star/S*/quant.tsv",
                    }
                ],
            },
        ],
    }
    out = export_mod.export_project(run_dir, payload)

    import yaml

    proj = yaml.safe_load(out["project_yaml"])
    proj["permissions"] = {"owners": [], "editors": [], "viewers": []}
    validated = Project.model_validate(proj)

    assert [w.name for w in validated.workflows] == ["sheets", "star_quant"]
    assert validated.workflows[1].engine.name == "nextflow"
    # Each workflow keeps its own data_location; the second is scoped to star/.
    assert validated.workflows[0].data_location.locations[0].endswith(str(run_dir))
    assert validated.workflows[1].data_location.locations[0].endswith("star")


def test_export_project_workflow_provenance(run_dir: Path) -> None:
    """repository_url / version / catalog round-trip onto the Workflow."""
    from depictio.models.models.projects import Project

    payload = {
        "name": "Prov",
        "workflows": [
            {
                "name": "rnaseq",
                "engine": "nextflow",
                "folder": "",
                "structure": "flat",
                "repository_url": "https://github.com/nf-core/rnaseq",
                "version": "3.14.0",
                "catalog": {"name": "nf-core", "url": "https://github.com/nf-core/rnaseq"},
                "data_collections": [
                    {"dc_tag": "sheet", "path": "samplesheet.csv", "mode": "single"}
                ],
            }
        ],
    }
    out = export_mod.export_project(run_dir, payload)

    import yaml

    proj = yaml.safe_load(out["project_yaml"])
    proj["permissions"] = {"owners": [], "editors": [], "viewers": []}
    wf = Project.model_validate(proj).workflows[0]
    assert wf.repository_url == "https://github.com/nf-core/rnaseq"
    assert wf.version == "3.14.0"
    assert wf.catalog is not None and wf.catalog.name == "nf-core"


def test_export_project_requires_workflow(run_dir: Path) -> None:
    with pytest.raises(ValueError):
        export_mod.export_project(run_dir, {"name": "Empty", "workflows": []})


def test_export_project_duplicate_workflow_name_raises(run_dir: Path) -> None:
    wf = {
        "name": "dup",
        "data_collections": [{"dc_tag": "a", "path": "samplesheet.csv", "mode": "single"}],
    }
    dup = {
        "name": "dup",
        "data_collections": [{"dc_tag": "b", "path": "star/S1/quant.tsv", "mode": "single"}],
    }
    with pytest.raises(ValueError):
        export_mod.export_project(run_dir, {"name": "P", "workflows": [wf, dup]})


def test_export_project_duplicate_dc_tag_across_workflows_raises(run_dir: Path) -> None:
    with pytest.raises(ValueError):
        export_mod.export_project(
            run_dir,
            {
                "name": "P",
                "workflows": [
                    {
                        "name": "a",
                        "data_collections": [
                            {"dc_tag": "same", "path": "samplesheet.csv", "mode": "single"}
                        ],
                    },
                    {
                        "name": "b",
                        "data_collections": [
                            {"dc_tag": "same", "path": "star/S1/quant.tsv", "mode": "single"}
                        ],
                    },
                ],
            },
        )


def test_scan_preview_subroot_scopes_matches(run_dir: Path) -> None:
    # samplesheet.csv lives at the root; a subroot into star/ excludes it, and a
    # subroot scopes the tree-wide basename match to that folder.
    whole = recognize_mod.scan_preview(run_dir, "**/quant.tsv")
    assert whole["match_count"] == 3
    scoped = recognize_mod.scan_preview(run_dir, "**/quant.tsv", subroot="star/S1")
    assert scoped["matched"] == ["star/S1/quant.tsv"]


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def test_routes_via_testclient(run_dir: Path) -> None:
    from fastapi.testclient import TestClient

    from depictio.authoring.server import create_app

    client = TestClient(create_app(run_dir))

    assert client.get("/studio/tree").status_code == 200
    assert client.post("/studio/preview-data", json={"path": "samplesheet.csv"}).status_code == 200
    assert client.post("/studio/recognize", json={"path": "samplesheet.csv"}).status_code == 200

    sp = client.post("/studio/scan-preview", json={"glob": "star/*/quant.tsv"})
    assert sp.status_code == 200
    assert sp.json()["match_count"] == 3
    # A glob that escapes the root → 400.
    assert client.post("/studio/scan-preview", json={"glob": "../../etc/*"}).status_code == 400

    # scan-preview scoped to a workflow sub-folder.
    scoped = client.post(
        "/studio/scan-preview", json={"glob": "**/quant.tsv", "subroot": "star/S1"}
    )
    assert scoped.status_code == 200
    assert scoped.json()["match_count"] == 1

    r = client.post(
        "/studio/export/project",
        json={
            "name": "HTTP Test",
            "workflows": [
                {
                    "name": "main",
                    "data_collections": [
                        {"dc_tag": "quant", "path": "star/S1/quant.tsv", "mode": "single"}
                    ],
                }
            ],
        },
    )
    assert r.status_code == 200
    assert (run_dir / export_mod.PROJECT_YAML_NAME).exists()

    # Path escape → 400.
    assert client.post("/studio/preview-data", json={"path": "../../etc/passwd"}).status_code == 400
