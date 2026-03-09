"""
Bioinformatics Modules — Demo App

Composes all 8 modules into a single Dash app with cross-module communication
via shared dcc.Store components. Each module runs in its own tab; shared stores
link interactions across tabs (e.g., selecting a contrast in Contrast Manager
automatically updates the Enrichment Explorer).

Communication graph:
    Progressive Filter  ──filtered_feature_ids──►  Contrast Manager, DimRed Explorer
    Progressive Filter  ──selected_features────►  Feature Explorer
    Feature Explorer    ──active_feature───────►  Progressive Filter, DimRed Explorer
    Contrast Manager    ──active_contrast──────►  Enrichment Explorer, Progressive Filter
    Contrast Manager    ──highlighted_samples──►  DimRed Explorer, Taxonomy Browser
"""

import sys
from pathlib import Path

import dash_mantine_components as dmc
from dash import Dash, Input, Output, callback_context, dcc, html
from dash_iconify import DashIconify

# Add parent dir to path so modules can import shared_stores / shared_data
sys.path.insert(0, str(Path(__file__).parent))

from modules import contrast_manager, dimred_explorer, enrichment_explorer, feature_explorer, peak_explorer, progressive_filter, taxonomy_browser, variant_inspector
from shared_data import load_all_data
from shared_stores import (
    ACTIVE_CONTRAST,
    ACTIVE_FEATURE,
    FILTERED_FEATURE_IDS,
    HIGHLIGHTED_SAMPLES,
    SELECTED_FEATURES,
    create_shared_stores,
)

# ─── Load all data once ──────────────────────────────────────────────────
DATA = load_all_data(seed=42)

# ─── Dash app ────────────────────────────────────────────────────────────
app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    external_stylesheets=[dmc.styles.ALL],
)


def _icon(name: str) -> DashIconify:
    return DashIconify(icon=name, width=18)


def _make_status_badge(store_id: str, label: str, icon: str) -> dmc.Badge:
    """Create a status badge that shows cross-module store state."""
    return dmc.Badge(
        label,
        id=f"status-{store_id}",
        leftSection=_icon(icon),
        variant="light",
        size="lg",
        radius="sm",
    )


# Module tab definitions
MODULE_TABS = [
    {
        "value": "progressive-filter",
        "label": "Progressive Filter",
        "icon": "tabler:filter",
        "module": progressive_filter,
    },
    {
        "value": "feature-explorer",
        "label": "Feature Explorer",
        "icon": "tabler:dna",
        "module": feature_explorer,
    },
    {
        "value": "contrast-manager",
        "label": "Contrast Manager",
        "icon": "tabler:arrows-diff",
        "module": contrast_manager,
    },
    {
        "value": "enrichment-explorer",
        "label": "Enrichment Explorer",
        "icon": "tabler:chart-dots-3",
        "module": enrichment_explorer,
    },
    {
        "value": "dimred-explorer",
        "label": "DimRed Explorer",
        "icon": "tabler:3d-cube-sphere",
        "module": dimred_explorer,
    },
    {
        "value": "peak-explorer",
        "label": "Peak Explorer",
        "icon": "tabler:chart-area-line",
        "module": peak_explorer,
    },
    {
        "value": "taxonomy-browser",
        "label": "Taxonomy Browser",
        "icon": "tabler:plant-2",
        "module": taxonomy_browser,
    },
    {
        "value": "variant-inspector",
        "label": "Variant Inspector",
        "icon": "tabler:virus",
        "module": variant_inspector,
    },
]

# ─── Layout ──────────────────────────────────────────────────────────────

app.layout = dmc.MantineProvider(
    forceColorScheme="light",
    children=[
        # Shared cross-module stores
        *create_shared_stores(),
        dmc.AppShell(
            [
                dmc.AppShellHeader(
                    dmc.Group(
                        [
                            dmc.Group(
                                [
                                    _icon("tabler:dna-2"),
                                    dmc.Title("Bioinformatics Modules", order=3),
                                ],
                                gap="xs",
                            ),
                            # Cross-module status bar
                            dmc.Group(
                                [
                                    _make_status_badge(
                                        FILTERED_FEATURE_IDS,
                                        "Filtered: --",
                                        "tabler:filter",
                                    ),
                                    _make_status_badge(
                                        ACTIVE_CONTRAST,
                                        "Contrast: --",
                                        "tabler:arrows-diff",
                                    ),
                                    _make_status_badge(
                                        ACTIVE_FEATURE,
                                        "Feature: --",
                                        "tabler:dna",
                                    ),
                                    _make_status_badge(
                                        HIGHLIGHTED_SAMPLES,
                                        "Samples: --",
                                        "tabler:users",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        justify="space-between",
                        px="md",
                        h="100%",
                    ),
                ),
                dmc.AppShellMain(
                    dmc.Container(
                        [
                            dmc.Tabs(
                                [
                                    dmc.TabsList(
                                        [
                                            dmc.TabsTab(
                                                tab["label"],
                                                leftSection=_icon(tab["icon"]),
                                                value=tab["value"],
                                            )
                                            for tab in MODULE_TABS
                                        ],
                                        grow=True,
                                    ),
                                    *[
                                        dmc.TabsPanel(
                                            tab["module"].create_layout(DATA),
                                            value=tab["value"],
                                            pt="md",
                                        )
                                        for tab in MODULE_TABS
                                    ],
                                ],
                                value="progressive-filter",
                                id="module-tabs",
                            ),
                        ],
                        fluid=True,
                        px="md",
                        py="md",
                    ),
                ),
            ],
            header={"height": 60},
            padding="md",
        ),
    ],
)


# ─── Register all module callbacks ───────────────────────────────────────

for tab in MODULE_TABS:
    tab["module"].register_callbacks(app, DATA)


# ─── Status bar callbacks (update badges from shared stores) ─────────────


@app.callback(
    Output(f"status-{FILTERED_FEATURE_IDS}", "children"),
    Input(FILTERED_FEATURE_IDS, "data"),
)
def update_filtered_badge(data):
    n = len(data) if data else 0
    return f"Filtered: {n}" if n > 0 else "Filtered: --"


@app.callback(
    Output(f"status-{ACTIVE_CONTRAST}", "children"),
    Input(ACTIVE_CONTRAST, "data"),
)
def update_contrast_badge(data):
    if data:
        short = data.replace("_vs_", " vs ").replace("_", " ")
        return f"Contrast: {short}"
    return "Contrast: --"


@app.callback(
    Output(f"status-{ACTIVE_FEATURE}", "children"),
    Input(ACTIVE_FEATURE, "data"),
)
def update_feature_badge(data):
    return f"Feature: {data}" if data else "Feature: --"


@app.callback(
    Output(f"status-{HIGHLIGHTED_SAMPLES}", "children"),
    Input(HIGHLIGHTED_SAMPLES, "data"),
)
def update_samples_badge(data):
    n = len(data) if data else 0
    return f"Samples: {n}" if n > 0 else "Samples: --"


# ─── Run ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=8070)
