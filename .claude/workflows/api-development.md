# API Development Workflow

Workflow for developing FastAPI endpoints in depictio.

## Directory Structure

```
depictio/api/v1/endpoints/
├── routers.py              # Main router aggregator
├── {domain}_endpoints/
│   ├── __init__.py
│   ├── routes.py           # Route handlers
│   ├── utils.py            # Helper functions
│   └── core_functions.py   # Core business logic
```

## Phase 1: Design

1. **Define the endpoint**
   - HTTP method (GET, POST, PUT, DELETE)
   - URL path following REST conventions
   - Request/response schemas
   - Authentication requirements

2. **Design data models**
   - Request body model
   - Response model
   - Database model updates

## Phase 2: Implementation

### Step 1: Create/Update Models

```python
# depictio/models/models/{domain}.py
from pydantic import BaseModel, Field
from depictio.models.models.base import DepictioBaseModel, PyObjectId

class MyRequest(BaseModel):
    """Request model."""
    field: str = Field(..., min_length=1)

class MyResponse(DepictioBaseModel):
    """Response model."""
    id: PyObjectId
    field: str
```

### Step 2: Create Endpoint

```python
# depictio/api/v1/endpoints/{domain}_endpoints/routes.py
from fastapi import APIRouter, Depends, HTTPException, status
from depictio.api.v1.endpoints.user_endpoints.core_functions import get_current_user
from depictio.models.models.users import UserBeanie

router = APIRouter()

@router.post("/", response_model=MyResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    request: MyRequest,
    current_user: UserBeanie = Depends(get_current_user)
) -> MyResponse:
    """Create a new item."""
    # Validate permissions
    # Process request
    # Save to database
    # Return response
    pass
```

### Step 3: Register Router

```python
# depictio/api/v1/endpoints/routers.py
from depictio.api.v1.endpoints.{domain}_endpoints.routes import router as {domain}_router

# Add to router list
app.include_router({domain}_router, prefix="/{domain}", tags=["{Domain}"])
```

### Step 4: Write Tests

```python
# depictio/tests/api/v1/endpoints/{domain}_endpoints/test_routes.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_item(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/depictio/api/v1/{domain}/",
        json={"field": "value"},
        headers=auth_headers
    )
    assert response.status_code == 201
    assert response.json()["field"] == "value"
```

## Phase 3: Validation

1. **Type checking**
   ```bash
   ty check depictio/api/ depictio/models/
   ```

2. **Run tests**
   ```bash
   pytest depictio/tests/api/v1/endpoints/{domain}_endpoints/ -xvs
   ```

3. **Manual testing**
   ```bash
   # Test with curl
   curl -X POST http://localhost:8058/depictio/api/v1/{domain}/ \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"field": "value"}'
   ```

## Best Practices

- Use async/await for all database operations
- Return proper HTTP status codes
- Include detailed error messages
- Log important operations
- Validate input with Pydantic
- Use dependency injection for auth
- Handle ObjectId conversions properly

## Common Patterns

### Pagination
```python
@router.get("/")
async def list_items(
    skip: int = 0,
    limit: int = 100,
    current_user: UserBeanie = Depends(get_current_user)
):
    items = await MyModel.find_all().skip(skip).limit(limit).to_list()
    return items
```

### Error Handling
```python
if not item:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Item with id {item_id} not found"
    )
```

### Permission Check
```python
if item.owner_id != current_user.id:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access this item"
    )
```
