"""Validate AI-emitted YAML for a single dashboard component.

The LLM emits YAML in the same grammar `depictio-cli dashboard import`
consumes. We wrap the single-component block in a minimal dashboard
envelope and run it through `DashboardDataLite.from_yaml(...)` — the
same offline validator the CLI uses. That guarantees the AI cannot
produce anything the CLI would reject, and gives us per-field error
messages we can feed back to the LLM on retry without re-deriving any
constraint logic.

`dump_single` is the symmetric helper for the "modify existing
component" flow: we serialize the current `StoredMetadata` to YAML and
include it in the prompt as the state the user is asking to revise.
"""

from __future__ import annotations

import textwrap
from typing import Any

import yaml
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite

# Keys that only make sense at the dashboard level (not on a single
# component). Stripped if the LLM accidentally emits them inside a
# component block.
_DASHBOARD_LEVEL_KEYS = frozenset(
    {"title", "subtitle", "dashboard_id", "project_tag", "components"}
)


def _strip_yaml_fences(text: str) -> str:
    """Tolerate ```yaml ... ``` fences if the LLM ignores instructions."""
    s = text.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _parse_component_yaml(yaml_text: str) -> dict[str, Any]:
    """Parse the LLM's YAML output to a single component dict.

    The model is instructed to emit either a bare component mapping or a
    one-item list. Both are accepted so we don't crash on a harmless
    formatting choice.
    """
    cleaned = _strip_yaml_fences(yaml_text)
    try:
        data = yaml.safe_load(cleaned)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}") from e
    if isinstance(data, list):
        if len(data) != 1 or not isinstance(data[0], dict):
            raise ValueError(
                f"Expected a single YAML component block, got a list with {len(data)} items."
            )
        comp = data[0]
    elif isinstance(data, dict):
        # If the model included a full dashboard envelope by mistake,
        # extract the first component so we still succeed.
        if "components" in data and isinstance(data["components"], list):
            comps = data["components"]
            if not comps:
                raise ValueError("YAML envelope had an empty 'components' list.")
            if not isinstance(comps[0], dict):
                raise ValueError("First entry in 'components' was not a mapping.")
            comp = comps[0]
        else:
            comp = data
    else:
        raise ValueError("YAML must contain a mapping or a single-item list.")
    return {k: v for k, v in comp.items() if k not in _DASHBOARD_LEVEL_KEYS}


def validate_single(yaml_text: str) -> dict[str, Any]:
    """Validate a single-component YAML block via the CLI's loader path.

    Returns the validated component dict (model_dump form). Raises
    `ValueError` (from YAML parsing) or `ValidationError` (from Pydantic)
    so callers can format errors uniformly for the retry prompt.
    """
    comp = _parse_component_yaml(yaml_text)
    # Wrap in the smallest valid envelope DashboardDataLite accepts.
    envelope = {"title": "AI", "components": [comp]}
    envelope_yaml = yaml.safe_dump(envelope, sort_keys=False)
    dashboard = DashboardDataLite.from_yaml(envelope_yaml)
    if not dashboard.components:
        raise ValueError("Validation produced no components.")
    first = dashboard.components[0]
    if isinstance(first, dict):
        # Validator domain pass already ran inside from_yaml; if it
        # returned a dict here it means the LiteComponent union fell
        # through without raising. Treat as a hard error so the LLM
        # can't slip past with an unknown shape.
        raise ValueError(
            f"Component validated to an untyped dict (component_type="
            f"{first.get('component_type')!r}). The component_type is "
            "either missing or not one of: figure, card, interactive, "
            "table, image, multiqc, map."
        )
    return first.model_dump(mode="json", exclude_none=True)


def format_validation_error_for_llm(exc: BaseException) -> str:
    """Render a validation failure as a short, actionable message.

    Used as the user-turn observation in the retry prompt — keep it
    compact so the next LLM round doesn't blow its context budget on
    error formatting.
    """
    if isinstance(exc, ValidationError):
        lines: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()) if x not in (0,))
            msg = err.get("msg", "")
            lines.append(f"- {loc or '(root)'}: {msg}")
        return "Pydantic validation failed:\n" + "\n".join(lines)
    return f"{type(exc).__name__}: {exc}"


def dump_single(component: dict[str, Any]) -> str:
    """Serialize one component dict to YAML for prompt context.

    Strips runtime-only fields (ids, layout, *_count) the LLM doesn't
    need to see — those would just bloat the prompt and tempt the model
    to write them back verbatim.
    """
    drop = {
        "wf_id",
        "dc_id",
        "project_id",
        "dc_config",
        "cols_json",
        "last_updated",
        "parent_index",
        "displayed_data_count",
        "total_data_count",
        "was_sampled",
        "filter_applied",
        "index",
        "tag",
        "layout",
        "x",
        "y",
        "w",
        "h",
        "static",
        "resizeHandles",
    }
    cleaned = {k: v for k, v in component.items() if k not in drop and v not in (None, "", [], {})}
    return textwrap.indent(
        yaml.safe_dump(cleaned, sort_keys=False, default_flow_style=False),
        prefix="",
    )
