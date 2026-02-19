"""
Callbacks for the ref_line_slider component.

Registers:
1. Slider → display text (clientside, shows current value)
2. Slider → value store (updates dcc.Store with current value + tag)
3. All slider stores → all figure stored-metadata + figure-triggers (updates ref lines + highlights)
4. All slider stores → highlight-filter tables (filters and shows matching rows)
"""

import time
from typing import Any

from dash import Input, Output, State, no_update
from dash import callback_context as ctx
from dash.dependencies import ALL, MATCH

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.modules.ref_line_slider_component.filter_utils import build_filter_mask

# Per-app registration guard
_registered_apps: set[int] = set()


def register_ref_line_slider_callbacks(app) -> bool:
    """Register all ref_line_slider callbacks for the given app.

    Args:
        app: Dash app instance.

    Returns:
        True if callbacks were registered, False if already registered.
    """
    app_id = id(app)
    if app_id in _registered_apps:
        logger.warning(
            f"⚠️  ref_line_slider callbacks already registered for app {app_id}, skipping"
        )
        return False

    logger.warning(f"📝 Registering ref_line_slider callbacks for app {app_id}")

    _register_display_callback(app)
    _register_store_callback(app)
    _register_figure_update_callback(app)

    _registered_apps.add(app_id)
    logger.warning(f"✅ ref_line_slider callbacks registered for app {app_id}")
    return True


