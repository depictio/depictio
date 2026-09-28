"""The shared budget of one agent-team run.

Every agent of a run draws from one :class:`BudgetLedger`: tool calls, LLM
tokens and, when the provider reports it, cost in USD. A slice of the pool is
held back for the reporter, so a run whose analysts spend everything still
ends with a report.

Cost is only enforced once known: a provider (or a litellm price map) that
reports no cost leaves ``cost_known`` false, and the token ceiling is the
bound that applies.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from depictio.api.v1.configs.logging_init import logger

# Share of the pool kept for the reporter.
RESERVE_CALLS = 2
RESERVE_FRACTION = 0.15


def completion_cost_usd(usage: Any, model: str | None) -> float | None:
    """Cost of one completion: the provider's figure, else litellm's price map, else None.

    ``litellm.cost_per_token`` answers 0.0 for a model it does not know, which
    is read as "unknown" rather than "free".
    """
    reported = getattr(usage, "cost_usd", None)
    if reported is not None:
        return float(reported)
    if not model:
        return None
    try:
        import litellm

        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )
    except Exception as exc:  # noqa: BLE001, a model outside the price map
        logger.debug(f"agents: no price for model {model}: {exc}")
        return None
    total = float(prompt_cost or 0) + float(completion_cost or 0)
    return total or None


@dataclass(frozen=True)
class BudgetSnapshot:
    tool_calls: int
    max_tool_calls: int
    tokens: int
    max_tokens: int
    spent_usd: float
    limit_usd: float
    cost_known: bool

    def event(self) -> dict[str, Any]:
        """Payload of the ``budget`` SSE event."""
        return {
            "spent_usd": round(self.spent_usd, 6),
            "limit_usd": self.limit_usd,
            "tool_calls": self.tool_calls,
            "max_tool_calls": self.max_tool_calls,
            "tokens": self.tokens,
            "cost_known": self.cost_known,
        }


class BudgetLedger:
    """Run-wide pool of tool calls, tokens and cost, with a reporter reserve.

    Callers pass ``reserve=True`` to draw on the reserved slice (the reporter
    only). Updates take a lock: LLM calls run in worker threads and several
    analysts share the ledger.
    """

    def __init__(
        self,
        *,
        max_tool_calls: int,
        limit_usd: float,
        max_tokens: int,
        reserve_calls: int = RESERVE_CALLS,
        reserve_fraction: float = RESERVE_FRACTION,
    ) -> None:
        self.max_tool_calls = max_tool_calls
        self.limit_usd = limit_usd
        self.max_tokens = max_tokens
        self.reserve_calls = min(reserve_calls, max_tool_calls)
        self.reserve_fraction = reserve_fraction
        self.tool_calls = 0
        self.tokens = 0
        self.spent_usd = 0.0
        self.cost_known = True
        self._priced_calls = 0
        self._lock = threading.Lock()

    # -- limits ------------------------------------------------------------
    def _call_limit(self, reserve: bool) -> int:
        return self.max_tool_calls if reserve else self.max_tool_calls - self.reserve_calls

    def _token_limit(self, reserve: bool) -> float:
        return self.max_tokens if reserve else self.max_tokens * (1 - self.reserve_fraction)

    def _usd_limit(self, reserve: bool) -> float:
        return self.limit_usd if reserve else self.limit_usd * (1 - self.reserve_fraction)

    def _spend_exhausted(self, reserve: bool) -> bool:
        if self.tokens >= self._token_limit(reserve):
            return True
        return self._cost_enforced() and self.spent_usd >= self._usd_limit(reserve)

    def _cost_enforced(self) -> bool:
        return self.cost_known and self._priced_calls > 0

    # -- queries -------------------------------------------------------------
    def exhausted(self, *, reserve: bool = False) -> bool:
        """True when this caller may neither call a tool nor start another LLM turn."""
        with self._lock:
            if self._spend_exhausted(reserve):
                return True
            return self.tool_calls >= self._call_limit(reserve)

    def can_think(self, *, reserve: bool = False) -> bool:
        """True while another LLM turn fits (tool calls aside)."""
        with self._lock:
            return not self._spend_exhausted(reserve)

    # -- updates -------------------------------------------------------------
    def try_tool_call(self, *, reserve: bool = False) -> bool:
        """Take one tool call from the pool; False when none is left for this caller."""
        with self._lock:
            if self._spend_exhausted(reserve) or self.tool_calls >= self._call_limit(reserve):
                return False
            self.tool_calls += 1
            return True

    def record_llm(self, usage: Any, model: str | None) -> float | None:
        """Charge one completion's tokens and cost. Returns the cost, or None if unknown."""
        cost = completion_cost_usd(usage, model)
        with self._lock:
            self.tokens += int(getattr(usage, "total_tokens", 0) or 0)
            if cost is None:
                self.cost_known = False
            else:
                self.spent_usd += cost
                self._priced_calls += 1
        return cost

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            return BudgetSnapshot(
                tool_calls=self.tool_calls,
                max_tool_calls=self.max_tool_calls,
                tokens=self.tokens,
                max_tokens=self.max_tokens,
                spent_usd=self.spent_usd,
                limit_usd=self.limit_usd,
                cost_known=self.cost_known and self._priced_calls > 0,
            )
