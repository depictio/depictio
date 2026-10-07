"""Image uploads to S3 storage, for image data collections.

An image data collection is a table whose ``image_column`` holds image paths
relative to its ``s3_base_folder``. ``depictio ingest`` uploads each one's
``local_images_path`` there, and ``depictio data push-images`` uploads any
directory by hand.
"""

from __future__ import annotations

import mimetypes
import os
import re
from collections.abc import Iterable
from pathlib import Path

from rich.markup import escape

from depictio.cli.cli.utils.rich_utils import console, rich_print_checked_statement
from depictio.cli.cli_logging import logger

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".tiff",
    ".tif",
}

# The {VAR} placeholders data_location.locations expands from the environment.
_ENV_PLACEHOLDER = re.compile(r"\{([A-Z0-9_]+)\}")
# How many missing images a failure names; the rest are counted.
_MISSING_SHOWN = 5


class ImageUploadError(Exception):
    """An image data collection whose images could not all be put in storage."""


def is_image_file(path: Path) -> bool:
    """Whether ``path`` has a supported image extension, in any case."""
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def scan_directory_for_images(
    directory: Path,
    recursive: bool = True,
    extensions: set[str] | None = None,
) -> list[Path]:
    """The image files in ``directory``, sorted, with ``extensions`` (default: all
    supported ones) matched in lower and upper case."""
    if extensions is None:
        extensions = SUPPORTED_IMAGE_EXTENSIONS

    find = directory.rglob if recursive else directory.glob
    images: list[Path] = []
    for ext in extensions:
        images.extend(find(f"*{ext}"))
        images.extend(find(f"*{ext.upper()}"))
    # A case-insensitive filesystem returns a file for both spellings.
    return sorted(set(images))


def get_content_type(path: Path) -> str:
    """The MIME type to store an image with, so browsers render it inline."""
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type or "application/octet-stream"


def parse_s3_folder(uri: str) -> tuple[str, str]:
    """``s3://bucket/some/folder`` as ``("bucket", "some/folder/")``, the prefix
    empty for the bucket root and without empty segments ('a//b' is 'a/b').
    Raises ValueError for anything but an s3:// path."""
    if not uri.startswith("s3://"):
        raise ValueError(f"S3 path must start with 's3://' (e.g., s3://bucket/path/): {uri}")
    bucket, _, path = uri[5:].partition("/")
    if not bucket:
        raise ValueError(f"S3 path names no bucket: {uri}")
    path = "/".join(segment for segment in path.split("/") if segment)
    return bucket, f"{path}/" if path else ""


def image_key(s3_base_folder: str, relative_path: str) -> str:
    """The S3 key of an image path relative to ``s3_base_folder``: where the upload
    puts a local image, and where the dashboard reads an ``image_column`` value.

    Mirrors ``buildImageUrl`` in the viewer's ImageRenderer: the path goes under the
    folder, less its leading slashes and a leading copy of the folder's last
    segment, so 'images/a.png' under 's3://b/images/' is 'images/a.png', not
    'images/images/a.png'. At the bucket root that segment is the bucket's name, as
    in the viewer. The folder's slashes are normalised by ``parse_s3_folder``.
    """
    bucket, prefix = parse_s3_folder(s3_base_folder)
    last = prefix.rstrip("/").rsplit("/", 1)[-1] if prefix else bucket
    rel = relative_path.lstrip("/")
    if rel.startswith(f"{last}/"):
        rel = rel[len(last) + 1 :]
    return f"{prefix}{rel}"


def s3_client(CLI_config):
    """A boto3 client for the S3 storage of a CLI configuration."""
    import boto3

    return boto3.client(
        "s3",
        aws_access_key_id=CLI_config.s3_storage.aws_access_key_id,
        aws_secret_access_key=CLI_config.s3_storage.aws_secret_access_key,
        endpoint_url=CLI_config.s3_storage.url,
    )


def list_existing_keys(s3_client, bucket: str, prefix: str) -> set[str]:
    """Every object key already under ``prefix``, via one paginated LIST.

    Replaces a per-image ``head_object`` when skipping existing uploads: LIST
    returns 1000 keys per call, so 10k images cost ~10 requests instead of
    10k. Returns an empty set on failure: the caller then re-uploads rather
    than wrongly skipping, which is the safe direction to be wrong in.
    """
    keys: set[str] = set()
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.add(obj["Key"])
    except Exception as e:
        logger.warning(f"Could not list existing objects under {prefix}: {e}")
        return set()
    return keys


