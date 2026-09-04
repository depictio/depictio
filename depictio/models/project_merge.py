"""Merge helpers for project documents written by two surfaces at once.

A project is edited from two places. The CLI round-trips a whole
``project.yaml`` through ``PUT /projects/update``; the browser appends
workflows straight onto the stored document (see
``datacollections_endpoints/utils.py``, which wraps every uploaded data
collection in its own synthetic workflow and ``$push``es it).

Because the CLI sends the *entire* document, a plain ``$set`` makes the last
writer win: everything added from the browser is absent from the CLI's payload
and is therefore deleted. ``registration_time`` and ``is_public`` were already
carved out of that ``$set`` for the same reason; workflows are the third case,
and the only one that loses user data.

The rule here is deliberately conservative: **what the payload does not mention
is kept.** Omission is how the CLI describes "not mine", not how it describes
"delete this". Removal has its own explicit endpoints, and silently dropping a
data collection because a YAML file on someone's laptop no longer lists it is
exactly the failure this module exists to prevent.
"""


def _identity(entry: dict) -> str | None:
    """Stable identity for a stored or incoming sub-document.

    ``MongoModel.mongo()`` rewrites ``id`` to ``_id`` recursively, so both
    sides of the merge are keyed the same way. Ids are compared as strings
    because one side arrives as ``ObjectId`` and the other may already be
    serialized.
    """
    raw = entry.get("_id") or entry.get("id")
    return str(raw) if raw else None


def _merge_by_identity(stored: list[dict], incoming: list[dict]) -> list[dict]:
    """``incoming``, then any ``stored`` entry whose id it never mentioned.

    Incoming entries win on conflict: the CLI is authoritative for what it
    knows about. Order follows the payload, so a CLI-driven reordering still
    takes effect, with preserved entries appended in their stored order.
    """
    incoming_ids = {ident for entry in incoming if (ident := _identity(entry))}
    preserved = [
        entry for entry in stored if (ident := _identity(entry)) and ident not in incoming_ids
    ]
    return [*incoming, *preserved]


def merge_project_workflows(
    stored_workflows: list[dict] | None,
    incoming_workflows: list[dict] | None,
) -> list[dict]:
    """Workflow list to persist, keeping workflows the payload omits.

    Also merges one level deeper: for a workflow present on both sides, a data
    collection stored against it but missing from the payload is kept. Browser
    uploads currently always create their own workflow, so that inner merge is
    defensive rather than load-bearing today, but it is what makes the rule
    ("what the payload does not mention is kept") true at both levels.
    """
    stored = stored_workflows or []
    # Copied, so merging a workflow's data collections never mutates the payload.
    incoming = [dict(workflow) for workflow in (incoming_workflows or [])]

    stored_by_id = {ident: wf for wf in stored if (ident := _identity(wf))}
    for workflow in incoming:
        counterpart = stored_by_id.get(_identity(workflow) or "")
        if counterpart is None:
            continue
        workflow["data_collections"] = _merge_by_identity(
            counterpart.get("data_collections") or [],
            workflow.get("data_collections") or [],
        )

    return _merge_by_identity(stored, incoming)


def merge_project_data_collections(
    stored_data_collections: list[dict] | None,
    incoming_data_collections: list[dict] | None,
) -> list[dict]:
    """Top-level data collection list to persist, keeping the ones omitted.

    Basic projects hold data collections directly on the project rather than
    under a workflow. Nothing writes here from the browser today, but the same
    rule applies for the same reason.
    """
    return _merge_by_identity(stored_data_collections or [], incoming_data_collections or [])
