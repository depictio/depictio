"""Persistence for whole-dashboard generation runs (`ai_generations` collection).

Same policy as `ai_analyses`: a run is a derived artifact addressed by its
own id, never written into the dashboard document. The dashboard only
carries the small `ai_generation` stamp that points back at `run_id`, so
a draft can be traced to the plan, the per-component outcomes and the
budget that produced it after the stream is gone.

The run is saved at start, after the plan, after every component and in
the generator's `finally`, so a cancelled or crashed generation is
inspectable afterwards instead of vanished.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from depictio.api.v1.endpoints.ai_endpoints.schemas import BudgetSpent

# "planned" is a run that stopped after the plan on purpose (`plan_only`):
# it spent tokens and produced a plan, but no draft, so calling it
# "complete" would have the history promise a dashboard that is not there.
GenerationStatus = Literal["running", "planned", "complete", "failed", "cancelled"]


class GenerationRun(BaseModel):
    """The persisted record of one dashboard generation.

    `plan` is the validated plan as a plain dict (the plan model lives in
    `dashboard_plan.py` and is not needed to read a record back);
    `components` holds one dict per planned component in the shape of
    `GeneratedComponentEvent`, in plan order; `yaml` is the persisted draft
    once it exists. `dashboard_id` stays None until the draft is saved.
    """

    id: str
    project_id: str
    dashboard_id: str | None = None
    prompt: str = ""
    model: str
    status: GenerationStatus = "running"
    plan: dict[str, Any] | None = None
    components: list[dict[str, Any]] = Field(default_factory=list)
    yaml: str = ""
    budget_spent: BudgetSpent = Field(default_factory=BudgetSpent)
    warnings: list[str] = Field(default_factory=list)
    created_at: str


def _collection():
    """Resolved lazily so tests can monkeypatch depictio.api.v1.db."""
    from depictio.api.v1.db import ai_generations_collection

    return ai_generations_collection


def _now_iso() -> str:
    """Naive UTC ISO timestamp, the API's wire convention (no offset suffix)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def new_run(project_id: str, prompt: str, model: str) -> GenerationRun:
    return GenerationRun(
        id=uuid.uuid4().hex,
        project_id=project_id,
        prompt=prompt,
        model=model,
        status="running",
        created_at=_now_iso(),
    )


def save(run: GenerationRun) -> None:
    """Upsert the run; called at start, after the plan, per component and at the end.

    Persisting the running state (not only the final one) is what makes a
    cancelled or crashed run inspectable afterwards instead of vanished.
    """
    doc = run.model_dump(mode="json")
    _collection().replace_one({"id": run.id}, doc, upsert=True)


def get(run_id: str) -> GenerationRun | None:
    doc = _collection().find_one({"id": run_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return GenerationRun.model_validate(doc)


def list_for_project(project_id: str, limit: int = 20) -> list[GenerationRun]:
    docs = _collection().find({"project_id": project_id}).sort("created_at", -1).limit(limit)
    out: list[GenerationRun] = []
    for doc in docs:
        doc.pop("_id", None)
        try:
            out.append(GenerationRun.model_validate(doc))
        except ValidationError:  # pragma: no cover, corrupt legacy doc
            continue
    return out
