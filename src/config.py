import yaml
from pydantic import BaseSettings


class Settings(BaseSettings):
    mongo_url: str
    mongo_db: str
    api_host: str
    api_port: int
    multiqc_directory: str

    @classmethod
    def from_yaml(cls, file_path: str):
        with open(file_path, "r") as f:
            settings = yaml.safe_load(f)
        return cls(**settings)
