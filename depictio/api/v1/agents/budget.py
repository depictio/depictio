"""The shared budget of one agent-team run.

Every agent of a run draws from one :class:`BudgetLedger`: tool calls, LLM
tokens and, when the provider reports it, cost in USD.

The cost and token pools are split into phases that follow the pipeline:
analysts, skeptic, writers (annotator and questioner), reporter (see
``PHASES``). A phase may spend up to the cumulative share of the phases up to
and including it, so the allowance a finished phase leaves unused rolls
forward to the later ones, and a phase never eats into the shares of the
phases after it. Parallel analysts share the analysts' phase. The reporter's
phase is the last one: a run whose earlier agents spend everything they may
still ends with a report.

Cost is only enforced once known: a provider (or a litellm price map) that
reports no cost leaves ``cost_known`` false, and the token ceiling is the
bound that applies.

The ledger anticipates the next LLM call instead of only noticing a limit
once it is crossed. It remembers the largest cost and token count of the
calls each role has made (a role's calls grow with its conversation, so the
largest is also the latest) and refuses a new turn when what is spent plus
that expectation would pass the caller's limit: the cumulative share of its
phase (every phase but the reporter's when no phase is named, the whole pool
for the reporter or a caller with ``reserve=True``). A role that has not
called yet is expected to cost as much as the largest call of the run. The
final spend therefore normally stays under ``limit_usd``;
one call can still exceed it slightly when it is larger than expected (a
long tool result in its prompt) or when parallel analysts pass the check
together before either is charged.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from depictio.api.v1.configs.logging_init import logger

# Phases of a run, in pipeline order, with their share of the cost and token
# pools. The shares add up to 1; the last phase is the reporter's reserve.
PHASES: tuple[tuple[str, float], ...] = (
    ("analysts", 0.45),
    ("skeptic", 0.25),
    ("writers", 0.15),
    ("reporter", 0.15),
)
ROLE_PHASES: dict[str, str] = {
    "analyst": "analysts",
    "skeptic": "skeptic",
    "annotator": "writers",
    "questioner": "writers",
    "reporter": "reporter",
}
# Tool calls kept for the reporter.
RESERVE_CALLS = 2


def phase_of(role: str) -> str | None:
    """The budget phase a role spends in; None for a role outside the pipeline."""
    return ROLE_PHASES.get(role)


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
    """Run-wide pool of tool calls, tokens and cost, split into phases.

    Callers name their ``phase`` (see ``PHASES``); ``reserve=True`` draws on
    the whole pool (the reporter). A caller naming neither may use every
    phase but the last. Updates take a lock: LLM calls run in worker threads
    and several analysts share the ledger.
    """

    def __init__(
        self,
        *,
        max_tool_calls: int,
        limit_usd: float,
        max_tokens: int,
        reserve_calls: int = RESERVE_CALLS,
        phases: tuple[tuple[str, float], ...] = PHASES,
    ) -> None:
        self.max_tool_calls = max_tool_calls
        self.limit_usd = limit_usd
        self.max_tokens = max_tokens
        self.reserve_calls = min(reserve_calls, max_tool_calls)
        total = sum(share for _, share in phases) or 1.0
        # Cumulative share of the pool each phase may spend up to.
        self._phase_caps: dict[str, float] = {}
        running = 0.0
        for name, share in phases:
            running += share / total
            self._phase_caps[name] = running
        self._last_phase = phases[-1][0] if phases else None
        # A caller naming no phase may use every phase but the last.
        self._default_cap = 1.0 - (phases[-1][1] / total if phases else 0.0)
        self.tool_calls = 0
        self.tokens = 0
        self.spent_usd = 0.0
        self.cost_known = True
        self._priced_calls = 0
        # Largest cost and token count of one call, per role and over the run.
        self._max_cost: dict[str, float] = {}
        self._max_tokens: dict[str, int] = {}
        self._lock = threading.Lock()

    # -- limits ------------------------------------------------------------
    def _cap(self, reserve: bool, phase: str | None) -> float:
        """Share of the pool the caller may have spent by the end of its turns."""
        if reserve:
            return 1.0
        if phase is None:
            return self._default_cap
        return self._phase_caps.get(phase, self._default_cap)

    def _call_limit(self, reserve: bool, phase: str | None = None) -> int:
        if reserve or (phase is not None and phase == self._last_phase):
            return self.max_tool_calls
        return self.max_tool_calls - self.reserve_calls

    def _token_limit(self, reserve: bool, phase: str | None = None) -> float:
        return self.max_tokens * self._cap(reserve, phase)

    def _usd_limit(self, reserve: bool, phase: str | None = None) -> float:
        return self.limit_usd * self._cap(reserve, phase)

    def _spend_exhausted(self, reserve: bool, phase: str | None = None) -> bool:
        if self.tokens >= self._token_limit(reserve, phase):
            return True
        return self._cost_enforced() and self.spent_usd >= self._usd_limit(reserve, phase)

    def _cost_enforced(self) -> bool:
        return self.cost_known and self._priced_calls > 0

    def _expected(self, table: dict[str, Any], role: str | None) -> float:
        if role is not None and role in table:
            return float(table[role])
        return float(max(table.values(), default=0))

    def _turns_fit(
        self,
        reserve: bool,
        role: str | None,
        turns: int,
        phase: str | None = None,
        then: str | None = None,
    ) -> bool:
        """``turns`` calls of ``role`` (plus one of ``then``, if named) fit the caller's cap."""
        if self._spend_exhausted(reserve, phase):
            return False
        if turns <= 0 and then is None:
            return True
        tokens = self.tokens + turns * self._expected(self._max_tokens, role)
        if then is not None:
            tokens += self._expected(self._max_tokens, then)
        if tokens > self._token_limit(reserve, phase):
            return False
        if not self._cost_enforced():
            return True
        cost = self.spent_usd + turns * self._expected(self._max_cost, role)
        if then is not None:
            cost += self._expected(self._max_cost, then)
        return cost <= self._usd_limit(reserve, phase)

    # -- queries -------------------------------------------------------------
    def exhausted(self, *, reserve: bool = False, phase: str | None = None) -> bool:
        """True when this caller may neither call a tool nor start another LLM turn."""
        with self._lock:
            if self._spend_exhausted(reserve, phase):
                return True
            return self.tool_calls >= self._call_limit(reserve, phase)

    def can_think(
        self,
        *,
        reserve: bool = False,
        role: str | None = None,
        turns: int = 1,
        phase: str | None = None,
    ) -> bool:
        """True while ``turns`` more LLM calls of ``role`` are expected to fit (tool calls aside).

        The expectation is the largest call ``role`` made so far (the run's
        largest for a role that has not called yet); nothing is expected
        before the first call. The limit is the cumulative share of ``phase``.
        """
        with self._lock:
            return self._turns_fit(reserve, role, turns, phase)

    def can_force(self, *, role: str | None, then: str | None) -> bool:
        """True when one call of ``role`` still leaves room in the whole pool for one of ``then``.

        For an answer that must be given even past its phase's share (the
        skeptic's verdicts): it may borrow from later phases, but never the
        last call ``then`` (the reporter) needs.
        """
        with self._lock:
            return self._turns_fit(True, role, 1, None, then)

    def expected_cost(self, role: str | None = None) -> float:
        """Cost the next call of ``role`` is expected to have (0.0 while unknown)."""
        with self._lock:
            return self._expected(self._max_cost, role)

    # -- updates -------------------------------------------------------------
    def try_tool_call(self, *, reserve: bool = False, phase: str | None = None) -> bool:
        """Take one tool call from the pool; False when none is left for this caller."""
        with self._lock:
            if self._spend_exhausted(reserve, phase) or self.tool_calls >= self._call_limit(
                reserve, phase
            ):
                return False
            self.tool_calls += 1
            return True

    def record_llm(self, usage: Any, model: str | None, role: str | None = None) -> float | None:
        """Charge one completion's tokens and cost. Returns the cost, or None if unknown.

        ``role`` names who made the call, so the ledger can expect the next one.
        """
        cost = completion_cost_usd(usage, model)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
        key = role or ""
        with self._lock:
            self.tokens += tokens
            self._max_tokens[key] = max(self._max_tokens.get(key, 0), tokens)
            if cost is None:
                self.cost_known = False
            else:
                self.spent_usd += cost
                self._priced_calls += 1
                self._max_cost[key] = max(self._max_cost.get(key, 0.0), cost)
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
