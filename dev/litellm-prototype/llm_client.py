"""Provider-agnostic LLM client using LiteLLM with in-memory caching.

Uses LangChain's pandas agent for data analysis — the LLM writes and
executes real pandas code, with full execution trace for explainability.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import litellm
import pandas as pd
from dotenv import load_dotenv
from langchain_community.chat_models import ChatLiteLLM
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent

from schemas import AnalysisAgentResult, ExecutionStep, PlotSuggestion

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
- dict_kwargs MUST NOT be empty — always include at least "x" (and "y" for scatter/line/bar)
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


# ---------------------------------------------------------------------------
# Analysis cache — same question + same data + same model → same result
# ---------------------------------------------------------------------------
_analysis_cache: dict[str, AnalysisAgentResult] = {}


def _analysis_cache_key(prompt: str, df: pd.DataFrame) -> str:
    """Deterministic cache key from question + data content + model."""
    df_hash = hashlib.sha256(
        pd.util.hash_pandas_object(df).values.tobytes()
    ).hexdigest()[:16]
    return hashlib.sha256(
        f"{prompt}:{df_hash}:{get_model()}".encode()
    ).hexdigest()


def analyze_data(user_prompt: str, df: pd.DataFrame) -> AnalysisAgentResult:
    """Run LangChain pandas agent — the LLM writes + executes real pandas code.

    Returns the final answer plus a full execution trace (thought → code → output)
    for every step, enabling both explainability (UI accordion) and reproducibility
    (cached by question + data hash + model).
    """
    # Check cache first
    cache_key = _analysis_cache_key(user_prompt, df)
    if cache_key in _analysis_cache:
        cached = _analysis_cache[cache_key]
        logger.info("═══ Analysis Cache HIT ═══  key=%s  steps=%d", cache_key[:12], len(cached.steps))
        return cached

    logger.info("═══ analyze_data() — LangChain pandas agent ═══")
    logger.info("Question: %s", user_prompt)
    logger.info("DataFrame: %d rows x %d cols  columns=%s", len(df), len(df.columns), list(df.columns))

    t0 = time.perf_counter()

    # Create LangChain LLM backed by LiteLLM (provider-agnostic)
    llm = ChatLiteLLM(model=get_model(), temperature=0)

    # Create pandas agent — it gets a Python REPL with `df` in scope
    agent = create_pandas_dataframe_agent(
        llm,
        df,
        agent_type="zero-shot-react-description",
        verbose=True,  # prints full ReAct chain to terminal
        return_intermediate_steps=True,
        allow_dangerous_code=True,  # required — we control the data
        handle_parsing_errors=True,  # recover when LLM skips Action:/Action Input: format
        max_iterations=10,
    )

    result = agent.invoke({"input": user_prompt})
    elapsed = time.perf_counter() - t0

    # Extract execution trace from intermediate steps
    steps = []
    for action, observation in result.get("intermediate_steps", []):
        # action is an AgentAction with .tool_input and .log
        # When handle_parsing_errors kicks in, tool_input may be the raw
        # unparseable text — still useful to show the user what happened.
        tool_input = getattr(action, "tool_input", "")
        if isinstance(tool_input, str):
            code = tool_input
        elif isinstance(tool_input, dict):
            code = tool_input.get("query", str(tool_input))
        else:
            code = str(tool_input)

        thought = getattr(action, "log", "").strip()
        steps.append(ExecutionStep(
            thought=thought,
            code=code,
            output=str(observation).strip(),
        ))

    agent_result = AnalysisAgentResult(
        answer=result["output"],
        steps=steps,
    )

    # Log summary
    logger.info("═══ Agent complete (%.1fs) — %d steps ═══", elapsed, len(steps))
    for i, step in enumerate(steps, 1):
        logger.info("─── Step %d ───", i)
        logger.info("  Code: %s", step.code)
        logger.info("  Output: %s", step.output[:200] + ("..." if len(step.output) > 200 else ""))
    logger.info("─── Final Answer ───")
    logger.info("  %s", agent_result.answer[:500])

    # Cache for reproducibility
    _analysis_cache[cache_key] = agent_result

    return agent_result
