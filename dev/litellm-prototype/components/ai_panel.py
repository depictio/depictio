"""AI assistant panels — Component Creator + Data Analyst."""

from __future__ import annotations

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify


def create_ai_component_creator() -> dmc.Paper:
    """Panel for AI-assisted plot/component creation."""
    return dmc.Paper(
        dmc.Stack(
            [
                dmc.Group(
                    [
                        DashIconify(icon="mdi:creation", width=24, color="violet"),
                        dmc.Text("AI Component Creator", size="lg", fw=600),
                    ],
                    gap="xs",
                ),
                dmc.Text(
                    "Describe a visualization in natural language and the AI will generate a Plotly chart.",
                    size="sm",
                    c="dimmed",
                ),
                dmc.Textarea(
                    id="ai-plot-input",
                    placeholder='e.g. "scatter plot of sepal length vs width, colored by variety"',
                    minRows=2,
                    maxRows=4,
                    w="100%",
                ),
                dmc.Group(
                    [
                        dmc.Button(
                            "Generate",
                            id="ai-plot-generate-btn",
                            leftSection=DashIconify(icon="mdi:auto-fix"),
                            variant="gradient",
                            gradient={"from": "violet", "to": "grape"},
                        ),
                        dmc.Button(
                            "Add to Dashboard",
                            id="ai-plot-add-btn",
                            leftSection=DashIconify(icon="mdi:plus-circle"),
                            variant="outline",
                            color="violet",
                            disabled=True,
                        ),
                    ],
                    gap="sm",
                ),
                # Loading + preview area
                dcc.Loading(
                    id="ai-plot-loading",
                    type="circle",
                    children=html.Div(id="ai-plot-preview", style={"minHeight": "50px"}),
                ),
                # Store the suggestion JSON for "Add to Dashboard"
                dcc.Store(id="ai-plot-suggestion-store"),
            ],
            gap="md",
        ),
        withBorder=True,
        radius="md",
        p="lg",
        shadow="sm",
    )


def create_ai_data_analyst() -> dmc.Paper:
    """Panel for AI-assisted data analysis."""
    return dmc.Paper(
        dmc.Stack(
            [
                dmc.Group(
                    [
                        DashIconify(icon="mdi:brain", width=24, color="teal"),
                        dmc.Text("AI Data Analyst", size="lg", fw=600),
                    ],
                    gap="xs",
                ),
                dmc.Text(
                    "Ask questions about your data and get structured analysis with key findings.",
                    size="sm",
                    c="dimmed",
                ),
                dmc.Textarea(
                    id="ai-analysis-input",
                    placeholder='e.g. "What are the key differences between iris varieties?"',
                    minRows=2,
                    maxRows=4,
                    w="100%",
                ),
                dmc.Button(
                    "Analyze",
                    id="ai-analysis-btn",
                    leftSection=DashIconify(icon="mdi:magnify"),
                    variant="gradient",
                    gradient={"from": "teal", "to": "cyan"},
                ),
                # Loading + results area
                dcc.Loading(
                    id="ai-analysis-loading",
                    type="circle",
                    children=html.Div(id="ai-analysis-results", style={"minHeight": "50px"}),
                ),
            ],
            gap="md",
        ),
        withBorder=True,
        radius="md",
        p="lg",
        shadow="sm",
    )
