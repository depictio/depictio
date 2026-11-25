"""Object files shipped inside a bundle (protein kinds) and the 3Dmol add-on.

``depictio/serverless/objects.py`` packs the structure / PAE files the protein
tiles read; ``depictio/serverless/addons.py`` appends the 3Dmol.js add-on only
to bundles holding a molecule_3d tile.
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from depictio.models.models.serverless import ComponentTier, TierReason
from depictio.serverless import addons as addons_mod
from depictio.serverless.objects import (
    ObjectBudget,
    ObjectSource,
    build_collection,
    collection_detail,
    needs_three_dmol,
    object_dc_refs,
    pack_object,
    sample_from_name,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SHOWCASE = REPO_ROOT / "depictio" / "projects" / "init" / "advanced_viz_showcase" / "data"
PROTEIN_SPEC = REPO_ROOT / "depictio" / "serverless" / "examples" / "protein.yaml"


def _src(sample: str, data: bytes, name: str | None = None) -> ObjectSource:
    return ObjectSource(sample, name or f"{sample}.pdb", len(data), lambda: data)


def test_pack_object_gzips_text_and_keeps_gzip_as_is() -> None:
    key, b64, gz = pack_object(b"ATOM  " * 100)
    assert gz and key.startswith("obj_")
    assert gzip.decompress(base64.b64decode(b64)) == b"ATOM  " * 100
    already = gzip.compress(b"data")
    key2, b64_2, gz2 = pack_object(already)
    assert not gz2 and base64.b64decode(b64_2) == already
    # Content-addressed: the same bytes ship once.
    assert pack_object(b"ATOM  " * 100)[0] == key


@pytest.mark.parametrize(
    ("name", "sample"),
    [
        ("demo_protein.pae.tsv", "demo_protein"),
        ("P12345.pae.json.gz", "P12345"),
        ("model.cif.gz", "model"),
        ("x.pdb", "x"),
    ],
)
def test_sample_from_name(name: str, sample: str) -> None:
    assert sample_from_name(name) == sample


def test_the_cap_drops_samples_the_table_does_not_name_first() -> None:
    blobs: dict[str, str] = {}
    budget = ObjectBudget(cap=250, per_object=200)
    sources = [_src("a", b"x" * 100), _src("b", b"y" * 100), _src("c", b"z" * 100)]
    coll = build_collection(sources, "pdb", budget, blobs, preferred=["c", "b"])
    assert [f.sample for f in coll.files] == ["c", "b"]
    assert coll.dropped == ["a"] and coll.total == 3
    assert len(blobs) == 2
    detail = collection_detail(coll)
    assert detail and "2 of 3 files shipped" in detail and "left out: a" in detail


def test_a_file_over_the_per_object_cap_is_never_shipped() -> None:
    blobs: dict[str, str] = {}
    coll = build_collection(
        [_src("big", b"x" * 500)], "pdb", ObjectBudget(cap=10_000, per_object=100), blobs
    )
    assert coll.files == [] and coll.dropped == ["big"] and blobs == {}


def test_object_refs_follow_the_structure_source() -> None:
    file_mode = {
        "component_type": "advanced_viz",
        "viz_kind": "molecule_3d",
        "config": {"structure_source": "file", "structure_dc_id": "d" * 24},
    }
    assert object_dc_refs(file_mode) == [("structure", "d" * 24)]
    resolve = {**file_mode, "config": {**file_mode["config"], "structure_source": "resolve"}}
    assert object_dc_refs(resolve) == []
    pae = {"component_type": "advanced_viz", "viz_kind": "pae_matrix", "config": {"pae_dc_id": "p"}}
    assert object_dc_refs(pae) == [("pae", "p")]
    assert needs_three_dmol([file_mode]) and not needs_three_dmol([pae])


def _protein_data_dir(root: Path, with_pae: bool = True) -> Path:
    wf = root / "protein_demo"
    (wf / "structures").mkdir(parents=True)
    pl.read_csv(SHOWCASE / "protein_residues_demo.tsv", separator="\t").write_parquet(
        wf / "protein_residues_demo.parquet"
    )
    (wf / "structures" / "demo_protein.pdb").write_bytes(
        (SHOWCASE / "demo_protein.pdb").read_bytes()
    )
    if with_pae:
        (wf / "pae").mkdir()
        (wf / "pae" / "demo_protein.pae.tsv").write_bytes(
            (SHOWCASE / "demo_protein.pae.tsv").read_bytes()
        )
    return root


@pytest.fixture
def fake_addons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "addons"
    d.mkdir()
    (d / "3dmol.js").write_text("window['3Dmol']={createViewer(){}};")
    (d / "addons.json").write_text(
        json.dumps({"3dmol": {"version": "2.5.5", "file": "3dmol.js", "bytes": 35}})
    )
    monkeypatch.setenv(addons_mod.ADDONS_DIR_ENV, str(d))
    return d


def test_producer_b_ships_the_files_and_the_3dmol_addon(tmp_path: Path, fake_addons: Path) -> None:
    from depictio.serverless.producer_b import build_manifest, load_spec

    result = build_manifest(load_spec(PROTEIN_SPEC), _protein_data_dir(tmp_path / "data"))
    m = result.manifest
    names = sorted(f.name for c in m.objects.values() for f in c.files)
    assert names == ["demo_protein.pae.tsv", "demo_protein.pdb"]
    for coll in m.objects.values():
        for f in coll.files:
            assert f.uri.removeprefix("inline:") in m.inline_blobs
    assert [a.name for a in m.addons] == ["3dmol"]
    tiers = {r.component_id: r.tier for r in result.tier_rows}
    assert tiers["viz-structure"] is ComponentTier.LIVE
    assert tiers["viz-pae"] is ComponentTier.LIVE
    assert tiers["viz-ramachandran"] is ComponentTier.LIVE


def test_a_missing_file_collection_degrades_to_partial_with_the_reason(
    tmp_path: Path, fake_addons: Path
) -> None:
    from depictio.serverless.producer_b import build_manifest, load_spec

    result = build_manifest(
        load_spec(PROTEIN_SPEC), _protein_data_dir(tmp_path / "data", with_pae=False)
    )
    row = next(r for r in result.tier_rows if r.component_id == "viz-pae")
    assert row.tier is ComponentTier.PARTIAL
    assert row.detail and "no files under" in row.detail


def test_render_puts_the_addon_before_the_runtime_script(
    tmp_path: Path, fake_addons: Path, monkeypatch
) -> None:
    from depictio.serverless import producer_b

    (tmp_path / "combined-runtime.js").write_text("window.__runtime=1;")
    (tmp_path / "combined-runtime.css").write_text("body{margin:0}")
    monkeypatch.setenv(producer_b.TEMPLATE_PATH_ENV, str(tmp_path / "combined-runtime.js"))
    result = producer_b.build_manifest(
        producer_b.load_spec(PROTEIN_SPEC), _protein_data_dir(tmp_path / "data")
    )
    html = producer_b.render_bundle_html(result.manifest)
    assert html.index('<script data-depictio-addon="3dmol">') < html.index("window.__runtime=1;")


def test_render_appends_the_addon_before_body_of_a_legacy_template(
    tmp_path: Path, fake_addons: Path, monkeypatch
) -> None:
    from depictio.serverless import producer_b

    template = tmp_path / "static.html"
    template.write_text(
        '<html><head></head><body><script id="bundle-manifest">__BUNDLE_MANIFEST__</script></body></html>'
    )
    monkeypatch.setenv(producer_b.TEMPLATE_PATH_ENV, str(template))
    result = producer_b.build_manifest(
        producer_b.load_spec(PROTEIN_SPEC), _protein_data_dir(tmp_path / "data")
    )
    html = producer_b.render_bundle_html(result.manifest)
    assert '<script data-depictio-addon="3dmol">' in html
    assert html.index("data-depictio-addon") < html.index("</body>")
    assert "__BUNDLE_MANIFEST__" not in html


def test_no_addon_without_a_molecule_tile(tmp_path: Path, fake_addons: Path) -> None:
    template = "<html><body>x</body></html>"
    assert addons_mod.apply_addons(template, []) == template


def test_producer_a_ships_from_the_collection_and_marks_unshippable_tiles_partial(
    monkeypatch: pytest.MonkeyPatch, fake_addons: Path
) -> None:
    pytest.importorskip("fastapi")
    from depictio.serverless import producer_a
    from depictio.serverless.preflight import TierRow

    pdb = (SHOWCASE / "demo_protein.pdb").read_bytes()
    sources = {
        "s" * 24: (
            "pdb",
            [ObjectSource("demo_protein", "demo_protein.pdb", len(pdb), lambda: pdb)],
        ),
        "e" * 24: ("pae", []),
    }
    monkeypatch.setattr(producer_a, "_indexed_file_sources", lambda dc_id: sources[dc_id])
    mol = {
        "component_type": "advanced_viz",
        "viz_kind": "molecule_3d",
        "title": "Structure",
        "dc_id": "r" * 24,
        "config": {"structure_source": "file", "structure_dc_id": "s" * 24, "entity_col": "entity"},
    }
    pae = {
        "component_type": "advanced_viz",
        "viz_kind": "pae_matrix",
        "dc_id": "r" * 24,
        "config": {"pae_dc_id": "e" * 24},
    }
    rows = {
        cid: TierRow(
            component_id=cid, title=cid, component_type="advanced_viz", tier=ComponentTier.LIVE
        )
        for cid in ("mol", "pae")
    }
    frames = {"r" * 24: pl.DataFrame({"entity": ["demo_protein"] * 3})}
    blobs: dict[str, str] = {}
    objects, resolved, addons = producer_a.collect_objects_a(
        [(None, mol, "mol"), (None, pae, "pae")],
        rows,
        frames,
        blobs,
        producer_a.ExportUser(id=None),
    )
    assert [f.name for f in objects["s" * 24].files] == ["demo_protein.pdb"]
    assert resolved == []
    assert [a.name for a in addons] == ["3dmol"]
    assert rows["mol"].tier is ComponentTier.LIVE
    assert rows["pae"].tier is ComponentTier.PARTIAL
    assert "holds no readable object" in (rows["pae"].detail or "")


def test_image_snapshot_ships_thumbnails_under_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    import io as _io

    from PIL import Image

    from depictio.api.v1 import s3 as s3_mod
    from depictio.api.v1.configs.config import settings
    from depictio.serverless import producer_a
    from depictio.serverless.objects import image_s3_path

    big = _io.BytesIO()
    noise = np.random.default_rng(0).integers(0, 255, (900, 1200, 3), dtype=np.uint8)
    Image.fromarray(noise, "RGB").save(big, format="PNG")  # incompressible: ~3 MB
    stored = {"cells/a.png": big.getvalue(), "cells/b.png": b"\x89PNG tiny"}

    class FakeS3:
        def get_object(self, Bucket, Key):
            assert Bucket == settings.s3.bucket
            return {"Body": _io.BytesIO(stored[Key])}

    class FakeRoutes:
        @staticmethod
        def render_image_paths_endpoint(
            dashboard_id, component_id, request, current_user, access_token
        ):
            assert request == {"filters": [], "max": 2}
            rows = [
                {"img": "cells/a.png", "id": 1},
                {"img": "b.png", "id": 2},
                {"img": None, "id": 3},
            ]
            return {"rows": rows, "image_column": "img", "paths": [r["img"] for r in rows]}

    monkeypatch.setattr(s3_mod, "s3_client", FakeS3())
    monkeypatch.setattr(producer_a, "_routes", lambda: FakeRoutes)
    comp = {
        "component_type": "image",
        "image_column": "img",
        "max_images": 2,
        "s3_base_folder": f"s3://{settings.s3.bucket}/cells/",
    }
    assert image_s3_path(comp["s3_base_folder"], "cells/a.png").endswith("/cells/a.png")
    blobs: dict[str, str] = {}
    payload, note = producer_a._freeze_image(
        None, comp, "img-1", producer_a.ExportUser(id=None), ObjectBudget(), blobs
    )
    assert [r["id"] for r in payload["rows"]] == [1, 2]
    assert all(r["img"].startswith("inline:obj_") for r in payload["rows"])
    # The 1200 px PNG was downsampled; the tiny one shipped as is.
    shipped = sorted(len(base64.b64decode(v)) for v in blobs.values())
    assert shipped[0] == len(b"\x89PNG tiny") and shipped[1] < len(big.getvalue())
    assert note is None


def test_python_jobs_settle_only_when_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from depictio.models.models.serverless import DataRef
    from depictio.serverless import producer_a
    from depictio.serverless.preflight import TierRow
    from depictio.serverless.pyodide import plan

    monkeypatch.setattr(plan, "unavailable_reason", lambda features: None)
    code = {"component_type": "figure", "mode": "code", "dc_id": "d" * 24, "code_content": "fig=1"}
    bound = {**code, "code_content": "fig=2"}
    items = [(None, code, "f1"), (None, bound, "f2")]
    ref = DataRef(uri="inline:dc_x", rows=3, size_bytes=1, columns=[])

    def rows():
        return {
            cid: TierRow(cid, cid, "figure", ComponentTier.FROZEN, TierReason.CODE_MODE, "x")
            for cid in ("f1", "f2")
        }

    cands = producer_a.mark_python_candidates(items, "auto")
    assert set(cands) == {"f1", "f2"} and code[producer_a.PYTHON_JOB_KEY] == "code_figure"
    tiers = rows()
    jobs, info = producer_a.settle_python_jobs(
        items, tiers, {"f2": object()}, {"d" * 24: ref}, cands, "auto"
    )
    assert list(jobs) == ["f1"] and info["embedded"]
    assert jobs["f1"].table_uri == f"inline:ipc_{'d' * 24}"
    assert tiers["f1"].tier is ComponentTier.LIVE and "Pyodide" in (tiers["f1"].detail or "")
    assert tiers["f2"].tier is ComponentTier.FROZEN  # bound: TypeScript serves it
    assert producer_a.PYTHON_JOB_KEY not in code  # marker stripped
    # off: nothing marked, nothing embedded.
    assert producer_a.mark_python_candidates(items, "off") == {}
    tiers = rows()
    jobs, info = producer_a.settle_python_jobs(items, tiers, {}, {"d" * 24: ref}, {}, "off")
    assert jobs == {} and not info["embedded"] and tiers["f1"].tier is ComponentTier.FROZEN
