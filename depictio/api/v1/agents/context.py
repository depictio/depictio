"""Who is calling an agent tool, and with what rights."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from depictio.models.models.users import TokenScope, UserBeanie


@dataclass(frozen=True)
class ToolContext:
    """The caller of one tool invocation.

    ``scopes`` is already effective (``read`` included, ``None`` expanded).
    ``run_id`` groups the writes of one agent run, so per-run caps apply;
    callers that do not supply one get a fresh id per context.
    """

    user: UserBeanie
    scopes: frozenset[TokenScope]
    agent_name: str = "mcp-client"
    agent_model: str | None = None
    run_id: str = field(default_factory=lambda: uuid4().hex)
    token_id: str | None = None

    def has(self, scope: TokenScope) -> bool:
        return scope in self.scopes

    @property
    def rate_limit_key(self) -> str:
        """Tools and resources share one rate-limit bucket per token (else per user)."""
        return self.token_id or str(getattr(self.user, "id", ""))
