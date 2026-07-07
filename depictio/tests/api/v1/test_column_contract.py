"""Tests for the dashboard column reuse-contract extractor (Phase 0).

``build_column_contract`` enumerates, per data collection, exactly which columns a
dashboard's components reference — the manifest bundled with a shared template so the
importer can validate the target data and pre-fill column-rename suggestions. These
tests pin the per-component-type binding rules and the cross-component aggregation.
"""

from depictio.api.v1.services.reuse.column_contract import build_column_contract


def _cols(contract, dc_tag):
    """Return the set of required column names for a DC tag."""
    return {req.name for req in contract.collections.get(dc_tag, [])}


class TestPerComponentType:
    def test_figure_dict_kwargs_and_selection(self):
        contract = build_column_contract(
            [
                {
                    "component_type": "figure",
                    "data_collection_tag": "t",
                    "dict_kwargs": {"x": "a", "y": "b", "color": "c", "hover_data": ["h1", "h2"]},
                    "selection_column": "sel",
                }
            ]
        )
        assert _cols(contract, "t") == {"a", "b", "c", "h1", "h2", "sel"}

    def test_code_mode_figure_is_skipped(self):
        # Arbitrary user code can read any column — not enumerable.
        contract = build_column_contract(
            [
                {
                    "component_type": "figure",
                    "data_collection_tag": "t",
                    "mode": "code",
                    "code_content": "px.scatter(df, x='hidden')",
                }
            ]
        )
        assert _cols(contract, "t") == set()

    def test_card_columns_and_declared_type(self):
        contract = build_column_contract(
            [
                {
                    "component_type": "card",
                    "data_collection_tag": "t",
                    "aggregation": "median",
                    "column_name": "mass",
                    "column_type": "float64",
                    "secondary_layout": "top_n",
                    "breakdown_col": "species",
                }
            ]
        )
        assert _cols(contract, "t") == {"mass", "species"}
        mass = next(r for r in contract.collections["t"] if r.name == "mass")
        assert mass.type == "float64"
        assert mass.roles == ["card:aggregation"]

    def test_interactive_filter(self):
        contract = build_column_contract(
            [
                {
                    "component_type": "interactive",
                    "data_collection_tag": "t",
                    "column_name": "species",
                    "column_type": "object",
                }
            ]
        )
        req = contract.collections["t"][0]
        assert (
            req.name == "species" and req.type == "object" and req.roles == ["interactive:filter"]
        )

    def test_table_columns_and_selection(self):
        contract = build_column_contract(
            [
                {
                    "component_type": "table",
                    "data_collection_tag": "t",
                    "columns": ["gene", "pvalue"],
                    "row_selection_column": "gene",
                }
            ]
        )
        assert _cols(contract, "t") == {"gene", "pvalue"}

    def test_image_columns_field_is_not_a_data_column(self):
        # `columns` on an image component is a grid-column *count* (int).
        contract = build_column_contract(
            [
                {
                    "component_type": "image",
                    "data_collection_tag": "t",
                    "image_column": "path",
                    "columns": 4,
                }
            ]
        )
        assert _cols(contract, "t") == {"path"}

    def test_map_bindings_and_hover_list(self):
        contract = build_column_contract(
            [
                {
                    "component_type": "map",
                    "data_collection_tag": "t",
                    "lat_column": "lat",
                    "lon_column": "lon",
                    "color_column": "region",
                    "hover_columns": ["city", "pop"],
                }
            ]
        )
        assert _cols(contract, "t") == {"lat", "lon", "region", "city", "pop"}

    def test_advanced_viz_role_col_fields(self):
        contract = build_column_contract(
            [
                {
                    "component_type": "advanced_viz",
                    "data_collection_tag": "t",
                    "config": {
                        "feature_id_col": "gene",
                        "effect_size_col": "logFC",
                        "label_cols": ["gene", "symbol"],
                        "top_n": 10,
                    },
                }
            ]
        )
        assert _cols(contract, "t") == {"gene", "logFC", "symbol"}

    def test_text_component_has_no_columns(self):
        contract = build_column_contract(
            [{"component_type": "text", "data_collection_tag": "t", "content": "hi"}]
        )
        assert contract.collections == {}


class TestAggregation:
    def test_roles_and_types_merge_across_components(self):
        contract = build_column_contract(
            [
                {
                    "component_type": "interactive",
                    "data_collection_tag": "t",
                    "column_name": "species",
                    "column_type": "object",
                },
                {
                    "component_type": "figure",
                    "data_collection_tag": "t",
                    "dict_kwargs": {"x": "species", "color": "species"},
                },
            ]
        )
        species = contract.collections["t"][0]
        assert species.name == "species"
        assert species.type == "object"
        # Deduped, one entry per distinct role.
        assert set(species.roles) == {"interactive:filter", "figure:x", "figure:color"}

    def test_separate_dcs_are_kept_separate(self):
        contract = build_column_contract(
            [
                {
                    "component_type": "card",
                    "data_collection_tag": "a",
                    "aggregation": "sum",
                    "column_name": "x",
                },
                {
                    "component_type": "card",
                    "data_collection_tag": "b",
                    "aggregation": "sum",
                    "column_name": "y",
                },
            ]
        )
        assert _cols(contract, "a") == {"x"}
        assert _cols(contract, "b") == {"y"}

    def test_component_without_dc_tag_is_skipped(self):
        contract = build_column_contract(
            [{"component_type": "card", "aggregation": "sum", "column_name": "x"}]
        )
        assert contract.collections == {}

    def test_empty_and_none_input(self):
        assert build_column_contract(None).collections == {}
        assert build_column_contract([]).collections == {}
