"""AI Dashboard Prototype — LiteLLM + Dash + DMC 2.0.

Run: python app.py
Requires: .env file with LLM_MODEL and provider API key (see .env.example)
"""

from __future__ import annotations

import json
import logging
import traceback

import dash_mantine_components as dmc
import pandas as pd
import plotly.express as px
from dash import Dash, Input, Output, State, callback, ctx, dcc, html, no_update
from dash_iconify import DashIconify

import llm_client
from components.ai_panel import create_ai_component_creator, create_ai_data_analyst
from components.cards import create_stat_card
from components.figures import create_figure
from components.interactive import create_multiselect, create_range_slider, create_select
from components.tables import create_table
from sample_data import DATASETS, get_column_metadata

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)-12s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------
app = Dash(
    __name__,
    external_stylesheets=dmc.styles.ALL,
    suppress_callback_exceptions=True,
)

# ---------------------------------------------------------------------------
# Dataset configs — defines default cards, figures, and filters per dataset
# ---------------------------------------------------------------------------
DATASET_CONFIGS = {
    "iris": {
        "cards": [
            {"title": "Total Samples", "col": None, "agg": "count", "icon": "mdi:flower", "color": "#7c3aed"},
            {"title": "Avg Sepal Length", "col": "sepal_length", "agg": "mean", "icon": "mdi:ruler", "color": "#2563eb"},
            {"title": "Avg Petal Width", "col": "petal_width", "agg": "mean", "icon": "mdi:leaf", "color": "#059669"},
            {"title": "Varieties", "col": "variety", "agg": "nunique", "icon": "mdi:tag-multiple", "color": "#d97706"},
        ],
        "figures": [
            {"visu_type": "scatter", "kwargs": {"x": "sepal_length", "y": "sepal_width", "color": "variety"}, "title": "Sepal: Length vs Width"},
            {"visu_type": "histogram", "kwargs": {"x": "petal_length", "color": "variety"}, "title": "Petal Length Distribution"},
        ],
        "filters": {
            "select": {"col": "variety", "label": "Variety"},
            "range": {"col": "sepal_length", "label": "Sepal Length"},
            "multiselect": {"col": "variety", "label": "Include Varieties"},
        },
    },
    "genomics_qc": {
        "cards": [
            {"title": "Total Samples", "col": None, "agg": "count", "icon": "mdi:dna", "color": "#7c3aed"},
            {"title": "Avg Mapping Rate", "col": "mapping_rate", "agg": "mean", "icon": "mdi:target", "color": "#2563eb"},
            {"title": "Avg Duplication", "col": "duplication_rate", "agg": "mean", "icon": "mdi:content-copy", "color": "#dc2626"},
            {"title": "Pass Rate", "col": "status", "agg": "pass_rate", "icon": "mdi:check-circle", "color": "#059669"},
        ],
        "figures": [
            {"visu_type": "scatter", "kwargs": {"x": "mapping_rate", "y": "duplication_rate", "color": "status"}, "title": "Mapping vs Duplication"},
            {"visu_type": "histogram", "kwargs": {"x": "gc_content", "color": "library_type"}, "title": "GC Content Distribution"},
        ],
        "filters": {
            "select": {"col": "library_type", "label": "Library Type"},
            "range": {"col": "mapping_rate", "label": "Mapping Rate (%)"},
            "multiselect": {"col": "status", "label": "Include Statuses"},
        },
    },
}


def compute_card_value(df: pd.DataFrame, col: str | None, agg: str) -> str:
    """Compute a metric value for a stat card."""
    if agg == "count":
        return f"{len(df):,}"
    if agg == "nunique":
        return str(df[col].nunique())
    if agg == "pass_rate":
        rate = (df[col] == "PASS").mean() * 100
        return f"{rate:.1f}%"
    val = getattr(df[col], agg)()
    return f"{val:,.2f}"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
