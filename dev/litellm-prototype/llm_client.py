"""Provider-agnostic LLM client using LiteLLM with in-memory caching."""

from __future__ import annotations

import hashlib
import json
import logging
import os

import litellm
from dotenv import load_dotenv

from schemas import AnalysisResult, PlotSuggestion

load_dotenv()
logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True

# In-memory cache (use Redis in production)
_cache: dict[str, str] = {}


def get_model() -> str:
    return os.getenv("LLM_MODEL", "openrouter/anthropic/claude-sonnet-4-6")


def _cache_key(messages: list[dict], model: str) -> str:
    payload = json.dumps({"messages": messages, "model": model}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def completion(messages: list[dict], response_format: type | None = None) -> str:
    """Call LiteLLM with caching and optional structured output.

    Args:
        messages: Chat messages in OpenAI format.
        response_format: Optional Pydantic model class for structured output.

    Returns:
        Raw string content from the LLM response.
    """
    model = get_model()
    key = _cache_key(messages, model)

    if key in _cache:
        logger.info("Cache hit for %s", key[:12])
        return _cache[key]

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 2048,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    logger.info("Calling %s (response_format=%s)", model, response_format)
    response = litellm.completion(**kwargs)
    content = response.choices[0].message.content

    _cache[key] = content
    return content


def suggest_plot(user_prompt: str, column_metadata: str) -> PlotSuggestion:
    """Ask the LLM to suggest a Plotly Express plot configuration."""
    system_prompt = f"""You are a data visualization expert. Given a dataset description and a user request,
suggest a single Plotly Express plot configuration.

DATASET:
{column_metadata}

Respond with valid JSON matching this exact schema:
{{
    "visu_type": "scatter|bar|line|histogram|box|violin|heatmap",
    "dict_kwargs": {{"x": "column_name", "y": "column_name", ...}},
    "title": "Chart title",
    "explanation": "Why this plot is useful"
}}

IMPORTANT:
- dict_kwargs must only contain valid Plotly Express parameter names (x, y, color, size, facet_col, facet_row, etc.)
- Column names in dict_kwargs MUST match the dataset columns exactly
- Do NOT include the DataFrame as a parameter — only column mappings
- Respond with ONLY the JSON object, no markdown fences or extra text"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = completion(messages, response_format=PlotSuggestion)

    # Parse — litellm may return raw JSON string or already-parsed content
    if isinstance(result, str):
        return PlotSuggestion.model_validate_json(result)
    return PlotSuggestion.model_validate(result)


def analyze_data(user_prompt: str, column_metadata: str, sample_rows: str) -> AnalysisResult:
    """Ask the LLM to analyze the dataset."""
    system_prompt = f"""You are a data analyst. Given a dataset description and sample rows,
answer the user's question with structured analysis.

DATASET:
{column_metadata}

SAMPLE ROWS (first 5):
{sample_rows}

Respond with valid JSON matching this exact schema:
{{
    "summary": "Markdown-formatted summary paragraph",
    "key_findings": ["finding 1", "finding 2", ...],
    "suggested_plots": [
        {{
            "visu_type": "scatter|bar|line|histogram|box|violin|heatmap",
            "dict_kwargs": {{"x": "col", "y": "col", ...}},
            "title": "Chart title",
            "explanation": "Why this plot"
        }}
    ] or null
}}

IMPORTANT:
- key_findings should be 3-6 concise bullet points
- suggested_plots is optional — include only if relevant visualizations would help
- Column names must match the dataset exactly
- Respond with ONLY the JSON object, no markdown fences or extra text"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = completion(messages, response_format=AnalysisResult)

    if isinstance(result, str):
        return AnalysisResult.model_validate_json(result)
    return AnalysisResult.model_validate(result)
