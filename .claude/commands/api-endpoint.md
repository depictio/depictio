# API Endpoint Generator

Create a new FastAPI endpoint following depictio conventions.

## Instructions

When creating a new API endpoint:

1. **Analyze the request** to understand:
   - Endpoint purpose and HTTP method(s)
   - Required request/response models
   - Authentication requirements
   - Related data collections or workflows

2. **Follow depictio patterns**:
   - Location: `depictio/api/v1/endpoints/{domain}_endpoints/`
   - Use Pydantic models from `depictio/models/`
   - Async functions with Beanie ODM for MongoDB
   - JWT authentication via `get_current_user` dependency
   - Proper error handling with HTTPException

3. **Create or update files**:
   - `routes.py` - Endpoint route handlers
   - `utils.py` - Helper functions if needed
   - Update `depictio/api/v1/endpoints/routers.py` to include new router

4. **Add tests**:
   - Create test file in `depictio/tests/api/v1/endpoints/{domain}_endpoints/`
   - Test success and error cases

## Template Structure

```python
from fastapi import APIRouter, Depends, HTTPException, status
from depictio.api.v1.endpoints.user_endpoints.core_functions import get_current_user
from depictio.models.models.users import UserBeanie

router = APIRouter()

@router.get("/endpoint")
async def get_endpoint(
    current_user: UserBeanie = Depends(get_current_user)
):
    """Endpoint description."""
    pass
```

## Usage

`/api-endpoint <description>` - Create endpoint based on description

$ARGUMENTS
