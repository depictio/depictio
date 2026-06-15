import os
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import AliasChoices, Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Passwords we refuse to accept on a server boot. Lower-cased before comparison.
_WEAK_PASSWORDS: frozenset[str] = frozenset(
    {
        "",
        "minio",
        "minio123",
        "password",
        "passw0rd",
        "admin",
        "admin123",
        "depictio",
        "test_pwd",
        "test",
        "secret",
        "12345678",
        "letmein",
    }
)
# "changeme" / "change_me" are intentionally NOT in _WEAK_PASSWORDS so they
# remain usable as a dev/default admin password for quick local starts.
_WEAK_PASSWORDS_MINIO: frozenset[str] = _WEAK_PASSWORDS | frozenset({"changeme", "change_me"})
_MIN_SECRET_LEN = 8

# ── Core Services ─────────────────────────────────────────────────────────────


class ServiceConfig(BaseSettings):
    """Base class for service configurations with internal/external URL handling."""

    service_name: str
    service_port: int
    external_host: str = Field(default="localhost", description="Hostname for external access")
    external_port: int
    external_protocol: str = Field(
        default="http", description="Protocol for external access (http/https)"
    )
    public_url: Optional[str] = Field(
        default=None,
        description="Override URL for external access (e.g. reverse-proxy or CDN endpoint)",
    )
    external_service: bool = Field(
        default=False, description="True when the service is outside the Docker Compose network"
    )

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

    @property
    def port(self) -> int:
        return self.external_port


