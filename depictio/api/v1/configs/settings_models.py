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
    keys_dir: Path = Field(default=Path("./depictio/keys"))
    keys_algorithm: str = Field(default="RS256")
    cli_config_dir: Path = Field(default=Path("./depictio/.depictio"))
    internal_api_key_env: Optional[str] = Field(default=None)

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


class Settings(BaseSettings):
    context: str = Field(default="server")

    fastapi: FastAPIConfig = Field(default_factory=FastAPIConfig)
    dash: DashConfig = Field(default_factory=DashConfig)
    mongodb: MongoDBConfig = Field(default_factory=MongoDBConfig)
    minio: S3DepictioCLIConfig = Field(default_factory=S3DepictioCLIConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    jbrowse: JBrowseConfig = Field(default_factory=JBrowseConfig)

    model_config = SettingsConfigDict(env_prefix="DEPICTIO_")
