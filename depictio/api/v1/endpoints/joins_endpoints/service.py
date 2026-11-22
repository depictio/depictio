"""Joins made in the web UI: preview, create, list, delete, and rebuild.

A join combines two table data collections of a project into a third, an
ordinary table collection (``joined_<name>``) that every component can read.
Its sources are left as they are. The definition is the one ``project.yaml``
holds under ``joins:`` (``JoinDefinition``), stored on the project, and the
table is written by the CLI's own helpers (``validate_join_definition``,
``execute_join``, ``persist_joined_table``), run in-process with the caller's
usable token, as the upload routes run the scan and process helpers.

What differs from the CLI is how the result reaches Mongo: the CLI goes back
into the API over HTTP, through owner-only routes, while these functions have
checked the caller's role already and write it directly (``_server_hooks``).

A join follows its sources: every write of a table through the web UI
(Manage data, Add columns, cell edits, a restored version) ends in
``rebuild_dependent_joins``, which re-runs the joins reading it, and the joins
reading those. A rebuild that changes no row writes nothing; one that does
writes a new Delta version, which "What's new" and "Before | Now" read like an
append. Synchronous throughout: routes dispatch via ``asyncio.to_thread``.
"""

from __future__ import annotations

from typing import Any

import polars as pl
from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, deltatables_collection, projects_collection
from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _cli_config_with_token,
    _editable_project_and_token,
    _usable_user_token,
)
from depictio.api.v1.endpoints.projects_endpoints.publish_lock import is_project_locked
from depictio.api.v1.permissions import get_user_group_ids, has_permission
from depictio.models.models.joins import JoinDefinition, JoinType

#: Columns the ingest and the join add for their own bookkeeping: never offered
#: as a key, never shown in a preview.
BOOKKEEPING_COLUMNS = frozenset({"aggregation_time", "depictio_run_id", "join_timestamp"})
#: Rows of the joined table shown in a preview.
SAMPLE_ROWS = 10
#: Unmatched key values named in a preview, per side.
UNMATCHED_SAMPLE = 5
#: Tag prefix ``persist_joined_table`` gives the joined collection.
JOINED_TAG_PREFIX = "joined_"
#: Name a preview runs under, whatever the reader has typed so far.
PREVIEW_NAME = "preview"
#: Longest join name (``JoinDefinition.name``).
MAX_NAME_LENGTH = 100
#: Most columns a suggested key combines.
MAX_SUGGESTED_KEY_COLUMNS = 3


class JoinRequest(BaseModel):
    """A join as the web UI sends it: collections by id, the rest as in YAML."""

    #: Checked by ``name_problem`` (at most ``MAX_NAME_LENGTH``), so a preview
    #: says why a name is refused rather than failing validation; the bound
    #: only caps the payload.
    name: str = Field(default="", max_length=1000)
    left_dc_id: str
    right_dc_id: str
    #: Empty asks the server for its suggestion (preview only).
    on_columns: list[str] = Field(default_factory=list)
    how: JoinType = JoinType.LEFT
    description: str | None = Field(default=None, max_length=500)


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


# ----------------------------------------------------------------------------
# Project, collections, references
# ----------------------------------------------------------------------------


def _project_model(doc: dict):
    """The ``Project`` the CLI helpers take, built as the ingestion task builds it."""
    from depictio.models.models.projects import Project, ProjectBeanie

    return Project.model_validate(ProjectBeanie.from_mongo(doc).model_dump())