def _register_display_callback(app) -> None:
    """Clientside callback to update the displayed value text."""
    app.clientside_callback(
        """
        function(slider_value) {
            if (slider_value === null || slider_value === undefined) {
                return window.dash_clientside.no_update;
            }
            return slider_value.toFixed(2);
        }
        """,
        Output({"type": "ref-line-slider-display", "index": MATCH}, "children"),
        Input({"type": "ref-line-slider", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )


def _register_store_callback(app) -> None:
    """Update the value store when the slider changes."""

    @app.callback(
        Output({"type": "ref-line-slider-value", "index": MATCH}, "data"),
        Input({"type": "ref-line-slider", "index": MATCH}, "value"),
        State({"type": "ref-line-slider-value", "index": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def update_slider_store(slider_value: float, current_data: dict[str, Any]) -> dict[str, Any]:
        """Persist the current slider value into the store."""
        new_data = dict(current_data or {})
        new_data["value"] = slider_value
        return new_data


def _register_figure_update_callback(app) -> None:
    """Watch ALL slider stores and update ALL linked figure stored-metadata + triggers."""

    @app.callback(
        Output({"type": "stored-metadata-component", "index": ALL}, "data", allow_duplicate=True),
        Output({"type": "figure-trigger", "index": ALL}, "data", allow_duplicate=True),
        Input({"type": "ref-line-slider-value", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "figure-trigger", "index": ALL}, "data"),
        prevent_initial_call=True,
    )
    def update_figures_from_ref_line_sliders(
        slider_data_list: list[dict[str, Any] | None],
        all_stored_metadata: list[dict[str, Any] | None],
        all_triggers: list[dict[str, Any] | None],
    ) -> tuple[list, list]:
        """
        For each figure with `linked_slider` references in its customizations,
        update the reference line position and any dynamic highlight conditions.

        NOTE: stored-metadata-component (ALL) includes all component types (figure, card,
        table, etc.) while figure-trigger (ALL) only exists for figure components, so
        these two lists have different lengths and must NOT be zipped together.
        We use callback_context to match triggers to their corresponding metadata by index.
        """
        # Build tag → value map from all slider stores
        slider_map: dict[str, float] = {}
        for store_data in slider_data_list or []:
            if store_data and "tag" in store_data and "value" in store_data:
                slider_map[store_data["tag"]] = float(store_data["value"])

        if not slider_map:
            return [no_update] * len(all_stored_metadata), [no_update] * len(all_triggers)

        # Map component index → position in each ALL list via callback context
        # states_list[0] = stored-metadata-component entries, states_list[1] = figure-trigger entries
        metadata_ids: list[str] = [
            entry["id"]["index"] for entry in (ctx.states_list[0] if ctx.states_list else [])
        ]
        trigger_ids: list[str] = [
            entry["id"]["index"]
            for entry in (ctx.states_list[1] if len(ctx.states_list) > 1 else [])
        ]
        trigger_idx_map: dict[str, int] = {idx: pos for pos, idx in enumerate(trigger_ids)}

        new_metadata: list = [no_update] * len(all_stored_metadata)
        new_triggers: list = [no_update] * len(all_triggers)

        for i, stored_meta in enumerate(all_stored_metadata or []):
            if not stored_meta or stored_meta.get("component_type") != "figure":
                continue

            customizations = stored_meta.get("customizations")
            if not customizations:
                continue

            changed = False
            ref_lines = list(customizations.get("reference_lines") or [])
            highlights = list(customizations.get("highlights") or [])

            # Update reference line positions
            for line in ref_lines:
                slider_tag = line.get("linked_slider")
                if not slider_tag or slider_tag not in slider_map:
                    continue
                new_val = slider_map[slider_tag]
                line_type = line.get("type", "vline")
                pos_key = "y" if line_type == "hline" else "x"
                if line.get(pos_key) != new_val:
                    line[pos_key] = new_val
                    changed = True
                    logger.debug(
                        f"Updated {line_type} {pos_key}={new_val} via slider '{slider_tag}'"
                    )

            # Update dynamic highlight conditions linked to sliders
            for highlight in highlights:
                for condition in highlight.get("conditions") or []:
                    cond_slider_tag = condition.get("linked_slider")
                    if not cond_slider_tag or cond_slider_tag not in slider_map:
                        continue
                    new_val = slider_map[cond_slider_tag]
                    if condition.get("value") != new_val:
                        condition["value"] = new_val
                        changed = True
                        logger.debug(
                            f"Updated highlight condition '{condition.get('name')}' "
                            f"value={new_val} via slider '{cond_slider_tag}'"
                        )

            if not changed:
                continue

            # Persist updated customizations
            updated_meta = dict(stored_meta)
            updated_customizations = dict(customizations)
            updated_customizations["reference_lines"] = ref_lines
            updated_customizations["highlights"] = highlights
            updated_meta["customizations"] = updated_customizations
            new_metadata[i] = updated_meta

            # Update the corresponding figure-trigger (matched by component index)
            comp_index = metadata_ids[i] if i < len(metadata_ids) else None
            if comp_index is not None and comp_index in trigger_idx_map:
                j = trigger_idx_map[comp_index]
                trigger = dict((all_triggers[j] if all_triggers and all_triggers[j] else {}))
                trigger["timestamp"] = time.time()
                trigger["source"] = "ref_line_slider"
                trigger["customizations"] = updated_customizations
                new_triggers[j] = trigger

        return new_metadata, new_triggers


def _register_highlight_table_callback(app) -> None:
    """Watch ALL slider stores and update highlight-filter table displays (MATCH per table)."""

    @app.callback(
        Output({"type": "highlight-filter-display", "index": MATCH}, "children"),
        Input({"type": "ref-line-slider-value", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def update_highlight_filter_table(
        slider_data_list: list[dict[str, Any] | None],
        stored_metadata: dict[str, Any] | None,
        local_store: dict[str, Any] | None,
    ):
        """Load and filter data for a highlight-filter table based on current slider values."""
        import dash_mantine_components as dmc
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite

        if not stored_metadata:
            return dmc.Text("No metadata", size="sm", c="dimmed")

        highlight_filter = stored_metadata.get("highlight_filter")
        if not highlight_filter:
            return no_update

        # Build slider tag → value map
        slider_map: dict[str, float] = {}
        for store_data in slider_data_list or []:
            if store_data and "tag" in store_data and "value" in store_data:
                slider_map[store_data["tag"]] = float(store_data["value"])

        # Load data
        wf_id = stored_metadata.get("wf_id")
        dc_id = stored_metadata.get("dc_id")
        token = (local_store or {}).get("access_token")

        if not wf_id or not dc_id or not token:
            return dmc.Text("Missing data connection", size="sm", c="dimmed")

        try:
            df = load_deltatable_lite(ObjectId(wf_id), ObjectId(dc_id), TOKEN=token)
        except Exception as e:
            logger.error(f"highlight_filter_table: failed to load data: {e}")
            return dmc.Text(f"Data unavailable: {e}", size="sm", c="red")

        if df.is_empty():
            return dmc.Text("No data", size="sm", c="dimmed")

        # Apply filter conditions
        conditions = highlight_filter.get("conditions") or []
        logic = highlight_filter.get("logic", "and")
        mask = build_filter_mask(df, conditions, slider_map, logic)

        filtered = df.filter(mask) if mask is not None else df

        if filtered.is_empty():
            return dmc.Text("No matching rows", size="sm", c="dimmed")

        # Render as a simple DMC table (first 100 rows)
        display_df = filtered.head(100)
        columns = display_df.columns

        header = dmc.TableThead(
            dmc.TableTr([dmc.TableTh(col, style={"fontSize": "12px"}) for col in columns])
        )
        rows = [
            dmc.TableTr(
                [
                    dmc.TableTd(
                        str(display_df[col][i]),
                        style={"fontSize": "11px"},
                    )
                    for col in columns
                ]
            )
            for i in range(len(display_df))
        ]
        body = dmc.TableTbody(rows)

        return [
            dmc.Text(
                f"{len(filtered)} matching rows"
                + (" (showing 100)" if len(filtered) > 100 else ""),
                size="xs",
                c="dimmed",
                mb="xs",
            ),
            dmc.Table(
                [header, body],
                striped=True,
                highlightOnHover=True,
                withTableBorder=True,
                withColumnBorders=True,
                style={"fontSize": "11px"},
            ),
        ]


