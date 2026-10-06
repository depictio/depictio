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
    empty for the bucket root. Raises ValueError for anything but an s3:// path."""
    if not uri.startswith("s3://"):
        raise ValueError(f"S3 path must start with 's3://' (e.g., s3://bucket/path/): {uri}")
    bucket, _, path = uri[5:].partition("/")
    if not bucket:
        raise ValueError(f"S3 path names no bucket: {uri}")
    path = path.strip("/")
    return bucket, f"{path}/" if path else ""


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
    """Upload ``images`` to ``prefix``, keeping their paths relative to ``source_root``.

    Keys already in storage are skipped unless ``overwrite``. ``label`` names the
    upload in the DEPICTIO_INGEST_TIMINGS marker. Returns how many images were
    uploaded, skipped and failed.
    """
    # Uploads are independent and network-bound, so they run in parallel; boto3
    # low-level clients are thread-safe, so one client is shared.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    from depictio.cli.cli.utils.ingest_timing import ingest_run, record, timed

    existing_keys: set[str] = set()
    if not overwrite:
        with timed("list_existing"):
            existing_keys = list_existing_keys(s3_client, bucket, prefix)
        logger.debug(f"Found {len(existing_keys)} existing object(s) under {prefix}")

    def _upload_one(img: Path) -> str:
        rel_path = img.relative_to(source_root)
        s3_key = f"{prefix}{rel_path}".replace("\\", "/")
        try:
            if not overwrite and s3_key in existing_keys:
                return "skipped"
            s3_client.upload_file(
                str(img), bucket, s3_key, ExtraArgs={"ContentType": get_content_type(img)}
            )
            logger.debug(f"Uploaded: {rel_path} → s3://{bucket}/{s3_key}")
            return "uploaded"
        except Exception as e:
            logger.error(f"Failed to upload {rel_path}: {e}")
            return "error"

    counts = {"uploaded": 0, "skipped": 0, "error": 0}
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


def image_key(s3_base_folder: str, relative_path: str) -> str:
    """The key the dashboard reads for an ``image_column`` value.

    Mirrors the viewer's image component: the path goes under ``s3_base_folder``,
    less a leading copy of the folder's last segment, so 'images/a.png' under
    's3://b/images/' is 'images/a.png', not 'images/images/a.png'.
    """
    base = s3_base_folder.rstrip("/")
    last = base.rsplit("/", 1)[-1]
    rel = relative_path.lstrip("/")
    if last and rel.startswith(f"{last}/"):
        rel = rel[len(last) + 1 :]
    return f"{base}/{rel}"[5:].partition("/")[2]


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


def image_collections_to_upload(project_config) -> list:
    """The project's image data collections that name a ``local_images_path``."""
    return [
        dc
        for workflow in project_config.workflows
        for dc in workflow.data_collections
        if dc.config.type == "image"
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


def upload_collection_images(data_collection, CLI_config) -> dict:
    """Upload an image data collection's ``local_images_path`` to its
    ``s3_base_folder``, then check every image its table references is there.

    Raises ImageUploadError, with a message for the user, when that fails.
    """
    tag = data_collection.data_collection_tag
    props = data_collection.config.dc_specific_properties
    s3_base_folder = props.s3_base_folder
    source = resolve_local_images_path(props.local_images_path)
    if not source.is_dir():
        raise ImageUploadError(
            f"'{tag}': local_images_path is not a directory: {source} "
            f"(from '{props.local_images_path}'; a relative path is read from {Path.cwd()})"
        )
    bucket, prefix = parse_s3_folder(s3_base_folder)
    if bucket != CLI_config.s3_storage.bucket:
        # The server only serves images from its own bucket.
        rich_print_checked_statement(
            f"'{tag}': s3_base_folder is in bucket '{bucket}', but the server serves "
            f"images from '{CLI_config.s3_storage.bucket}' only",
            "warning",
        )

    images = scan_directory_for_images(source, extensions=set(props.supported_formats))
    rich_print_checked_statement(
        f"'{tag}': uploading {len(images)} image(s) from {source} to {s3_base_folder}", "info"
    )
    counts = {"uploaded": 0, "skipped": 0, "error": 0}
    if images:
        counts = upload_images(
            images, source, s3_client(CLI_config), bucket, prefix, label=s3_base_folder
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

    stored = f"{counts['uploaded']} uploaded, {counts['skipped']} already in storage"
    if referenced is None:
        rich_print_checked_statement(
            f"'{tag}': {stored}; {verified['count']} image(s) in {s3_base_folder}. "
            f"Its table could not be read, so the paths it references were not checked",
            "warning",
        )
    else:
        rich_print_checked_statement(
            f"'{tag}': {stored}; {verified['count']} image(s) in {s3_base_folder}, "
            f"including all {len(referenced)} the table references",
            "success",
        )
    return {**counts, "count": verified["count"], "referenced": referenced}
