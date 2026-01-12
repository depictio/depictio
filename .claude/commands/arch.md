# Architecture Explorer

Explore and understand the depictio architecture.

## Instructions

Help understand the codebase architecture:

1. **Component overview**:
   - `depictio/api/` - FastAPI backend (REST API, auth, background tasks)
   - `depictio/dash/` - Plotly Dash frontend (interactive dashboards)
   - `depictio/cli/` - Typer CLI tool (data management)
   - `depictio/models/` - Shared Pydantic models

2. **Key subsystems**:

   **API Layer** (`depictio/api/v1/endpoints/`):
   - 17 endpoint groups for different domains
   - JWT authentication with role-based access
   - Beanie ODM for async MongoDB

   **Dashboard Components** (`depictio/dash/modules/`):
   - Figure, Table, Card, Interactive, Text, JBrowse, MultiQC
   - Each has frontend.py, callbacks/, utils.py

   **Data Flow**:
   1. CLI ingests data -> Delta format -> MongoDB registration
   2. API serves metadata and data access
   3. Dash renders interactive visualizations

3. **Exploration commands**:
   - Show directory structure
   - Find related files
   - Trace data flow
   - Identify dependencies

## Topics

- `api` - FastAPI backend architecture
- `dash` - Dash frontend architecture
- `models` - Data model relationships
- `auth` - Authentication flow
- `data` - Data ingestion pipeline
- `storage` - S3/MinIO file storage
- `callbacks` - Dash callback patterns

## Usage

`/arch` - Show high-level architecture overview
`/arch <topic>` - Deep dive into specific topic
`/arch flow <feature>` - Trace data flow for a feature

$ARGUMENTS
