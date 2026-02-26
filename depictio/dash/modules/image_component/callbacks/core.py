"""
Image Component - Core Rendering Callbacks

Callbacks for rendering images in view mode (always loaded at app startup):
- render_image_grid: Render image grid from data collection with filtering
- toggle_image_modal: Handle modal open/close on thumbnail click
"""

from __future__ import annotations

from typing import Any

import dash
import dash_mantine_components as dmc
from bson import ObjectId
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html, no_update

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.modules.image_component.utils import (
    build_image_url,
    is_supported_image_format,
)
from depictio.dash.utils import extend_filters_via_links

# =============================================================================
# Filter Extraction Helpers
# =============================================================================


def _build_metadata_index(
    metadata_list: list | None,
    metadata_ids: list | None,
) -> dict[str, dict]:
    """Build a mapping from component index to full metadata."""
    if not metadata_list or not metadata_ids:
        return {}
    return {
        meta_id["index"]: metadata_list[idx]
        for idx, meta_id in enumerate(metadata_ids)
        if idx < len(metadata_list)
    }


def _enrich_filter_components(
    components: list[dict],
    metadata_by_index: dict[str, dict],
) -> list[dict]:
    """Enrich filter components with full metadata.

    Handles both regular interactive components (metadata from stores) and
    selection sources (scatter_selection, table_selection) which have metadata
    embedded in the store entry itself.
    """
    enriched = []
    for comp in components:
        source = comp.get("source")

        # Handle selection sources (scatter_selection, table_selection)
        if source in ("scatter_selection", "table_selection", "map_selection"):
            selection_metadata = {
                "dc_id": comp.get("dc_id"),
                "column_name": comp.get("column_name"),
                "interactive_component_type": "MultiSelect",
                "source": source,
            }
            enriched.append({**comp, "metadata": selection_metadata})
        else:
            # Regular interactive components need metadata lookup
            enriched.append({**comp, "metadata": metadata_by_index.get(str(comp.get("index")), {})})
    return enriched


def _group_filters_by_dc(components: list[dict]) -> dict[str, list[dict]]:
    """Group filter components by their data collection ID."""
    filters_by_dc: dict[str, list[dict]] = {}
    for component in components:
        dc_id = str(component.get("metadata", {}).get("dc_id", ""))
        if dc_id:
            filters_by_dc.setdefault(dc_id, []).append(component)
    return filters_by_dc


def _filter_active_components(components: list[dict]) -> list[dict]:
    """Filter out components with empty or null values."""
    empty_values = (None, [], "", False)
    return [c for c in components if c.get("value") not in empty_values]


