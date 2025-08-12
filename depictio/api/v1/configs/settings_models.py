import os
from pathlib import Path
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceConfig(BaseSettings):
    """Base class for service configurations with internal/external URL handling."""

    service_name: str
    service_port: int
    external_host: str = Field(default="localhost")
    external_port: int
    external_protocol: str = Field(default="http")
    public_url: Optional[str] = Field(default=None)
    external_service: bool = Field(default=False)

    @property
    def internal_url(self) -> str:
        """URL for internal service-to-service communication."""
        return f"http://{self.service_name}:{self.service_port}"

    @property
    def external_url(self) -> str:
        """URL for external access."""
        if self.public_url:
            return self.public_url
        return f"{self.external_protocol}://{self.external_host}:{self.external_port}"

    @property
    def url(self) -> str:
        context = os.getenv("DEPICTIO_CONTEXT", "server")

        if context == "server":
            # Use public_url only for truly external services
            if self.public_url and self.external_service:
                return self.public_url

            return self.internal_url

        return self.external_url

    # @property
    # def url(self) -> str:
    #     # """Returns appropriate URL based on DEPICTIO_CONTEXT."""
    #     context = os.getenv("DEPICTIO_CONTEXT", "client")
    #     print(f"SETTINGS DEPICTIO_CONTEXT: {context}")
    #     # return self.internal_url if context == "server" else self.external_url

    #     # If running inside the server context we normally want to use the
    #     # internal service URL for inter-service communication.  However when a
    #     # ``public_url`` pointing to a remote MinIO/S3 instance is provided we
    #     # must use that instead.  This allows the same configuration object to
    #     # be used both from inside microservices and when connecting to an
    #     # external S3 installation.
    #     if context == "server":
    #         if self.public_url:
    #             host = urlparse(self.public_url).hostname or ""
    #             if host not in {self.service_name, "localhost", "127.0.0.1"}:
    #                 return self.public_url
    #         return self.internal_url

    #     return self.external_url

    @property
    def port(self) -> int:
        return self.external_port


class S3DepictioCLIConfig(ServiceConfig):
    """S3 configuration inheriting service URL management."""

    service_name: str = Field(default="minio")
    service_port: int = Field(default=9000)
    external_port: int = Field(default=9000)

    # S3-specific fields
    root_user: str = Field(default="minio")
    root_password: str = Field(default="minio123")
    bucket: str = Field(default="depictio-bucket")

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MINIO_")

    # Backwards compatibility aliases
    # def __init__(self, **data: object) -> None:
    #     print(f"Data received in S3DepictioCLIConfig: {data}")
    #     data.setdefault("public_url", f"{data['external_protocol']}://{data['external_host']}:{data['external_port']}")
    #     data.setdefault("endpoint_url", data.get("public_url"))
    #     super().__init__(**data)
    # if endpoint_url:
    # parsed = urlparse(endpoint_url)
    # if parsed.scheme:
    #     data.setdefault("external_protocol", parsed.scheme)
    # if parsed.hostname:
    #     data.setdefault("external_host", parsed.hostname)
    # if parsed.port:
    #     data.setdefault("external_port", parsed.port)

    # super().__init__(**data)

    # Backwards compatibility aliases
    @property
    def endpoint_url(self) -> str:
        """Returns URL for Polars and other S3 clients."""
        return self.url

    @property
    def host(self) -> str:
        return self.external_host

    # Additional aliases for S3 compatibility
    @property
    def aws_access_key_id(self) -> str:
        return self.root_user

    @property
    def aws_secret_access_key(self) -> str:
        return self.root_password


class FastAPIConfig(ServiceConfig):
    service_name: str = Field(default="depictio-backend")
    service_port: int = Field(default=8058)
    external_port: int = Field(default=8058)
    host: str = Field(default="0.0.0.0")
    workers: int = Field(default=1)
    ssl: bool = Field(default=False)
    logging_level: str = Field(default="INFO")

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_FASTAPI_")


