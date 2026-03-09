"""AI assistant panels — Component Creator + Data Analyst."""

from __future__ import annotations

import re

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from schemas import AnalysisAgentResult


def _highlight_answer(text: str, columns: list[str] | None = None) -> list:
    """Parse answer text and return Dash components with highlighted numbers and column names.

    - Numbers/percentages → bold teal
    - Column names → monospace violet badge
    - Rest → plain text
    """
    # Build regex: match column names (longest first) OR numbers with optional %/,/.
    patterns = []
    col_set = set()
    if columns:
        # Sort by length descending so longer names match first
        sorted_cols = sorted(columns, key=len, reverse=True)
        col_patterns = [re.escape(c) for c in sorted_cols]
        col_set = set(columns)
        patterns.append(f"({'|'.join(col_patterns)})")
    # Numbers: integers, decimals, percentages, with optional comma separators
    patterns.append(r"(\d[\d,]*\.?\d*%?)")

    if not patterns:
        return [text]

    combined = "|".join(patterns)
    parts = re.split(f"({combined})", text)

    result = []
    for part in parts:
        if not part:
            continue
        if part in col_set:
            result.append(
                dmc.Badge(part, variant="light", color="violet", size="sm", radius="sm",
                          style={"fontFamily": "monospace", "verticalAlign": "middle"})
            )
        elif re.fullmatch(r"\d[\d,]*\.?\d*%?", part):
            result.append(dmc.Text(part, span=True, fw=700, c="teal", ff="monospace"))
        else:
            result.append(part)
    return result


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


def _classify_step(step) -> str:
    """Classify a step as 'success', 'error', or 'info' based on its output."""
    output_lower = step.output.lower()
    if any(kw in output_lower for kw in ("error", "traceback", "exception", "invalid")):
        return "error"
    if any(kw in output_lower for kw in ("warning", "deprecat")):
        return "warning"
    return "success"


_STEP_BADGE = {
    "success": {"color": "teal", "icon": "mdi:check-circle"},
    "error": {"color": "red", "icon": "mdi:alert-circle"},
    "warning": {"color": "yellow", "icon": "mdi:alert"},
}


def render_execution_trace(
    result: AnalysisAgentResult,
    columns: list[str] | None = None,
) -> dmc.Stack:
    """Render the agent's answer + collapsible execution trace with highlighting.

    Args:
        result: The agent result with answer and execution steps.
        columns: Optional list of DataFrame column names for highlighting in the answer.
    """
    # --- Final answer with highlighted numbers and column names ---
    highlighted_answer = _highlight_answer(result.answer, columns)

    answer_section = dmc.Alert(
        children=dmc.Text(highlighted_answer, size="sm"),
        title="Answer",
        color="teal",
        variant="light",
        icon=DashIconify(icon="mdi:lightbulb-on", width=20),
    )

    # --- Execution trace with step classification and filtering ---
    if result.steps:
        # Classify steps
        step_classes = [_classify_step(step) for step in result.steps]
        n_success = step_classes.count("success")
        n_error = step_classes.count("error")
        n_warning = step_classes.count("warning")

        # Summary badges
        summary_badges = [
            dmc.Badge(f"{len(result.steps)} steps", variant="light", color="gray", size="sm"),
        ]
        if n_success:
            summary_badges.append(
                dmc.Badge(f"{n_success} passed", variant="light", color="teal", size="sm",
                          leftSection=DashIconify(icon="mdi:check-circle", width=14))
            )
        if n_error:
            summary_badges.append(
                dmc.Badge(f"{n_error} errors", variant="light", color="red", size="sm",
                          leftSection=DashIconify(icon="mdi:alert-circle", width=14))
            )
        if n_warning:
            summary_badges.append(
                dmc.Badge(f"{n_warning} warnings", variant="light", color="yellow", size="sm",
                          leftSection=DashIconify(icon="mdi:alert", width=14))
            )

        # Filter chips (stored as data attributes, filtered via CSS)
        filter_chips = dmc.ChipGroup(
            [
                dmc.Chip("All", value="all", variant="outline", size="xs"),
                dmc.Chip("Code Only", value="code", variant="outline", size="xs", color="violet"),
                dmc.Chip("Errors", value="errors", variant="outline", size="xs", color="red"),
            ],
            id="analysis-step-filter",
            value="all",
        )

        # Build accordion items with status badges
        accordion_items = []
        for i, (step, cls) in enumerate(zip(result.steps, step_classes), 1):
            badge_cfg = _STEP_BADGE[cls]

            # Thought section — highlight column names if available
            thought_content = _highlight_answer(step.thought, columns) if columns else [step.thought]

            # Output section — highlight numbers
            output_highlighted = _highlight_answer(step.output, columns) if columns else [step.output]

            item_content = dmc.Stack(
                [
                    # Thought
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:thought-bubble", width=16, color="dimmed"),
                            dmc.Text("Thought", size="xs", fw=600, c="dimmed"),
                        ],
                        gap=4,
                    ),
                    dmc.Blockquote(
                        dmc.Text(thought_content, size="sm", c="dimmed"),
                        color="gray",
                        p="xs",
                        style={"fontSize": "0.85rem"},
                    ),
                    # Code
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:code-braces", width=16, color="violet"),
                            dmc.Text("Code", size="xs", fw=600, c="dimmed"),
                        ],
                        gap=4,
                    ),
                    dmc.Code(step.code, block=True, color="violet"),
                    # Output
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:console", width=16, color=badge_cfg["color"]),
                            dmc.Text("Output", size="xs", fw=600, c="dimmed"),
                        ],
                        gap=4,
                    ),
                    dmc.Code(
                        step.output if cls == "error" else None,
                        block=True,
                        color="red" if cls == "error" else None,
                    )
                    if cls == "error"
                    else dmc.Paper(
                        dmc.Text(output_highlighted, size="sm", ff="monospace"),
                        p="xs",
                        radius="sm",
                        bg="gray.0",
                    ),
                ],
                gap=4,
            )

            # Step label with status badge
            step_label = dmc.Group(
                [
                    dmc.Badge(
                        f"Step {i}",
                        variant="filled",
                        color=badge_cfg["color"],
                        size="sm",
                        leftSection=DashIconify(icon=badge_cfg["icon"], width=14),
                    ),
                    dmc.Text(
                        step.code[:60] + ("..." if len(step.code) > 60 else ""),
                        size="sm",
                        ff="monospace",
                        truncate="end",
                    ),
                ],
                gap="xs",
            )

            accordion_items.append(
                dmc.AccordionItem(
                    [
                        dmc.AccordionControl(step_label),
                        dmc.AccordionPanel(item_content),
                    ],
                    value=f"step-{i}",
                    **{"data-step-status": cls},
                )
            )

        trace_section = dmc.Paper(
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:code-json", width=20),
                            dmc.Text("Execution Trace", size="md", fw=600),
                            *summary_badges,
                        ],
                        gap="xs",
                    ),
                    filter_chips,
                    dmc.Accordion(
                        accordion_items,
                        id="analysis-steps-accordion",
                        variant="separated",
                    ),
                ],
                gap="xs",
            ),
            withBorder=True,
            p="md",
            radius="md",
        )
    else:
        trace_section = dmc.Text("No execution steps recorded.", size="sm", c="dimmed")

    return dmc.Stack([answer_section, trace_section], gap="sm")


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
                    "Ask questions about your data — the AI writes and runs real pandas code, "
                    "then shows you every step.",
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