def upload_images(
    images: list[Path],
    source_root: Path,
    s3_client,
    bucket: str,
    prefix: str,
    *,
    overwrite: bool = False,
    concurrency: int = 8,
    label: str,
) -> dict[str, int]:
    """Upload ``images`` under ``prefix``, each at the ``image_key`` of its path
    relative to ``source_root``.

    Keys already in storage are skipped, or with ``overwrite`` uploaded again.
    ``label`` names the upload in the DEPICTIO_INGEST_TIMINGS marker. Returns how
    many images were uploaded new, replaced an older copy, were skipped and failed.
    """
    # Uploads are independent and network-bound, so they run in parallel; boto3
    # low-level clients are thread-safe, so one client is shared.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    from depictio.cli.cli.utils.ingest_timing import ingest_run, record, timed

    folder = f"s3://{bucket}/{prefix}"
    # Listed with overwrite too, to tell a replaced image from a new one.
    with timed("list_existing"):
        existing_keys = list_existing_keys(s3_client, bucket, prefix)
    logger.debug(f"Found {len(existing_keys)} existing object(s) under {prefix}")

    def _upload_one(img: Path) -> str:
        rel_path = img.relative_to(source_root).as_posix()
        s3_key = image_key(folder, rel_path)
        exists = s3_key in existing_keys
        if exists and not overwrite:
            return "skipped"
        try:
            s3_client.upload_file(
                str(img), bucket, s3_key, ExtraArgs={"ContentType": get_content_type(img)}
            )
            logger.debug(f"Uploaded: {rel_path} → s3://{bucket}/{s3_key}")
            return "replaced" if exists else "uploaded"
        except Exception as e:
            # The count of failures names none of them: each is said here.
            rich_print_checked_statement(
                f"Failed to upload {escape(rel_path)}: {escape(str(e))}", "error"
            )
            return "error"

    counts = {"uploaded": 0, "replaced": 0, "skipped": 0, "error": 0}
    with (
        ingest_run(label, "image"),
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress,
    ):
        record("n_images", len(images))
        task = progress.add_task("Uploading images...", total=len(images))
        # Timed as one batch from the main thread: the per-phase contextvar does
        # not cross into the worker threads.
        with ThreadPoolExecutor(max_workers=concurrency) as executor, timed("upload"):
            futures = [executor.submit(_upload_one, img) for img in images]
            for future in as_completed(futures):
                counts[future.result()] += 1
                progress.update(task, advance=1)
    return counts


def verify_s3_images(
    s3_base_folder: str, CLI_config, referenced: Iterable[str] | None = None
) -> dict:
    """The images stored under ``s3_base_folder``, and which ``referenced`` paths
    (``image_column`` values) have no image there.

    Returns ``count`` (images found), ``sample`` (up to five keys) and ``missing``
    (sorted), or ``error`` when the folder cannot be listed.
    """
    try:
        bucket, prefix = parse_s3_folder(s3_base_folder)
        paginator = s3_client(CLI_config).get_paginator("list_objects_v2")
        keys = {
            obj["Key"]
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
            for obj in page.get("Contents", [])
        }
    except Exception as e:
        logger.warning(f"Failed to verify S3 images at {s3_base_folder}: {e}")
        return {"count": 0, "sample": [], "missing": [], "error": str(e)}

    images = sorted(key for key in keys if is_image_file(Path(key)))
    missing = sorted(
        {rel for rel in referenced or () if image_key(s3_base_folder, rel) not in keys}
    )
    return {"count": len(images), "sample": images[:5], "missing": missing}


def resolve_local_images_path(value: str) -> Path:
    """``local_images_path`` as an absolute directory, read like the project's other paths.

    $VAR is already expanded when the project configuration is validated, and a
    template's {DATA_ROOT} when it is resolved. As in ``data_location.locations``,
    {VAR} comes from the environment ({DEPICTIO_DATA_ROOT} under the Nextflow
    trigger). A relative path is from the current directory, like ``locations``
    and ``scan`` filenames.
    """
    for name in _ENV_PLACEHOLDER.findall(value):
        env_value = os.environ.get(name)
        if not env_value:
            raise ImageUploadError(
                f"Environment variable '{name}' is not set for local_images_path '{value}'"
            )
        value = value.replace(f"{{{name}}}", env_value)
    return Path(value).expanduser().resolve()


def image_collections_to_upload(
    project_config,
    workflow_name: str | None = None,
    data_collection_tag: str | None = None,
) -> list:
    """The project's image data collections that name a ``local_images_path``,
    narrowed like the scan: to the workflow whose tag is ``workflow_name`` and the
    data collection tagged ``data_collection_tag``, when given."""
    return [
        dc
        for workflow in project_config.workflows
        if not workflow_name or workflow.workflow_tag == workflow_name
        for dc in workflow.data_collections
        if (not data_collection_tag or dc.data_collection_tag == data_collection_tag)
        and dc.config.type == "image"
        and getattr(dc.config.dc_specific_properties, "local_images_path", None)
    ]


