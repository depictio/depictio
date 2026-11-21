"""Routes for table joins made in the web UI (``/joins``).

The work is in ``service.py``: synchronous, since it drives the CLI's join
helpers, so every route hands it to a thread.
"""

import asyncio

from fastapi import APIRouter, Depends

from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _cleanup_s3_delta_table,
    _ensure_user_cli_token,
)
from depictio.api.v1.endpoints.joins_endpoints.service import (
    JoinRequest,
    create_join,
    delete_join,
    list_joins,
    preview_join,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous

joins_endpoint_router = APIRouter()


@joins_endpoint_router.get("/{project_id}")
async def list_project_joins(project_id: str, current_user=Depends(get_user_or_anonymous)):
    """The project's joins, with the ids of the tables they read and write.

    ``can_edit`` says whether the caller may add or delete one (owner or editor,
    project not published). 404 when the caller cannot see the project.
    """
    return await asyncio.to_thread(list_joins, project_id, current_user)


@joins_endpoint_router.post("/{project_id}/preview")
async def preview_project_join(
    project_id: str, body: JoinRequest, current_user=Depends(get_current_user)
):
    """What a join would give, written nowhere.

    Body: ``left_dc_id``, ``right_dc_id``, ``on_columns`` (empty: the server's
    suggestion), ``how`` (``left`` by default), ``name``. Answers the row counts
    of both sides and of the result, the rows of each side without a partner
    and the first rows. Owners and editors (403), 409 on a published project or
    a table without data, 422 (with a ``code``) for a join that cannot be made.
    """
    await _ensure_user_cli_token(current_user)
    return await asyncio.to_thread(preview_join, project_id, body, current_user)


@joins_endpoint_router.post("/{project_id}")
async def create_project_join(
    project_id: str, body: JoinRequest, current_user=Depends(get_current_user)
):
    """Add a join to the project and write its table, a new table collection.

    The sources are left as they are; the joined table is rebuilt whenever one
    of them changes through the web UI. Same rules as the preview, plus 409
    (``name_taken``) when the name or its collection tag is in use.
    """
    await _ensure_user_cli_token(current_user)
    return await asyncio.to_thread(create_join, project_id, body, current_user)


@joins_endpoint_router.delete("/{project_id}/{join_name}")
async def delete_project_join(
    project_id: str, join_name: str, current_user=Depends(get_current_user)
):
    """Remove a join and its table; the sources stay. Owners and editors.

    409 on a published project, or when another join reads this one's table.
    """
    result = await asyncio.to_thread(delete_join, project_id, join_name, current_user)
    if result.get("data_collection_id"):
        await _cleanup_s3_delta_table(result["data_collection_id"])
    return result
