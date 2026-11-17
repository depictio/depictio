"""The rows a genome browser points at, and the rank track of its best calls.

``picked_from_rows`` names the picked ``locus_from`` rows for the viewer (loci
for variant tracks, names for annotation tracks, keys for a table of the same
collection); ``rank_track_config`` draws the first calls as ``#rank label``.
"""

from __future__ import annotations

from depictio.api.v1.services.jbrowse.render import (
    RANK_TRACK_ID,
    picked_from_rows,
    rank_track_config,
)

VARIANTS = {
    "chrom_column": "chrom",
    "start_column": "pos",
    "end_column": "end",
    "label_column": "gene",
    "padding": 25000,
}
ISOFORMS = {
    "chrom_column": "chrom",
    "start_column": "start",
    "end_column": "end",
    "label_column": "gene_name",
    "locate_column": "transcript_id",
}


def test_a_picked_variant_is_named_by_its_unpadded_locus_and_its_key_columns():
    picked = picked_from_rows([{"chrom": "21", "pos": 1000, "end": 1000, "gene": "APP"}], VARIANTS)
    assert picked == {
        "loci": ["21:1000-1000"],
        "names": ["APP"],
        "keys": [{"chrom": "21", "pos": 1000}],
    }


def test_a_transcript_without_coordinates_is_picked_by_its_id():
    rows = [
        {"chrom": None, "start": None, "end": None, "gene_name": "HLA-B", "transcript_id": "ENST1"}
    ]
    picked = picked_from_rows(rows, ISOFORMS)
    assert picked == {
        "loci": [],
        "names": ["ENST1"],
        "keys": [{"transcript_id": "ENST1"}],
        # The gene the transcript sits under, found without colouring its isoforms.
        "genes": ["HLA-B"],
    }


def test_rows_naming_nothing_pick_nothing():
    assert picked_from_rows([{"chrom": None, "pos": None}], VARIANTS) is None


def test_the_rank_track_names_each_call_by_rank_with_zero_based_starts():
    rows = [
        {"chrom": "21", "pos": 1000, "end": 1000, "gene": "APP"},
        {"chrom": "21", "pos": 5000, "end": 5002, "gene": None},
        {"chrom": None, "pos": 9, "end": 9, "gene": "lost"},
    ]
    conf = rank_track_config(rows, {**VARIANTS, "name": "Ranked variants"}, "GRCh38")
    assert conf is not None
    assert conf["trackId"] == RANK_TRACK_ID
    assert conf["name"] == "Top 2 Ranked variants"
    features = conf["adapter"]["features"]
    assert [(f["name"], f["start"], f["end"]) for f in features] == [
        ("\u2605 #1 APP", 999, 1000),
        ("\u2605 #2", 4999, 5002),
    ]


def test_no_usable_row_makes_no_rank_track():
    assert rank_track_config([{"chrom": "1", "pos": "x", "end": None}], VARIANTS, "hg38") is None


def test_a_pick_below_the_top_is_drawn_on_the_rank_track_by_its_label():
    rows = [{"chrom": "21", "pos": 1000, "end": 1000, "gene": "APP"}]
    picked = [
        {"chrom": "21", "pos": 1000, "end": 1000, "gene": "APP"},
        {"chrom": "10", "pos": 50, "end": 80, "gene": "NOLC1"},
    ]
    conf = rank_track_config(rows, VARIANTS, "GRCh38", picked)
    features = conf["adapter"]["features"]
    assert [(f["name"], f.get("rank")) for f in features] == [
        ("\u2605 #1 APP", 1),
        ("NOLC1", None),
    ]
    assert conf["name"] == "Top 1 calls"


def test_rank_calls_take_the_category_colour_of_their_rank_color_by_value():
    rows = [
        {"chrom": "21", "pos": 1000, "end": 1000, "gene": "APP", "model": "Recessive"},
        {"chrom": "21", "pos": 2000, "end": 2000, "gene": "SOD1", "model": None},
    ]
    spec = {**VARIANTS, "rank_color_by": "model"}
    conf = rank_track_config(rows, spec, "GRCh38", None, {"model": {"Recessive": "#f08c00"}})
    features = conf["adapter"]["features"]
    assert [f.get("color") for f in features] == ["#f08c00", None]
    assert conf["displays"][0]["renderer"]["color1"].startswith("jexl:get(feature,'color')")


def test_gencode_genes_group_their_transcripts_by_symbol():
    from depictio.api.v1.services.jbrowse.assemblies import (
        get_assembly_preset,
        preset_annotation_track,
    )

    adapter = preset_annotation_track(get_assembly_preset("hg38"))["adapter"]
    # The default (geneName2) is UniProt: a gene would be labelled Q86WR7.
    assert adapter["aggregateField"] == "geneName"


def test_an_ensembl_gene_id_is_named_by_its_symbol():
    from depictio.api.v1.services.jbrowse.render import gene_symbols

    hits = {"ENSG00000204463": [{"label": "ENSG00000204463.16"}, {"label": "BAG6"}]}

    def search(genome, name, limit):
        return hits.get(name, [])

    assert gene_symbols(["ENSG00000204463", "ENSG1", "TP53"], "hg38", search) == [
        "BAG6",
        "ENSG1",
        "TP53",
    ]
    assert gene_symbols(["ENSG00000204463"], None, search) == ["ENSG00000204463"]


def test_a_gene_frame_holds_the_row_and_keeps_its_chromosome_name():
    from depictio.api.v1.services.jbrowse.render import union_locus

    assert union_locus("10:11850000-11850300", "chr10:11823356-11872277") == "10:11823356-11872277"
    assert union_locus("10:5-9", "chr11:1-100") == "10:5-9"
    assert union_locus("10:5-9", None) == "10:5-9"
