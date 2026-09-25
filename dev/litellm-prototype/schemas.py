"""Pydantic output schemas for structured LLM responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PlotSuggestion(BaseModel):
    """Structured output for plot generation — maps directly to Plotly Express kwargs."""

    visu_type: Literal["scatter", "bar", "line", "histogram", "box", "violin", "heatmap"] = Field(
        description="Plotly Express function name"
    )
    dict_kwargs: dict[str, Any] = Field(
        description="Keyword arguments passed to the Plotly Express function (e.g. x, y, color, size, facet_col)"
    )
    title: str = Field(description="Human-readable chart title")
    explanation: str = Field(description="Brief explanation of why this visualization was suggested")

    @model_validator(mode="after")
    def check_dict_kwargs_not_empty(self) -> "PlotSuggestion":
        if not self.dict_kwargs:
            raise ValueError(
                "dict_kwargs must not be empty — it must contain at least 'x' "
                "(and 'y' for scatter/line/bar) with valid column names."
            )
        needs_x = self.visu_type not in ("histogram",)
        if needs_x and "x" not in self.dict_kwargs:
            raise ValueError(
                f"dict_kwargs for '{self.visu_type}' must contain at least 'x' with a valid column name."
            )
        return self


class CardSuggestion(BaseModel):
    """Structured output for metric card generation."""

    column: str = Field(description="DataFrame column to aggregate")
    aggregation: Literal["count", "sum", "mean", "median", "min", "max", "std"] = Field(
        description="Aggregation function to apply"
    )
    title: str = Field(description="Card display title")
    icon: str = Field(description="Material Design Icon name (e.g. mdi:chart-line)")


class AnalysisResult(BaseModel):
    """Structured output for data analysis (legacy — kept for reference)."""

    summary: str = Field(description="Markdown-formatted summary of the analysis")
    key_findings: list[str] = Field(description="List of key findings as bullet points")
    suggested_plots: list[PlotSuggestion] | None = Field(
        default=None, description="Optional list of suggested visualizations"
    )


class ExecutionStep(BaseModel):
    """A single step in the LangChain pandas agent's execution trace."""

    thought: str = Field(description="The agent's reasoning for this step")
    code: str = Field(description="The pandas code that was executed")
    output: str = Field(description="The result of executing the code")


class AnalysisAgentResult(BaseModel):
    """Result from the LangChain pandas agent — answer + full execution trace."""

    answer: str = Field(description="Final natural-language answer from the agent")
    steps: list[ExecutionStep] = Field(description="Ordered list of code execution steps")
