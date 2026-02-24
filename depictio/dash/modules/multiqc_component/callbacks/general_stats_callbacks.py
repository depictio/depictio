"""General Statistics callbacks for MultiQC component.

Three MATCH callbacks:
1. View toggle (Table <-> Violin)
2. Read-mode toggle (Mean/R1/R2/All) - swaps data + styles + violin
3. Interactive filtering - filters rows by sample from interactive-values-store
"""

import dash
from dash import ALL, MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


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
            table_style = {
                "display": "none",
                "border": "none",
                "borderTop": "1px solid #ddd",
                "borderBottom": "1px solid #ddd",
                "overflow": "auto",
                "maxHeight": "600px",
            }
            violin_style = {"display": "block"}
        else:
            table_style = {
                "border": "none",
                "borderTop": "1px solid #ddd",
                "borderBottom": "1px solid #ddd",
                "overflow": "auto",
                "maxHeight": "600px",
            }
            violin_style = {"display": "none"}

        return table_style, violin_style

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
        prevent_initial_call=True,
    )
    def filter_general_stats_by_interactive(
        interactive_values,
        stored_metadata,
        store_data,
        current_read_mode,
        interactive_metadata_list,
    ):
        """Filter general stats table/violin when interactive components change."""
        logger.info(
            f"[GS-FILTER] ENTERED - stored_metadata keys: {list(stored_metadata.keys()) if stored_metadata else 'None'}"
        )

        # Guard: not a general stats component
        if not stored_metadata:
            logger.info("[GS-FILTER] EXIT: no stored_metadata")
            return dash.no_update, dash.no_update
        is_gs = (
            stored_metadata.get("selected_plot") == "general_stats"
            or stored_metadata.get("selected_module") == "general_stats"
        )
        logger.info(
            f"[GS-FILTER] is_gs={is_gs}, selected_plot={stored_metadata.get('selected_plot')}, "
            f"selected_module={stored_metadata.get('selected_module')}"
        )
        if not is_gs:
            logger.info("[GS-FILTER] EXIT: not general_stats")
            return dash.no_update, dash.no_update

        # Guard: no store data
        if not store_data:
            logger.info("[GS-FILTER] EXIT: no store_data")
            return dash.no_update, dash.no_update

        # Get current mode data
        mode = current_read_mode or "mean"
        if mode not in store_data:
            logger.info(f"[GS-FILTER] EXIT: mode '{mode}' not in store_data keys: {list(store_data.keys())}")
            return dash.no_update, dash.no_update
        mode_data = store_data[mode]
        full_data = mode_data["table_data"]

        # No interactive values or empty -> reset to full data
        if not interactive_values:
            logger.info("[GS-FILTER] No interactive_values -> returning full data")
            return full_data, dash.no_update

        logger.info(
            f"[GS-FILTER] interactive_values keys: {list(interactive_values.keys())}"
        )

        # Parse interactive_components_values from the store
        # Store structure: {"interactive_components_values": [{"index": ..., "value": ...}], ...}
        components_values = interactive_values.get("interactive_components_values", [])
        logger.info(f"[GS-FILTER] components_values count: {len(components_values)}")
        if not components_values:
            logger.info("[GS-FILTER] No components_values -> returning full data")
            return full_data, dash.no_update

        # Build index->value lookup from the store
        values_by_index = {}
        for comp in components_values:
            idx = comp.get("index")
            val = comp.get("value")
            if idx and val:
                values_by_index[idx] = val
            logger.info(f"[GS-FILTER]   comp index={idx}, value type={type(val).__name__}, value={val}")

        logger.info(f"[GS-FILTER] values_by_index has {len(values_by_index)} entries")
        if not values_by_index:
            logger.info("[GS-FILTER] No values_by_index -> returning full data")
            return full_data, dash.no_update

        # Log interactive metadata
        logger.info(f"[GS-FILTER] interactive_metadata_list count: {len(interactive_metadata_list or [])}")
        for i, meta in enumerate(interactive_metadata_list or []):
            if meta:
                logger.info(
                    f"[GS-FILTER]   meta[{i}]: index={meta.get('index')}, "
                    f"dc_id={meta.get('dc_id') or meta.get('data_collection_id')}"
                )

        logger.info(
            f"[GS-FILTER] multiqc dc_id={stored_metadata.get('dc_id') or stored_metadata.get('data_collection_id')}"
        )
        logger.info(f"[GS-FILTER] all_samples count: {len(store_data.get('all_samples', []))}")
        logger.info(f"[GS-FILTER] all_samples (first 5): {store_data.get('all_samples', [])[:5]}")

        # Extract sample names using DC-matching + sample expansion
        selected_samples = _extract_samples_from_interactive(
            values_by_index,
            stored_metadata,
            store_data,
            interactive_metadata_list,
        )

        if selected_samples is None:
            logger.info("[GS-FILTER] _extract returned None -> returning full data")
            return full_data, dash.no_update

        # Filter table data
        filtered_data = [
            row for row in full_data if row.get("Sample Name") in selected_samples
        ]

        logger.info(
            f"[GS-FILTER] SUCCESS: {len(filtered_data)}/{len(full_data)} rows "
            f"({len(selected_samples)} samples: {selected_samples})"
        )

        return filtered_data, dash.no_update


def _extract_samples_from_interactive(
    values_by_index: dict[str, list],
    stored_metadata: dict,
    store_data: dict,
    interactive_metadata_list: list,
) -> set[str] | None:
    """Extract selected sample names from interactive component values.

    Args:
        values_by_index: Dict mapping component index to its selected values.
        stored_metadata: This component's stored metadata (has dc_id).
        store_data: General stats store data (has all_samples).
        interactive_metadata_list: All interactive component metadata (has dc_id per component).

    Returns:
        Set of sample names to keep, or None if no filtering should be applied.
    """
    all_samples = set(store_data.get("all_samples", []))
    if not all_samples:
        return None

    # Get this component's data collection ID
    multiqc_dc_id = stored_metadata.get("dc_id") or stored_metadata.get(
        "data_collection_id"
    )
    if not multiqc_dc_id:
        return None

    # Find interactive components targeting the same DC
    # Match component index from metadata to its value in the store
    selected_values = None
    for interactive_meta in interactive_metadata_list or []:
        if not interactive_meta:
            continue

        interactive_dc_id = interactive_meta.get("dc_id") or interactive_meta.get(
            "data_collection_id"
        )
        if str(interactive_dc_id) != str(multiqc_dc_id):
            continue

        interactive_id = interactive_meta.get("index")
        if interactive_id and interactive_id in values_by_index:
            vals = values_by_index[interactive_id]
            if isinstance(vals, list) and vals:
                selected_values = vals
                break

    if not selected_values:
        return None

    # Expand canonical sample IDs to variants (e.g. SRR123 -> SRR123_1, SRR123_2)
    expanded = set()
    for val in selected_values:
        val_str = str(val)
        if val_str in all_samples:
            expanded.add(val_str)
        # Also check paired-end variants
        for suffix in ("_1", "_2"):
            variant = f"{val_str}{suffix}"
            if variant in all_samples:
                expanded.add(val_str)
                expanded.add(variant)

    if expanded:
        return expanded & all_samples

    # Last resort: try direct match of values against sample names
    value_set = {str(v) for v in selected_values}
    overlap = value_set & all_samples
    return overlap if overlap else None
