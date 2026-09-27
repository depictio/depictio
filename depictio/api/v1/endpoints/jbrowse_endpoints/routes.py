"""Genome browser endpoints: assembly/preset catalogues and the track proxy.

The embedded JBrowse view reads every track, index and custom-assembly file
through ``/jbrowse/tracks/…`` and ``/jbrowse/assembly/…``. Those URLs are
minted by ``POST /dashboards/render_jbrowse`` with a short-lived signature
(see ``services/jbrowse/signing.py``); the location they read is looked up
server-side in the data collection, so the browser can never make the API
fetch an arbitrary URL.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.api.v1.services import remote_read
from depictio.api.v1.services.jbrowse import signing
from depictio.api.v1.services.jbrowse.assemblies import (
    PRESET_ROLES,
    get_assembly_preset,
    list_assembly_presets,
    preset_file_uri,
)
from depictio.api.v1.services.jbrowse.config_builder import list_builtin_presets
from depictio.api.v1.services.jbrowse.tracks import (
    ASSEMBLY_ROLES,
    TRACK_ROLES,
    TracksDC,
    find_tracks_dc,
    s3_base_folder,
    tracks_by_key,
    user_can_read_project,
)
from depictio.models.models.data_collections_types.genomic_tracks import CustomAssembly

jbrowse_endpoints_router = APIRouter()

_MIME = {
    ".bam": "application/octet-stream",
    ".bai": "application/octet-stream",
    ".cram": "application/octet-stream",
    ".crai": "application/octet-stream",
    ".bw": "application/octet-stream",
    ".bigwig": "application/octet-stream",
    ".bb": "application/octet-stream",
    ".bigbed": "application/octet-stream",
    ".2bit": "application/octet-stream",
    ".gz": "application/gzip",
    ".tbi": "application/octet-stream",
    ".csi": "application/octet-stream",
}


def _content_type(uri: str) -> str:
    path = uri.split("?", 1)[0].lower()
    for ext, mime in _MIME.items():
        if path.endswith(ext):
            return mime
    return "text/plain; charset=utf-8"


@jbrowse_endpoints_router.get("/assemblies")
def get_assembly_presets() -> list[dict]:
    """Built-in reference assemblies (name, display name, organism, annotation)."""
    return list_assembly_presets()


@jbrowse_endpoints_router.get("/presets")
def get_config_presets() -> list[dict]:
    """Built-in named config presets a component can pick with ``preset:``."""
    return list_builtin_presets()


async def _optional_user(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
):
    """The caller when a bearer token (or public/single-user mode) identifies one."""
    try:
        return await get_user_or_anonymous(token)
    except HTTPException:
        return None


def _authorize(
    request: Request,
    scope: str,
    dc_id: str,
    item: str,
    role: str,
    user,
) -> TracksDC:
    """Resolve the DC and check the signed URL (or a bearer token) grants ``role``."""
    tdc = find_tracks_dc(dc_id)
    if tdc is None:
        raise HTTPException(status_code=404, detail="Track collection not found")

    q = request.query_params
    uid = q.get("uid")
    if signing.verify(scope, dc_id, item, role, uid, q.get("exp"), q.get("sig")):
        assert uid is not None
        if user_can_read_project(tdc.project_id, uid):
            return tdc
        raise HTTPException(status_code=404, detail="Track collection not found")

    if user is not None and user_can_read_project(tdc.project_id, str(user.id)):
        return tdc
    raise HTTPException(status_code=401, detail="Missing or expired track URL signature")


def _serve(request: Request, src: remote_read.ByteSource, uri: str) -> Response:
    try:
        size = remote_read.source_size(src)
    except remote_read.RemoteReadError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    try:
        rng = remote_read.parse_range(request.headers.get("range"), size)
    except remote_read.RemoteReadError as exc:
        raise HTTPException(
            status_code=exc.status,
            detail=exc.detail,
            headers={"Content-Range": f"bytes */{size}"},
        ) from exc

    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "Content-Type": _content_type(uri),
    }
    if request.method == "HEAD":
        return Response(status_code=200, headers={**base_headers, "Content-Length": str(size)})

    max_range = settings.jbrowse.max_range_mb * 1024 * 1024
    if rng is None:
        if size > settings.jbrowse.max_full_read_mb * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="File too large to serve whole; index it (bgzip + tabix) "
                "so the browser reads it by range",
            )
        if size == 0:
            return Response(status_code=200, headers={**base_headers, "Content-Length": "0"})
        rng = remote_read.ByteRange(0, size - 1)
        status = 200
    else:
        if rng.length > max_range:
            rng = remote_read.ByteRange(rng.start, rng.start + max_range - 1)
        status = 206

    try:
        chunks = remote_read.open_range(src, rng)
    except remote_read.RemoteReadError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    headers = {**base_headers, "Content-Length": str(rng.length)}
    if status == 206:
        headers["Content-Range"] = f"bytes {rng.start}-{rng.end}/{size}"
    return StreamingResponse(chunks, status_code=status, headers=headers)


@jbrowse_endpoints_router.api_route("/tracks/{dc_id}/{track_key}/{role}", methods=["GET", "HEAD"])
def proxy_track_file(
    dc_id: str,
    track_key: str,
    role: str,
    request: Request,
    user=Depends(_optional_user),
) -> Response:
    """Serve (a byte range of) one track's data or index file."""
    if role not in TRACK_ROLES:
        raise HTTPException(status_code=404, detail="Unknown track file role")
    tdc = _authorize(request, "track", dc_id, track_key, role, user)
    track = tracks_by_key(tdc).get(track_key)
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    uri = track.uri if role == "data" else track.index_uri
    if not uri:
        raise HTTPException(status_code=404, detail="Track has no index")
    try:
        src = remote_read.resolve_location(uri, s3_base_folder(dc_id, tdc.props))
    except remote_read.RemoteReadError as exc:
        logger.info(f"jbrowse proxy refused {dc_id}/{track_key}/{role}: {exc.detail}")
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return _serve(request, src, uri)