def _get_dc_image_config(dc_id: str, access_token: str) -> dict | None:
    """Fetch image-specific properties from DC config."""
    import httpx

    from depictio.api.v1.configs.config import API_BASE_URL

    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )

        if response.status_code != 200:
            return None

        dc_data = response.json()
        config = dc_data.get("config", {})

        if config.get("type", "").lower() != "image":
            return None

        props = config.get("dc_specific_properties", {})
        return {
            "image_column": props.get("image_column"),
            "s3_base_folder": props.get("s3_base_folder"),
            "thumbnail_size": props.get("thumbnail_size", 150),
            "supported_formats": props.get("supported_formats", []),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch DC image config for {dc_id}: {e}")
        return None


def _extract_filters_for_image(
    dc_id: str,
    filters_data: dict | None,
    interactive_metadata_list: list | None,
    interactive_metadata_ids: list | None,
    project_metadata: dict | None,
    access_token: str | None = None,
) -> list[dict]:
    """Extract active filters for an image component including cross-DC links."""
    if not filters_data or not filters_data.get("interactive_components_values"):
        return []

    metadata_by_index = _build_metadata_index(interactive_metadata_list, interactive_metadata_ids)
    components = filters_data.get("interactive_components_values", [])
    enriched = _enrich_filter_components(components, metadata_by_index)
    filters_by_dc = _group_filters_by_dc(enriched)

    dc_id_str = str(dc_id)
    relevant_filters = list(filters_by_dc.get(dc_id_str, []))

    # Add filters from linked DCs
    link_filters = extend_filters_via_links(
        target_dc_id=dc_id_str,
        filters_by_dc=filters_by_dc,
        project_metadata=project_metadata,
        access_token=access_token,
        component_type="image",
    )
    if link_filters:
        relevant_filters.extend(link_filters)

    return _filter_active_components(relevant_filters)


def _centered_message(text: str, italic: bool = True) -> list:
    """Create a centered message element for empty states."""
    return [
        dmc.Center(
            dmc.Text(text, c="dimmed", fs="italic" if italic else None),
            style={"padding": "2rem"},
        )
    ]


def _build_thumbnail(
    img_path: str,
    img_idx: int,
    comp_index: str,
    s3_base_folder: str,
    api_base_url: str,
    thumbnail_size: int,
) -> html.Div:
    """Build a single thumbnail card with click tracking."""
    img_url = build_image_url(
        relative_path=str(img_path),
        base_s3_folder=s3_base_folder,
        api_base_url=api_base_url,
    )
    filename = str(img_path).split("/")[-1]

    thumbnail = dmc.Card(
        children=[
            dmc.CardSection(
                html.Img(
                    src=img_url,
                    style={
                        "width": "100%",
                        "height": f"{thumbnail_size}px",
                        "objectFit": "cover",
                        "cursor": "pointer",
                        "display": "block",
                    },
                ),
                style={"overflow": "visible"},
            ),
            dmc.Text(filename, size="xs", c="dimmed", truncate=True, ta="center", mt="xs"),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        p=0,
        className="image-thumbnail-card",
        style={"overflow": "visible", "cursor": "pointer"},
    )

    return html.Div(
        [
            thumbnail,
            dcc.Store(
                id={"type": "image-thumb-data", "index": comp_index, "img_index": img_idx},
                data={"src": img_url, "title": filename, "path": str(img_path)},
            ),
        ],
        id={"type": "image-thumb-card", "index": comp_index, "img_index": img_idx},
        n_clicks=0,
    )


def register_core_callbacks(app):
    """Register core rendering callbacks for image component."""

    @app.callback(
        Output({"type": "image-grid", "index": ALL}, "children"),
        Input({"type": "image-trigger", "index": ALL}, "data"),
        Input("interactive-values-store", "data"),
        State({"type": "image-trigger", "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "id"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "id"),
        State("local-store", "data"),
        State("project-metadata-store", "data"),
        prevent_initial_call=False,
    )
    def render_image_grid(
        trigger_data_list: list[dict[str, Any] | None],
        filters_data: dict[str, Any] | None,
        trigger_ids: list[dict[str, Any]],
        stored_metadata_list: list[dict[str, Any] | None],
        stored_metadata_ids: list[dict[str, Any]],
        interactive_metadata_list: list[dict[str, Any] | None],
        interactive_metadata_ids: list[dict[str, Any]],
        local_data: dict[str, Any] | None,
        project_metadata: dict[str, Any] | None,
    ) -> list[list[Any]]:
        """Render image grid from data collection with interactive filtering."""
        if not trigger_data_list or not any(trigger_data_list):
            return [[no_update] for _ in trigger_data_list] if trigger_data_list else []

        access_token = local_data.get("access_token") if local_data else None
        if not access_token:
            logger.error("No access token for image grid rendering")
            return [[dmc.Alert("Authentication required", color="red")] for _ in trigger_data_list]

        from depictio.api.v1.configs.config import settings

        api_base_url = f"http://localhost:{settings.fastapi.port}"
        all_grids: list[list[Any]] = []

        for trigger_data, trigger_id in zip(trigger_data_list, trigger_ids):
            component_id = trigger_id.get("index", "unknown")[:8] if trigger_id else "unknown"

            if not trigger_data or not isinstance(trigger_data, dict):
                all_grids.append([no_update])
                continue

            try:
                wf_id = trigger_data.get("wf_id")
                dc_id = trigger_data.get("dc_id")
                image_column = trigger_data.get("image_column")
                s3_base_folder = trigger_data.get("s3_base_folder", "")
                thumbnail_size = trigger_data.get("thumbnail_size", 150)
                max_images = trigger_data.get("max_images", 20)

                # Get fresh config from DC for image_column and s3_base_folder
                if dc_id and access_token:
                    dc_config = _get_dc_image_config(dc_id, access_token)
                    if dc_config:
                        image_column = image_column or dc_config.get("image_column")
                        s3_base_folder = dc_config.get("s3_base_folder") or s3_base_folder

                if not all([wf_id, dc_id, image_column]):
                    logger.warning(f"Image {component_id}: Missing required parameters")
                    all_grids.append(_centered_message("Configure image column in edit mode"))
                    continue

                # Extract filters including cross-DC links
                filters = _extract_filters_for_image(
                    dc_id=str(dc_id),
                    filters_data=filters_data,
                    interactive_metadata_list=interactive_metadata_list,
                    interactive_metadata_ids=interactive_metadata_ids,
                    project_metadata=project_metadata,
                    access_token=access_token,
                )

                # Load data with filters
                data = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id),
                    metadata=filters if filters else None,
                    TOKEN=access_token,
                )

                if data is None or len(data) == 0:
                    if filters:
                        logger.info(f"Image {component_id}: No data after {len(filters)} filters")
                        all_grids.append(_centered_message("No images match the current filter"))
                    else:
                        logger.warning(f"Image {component_id}: No data found")
                        all_grids.append(_centered_message("No data found"))
                    continue

                if image_column not in data.columns:
                    logger.error(f"Image {component_id}: Column '{image_column}' not found")
                    all_grids.append([dmc.Alert(f"Column '{image_column}' not found", color="red")])
                    continue

                # Get unique, sorted image paths
                image_paths = data[image_column].unique(maintain_order=True).to_list()
                image_paths = [p for p in image_paths if p and is_supported_image_format(str(p))]
                image_paths = sorted(image_paths)[:max_images]

                if not image_paths:
                    all_grids.append(_centered_message("No images found in data"))
                    continue

                # Build thumbnails
                comp_index = trigger_id.get("index")
                thumbnails = [
                    _build_thumbnail(
                        img_path,
                        idx,
                        comp_index,
                        s3_base_folder or "",
                        api_base_url,
                        thumbnail_size,
                    )
                    for idx, img_path in enumerate(image_paths)
                ]

                all_grids.append(thumbnails)
                filter_info = f" ({len(filters)} filters)" if filters else ""
                logger.info(
                    f"Image {component_id}: Rendered {len(thumbnails)} thumbnails{filter_info}"
                )

            except Exception as e:
                logger.error(f"Image {component_id}: Error rendering grid: {e}")
                all_grids.append([dmc.Alert(f"Error loading images: {str(e)}", color="red")])

        return all_grids

    @app.callback(
        Output({"type": "image-modal", "index": MATCH}, "opened"),
        Output({"type": "image-modal-img", "index": MATCH}, "src"),
        Output({"type": "image-modal-title", "index": MATCH}, "children"),
        Input({"type": "image-thumb-card", "index": MATCH, "img_index": ALL}, "n_clicks"),
        State({"type": "image-thumb-data", "index": MATCH, "img_index": ALL}, "data"),
        State({"type": "image-modal", "index": MATCH}, "opened"),
        prevent_initial_call=True,
    )
    def toggle_image_modal(
        n_clicks_list: list[int | None],
        thumb_data_list: list[dict[str, str]],
        current_opened: bool,
    ) -> tuple[bool, str, str]:
        """Toggle image modal on thumbnail click."""
        if not ctx.triggered or not ctx.triggered[0].get("value"):
            raise dash.exceptions.PreventUpdate

        triggered_id = ctx.triggered_id
        if not triggered_id:
            raise dash.exceptions.PreventUpdate

        clicked_idx = triggered_id.get("img_index")
        if clicked_idx is not None and clicked_idx < len(thumb_data_list):
            img_data = thumb_data_list[clicked_idx]
            return True, img_data.get("src", ""), img_data.get("title", "")

        raise dash.exceptions.PreventUpdate

    @app.callback(
        Output({"type": "image-modal", "index": MATCH}, "opened", allow_duplicate=True),
        Input({"type": "image-modal", "index": MATCH}, "opened"),
        prevent_initial_call=True,
    )
    def handle_modal_close(opened: bool) -> bool:
        """Handle modal close event (pass through)."""
        return opened
