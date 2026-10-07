"""The phylogeny summary (`collapse_rank`) and an advanced viz's card header,
through the config model and YAML import and export."""

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.configs import PhylogeneticConfig
from depictio.models.models.dashboards import DashboardDataLite

TREE = {
    "tree_wf_id": "646b0f3c1e4a2d7f8e5b8ca3",
    "tree_dc_id": "646b0f3c1e4a2d7f8e5b8cdb",
    "tree_dc_tag": "phylogenetic_tree_canonical",
    "metadata_wf_id": "646b0f3c1e4a2d7f8e5b8ca3",
    "metadata_dc_id": "646b0f3c1e4a2d7f8e5b8cdc",
    "metadata_dc_tag": "phylogenetic_tree_metadata_canonical",
    "color_col": "Kingdom",
}

SUMMARY = {
    "collapse_rank": "Phylum",
    "top_n": 12,
    "size_by": "abundance",
    "abundance_dc_tag": "taxonomy_rel_abundance",
    "abundance_split_col": "locality",
}

HEADER = {
    "figure_style": "minimal",
    "subtitle": "top phyla, sized by share of reads",
    "icon_name": "mdi:family-tree",
    "icon_color": "#82c91e",
    "hide_legend": True,
    "link": "tab:Phylogeny",
}


def _component(config: dict, **extra) -> dict:
    return {
        "component_type": "advanced_viz",
        "tag": "ov-tree",
        "index": "ov-tree",
        "workflow_tag": "nf-core/ampliseq",
        "data_collection_tag": "phylogenetic_tree_canonical",
        "title": "Tree of life",
        "section": "Findings",
        "viz_kind": "phylogenetic",
        "config": {"viz_kind": "phylogenetic", **config},
        "layout": {"x": 0, "y": 7, "w": 5, "h": 5},
        **extra,
    }


def _dash(*components):
    return DashboardDataLite(title="Overview", components=list(components))


# ---- Config ------------------------------------------------------------------


def test_summary_is_off_by_default():
    cfg = PhylogeneticConfig(**TREE)
    assert cfg.collapse_rank is None
    assert (cfg.top_n, cfg.size_by, cfg.abundance_col, cfg.abundance_sample_col) == (
        10,
        "tips",
        "rel_abundance",
        "sample",
    )


def test_summary_config_validates():
    cfg = PhylogeneticConfig(**TREE, **SUMMARY)
    assert cfg.collapse_rank == "Phylum"
    assert cfg.size_by == "abundance"


@pytest.mark.parametrize("top_n", [0, 61])
def test_top_n_is_bounded(top_n):
    with pytest.raises(ValidationError):
        PhylogeneticConfig(**TREE, collapse_rank="Phylum", top_n=top_n)


def test_size_by_takes_tips_or_abundance():
    with pytest.raises(ValidationError):
        PhylogeneticConfig(**TREE, collapse_rank="Phylum", size_by="reads")


def test_abundance_needs_its_table():
    with pytest.raises(ValidationError, match="abundance_dc_tag"):
        PhylogeneticConfig(**TREE, collapse_rank="Phylum", size_by="abundance")
    # Either binding will do: the tag is resolved to ids at import.
    PhylogeneticConfig(
        **TREE,
        collapse_rank="Phylum",
        size_by="abundance",
        abundance_dc_id="x",
        abundance_wf_id="y",
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"size_by": "abundance", "abundance_dc_tag": "t"},
        {"abundance_split_col": "site"},
        {"top_n": 12, "collapse_rank": None},
    ],
)
def test_summary_settings_outlive_a_switch_to_the_full_tree(extra):
    # The View switch writes `collapse_rank: null` and leaves the rest, so that
    # switching back returns the summary as it was. The full tree ignores them.
    cfg = PhylogeneticConfig(**TREE, **extra)
    assert cfg.collapse_rank is None


def test_collapse_rank_needs_tip_metadata():
    bare = {k: TREE[k] for k in ("tree_wf_id", "tree_dc_id")}
    with pytest.raises(ValidationError, match="metadata_dc_tag"):
        PhylogeneticConfig(**bare, collapse_rank="Phylum")


def test_unknown_summary_key_is_rejected():
    with pytest.raises(ValidationError):
        PhylogeneticConfig(**TREE, collapse_rank="Phylum", top="12")


# ---- Import / export ------------------------------------------------------------


