"""Layout for the Feature Explorer module.

DMC 2.0 Paper with sidebar for gene search and metadata sort selector.
Main area: violin plot, heatmap row, rank badges, co-expression table,
external links.

All component IDs are prefixed with ``fe-`` to avoid conflicts
when composed with other modules.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

# ── Column metadata (matches shared_data metadata columns) ──────────────
METADATA_COLS: list[str] = ["condition", "batch", "cell_type"]

COLUMN_LABELS: dict[str, str] = {
    "condition": "Condition",
    "batch": "Batch",
    "cell_type": "Cell Type",
    "sample_id": "Sample ID",
}


def _meta_sort_options() -> list[dict[str, str]]:
    """Metadata column options for the sample sort selector."""
    return [{"value": c, "label": COLUMN_LABELS.get(c, c)} for c in METADATA_COLS]


def _create_sidebar(gene_options: list[dict[str, str]]) -> dmc.ScrollArea:
    """Build sidebar with gene search and controls."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Feature Explorer", order=4),
                dmc.Text("Module v1.0", size="xs", c="dimmed"),
                # ── Gene search ───────────────────────────
                dmc.Divider(label="Gene Search", labelPosition="center"),
                dmc.Select(
                    id="fe-gene-select",
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
                    id="fe-sort-by-meta",
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
        id="fe-coexpression-table",
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


def create_layout(data: dict) -> dmc.Paper:
    """Create the Feature Explorer module layout.

    Args:
        data: The data dict from ``shared_data.load_all_data()``.

    Returns:
        A ``dmc.Paper`` wrapping the complete module UI.
    """
    gene_names = sorted(data["gene_names"])
    gene_options = [{"value": g, "label": g} for g in gene_names]

    return dmc.Paper(
        dmc.Stack(
            [
                # Module layout: sidebar + main area
                dmc.Grid(
                    [
                        # Sidebar column
                        dmc.GridCol(
                            _create_sidebar(gene_options),
                            span=3,
                        ),
                        # Main content column
                        dmc.GridCol(
                            dmc.Stack(
                                [
                                    # ── Violin / strip plot ───────────
                                    dmc.Paper(
                                        dcc.Graph(
                                            id="fe-violin-plot",
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
                                            id="fe-heatmap-row",
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
                                                    "DE Results",
                                                    fw=600,
                                                    size="sm",
                                                    id="fe-de-results-title",
                                                ),
                                                dmc.Group(
                                                    id="fe-rank-badges",
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
                                                    id="fe-external-links",
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
                            ),
                            span=9,
                        ),
                    ],
                    gutter="md",
                ),
            ],
            gap="md",
        ),
        p="md",
        radius="sm",
        withBorder=True,
    )
