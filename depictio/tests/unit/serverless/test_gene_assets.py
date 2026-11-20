"""Gene tables travel inside the bundle (the advviz "Alternative splicing" tab
fetched ``./assets/genomes/hg38.genes.json`` over file://)."""

from __future__ import annotations

import base64
import gzip
import json

from depictio.serverless import gene_assets


def _tile(kind: str, **config) -> dict:
    return {
        "component_type": "advanced_viz",
        "viz_kind": kind,
        "config": {"viz_kind": kind, **config},
    }


# The advviz dashboard's genome tiles, as its seed holds them.
ADVVIZ = [
    _tile("sashimi", annotation="hg38"),
    _tile("genome_view", annotation="none", assembly="hg38", default_region="chr8"),
    _tile("genome_view", annotation="none", assembly=None),
    _tile("cnv_profile", annotation="hg38"),
]


def test_the_assemblies_are_the_ones_the_genome_tiles_name():
    assert gene_assets.gene_assemblies(ADVVIZ) == {"hg38"}
    assert gene_assets.gene_assemblies([_tile("cnv_profile", annotation="mm10")]) == {"mm10"}
    # 'none', an assembly with no table, and other kinds ask for nothing.
    assert (
        gene_assets.gene_assemblies(
            [
                _tile("genome_view", annotation="none"),
                _tile("genome_view", assembly="dm6"),
                _tile("volcano", annotation="hg38"),
                {"component_type": "figure", "config": {"annotation": "hg38"}},
            ]
        )
        == set()
    )


def test_the_shipped_table_decodes_to_the_served_one():
    blobs, missing = gene_assets.gene_blobs(ADVVIZ)
    assert missing == [] and set(blobs) == {"genes_hg38"}

    shipped = gzip.decompress(base64.b64decode(blobs["genes_hg38"]))
    served = gene_assets.gene_asset_path("hg38").read_bytes()
    assert shipped == served
    table = json.loads(shipped)
    assert {"name", "chrom", "start", "end"} <= set(table["columns"])
    # Compressed: well under the raw size it would cost inlined as text.
    assert len(blobs["genes_hg38"]) < len(served) / 2


def test_a_table_this_process_cannot_read_is_left_out(monkeypatch, tmp_path):
    monkeypatch.setattr(gene_assets, "_SOURCE_DIR", tmp_path)
    monkeypatch.setattr(gene_assets, "_DIST_DIR", tmp_path / "dist")
    blobs, missing = gene_assets.gene_blobs(ADVVIZ, template_dir=tmp_path)
    assert blobs == {} and missing == ["hg38"]

    # The copy Vite writes beside the static template is the second place.
    genomes = tmp_path / "assets" / "genomes"
    genomes.mkdir(parents=True)
    (genomes / "hg38.genes.json").write_text('{"columns": [], "genes": []}')
    blobs, missing = gene_assets.gene_blobs(ADVVIZ, template_dir=tmp_path)
    assert set(blobs) == {"genes_hg38"} and missing == []


def test_a_wheel_reads_the_table_from_the_spa_build(monkeypatch, tmp_path):
    """A wheel ships viewer/dist (Vite copies public/ into it), not public/."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "hg38.genes.json").write_text('{"columns": [], "genes": []}')
    monkeypatch.setattr(gene_assets, "_SOURCE_DIR", tmp_path / "absent")
    monkeypatch.setattr(gene_assets, "_DIST_DIR", dist)
    assert gene_assets.gene_asset_path("hg38") == dist / "hg38.genes.json"