def test_summary_and_header_survive_import():
    full = _dash(_component({**TREE, **SUMMARY}, **HEADER)).to_full()["stored_metadata"][0]
    assert full["viz_kind"] == "phylogenetic"
    assert {k: full["config"][k] for k in SUMMARY} == SUMMARY
    assert {k: full[k] for k in HEADER} == HEADER


def test_summary_and_header_round_trip():
    full = _dash(_component({**TREE, **SUMMARY}, **HEADER)).to_full()
    back = DashboardDataLite.from_full(full)
    comp = back.components[0]
    assert comp.viz_kind == "phylogenetic"
    assert comp.config.collapse_rank == "Phylum"
    assert comp.config.abundance_dc_tag == "taxonomy_rel_abundance"
    assert {k: getattr(comp, k) for k in HEADER} == HEADER
    # And once more through the import: nothing lost on the second pass.
    again = DashboardDataLite.from_full(back.to_full()).components[0]
    assert again.config == comp.config
    assert {k: getattr(again, k) for k in HEADER} == HEADER


def test_description_round_trips():
    about = "One tip per phylum, placed at its largest clean clade."
    full = _dash(_component({**TREE, **SUMMARY}, description=about)).to_full()
    assert full["stored_metadata"][0]["description"] == about
    assert DashboardDataLite.from_full(full).components[0].description == about


def test_export_leaves_defaults_out():
    yaml_text = _dash(_component({**TREE, **SUMMARY}, **HEADER)).to_yaml()
    exported = DashboardDataLite.from_full(
        _dash(_component({**TREE, **SUMMARY}, **HEADER)).to_full()
    ).to_yaml()
    for key in ("collapse_rank: Phylum", "top_n: 12", "abundance_dc_tag:", "link: tab:Phylogeny"):
        assert key in yaml_text
        assert key in exported
    # Model defaults the import fills in are not written back out.
    for key in ("abundance_col:", "default_layout:", "show_internal_labels:"):
        assert key not in exported


def test_exported_yaml_imports_to_the_same_tile():
    first = DashboardDataLite.from_full(
        _dash(_component({**TREE, **SUMMARY}, **HEADER)).to_full()
    ).components[0]
    text = DashboardDataLite(title="Overview", components=[first]).to_yaml()
    again = DashboardDataLite.from_yaml(text).components[0]
    assert again.config == first.config
    assert {k: getattr(again, k) for k in HEADER} == HEADER


def test_full_tree_exports_without_summary_keys():
    full = _dash(_component(TREE)).to_full()
    exported = DashboardDataLite.from_full(full).to_yaml()
    assert "viz_kind: phylogenetic" in exported
    assert "collapse_rank" not in exported
    assert "figure_style" not in exported


def test_config_its_model_rejects_is_exported_as_stored():
    full = _dash(_component(TREE)).to_full()
    stored = full["stored_metadata"][0]
    stored["config"] = {**stored["config"], "retired_key": 1}
    comp = DashboardDataLite.from_full(full).components[0]
    cfg = comp["config"] if isinstance(comp, dict) else comp.config
    assert cfg["retired_key"] == 1


# ---- Built in the UI ---------------------------------------------------------
#
# What the builder writes: every source by ids, and by tag beside them when the
# DC is in the component's own workflow (phylo/sources.ts `phyloSourcePatch`);
# the abundance columns as `<role>_col`; the view as `collapse_rank`, null once
# switched back to the full tree.

BUILT = {
    "viz_kind": "phylogenetic",
    "tree_wf_id": "wf-ampliseq",
    "tree_dc_id": "dc-tree",
    "tree_dc_tag": "phylogenetic_tree_canonical",
    "metadata_wf_id": "wf-ampliseq",
    "metadata_dc_id": "dc-tips",
    "metadata_dc_tag": "phylogenetic_tree_metadata_canonical",
    "taxon_col": "taxon",
    "color_col": "Kingdom",
    "extra_color_cols": ["Phylum", "Class"],
    "abundance_wf_id": "wf-ampliseq",
    "abundance_dc_id": "dc-reads",
    "abundance_dc_tag": "taxonomy_rel_abundance",
    "abundance_col": "rel_abundance",
    "abundance_sample_col": "sample",
    "abundance_split_col": "locality",
    "collapse_rank": "Phylum",
    "top_n": 8,
    "size_by": "abundance",
}