app.layout = dmc.MantineProvider(
    dmc.AppShell(
        [
            # Header
            dmc.AppShellHeader(
                dmc.Group(
                    [
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:robot-happy", width=28, color="violet"),
                                dmc.Text("AI Dashboard Prototype", size="xl", fw=700),
                            ],
                            gap="xs",
                        ),
                        dmc.Group(
                            [
                                dmc.Text("Dataset:", size="sm", fw=500),
                                dmc.Select(
                                    id="dataset-selector",
                                    data=[{"label": v["label"], "value": k} for k, v in DATASETS.items()],
                                    value="iris",
                                    w=200,
                                    size="sm",
                                ),
                                dmc.Badge(
                                    f"LLM: {llm_client.get_model()}",
                                    variant="outline",
                                    color="violet",
                                    size="lg",
                                ),
                            ],
                            gap="sm",
                        ),
                    ],
                    justify="space-between",
                    h="100%",
                    px="md",
                ),
                h=60,
            ),
            # Main content
            dmc.AppShellMain(
                dmc.Container(
                    dmc.Stack(
                        [
                            # Metric Cards row
                            dmc.SimpleGrid(id="cards-row", cols=4, spacing="md"),
                            # Figures row
                            dmc.SimpleGrid(id="figures-row", cols=2, spacing="md"),
                            # Filters row
                            dmc.Paper(
                                dmc.Group(
                                    [
                                        dmc.Group(
                                            [
                                                DashIconify(icon="mdi:filter-variant", width=20),
                                                dmc.Text("Filters", size="md", fw=600),
                                            ],
                                            gap="xs",
                                        ),
                                        html.Div(id="filters-row", style={"display": "flex", "gap": "1rem", "flex": 1, "alignItems": "flex-end"}),
                                    ],
                                    gap="md",
                                    align="flex-end",
                                ),
                                withBorder=True,
                                radius="md",
                                p="md",
                            ),
                            # Table
                            html.Div(id="table-container"),
                            # AI section header
                            dmc.Divider(
                                label=dmc.Group(
                                    [
                                        DashIconify(icon="mdi:robot", width=20),
                                        dmc.Text("AI Assistant", fw=600),
                                    ],
                                    gap="xs",
                                ),
                                labelPosition="center",
                                size="sm",
                            ),
                            # AI panels
                            dmc.SimpleGrid(
                                [
                                    create_ai_component_creator(),
                                    create_ai_data_analyst(),
                                ],
                                cols=2,
                                spacing="md",
                            ),
                            # Dynamic AI-generated figures area
                            html.Div(id="ai-generated-figures"),
                        ],
                        gap="lg",
                        pt="md",
                    ),
                    size="xl",
                    py="md",
                ),
            ),
        ],
        header={"height": 60},
        padding="md",
    ),
    forceColorScheme="light",
)


# ---------------------------------------------------------------------------
# Helper: load dataset
# ---------------------------------------------------------------------------
def load_dataset(dataset_key: str) -> pd.DataFrame:
    return DATASETS[dataset_key]["loader"]()


# ---------------------------------------------------------------------------
# Callback: dataset change → rebuild cards, figures, filters, table
# ---------------------------------------------------------------------------
@callback(
    Output("cards-row", "children"),
    Output("figures-row", "children"),
    Output("filters-row", "children"),
    Output("table-container", "children"),
    Input("dataset-selector", "value"),
)
def update_dashboard(dataset_key):
    df = load_dataset(dataset_key)
    config = DATASET_CONFIGS[dataset_key]

    # Cards
    cards = []
    for c in config["cards"]:
        val = compute_card_value(df, c["col"], c["agg"])
        cards.append(create_stat_card(c["title"], val, c["icon"], c["color"]))

    # Figures
    figures = []
    for f in config["figures"]:
        figures.append(create_figure(df, f["visu_type"], f["kwargs"], title=f["title"]))

    # Filters
    fc = config["filters"]
    select_col = fc["select"]["col"]
    range_col = fc["range"]["col"]
    multi_col = fc["multiselect"]["col"]

    filters = [
        create_select("filter-select", fc["select"]["label"], df[select_col].unique().tolist()),
        html.Div(
            create_range_slider("filter-range", fc["range"]["label"], float(df[range_col].min()), float(df[range_col].max())),
            style={"flex": 1},
        ),
        create_multiselect("filter-multiselect", fc["multiselect"]["label"], df[multi_col].unique().tolist()),
    ]

    # Table
    table = create_table(df, "data-table")

    return cards, figures, filters, table


# ---------------------------------------------------------------------------
# Callback: filters → update figures + table
# ---------------------------------------------------------------------------
@callback(
    Output("figures-row", "children", allow_duplicate=True),
    Output("table-container", "children", allow_duplicate=True),
    Input("filter-select", "value"),
    Input("filter-range", "value"),
    Input("filter-multiselect", "value"),
    State("dataset-selector", "value"),
    prevent_initial_call=True,
)
def apply_filters(select_val, range_val, multi_val, dataset_key):
    df = load_dataset(dataset_key)
    config = DATASET_CONFIGS[dataset_key]
    fc = config["filters"]

    # Apply select filter
    if select_val:
        df = df[df[fc["select"]["col"]] == select_val]

    # Apply range filter
    if range_val and len(range_val) == 2:
        col = fc["range"]["col"]
        df = df[(df[col] >= range_val[0]) & (df[col] <= range_val[1])]

    # Apply multiselect filter
    if multi_val:
        df = df[df[fc["multiselect"]["col"]].isin(multi_val)]

    # Rebuild figures
    figures = []
    for f in config["figures"]:
        figures.append(create_figure(df, f["visu_type"], f["kwargs"], title=f["title"]))

    # Rebuild table
    table = create_table(df, "data-table")

    return figures, table