class DashConfig(ServiceConfig):
    service_name: str = Field(default="depictio-frontend")
    service_port: int = Field(default=5080)
    external_port: int = Field(default=5080)
    host: str = Field(default="0.0.0.0")
    workers: int = Field(default=1)
    debug: bool = Field(default=True)
    auto_generate_figures: bool = Field(
        default=True, description="Enable automatic figure generation in UI mode"
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_DASH_")


class MongoDBConfig(ServiceConfig):
    service_name: str = Field(default="mongo")
    service_port: int = Field(default=27018)
    external_port: int = Field(default=27018)
    db_name: str = Field(default="depictioDB")
    wipe: bool = Field(default=False)

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MONGODB_")

    # Collections
    class Collections(BaseSettings):
        data_collection: str = Field(default="data_collections")
        workflow_collection: str = Field(default="workflows")
        runs_collection: str = Field(default="runs")
        files_collection: str = Field(default="files")
        users_collection: str = Field(default="users")
        tokens_collection: str = Field(default="tokens")
        groups_collection: str = Field(default="groups")
        deltatables_collection: str = Field(default="deltatables")
        jbrowse_collection: str = Field(default="jbrowse")
        dashboards_collection: str = Field(default="dashboards")
        initialization_collection: str = Field(default="initialization")
        projects_collection: str = Field(default="projects")
        test_collection: str = Field(default="test")

    collections: Collections = Field(default_factory=Collections)


class AuthConfig(BaseSettings):
    keys_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent.parent / "keys"
    )
    keys_algorithm: str = Field(default="RS256")
    cli_config_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent.parent / ".depictio"
    )
    internal_api_key_env: Optional[str] = Field(default=None)
    unauthenticated_mode: bool = Field(default=False, description="Enable unauthenticated mode")
    anonymous_user_email: str = Field(
        default="anonymous@depict.io",
        description="Default anonymous user email",
    )
    temporary_user_expiry_hours: int = Field(
        default=24,
        description="Number of hours until temporary users expire",
    )
    temporary_user_expiry_minutes: int = Field(
        default=0,
        description="Number of minutes until temporary users expire",
    )

    # Google OAuth Configuration
    google_oauth_enabled: bool = Field(
        default=False, description="Enable Google OAuth authentication"
    )
    google_oauth_client_id: Optional[str] = Field(
        default=None, description="Google OAuth client ID"
    )
    google_oauth_client_secret: Optional[str] = Field(
        default=None, description="Google OAuth client secret"
    )
    google_oauth_redirect_uri: Optional[str] = Field(
        default=None, description="Google OAuth redirect URI"
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_AUTH_", case_sensitive=False)

    def __init__(self, **data):
        super().__init__(**data)

        # Manually read the environment variable if not set
        if self.internal_api_key_env is None:
            import os

            self.internal_api_key_env = os.getenv("DEPICTIO_AUTH_INTERNAL_API_KEY")

    @computed_field
    @property
    def internal_api_key(self) -> str:
        """
        Get the internal API key using the existing key_utils_base functions.
        This maintains consistency and avoids code duplication.
        """
        # First check if environment variable is set
        if self.internal_api_key_env:
            return self.internal_api_key_env

        # Otherwise use the key utils to load/generate
        from depictio.api.v1.key_utils_base import _load_or_generate_api_internal_key

        return _load_or_generate_api_internal_key(
            keys_dir=self.keys_dir,
            algorithm=self.keys_algorithm,
        )


class LoggingConfig(BaseSettings):
    verbosity_level: str = Field(default="ERROR")

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_LOGGING_")


class JBrowseConfig(BaseSettings):
    enabled: bool = Field(default=False)

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_JBROWSE_")


class PerformanceConfig(BaseSettings):
    """Performance and timeout settings that can be tuned per environment."""

    # HTTP client timeouts (in seconds)
    http_client_timeout: int = Field(default=30)
    api_request_timeout: int = Field(default=60)

    # Playwright/browser timeouts (in milliseconds)
    browser_navigation_timeout: int = Field(default=60000)  # 60s default
    browser_page_load_timeout: int = Field(default=90000)  # 90s default
    browser_element_timeout: int = Field(default=30000)  # 30s default

    # Screenshot-specific timeouts (production typically needs longer)
    screenshot_navigation_timeout: int = Field(default=45000)  # 45s for navigation
    screenshot_content_wait: int = Field(default=15000)  # 15s for content
    screenshot_stabilization_wait: int = Field(default=5000)  # 5s for stability
    screenshot_capture_timeout: int = Field(default=90000)  # 90s for actual screenshot capture
    screenshot_api_timeout: int = Field(default=300)  # 5 minutes for complete screenshot API call

    # Service readiness check settings
    service_readiness_retries: int = Field(default=5)
    service_readiness_delay: int = Field(default=3)
    service_readiness_timeout: int = Field(default=10)

    # DNS and network performance settings
    dns_cache_ttl: int = Field(default=300)  # 5 minutes
    connection_pool_size: int = Field(default=10)
    max_keepalive_connections: int = Field(default=5)

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_PERFORMANCE_")


class BackupConfig(BaseSettings):
    """Backup and restore configuration settings."""

    # Base directory for all backup-related files (similar to AuthConfig pattern)
    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent)
    # Directory where backup files are stored on the server (relative to base_dir)
    backup_dir: str = Field(default="backups")

    # S3 data backup strategy
    s3_backup_strategy: str = Field(
        default="s3_to_s3",
        description="Strategy for S3 data backup: 's3_to_s3', 'local', or 'both'",
    )

    # Local S3 data backup directory (for local strategy)
    s3_local_backup_dir: str = Field(default="backups/s3_data_backups")

    # Backup S3 configuration (for separate backup bucket)
    backup_s3_enabled: bool = Field(default=False, description="Enable separate backup S3 bucket")
    backup_s3_bucket: str = Field(default="depictio-backups", description="Backup S3 bucket name")
    backup_s3_endpoint_url: Optional[str] = Field(
        default=None, description="Backup S3 endpoint URL"
    )
    backup_s3_access_key: Optional[str] = Field(default=None, description="Backup S3 access key")
    backup_s3_secret_key: Optional[str] = Field(default=None, description="Backup S3 secret key")
    backup_s3_region: str = Field(default="us-east-1", description="Backup S3 region")

    # Compression and optimization
    compress_local_backups: bool = Field(default=True, description="Compress local S3 data backups")
    backup_file_retention_days: int = Field(default=30, description="Days to retain backup files")

    @computed_field
    @property
    def backup_path(self) -> str:
        """Get absolute backup directory path for MongoDB backups."""
        return str(self.base_dir / self.backup_dir)

    @computed_field
    @property
    def s3_local_backup_path(self) -> str:
        """Get absolute local backup directory path for S3 data."""
        return str(self.base_dir / self.s3_local_backup_dir)

    @computed_field
    @property
    def backup_s3_config(self) -> Optional[dict]:
        """Get backup S3 configuration if enabled."""
        if not self.backup_s3_enabled:
            return None

        config = {
            "region_name": self.backup_s3_region,
            "verify": False,  # Disable SSL verification for play.minio.io
        }

        if self.backup_s3_endpoint_url:
            config["endpoint_url"] = self.backup_s3_endpoint_url
        if self.backup_s3_access_key:
            config["aws_access_key_id"] = self.backup_s3_access_key
        if self.backup_s3_secret_key:
            config["aws_secret_access_key"] = self.backup_s3_secret_key

        return config

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_BACKUP_")


