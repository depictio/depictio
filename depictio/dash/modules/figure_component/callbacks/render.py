"""
Figure Component - Render Callbacks

This module contains callbacks for rendering figure previews during design/creation mode.
These callbacks listen to parameter changes and update the figure preview in real-time.
"""

import dash
from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


def register_render_callbacks(app):
    """Register figure rendering callbacks for preview mode."""

    @app.callback(
        Output({"type": "figure-design-preview", "index": MATCH}, "figure"),
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        ],
        [
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
            State({"type": "figure-design-preview", "index": MATCH}, "id"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def render_figure_preview(
        dict_kwargs,
        visu_type,
        workflow,
        data_collection,
        metadata,
        graph_id,
        local_data,
    ):
        """
        Render figure preview when parameters change.

        This callback fires when:
        1. Parameters change in dict_kwargs store (user selects x, y, color, etc.)
        2. Visualization type changes

        It loads the data and generates a Plotly figure for preview.
        """

        if not local_data:
            raise dash.exceptions.PreventUpdate

        # Skip if no visualization type selected yet
        if not visu_type:
            logger.info("🚫 RENDER: No visualization type selected")
            raise dash.exceptions.PreventUpdate

        logger.info("=" * 80)
        logger.info("🎨 RENDER: Generating figure preview")
        logger.info(f"📊 Component ID: {graph_id.get('index', 'unknown')}")
        logger.info(f"📈 Visualization type: {visu_type}")
        logger.info(f"🔧 Parameters: {dict_kwargs}")
        logger.info(f"📁 Workflow: {workflow}")
        logger.info(f"📁 Data Collection: {data_collection}")
        logger.info("=" * 80)

        try:
            # Import dependencies
            from depictio.api.v1.deltatables_utils import load_deltatable_lite
            from depictio.dash.modules.figure_component.utils import render_figure

            TOKEN = local_data["access_token"]

            # Get workflow and data collection IDs from metadata if not provided
            wf_id = workflow or (metadata.get("wf_id") if metadata else None)
            dc_id = data_collection or (metadata.get("dc_id") if metadata else None)

            if not wf_id or not dc_id:
                logger.warning("🚫 RENDER: Missing workflow or data collection ID")
                return {}

            # Load data
            logger.info(f"📥 Loading data from workflow {wf_id}, collection {dc_id}")
            df = load_deltatable_lite(workflow_id=wf_id, data_collection_id=dc_id, TOKEN=TOKEN)

            if df is None or df.height == 0:
                logger.warning("🚫 RENDER: No data loaded")
                return {}

            logger.info(f"✓ Loaded {df.height} rows × {len(df.columns)} columns")

            # Render figure
            logger.info(f"🎨 Rendering {visu_type} visualization")
            figure, trace_metadata = render_figure(
                dict_kwargs=dict_kwargs or {},
                visu_type=visu_type,
                df=df,
                theme="light",  # TODO: Get theme from store
            )

            logger.info("✅ RENDER: Figure generated successfully")
            return figure

        except Exception as e:
            logger.error(f"❌ RENDER ERROR: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")

            # Return empty figure with error message
            return {
                "data": [],
                "layout": {
                    "title": f"Error: {str(e)}",
                    "annotations": [
                        {
                            "text": f"Failed to render figure:<br>{str(e)}",
                            "xref": "paper",
                            "yref": "paper",
                            "showarrow": False,
                            "font": {"size": 14, "color": "red"},
                        }
                    ],
                },
            }

    logger.info("✅ Figure render callbacks registered (preview rendering)")