# ---------------------------------------------------------------------------
# Callback: AI Component Creator — Generate
# ---------------------------------------------------------------------------
@callback(
    Output("ai-plot-preview", "children"),
    Output("ai-plot-suggestion-store", "data"),
    Output("ai-plot-add-btn", "disabled"),
    Input("ai-plot-generate-btn", "n_clicks"),
    State("ai-plot-input", "value"),
    State("dataset-selector", "value"),
    prevent_initial_call=True,
)
def generate_ai_plot(n_clicks, user_prompt, dataset_key):
    if not user_prompt:
        return dmc.Alert("Please describe a visualization.", color="yellow"), None, True

    try:
        df = load_dataset(dataset_key)
        metadata = get_column_metadata(df)
        suggestion = llm_client.suggest_plot(user_prompt, metadata)

        # Render preview
        fig = create_figure(df, suggestion.visu_type, suggestion.dict_kwargs, title=suggestion.title, graph_id="ai-preview-graph")

        preview = dmc.Stack(
            [
                fig,
                dmc.Alert(
                    children=dmc.Stack(
                        [
                            dmc.Text(f"Type: {suggestion.visu_type}", size="sm"),
                            dmc.Text(f"Config: {json.dumps(suggestion.dict_kwargs)}", size="sm", ff="monospace"),
                            dmc.Text(suggestion.explanation, size="sm", c="dimmed"),
                        ],
                        gap=4,
                    ),
                    title="Generated Configuration",
                    color="violet",
                    variant="light",
                ),
            ],
            gap="sm",
        )

        return preview, suggestion.model_dump(), False

    except Exception as e:
        logging.error("AI plot generation failed: %s", traceback.format_exc())
        return dmc.Alert(f"Error: {e}", color="red", title="Generation Failed"), None, True


# ---------------------------------------------------------------------------
# Callback: AI Component Creator — Add to Dashboard
# ---------------------------------------------------------------------------
@callback(
    Output("ai-generated-figures", "children"),
    Input("ai-plot-add-btn", "n_clicks"),
    State("ai-plot-suggestion-store", "data"),
    State("dataset-selector", "value"),
    State("ai-generated-figures", "children"),
    prevent_initial_call=True,
)
def add_ai_plot_to_dashboard(n_clicks, suggestion_data, dataset_key, existing_children):
    if not suggestion_data:
        return no_update

    df = load_dataset(dataset_key)
    fig = create_figure(
        df,
        suggestion_data["visu_type"],
        suggestion_data["dict_kwargs"],
        title=f"[AI] {suggestion_data['title']}",
        graph_id=f"ai-added-{n_clicks}",
    )

    children = existing_children or []
    if not isinstance(children, list):
        children = [children]
    children.append(fig)

    return children


# ---------------------------------------------------------------------------
# Callback: AI Data Analyst — Analyze
# ---------------------------------------------------------------------------
@callback(
    Output("ai-analysis-results", "children"),
    Input("ai-analysis-btn", "n_clicks"),
    State("ai-analysis-input", "value"),
    State("dataset-selector", "value"),
    prevent_initial_call=True,
)
def run_ai_analysis(n_clicks, user_prompt, dataset_key):
    if not user_prompt:
        return dmc.Alert("Please ask a question about the data.", color="yellow")

    try:
        df = load_dataset(dataset_key)
        metadata = get_column_metadata(df)
        sample_rows = df.head(5).to_string(index=False)

        result = llm_client.analyze_data(user_prompt, metadata, sample_rows)

        # Build results display
        findings_list = dmc.List(
            [dmc.ListItem(f) for f in result.key_findings],
            size="sm",
            spacing="xs",
        )

        results = dmc.Stack(
            [
                dmc.Alert(
                    children=dmc.Text(result.summary, size="sm"),
                    title="Summary",
                    color="teal",
                    variant="light",
                ),
                dmc.Paper(
                    dmc.Stack(
                        [
                            dmc.Text("Key Findings", size="md", fw=600),
                            findings_list,
                        ],
                        gap="xs",
                    ),
                    withBorder=True,
                    p="md",
                    radius="md",
                ),
            ],
            gap="sm",
        )

        # Add suggested plots if any
        if result.suggested_plots:
            plot_previews = []
            for i, sp in enumerate(result.suggested_plots[:3]):  # max 3
                try:
                    plot_previews.append(
                        create_figure(df, sp.visu_type, sp.dict_kwargs, title=sp.title, graph_id=f"analysis-plot-{i}")
                    )
                except Exception:
                    pass

            if plot_previews:
                results.children.append(
                    dmc.Stack(
                        [dmc.Text("Suggested Visualizations", size="md", fw=600)]
                        + plot_previews,
                        gap="sm",
                    )
                )

        return results

    except Exception as e:
        logging.error("AI analysis failed: %s", traceback.format_exc())
        return dmc.Alert(f"Error: {e}", color="red", title="Analysis Failed")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=8050)
