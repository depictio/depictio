import yaml
from pydantic import BaseSettings, SecretStr


class Settings(BaseSettings):
    mongo_url: str
    mongo_db: str
    api_host: str
    api_port: int
    redis_host: str
    redis_port: int
    redis_db: int
    redis_cache_ttl: int
    multiqc_directory: str
    user_secret_key: SecretStr

    @classmethod
    def from_yaml(cls, file_path: str):
        with open(file_path, "r") as f:
            settings = yaml.safe_load(f)
        return cls(**settings)
