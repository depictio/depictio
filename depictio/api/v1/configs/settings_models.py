from typing import Dict, Union

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from depictio.api.v1.key_utils import _load_or_generate_api_internal_key
from depictio.models.models.s3 import S3DepictioCLIConfig


class Collections(BaseSettings):
    """Collections names in MongoDB."""

    projects_collection: str = "projects"
    data_collection: str = "data_collections"
    workflow_collection: str = "workflows"
    runs_collection: str = "runs"
    files_collection: str = "files"
    users_collection: str = "users"
    tokens_collection: str = "tokens"
    groups_collection: str = "groups"
    deltatables_collection: str = "deltatables"
    jbrowse_collection: str = "jbrowse_collection"
    dashboards_collection: str = "dashboards"
    initialization_collection: str = "initialization"
    test_collection: str = "test"


class MongoConfig(BaseSettings):
    """MongoDB configuration."""

    collections: Collections = Collections()
    service_name: str = "mongo"
    port: int = Field(default=27018)
    db_name: str = Field(default="depictioDB")
    wipe: bool = Field(
        default=False,
    )
    model_config = SettingsConfigDict(env_prefix="DEPICTIO_MONGODB_")


class FastAPIConfig(BaseSettings):
    """Backend configuration."""

    host: str = "0.0.0.0"
    service_name: str = "depictio_backend"
    port: int = Field(default=8058)
    logging_level: str = "INFO"
    model_config = SettingsConfigDict(env_prefix="DEPICTIO_FASTAPI_")
    workers: int = Field(default=1)
    ssl: bool = Field(default=False)
    internal_api_key: str = Field(default_factory=_load_or_generate_api_internal_key)
    playwright_dev_mode: bool = Field(default=False)


class DashConfig(BaseSettings):
    """Frontend configuration."""

    debug: bool = True
    host: str = "0.0.0.0"
    service_name: str = "depictio_frontend"
    workers: int = Field(default=1)
    port: int = Field(default=5080)
    model_config = SettingsConfigDict(env_prefix="DEPICTIO_DASH_")


class JbrowseConfig(BaseSettings):
    """Jbrowse configuration."""

    enabled: bool = True
    instance: Dict[str, Union[str, int]] = {"host": "http://localhost", "port": 3000}
    watcher_plugin: Dict[str, Union[str, int]] = {
        "host": "http://localhost",
        "port": 9010,
    }
    data_dir: str = "/data"
    config_dir: str = "/jbrowse-watcher-plugin/sessions"
    model_config = SettingsConfigDict(env_prefix="DEPICTIO_JBROWSE_")


class Auth(BaseSettings):
    """Authentication configuration."""

    tmp_token: str = Field(default="eyJhb...")
    keys_dir: str = Field(
        default="depictio/keys",
    )
    keys_algorithm: str = "RS256"
    cli_config_dir: str = Field(
        default="depictio/.depictio",
    )
    model_config = SettingsConfigDict(
        arbitrary_types_allowed=True, env_prefix="DEPICTIO_AUTH_"
    )


class Settings(BaseSettings):
    """Joint settings."""

    mongodb: MongoConfig = MongoConfig()
    fastapi: FastAPIConfig = FastAPIConfig()
    dash: DashConfig = DashConfig()
    minio: S3DepictioCLIConfig = S3DepictioCLIConfig()
    jbrowse: JbrowseConfig = JbrowseConfig()
    auth: Auth = Auth()
