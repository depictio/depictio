"""Layout for the Enrichment Explorer module.

Sidebar controls (contrast selector, source filter, top-N slider) and main area
with enrichment table, running ES plot, dot plot, and leading edge heatmap.

All component IDs are prefixed with ``ee-`` to avoid conflicts with other modules.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from dash_iconify import DashIconify


def _get_contrasts(data: dict) -> list[str]:
    """Extract available contrast names from enrichment data."""
    return sorted(data["enrichment_df"]["contrast"].unique().tolist())


def _contrast_options(data: dict) -> list[dict[str, str]]:
    return [{"value": c, "label": c.replace("_", " ")} for c in _get_contrasts(data)]


def _compute_summary_stats(data: dict, default_contrast: str | None) -> dict:
    """Compute summary statistics for badges."""
    enrich_df = data["enrichment_df"]
    total_pathways = enrich_df["pathway_name"].nunique()

    if default_contrast:
        contrast_df = enrich_df[enrich_df["contrast"] == default_contrast]
        sig_pathways = int((contrast_df["padj"] < 0.05).sum())
        top_nes = (
            contrast_df.loc[contrast_df["NES"].abs().idxmax(), "NES"]
            if len(contrast_df) > 0
            else 0.0
        )
    else:
        sig_pathways = 0
        top_nes = 0.0

    return {
        "total_pathways": total_pathways,
        "sig_pathways": sig_pathways,
        "top_nes": top_nes,
    }


def _create_sidebar(data: dict) -> dmc.ScrollArea:
    """Build sidebar with all controls."""
    contrasts = _get_contrasts(data)
    default_contrast = contrasts[0] if contrasts else None
    stats = _compute_summary_stats(data, default_contrast)

    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Enrichment Explorer", order=4),
                dmc.Text("Module v1.0", size="xs", c="dimmed"),
                # ── Summary badges ─────────────────────────
                dmc.Group(
                    [
                        dmc.Badge(
                            f"{stats['total_pathways']} pathways",
                            variant="light",
                            size="sm",
                            id="ee-badge-total-pathways",
                        ),
                        dmc.Badge(
                            id="ee-badge-sig-pathways",
                            variant="light",
                            color="red",
                            size="sm",
                            children=f"{stats['sig_pathways']} significant",
                        ),
                        dmc.Badge(
                            id="ee-badge-active-contrast",
                            variant="light",
                            color="blue",
                            size="sm",
                            children=default_contrast or "No contrast",
                        ),
                        dmc.Badge(
                            id="ee-badge-top-nes",
                            variant="light",
                            color="grape",
                            size="sm",
                            children=f"Top NES: {stats['top_nes']:.2f}",
                        ),
                    ],
                    gap="xs",
                ),
                # ── Contrast selector ─────────────────────
                dmc.Divider(label="Contrast", labelPosition="center"),
                dmc.Select(
                    id="ee-contrast-select",
                    data=_contrast_options(data),
                    value=default_contrast,
                    label="DE Contrast",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:compare-arrows", width=14),
                ),
                # ── Pathway source filter ─────────────────
                dmc.Divider(label="Pathway Source", labelPosition="center"),
                dmc.CheckboxGroup(
                    id="ee-source-filter",
                    label="Filter by source",
                    value=["GO_BP", "KEGG", "Reactome"],
                    children=dmc.Stack(
                        [
                            dmc.Checkbox(label="GO Biological Process", value="GO_BP"),
                            dmc.Checkbox(label="KEGG", value="KEGG"),
                            dmc.Checkbox(label="Reactome", value="Reactome"),
                        ],
                        gap="xs",
                    ),
                ),
                # ── Top N slider ──────────────────────────
                dmc.Divider(label="Dot Plot", labelPosition="center"),
                dmc.Text("Top N pathways", size="xs", c="dimmed"),
                dmc.Slider(
                    id="ee-top-n-slider",
                    min=5,
                    max=30,
                    value=15,
                    step=1,
                    marks=[
                        {"value": 5, "label": "5"},
                        {"value": 15, "label": "15"},
                        {"value": 30, "label": "30"},
                    ],
                    size="sm",
                ),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_enrichment_grid() -> dag.AgGrid:
    """Enrichment results AG Grid table."""
    return dag.AgGrid(
        id="ee-enrichment-table",
        columnDefs=[
            {"field": "pathway_name", "headerName": "Pathway", "minWidth": 250, "flex": 2},
            {
                "field": "NES",
                "headerName": "NES",
                "type": "numericColumn",
                "valueFormatter": {"function": "d3.format('.3f')(params.value)"},
                "flex": 1,
            },
            {
                "field": "padj",
                "headerName": "p-adj",
                "type": "numericColumn",
                "valueFormatter": {"function": "d3.format('.2e')(params.value)"},
                "flex": 1,
            },
            {
                "field": "leading_edge_size",
                "headerName": "LE Size",
                "type": "numericColumn",
                "flex": 1,
            },
            {
                "field": "gene_set_size",
                "headerName": "Set Size",
                "type": "numericColumn",
                "flex": 1,
            },
            {"field": "source", "headerName": "Source", "flex": 1},
        ],
        rowData=[],
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 10,
            "rowSelection": {"mode": "singleRow"},
            "enableCellTextSelection": True,
            "animateRows": False,
        },
        defaultColDef={
            "sortable": True,
            "resizable": True,
            "filter": True,
        },
        style={"height": "300px"},
        className="ag-theme-alpine",
    )


def create_layout(data: dict) -> dmc.Paper:
    """Create the Enrichment Explorer module layout.

    Parameters
    ----------
    data : dict
        Data dict from ``shared_data.load_all_data()``.

    Returns
    -------
    dmc.Paper
        The module wrapped in a Paper component (no AppShell).
    """
    return dmc.Paper(
        dmc.Grid(
            [
                # Sidebar column
                dmc.GridCol(
                    _create_sidebar(data),
                    span=3,
                ),
                # Main content column
                dmc.GridCol(
                    dmc.Stack(
                        [
                            # Enrichment table
                            dmc.Paper(
                                _create_enrichment_grid(),
                                p="xs",
                                radius="sm",
                                withBorder=True,
                            ),
                            # Running ES plot
                            dmc.Paper(
                                dcc.Graph(
                                    id="ee-running-es-plot",
                                    config={
                                        "displayModeBar": "hover",
                                        "responsive": True,
                                    },
                                    style={"height": "350px"},
                                ),
                                p="xs",
                                radius="sm",
                                withBorder=True,
                            ),
                            # Bottom row: dot plot + leading edge heatmap
                            dmc.Grid(
                                [
                                    dmc.GridCol(
                                        dmc.Paper(
                                            dcc.Graph(
                                                id="ee-dot-plot",
                                                config={
                                                    "displayModeBar": "hover",
                                                    "responsive": True,
                                                },
                                                style={"height": "500px"},
                                            ),
                                            p="xs",
                                            radius="sm",
                                            withBorder=True,
                                        ),
                                        span=6,
                                    ),
                                    dmc.GridCol(
                                        dmc.Paper(
                                            dcc.Graph(
                                                id="ee-le-heatmap",
                                                config={
                                                    "displayModeBar": "hover",
                                                    "responsive": True,
                                                },
                                                style={"height": "500px"},
                                            ),
                                            p="xs",
                                            radius="sm",
                                            withBorder=True,
                                        ),
                                        span=6,
                                    ),
                                ],
                                gutter="md",
                            ),
                        ],
                        gap="md",
                    ),
                    span=9,
                ),
            ],
            gutter="md",
        ),
        p="md",
        radius="sm",
        withBorder=True,
    )
