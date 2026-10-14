# API Endpoint Generator

Add a FastAPI endpoint. Conventions and invariants: `/CLAUDE.md`.

## Steps

1. Pick the domain package `depictio/api/v1/endpoints/<domain>_endpoints/` (look at a neighbour such as `projects_endpoints/routes.py` first). Add the handler to its `routes.py`; a new domain needs its router registered in `depictio/api/v1/endpoints/routers.py`.
2. Auth: `Depends(get_current_user)` for logged-in routes, `Depends(get_user_or_anonymous)` only for routes that are meant to work in public mode. Both live in `depictio/api/v1/endpoints/user_endpoints/routes.py`. Check the user's project/dashboard permission (owners, editors, viewers), not just that they are logged in.
3. Request and response types come from `depictio/models/` (add them there, see `/pydantic-model`). Handlers are `async`; raise `HTTPException` for 4xx.
4. A route that changes dashboard content must seed a baseline before the write and capture a version after it (`depictio/api/v1/endpoints/dashboards_endpoints/CLAUDE.md`).
5. If the viewer consumes it, update the client in `packages/depictio-react-core`.
6. Tests in `depictio/tests/api/` (success, 401/403, 404). Then `/quality`.

Usage: `/api-endpoint <description>`

$ARGUMENTS