class FastAPIConfig(ServiceConfig):
    """FastAPI backend server configuration."""

    service_name: str = Field(default="depictio-backend")
    service_port: int = Field(default=8058)
    external_port: int = Field(default=8058)
    host: str = Field(default="0.0.0.0", description="Bind address for the FastAPI server")
    workers: int = Field(default=4, description="Number of Gunicorn worker processes")
    ssl: bool = Field(default=False, description="Enable SSL/TLS")
    logging_level: str = Field(
        default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    cors_allowed_origins: list[str] | str = Field(
        default_factory=list,
        description=(
            "Allowed CORS origins for the API. Set via DEPICTIO_FASTAPI_CORS_ALLOWED_ORIGINS "
            "as a comma-separated list (e.g. 'https://app.example.com,https://example.com'). "
            "An empty list disables credentialed cross-origin requests. The wildcard '*' is "
            "rejected when combined with credentialed CORS — supply explicit origins instead."
        ),
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Whether the CORS layer attaches credentials (cookies / Authorization).",
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_FASTAPI_")

    @model_validator(mode="after")
    def _normalise_cors_origins(self) -> "FastAPIConfig":
        # Pydantic-settings parses lists from env via JSON by default; accept the
        # friendlier comma-separated form so deployments can set
        # DEPICTIO_FASTAPI_CORS_ALLOWED_ORIGINS=https://a,https://b
        if isinstance(self.cors_allowed_origins, str):
            object.__setattr__(
                self,
                "cors_allowed_origins",
                [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()],
            )
        return self


class ViewerConfig(ServiceConfig):
    """Viewer frontend server configuration."""

    service_name: str = Field(default="depictio-viewer")
    service_port: int = Field(default=80)
    external_port: int = Field(default=5080)
    host: str = Field(default="0.0.0.0", description="Bind address for the viewer server")
    workers: int = Field(default=4, description="Number of Gunicorn worker processes")
    debug: bool = Field(default=True, description="Enable debug mode with hot reload")
    auto_generate_figures: bool = Field(
        default=False, description="Enable automatic figure generation in UI mode"
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_VIEWER_")


class MongoDBConfig(ServiceConfig):
    """MongoDB database connection configuration."""

    service_name: str = Field(default="mongo")
    service_port: int = Field(default=27018)
    external_port: int = Field(default=27018)
    db_name: str = Field(default="depictioDB", description="MongoDB database name")
    wipe: bool = Field(
        default=False, description="Wipe the database on startup (destructive — development only)"
    )
    username: str | None = Field(
        default=None, description="MongoDB username (operator-managed RS auth)"
    )
    password: SecretStr | None = Field(
        default=None, description="MongoDB password (operator-managed RS auth)"
    )
    replica_set: str | None = Field(default=None, description="MongoDB replica set name, e.g. rs0")
    auth_source: str = Field(default="admin", description="MongoDB authentication source database")

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MONGODB_")

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
        multiqc_collection: str = Field(default="multiqc")
        multiqc_prerender_collection: str = Field(default="multiqc_prerender")
        task_events_collection: str = Field(default="task_events")
        ingestion_runs_collection: str = Field(default="ingestion_runs")
        app_logs_collection: str = Field(default="app_logs")
        test_collection: str = Field(default="test")

    collections: Collections = Field(default_factory=Collections)


class S3DepictioCLIConfig(ServiceConfig):
    """S3/MinIO object storage configuration."""

    service_name: str = Field(default="minio")
    service_port: int = Field(default=9000)
    external_port: int = Field(default=9000)
    root_user: str = Field(
        default="minio",
        description="MinIO/S3 root access key (not a secret on its own).",
    )
    root_password: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "MinIO/S3 root secret key. REQUIRED in server context — set via "
            "DEPICTIO_MINIO_ROOT_PASSWORD. The server refuses to start when this is unset, "
            "shorter than 8 characters, or matches a well-known default."
        ),
    )
    bucket: str = Field(
        default="depictio-bucket", description="Default S3 bucket name for Depictio data"
    )
    verify_tls: bool = Field(
        default=True,
        description=(
            "Verify TLS certificates when talking to S3/MinIO. Only set to false for local "
            "development against self-signed dev MinIO instances."
        ),
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MINIO_")

    @property
    def endpoint_url(self) -> str:
        """Returns URL for Polars and other S3 clients."""
        return self.url

    @property
    def host(self) -> str:
        return self.external_host

    # Aliases for S3 compatibility
    @property
    def aws_access_key_id(self) -> str:
        return self.root_user

    @property
    def aws_secret_access_key(self) -> str:
        # Single chokepoint that unwraps the secret for boto3/polars callers so
        # tokens never appear in `repr(settings)` / `model_dump()` output.
        # Tolerates plain-str values: direct attribute assignment (tests, legacy
        # callers) bypasses pydantic coercion, leaving a raw str in the field.
        pw = self.root_password
        return pw.get_secret_value() if isinstance(pw, SecretStr) else pw


class AuthConfig(BaseSettings):
    """Authentication and authorisation configuration."""

    keys_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent.parent / "keys",
        description="Directory for JWT public/private key files",
    )
    keys_algorithm: Literal["RS256", "RS512", "ES256", "SHA256"] = Field(
        default="RS256", description="JWT signing algorithm"
    )
    cli_config_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent.parent / ".depictio",
        description="Directory for CLI configuration files (admin token, etc.)",
    )
    internal_api_key_env: Optional[str] = Field(
        default=None,
        description="Internal API key for service-to-service communication (auto-generated if unset)",
    )
    unauthenticated_mode: bool = Field(default=False, description="Enable unauthenticated mode")
    single_user_mode: bool = Field(
        default=False,
        description="Enable single-user mode for personal/self-hosted instances. "
        "Grants admin privileges to the anonymous user for full functionality without authentication.",
    )
    public_mode: bool = Field(
        default=False,
        description="Enable public mode for public Depictio instances with sign-in modal",
        validation_alias=AliasChoices("public_mode", "unauthenticated_mode"),
    )
    demo_mode: bool = Field(
        default=False,
        description="Enable demo mode with guided tour tooltips for first-time users. "
        "Extends public mode with interactive onboarding hints.",
    )
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

    # Google OAuth
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

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)

        import os

        # Manually read environment variables if not set
        # This is needed because Pydantic v2 nested BaseSettings don't automatically
        # read environment variables when instantiated via default_factory
        if self.internal_api_key_env is None:
            self.internal_api_key_env = os.getenv("DEPICTIO_AUTH_INTERNAL_API_KEY")

        # Read auth mode environment variables
        env_public_mode = os.getenv("DEPICTIO_AUTH_PUBLIC_MODE", "").lower()
        if env_public_mode in ("true", "1", "yes"):
            object.__setattr__(self, "public_mode", True)

        env_single_user_mode = os.getenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "").lower()
        if env_single_user_mode in ("true", "1", "yes"):
            object.__setattr__(self, "single_user_mode", True)

        env_unauthenticated_mode = os.getenv("DEPICTIO_AUTH_UNAUTHENTICATED_MODE", "").lower()
        if env_unauthenticated_mode in ("true", "1", "yes"):
            object.__setattr__(self, "unauthenticated_mode", True)

        env_demo_mode = os.getenv("DEPICTIO_AUTH_DEMO_MODE", "").lower()
        if env_demo_mode in ("true", "1", "yes"):
            object.__setattr__(self, "demo_mode", True)

    @computed_field
    @property
    def is_single_user_mode(self) -> bool:
        """Returns True if single-user mode is enabled.

        Single-user mode provides full admin functionality for personal instances.
        """
        return self.single_user_mode

    @computed_field
    @property
    def is_public_mode(self) -> bool:
        """Returns True if public mode is enabled.

        Public mode allows anonymous access with optional sign-in for interactive features.
        """
        return self.public_mode or self.unauthenticated_mode

    @computed_field
    @property
    def is_demo_mode(self) -> bool:
        """Returns True if demo mode is enabled.

        Demo mode extends public mode with guided tour tooltips for first-time users.
        """
        return self.demo_mode

    @computed_field
    @property
    def requires_anonymous_user(self) -> bool:
        """Returns True if any mode requiring anonymous user is enabled."""
        return self.is_single_user_mode or self.is_public_mode

    @computed_field
    @property
    def internal_api_key(self) -> str:
        """
        Get the internal API key using the existing key_utils_base functions.
        This maintains consistency and avoids code duplication.
        """
        if self.internal_api_key_env:
            return self.internal_api_key_env

        from depictio.api.v1.key_utils_base import _load_or_generate_api_internal_key

        return _load_or_generate_api_internal_key(
            keys_dir=self.keys_dir,
            algorithm=self.keys_algorithm,
        )


