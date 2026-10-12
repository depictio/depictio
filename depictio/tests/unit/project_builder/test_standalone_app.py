"""``depictio project-builder <dir>``: the standalone server on one folder.

It serves the main viewer bundle with the builder's mode tag, the builder
routes at the main API's paths, and its own context/plan/write routes, for
the folder it was started on and no other, to loopback callers only. It must
never import the server stack (``depictio.api.main``, MongoDB, Celery).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from depictio.project_builder.routes import BUILDER_PREFIX  # noqa: E402
from depictio.project_builder.standalone import MODE_META, create_app  # noqa: E402

P = BUILDER_PREFIX


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    base = tmp_path / "results"
    (base / "star" / "S1").mkdir(parents=True)
    (base / "star" / "S2").mkdir(parents=True)
    (base / "star" / "S1" / "quant.tsv").write_text("gene\tcount\nA\t1\n")
    (base / "star" / "S2" / "quant.tsv").write_text("gene\tcount\nB\t2\n")
    (base / "samplesheet.csv").write_text("sample,condition\nS1,ctrl\nS2,treat\n")
    (base / ".hidden").mkdir()
    return base


@pytest.fixture
def viewer_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "index-abc.js").write_text("console.log(1)")
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>Depictio</title></head></html>"
    )
    return dist


@pytest.fixture
def client(folder: Path, viewer_dist: Path, tmp_path: Path) -> TestClient:
    app = create_app(folder, viewer_dist=viewer_dist, out_dir=tmp_path / "bundle")
    return TestClient(app, base_url="http://127.0.0.1:8129")


def _spec(folder: Path) -> dict:
    return {"data_root": str(folder)}


SHEET = {
    "tag": "sheet",
    "type": "table",
    "mode": "single",
    "path": "samplesheet.csv",
    "props": {"kind": "table", "format": "csv", "separator": ","},
}
QUANT = {
    "tag": "quant",
    "type": "table",
    "mode": "recursive",
    "regex": r"^star/[^/]+/quant\.tsv$",
    "props": {"kind": "table", "format": "tsv", "separator": "\t"},
}


def _template(client: TestClient, *dcs: dict) -> dict:
    draft = {"name": "Lab QC", "workflows": [{"name": "main", "data_collections": list(dcs)}]}
    response = client.post(f"{P}/template", json={"draft": draft})
    assert response.status_code == 200, response.text
    return response.json()["template"]


def test_the_spa_is_served_with_the_mode_tag(client: TestClient):
    page = client.get("/projects/build")
    assert page.status_code == 200
    assert MODE_META in page.text
    assert page.headers["cache-control"].startswith("no-cache")
    assert client.get("/anything/else").text == page.text
    assert client.get("/", follow_redirects=False).headers["location"] == "/projects/build"
    assert client.get("/dashboard/assets/index-abc.js").status_code == 200


def test_unknown_api_paths_are_404_not_the_spa(client: TestClient):
    assert client.get("/depictio/api/v1/projects/nope").status_code == 404


def test_context_names_the_folder_and_the_bundle(client: TestClient, folder: Path, tmp_path):
    context = client.get(f"{P}/context").json()
    assert context == {
        "mode": "standalone",
        "data_root": str(folder.resolve()),
        "out_dir": str(tmp_path / "bundle"),
        "writable": True,
    }


def test_tree_lists_one_level_without_hidden_entries(client: TestClient, folder: Path):
    listing = client.post(f"{P}/tree", json={"root": _spec(folder), "path": ""}).json()
    names = [entry["name"] for entry in listing["entries"]]
    assert names == ["star", "samplesheet.csv"]
    assert listing["is_remote"] is False


def test_another_folder_is_refused(client: TestClient, tmp_path: Path):
    response = client.post(f"{P}/tree", json={"root": {"data_root": str(tmp_path)}, "path": ""})
    assert response.status_code == 400
    assert response.json()["code"] == "builder_root_other"


@pytest.mark.parametrize("path", ["../", "/etc", "star/../../x"])
def test_paths_leaving_the_folder_are_refused(client: TestClient, folder: Path, path: str):
    response = client.post(f"{P}/tree", json={"root": _spec(folder), "path": path})
    assert response.status_code == 400
    assert response.json()["code"] == "builder_path_refused"


def test_match_lists_what_the_scan_would_ingest(client: TestClient, folder: Path):
    result = client.post(f"{P}/match", json={"root": _spec(folder), "collection": QUANT}).json()
    assert result["files"] == ["star/S1/quant.tsv", "star/S2/quant.tsv"]
    assert result["consistent"] is True
    assert result["schema"] == {"gene": "String", "count": "Int64"}


def test_plan_then_write_then_overwrite(client: TestClient, folder: Path, tmp_path: Path):
    template = _template(client, SHEET, QUANT)
    plan = client.post(f"{P}/plan", json={"template": template}).json()
    assert plan["template_id"] == "custom/lab-qc"
    assert plan["dry_run"] is True
    assert {row["data_collection_tag"]: row["matched"] for row in plan["data_collections"]} == {
        "sheet": 1,
        "quant": 2,
    }

    written = client.post(f"{P}/write", json={"template": template})
    assert written.status_code == 200
    bundle = tmp_path / "bundle" / "template.yaml"
    assert written.json()["path"] == str(bundle)
    assert "{DATA_ROOT}/samplesheet.csv" in bundle.read_text()
    assert written.json()["ingest_command"] == (
        f"depictio ingest {folder.resolve()} --template {bundle}"
    )

    again = client.post(f"{P}/write", json={"template": template})
    assert again.status_code == 409 and again.json()["code"] == "bundle_exists"
    replaced = client.post(f"{P}/write", json={"template": template, "overwrite": True})
    assert replaced.status_code == 200
    assert (tmp_path / "bundle" / "template.yaml.bak").is_file()


def test_write_refuses_an_invalid_template(client: TestClient):
    response = client.post(f"{P}/write", json={"template": {"name": "x"}})
    assert response.status_code == 422
    assert response.json()["code"] == "inline_template_invalid"


def test_file_preview_shim(client: TestClient, folder: Path):
    body = {
        "data_root": str(folder),
        "location": str(folder / "samplesheet.csv"),
        "infer_types": True,
    }
    preview = client.post("/depictio/api/v1/projects/run_file_preview", json=body).json()
    assert preview["columns"] == ["sample", "condition"]
    assert preview["dtypes"] == {"sample": "String", "condition": "String"}
    outside = {**body, "location": "/etc/hostname"}
    refused = client.post("/depictio/api/v1/projects/run_file_preview", json=outside)
    assert refused.status_code == 422 and refused.json()["code"] == "location_outside_run"


def test_a_non_loopback_host_is_refused(folder: Path, viewer_dist: Path):
    app = create_app(folder, viewer_dist=viewer_dist)
    rebinding = TestClient(app, base_url="http://attacker.example:8129")
    response = rebinding.get(f"{P}/context")
    assert response.status_code == 403
    assert response.json()["code"] == "non_loopback_host"
    assert TestClient(app, base_url="http://localhost:8129").get(f"{P}/context").status_code == 200


def test_the_host_check_is_off_when_serving_another_address(folder: Path, viewer_dist: Path):
    app = create_app(folder, viewer_dist=viewer_dist, allowed_hosts=None)
    remote = TestClient(app, base_url="http://builder.lab.example:8129")
    assert remote.get(f"{P}/context").status_code == 200


def test_the_standalone_app_never_imports_the_server_stack():
    # Beanie itself is a base dependency (depictio.models imports it); what must
    # stay out is the API app, its MongoDB connection and the worker.
    code = (
        "import sys; from pathlib import Path\n"
        "import depictio.project_builder.standalone as s\n"
        "bad = [m for m in ('depictio.api.main', 'depictio.api.v1.db', 'celery')"
        " if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""
