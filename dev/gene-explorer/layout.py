"""Layout for the single-gene deep-dive explorer prototype.

DMC 2.0 AppShell with sidebar for gene search and metadata sort selector.
Main area: violin plot, heatmap row, rank badges, co-expression table,
external links.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify
from data import COLUMN_LABELS, METADATA_COLS


def _meta_sort_options() -> list[dict[str, str]]:
    """Metadata column options for the sample sort selector."""
    return [{"value": c, "label": COLUMN_LABELS.get(c, c)} for c in METADATA_COLS]


def _create_navbar_content(gene_options: list[dict[str, str]]) -> dmc.ScrollArea:
    """Build sidebar with gene search and controls."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Gene Explorer", order=4),
                dmc.Text("Prototype v0.1", size="xs", c="dimmed"),
                # ── Gene search ───────────────────────────
                dmc.Divider(label="Gene Search", labelPosition="center"),
                dmc.Select(
                    id="gene-select",
                    data=gene_options,
                    value=gene_options[0]["value"] if gene_options else None,
                    label="Select gene",
                    searchable=True,
                    placeholder="Type to search...",
                    size="sm",
                    leftSection=DashIconify(icon="mdi:dna", width=16),
                    nothingFoundMessage="No gene found",
                ),
                # ── Heatmap sorting ───────────────────────
                dmc.Divider(label="Heatmap Options", labelPosition="center"),
                dmc.Select(
                    id="sort-by-meta",
                    data=_meta_sort_options(),
                    value="condition",
                    label="Sort samples by",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:sort", width=14),
                ),
                # ── Info ──────────────────────────────────
                dmc.Divider(label="Info", labelPosition="center"),
                dmc.Text(
                    "Select a gene to see its expression across conditions, "
                    "DE rank, co-expressed genes, and external links.",
                    size="xs",
                    c="dimmed",
                ),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_coexpression_grid() -> dag.AgGrid:
    """Co-expression AG Grid table."""
    return dag.AgGrid(
        id="coexpression-table",
        columnDefs=[
            {
                "field": "gene_name",
                "headerName": "Gene",
                "filter": "agTextColumnFilter",
                "minWidth": 120,
            },
            {
                "field": "pearson_r",
                "headerName": "Pearson r",
                "filter": "agNumberColumnFilter",
                "valueFormatter": {"function": "d3.format('.4f')(params.value)"},
            },
            {
                "field": "pvalue",
                "headerName": "p-value",
                "filter": "agNumberColumnFilter",
                "valueFormatter": {"function": "d3.format('.2e')(params.value)"},
            },
        ],
        rowData=[],
        dashGridOptions={
            "pagination": False,
            "enableCellTextSelection": True,
            "animateRows": False,
            "domLayout": "autoHeight",
        },
        defaultColDef={
            "flex": 1,
            "minWidth": 100,
            "sortable": True,
            "resizable": True,
        },
        style={"width": "100%"},
        className="ag-theme-alpine",
    )


def create_layout(gene_options: list[dict[str, str]]) -> dmc.MantineProvider:
    """Create the full application layout.

    Args:
        gene_options: List of {"value": name, "label": name} for gene Select.
    """
    return dmc.MantineProvider(
        dmc.AppShell(
            [
                dmc.AppShellNavbar(_create_navbar_content(gene_options)),
                dmc.AppShellMain(
                    dmc.Container(
                        dmc.Stack(
                            [
                                # ── Violin / strip plot ───────────
                                dmc.Paper(
                                    dcc.Graph(
                                        id="violin-plot",
                                        config={
                                            "displayModeBar": "hover",
                                            "responsive": True,
                                        },
                                        style={"height": "400px"},
                                    ),
                                    p="xs",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # ── Heatmap row ──────────────────
                                dmc.Paper(
                                    dcc.Graph(
                                        id="heatmap-row",
                                        config={
                                            "displayModeBar": False,
                                            "responsive": True,
                                        },
                                        style={"height": "160px"},
                                    ),
                                    p="xs",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # ── DE rank badges ───────────────
                                dmc.Paper(
                                    dmc.Stack(
                                        [
                                            dmc.Text(
                                                "DE Results (Treatment_A vs Control)",
                                                fw=600,
                                                size="sm",
                                            ),
                                            dmc.Group(
                                                id="rank-badges",
                                                children=[
                                                    dmc.Text(
                                                        "Select a gene",
                                                        size="sm",
                                                        c="dimmed",
                                                    )
                                                ],
                                                gap="sm",
                                                wrap="wrap",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    p="sm",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # ── Co-expression table ──────────
                                dmc.Paper(
                                    dmc.Stack(
                                        [
                                            dmc.Text(
                                                "Top 10 Co-expressed Genes",
                                                fw=600,
                                                size="sm",
                                            ),
                                            _create_coexpression_grid(),
                                        ],
                                        gap="xs",
                                    ),
                                    p="sm",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # ── External links ───────────────
                                dmc.Paper(
                                    dmc.Stack(
                                        [
                                            dmc.Text(
                                                "External Links",
                                                fw=600,
                                                size="sm",
                                            ),
                                            dmc.Group(
                                                id="external-links",
                                                children=[
                                                    dmc.Text(
                                                        "Select a gene",
                                                        size="sm",
                                                        c="dimmed",
                                                    )
                                                ],
                                                gap="md",
                                                wrap="wrap",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                    p="sm",
                                    radius="sm",
                                    withBorder=True,
                                ),
                            ],
                            gap="md",
                            p="md",
                        ),
                        fluid=True,
                    ),
                ),
            ],
            navbar={"width": 320, "breakpoint": "sm"},
            padding="md",
        ),
        forceColorScheme="light",
    )
