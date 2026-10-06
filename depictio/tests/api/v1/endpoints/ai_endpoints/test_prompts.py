"""Guardrail: every YAML example embedded in the prompt sheets must pass
the same validator the endpoint applies to LLM output.

If the component grammar drifts (a field renamed, a new required key), this
test fails before any user sees the LLM emit stale YAML that can never
validate.
"""

from __future__ import annotations

import re

import pytest

from depictio.api.v1.endpoints.ai_endpoints import component_yaml
from depictio.api.v1.endpoints.ai_endpoints.prompts import _YAML_EXAMPLES

# `<column>`-style placeholders → plausible concrete values. Substitution
# keyed on hint words so type-sensitive fields stay valid.
_PLACEHOLDER = re.compile(r"<[^>]+>")


def _fill(match: re.Match[str]) -> str:
    token = match.group(0)
    if "workflow_tag" in token:
        return "wf"
    if "data_collection_tag" in token:
        return "dc"
    return "colx"


@pytest.mark.parametrize("component_type", sorted(_YAML_EXAMPLES))
def test_prompt_yaml_example_validates(component_type: str) -> None:
    concrete = _PLACEHOLDER.sub(_fill, _YAML_EXAMPLES[component_type])
    parsed = component_yaml.validate_single(concrete)
    assert parsed["component_type"] == component_type
