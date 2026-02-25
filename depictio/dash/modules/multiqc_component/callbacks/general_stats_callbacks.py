"""General Statistics callbacks for MultiQC component.

Three MATCH callbacks:
1. View toggle (Table <-> Violin)
2. Read-mode toggle (Mean/R1/R2/All) - swaps data + styles + violin
3. Interactive filtering - filters rows by sample from interactive-values-store
"""

import dash
import pandas as pd
from dash import ALL, MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.multiqc_component.general_stats import _create_violin_plot
from depictio.dash.utils import enrich_interactive_components_with_metadata, resolve_link_values

# Style used to truly hide a Plotly/Dash element (display:none is ignored by Plotly).
_HIDDEN_STYLE = {
    "position": "absolute",
    "visibility": "hidden",
    "overflow": "hidden",
    "height": "0",
    "width": "0",
    "pointerEvents": "none",
}

_TABLE_VISIBLE_STYLE = {
    "border": "none",
    "borderTop": "1px solid #ddd",
    "borderBottom": "1px solid #ddd",
    "overflow": "auto",
    "maxHeight": "600px",
}


def register_general_stats_callbacks(app):
    """Register general stats callbacks for MultiQC component."""

    # ------------------------------------------------------------------
    # 1. View toggle: Table <-> Violin
    # ------------------------------------------------------------------
    @app.callback(
        Output({"type": "general-stats-table", "index": MATCH}, "style_table"),
        Output({"type": "general-stats-violin", "index": MATCH}, "style"),
        Input({"type": "general-stats-view-toggle", "index": MATCH}, "value"),
        State({"type": "general-stats-store", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def toggle_general_stats_view(view_value, store_data):
        """Toggle between table and violin views."""
        if not store_data:
            return dash.no_update, dash.no_update

        if view_value == "violin":
            return _HIDDEN_STYLE, {"display": "block"}
        else:
            return _TABLE_VISIBLE_STYLE, _HIDDEN_STYLE

    # ------------------------------------------------------------------
    # 2. Read-mode toggle: Mean / R1 / R2 / All
    # ------------------------------------------------------------------
    @app.callback(
        Output({"type": "general-stats-table", "index": MATCH}, "data"),
        Output(
            {"type": "general-stats-table", "index": MATCH},
            "style_data_conditional",
        ),
        Output({"type": "general-stats-violin", "index": MATCH}, "figure"),
        Input({"type": "general-stats-read-toggle", "index": MATCH}, "value"),
        State({"type": "general-stats-store", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def switch_general_stats_read_mode(read_mode, store_data):
        """Switch table data and violin when read mode changes."""
        if not store_data or read_mode not in store_data:
            return dash.no_update, dash.no_update, dash.no_update

        mode_data = store_data[read_mode]
        return (
            mode_data["table_data"],
            mode_data["table_styles"],
            mode_data["violin_figure"],
        )

    # ------------------------------------------------------------------
    # 3. Interactive filtering (sample selection from other components)
    # ------------------------------------------------------------------
    @app.callback(
        Output(
            {"type": "general-stats-table", "index": MATCH},
            "data",
            allow_duplicate=True,
        ),
        Output(
            {"type": "general-stats-violin", "index": MATCH},
            "figure",
            allow_duplicate=True,
        ),
        Input("interactive-values-store", "data"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        State({"type": "general-stats-store", "index": MATCH}, "data"),
        State({"type": "general-stats-read-toggle", "index": MATCH}, "value"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def filter_general_stats_by_interactive(
        interactive_values,
        stored_metadata,
        store_data,
        current_read_mode,
        interactive_metadata_list,
        interactive_metadata_ids,
        local_data,
    ):
        """Filter general stats table/violin when interactive components change.

        Uses the same enrichment + link resolution pattern as the regular
        MultiQC plot callback in core.py to support cross-DC filtering.
        """
        # Guard: not a general stats component
        if not stored_metadata:
            return dash.no_update, dash.no_update
        is_gs = (
            stored_metadata.get("selected_plot") == "general_stats"
            or stored_metadata.get("selected_module") == "general_stats"
        )
        if not is_gs:
            return dash.no_update, dash.no_update

        # Guard: no store data
        if not store_data:
            return dash.no_update, dash.no_update

        # Get current mode data
        mode = current_read_mode or "mean"
        if mode not in store_data:
            return dash.no_update, dash.no_update
        mode_data = store_data[mode]
        full_data = mode_data["table_data"]
        full_violin = mode_data["violin_figure"]

        # No interactive values or empty -> reset to full data + violin
        if not interactive_values:
            return full_data, full_violin

        components_values = interactive_values.get("interactive_components_values", [])
        if not components_values:
            return full_data, full_violin

        # Check if any component actually has a value
        has_any_value = any(comp.get("value") for comp in components_values)
        if not has_any_value:
            return full_data, full_violin

        # Enrich lightweight store data with full metadata
        enriched_components = enrich_interactive_components_with_metadata(
            interactive_values,
            interactive_metadata_list,
            interactive_metadata_ids,
        )

        if not enriched_components:
            return full_data, full_violin

        # Resolve filter values to sample names
        multiqc_dc_id = stored_metadata.get("dc_id") or stored_metadata.get("data_collection_id")
        project_id = stored_metadata.get("project_id")
        token = local_data.get("access_token") if local_data else None
        all_samples = set(store_data.get("all_samples", []))

        selected_samples = _resolve_samples_from_enriched(
            enriched_components=enriched_components,
            multiqc_dc_id=multiqc_dc_id,
            project_id=project_id,
            token=token,
            all_samples=all_samples,
            full_data=full_data,
        )

        if selected_samples is None:
            # No filtering could be applied — return full data
            return full_data, full_violin

        # Filter table data
        filtered_data = [row for row in full_data if row.get("Sample Name") in selected_samples]

        logger.info(
            f"[GS-FILTER] {len(filtered_data)}/{len(full_data)} rows "
            f"({len(selected_samples)} matched samples)"
        )

        # Rebuild violin from filtered data
        filtered_violin = _rebuild_violin_from_filtered(filtered_data, mode_data)

        return filtered_data, filtered_violin


def _resolve_samples_from_enriched(
    enriched_components: list[dict],
    multiqc_dc_id: str | None,
    project_id: str | None,
    token: str | None,
    all_samples: set[str],
    full_data: list[dict],
) -> set[str] | None:
    """Resolve enriched interactive component values to sample names.

    For each enriched component with a value:
    - Cross-DC (comp dc_id != multiqc dc_id): use resolve_link_values()
    - Same-DC, values are sample names: use directly
    - Same-DC, values are column values: scan table rows for matches

    Multiple components are intersected (AND semantics).

    Returns set of sample names, or None if no filtering applies.
    """
    if not multiqc_dc_id or not all_samples:
        return None

    resolved_sets: list[set[str]] = []

    for comp in enriched_components:
        value = comp.get("value")
        if not value:
            continue
        values_list = value if isinstance(value, list) else [value]
        if not values_list:
            continue

        metadata = comp.get("metadata", {})
        comp_dc_id = metadata.get("dc_id") or metadata.get("data_collection_id")
        comp_column = metadata.get("column_name", "")

        if comp_dc_id and str(comp_dc_id) != str(multiqc_dc_id):
            # Cross-DC: use link resolution
            if not project_id or not token:
                continue
            resolved = resolve_link_values(
                project_id=project_id,
                source_dc_id=comp_dc_id,
                source_column=comp_column,
                filter_values=values_list,
                target_dc_id=multiqc_dc_id,
                token=token,
            )
            if resolved and resolved.get("resolved_values"):
                resolved_sets.append(set(resolved["resolved_values"]) & all_samples)
        else:
            # Same-DC: check if values are sample names
            value_strs = {str(v) for v in values_list}
            direct_match = value_strs & all_samples

            if direct_match:
                # Also expand paired-end variants
                expanded = set(direct_match)
                for val in direct_match:
                    for suffix in ("_1", "_2"):
                        variant = f"{val}{suffix}"
                        if variant in all_samples:
                            expanded.add(variant)
                resolved_sets.append(expanded)
            else:
                # Values are column values — scan table rows for matches
                matched_samples = set()
                for row in full_data:
                    sample = row.get("Sample Name")
                    if not sample:
                        continue
                    for col_val in row.values():
                        if str(col_val) in value_strs:
                            matched_samples.add(sample)
                            break
                if matched_samples:
                    resolved_sets.append(matched_samples)

    if not resolved_sets:
        return None

    # Intersect all resolved sets (AND semantics)
    result = resolved_sets[0]
    for s in resolved_sets[1:]:
        result = result & s

    return result if result else None


def _rebuild_violin_from_filtered(filtered_data: list[dict], mode_data: dict) -> dict:
    """Rebuild the violin figure from filtered table data.

    Uses original_to_tool and display_to_original stored in mode_data
    to call _create_violin_plot with the filtered DataFrame.
    """
    if not filtered_data:
        # Return an empty figure rather than the full violin
        return {"data": [], "layout": {"height": 100, "title": {"text": "No data"}}}

    original_to_tool = mode_data.get("original_to_tool", {})
    display_to_original = mode_data.get("display_to_original")

    df_filtered = pd.DataFrame(filtered_data)
    fig = _create_violin_plot(df_filtered, original_to_tool, display_to_original)
    return fig.to_dict()
