#!/usr/bin/env python3
"""Copy a bucket from a legacy MinIO server into the new bundled SeaweedFS store.

Depictio's bundled object store moved from MinIO to SeaweedFS (``weed mini``).
MinIO's on-disk layout (``xl.meta``) cannot be read by any other server, so the
data has to be copied *through the S3 API*: start the old MinIO next to the new
store (``docker-compose/docker-compose.minio-legacy.yaml``) and run this script.

The script only needs ``boto3`` (already a Depictio dependency)::

    # dry run — list what would be copied
    uv run scripts/migrate_minio_to_seaweedfs.py --dry-run

    # real copy, then verify key count + sizes
    uv run scripts/migrate_minio_to_seaweedfs.py --verify

Defaults: source ``http://127.0.0.1:9100`` (the legacy side-car), target
``http://127.0.0.1:9000`` (the new store as published by docker-compose.dev.yaml
or a ``kubectl port-forward``), credentials from ``DEPICTIO_MINIO_ROOT_USER`` /
``DEPICTIO_MINIO_ROOT_PASSWORD`` for both sides, bucket ``DEPICTIO_MINIO_BUCKET``
(``depictio-bucket``).

Kubernetes (ReadWriteOnce PVC — old and new pods cannot mount the data at the
same time): run in two hops through a local directory::

    # before the chart upgrade, old MinIO still running
    kubectl port-forward svc/<release>-minio 9100:9000
    uv run scripts/migrate_minio_to_seaweedfs.py --export-dir ./s3-export
    # upgrade the chart, then
    kubectl port-forward svc/<release>-minio 9000:9000
    uv run scripts/migrate_minio_to_seaweedfs.py --import-dir ./s3-export --verify

MongoDB is untouched: object keys are identical on both sides, so no
reference inside Depictio changes.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

MULTIPART_THRESHOLD = 64 * 1024 * 1024  # 64 MiB — keep small objects single-part


@dataclass(frozen=True)
class Endpoint:
    url: str
    access_key: str
    secret_key: str
    region: str = "us-east-1"

    def client(self):
        # Same client shape as depictio.cli.cli.utils.multiqc_processor._make_s3_client:
        # path-style addressing + SigV4 is the portable choice across S3 stores.
        return boto3.client(
            "s3",
            endpoint_url=self.url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 5, "mode": "standard"},
            ),
        )


@dataclass
class Obj:
    key: str
    size: int
    etag: str


def _default_target_url() -> str:
    """Prefer the Depictio settings resolution when the package is importable."""
    try:
        from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig

        cfg = S3DepictioCLIConfig()
        # ``url`` resolves to the internal service name in server context; from a
        # host shell we want the externally reachable one.
        return cfg.external_url
    except Exception:  # depictio not installed / settings validation — fall back
        return "http://127.0.0.1:9000"


def list_objects(client, bucket: str, prefix: str) -> list[Obj]:
    paginator = client.get_paginator("list_objects_v2")
    out: list[Obj] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            out.append(Obj(key=o["Key"], size=int(o["Size"]), etag=o.get("ETag", "").strip('"')))
    return out


def ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in ("404", "NoSuchBucket"):
            raise
        client.create_bucket(Bucket=bucket)
        print(f"created bucket {bucket!r} on target")


def head_or_none(client, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def copy_one(src, dst, bucket: str, obj: Obj, skip_existing: bool) -> str:
    if skip_existing:
        existing = head_or_none(dst, bucket, obj.key)
        if existing is not None and int(existing.get("ContentLength", -1)) == obj.size:
            return "skipped"
    resp = src.get_object(Bucket=bucket, Key=obj.key)
    extra: dict[str, Any] = {}
    if resp.get("ContentType"):
        extra["ContentType"] = resp["ContentType"]
    if resp.get("Metadata"):
        extra["Metadata"] = resp["Metadata"]
    dst.upload_fileobj(
        resp["Body"],
        bucket,
        obj.key,
        ExtraArgs=extra or None,
        Config=TransferConfig(multipart_threshold=MULTIPART_THRESHOLD),
    )
    return "copied"


def export_one(src, bucket: str, obj: Obj, export_dir: Path) -> str:
    dest = export_dir / obj.key
    if dest.exists() and dest.stat().st_size == obj.size:
        return "skipped"
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.download_file(bucket, obj.key, str(dest))
    return "copied"


def import_one(dst, bucket: str, path: Path, key: str, skip_existing: bool) -> str:
    if skip_existing:
        existing = head_or_none(dst, bucket, key)
        if existing is not None and int(existing.get("ContentLength", -1)) == path.stat().st_size:
            return "skipped"
    dst.upload_file(
        str(path), bucket, key, Config=TransferConfig(multipart_threshold=MULTIPART_THRESHOLD)
    )
    return "copied"


def run_parallel(jobs, workers: int) -> dict[str, int]:
    counts = {"copied": 0, "skipped": 0, "failed": 0}
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn): label for label, fn in jobs}
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                counts[fut.result()] += 1
            except Exception as exc:  # keep going, report at the end
                counts["failed"] += 1
                failures.append((label, str(exc)))
                print(f"FAILED {label}: {exc}", file=sys.stderr)
    for label, err in failures[:20]:
        print(f"  - {label}: {err}", file=sys.stderr)
    return counts


def verify(src_objs: list[Obj], dst_objs: list[Obj]) -> bool:
    dst_by_key = {o.key: o for o in dst_objs}
    missing = [o.key for o in src_objs if o.key not in dst_by_key]
    size_mismatch = [
        o.key for o in src_objs if o.key in dst_by_key and dst_by_key[o.key].size != o.size
    ]
    # ETags only compare for single-part objects (multipart ETags are not content hashes).
    etag_mismatch = [
        o.key
        for o in src_objs
        if o.key in dst_by_key
        and "-" not in o.etag
        and "-" not in dst_by_key[o.key].etag
        and o.etag
        and dst_by_key[o.key].etag
        and o.etag != dst_by_key[o.key].etag
    ]
    print(
        f"verify: source={len(src_objs)} target={len(dst_objs)} "
        f"missing={len(missing)} size_mismatch={len(size_mismatch)} etag_mismatch={len(etag_mismatch)}"
    )
    for label, keys in (("missing", missing), ("size", size_mismatch), ("etag", etag_mismatch)):
        for k in keys[:10]:
            print(f"  {label}: {k}")
    return not (missing or size_mismatch or etag_mismatch)


def main(argv: list[str] | None = None) -> int:
    env = os.environ
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source-endpoint", default=env.get("MIGRATE_SOURCE_ENDPOINT", "http://127.0.0.1:9100")
    )
    parser.add_argument(
        "--source-access-key",
        default=env.get("MIGRATE_SOURCE_ACCESS_KEY")
        or env.get("DEPICTIO_MINIO_ROOT_USER", "minio"),
    )
    parser.add_argument(
        "--source-secret-key",
        default=env.get("MIGRATE_SOURCE_SECRET_KEY") or env.get("DEPICTIO_MINIO_ROOT_PASSWORD"),
        help="Defaults to DEPICTIO_MINIO_ROOT_PASSWORD (required)",
    )
    parser.add_argument(
        "--target-endpoint", default=env.get("MIGRATE_TARGET_ENDPOINT") or _default_target_url()
    )
    parser.add_argument(
        "--target-access-key",
        default=env.get("MIGRATE_TARGET_ACCESS_KEY")
        or env.get("DEPICTIO_MINIO_ROOT_USER", "minio"),
    )
    parser.add_argument(
        "--target-secret-key",
        default=env.get("MIGRATE_TARGET_SECRET_KEY") or env.get("DEPICTIO_MINIO_ROOT_PASSWORD"),
        help="Defaults to DEPICTIO_MINIO_ROOT_PASSWORD (required)",
    )
    parser.add_argument("--bucket", default=env.get("DEPICTIO_MINIO_BUCKET", "depictio-bucket"))
    parser.add_argument("--target-bucket", default=None, help="Defaults to --bucket")
    parser.add_argument("--prefix", default="", help="Only copy keys under this prefix")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", help="List objects, copy nothing")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip keys already on target with the same size",
    )
    parser.add_argument("--verify", action="store_true", help="Compare listings after the copy")
    parser.add_argument(
        "--export-dir",
        type=Path,
        help="Download the source bucket into this directory instead of copying",
    )
    parser.add_argument(
        "--import-dir",
        type=Path,
        help="Upload this directory into the target bucket instead of copying",
    )
    args = parser.parse_args(argv)

    if args.export_dir and args.import_dir:
        parser.error("--export-dir and --import-dir are mutually exclusive")
    if not args.import_dir and not args.source_secret_key:
        parser.error("--source-secret-key (or DEPICTIO_MINIO_ROOT_PASSWORD) is required")
    if not args.export_dir and not args.target_secret_key:
        parser.error("--target-secret-key (or DEPICTIO_MINIO_ROOT_PASSWORD) is required")
    target_bucket = args.target_bucket or args.bucket

    src_ep = Endpoint(args.source_endpoint, args.source_access_key, args.source_secret_key)
    dst_ep = Endpoint(args.target_endpoint, args.target_access_key, args.target_secret_key)

    # ---- import from directory ------------------------------------------------
    if args.import_dir:
        dst = dst_ep.client()
        files = [p for p in args.import_dir.rglob("*") if p.is_file()]
        print(f"import: {len(files)} files from {args.import_dir} -> {dst_ep.url}/{target_bucket}")
        if args.dry_run:
            for p in files[:50]:
                print(f"  {p.relative_to(args.import_dir).as_posix()}")
            return 0
        ensure_bucket(dst, target_bucket)
        jobs = [
            (
                p.relative_to(args.import_dir).as_posix(),
                lambda p=p: import_one(
                    dst,
                    target_bucket,
                    p,
                    p.relative_to(args.import_dir).as_posix(),
                    args.skip_existing,
                ),
            )
            for p in files
        ]
        counts = run_parallel(jobs, args.workers)
        print(f"import: {counts}")
        if args.verify:
            dst_objs = list_objects(dst, target_bucket, args.prefix)
            expected = [
                Obj(key=p.relative_to(args.import_dir).as_posix(), size=p.stat().st_size, etag="")
                for p in files
            ]
            return 0 if verify(expected, dst_objs) and counts["failed"] == 0 else 1
        return 0 if counts["failed"] == 0 else 1

    # ---- list source -----------------------------------------------------------
    src = src_ep.client()
    src_objs = list_objects(src, args.bucket, args.prefix)
    total_bytes = sum(o.size for o in src_objs)
    print(
        f"source: {src_ep.url}/{args.bucket} prefix={args.prefix!r}: {len(src_objs)} objects, {total_bytes / 1e6:.1f} MB"
    )
    if args.dry_run:
        for o in src_objs[:50]:
            print(f"  {o.size:>12}  {o.key}")
        if len(src_objs) > 50:
            print(f"  … {len(src_objs) - 50} more")
        return 0

    # ---- export to directory ---------------------------------------------------
    if args.export_dir:
        args.export_dir.mkdir(parents=True, exist_ok=True)
        jobs = [
            (o.key, lambda o=o: export_one(src, args.bucket, o, args.export_dir)) for o in src_objs
        ]
        counts = run_parallel(jobs, args.workers)
        print(f"export -> {args.export_dir}: {counts}")
        return 0 if counts["failed"] == 0 else 1

    # ---- S3 -> S3 --------------------------------------------------------------
    dst = dst_ep.client()
    ensure_bucket(dst, target_bucket)
    print(f"target: {dst_ep.url}/{target_bucket}")
    jobs = [
        (o.key, lambda o=o: copy_one(src, dst, args.bucket, o, args.skip_existing))
        for o in src_objs
    ]
    counts = run_parallel(jobs, args.workers)
    print(f"copy: {counts}")
    ok = counts["failed"] == 0
    if args.verify:
        dst_objs = list_objects(dst, target_bucket, args.prefix)
        ok = verify(src_objs, dst_objs) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
