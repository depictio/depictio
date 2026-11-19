"""Tokens a worker task mints for the user it works for, and revokes when done.

A task that calls the API or drives the viewer on someone's behalf (a rendered
report, a headless figure extraction) acts with *their* rights, never the
admin's, and for no longer than it runs. The token is minted when the task
starts rather than when it is queued, so time spent waiting for a worker does
not eat into it, and lives for the task's own time limit at least. Callers
hold a Beanie context (``TokenBeanie``); they delete the token in ``finally``.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from depictio.models.models.base import PyObjectId
from depictio.models.models.users import TokenBeanie, TokenData


async def mint_task_token(user_id: str, name: str, lifetime_s: int) -> TokenBeanie:
    """A short-lived token for ``user_id``, valid for ``lifetime_s`` at least."""
    from depictio.api.v1.endpoints.user_endpoints.utils import create_access_token

    data = TokenData(sub=PyObjectId(user_id), name=name, token_lifetime="short-lived")
    hours = max(1, math.ceil(lifetime_s / 3600))
    access_token, expire = await create_access_token(data, expiry_hours=hours)
    token = TokenBeanie(
        user_id=user_id,  # type: ignore[arg-type]
        access_token=access_token,
        # No refresh: the task's token is not to be renewed past the task.
        refresh_token="",
        token_lifetime="short-lived",
        expire_datetime=expire,
        refresh_expire_datetime=expire,
        name=name,
    )
    await token.save()
    return token


def browser_token_payload(token: TokenBeanie) -> dict[str, Any]:
    """The token as the viewer keeps it in localStorage (``get_admin_auth_token``)."""
    data = token.model_dump(exclude_none=True)
    data["_id"] = str(data.pop("id", None) or token.id)
    data["user_id"] = str(data["user_id"])
    data["logged_in"] = True
    for key in ("expire_datetime", "refresh_expire_datetime", "created_at"):
        if isinstance(data.get(key), datetime):
            data[key] = data[key].strftime("%Y-%m-%d %H:%M:%S")
    return data


async def revoke(token: TokenBeanie | None) -> None:
    if token is not None:
        await token.delete()