def _referenced_images(data_collection, CLI_config) -> list[str] | None:
    """The image paths in the data collection's processed table, or None if it
    cannot be read."""
    from depictio.cli.cli.utils.deltatables import read_delta_table
    from depictio.models.s3_utils import turn_S3_config_into_polars_storage_options

    column = data_collection.config.dc_specific_properties.image_column
    table = f"s3://{CLI_config.s3_storage.bucket}/{data_collection.id}"
    result = read_delta_table(
        table, turn_S3_config_into_polars_storage_options(CLI_config.s3_storage)
    )
    df = result.get("data")
    if result.get("result") != "success" or df is None or column not in df.columns:
        logger.warning(f"Could not read column '{column}' of {table}: {result.get('message')}")
        return None
    return [str(v) for v in df[column].drop_nulls().unique().to_list() if str(v).strip()]


def upload_collection_images(data_collection, CLI_config, overwrite: bool = False) -> dict:
    """Upload an image data collection's ``local_images_path`` to its
    ``s3_base_folder``, then check every image its table references is there.

    Images already in storage are skipped, or with ``overwrite`` uploaded again.
    Raises ImageUploadError, with a message for the user, when that fails.
    """
    tag = data_collection.data_collection_tag
    props = data_collection.config.dc_specific_properties
    s3_base_folder = props.s3_base_folder
    bucket, prefix = parse_s3_folder(s3_base_folder)
    served = CLI_config.s3_storage.bucket
    # Both checked before uploading: the dashboard could show none of the images.
    if bucket != served:
        # The server's image route refuses any other bucket.
        raise ImageUploadError(
            f"'{tag}': s3_base_folder {s3_base_folder} is in bucket '{bucket}', but the "
            f"server serves images from its bucket '{served}' only. Set s3_base_folder "
            f"to a folder in it, e.g. s3://{served}/{prefix}"
        )
    if f"s3://{bucket}/{prefix}".rstrip("/") != s3_base_folder.rstrip("/"):
        # The viewer keeps the empty segment in the key, which the server refuses.
        raise ImageUploadError(
            f"'{tag}': s3_base_folder {s3_base_folder} has an empty segment ('//'), and "
            f"the dashboard cannot read images from it. Write it as s3://{bucket}/{prefix}"
        )
    source = resolve_local_images_path(props.local_images_path)
    if not source.is_dir():
        raise ImageUploadError(
            f"'{tag}': local_images_path is not a directory: {source} "
            f"(from '{props.local_images_path}'; a relative path is read from {Path.cwd()})"
        )

    images = scan_directory_for_images(source, extensions=set(props.supported_formats))
    replacing = ", replacing those already in storage" if overwrite else ""
    rich_print_checked_statement(
        f"'{escape(tag)}': uploading {len(images)} image(s) from {escape(str(source))} "
        f"to {escape(s3_base_folder)}{replacing}",
        "info",
    )
    counts = {"uploaded": 0, "replaced": 0, "skipped": 0, "error": 0}
    if images:
        counts = upload_images(
            images,
            source,
            s3_client(CLI_config),
            bucket,
            prefix,
            overwrite=overwrite,
            label=s3_base_folder,
        )
    if counts["error"]:
        raise ImageUploadError(
            f"'{tag}': {counts['error']} of {len(images)} image(s) failed to upload to "
            f"{s3_base_folder}; the errors are above"
        )

    referenced = _referenced_images(data_collection, CLI_config)
    verified = verify_s3_images(s3_base_folder, CLI_config, referenced)
    if "error" in verified:
        raise ImageUploadError(f"'{tag}': could not list {s3_base_folder}: {verified['error']}")
    missing = verified["missing"]
    if missing:
        shown = ", ".join(missing[:_MISSING_SHOWN])
        more = f" and {len(missing) - _MISSING_SHOWN} more" if len(missing) > _MISSING_SHOWN else ""
        raise ImageUploadError(
            f"'{tag}': {len(missing)} image(s) the table's '{props.image_column}' column "
            f"references are not in {s3_base_folder}: {shown}{more}. Put them in {source}, "
            f"keeping the paths the column gives"
        )

    # With overwrite nothing is skipped, without it nothing is replaced.
    kept = (
        f"{counts['replaced']} replaced" if overwrite else f"{counts['skipped']} already in storage"
    )
    stored = f"'{escape(tag)}': {counts['uploaded']} uploaded, {kept}"
    folder = escape(s3_base_folder)
    if referenced is None:
        rich_print_checked_statement(
            f"{stored}; {verified['count']} image(s) in {folder}. "
            f"Its table could not be read, so the paths it references were not checked",
            "warning",
        )
    else:
        rich_print_checked_statement(
            f"{stored}; {verified['count']} image(s) in {folder}, "
            f"including all {len(referenced)} the table references",
            "success",
        )
    return {**counts, "count": verified["count"], "referenced": referenced}
