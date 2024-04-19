from pydantic import BaseModel, Field
from bson import ObjectId
from typing import Optional
import json

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        print("Validator called!")  # This should print when a new ObjectId is created
        if not isinstance(v, ObjectId):
            return cls()
        return v

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type='string')

class TestModel(BaseModel):
    toto: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: lambda o: str(o),
        }
        orm_mode = True

# Instantiate two test models
instance1 = TestModel(name="Instance 1")
instance2 = TestModel(name="Instance 2")

# Print the dictionary representation including aliases
print(instance1)