def _assembly_uri(assembly: CustomAssembly, role: str) -> str | None:
    fasta = assembly.fasta_uri
    return {
        "fasta": fasta,
        "fai": assembly.fai_uri or (f"{fasta}.fai" if fasta else None),
        "gzi": assembly.gzi_uri or (f"{fasta}.gzi" if fasta else None),
        "twobit": assembly.twobit_uri,
        "chrom_sizes": assembly.chrom_sizes_uri,
        "aliases": assembly.refname_aliases_uri,
    }.get(role)


@jbrowse_endpoints_router.api_route("/assembly/{dc_id}/{role}", methods=["GET", "HEAD"])
def proxy_assembly_file(
    dc_id: str,
    role: str,
    request: Request,
    user=Depends(_optional_user),
) -> Response:
    """Serve (a byte range of) a custom assembly file of a track collection."""
    if role not in ASSEMBLY_ROLES:
        raise HTTPException(status_code=404, detail="Unknown assembly file role")
    tdc = _authorize(request, "assembly", dc_id, "assembly", role, user)
    assembly = tdc.props.assembly
    if not isinstance(assembly, CustomAssembly):
        raise HTTPException(status_code=404, detail="Collection uses a preset assembly")
    uri = _assembly_uri(assembly, role)
    if not uri:
        raise HTTPException(status_code=404, detail="Assembly file not configured")
    try:
        src = remote_read.resolve_location(uri, s3_base_folder(dc_id, tdc.props))
    except remote_read.RemoteReadError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return _serve(request, src, uri)


# Small preset files (chrom.sizes, alias tables) are read whole by the browser
# on every view: keep them in memory rather than re-fetching them from UCSC.
_SMALL_FILE_BYTES = 2 * 1024 * 1024
_small_files: dict[str, bytes] = {}


def _serve_bytes(request: Request, data: bytes, uri: str) -> Response:
    size = len(data)
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
        "Content-Type": _content_type(uri),
    }
    if request.method == "HEAD":
        return Response(status_code=200, headers={**base_headers, "Content-Length": str(size)})
    try:
        rng = remote_read.parse_range(request.headers.get("range"), size)
    except remote_read.RemoteReadError as exc:
        raise HTTPException(
            status_code=exc.status, detail=exc.detail, headers={"Content-Range": f"bytes */{size}"}
        ) from exc
    if rng is None:
        return Response(content=data, status_code=200, headers=base_headers)
    return Response(
        content=data[rng.start : rng.end + 1],
        status_code=206,
        headers={**base_headers, "Content-Range": f"bytes {rng.start}-{rng.end}/{size}"},
    )


@jbrowse_endpoints_router.api_route("/preset/{name}/{role}", methods=["GET", "HEAD"])
def proxy_preset_file(name: str, role: str, request: Request) -> Response:
    """Serve (a byte range of) a built-in assembly's public UCSC file.

    Public: the files are public reference data. Only the URLs hardcoded in the
    presets can be read, so the route cannot be pointed anywhere else.
    """
    preset = get_assembly_preset(name)
    if preset is None or role not in PRESET_ROLES:
        raise HTTPException(status_code=404, detail="Unknown assembly preset file")
    uri = preset_file_uri(preset, role)
    if not uri:
        raise HTTPException(status_code=404, detail="This preset has no such file")
    src = remote_read.ByteSource("https", url=uri)
    cached = _small_files.get(uri)
    if cached is not None:
        return _serve_bytes(request, cached, uri)
    try:
        size = remote_read.source_size(src)
    except remote_read.RemoteReadError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    if size <= _SMALL_FILE_BYTES:
        try:
            data = remote_read.read_all(src, _SMALL_FILE_BYTES)
        except remote_read.RemoteReadError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        if len(_small_files) > 256:
            _small_files.clear()
        _small_files[uri] = data
        return _serve_bytes(request, data, uri)
    return _serve(request, src, uri)
