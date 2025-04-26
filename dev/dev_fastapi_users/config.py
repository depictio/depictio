from pydantic import BaseModel
from typing import Optional

class Settings(BaseModel):
    database_url: str = "mongodb://localhost:27017"
    database_name: str = "fastapi_users_db"
    secret: str = "SECRET_KEY_CHANGE_THIS"
    token_lifetime_seconds: int = 3600

settings = Settings()