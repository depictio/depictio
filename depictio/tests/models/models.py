from bson import ObjectId
from pydantic import BaseModel, ConfigDict


class HelloModel(BaseModel):
    key1: str
    key2: int


class DummyModel(BaseModel):
    id: ObjectId
    name: str

    model_config = ConfigDict(arbitrary_types_allowed=True)
