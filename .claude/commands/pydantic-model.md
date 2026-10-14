# Pydantic Model Generator

Add or change a model in `depictio/models/models/`. These models are shared by the API, CLI and worker.

## Conventions (read a neighbour first, e.g. `projects.py`, `users.py`)

- Pydantic v2. Plain models derive from `BaseModel` or `MongoModel` (`base.py`, which also holds `PyObjectId`).
- Mongo documents are a second class `<Name>Beanie(<Name>, Document)` with an inner `class Settings: name = "<collection>"`; add it to the `init_beanie` document list in `depictio/api/v1/services/lifespan.py` (and `depictio/api/celery_app.py` if the worker reads it).
- Use `X | None` and explicit types on every field; validators with `@field_validator`.
- Gate: `uv run --extra dev ty check depictio/models/` must report zero errors (do not add the file to the `[tool.ty.src]` excludes).
- A dashboard model field must also be added to `TabSnapshot` or a `SNAPSHOT_*_FIELDS` set in `depictio/api/v1/endpoints/dashboards_endpoints/versioning.py`, or the field-coverage test fails.
- Tests in `depictio/tests/models/`.

Usage: `/pydantic-model <name> <description>`

$ARGUMENTS
