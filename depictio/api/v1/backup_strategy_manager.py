"""
S3 Data Backup Strategy Manager

Provides different strategies for backing up S3 deltatable data:
1. S3-to-S3: Copy to backup S3 bucket (default)
2. Local: Download to local filesystem
3. Both: S3-to-S3 + Local backup

This allows data to be copied closer to the server for faster access,
disaster recovery, and cross-environment migration.
"""

import shutil
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


class S3BackupStrategyManager:
    """
    Manages different strategies for backing up S3 deltatable data.

    Supports multiple backup destinations to provide flexible data protection
    and migration capabilities.
    """

    def __init__(self, source_s3_config: dict):
        """
        Initialize the backup strategy manager.

        Args:
            source_s3_config: Source S3 configuration
        """
        self.source_s3_config = source_s3_config
        self.backup_config = settings.backup

        # Initialize source S3 client
        logger.info(f"Initializing source S3 client with config: {source_s3_config}")
        self.source_client = boto3.client(
            "s3",
            endpoint_url=source_s3_config.get("endpoint_url"),
            aws_access_key_id=source_s3_config["aws_access_key_id"],
            aws_secret_access_key=source_s3_config["aws_secret_access_key"],
            region_name=source_s3_config.get("region_name", "us-east-1"),
            verify=False,  # Disable SSL verification for local MinIO
        )

        # Initialize backup S3 client if configured
        self.backup_s3_client = None
        if self.backup_config.backup_s3_config:
            backup_config = self.backup_config.backup_s3_config
            logger.info(f"Initializing backup S3 client with config: {backup_config}")
            self.backup_s3_client = boto3.client("s3", **backup_config)

    async def backup_deltatable_data(
        self, deltatable_locations: List[str], backup_prefix: str = "backup", dry_run: bool = False
    ) -> Dict:
        """
        Backup deltatable data using the configured strategy.

        Args:
            deltatable_locations: List of S3 paths to backup
            backup_prefix: Prefix for backup organization
            dry_run: If True, simulate without actual copying

        Returns:
            Dictionary with backup results
        """
        backup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        strategy = self.backup_config.s3_backup_strategy

        logger.info(f"Starting S3 backup with strategy: {strategy}")

        results = {
            "strategy": strategy,
            "backup_timestamp": backup_timestamp,
            "locations_processed": 0,
            "total_files": 0,
            "total_bytes": 0,
            "success": True,
            "errors": [],
            "backup_locations": {},
        }

        try:
            if strategy == "s3_to_s3":
                await self._backup_s3_to_s3(
                    deltatable_locations, backup_prefix, backup_timestamp, dry_run, results
                )
            elif strategy == "local":
                await self._backup_s3_to_local(
                    deltatable_locations, backup_prefix, backup_timestamp, dry_run, results
                )
            elif strategy == "both":
                # Perform both strategies
                s3_results = await self._backup_s3_to_s3(
                    deltatable_locations,
                    backup_prefix,
                    backup_timestamp,
                    dry_run,
                    {
                        "backup_locations": {},
                        "total_files": 0,
                        "total_bytes": 0,
                        "success": True,
                        "errors": [],
                    },
                )
                local_results = await self._backup_s3_to_local(
                    deltatable_locations,
                    backup_prefix,
                    backup_timestamp,
                    dry_run,
                    {
                        "backup_locations": {},
                        "total_files": 0,
                        "total_bytes": 0,
                        "success": True,
                        "errors": [],
                    },
                )

                # Combine results
                results["s3_backup"] = s3_results
                results["local_backup"] = local_results
                results["total_files"] = s3_results.get("total_files", 0)
                results["total_bytes"] = s3_results.get("total_bytes", 0)
                results["success"] = s3_results.get("success", False) and local_results.get(
                    "success", False
                )

                # Combine backup locations from both strategies
                combined_locations = {}
                combined_locations.update(s3_results.get("backup_locations", {}))
                combined_locations.update(local_results.get("backup_locations", {}))
                results["backup_locations"] = combined_locations
            else:
                raise ValueError(f"Unknown backup strategy: {strategy}")

        except Exception as e:
            logger.error(f"Backup strategy failed: {e}")
            results["success"] = False
            results["errors"].append(str(e))

        return results

    async def _backup_s3_to_s3(
        self,
        deltatable_locations: List[str],
        backup_prefix: str,
        backup_timestamp: str,
        dry_run: bool,
        results: Dict,
    ) -> Dict:
        """Backup S3 data to backup S3 bucket."""
        if not self.backup_s3_client:
            raise ValueError("Backup S3 not configured for s3_to_s3 strategy")

        backup_bucket = self.backup_config.backup_s3_bucket
        source_bucket = self.source_s3_config["bucket"]

        # Check if backup bucket is accessible
        try:
            # List available buckets to find a suitable one
            response = self.backup_s3_client.list_buckets()
            available_buckets = [bucket["Name"] for bucket in response.get("Buckets", [])]
            logger.info(f"Available buckets on backup S3: {available_buckets}")

            if backup_bucket not in available_buckets:
                logger.warning(f"Backup bucket '{backup_bucket}' not found in available buckets")
                if available_buckets:
                    # Use the first available bucket
                    backup_bucket = available_buckets[0]
                    logger.info(f"Using existing bucket: {backup_bucket}")
                else:
                    raise ValueError("No buckets available on backup S3 server")
            else:
                logger.info(f"Using configured backup bucket: {backup_bucket}")

        except ClientError as e:
            logger.error(f"Error accessing backup S3 server: {e}")
            results["success"] = False
            results.setdefault("errors", []).append(f"Error accessing backup S3: {e}")
            return results

        for location in deltatable_locations:
            try:
                location_key = location.strip("/")
                backup_location = f"{backup_prefix}/{backup_timestamp}/{location_key}"

                # List files in source location
                response = self.source_client.list_objects_v2(
                    Bucket=source_bucket, Prefix=location_key
                )

                if "Contents" not in response:
                    logger.warning(f"No files found in location: {location}")
                    continue

                files_copied = 0
                bytes_copied = 0

                for obj in response["Contents"]:
                    source_key = obj["Key"]
                    backup_key = source_key.replace(location_key, backup_location, 1)

                    if not dry_run:
                        # Download from source and upload to backup (cross-service copy)
                        logger.debug(f"Downloading from source: s3://{source_bucket}/{source_key}")
                        try:
                            # Download object from source S3
                            response = self.source_client.get_object(
                                Bucket=source_bucket, Key=source_key
                            )
                            object_data = response["Body"].read()

                            # Upload to backup S3
                            logger.debug(f"Uploading to backup: s3://{backup_bucket}/{backup_key}")
                            self.backup_s3_client.put_object(
                                Bucket=backup_bucket,
                                Key=backup_key,
                                Body=object_data,
                                ContentType=response.get("ContentType", "application/octet-stream"),
                            )
                        except ClientError as copy_error:
                            logger.error(f"Failed to copy {source_key}: {copy_error}")
                            raise

                    files_copied += 1
                    bytes_copied += obj["Size"]

                    logger.debug(
                        f"{'DRY RUN: Would copy' if dry_run else 'Copied'}: {source_key} -> s3://{backup_bucket}/{backup_key}"
                    )

                results["backup_locations"][location] = f"s3://{backup_bucket}/{backup_location}"
                results["locations_processed"] = results.get("locations_processed", 0) + 1
                results["total_files"] = results.get("total_files", 0) + files_copied
                results["total_bytes"] = results.get("total_bytes", 0) + bytes_copied

                logger.info(
                    f"S3-to-S3 backup: {files_copied} files ({bytes_copied} bytes) from {location}"
                )

            except ClientError as e:
                error_msg = f"S3 error backing up {location}: {e}"
                logger.error(error_msg)
                results.setdefault("errors", []).append(error_msg)
                results["success"] = False

        return results

    async def _backup_s3_to_local(
        self,
        deltatable_locations: List[str],
        backup_prefix: str,
        backup_timestamp: str,
        dry_run: bool,
        results: Dict,
    ) -> Dict:
        """Backup S3 data to local filesystem."""
        base_local_path = Path(self.backup_config.s3_local_backup_path)
        backup_local_path = base_local_path / backup_prefix / backup_timestamp

        if not dry_run:
            backup_local_path.mkdir(parents=True, exist_ok=True)

        source_bucket = self.source_s3_config["bucket"]

        for location in deltatable_locations:
            try:
                location_key = location.strip("/")
                local_location = backup_local_path / location_key

                if not dry_run:
                    local_location.mkdir(parents=True, exist_ok=True)

                # List files in source location
                response = self.source_client.list_objects_v2(
                    Bucket=source_bucket, Prefix=location_key
                )

                if "Contents" not in response:
                    logger.warning(f"No files found in location: {location}")
                    continue

                files_downloaded = 0
                bytes_downloaded = 0

                for obj in response["Contents"]:
                    source_key = obj["Key"]
                    # Create relative path structure
                    relative_key = source_key.replace(location_key, "", 1).lstrip("/")
                    local_file_path = local_location / relative_key

                    if not dry_run:
                        # Ensure parent directory exists
                        local_file_path.parent.mkdir(parents=True, exist_ok=True)

                        # Download file
                        self.source_client.download_file(
                            source_bucket, source_key, str(local_file_path)
                        )

                    files_downloaded += 1
                    bytes_downloaded += obj["Size"]

                    logger.debug(
                        f"{'DRY RUN: Would download' if dry_run else 'Downloaded'}: {source_key} -> {local_file_path}"
                    )

                # Compress if enabled
                if self.backup_config.compress_local_backups and not dry_run:
                    await self._compress_local_backup(
                        local_location, location_key, backup_timestamp
                    )

                results["backup_locations"][location] = str(local_location)
                results["locations_processed"] = results.get("locations_processed", 0) + 1
                results["total_files"] = results.get("total_files", 0) + files_downloaded
                results["total_bytes"] = results.get("total_bytes", 0) + bytes_downloaded

                logger.info(
                    f"S3-to-Local backup: {files_downloaded} files ({bytes_downloaded} bytes) from {location}"
                )

            except Exception as e:
                error_msg = f"Local backup error for {location}: {e}"
                logger.error(error_msg)
                results.setdefault("errors", []).append(error_msg)
                results["success"] = False

        return results

    async def _compress_local_backup(
        self, local_path: Path, location_key: str, backup_timestamp: str
    ):
        """Compress local backup directory."""
        try:
            # Create compressed archive
            archive_name = f"{location_key.replace('/', '_')}_{backup_timestamp}.tar.gz"
            archive_path = local_path.parent / archive_name

            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(local_path, arcname=local_path.name)

            # Remove uncompressed directory
            shutil.rmtree(local_path)

            logger.info(f"Compressed local backup: {archive_path}")

        except Exception as e:
            logger.error(f"Compression failed for {local_path}: {e}")

    async def cleanup_old_backups(self):
        """Clean up old backup files based on retention policy."""
        retention_days = self.backup_config.backup_file_retention_days
        cutoff_date = datetime.now() - timedelta(days=retention_days)

        # Clean up local backups
        if self.backup_config.s3_backup_strategy in ["local", "both"]:
            await self._cleanup_local_backups(cutoff_date)

        # Clean up S3 backups
        if self.backup_config.s3_backup_strategy in ["s3_to_s3", "both"] and self.backup_s3_client:
            await self._cleanup_s3_backups(cutoff_date)

    async def _cleanup_local_backups(self, cutoff_date: datetime):
        """Clean up old local backup files."""
        try:
            base_path = Path(self.backup_config.s3_local_backup_path)
            if not base_path.exists():
                return

            for backup_dir in base_path.iterdir():
                if backup_dir.is_dir():
                    try:
                        # Parse timestamp from directory name
                        for subdir in backup_dir.iterdir():
                            if subdir.is_dir() and len(subdir.name) == 15:  # YYYYMMDD_HHMMSS format
                                backup_date = datetime.strptime(subdir.name, "%Y%m%d_%H%M%S")
                                if backup_date < cutoff_date:
                                    shutil.rmtree(subdir)
                                    logger.info(f"Cleaned up old local backup: {subdir}")
                    except ValueError:
                        continue  # Skip directories that don't match timestamp format

        except Exception as e:
            logger.error(f"Local backup cleanup failed: {e}")

    async def _cleanup_s3_backups(self, cutoff_date: datetime):
        """Clean up old S3 backup files."""
        try:
            bucket = self.backup_config.backup_s3_bucket

            # List backup prefixes
            response = self.backup_s3_client.list_objects_v2(Bucket=bucket, Delimiter="/")

            for prefix_info in response.get("CommonPrefixes", []):
                prefix = prefix_info["Prefix"]

                # List timestamp directories within each prefix
                timestamp_response = self.backup_s3_client.list_objects_v2(
                    Bucket=bucket, Prefix=prefix, Delimiter="/"
                )

                for timestamp_info in timestamp_response.get("CommonPrefixes", []):
                    timestamp_prefix = timestamp_info["Prefix"]
                    timestamp_str = timestamp_prefix.rstrip("/").split("/")[-1]

                    try:
                        if len(timestamp_str) == 15:  # YYYYMMDD_HHMMSS format
                            backup_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                            if backup_date < cutoff_date:
                                # Delete all objects with this timestamp prefix
                                await self._delete_s3_prefix(bucket, timestamp_prefix)
                                logger.info(f"Cleaned up old S3 backup: {timestamp_prefix}")
                    except ValueError:
                        continue  # Skip directories that don't match timestamp format

        except Exception as e:
            logger.error(f"S3 backup cleanup failed: {e}")

    async def _delete_s3_prefix(self, bucket: str, prefix: str):
        """Delete all objects with a given prefix."""
        paginator = self.backup_s3_client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if "Contents" in page:
                objects_to_delete = [{"Key": obj["Key"]} for obj in page["Contents"]]

                if objects_to_delete:
                    self.backup_s3_client.delete_objects(
                        Bucket=bucket, Delete={"Objects": objects_to_delete}
                    )


async def create_backup_with_strategy(
    deltatable_locations: List[str], backup_prefix: str = "backup", dry_run: bool = False
) -> Dict:
    """
    Convenience function to create backup using configured strategy.

    Args:
        deltatable_locations: List of S3 paths to backup
        backup_prefix: Prefix for backup organization
        dry_run: If True, simulate without actual copying

    Returns:
        Dictionary with backup results
    """
    # Get source S3 config from settings
    source_s3_config = {
        "bucket": settings.minio.bucket,
        "endpoint_url": settings.minio.endpoint_url,
        "aws_access_key_id": settings.minio.aws_access_key_id,
        "aws_secret_access_key": settings.minio.aws_secret_access_key,
        "region_name": "us-east-1",
    }

    manager = S3BackupStrategyManager(source_s3_config)
    return await manager.backup_deltatable_data(deltatable_locations, backup_prefix, dry_run)
