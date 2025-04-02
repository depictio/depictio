import os
from typing import Dict, Union
from pydantic import AliasChoices, ConfigDict, Field
from pydantic_settings import BaseSettings
from depictio_models.models.s3 import MinioConfig


class Collections(BaseSettings):
    """Collections names in MongoDB."""

    projects_collection: str = "projects"
    data_collection: str = "data_collections"
    workflow_collection: str = "workflows"
    runs_collection: str = "runs"
    files_collection: str = "files"
    users_collection: str = "users"
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
    port: int = Field(default=27018, json_schema_extra={"env": "DEPICTIO_MONGODB_PORT"})
    db_name: str = Field(
        default="depictioDB", json_schema_extra={"env": "DEPICTIO_MONGODB_NAME"}
    )
    wipe: bool = Field(
        default=False, json_schema_extra={"env": "DEPICTIO_MONGODB_WIPE"}
    )
    model_config = ConfigDict(env_prefix="DEPICTIO_MONGODB_")

    # class Config:
    #     env_prefix = 'DEPICTIO_MONGO_'


class FastAPIConfig(BaseSettings):
    """Backend configuration."""

    host: str = "0.0.0.0"
    service_name: str = "depictio_backend"
    port: int = Field(default=8058, json_schema_extra={"env": "DEPICTIO_FASTAPI_PORT"})
    logging_level: str = "INFO"
    model_config = ConfigDict(env_prefix="DEPICTIO_FASTAPI_")
    workers: int = Field(
        default=1, json_schema_extra={"env": "DEPICTIO_FASTAPI_WORKERS"}
    )
    # class Config:
    #     env_prefix = 'DEPICTIO_FASTAPI_'


class DashConfig(BaseSettings):
    """Frontend configuration."""

    debug: bool = True
    host: str = "0.0.0.0"
    service_name: str = "depictio_frontend"
    workers: int = Field(default=1, json_schema_extra={"env": "DEPICTIO_DASH_WORKERS"})
    port: int = Field(default=5080, json_schema_extra={"env": "DEPICTIO_DASH_PORT"})
    model_config = ConfigDict(env_prefix="DEPICTIO_DASH_")
    # class Config:
    #     env_prefix = 'DEPICTIO_DASH_'


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
    model_config = ConfigDict(env_prefix="DEPICTIO_JBROWSE_")
    # class Config:
    #     env_prefix = 'DEPICTIO_JBROWSE_'


class Auth(BaseSettings):
    """Authentication configuration."""

    tmp_token: str = Field(default="eyJhb...")
    keys_dir: str = Field(
        default="depictio/keys", json_schema_extra={"env": "DEPICTIO_AUTH_KEYS_DIR"}
    )
    keys_algorithm: str = "RS256"
    cli_config_dir: str = Field(
        default="depictio/.depictio",
        json_schema_extra={"env": "DEPICTIO_AUTH_CLI_CONFIG_DIR"},
    )
    model_config = ConfigDict(arbitrary_types_allowed=True, env_prefix="DEPICTIO_AUTH_")

    # class Config:
    #     env_prefix = 'DEPICTIO_AUTH_'
    # arbitrary_types_allowed = True


class Settings(BaseSettings):
    """Joint settings."""

    mongodb: MongoConfig = MongoConfig()
    # redis: RedisConfig = RedisConfig()
    # rabbitmq: RabbitMQConfig = RabbitMQConfig()
    fastapi: FastAPIConfig = FastAPIConfig()
    dash: DashConfig = DashConfig()
    minio: MinioConfig = MinioConfig()
    jbrowse: JbrowseConfig = JbrowseConfig()
    auth: Auth = Auth()