class AuthBootstrapConfig(BaseSettings):
    """First-boot admin (and optional CI test user) seeding.

    Replaces the legacy ``initial_users.yaml`` file. On startup the bootstrap
    creates the admin user *only* when no admin exists in MongoDB; on
    subsequent boots it is a no-op so operator-set passwords survive
    container restarts and Helm wipe-jobs.
    """

    admin_email: str = Field(
        default="",
        description=(
            "Email address used to seed the initial admin. REQUIRED in server context "
            "when no admin yet exists in MongoDB. Set via DEPICTIO_BOOTSTRAP_ADMIN_EMAIL."
        ),
    )
    admin_password: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Password for the bootstrap admin. REQUIRED, ≥8 characters. "
            "Set via DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD."
        ),
    )

    # Optional CI / dev test user. Off by default; CI sets the flag to true and
    # the existing fixture credentials keep working so the Cypress + workflow
    # tests are zero-touch.
    seed_test_user: bool = Field(
        default=False,
        description=(
            "When true, also seed a non-admin user for CI/Cypress fixtures. Disabled by "
            "default — production deployments must leave this off."
        ),
    )
    test_user_email: str = Field(
        default="test_user@example.com",
        description="Email for the seeded CI test user (only consulted when seed_test_user=true).",
    )
    test_user_password: SecretStr = Field(
        default=SecretStr("test_pwd"),
        description=(
            "Password for the seeded CI test user. Only used when seed_test_user=true. "
            "Override via DEPICTIO_BOOTSTRAP_TEST_USER_PASSWORD."
        ),
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_BOOTSTRAP_", case_sensitive=False)


# ── Infrastructure ────────────────────────────────────────────────────────────


class LoggingConfig(BaseSettings):
    """Application logging configuration."""

    verbosity_level: str = Field(
        default="ERROR", description="Log verbosity level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_LOGGING_")


class CacheConfig(BaseSettings):
    """Redis cache configuration settings."""

    # Redis connection settings
    redis_host: str = Field(default="redis", description="Redis server hostname")
    redis_port: int = Field(default=6379, description="Redis server port")
    redis_password: str | None = Field(default=None, description="Redis password")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_ssl: bool = Field(default=False, description="Use SSL for Redis connection")

    # Cache behavior settings
    enable_redis_cache: bool = Field(
        default=True, description="Enable Redis caching for DataFrames"
    )
    fallback_to_memory: bool = Field(
        default=True, description="Fallback to in-memory cache if Redis fails"
    )

    # Cache expiration settings
    default_ttl: int = Field(default=3600, description="Default cache TTL in seconds (1 hour)")
    dataframe_ttl: int = Field(
        default=1800, description="DataFrame cache TTL in seconds (30 minutes)"
    )

    # Cache limits
    max_dataframe_size_mb: int = Field(
        default=100, description="Maximum DataFrame size to cache (MB)"
    )
    redis_max_memory_mb: int = Field(default=1024, description="Redis max memory limit (MB)")

    # Cache key settings
    cache_key_prefix: str = Field(default="depictio:df:", description="Prefix for cache keys")
    cache_version: str = Field(default="v1", description="Cache version for key namespacing")

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_CACHE_")


class CeleryConfig(BaseSettings):
    """Celery task queue configuration for background processing."""

    # Redis broker settings (uses same Redis as cache but different DB)
    broker_host: str = Field(default="redis", description="Redis broker hostname")
    broker_port: int = Field(default=6379, description="Redis broker port")
    broker_password: Optional[str] = Field(default=None, description="Redis broker password")
    broker_db: int = Field(default=1, description="Redis database for Celery broker")

    # Result backend settings
    result_backend_host: str = Field(default="redis", description="Redis result backend hostname")
    result_backend_port: int = Field(default=6379, description="Redis result backend port")
    result_backend_password: Optional[str] = Field(
        default=None, description="Redis result backend password"
    )
    result_backend_db: int = Field(default=2, description="Redis database for Celery results")

    # Worker settings
    # NOTE: these two fields document the intended worker topology but are NOT
    # currently wired into worker startup — ``docker-images/run_celery_worker.sh``
    # passes ``--concurrency=$DEPICTIO_CELERY_WORKERS`` and no ``--pool`` (so the
    # worker runs Celery's default ``prefork``). Defaults are kept aligned with
    # that reality; raise throughput via ``DEPICTIO_CELERY_WORKERS``.
    worker_concurrency: int = Field(default=4, description="Number of concurrent worker processes")
    worker_pool: str = Field(
        default="prefork", description="Worker pool type (prefork, threads, processes)"
    )
    worker_prefetch_multiplier: int = Field(default=1, description="Worker prefetch multiplier")
    worker_max_tasks_per_child: int = Field(
        default=50, description="Max tasks per worker before restart"
    )

    # Task settings
    task_soft_time_limit: int = Field(
        default=300, description="Task soft time limit in seconds (5min)"
    )
    task_time_limit: int = Field(default=600, description="Task hard time limit in seconds (10min)")
    result_expires: int = Field(default=3600, description="Task result expiration in seconds (1hr)")

    # Queue settings
    default_queue: str = Field(default="dashboard_tasks", description="Default task queue name")

    # Monitoring settings
    worker_send_task_events: bool = Field(default=True, description="Enable task event monitoring")
    task_send_sent_event: bool = Field(default=True, description="Send task sent events")

    # FastAPI offload settings — wraps preview/render endpoints with a
    # non-blocking poll on a Celery task so heavy Polars/Plotly work runs on
    # the worker process instead of pinning an API worker.
    offload_preview: bool = Field(
        default=True,
        description="Always offload component-design preview endpoints (/figure/preview etc.) to Celery",
    )
    offload_rendering: bool = Field(
        default=False,
        description=(
            "Force-offload ALL dashboard render endpoints (/dashboards/render_*) to "
            "Celery regardless of cost. Off by default: renders offload adaptively by "
            "size/type (see offload_size_threshold_bytes) so cheap interactive figures "
            "stay inline and skip the broker + result-backend round-trip."
        ),
    )
    offload_size_threshold_bytes: int = Field(
        default=50 * 1024 * 1024,
        description=(
            "Source Delta-table size (bytes) at/above which a dashboard render is "
            "offloaded to Celery even when offload_rendering is off; below it renders "
            "run inline. Coarse proxy for build cost pending the #4 render benchmark. "
            "Set to 0 to disable size-based offload."
        ),
    )
    offload_timeout_seconds: float = Field(
        default=30.0,
        description="Per-request Celery offload timeout (seconds) before HTTP 504",
    )

    @computed_field
    @property
    def _redis_password(self) -> str:
        """Get Redis password from environment, fallback to cache password or default."""
        if self.broker_password:
            return self.broker_password
        import os

        redis_password = os.getenv("REDIS_PASSWORD", "")
        return redis_password

    @computed_field
    @property
    def broker_url(self) -> str:
        """Construct Redis broker URL."""
        password = self._redis_password
        if password and password != "":
            return f"redis://:{password}@{self.broker_host}:{self.broker_port}/{self.broker_db}"
        return f"redis://{self.broker_host}:{self.broker_port}/{self.broker_db}"

    @computed_field
    @property
    def result_backend_url(self) -> str:
        """Construct Redis result backend URL."""
        result_password = self.result_backend_password or self._redis_password
        if result_password and result_password != "":
            return f"redis://:{result_password}@{self.result_backend_host}:{self.result_backend_port}/{self.result_backend_db}"
        return f"redis://{self.result_backend_host}:{self.result_backend_port}/{self.result_backend_db}"

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_CELERY_")


class S3CacheConfig(BaseSettings):
    """S3 file caching configuration for MultiQC and other S3 operations.

    The cache directory stores downloaded S3 files locally to avoid repeated downloads.
    Default location is ~/.depictio/s3_cache (persistent across restarts).

    Environment variable: DEPICTIO_S3_CACHE_DIR
    Example: export DEPICTIO_S3_CACHE_DIR=/data/depictio_s3_cache

    Note: The previous default /tmp/depictio_s3_cache was ephemeral and caused
    repeated downloads after system restarts.
    """

    cache_dir: str = Field(
        default="~/.depictio/s3_cache",
        description="Local directory for S3 file cache. Use DEPICTIO_S3_CACHE_DIR to override.",
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_S3_")


class MultiQCPrerenderConfig(BaseSettings):
    """Disk-persistent storage for pre-rendered MultiQC Plotly figures.

    Phase 2 of the MultiQC caching story: the Celery build task writes each
    rendered figure as a gzipped JSON dict under
    ``<prerender_dir>/<dc_id>/<sha>.json.gz``. The render endpoint reads from
    here on Redis miss so a FLUSHALL / container restart never re-pays the
    76s parse+build cost.

    Environment variable: DEPICTIO_MULTIQC_PRERENDER_DIR
    Example (compose): DEPICTIO_MULTIQC_PRERENDER_DIR=/app/multiqc_prerender
    """

    prerender_dir: str = Field(
        default="~/.depictio/multiqc_prerender",
        description=(
            "Local directory for pre-rendered MultiQC figures. Use "
            "DEPICTIO_MULTIQC_PRERENDER_DIR to override (the dev compose mounts "
            "./${DATA_DIR}/multiqc_prerender to /app/multiqc_prerender)."
        ),
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MULTIQC_")


# ── Optional Features ─────────────────────────────────────────────────────────


class JBrowseConfig(BaseSettings):
    """JBrowse genomics viewer integration configuration."""

    enabled: bool = Field(default=False, description="Enable JBrowse genomics viewer integration")

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_JBROWSE_")


class BackupConfig(BaseSettings):
    """Backup and restore configuration settings."""

    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent)
    backup_dir: str = Field(default="backups")
    s3_backup_strategy: str = Field(
        default="s3_to_s3",
        description="Strategy for S3 data backup: 's3_to_s3', 'local', or 'both'",
    )
    s3_local_backup_dir: str = Field(default="backups/s3_data_backups")
    backup_s3_enabled: bool = Field(default=False, description="Enable separate backup S3 bucket")
    backup_s3_bucket: str = Field(default="depictio-backups", description="Backup S3 bucket name")
    backup_s3_endpoint_url: Optional[str] = Field(
        default=None, description="Backup S3 endpoint URL"
    )
    backup_s3_access_key: Optional[str] = Field(default=None, description="Backup S3 access key")
    backup_s3_secret_key: Optional[str] = Field(default=None, description="Backup S3 secret key")
    backup_s3_region: str = Field(default="us-east-1", description="Backup S3 region")
    compress_local_backups: bool = Field(default=True, description="Compress local S3 data backups")
    backup_file_retention_days: int = Field(default=30, description="Days to retain backup files")
    migration_allowed_s3_endpoints: list[str] | str = Field(
        default_factory=list,
        description=(
            "Opt-in allowlist of external S3/MinIO endpoint URLs that project migration "
            "(/export-project) is permitted to push data to. Set via "
            "DEPICTIO_BACKUP_MIGRATION_ALLOWED_S3_ENDPOINTS as a comma-separated list "
            "(e.g. 'https://s3.partner.example.com,https://minio.other.example.com:9000'). "
            "Empty by default — when empty, ALL caller-supplied external endpoints are "
            "rejected and only the deployment's own configured MinIO endpoint is allowed "
            "(self-migration). Each entry is matched exactly on normalized scheme+host+port. "
            "This is a server-side SSRF / data-exfiltration guard: only add operator-vetted "
            "endpoints you trust the server to connect to."
        ),
    )

    @model_validator(mode="after")
    def _normalise_migration_endpoints(self) -> "BackupConfig":
        # Accept the friendlier comma-separated form for the env var in addition to
        # pydantic-settings' default JSON list parsing, mirroring cors_allowed_origins.
        if isinstance(self.migration_allowed_s3_endpoints, str):
            object.__setattr__(
                self,
                "migration_allowed_s3_endpoints",
                [e.strip() for e in self.migration_allowed_s3_endpoints.split(",") if e.strip()],
            )
        return self

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


class EventsConfig(BaseSettings):
    """Configuration for real-time event system (WebSocket notifications).

    Enables automatic dashboard updates when backend data changes.
    Supports MongoDB change streams for data_collection updates.
    """

    enabled: bool = Field(default=False, description="Enable real-time event system")
    redis_host: str = Field(default="redis", description="Redis server hostname for pub/sub")
    redis_port: int = Field(default=6379, description="Redis server port")
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    redis_db: int = Field(
        default=3, description="Redis database number (separate from cache=0, celery=1,2)"
    )
    mongodb_change_streams_enabled: bool = Field(
        default=True, description="Enable MongoDB change streams for data_collections"
    )
    ws_heartbeat_interval: int = Field(
        default=30, description="WebSocket heartbeat/ping interval in seconds"
    )
    ws_connection_timeout: int = Field(
        default=60, description="WebSocket connection timeout in seconds"
    )
    debounce_ms: int = Field(
        default=1000, description="Debounce interval in milliseconds for rapid updates"
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_EVENTS_")

    @computed_field
    @property
    def redis_url(self) -> str:
        """Construct Redis URL for pub/sub."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


class MonitoringConfig(BaseSettings):
    """Configuration for the admin "Log & Task" monitoring feature.

    Backs the admin-only monitoring tab that surfaces Celery task history, CLI
    ingestion runs, and recent application logs. Persistence is a durable
    MongoDB ledger; live updates ride the real-time events WebSocket when
    ``settings.events.enabled`` is also true.
    """

    enabled: bool = Field(default=True, description="Enable the admin monitoring feature")
    retention_days: int = Field(
        default=14, description="TTL (days) for task_events records before automatic expiry"
    )
    app_log_min_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="WARNING", description="Minimum level captured into the app_logs collection"
    )
    app_log_capped_mb: int = Field(
        default=64, description="Size cap (MB) of the capped app_logs collection"
    )
    live_updates: bool = Field(
        default=True,
        description="Push live task/ingestion status changes over the events WebSocket "
        "(only active when events.enabled is also true)",
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MONITORING_")


class DashboardYAMLConfig(BaseSettings):
    """Configuration for YAML-based dashboard management.

    Enables file-based dashboard editing where users can read/write YAML files
    directly from a designated directory for version control and IaC workflows.
    """

    # DEPRECATED: YAML system is being phased out in favor of JSON-based API (see YAML_MONGODB_ANALYSIS.md)
    enabled: bool = Field(
        default=False, description="Enable YAML-based dashboard management (DEPRECATED)"
    )
    local_dir: Path = Field(
        default_factory=lambda: (
            Path(__file__).parent.parent.parent.parent.parent / "dashboards" / "local"
        ),
        description="Directory for instance-specific dashboard YAML files (auto-synced)",
    )
    templates_dir: Path = Field(
        default_factory=lambda: (
            Path(__file__).parent.parent.parent.parent.parent / "dashboards" / "templates"
        ),
        description="Directory for template dashboard YAML files (version control)",
    )
    base_dir: Path | None = Field(
        default=None,
        description="DEPRECATED: Use local_dir instead. Base directory for dashboard YAML files",
    )
    organize_by_project: bool = Field(
        default=True,
        description="Organize YAML files in subdirectories by project name",
    )
    use_dashboard_title: bool = Field(
        default=True,
        description="Use dashboard title in filename (vs just ID)",
    )
    include_export_metadata: bool = Field(
        default=True,
        description="Include export timestamp and version in YAML files",
    )
    compact_mode: bool = Field(
        default=True,
        description="Use compact YAML format with references (75-80% smaller files)",
    )
    mvp_mode: bool = Field(
        default=True,
        description="Use MVP minimal YAML format (60-80 lines, human-readable IDs, no layout)",
    )
    regenerate_stats: bool = Field(
        default=True,
        description="Regenerate column statistics on import instead of storing in YAML",
    )
    auto_layout: bool = Field(
        default=False,
        description="Auto-generate component layout on import if missing",
    )
    auto_export_on_save: bool = Field(
        default=False,
        description="Automatically export to YAML when dashboard is saved (DEPRECATED)",
    )
    auto_import_on_change: bool = Field(
        default=False,
        description="Automatically import from YAML when files change (requires watcher) (DEPRECATED)",
    )
    watcher_debounce_seconds: float = Field(
        default=2.0,
        description="Seconds to wait after file change before syncing",
    )
    watch_local_dir: bool = Field(
        default=False,
        description="Watch and auto-sync local dashboards directory (DEPRECATED)",
    )
    watch_templates_dir: bool = Field(
        default=False,
        description="Watch and auto-sync templates directory (useful for template development)",
    )
    enable_validation: bool = Field(
        default=True,
        description="Enable validation gate before syncing YAML to MongoDB",
    )
    block_on_validation_errors: bool = Field(
        default=True,
        description="Block sync if validation fails (set False to only warn)",
    )
    validate_column_names: bool = Field(
        default=True,
        description="Validate that column names exist in data collection schema",
    )
    validate_component_types: bool = Field(
        default=True,
        description="Validate chart types, aggregation functions, and filter types",
    )

    model_config = SettingsConfigDict(
        env_prefix="DEPICTIO_DASHBOARD_YAML_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @computed_field
    @property
    def yaml_dir_path(self) -> str:
        """Get absolute YAML directory path (defaults to local_dir)."""
        if self.base_dir is not None:
            return str(self.base_dir.resolve())
        return str(self.local_dir.resolve())

    @computed_field
    @property
    def templates_path(self) -> str:
        """Get absolute templates directory path."""
        return str(self.templates_dir.resolve())


# ── Observability & Development ───────────────────────────────────────────────


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
    screenshot_navigation_timeout: int = Field(default=60000)  # 60s for navigation
    screenshot_content_wait: int = Field(default=30000)  # 30s for content
    screenshot_stabilization_wait: int = Field(default=10000)  # 10s for stability
    screenshot_capture_timeout: int = Field(default=120000)  # 120s for actual screenshot capture
    screenshot_api_timeout: int = Field(default=600)  # 10 minutes for complete screenshot API call

    # Service readiness check settings
    service_readiness_retries: int = Field(default=5)
    service_readiness_delay: int = Field(default=3)
    service_readiness_timeout: int = Field(default=10)

    # DNS and network performance settings
    dns_cache_ttl: int = Field(default=300)  # 5 minutes
    connection_pool_size: int = Field(
        default=25, description="HTTP connection pool size for multi-worker environments"
    )
    max_keepalive_connections: int = Field(
        default=20, description="Max persistent HTTP connections (increased for 4 workers)"
    )

    # Loading spinner optimization settings
    disable_loading_spinners: bool = Field(
        default=True, description="Disable all loading spinners for maximum performance"
    )

    # Animation optimization settings
    disable_animations: bool = Field(
        default=True, description="Disable SVG and CSS animations for maximum performance"
    )
    disable_theme_animations: bool = Field(
        default=True, description="Disable theme CSS injection and complex theme operations"
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_PERFORMANCE_")


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


class ProfilingConfig(BaseSettings):
    """Configuration for application profiling."""

    enabled: bool = Field(default=False, description="Enable application profiling")
    profile_dir: str = Field(default="./prof_files", description="Directory to save profile files")
    sort_by: str = Field(default="cumtime,tottime", description="Profile sorting criteria")
    restrictions: int = Field(default=50, description="Number of top functions to show in reports")
    memory_profiling: bool = Field(default=False, description="Enable memory usage profiling")

    # Werkzeug-specific options
    werkzeug_enabled: bool = Field(default=True, description="Enable Werkzeug request profiling")
    werkzeug_stream: bool = Field(default=False, description="Stream profiling output to terminal")
    werkzeug_safe_mode: bool = Field(
        default=True, description="Enable safe mode to prevent profiler conflicts"
    )

    # Callback profiling options
    profile_callbacks: bool = Field(
        default=False, description="Enable automatic callback profiling"
    )
    profile_slow_callbacks_only: bool = Field(
        default=True, description="Only profile callbacks slower than threshold"
    )
    slow_callback_threshold: float = Field(
        default=0.1, description="Threshold in seconds for slow callbacks"
    )

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_PROFILING_")

    @computed_field
    @property
    def sort_criteria(self) -> tuple[str, ...]:
        """Parse sort criteria string into tuple."""
        return tuple(s.strip() for s in self.sort_by.split(","))

    @computed_field
    @property
    def profile_path(self) -> Path:
        """Get resolved profile directory path."""
        return Path(self.profile_dir).resolve()


# ── Root ──────────────────────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Root application settings, composed of all subsystem configurations."""

    context: str = Field(
        default="server", description="Runtime context: 'server' (API/worker) or 'client' (CLI)"
    )

    # Core services
    fastapi: FastAPIConfig = Field(default_factory=FastAPIConfig)
    viewer: ViewerConfig = Field(default_factory=ViewerConfig)
    mongodb: MongoDBConfig = Field(default_factory=MongoDBConfig)
    minio: S3DepictioCLIConfig = Field(default_factory=S3DepictioCLIConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    bootstrap: AuthBootstrapConfig = Field(default_factory=AuthBootstrapConfig)

    # Infrastructure
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    s3_cache: S3CacheConfig = Field(default_factory=S3CacheConfig)
    multiqc_prerender: MultiQCPrerenderConfig = Field(default_factory=MultiQCPrerenderConfig)

    # Optional features
    jbrowse: JBrowseConfig = Field(default_factory=JBrowseConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    dashboard_yaml: DashboardYAMLConfig = Field(default_factory=DashboardYAMLConfig)

    # Observability & development
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    google_analytics: GoogleAnalyticsConfig = Field(default_factory=GoogleAnalyticsConfig)
    profiling: ProfilingConfig = Field(default_factory=ProfilingConfig)

    disable_example_dashboards: bool = Field(
        default=False,
        description=(
            "Skip seeding the bundled reference projects and dashboards "
            "(iris, penguins, advanced visualisations, ampliseq, viralrecon) "
            "on API startup. Useful for clean-slate deployments where the "
            "demo content is not desired."
        ),
    )

    seed_projects: str = Field(
        default="",
        description=(
            "Comma-separated allowlist of reference projects to seed on API "
            "startup, e.g. 'iris' or 'iris,penguins'. Empty (the default) seeds "
            "all of them. Ignored when DEPICTIO_DISABLE_EXAMPLE_DASHBOARDS is "
            "true (that takes precedence and seeds nothing). Valid names: "
            "iris, penguins, ampliseq, advanced_viz_showcase, viralrecon."
        ),
    )

    enable_dev_endpoints: bool = Field(
        default=False,
        description=(
            "Expose destructive/test-only dev endpoints (utils/drop_S3_content, "
            "utils/drop_all_collections, events/test-trigger). Off by default so "
            "they 404 in production even for admins; enable only for local "
            "development and integration scripts."
        ),
    )

    model_config = SettingsConfigDict(
        env_prefix="DEPICTIO_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields in .env that aren't in the model
    )

    @property
    def seed_projects_filter(self) -> set[str] | None:
        """Allowlist of reference projects to seed, or None to seed all.

        Parses the ``DEPICTIO_SEED_PROJECTS`` CSV into a set. An empty/blank
        value yields ``None``, which callers treat as "seed everything".
        """
        names = {name.strip() for name in self.seed_projects.split(",") if name.strip()}
        return names or None

    @model_validator(mode="after")
    def _enforce_server_secrets(self) -> "Settings":
        """Fail fast at startup if server-context secrets are missing or weak.

        Skipped in client (CLI) context — the CLI talks to a remote API and
        doesn't hold the MinIO root password or seed admins itself.
        """
        if self.context != "server":
            return self

        # Single-user mode is for local development — no secret enforcement.
        if self.auth.is_single_user_mode:
            return self

        errors: list[str] = []

        # MinIO root password is consumed by API + worker, so it must always
        # be set on a server boot regardless of single-user / public mode.
        minio_pw = self.minio.root_password.get_secret_value()
        if minio_pw.lower() in _WEAK_PASSWORDS_MINIO:
            errors.append(
                "DEPICTIO_MINIO_ROOT_PASSWORD is unset or matches a known-default value. "
                "Set it to a strong secret before starting the server."
            )
        elif len(minio_pw) < _MIN_SECRET_LEN:
            errors.append(
                f"DEPICTIO_MINIO_ROOT_PASSWORD must be at least {_MIN_SECRET_LEN} characters."
            )

        # Bootstrap admin credentials. Empty values are allowed at validator
        # time — the admin may already exist in MongoDB from a prior boot, in
        # which case the bootstrap is a no-op. ``db_init`` does the final
        # "no admin in DB + no env" check there because only that layer can
        # talk to the database.
        admin_pw = self.bootstrap.admin_password.get_secret_value()
        if admin_pw:
            if admin_pw.lower() in _WEAK_PASSWORDS:
                errors.append(
                    "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD matches a known-default value; "
                    "choose a stronger secret."
                )
            elif len(admin_pw) < _MIN_SECRET_LEN:
                errors.append(
                    "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD must be at least "
                    f"{_MIN_SECRET_LEN} characters."
                )

        if errors:
            raise ValueError("Insecure configuration:\n  - " + "\n  - ".join(errors))

        return self
