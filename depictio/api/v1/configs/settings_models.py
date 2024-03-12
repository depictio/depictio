
from typing import Dict, Union
from pydantic import BaseModel
import yaml


class Collections(BaseModel):
    data_collection: str
    workflow_collection: str
    runs_collection: str
    files_collection: str
    users_collection: str
    deltatables_collection: str


class MongoConfig(BaseModel):
    host: str
    port: int
    db_name: str
    collections: Collections

class RedisConfig(BaseModel):
    host: str
    port: int
    db: int
    cache_ttl: int
    user_secret_key: str

class FastAPIConfig(BaseModel):
    host: str
    port: int

class DashConfig(BaseModel):
    host: str
    port: int

class MinioConfig(BaseModel):
    endpoint: str
    port: int
    access_key: str
    secret_key: str
    secure: bool
    bucket: str
    data_dir: str


class JbrowseConfig(BaseModel):
    enabled: bool
    instance: Dict[str, Union[str, int]]
    watcher_plugin: Dict[str, Union[str, int]]
    data_dir: str
    config_dir: str

class Auth(BaseModel):
    tmp_token: str

    class Config:
        arbitrary_types_allowed = True


class Settings(BaseModel):
    mongodb: MongoConfig
    redis: RedisConfig
    fastapi: FastAPIConfig
    dash: DashConfig
    minio: MinioConfig
    jbrowse: JbrowseConfig
    auth: Auth

    @classmethod
    def from_yaml(cls, path: str):
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)
