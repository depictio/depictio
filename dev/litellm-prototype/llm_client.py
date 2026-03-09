"""Provider-agnostic LLM client using LiteLLM with in-memory caching."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import litellm
from dotenv import load_dotenv

from schemas import AnalysisResult, PlotSuggestion

load_dotenv()
logger = logging.getLogger(__name__)

# Suppress litellm's verbose internal logging
litellm.suppress_debug_info = True

# In-memory cache (use Redis in production)
_cache: dict[str, str] = {}


def get_model() -> str:
    return os.getenv("LLM_MODEL", "openrouter/anthropic/claude-sonnet-4-6")


def _cache_key(messages: list[dict], model: str) -> str:
    payload = json.dumps({"messages": messages, "model": model}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _log_messages(messages: list[dict]) -> None:
    """Log each message role and content at DEBUG level."""
    for msg in messages:
        role = msg["role"].upper()
        logger.debug("─── %s Prompt ───", role)
        logger.debug("%s", msg["content"])


def completion(messages: list[dict], response_format: type | None = None) -> str:
    """Call LiteLLM with caching and optional structured output."""
    model = get_model()
    key = _cache_key(messages, model)
    fmt_name = response_format.__name__ if response_format else "None"

    if key in _cache:
        logger.info("═══ Cache HIT ═══  key=%s format=%s", key[:12], fmt_name)
        logger.debug("─── Cached Response ───")
        logger.debug("%s", _cache[key])
        return _cache[key]

    logger.info("═══ LLM Request ═══")
    logger.info("Model: %s | temperature: 0 | format: %s", model, fmt_name)
    _log_messages(messages)

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 2048,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    t0 = time.perf_counter()
    response = litellm.completion(**kwargs)
    elapsed = time.perf_counter() - t0
    content = response.choices[0].message.content

    # Token usage
    usage = getattr(response, "usage", None)
    if usage:
        logger.info(
            "═══ LLM Response (%.1fs) ═══  Tokens: %d prompt + %d completion = %d total",
            elapsed,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
        )
    else:
        logger.info("═══ LLM Response (%.1fs) ═══  (no token usage reported)", elapsed)

    logger.debug("─── Raw Response ───")
    logger.debug("%s", content)

    _cache[key] = content
    return content


def suggest_plot(user_prompt: str, column_metadata: str) -> PlotSuggestion:
    """Ask the LLM to suggest a Plotly Express plot configuration."""
    logger.info("═══ suggest_plot() ═══")
    logger.debug("─── Column Metadata ───")
    logger.debug("%s", column_metadata)

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

    if isinstance(result, str):
        parsed = PlotSuggestion.model_validate_json(result)
    else:
        parsed = PlotSuggestion.model_validate(result)

    logger.info(
        "═══ Parsed: PlotSuggestion ═══  type=%s | kwargs=%s | title=%s",
        parsed.visu_type,
        parsed.dict_kwargs,
        parsed.title,
    )
    return parsed


def analyze_data(user_prompt: str, column_metadata: str, data_profile: str) -> AnalysisResult:
    """Ask the LLM to analyze the dataset using pre-computed statistics.

    The data_profile contains real pandas operations: describe(), corr(),
    value_counts(), groupby().agg(), sample rows — so the LLM reasons
    about actual computed numbers.
    """
    logger.info("═══ analyze_data() ═══")
    logger.debug("─── Column Metadata ───")
    logger.debug("%s", column_metadata)
    logger.debug("─── Data Profile (%d chars) ───", len(data_profile))
    logger.debug("%s", data_profile)

    system_prompt = f"""You are a data analyst. You have been given a dataset description and
PRE-COMPUTED STATISTICS from real pandas operations (describe, correlations, value counts,
group-by aggregations, and sample rows). Use these actual numbers to answer the user's question.

DATASET SCHEMA:
{column_metadata}

PRE-COMPUTED DATA PROFILE:
{data_profile}

Base your analysis on the actual statistics above. Reference specific numbers, correlations,
and group differences. Do not guess — use the computed values.

Respond with valid JSON matching this exact schema:
{{
    "summary": "Markdown-formatted summary paragraph referencing actual statistics",
    "key_findings": ["finding 1 with actual numbers", "finding 2 with actual numbers", ...],
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
- key_findings should be 3-6 concise bullet points with actual numbers from the profile
- suggested_plots is optional — include only if relevant visualizations would help
- Column names must match the dataset exactly
- Respond with ONLY the JSON object, no markdown fences or extra text"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = completion(messages, response_format=AnalysisResult)

    if isinstance(result, str):
        parsed = AnalysisResult.model_validate_json(result)
    else:
        parsed = AnalysisResult.model_validate(result)

    n_plots = len(parsed.suggested_plots) if parsed.suggested_plots else 0
    logger.info(
        "═══ Parsed: AnalysisResult ═══  summary=%d chars | findings=%d | suggested_plots=%d",
        len(parsed.summary),
        len(parsed.key_findings),
        n_plots,
    )
    logger.info("─── Key Findings ───")
    for i, finding in enumerate(parsed.key_findings, 1):
        logger.info("  %d. %s", i, finding)

    return parsed
