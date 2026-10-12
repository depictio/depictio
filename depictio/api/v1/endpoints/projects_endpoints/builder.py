"""The Project Builder's routes on the main API: ``/projects/builder/*``.

The routes themselves are ``depictio.project_builder.routes``; this module is
how the main API opens the root a request names. Exactly as the run-folder
dialog opens a run folder (``from_run._request_read_config`` +
``_build_data_root``): a folder on the server's disk only under ``depictio
local``, below an allowed root, for an administrator on this machine; an
``s3://`` prefix through the target its configuration (or the request's
private-bucket settings) resolves to. Same caller gate as ``from_run`` too:
authenticated, and refused to non-admins in public mode. An ``s3://`` root's
listing is reused for a minute per caller (``RootCache``), so the match panel
can ask per keystroke without re-listing the prefix.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError

from depictio.api.v1.endpoints.projects_endpoints.from_run import (
    _build_data_root,
    _request_read_config,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.api.v1.endpoints.projects_endpoints.storage_config import RunStorageIn
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.roots import RootCache
from depictio.project_builder.routes import RootOpener, RootSpec, build_builder_router

_ROOTS = RootCache()


def _storage_key(storage: dict | None) -> str:
    if not storage:
        return ""
    return hashlib.sha256(json.dumps(storage, sort_keys=True).encode()).hexdigest()


def server_root_opener(request: Request, current_user=Depends(get_user_or_anonymous)) -> RootOpener:
    """The opener every builder route gets on the main API (a FastAPI dependency)."""
    from depictio.api.v1.endpoints.projects_endpoints.routes import (
        _reject_non_admin_in_public_mode,
    )

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    # The from_run gate: the builder is a way of creating a project.
    _reject_non_admin_in_public_mode(current_user, "Project creation")

    def open_root(spec: RootSpec, *, count_files: bool):
        try:
            storage = RunStorageIn(**spec.storage) if spec.storage else None
        except ValidationError as exc:
            # Never the rejected input: it may be the secret itself.
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error.get('loc', ()))}: {error.get('msg')}"
                for error in exc.errors(
                    include_input=False, include_url=False, include_context=False
                )
            )
            raise BuilderRefused(
                422, f"Invalid storage settings: {problems}", "storage_invalid"
            ) from None
        try:
            _settings, read_config = _request_read_config(spec.data_root, storage)
            key = (spec.data_root, _storage_key(spec.storage), str(current_user.id))
            return _ROOTS.get(
                key,
                lambda: _build_data_root(
                    spec.data_root,
                    read_config,
                    request=request,
                    current_user=current_user,
                    count_files=count_files,
                ),
                refresh=spec.refresh,
            )
        except CodedHTTPException as exc:
            raise BuilderRefused(exc.status_code, str(exc.detail), exc.code) from exc
        except HTTPException as exc:
            raise BuilderRefused(exc.status_code, str(exc.detail)) from exc

    return open_root


builder_endpoint_router = build_builder_router(server_root_opener)
