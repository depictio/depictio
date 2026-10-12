"""Show the start of one file of a run folder: ``POST /projects/run_file_preview``.

The run-folder dialog of ``POST /projects/from_run`` lists the files a template
would read (the report's ``input_files``, each collection's ``samples``), and
its folder browser the files of each folder. This shows what one of them
holds, so the user can tell it is the file they meant before a project is made
from the folder: the first rows of a table, the first lines of a text, or in
plain words why it is not shown. ``data_root`` is then the folder the file was
listed in.

The run folder is opened exactly as ``from_run`` opens it
(:func:`from_run._build_data_root`, with the request's storage settings read
as there), so this route answers the same refusals: a folder on this computer
only under ``depictio local``, below an allowed root, for an administrator on
this machine; an ``s3://`` one through the target its configuration resolves
to. The file has to lie below the folder, and is read through the root alone.

How a file is decoded, and how little of it is read, is
:mod:`depictio.cli.cli.utils.file_preview`, which the Project Builder's
standalone server uses as well.

Synchronous: the route dispatches via ``asyncio.to_thread``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from depictio.api.v1.endpoints.projects_endpoints.from_run import (
    _build_data_root,
    _request_read_config,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.api.v1.endpoints.projects_endpoints.storage_config import RunStorageIn
from depictio.cli.cli.utils.file_preview import (  # noqa: F401 — re-exported
    BINARY,
    MAX_CELL_CHARS,
    MAX_GZ_BYTES,
    MAX_HEAD_BYTES,
    MAX_PARQUET_BYTES,
    MAX_PREVIEW_COLUMNS,
    MAX_TEXT_CHARS,
    MAX_TEXT_LINES,
    RunFilePreview,
    preview_root_file,
)
from depictio.models.local_access import LocalPathRefused

OUTSIDE_RUN = "location_outside_run"
FILE_MISSING = "run_file_missing"


class RunFilePreviewRequest(BaseModel):
    """Body of POST /projects/run_file_preview.

    ``data_root`` and ``storage`` as ``POST /projects/from_run`` takes them;
    ``location`` a file below ``data_root``, a real path or an ``s3://`` URL.
    """

    data_root: str
    location: str
    storage: RunStorageIn | None = None
    max_rows: int = Field(default=20, ge=1, le=50)
    # Name each column's dtype too (``RunFilePreview.dtypes``).
    infer_types: bool = False


# ── the route ────────────────────────────────────────────────────────────────


def preview_run_file(payload: RunFilePreviewRequest, *, request, current_user) -> RunFilePreview:
    """The preview of ``payload.location``, a file of run folder ``payload.data_root``.

    Refused as ``POST /projects/from_run`` refuses the folder (the same
    :func:`from_run._build_data_root`); then a 422 coded
    ``location_outside_run`` for a location the folder does not hold, a 404
    ``run_file_missing`` for one that is not a file there, and a 422 with the
    policy's own code for a file the policy does not let the server read. An
    S3 refusal or failure keeps its own code.
    """
    _settings, read_config = _request_read_config(payload.data_root, payload.storage)
    # One bounded read of one file: the file count that keeps a scan off a
    # whole disk does not apply, so any folder the browser lists can show its
    # files, a home folder included.
    root = _build_data_root(
        payload.data_root,
        read_config,
        request=request,
        current_user=current_user,
        count_files=False,
    )
    relative = root.relative_of(payload.location)
    if relative is None:
        raise CodedHTTPException(
            422,
            f"'{payload.location}' is outside the run folder '{root.location}'. Pick a "
            "file in that folder.",
            OUTSIDE_RUN,
        )
    try:
        return preview_root_file(
            root, relative, max_rows=payload.max_rows, infer_types=payload.infer_types
        )
    except FileNotFoundError as exc:
        raise CodedHTTPException(
            404, f"'{payload.location}' is not a file of the run folder.", FILE_MISSING
        ) from exc
    except LocalPathRefused as exc:
        raise CodedHTTPException(422, exc.detail, exc.code) from exc