class AnalyticsConfig(BaseSettings):
    """Configuration for analytics tracking."""

    enabled: bool = Field(default=False, description="Enable analytics tracking")
    session_timeout_minutes: int = Field(
        default=30,
        description="Session timeout in minutes",
        ge=5,
        le=1440,
    )
    cleanup_days: int = Field(
        default=90,
        description="Days to retain analytics data",
        ge=1,
        le=365,
    )
    track_anonymous_users: bool = Field(
        default=True,
        description="Track anonymous user sessions",
    )
    cleanup_enabled: bool = Field(
        default=True,
        description="Enable automatic cleanup of old analytics data",
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_ANALYTICS_")


class GoogleAnalyticsConfig(BaseSettings):
    """Configuration for Google Analytics tracking."""

    enabled: bool = Field(default=False, description="Enable Google Analytics tracking")
    tracking_id: Optional[str] = Field(
        default=None,
        description="Google Analytics tracking ID (GA4 measurement ID)",
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_GOOGLE_ANALYTICS_")

    @property
    def is_configured(self) -> bool:
        """Check if Google Analytics is properly configured."""
        return self.enabled and self.tracking_id is not None


class Settings(BaseSettings):
    context: str = Field(default="server")
    fastapi: FastAPIConfig = Field(default_factory=FastAPIConfig)
    dash: DashConfig = Field(default_factory=DashConfig)
    mongodb: MongoDBConfig = Field(default_factory=MongoDBConfig)
    minio: S3DepictioCLIConfig = Field(default_factory=S3DepictioCLIConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    jbrowse: JBrowseConfig = Field(default_factory=JBrowseConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    google_analytics: GoogleAnalyticsConfig = Field(default_factory=GoogleAnalyticsConfig)

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_")
