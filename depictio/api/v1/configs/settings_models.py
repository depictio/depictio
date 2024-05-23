from typing import Dict, Union
from pydantic import BaseSettings, Field

class Collections(BaseSettings):
    """Collections names in MongoDB."""
    data_collection: str = "data_collections"
    workflow_collection: str = "workflows"
    runs_collection: str = "runs"
    files_collection: str = "files"
    users_collection: str = "users"
    deltatables_collection: str = "deltatables"
    jbrowse_collection: str = "jbrowse_collection"
    dashboards_collection: str = "dashboards_collection"


class MongoConfig(BaseSettings):
    """MongoDB configuration."""
    service_name: str = "mongo"
    port: int = 27018
    db_name: str = "depictioDB"
    collections: Collections = Collections()
    class Config:
        env_prefix = 'MONGO_'


class RedisConfig(BaseSettings):
    """Redis configuration."""
    service_name: str = "redis"
    port: int = 6379
    db: int = 0
    cache_ttl: int = 300
    user_secret_key: str = Field(default="mysecretkey")
    class Config:
        env_prefix = 'REDIS_'


class RabbitMQConfig(BaseSettings):
    """RabbitMQ configuration."""
    service_name: str = "rabbitmq"
    port: int = 5672
    exchange: str = "direct"
    routing_key: str = Field(default="depictio_key")
    queue: str = "jbrowse_logs"
    class Config:
        env_prefix = 'RABBITMQ_'


class FastAPIConfig(BaseSettings):
    """Backend configuration."""
    host: str = "0.0.0.0"
    service_name: str = "depictio_backend"
    port: int = 8058
    class Config:
        env_prefix = 'DEPICTIO_BACKEND_'

class DashConfig(BaseSettings):
    """Frontend configuration."""
    host: str = "0.0.0.0"
    service_name: str = "depictio_frontend"
    port: int = 5080


class MinioConfig(BaseSettings):
    """Minio configuration."""
    internal_endpoint: str = "http://minio"
    external_endpoint: str = "http://localhost"
    port: int = 9000
    access_key: str = Field(default="minio")
    secret_key: str = Field(default="minio123")
    secure: bool = False
    bucket: str = "depictio-bucket"
    data_dir: str = "/depictio/minio_data"
    class Config:
        env_prefix = 'MINIO_'


class JbrowseConfig(BaseSettings):
    """Jbrowse configuration."""
    enabled: bool = True
    instance: Dict[str, Union[str, int]] = {'host': "http://localhost", 'port': 3000}
    watcher_plugin: Dict[str, Union[str, int]] = {'host': "http://localhost", 'port': 9010}
    data_dir: str = "/data"
    config_dir: str = "/jbrowse-watcher-plugin/sessions"
    class Config:
        env_prefix = 'JBROWSE_'


class Auth(BaseSettings):
    """Authentication configuration."""
    tmp_token: str = Field(default="eyJhb...")
    private_key: str = Field(default=None)
    public_key: str = Field(default=None)

    class Config:
        env_prefix = 'AUTH_'
        arbitrary_types_allowed = True


class Settings(BaseSettings):
    """Joint settings."""
    mongodb: MongoConfig = MongoConfig()
    redis: RedisConfig = RedisConfig()
    rabbitmq: RabbitMQConfig = RabbitMQConfig()
    fastapi: FastAPIConfig = FastAPIConfig()
    dash: DashConfig = DashConfig()
    minio: MinioConfig = MinioConfig()
    jbrowse: JbrowseConfig = JbrowseConfig()
    auth: Auth = Auth()
