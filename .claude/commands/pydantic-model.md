# Pydantic Model Generator

Create or modify Pydantic models following depictio conventions.

## Instructions

When working with models:

1. **Location**: `depictio/models/models/`
   - `base.py` - Base models and PyObjectId
   - `users.py` - User, Group, Token models
   - `projects.py` - Project models
   - `workflows.py` - Workflow models
   - `data_collections.py` - Data collection models
   - `dashboards.py` - Dashboard models
   - `files.py` - File metadata models
   - `analytics.py` - Analytics models

2. **Model patterns**:
   - Use Pydantic v2 syntax
   - Inherit from `DepictioBaseModel` for shared functionality
   - Use `PyObjectId` for MongoDB ObjectId fields
   - Add `Beanie` suffix for MongoDB document models

3. **Type safety requirements**:
   - All fields must have explicit types
   - Use Optional[] for nullable fields
   - Use Union[] for polymorphic fields
   - Add proper validators using `@field_validator`

4. **MongoDB integration**:
   - Document models inherit from `beanie.Document`
   - Define `Settings` class with collection name
   - Use `Link[]` for document references

## Example Pattern

```python
from typing import Optional
from pydantic import Field, field_validator
from bson import ObjectId
from beanie import Document
from depictio.models.models.base import DepictioBaseModel, PyObjectId

class MyModel(DepictioBaseModel):
    """Model description."""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return v.strip()

class MyModelBeanie(Document, MyModel):
    class Settings:
        name = "my_collection"
```

## Usage

`/pydantic-model <name> <description>` - Create or update model

$ARGUMENTS
