import os
import secrets
import time
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
        self._cached_key: Optional[str] = None  # Internal cache, set after init

        # Manually read the environment variable if not set
        if self.internal_api_key_env is None:
            import os

            self.internal_api_key_env = os.getenv("DEPICTIO_AUTH_INTERNAL_API_KEY")

    @computed_field
    @property
    def internal_api_key(self) -> str:
        """
        Automatically generate and manage internal API key for container communication.

        The key is shared between backend and frontend containers via the shared volume.
        Backend generates the key if it doesn't exist, frontend reads the existing key.

        Priority:
        1. Environment variable DEPICTIO_AUTH_INTERNAL_API_KEY (if set)
        2. Cached key (avoid repeated file I/O)
        3. Existing key file in shared volume
        4. Generate new key (backend only) and save to shared volume
        5. Fallback to default (should not happen in normal operation)
        """
        context = os.getenv("DEPICTIO_CONTEXT", "server")
        print(f"[DEBUG] AuthConfig.internal_api_key called from context: {context}")

        # 1. Use environment variable if provided (highest priority)
        if self.internal_api_key_env:
            print("[DEBUG] Using internal API key from environment variable")
            return self.internal_api_key_env

        # 2. Return cached key if available
        if self._cached_key:
            print("[DEBUG] Using cached internal API key")
            return self._cached_key

        # 3. Check for existing key file in shared volume
        key_file = self.keys_dir / "internal_api_key.txt"
        print(f"[DEBUG] Checking for key file at: {key_file}")

        if key_file.exists():
            print("[DEBUG] Key file exists, attempting to read...")
            try:
                with open(key_file, "r") as f:
                    existing_key = f.read().strip()
                if existing_key:
                    print(f"[DEBUG] Successfully read key from file (length: {len(existing_key)})")
                    print(f"[DEBUG - WARNING TO REMOVE] Internal API key found: {existing_key}")
                    # Cache the key for future calls
                    self._cached_key = existing_key
                    return existing_key
                else:
                    print("[DEBUG] Key file is empty")
            except (IOError, OSError) as e:
                print(f"[DEBUG] Warning: Could not read internal API key file: {e}")
        else:
            print("[DEBUG] Key file does not exist")

        # 4. Generate new key (should only happen on backend/first startup)
        print(f"[DEBUG] Context is {context}, checking if should generate key...")

        if context in ["server", "API"]:  # Backend should generate the key
            print("[DEBUG] Backend context detected, attempting to generate new key...")
            try:
                # Ensure keys directory exists
                print(f"[DEBUG] Creating keys directory at: {self.keys_dir}")
                self.keys_dir.mkdir(parents=True, exist_ok=True)

                # Generate a secure random key
                new_key = secrets.token_urlsafe(32)  # 256-bit key, URL-safe
                print(f"[DEBUG] Generated new key (length: {len(new_key)})")

                # Save to shared file for frontend to read
                print(f"[DEBUG] Saving key to file: {key_file}")
                with open(key_file, "w") as f:
                    f.write(new_key)

                # Set appropriate permissions (readable by container user)
                os.chmod(key_file, 0o644)
                print("[DEBUG] Set file permissions to 644")

                print(f"[DEBUG] Generated new internal API key and saved to {key_file}")

                # Cache the key for future calls
                self._cached_key = new_key
                return new_key

            except (IOError, OSError) as e:
                print(f"[DEBUG] Error: Could not generate/save internal API key: {e}")
                print("[DEBUG] Falling back to default key - this may cause authentication issues")

        else:  # Frontend should wait for backend to generate key
            print(f"Warning: No internal API key found in {key_file}")
            print("Frontend waiting for backend to generate key...")

            # Retry mechanism: wait for backend to generate key
            max_retries = 10
            retry_delay = 2  # seconds

            for attempt in range(max_retries):
                time.sleep(retry_delay)

                if key_file.exists():
                    try:
                        with open(key_file, "r") as f:
                            existing_key = f.read().strip()
                        if existing_key:
                            print(f"Found internal API key after {attempt + 1} attempts")
                            # Cache the key for future calls
                            self._cached_key = existing_key
                            return existing_key
                    except (IOError, OSError):
                        pass  # Continue retrying

                print(f"Attempt {attempt + 1}/{max_retries}: Still waiting for internal API key...")

            print("Warning: Max retries exceeded, backend may not have started yet")

        # 4. Fallback to default (should not happen in normal operation)
        return "default-internal-key-fallback"


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
