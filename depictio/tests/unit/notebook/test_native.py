"""Advanced visualisations drawn in the document from their data (``depictio.notebook.native``).

The seeded tiles that are not Plotly in the app are drawn here through a fake API
that answers from the seeds' own TSVs, exactly as the client asks the real one.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import httpx
import polars as pl
import pytest
import yaml

from depictio.api.v1.services.notebook_export.classify import classify
from depictio.notebook import DepictioClient, native
from depictio.notebook.components import component_for
from depictio.notebook.native import pedigree, phylo, protein

REPO = Path(__file__).resolve().parents[4]
SHOWCASE = REPO / "depictio" / "projects" / "init" / "advanced_viz_showcase"
AMPLISEQ = REPO / "depictio" / "projects" / "nf-core" / "ampliseq" / "2.18.0"
# ampliseq's static ids (db_init_reference_datasets.STATIC_IDS) for the phylogeny tiles.
AMPLISEQ_FILES = {
    "646b0f3c1e4a2d7f8e5b8cdb": AMPLISEQ / "qiime2" / "phylogenetic_tree" / "tree.nwk",
    "646b0f3c1e4a2d7f8e5b8cdc": AMPLISEQ / "phylogenetic_tree_metadata_canonical.tsv",
    "646b0f3c1e4a2d7f8e5b8ca9": AMPLISEQ / "taxonomy_rel_abundance.tsv",
    "646b0f3c1e4a2d7f8e5b8caa": AMPLISEQ / "ancombc_results.tsv",
}


def _strip(o):
    if isinstance(o, dict):
        if set(o) == {"$oid"}:
            return o["$oid"]
        return {k: _strip(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def _files() -> dict[str, tuple[Path, str]]:
    out: dict[str, tuple[Path, str]] = {}
    cfg = yaml.safe_load((SHOWCASE / "project.yaml").read_text())
    for wf in cfg["workflows"]:
        for dc in wf["data_collections"]:
            c = dc.get("config") or {}
            fn = ((c.get("scan") or {}).get("scan_parameters") or {}).get("filename")
            if fn:
                out[str(dc["id"])] = (SHOWCASE / "data" / Path(fn).name, str(c["type"]).lower())
    for dc_id, path in AMPLISEQ_FILES.items():
        out[dc_id] = (path, "table")
    return out


FILES = _files()


class SeedApi:
    """``/advanced_viz/data``, newick and indexed files, from the seeds' files."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        # What `/dashboards/get/<id>` answers: the colours a tab draws in.
        self.dashboard: dict = {}

    def frame(self, dc_id: str) -> pl.DataFrame:
        return pl.read_csv(
            FILES[dc_id][0], separator="\t", infer_schema_length=10000, null_values=["", "NA"]
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.calls.append((path, body))
        if path.endswith("/advanced_viz/data"):
            assert body["wf_id"] and body["columns"], body
            df = self.frame(str(body["dc_id"]))
            for f in body.get("filter_metadata") or []:
                col, val = f.get("column_name"), f.get("value")
                if col in df.columns and isinstance(val, list) and val:
                    df = df.filter(pl.col(col).cast(pl.Utf8).is_in([str(v) for v in val]))
            df = df.select([c for c in body["columns"] if c in df.columns])
            return httpx.Response(200, json={"rows": df.to_dict(as_series=False)})
        if path.endswith("/newick"):
            dc_id = path.split("/")[-2]
            return httpx.Response(200, text=FILES[dc_id][0].read_text())
        if "/files/indexed/" in path:
            dc_id = path.rsplit("/", 1)[-1]
            p = FILES[dc_id][0]
            entry = {"sample": p.name.split(".")[0], "name": p.name, "url": f"/raw/{dc_id}"}
            return httpx.Response(200, json={"files": [entry]})
        if path.startswith("/raw/"):
            return httpx.Response(200, text=FILES[path.rsplit("/", 1)[-1]][0].read_text())
        if "/deltatables/specs/" in path:
            df = self.frame(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=[{"name": c} for c in df.columns])
        if "/dashboards/get/" in path:
            return httpx.Response(200, json=self.dashboard)
        if "/component_figure/" in path:
            png = "data:image/png;base64,iVBORw0KGgo="
            return httpx.Response(200, json={"status": "ready", "image": png})
        return httpx.Response(404, json={"detail": path})


@pytest.fixture
def api():
    return SeedApi()


@pytest.fixture
def client(api):
    return DepictioClient("http://depictio.test", "t", transport=httpx.MockTransport(api))


@pytest.fixture(autouse=True)
def _fresh():
    native.use_native(True)
    protein._3DMOL["emitted"] = False
    yield
    native.use_native(True)


def _seed_tiles() -> list[tuple[str, dict]]:
    tiles = []
    for path in sorted(SHOWCASE.glob(".db_seeds/*.json")) + sorted(
        AMPLISEQ.glob(".db_seeds/*.json")
    ):
        doc = _strip(json.loads(path.read_text()))
        for meta in doc.get("stored_metadata") or []:
            if meta.get("component_type") == "advanced_viz" and classify(meta).native:
                tiles.append((f"{path.stem}:{meta.get('title')}", meta))
    return tiles


SEED_TILES = _seed_tiles()


def test_the_seeds_hold_every_kind_the_document_draws():
    keys = {native.renderer_key(m) for _, m in SEED_TILES}
    assert keys == set(native.registered())


@pytest.mark.parametrize("meta", [m for _, m in SEED_TILES], ids=[i for i, _ in SEED_TILES])
def test_every_seeded_tile_is_drawn_here_from_its_data(client, api, meta):
    comp = component_for(client, "dash", meta, {"filters": []})
    bundle = comp._repr_mimebundle_()
    assert comp.native_error is None, comp.native_error
    assert 'class="dpx-tile dpx-native"' in bundle["text/html"]
    # From the data the renderer reads, never the server's browser.
    assert not any("/component_figure/" in p for p, _ in api.calls)
    if classify(meta).output == "interactive" and native.renderer_key(meta) != "molecule_3d":
        assert comp.figure is not None and len(comp.figure.data) > 0


def test_a_renderer_that_fails_falls_back_on_the_snapshot(client, api, monkeypatch):
    meta = next(m for _, m in SEED_TILES if m["viz_kind"] == "pedigree")

    def boom(tile):
        raise RuntimeError("the pedigree has a loop")

    renderer = native.registered()["pedigree"]
    monkeypatch.setitem(
        native._RENDERERS,
        "pedigree",
        native.NativeRenderer(**{**renderer.__dict__, "render": boom}),
    )
    comp = component_for(client, "dash", meta, {"filters": []})
    html = comp._repr_mimebundle_()["text/html"]
    assert "dpx-snapshot" in html and "the pedigree has a loop" in html
    assert comp.native_error == "the pedigree has a loop"


def test_native_drawing_can_be_turned_off(client, api):
    native.use_native(False)
    meta = next(m for _, m in SEED_TILES if m["viz_kind"] == "pedigree")
    html = component_for(client, "dash", meta, {"filters": []})._repr_mimebundle_()["text/html"]
    assert "dpx-snapshot" in html


def test_the_state_filters_reach_every_fetch(client, api):
    meta = next(m for _, m in SEED_TILES if m["viz_kind"] == "allele_grid")
    flt = {
        "index": "f",
        "column_name": "sample_id",
        "value": ["DONOR_01"],
        "metadata": {"dc_id": meta["dc_id"]},
    }
    html = component_for(client, "dash", meta, {"filters": [flt]})._repr_mimebundle_()["text/html"]
    assert "DONOR_01" in html and "DONOR_02" not in html
    sent = [b for p, b in api.calls if p.endswith("/advanced_viz/data")]
    assert sent and all(flt in b["filter_metadata"] for b in sent)


def test_a_record_card_with_no_pick_lists_the_records_it_picks_from(client):
    meta = next(
        m
        for _, m in SEED_TILES
        if m["viz_kind"] == "record_card" and not m["config"].get("default_record")
    )
    html = component_for(client, "dash", meta, {"filters": []})._repr_mimebundle_()["text/html"]
    assert "No record was picked" in html and "<table" in html


def test_a_record_card_follows_the_pick_in_the_state(client):
    meta = next(m for _, m in SEED_TILES if m["config"].get("default_record") == "GENE072")
    pick = {
        "index": "scatter",
        "source": "scatter_selection",
        "column_name": "feature_id",
        "value": ["GENE005"],
        "metadata": {"dc_id": meta["dc_id"]},
    }
    html = component_for(client, "dash", meta, {"filters": [pick]})._repr_mimebundle_()["text/html"]
    assert "GENE005" in html and "GENE072" not in html
    default = component_for(client, "dash", meta, {"filters": []})._repr_mimebundle_()["text/html"]
    assert "GENE072" in default and "the default record" in default


def test_a_structure_without_py3dmol_is_its_backbone_in_plotly(client, monkeypatch):
    monkeypatch.setattr(protein, "_has_py3dmol", lambda: False)
    meta = next(m for _, m in SEED_TILES if m["viz_kind"] == "molecule_3d")
    comp = component_for(client, "dash", meta, {"filters": []})
    comp._repr_mimebundle_()
    assert comp.figure.data[0].type == "scatter3d"


def test_3dmol_is_inlined_once_per_document(client):
    pytest.importorskip("py3Dmol")
    metas = [m for _, m in SEED_TILES if m["viz_kind"] == "molecule_3d"][:2]
    first, second = (
        component_for(client, "dash", m, {"filters": []})._repr_mimebundle_()["text/html"]
        for m in metas
    )
    assert "$3Dmolpromise=Promise.resolve()" in first and "3dmol.org" not in first.lower()[:2000]
    assert "$3Dmolpromise=Promise.resolve()" not in second
    assert len(second) < len(first) / 3


# ---------------------------------------------------------------------------
# The pieces
# ---------------------------------------------------------------------------


def test_logo_heights_follow_hmmlogo():
    emissions = {"A": 0.7, "C": 0.1, "D": 0.1, "E": 0.1}
    bg = protein._background()
    re_k = sum(p * math.log2(p / bg[a]) for a, p in emissions.items())
    heights, info = protein.column_heights(emissions, "relent_abovebg")
    assert info == pytest.approx(re_k)
    # The whole stack is redistributed over the letters above background.
    assert sum(heights.values()) == pytest.approx(re_k)
    assert heights["D"] == pytest.approx(re_k * 0.1 / (0.7 + 0.1 + 0.1 + 0.1))
    probs, mass = protein.column_heights(emissions, "probability")
    assert probs == emissions and mass == pytest.approx(1.0)


def test_pae_reads_alphafold_json_and_matrices():
    assert protein.parse_pae('[{"predicted_aligned_error": [[0, 1], [2, 0]]}]') == [[0, 1], [2, 0]]
    assert protein.parse_pae("0\t1.5\n2\t0\n") == [[0, 1.5], [2, 0]]
    triples = {"residue1": [1, 1, 2, 2], "residue2": [1, 2, 1, 2], "distance": [0, 3, 4, 0]}
    assert protein.parse_pae(json.dumps(triples)) == [[0, 3], [4, 0]]


def test_pedigree_generations_and_married_in_founders():
    people = [
        {"id": "gf", "father": None, "mother": None},
        {"id": "gm", "father": None, "mother": None},
        {"id": "dad", "father": "gf", "mother": "gm"},
        {"id": "mum", "father": None, "mother": None},
        {"id": "kid", "father": "dad", "mother": "mum"},
    ]
    slots, widths = pedigree.layout_family(people)
    assert {i: g for i, (g, _) in slots.items()} == {"gf": 0, "gm": 0, "dad": 1, "mum": 1, "kid": 2}
    # A couple stands side by side.
    assert abs(slots["dad"][1] - slots["mum"][1]) == 1
    assert widths == {0: 2, 1: 2, 2: 1}


def test_lineages_sit_at_their_core_clades():
    tree = phylo.parse_newick("((a:1,b:1)x:1,((c:1,d:1):1,e:1):1);")
    groups = {"a": "P1", "b": "P1", "c": "P2", "d": "P2", "e": "P1"}
    cores = phylo.core_clades(tree, groups)
    assert cores["P1"][1] == 2 and cores["P2"][1] == 2
    summary = phylo.induced(tree, {cores[g][0]: g for g in cores})
    assert sorted(n.name for n in phylo._leaves(summary)) == ["P1", "P2"]
    assert phylo.format_share(0.0996) == "10%" and phylo.format_share(0.0004) == "<0.1%"


def test_the_tree_of_life_wears_the_dashboards_kingdom_colours(client, api):
    """`color_col: Kingdom` on the ampliseq overview: the tips take the colours
    the dashboard pins for Kingdom (inherited from the main tab and laid over
    by the tab's own), not the palette's next hues."""
    meta = next(m for _, m in SEED_TILES if m.get("index") == "ov-tree")
    api.dashboard = {
        "inherited_category_colors": {"Kingdom": {"Archaea": "#111111", "Bacteria": "#222222"}},
        "category_colors": {"Kingdom": {"Bacteria": "#1098ad"}},
    }
    comp = component_for(client, "dash", meta, {"filters": []})
    fig = comp.figure
    assert comp.native_error is None, comp.native_error
    colours = {
        c
        for trace in fig.data
        for c in (
            trace.marker.color
            if trace.marker is not None and isinstance(trace.marker.color, (list, tuple))
            else []
        )
    }
    assert "#1098ad" in colours  # Bacteria: the tab's own pin wins
    assert "#222222" not in colours  # ...over the main tab's


def test_pinned_colours_win_and_the_rest_keep_the_palette():
    from depictio.notebook.native.layout import category_colors

    out = category_colors(["b", "a", "c"], pinned={"b": "#123456"})
    assert out["b"] == "#123456"
    assert out["a"] != out["c"] and "#123456" not in (out["a"], out["c"])