def _stored(config: dict) -> dict:
    """A dashboard as the builder saves it: ids resolved, config as built."""
    full = _dash(_component({**TREE, "collapse_rank": "Phylum"})).to_full()
    full["stored_metadata"][0]["config"] = dict(config)
    return full


def test_built_config_is_the_yaml_config():
    built = PhylogeneticConfig(**BUILT)
    from_yaml = DashboardDataLite.from_yaml(DashboardDataLite.from_full(_stored(BUILT)).to_yaml())
    assert from_yaml.components[0].config == built


def test_export_keeps_every_source_tag():
    exported = DashboardDataLite.from_full(_stored(BUILT)).to_yaml()
    for key in (
        "tree_dc_tag: phylogenetic_tree_canonical",
        "metadata_dc_tag: phylogenetic_tree_metadata_canonical",
        "abundance_dc_tag: taxonomy_rel_abundance",
        "abundance_split_col: locality",
        "collapse_rank: Phylum",
    ):
        assert key in exported


def test_a_tree_switched_to_full_view_round_trips():
    full_view = {**BUILT, "collapse_rank": None}
    exported = DashboardDataLite.from_full(_stored(full_view)).to_yaml()
    assert "collapse_rank" not in exported
    # The summary's settings ride along for the switch back.
    assert "size_by: abundance" in exported
    again = DashboardDataLite.from_yaml(exported).components[0].config
    assert again.collapse_rank is None
    assert (again.size_by, again.top_n, again.abundance_split_col) == ("abundance", 8, "locality")


def test_a_source_of_another_workflow_is_bound_by_ids_alone():
    # The builder writes no tag for it (the import resolves tags in the
    # component's own workflow only), and the ids go through untouched.
    elsewhere = {**BUILT, "abundance_wf_id": "wf-other", "abundance_dc_tag": None}
    again = (
        DashboardDataLite.from_yaml(DashboardDataLite.from_full(_stored(elsewhere)).to_yaml())
        .components[0]
        .config
    )
    assert (again.abundance_wf_id, again.abundance_dc_id, again.abundance_dc_tag) == (
        "wf-other",
        "dc-reads",
        None,
    )


def test_import_resolves_the_source_tags_in_the_target_project():
    """Exported from one instance, imported into a fresh project: every
    `<source>_dc_tag` is rewritten to that project's ids."""
    from unittest.mock import patch

    import mongomock
    from bson import ObjectId

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _resolve_workflow_tags

    ids = {tag: ObjectId() for tag in ("tree", "tips", "reads")}
    wf_id, project_id = ObjectId(), ObjectId()
    db = mongomock.MongoClient().test_db
    db.projects.insert_one(
        {
            "_id": project_id,
            "workflows": [
                {
                    "_id": wf_id,
                    "name": "ampliseq",
                    "engine": {"name": "nextflow"},
                    "data_collections": [
                        {"_id": ids["tree"], "data_collection_tag": "phylogenetic_tree_canonical"},
                        {
                            "_id": ids["tips"],
                            "data_collection_tag": "phylogenetic_tree_metadata_canonical",
                        },
                        {"_id": ids["reads"], "data_collection_tag": "taxonomy_rel_abundance"},
                    ],
                }
            ],
        }
    )
    exported = DashboardDataLite.from_full(_stored(BUILT)).to_yaml()
    component = DashboardDataLite.from_yaml(exported).to_full()["stored_metadata"][0]
    component["workflow_tag"] = "ampliseq"

    routes = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    with patch(f"{routes}.projects_collection", db.projects):
        _resolve_workflow_tags(component, project_id=project_id)

    cfg = component["config"]
    for source, tag in (("tree", "tree"), ("metadata", "tips"), ("abundance", "reads")):
        assert (cfg[f"{source}_wf_id"], cfg[f"{source}_dc_id"]) == (str(wf_id), str(ids[tag]))


def test_a_tree_is_a_data_collection_an_advanced_viz_may_bind():
    # The builder lists phylogeny DCs for an advanced viz: the tree is the
    # component's own DC (the YAML's `data_collection_tag`).
    from depictio.models.components.validation import (
        DC_COMPONENT_TYPE_MAPPING,
        validate_component_dc_type_compatibility,
    )

    assert validate_component_dc_type_compatibility("AdvancedViz", "phylogeny")[0]
    assert "AdvancedViz" in DC_COMPONENT_TYPE_MAPPING["phylogeny"]
