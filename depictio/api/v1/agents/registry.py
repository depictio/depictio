"""The agent tool registry: one declaration per tool, one call path for every client.

Tools are plain async functions registered with ``@agent_tool``. MCP and the
in-app agent runner both go through ``invoke()``, so the scope check, rate
limit, input validation, error mapping, output budget and audit row are the
same whoever calls.
"""

from __future__ import annotations

import copy
import importlib
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from pydantic_core import to_jsonable_python
from starlette.exceptions import HTTPException

from depictio.api.v1.agents import audit, ratelimit
from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.envelope import fit_to_budget
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.users import TokenScope

ToolFn = Callable[[ToolContext, Any], Awaitable[Any]]

# Tool modules under ``depictio.api.v1.agents.tools``, imported by
# ``ensure_tools_loaded``. A missing module is skipped.
TOOL_MODULES: tuple[str, ...] = (
    "discovery",
    "data",
    "annotations",
    "reports",
    "dashboards",
    "ingestion",
)


class ToolError(Exception):
    """A refusal or failure the agent should see as a readable message.

    Tools may raise it directly; ``invoke`` also maps ``HTTPException`` and
    validation errors onto it.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class ToolResult(BaseModel):
    """What ``invoke`` returns. ``call_id`` is the audit row's id; findings cite it."""

    ok: bool
    call_id: str
    data: Any | None = None
    error: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class ToolSpec:
    name: str
    scope: TokenScope
    description: str
    input_model: type[BaseModel]
    fn: ToolFn
    writes: bool = False
    max_chars: int | None = None
    evidence: bool = False
    enabled: Callable[[], bool] | None = None

    def is_enabled(self) -> bool:
        if self.enabled is None:
            return True
        try:
            return bool(self.enabled())
        except Exception as exc:
            logger.warning(f"agents: enabled() of tool {self.name} failed: {exc}")
            return False

    def input_schema(self) -> dict[str, Any]:
        """JSON schema of the input model with every ``$ref`` inlined."""
        return inline_refs(self.input_model.model_json_schema())

    def budget(self) -> int:
        return self.max_chars or settings.mcp.max_output_chars


REGISTRY: dict[str, ToolSpec] = {}


def _fn_id(fn: ToolFn) -> tuple[str | None, str | None]:
    # A module reload re-registers the same function; anything else is a clash.
    return getattr(fn, "__module__", None), getattr(fn, "__qualname__", None)


def agent_tool(
    *,
    name: str,
    scope: TokenScope,
    description: str,
    input_model: type[BaseModel],
    writes: bool = False,
    max_chars: int | None = None,
    evidence: bool = False,
    enabled: Callable[[], bool] | None = None,
) -> Callable[[ToolFn], ToolFn]:
    """Register ``async def fn(ctx: ToolContext, args: InputModel)`` as an agent tool.

    The function returns a Pydantic model, a dict, a list or a string; it is
    serialised to JSON and cut to ``max_chars`` (default
    ``settings.mcp.max_output_chars``). Wrap user-authored text with
    ``envelope.untrusted``. ``evidence=True`` marks tools whose results can
    back a finding; ``enabled`` hides the tool when it returns False.
    """

    def decorator(fn: ToolFn) -> ToolFn:
        existing = REGISTRY.get(name)
        if existing is not None and _fn_id(existing.fn) != _fn_id(fn):
            raise ValueError(
                f"Agent tool {name!r} is already registered by {existing.fn.__module__}"
            )
        REGISTRY[name] = ToolSpec(
            name=name,
            scope=scope,
            description=description,
            input_model=input_model,
            fn=fn,
            writes=writes,
            max_chars=max_chars,
            evidence=evidence,
            enabled=enabled,
        )
        return fn

    return decorator


def tools_for(scopes: Iterable[TokenScope]) -> list[ToolSpec]:
    """Enabled tools callable with ``scopes``, sorted by name."""
    allowed = set(scopes)
    return sorted(
        (spec for spec in REGISTRY.values() if spec.scope in allowed and spec.is_enabled()),
        key=lambda spec: spec.name,
    )