def _editable(project_id: str, current_user) -> tuple[dict, dict]:
    """``(project document, usable token)``: owners and editors, project not locked.

    The upload routes' checks: 400 / 404 / 403 / 409 (published) / 401 (no token),
    except that a project the user cannot even view answers 404, as listing its
    joins does: whether it exists is not theirs to learn.
    """
    _viewable(project_id, current_user)
    project_oid, token = _editable_project_and_token(project_id, current_user)
    doc = projects_collection.find_one({"_id": project_oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    return doc, token


def _viewable(project_id: str, current_user) -> tuple[dict, list]:
    """``(project document, the user's group ids)``; 404 unless the user may view it."""
    try:
        project_oid = ObjectId(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid project_id: {exc}")
    doc = projects_collection.find_one({"_id": project_oid})
    user_id = getattr(current_user, "id", None)
    groups = get_user_group_ids(user_id) if user_id else []
    if not doc or not has_permission(doc, current_user, "viewer", groups):
        raise HTTPException(status_code=404, detail="Project not found.")
    return doc, groups


def _iter_dcs(doc: dict):
    for workflow in doc.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            yield workflow, dc


def _dc_id(dc: dict) -> str:
    return str(dc.get("_id") or dc.get("id"))


def _locate(doc: dict, dc_id: str, side: str) -> tuple[dict, dict]:
    for workflow, dc in _iter_dcs(doc):
        if _dc_id(dc) == dc_id:
            return workflow, dc
    raise _refuse(404, "unknown_collection", f"The {side} table is not in this project.")


def _require_table(dc: dict, side: str) -> None:
    dc_type = str((dc.get("config") or {}).get("type") or "").lower()
    if dc_type != "table":
        raise _refuse(
            422,
            "not_a_table",
            f"The {side} collection '{dc.get('data_collection_tag')}' is not a table: "
            "only tables can be joined.",
        )


def _reference(doc: dict, workflow: dict, dc: dict) -> str:
    """How a ``JoinDefinition`` names this collection.

    The bare tag when it names one collection only, else ``workflow.tag``.
    ``find_data_collection_by_tag`` reads a dot as that scope, so a tag that
    holds one is always scoped, and a workflow name holding one cannot be.
    """
    tag = str(dc.get("data_collection_tag") or "")
    same_tag = sum(1 for _, other in _iter_dcs(doc) if other.get("data_collection_tag") == tag)
    if same_tag == 1 and "." not in tag:
        return tag
    workflow_name = str(workflow.get("name") or "")
    if workflow_name and "." not in workflow_name:
        return f"{workflow_name}.{tag}"
    raise _refuse(
        422,
        "ambiguous_collection",
        f"'{tag}' cannot be told apart from another collection of this project: rename it first.",
    )


def _resolve_ids(project, join_def: JoinDefinition) -> tuple[str | None, str | None]:
    """The ids of the two collections a stored join reads (None when gone)."""
    from depictio.cli.cli.utils.joins import find_data_collection_by_tag

    left, _ = find_data_collection_by_tag(project, join_def.left_dc, join_def.workflow_name)
    right, _ = find_data_collection_by_tag(project, join_def.right_dc, join_def.workflow_name)
    return (
        str(left.id) if left is not None and left.id else None,
        str(right.id) if right is not None and right.id else None,
    )


def joins_reading(doc: dict, dc_id: str) -> list[str]:
    """Names of the project's joins that read collection ``dc_id``."""
    if not doc.get("joins"):
        return []
    project = _project_model(doc)
    return [j.name for j in project.joins if dc_id in _resolve_ids(project, j)]


def join_producing(doc: dict, dc_id: str) -> str | None:
    """The name of the join whose result is collection ``dc_id``, if any."""
    for join in doc.get("joins") or []:
        if str(join.get("result_dc_id") or "") == dc_id:
            return join.get("name")
    return None


# ----------------------------------------------------------------------------
# Reading the sources
# ----------------------------------------------------------------------------


def _read_source(cli_config, dc: dict, side: str) -> pl.DataFrame:
    from depictio.cli.cli.utils.deltatables import read_delta_table
    from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

    location = f"s3://{cli_config.s3_storage.bucket}/{_dc_id(dc)}"
    result = read_delta_table(
        location, turn_S3_config_into_polars_storage_options(cli_config.s3_storage)
    )
    frame = result.get("data")
    if result.get("result") != "success" or not isinstance(frame, pl.DataFrame):
        raise _refuse(
            409,
            "no_data",
            f"The {side} table '{dc.get('data_collection_tag')}' holds no data yet.",
        )
    return frame


def _visible(frame: pl.DataFrame) -> list[str]:
    return [c for c in frame.columns if c not in BOOKKEEPING_COLUMNS]


def _key_tuples(frame: pl.DataFrame, on: list[str]) -> list[tuple | None]:
    """Each row's key as text, None when a part is missing.

    ``execute_join`` casts key columns of different types to text, and a null
    never matches, so this is what decides whether two rows meet.
    """
    columns = [frame[c].cast(pl.String, strict=False).to_list() for c in on]
    keys: list[tuple | None] = []
    for parts in zip(*columns, strict=True):
        keys.append(None if any(p is None for p in parts) else tuple(parts))
    return keys


def _shown(key: tuple) -> str:
    return " / ".join(str(part) for part in key)


def _as_text(frame: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """The key columns as text, rows with a missing part left out (they match nothing)."""
    return frame.select([pl.col(c).cast(pl.String, strict=False) for c in columns]).drop_nulls()


def _matched_keys(left: pl.DataFrame, right: pl.DataFrame, columns: list[str]) -> int:
    """How many distinct key values the two tables have in common."""
    return (
        _as_text(left, columns)
        .unique()
        .join(_as_text(right, columns).unique(), on=columns, how="inner")
        .height
    )


def _is_unique(frame: pl.DataFrame, columns: list[str]) -> bool:
    keys = frame.select(columns)
    return keys.height == keys.unique().height


def suggest_on_columns(left: pl.DataFrame, right: pl.DataFrame, shared: list[str]) -> list[str]:
    """The shared column(s) most likely to be the key.

    A key naming one row on each side comes first: a single column when one is
    unique in both tables, else the smallest combination of shared columns that
    is (``sample`` + ``lane`` when a sample has several lanes), so no row is
    repeated. Among those, most values in common, then the left table's order.
    Failing that, the single column with most values in common, a column unique
    in more tables first. Nothing when no shared column has a value in common.
    """
    singles = []
    for position, column in enumerate(shared):
        matched = _matched_keys(left, right, [column])
        if matched:
            unique = _is_unique(left, [column]) + _is_unique(right, [column])
            singles.append(((unique, matched, -position), [column]))
    if not singles:
        return []
    best_single = max(singles, key=lambda item: item[0])
    if best_single[0][0] == 2:
        return best_single[1]
    from itertools import combinations

    for size in range(2, min(MAX_SUGGESTED_KEY_COLUMNS, len(shared)) + 1):
        candidates = []
        for combo in combinations(range(len(shared)), size):
            columns = [shared[i] for i in combo]
            if not (_is_unique(left, columns) and _is_unique(right, columns)):
                continue
            matched = _matched_keys(left, right, columns)
            if matched:
                candidates.append(((matched, [-i for i in combo]), columns))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
    return best_single[1]


# ----------------------------------------------------------------------------
# Definition
# ----------------------------------------------------------------------------


def _definition(
    doc: dict, request: JoinRequest, on_columns: list[str], *, name: str | None = None
) -> tuple[JoinDefinition, dict, dict]:
    """The ``JoinDefinition`` of ``request``, with the two collection documents."""
    if request.left_dc_id == request.right_dc_id:
        raise _refuse(422, "same_collection", "Pick two different tables.")
    left_wf, left_dc = _locate(doc, request.left_dc_id, "left")
    right_wf, right_dc = _locate(doc, request.right_dc_id, "right")
    _require_table(left_dc, "left")
    _require_table(right_dc, "right")
    try:
        join_def = JoinDefinition(
            name=name or request.name or "preview",
            left_dc=_reference(doc, left_wf, left_dc),
            right_dc=_reference(doc, right_wf, right_dc),
            on_columns=on_columns,
            how=request.how,
            description=request.description or None,
            # The joined collection sits next to the left table.
            workflow_name=left_wf.get("name"),
            # A table added from a file has a run id of its own (`<tag>-single-file-scan`),
            # so joining on it would match nothing.
            match_run_ids=False,
            persist=True,
        )
    except ValidationError as exc:
        message = "; ".join(err.get("msg", "") for err in exc.errors()) or str(exc)
        raise _refuse(422, "invalid_join", message.removeprefix("Value error, "))
    return join_def, left_dc, right_dc


def name_format_problem(name: str) -> str | None:
    """Why ``name`` cannot name any join, or None."""
    if not name:
        return "Give the join a name."
    if len(name) > MAX_NAME_LENGTH:
        return f"A join name has at most {MAX_NAME_LENGTH} characters."
    try:
        JoinDefinition.validate_name(name)
    except ValueError:
        if any(ch.isspace() for ch in name):
            return "A join name cannot contain spaces: use _ or - instead."
        return "Use only letters, digits, _ and - in a join name."
    return None


def name_problem(doc: dict, name: str) -> str | None:
    """Why ``name`` cannot name a new join of this project, or None."""
    problem = name_format_problem(name)
    if problem:
        return problem
    if any(j.get("name") == name for j in doc.get("joins") or []):
        return f"This project already has a join named '{name}'."
    tag = f"{JOINED_TAG_PREFIX}{name}"
    if any(dc.get("data_collection_tag") == tag for _, dc in _iter_dcs(doc)):
        return f"This project already has a table named '{tag}'."
    return None


def _check_columns(on_columns: list[str], shared: list[str], left_dc: dict, right_dc: dict) -> None:
    if not shared:
        raise _refuse(
            422,
            "no_shared_column",
            f"'{left_dc.get('data_collection_tag')}' and '{right_dc.get('data_collection_tag')}' "
            "have no column with the same name to join on.",
        )
    missing = [c for c in on_columns if c not in shared]
    if missing:
        raise _refuse(
            422,
            "invalid_columns",
            f"Column(s) {', '.join(missing)} are not in both tables.",
        )


def _validate(join_def: JoinDefinition, project, cli_config) -> None:
    from depictio.cli.cli.utils.joins import validate_join_definition

    validation = validate_join_definition(join_def, project, cli_config)
    if not validation.is_valid:
        raise _refuse(422, "invalid_join", "; ".join(validation.errors))
    if not (validation.left_dc_processed and validation.right_dc_processed):
        raise _refuse(409, "no_data", "; ".join(validation.warnings) or "A table holds no data.")


def _store_form(join_def: JoinDefinition) -> dict:
    """A join as the project document stores it (ObjectIds, no unset id)."""
    stored = join_def.model_dump()
    if stored.get("id") is None:
        stored.pop("id", None)
    if stored.get("result_dc_id"):
        stored["result_dc_id"] = ObjectId(str(stored["result_dc_id"]))
    return stored


def _client_form(stored: dict) -> dict:
    """A stored join as JSON: ids as text."""
    out = {}
    for key, value in stored.items():
        if key == "_id":
            key = "id"
        out[key] = str(value) if isinstance(value, ObjectId) else value
    return out


# ----------------------------------------------------------------------------
# Preview
# ----------------------------------------------------------------------------


def preview_join(project_id: str, request: JoinRequest, current_user) -> dict[str, Any]:
    """What creating ``request`` would give, written nowhere.

    ``on_columns`` empty means "suggest": the shared column with most values in
    common. Answers the counts of both sides and of the result, how many rows of
    each side find no partner (with a few of their keys), and the first rows.
    """
    from depictio.api.v1.endpoints.deltatables_endpoints.routes import _json_safe
    from depictio.cli.cli.utils.joins import execute_join

    doc, token = _editable(project_id, current_user)
    cli_config = _cli_config_with_token(current_user, token)
    _, left_dc, right_dc = _definition(doc, request, ["placeholder"], name=PREVIEW_NAME)
    left = _read_source(cli_config, left_dc, "left")
    right = _read_source(cli_config, right_dc, "right")
    left_columns, right_columns = _visible(left), _visible(right)
    shared = [c for c in left_columns if c in right_columns]
    suggested = suggest_on_columns(left, right, shared)
    on_columns = list(request.on_columns) or suggested or shared[:1]
    _check_columns(on_columns, shared, left_dc, right_dc)

    join_def, _, _ = _definition(doc, request, on_columns, name=PREVIEW_NAME)
    project = _project_model(doc)
    _validate(join_def, project, cli_config)
    joined, metadata = execute_join(join_def, project, cli_config)

    left_keys, right_keys = _key_tuples(left, on_columns), _key_tuples(right, on_columns)
    left_set = {k for k in left_keys if k is not None}
    right_set = {k for k in right_keys if k is not None}
    left_unmatched = [k for k in left_keys if k is None or k not in right_set]
    right_unmatched = [k for k in right_keys if k is None or k not in left_set]

    def sample(keys: list[tuple | None]) -> list[str]:
        seen: list[str] = []
        for key in keys:
            shown = "(empty)" if key is None else _shown(key)
            if shown not in seen:
                seen.append(shown)
            if len(seen) == UNMATCHED_SAMPLE:
                break
        return seen

    left_tag = str(left_dc.get("data_collection_tag") or "")
    right_tag = str(right_dc.get("data_collection_tag") or "")
    warnings: list[str] = _key_type_sentences(left, right, on_columns, left_tag, right_tag)
    if not left_set & right_set:
        warnings.append("No value of the join column is in both tables: nothing matches.")
    repeated = _repeating_sides(join_def.how, left_keys, right_keys, left_tag, right_tag)
    if repeated:
        warnings.append(
            f"Some values of {', '.join(on_columns)} are on more than one row of "
            f"{' and '.join(repeated)}: a row is repeated once per match, "
            f"which gives {joined.height} rows."
        )
    renamed = metadata.get("renamed_right_columns") or {}
    if renamed:
        warnings.append(_renamed_sentence(renamed, right_tag))

    shown_columns = _visible(joined)
    return {
        "name": request.name,
        "name_problem": name_problem(doc, request.name),
        "result_tag": f"{JOINED_TAG_PREFIX}{request.name}" if request.name else None,
        "how": join_def.how,
        "on_columns": on_columns,
        "suggested_on_columns": suggested,
        "shared_columns": shared,
        "left": {
            "data_collection_id": request.left_dc_id,
            "tag": left_dc.get("data_collection_tag"),
            "rows": left.height,
            "columns": left_columns,
            "unmatched_rows": len(left_unmatched),
            "unmatched_sample": sample(left_unmatched),
        },
        "right": {
            "data_collection_id": request.right_dc_id,
            "tag": right_dc.get("data_collection_tag"),
            "rows": right.height,
            "columns": right_columns,
            "unmatched_rows": len(right_unmatched),
            "unmatched_sample": sample(right_unmatched),
        },
        "matched_keys": len(left_set & right_set),
        "renamed_columns": [{"column": c, "renamed_to": new} for c, new in renamed.items()],
        "joined_rows": joined.height,
        "joined_columns": shown_columns,
        "sample_rows": [
            {c: _json_safe(v) for c, v in row.items()}
            for row in joined.select(shown_columns).head(SAMPLE_ROWS).iter_rows(named=True)
        ],
        "warnings": [w for w in warnings if w],
    }


def _repeating_sides(
    how: str, left_keys: list, right_keys: list, left_tag: str, right_tag: str
) -> list[str]:
    """The tables whose repeated key values that do match repeat rows of the other."""

    def repeated_matching(keys: list, other: set) -> bool:
        seen: set = set()
        for key in keys:
            if key is None or key not in other:
                continue
            if key in seen:
                return True
            seen.add(key)
        return False

    left_set = {k for k in left_keys if k is not None}
    right_set = {k for k in right_keys if k is not None}
    sides = []
    if how != "right" and repeated_matching(right_keys, left_set):
        sides.append(f"'{right_tag}'")
    if how != "left" and repeated_matching(left_keys, right_set):
        sides.append(f"'{left_tag}'")
    return sides


def _kind(dtype: pl.DataType) -> str:
    """A column type in words, as the key-type warning says it."""
    if dtype.is_integer():
        return "a whole number"
    if dtype.is_float() or dtype.is_decimal():
        return "a decimal number"
    if dtype == pl.Boolean:
        return "true / false"
    if dtype.is_temporal():
        return "a date"
    if dtype in (pl.String, pl.Categorical) or isinstance(dtype, pl.Enum):
        return "text"
    return str(dtype)


def _key_type_sentences(
    left: pl.DataFrame, right: pl.DataFrame, keys: list[str], left_tag: str, right_tag: str
) -> list[str]:
    """One sentence per key column of a different kind on each side.

    The join then compares the column as text (``normalize_join_column_types``),
    which silently matches less than it looks: 1 and 1.0, or 7 and "007", differ.
    """
    sentences = []
    for key in keys:
        if key not in left.columns or key not in right.columns:
            continue
        left_kind, right_kind = _kind(left[key].dtype), _kind(right[key].dtype)
        if left_kind != right_kind:
            sentences.append(
                f"{key} is {left_kind} in '{left_tag}' and {right_kind} in '{right_tag}': "
                "compared as text."
            )
    return sentences


def _renamed_sentence(renamed: dict[str, str], right_tag: str) -> str:
    columns = ", ".join(renamed)
    kept = ", ".join(renamed.values())
    if len(renamed) == 1:
        return f"Column {columns} is in both tables: the copy from '{right_tag}' is kept as {kept}."
    return (
        f"Columns {columns} are in both tables: the copies from '{right_tag}' are kept as {kept}."
    )


# ----------------------------------------------------------------------------
# Writing the result
# ----------------------------------------------------------------------------


def _record_size(project_oid: ObjectId, dc_id: str, size_bytes: int) -> None:
    """The joined table's size on its collection, as the upsert route records it.

    Cosmetic (the storage panel), so a failure is logged, never raised.
    """
    dc_oid = ObjectId(dc_id)
    try:
        # persist_joined_table builds the collection with flexible_metadata
        # null, in which Mongo cannot set a field: make it a document first.
        projects_collection.update_one(
            {"_id": project_oid},
            {"$set": {"workflows.$[].data_collections.$[dc].flexible_metadata": {}}},
            array_filters=[{"dc._id": dc_oid, "dc.flexible_metadata": None}],
        )
        prefix = "workflows.$[].data_collections.$[dc].flexible_metadata"
        projects_collection.update_one(
            {"_id": project_oid},
            {
                "$set": {
                    f"{prefix}.deltatable_size_bytes": size_bytes,
                    f"{prefix}.deltatable_size_mb": round(size_bytes / (1024 * 1024), 2),
                }
            },
            array_filters=[{"dc._id": dc_oid}],
        )
    except Exception as exc:  # noqa: BLE001 - a size is not worth failing a join over
        logger.warning(f"Size of joined table {dc_id} not recorded: {exc}")


def _server_hooks(project_oid: ObjectId, current_user):
    """``persist_joined_table``'s hooks for an in-process call: straight to Mongo."""
    from depictio.api.v1.endpoints.datacollections_endpoints.table_manage import (
        _bump_table_dc_aggregation,
        _columns_specs,
        _invalidate_table_caches_for_dc,
    )
    from depictio.cli.cli.utils.joins import JoinPersistHooks

    def records_version(dc_id: str, delta_version: int) -> bool:
        stored = deltatables_collection.find_one({"data_collection_id": ObjectId(dc_id)}) or {}
        aggregations = stored.get("aggregation") or []
        return bool(aggregations) and aggregations[-1].get("delta_version") == delta_version

    def sync_project(project, join_def: JoinDefinition) -> None:
        dc_oid = ObjectId(str(join_def.result_dc_id))
        if not projects_collection.find_one(
            {"_id": project_oid, "workflows.data_collections._id": dc_oid}, {"_id": 1}
        ):
            joined_dc = next(
                (
                    dc
                    for workflow in project.workflows
                    for dc in workflow.data_collections
                    if str(dc.id) == str(dc_oid)
                ),
                None,
            )
            if joined_dc is None:
                raise RuntimeError(f"Joined collection of '{join_def.name}' was not built.")
            projects_collection.update_one(
                {"_id": project_oid},
                {"$push": {"workflows.$[w].data_collections": joined_dc.mongo()}},
                array_filters=[{"w.name": join_def.workflow_name}],
            )
        stored = _store_form(join_def)
        updated = projects_collection.update_one(
            {"_id": project_oid, "joins.name": join_def.name},
            {"$set": {"joins.$": stored}},
        )
        if updated.matched_count == 0:
            projects_collection.update_one({"_id": project_oid}, {"$push": {"joins": stored}})

    def register(
        dc_id: str, location: str, size_bytes: int, provenance: dict, frame: pl.DataFrame
    ) -> None:
        dc_doc = None
        project_doc = projects_collection.find_one({"_id": project_oid}) or {}
        for _, dc in _iter_dcs(project_doc):
            if _dc_id(dc) == dc_id:
                dc_doc = dc
        _bump_table_dc_aggregation(
            dc_id,
            current_user,
            location,
            frame,
            write_mode=provenance.get("write_mode"),
            trigger=provenance.get("trigger"),
            delta_version=provenance.get("delta_version"),
            columns_specs=_columns_specs(dc_id, frame, dc_doc),
            provenance=provenance,
        )
        _record_size(project_oid, dc_id, size_bytes)
        _invalidate_table_caches_for_dc(dc_id)

    return JoinPersistHooks(
        records_version=records_version, sync_project=sync_project, register=register
    )


def _run(join_def: JoinDefinition, project, cli_config, project_oid, current_user) -> dict:
    """Execute and persist one join; ``persist_joined_table``'s result dict."""
    from depictio.cli.cli.utils.joins import execute_join, persist_joined_table

    joined, metadata = execute_join(join_def, project, cli_config)
    return persist_joined_table(
        join_def,
        joined,
        project,
        cli_config,
        metadata,
        overwrite=True,
        hooks=_server_hooks(project_oid, current_user),
        trigger="ui",
    )


def _set_status(project_oid: ObjectId, name: str, error: str | None) -> None:
    from depictio.models.timestamps import utc_now_naive

    projects_collection.update_one(
        {"_id": project_oid, "joins.name": name},
        {"$set": {"joins.$.last_error": error, "joins.$.last_checked_at": utc_now_naive()}},
    )


def create_join(project_id: str, request: JoinRequest, current_user) -> dict[str, Any]:
    """Add the join to the project and write its table, as a new table collection.

    409 when the name or its collection tag is taken; the preview's 422 / 409
    otherwise. Nothing is left behind when the write fails.
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.table_edit import _lock_for

    doc, token = _editable(project_id, current_user)
    if not request.on_columns:
        raise _refuse(422, "invalid_columns", "Pick the column(s) to join on.")
    project_oid = doc["_id"]
    cli_config = _cli_config_with_token(current_user, token)
    problem = name_format_problem(request.name)
    if problem:
        raise _refuse(422, "invalid_name", problem)
    join_def, left_dc, right_dc = _definition(doc, request, list(request.on_columns))

    with _lock_for(f"join:{project_id}:{join_def.name}"):
        doc = projects_collection.find_one({"_id": project_oid}) or doc
        problem = name_problem(doc, join_def.name)
        if problem:
            raise _refuse(409, "name_taken", problem)

        left = _read_source(cli_config, left_dc, "left")
        right = _read_source(cli_config, right_dc, "right")
        shared = [c for c in _visible(left) if c in _visible(right)]
        _check_columns(join_def.on_columns, shared, left_dc, right_dc)

        project = _project_model(doc)
        _validate(join_def, project, cli_config)
        # The same name gives the same table: a dashboard left reading the
        # table of a deleted join reads it again once the join is back.
        join_def.result_dc_id = result_dc_id(project_oid, join_def.name)
        project.joins.append(join_def)
        try:
            result = _run(join_def, project, cli_config, project_oid, current_user)
        except HTTPException:
            _undo_create(project_oid, join_def)
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the caller, rolled back
            logger.exception(f"Join '{join_def.name}' failed in project {project_id}")
            _undo_create(project_oid, join_def)
            raise _refuse(500, "join_failed", f"The join could not be written: {exc}")
        if result.get("result") != "success":
            _undo_create(project_oid, join_def)
            raise _refuse(500, "join_failed", str(result.get("message") or "The join failed."))
        _set_status(project_oid, join_def.name, None)

    logger.info(
        f"Join '{join_def.name}' created in project {project_id}: "
        f"{result.get('rows')} rows -> {result.get('dc_id')}"
    )
    return {
        "success": True,
        "join": _client_form(_store_form(join_def)),
        "data_collection_id": result.get("dc_id"),
        "data_collection_tag": result.get("dc_tag"),
        "rows": result.get("rows"),
        "columns": result.get("columns"),
        "delta_version": result.get("delta_version"),
    }


def result_dc_id(project_oid: ObjectId, name: str):
    """The id of the table of join ``name`` in this project, the same every time."""
    from depictio.models.models.joins import stable_join_result_id

    return stable_join_result_id(project_oid, name)


def _drop_result(project_oid: ObjectId, dc_id: str) -> None:
    """Remove a joined collection: from the project, its aggregation record and links.

    Its Delta files go separately (``_cleanup_s3_delta_table``, async).
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
        _delete_orphan_links_for_dc,
        _forget_cached_reads,
    )

    projects_collection.update_one(
        {"_id": project_oid},
        {"$pull": {"workflows.$[].data_collections": {"_id": ObjectId(dc_id)}}},
    )
    deltatables_collection.delete_many({"data_collection_id": ObjectId(dc_id)})
    _delete_orphan_links_for_dc(dc_id)
    # The join may come back under its name, with this same table id.
    _forget_cached_reads(dc_id)


def _undo_create(project_oid: ObjectId, join_def: JoinDefinition) -> None:
    projects_collection.update_one(
        {"_id": project_oid}, {"$pull": {"joins": {"name": join_def.name}}}
    )
    if join_def.result_dc_id:
        _drop_result(project_oid, str(join_def.result_dc_id))
        _delete_delta_files(str(join_def.result_dc_id))


def _delete_delta_files(dc_id: str) -> None:
    """The Delta files under ``s3://{bucket}/{dc_id}/``; logged, never raised."""
    from depictio.api.v1.s3 import s3_client
    from depictio.models.s3_utils import delete_keys

    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        keys = [
            obj["Key"]
            for page in paginator.paginate(Bucket=settings.s3.bucket, Prefix=f"{dc_id}/")
            for obj in page.get("Contents", []) or []
        ]
        if keys:
            delete_keys(s3_client, settings.s3.bucket, iter(keys))
    except Exception as exc:  # noqa: BLE001 - leftover files cost space, not correctness
        logger.warning(f"Joined table files of {dc_id} not removed: {exc}")


# ----------------------------------------------------------------------------
# List and delete
# ----------------------------------------------------------------------------


def list_joins(project_id: str, current_user) -> dict[str, Any]:
    """The project's joins, with the ids of what they read and write. Viewers too."""
    doc, groups = _viewable(project_id, current_user)
    can_edit = has_permission(doc, current_user, "editor", groups) and not is_project_locked(doc)

    tags = {_dc_id(dc): dc.get("data_collection_tag") for _, dc in _iter_dcs(doc)}
    project = _project_model(doc) if doc.get("joins") else None
    using = _dashboards_reading(doc["_id"], current_user, groups) if doc.get("joins") else {}
    joins = []
    for stored in doc.get("joins") or []:
        entry = _client_form(stored)
        if project is not None:
            join_def = next((j for j in project.joins if j.name == stored.get("name")), None)
            left_id, right_id = _resolve_ids(project, join_def) if join_def else (None, None)
        else:
            left_id = right_id = None
        result_id = entry.get("result_dc_id")
        entry.update(
            {
                "left_dc_id": left_id,
                "right_dc_id": right_id,
                "left_tag": tags.get(left_id) if left_id else None,
                "right_tag": tags.get(right_id) if right_id else None,
                "result_dc_id": result_id if result_id in tags else None,
                "result_tag": tags.get(result_id) if result_id else None,
                "dashboards": using.get(result_id or "", []),
            }
        )
        joins.append(entry)
    return {"joins": joins, "can_edit": can_edit}


def _dashboards_reading(project_oid: ObjectId, current_user, groups: list) -> dict[str, list]:
    """``{collection id: [{id, title}]}``: the project's dashboards each collection feeds.

    A tab counts as its dashboard. One the user cannot open is named as such.
    """
    docs = list(
        dashboards_collection.find(
            {"project_id": {"$in": [project_oid, str(project_oid)]}},
            {
                "dashboard_id": 1,
                "title": 1,
                "parent_dashboard_id": 1,
                "permissions": 1,
                "is_public": 1,
                "stored_metadata.dc_id": 1,
            },
        )
    )
    by_id = {str(d.get("dashboard_id") or d.get("_id")): d for d in docs}
    using: dict[str, list] = {}
    for d in docs:
        main_id = str(d.get("parent_dashboard_id") or d.get("dashboard_id") or d.get("_id"))
        main = by_id.get(main_id, d)
        if has_permission(main, current_user, "viewer", groups):
            entry = {"id": main_id, "title": str(main.get("title") or "Untitled dashboard")}
        else:
            entry = {"id": None, "title": "A dashboard you cannot open"}
        for component in d.get("stored_metadata") or []:
            dc_id = component.get("dc_id") if isinstance(component, dict) else None
            if dc_id is None:
                continue
            listed = using.setdefault(str(dc_id), [])
            if entry not in listed:
                listed.append(entry)
    return using


def delete_join(project_id: str, name: str, current_user) -> dict[str, Any]:
    """Remove the join and its table; its sources stay. Owners and editors.

    Answers the id of the removed collection, whose files the route deletes.
    """
    doc, _ = _editable(project_id, current_user)
    stored = next((j for j in doc.get("joins") or [] if j.get("name") == name), None)
    if stored is None:
        raise _refuse(404, "unknown_join", f"No join named '{name}' in this project.")
    dependants = [j for j in joins_reading(doc, str(stored.get("result_dc_id") or "")) if j != name]
    if stored.get("result_dc_id") and dependants:
        raise _refuse(
            409,
            "join_in_use",
            f"Join(s) {', '.join(dependants)} read this join's table: delete them first.",
        )
    projects_collection.update_one({"_id": doc["_id"]}, {"$pull": {"joins": {"name": name}}})
    result_id = str(stored["result_dc_id"]) if stored.get("result_dc_id") else None
    if result_id:
        _drop_result(doc["_id"], result_id)
    logger.info(f"Join '{name}' deleted from project {project_id} (table {result_id})")
    return {"success": True, "name": name, "data_collection_id": result_id}


# ----------------------------------------------------------------------------
# Rebuild after a source changed
# ----------------------------------------------------------------------------


def rebuild_dependent_joins(source_dc_id: str, current_user) -> list[dict[str, Any]]:
    """Re-run every join reading ``source_dc_id``, then the joins reading those.

    Called after a write through the web UI, once the source is committed: a
    failure is recorded on the join (``last_error``, shown in the project) and
    returned, never raised, since the source write itself went through. A join
    whose rows did not change writes nothing (``persist_joined_table``).
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.table_edit import _lock_for

    try:
        source_oid = ObjectId(source_dc_id)
    except Exception:
        return []
    doc = projects_collection.find_one({"workflows.data_collections._id": source_oid})
    if not doc or not doc.get("joins"):
        return []
    project_oid = doc["_id"]
    reports: list[dict[str, Any]] = []
    done: set[str] = set()
    pending = [source_dc_id]
    token = _usable_user_token(getattr(current_user, "id", None))
    while pending:
        changed = pending.pop(0)
        doc = projects_collection.find_one({"_id": project_oid}) or doc
        project = _project_model(doc)
        for join_def in project.joins:
            if join_def.name in done or not join_def.persist:
                continue
            if changed not in _resolve_ids(project, join_def):
                continue
            done.add(join_def.name)
            report = _rebuild_one(join_def, project, project_oid, token, current_user, _lock_for)
            reports.append(report)
            if report["status"] == "rebuilt" and report.get("data_collection_id"):
                pending.append(report["data_collection_id"])
    return reports


class _NotRebuilt(Exception):
    """Why a join cannot follow its sources, in words for the project page."""


def _frame_or_none(cli_config, dc_id: str) -> pl.DataFrame | None:
    """The table's rows, or None when it holds none (cleared, never filled)."""
    from depictio.cli.cli.utils.deltatables import read_delta_table
    from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

    result = read_delta_table(
        f"s3://{cli_config.s3_storage.bucket}/{dc_id}",
        turn_S3_config_into_polars_storage_options(cli_config.s3_storage),
    )
    frame = result.get("data")
    if result.get("result") != "success" or not isinstance(frame, pl.DataFrame):
        return None
    return frame


def _empty_side(
    stored: pl.DataFrame, other: pl.DataFrame, keys: list[str], *, missing: str
) -> pl.DataFrame:
    """No rows, with the columns side ``missing`` gave the stored joined table.

    A cleared table has no schema left to read, but the joined table kept its
    columns: those of the other side (the right ones as ``join_frames`` renamed
    them) are set aside, the rest are the missing side's.
    """
    from depictio.cli.cli.utils.joins import JOIN_TIMESTAMP_COLUMN

    schema = {c: t for c, t in stored.schema.items() if c != JOIN_TIMESTAMP_COLUMN}
    bookkeeping = {"depictio_run_id", "aggregation_time"}
    renamed_right = {
        c: c.removesuffix("_right")
        for c in schema
        if c.endswith("_right") and c.removesuffix("_right") in schema
    }
    if missing == "left":
        # The right side is there: its columns are known, under their stored names.
        right_only = {c for c in other.columns if c not in keys and f"{c}_right" not in schema}
        right_stored = right_only | {
            c for c, base in renamed_right.items() if base in other.columns
        }
        columns = {
            c: t
            for c, t in schema.items()
            if c in keys or c in bookkeeping or c not in right_stored
        }
    else:
        columns = {}
        for c, t in schema.items():
            if c in keys:
                columns[c] = t
            elif c in renamed_right and renamed_right[c] in other.columns:
                columns[renamed_right[c]] = t
            elif c not in other.columns and c not in bookkeeping and c not in renamed_right:
                columns[c] = t
    return pl.DataFrame(schema=columns)


def _rebuilt_frame(join_def, project, cli_config) -> tuple[pl.DataFrame, dict]:
    """The join over its sources as they are now, a cleared source as no rows."""
    from depictio.cli.cli.utils.joins import find_data_collection_by_tag, join_frames

    sides = {}
    for side, reference in (("left", join_def.left_dc), ("right", join_def.right_dc)):
        dc, _ = find_data_collection_by_tag(project, reference, join_def.workflow_name)
        if dc is None or not dc.id:
            raise _NotRebuilt(f"The table '{reference}' it reads is no longer in this project.")
        sides[side] = (dc, _frame_or_none(cli_config, str(dc.id)))
    (left_dc, left), (right_dc, right) = sides["left"], sides["right"]
    keys = list(join_def.on_columns)
    if left is None or right is None:
        stored = (
            _frame_or_none(cli_config, str(join_def.result_dc_id))
            if join_def.result_dc_id
            else None
        )
        if stored is None:
            empty = left_dc if left is None else right_dc
            raise _NotRebuilt(f"The table '{empty.data_collection_tag}' holds no data.")
        if left is None and right is None:
            left = _empty_side(stored, pl.DataFrame(), keys, missing="left")
            right = pl.DataFrame(schema={k: left.schema[k] for k in keys if k in left.columns})
        elif left is None:
            assert right is not None
            left = _empty_side(stored, right, keys, missing="left")
        else:
            right = _empty_side(stored, left, keys, missing="right")
    assert left is not None and right is not None
    for dc, frame in ((left_dc, left), (right_dc, right)):
        lost = [k for k in keys if k not in frame.columns]
        if lost:
            raise _NotRebuilt(
                f"The table '{dc.data_collection_tag}' no longer has the column(s) "
                f"{', '.join(lost)} it joins on."
            )
    return join_frames(join_def, left, right, left_dc, right_dc)


def _rebuild_one(join_def, project, project_oid, token, current_user, lock_for) -> dict[str, Any]:
    from depictio.cli.cli.utils.joins import persist_joined_table

    report: dict[str, Any] = {"join": join_def.name, "data_collection_id": None}

    def failed(error: str) -> dict[str, Any]:
        _set_status(project_oid, join_def.name, error)
        return {**report, "status": "failed", "error": error}

    if not token:
        return failed(
            "Your account has no usable access token: sign out and in again, "
            "then save a change to one of its tables."
        )
    cli_config = _cli_config_with_token(current_user, token)
    try:
        with lock_for(f"join:{project_oid}:{join_def.name}"):
            joined, metadata = _rebuilt_frame(join_def, project, cli_config)
            result = persist_joined_table(
                join_def,
                joined,
                project,
                cli_config,
                metadata,
                overwrite=True,
                hooks=_server_hooks(project_oid, current_user),
                trigger="ui",
            )
    except _NotRebuilt as exc:
        return failed(str(exc))
    except Exception as exc:  # noqa: BLE001 - the source write stands; the join says why it lags
        logger.exception(f"Rebuild of join '{join_def.name}' failed")
        return failed(f"An unexpected error stopped it ({type(exc).__name__}: {str(exc)[:200]}).")
    if result.get("result") != "success":
        logger.warning(f"Rebuild of join '{join_def.name}' not saved: {result.get('message')}")
        return failed(
            "The joined table could not be saved "
            f"({str(result.get('message') or 'no detail')[:200]})."
        )
    recovered = _had_error(project_oid, join_def.name)
    _set_status(project_oid, join_def.name, None)
    logger.info(
        f"Join '{join_def.name}' rebuilt: {result.get('rows')} rows, "
        f"Delta version {result.get('delta_version')}"
        + (" (unchanged)" if result.get("unchanged") else "")
    )
    return {
        **report,
        "status": "unchanged" if result.get("unchanged") else "rebuilt",
        "data_collection_id": result.get("dc_id"),
        "rows": result.get("rows"),
        "delta_version": result.get("delta_version"),
        # It had failed before: the write that fixed it says so, even when the
        # rows came out as they were stored (nothing new to write).
        "recovered": recovered,
    }


def _had_error(project_oid: ObjectId, name: str) -> bool:
    doc = projects_collection.find_one(
        {"_id": project_oid}, {"joins.name": 1, "joins.last_error": 1}
    )
    stored = next((j for j in (doc or {}).get("joins") or [] if j.get("name") == name), {})
    return bool(stored.get("last_error"))


def rebuild_after_write(source_dc_id: str, current_user) -> list[dict[str, Any]]:
    """``rebuild_dependent_joins``, which never fails the write that called it."""
    try:
        return rebuild_dependent_joins(source_dc_id, current_user)
    except Exception as exc:  # noqa: BLE001 - the source write already went through
        logger.exception(f"Joins reading {source_dc_id} not rebuilt: {exc}")
        return [
            {
                "join": None,
                "status": "failed",
                "error": f"The joins reading this table were not rebuilt ({type(exc).__name__}).",
            }
        ]


# ----------------------------------------------------------------------------
# Keeping joins pointed at their sources
# ----------------------------------------------------------------------------


def sides_reading(doc: dict, dc_id: str) -> list[tuple[str, str]]:
    """``(join name, "left_dc" | "right_dc")`` for every join side reading ``dc_id``."""
    if not doc.get("joins"):
        return []
    project = _project_model(doc)
    sides = []
    for join_def in project.joins:
        left_id, right_id = _resolve_ids(project, join_def)
        if left_id == dc_id:
            sides.append((join_def.name, "left_dc"))
        if right_id == dc_id:
            sides.append((join_def.name, "right_dc"))
    return sides


def retarget_joins(project_oid: ObjectId, dc_id: str, sides: list[tuple[str, str]]) -> None:
    """Point ``sides`` (from ``sides_reading`` before a rename) at ``dc_id`` again.

    A join names its sources by tag, so renaming a source would otherwise leave
    the join reading nothing.
    """
    if not sides:
        return
    doc = projects_collection.find_one({"_id": project_oid}) or {}
    for workflow, dc in _iter_dcs(doc):
        if _dc_id(dc) != dc_id:
            continue
        try:
            reference = _reference(doc, workflow, dc)
        except HTTPException:
            reference = f"{workflow.get('name')}.{dc.get('data_collection_tag')}"
        for name, side in sides:
            projects_collection.update_one(
                {"_id": project_oid, "joins.name": name}, {"$set": {f"joins.$.{side}": reference}}
            )
        return