def to_litellm_tools(scopes: Iterable[TokenScope]) -> list[dict[str, Any]]:
    """OpenAI-style function declarations, ``$ref``-free (some providers reject refs)."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_schema(),
            },
        }
        for spec in tools_for(scopes)
    ]


def inline_refs(schema: dict[str, Any], *, max_depth: int = 8) -> dict[str, Any]:
    """Resolve local ``#/$defs/...`` references and drop ``$defs``.

    Recursive models are cut at ``max_depth`` with an open object schema.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any, depth: int) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                if depth >= max_depth:
                    return {"type": "object"}
                target = copy.deepcopy(defs.get(ref.split("/")[-1], {}))
                siblings = {k: v for k, v in node.items() if k != "$ref"}
                return resolve({**target, **siblings}, depth + 1)
            return {k: resolve(v, depth) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item, depth) for item in node]
        return node

    return resolve(schema, 0)


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "arguments"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "Invalid arguments: " + "; ".join(parts)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return to_jsonable_python(value, fallback=str)


async def invoke(name: str, ctx: ToolContext, raw_args: dict[str, Any] | None) -> ToolResult:
    """Run one tool call through the shared chain and audit it. Never raises."""
    call_id = uuid4().hex
    args = raw_args or {}
    started = time.perf_counter()
    data: Any = None
    truncated = False
    error: str | None = None

    spec = REGISTRY.get(name)
    try:
        if spec is None or not spec.is_enabled():
            raise ToolError(f"Unknown tool: {name}", status=404)
        if not ctx.has(spec.scope):
            raise ToolError(
                f"Tool {name} needs the '{spec.scope}' scope, which this token does not have",
                status=403,
            )
        if not await ratelimit.allow(ctx.token_id or str(getattr(ctx.user, "id", ""))):
            raise ToolError("Rate limit exceeded; wait a minute before calling more tools", 429)
        try:
            parsed = spec.input_model.model_validate(args)
        except ValidationError as exc:
            raise ToolError(_validation_message(exc), status=422) from exc
        try:
            output = await spec.fn(ctx, parsed)
        except HTTPException as exc:
            raise ToolError(f"{exc.detail}", status=exc.status_code) from exc
        data, truncated = fit_to_budget(_jsonable(output), spec.budget())
    except ToolError as exc:
        error = exc.message
    except Exception as exc:
        logger.exception(f"agents: tool {name} failed (call {call_id}): {exc}")
        error = "Internal error while running the tool"

    await audit.record_call(
        ctx,
        name,
        args,
        error is None,
        error,
        (time.perf_counter() - started) * 1000,
        truncated,
        call_id=call_id,
    )
    if error is not None:
        return ToolResult(ok=False, call_id=call_id, error=error)
    return ToolResult(ok=True, call_id=call_id, data=data, truncated=truncated)


_tools_loaded = False


def ensure_tools_loaded() -> None:
    """Import every tool module once. A module that fails to import is skipped.

    Tools a failing module registered before the failure are removed again,
    so a half-imported module never exposes a partial tool set.
    """
    global _tools_loaded
    if _tools_loaded:
        return
    for module_name in TOOL_MODULES:
        qualified = f"depictio.api.v1.agents.tools.{module_name}"
        before = set(REGISTRY)
        try:
            importlib.import_module(qualified)
        except ModuleNotFoundError as exc:
            for added in set(REGISTRY) - before:
                REGISTRY.pop(added, None)
            if exc.name == qualified:
                logger.debug(f"agents: tool module {module_name} not present, skipped")
            else:
                logger.warning(f"agents: tool module {module_name} skipped, missing {exc.name}")
        except Exception as exc:
            for added in set(REGISTRY) - before:
                REGISTRY.pop(added, None)
            logger.warning(f"agents: tool module {module_name} failed to load: {exc}")
    _tools_loaded = True
