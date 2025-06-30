# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Environment Setup

```bash
# Install dependencies with uv (recommended) - Python 3.12
uv sync

# Or with pip
pip install -e .
pip install -e ".[dev]"

# Note: The project uses Python 3.12 in CI to ensure consistent type checking behavior
```

### Testing

```bash
# Run all tests
pytest depictio/tests/api depictio/tests/cli depictio/tests/models -xvs -n auto

# Run E2E tests (requires Cypress setup)
cd depictio/tests/e2e-tests && /Users/tweber/.nvm/versions/node/v20.16.0/bin/npx cypress run --config screenshotsFolder=cypress/screenshots,videosFolder=cypress/videos,trashAssetsBeforeRuns=false,video=true,screenshotOnRunFailure=true
```

### Code Quality

```bash
# Format code
ruff format .

# Lint code
ruff check .

# Type checking with ty (Astral's fast type checker)
ty check depictio/models/ depictio/api/ depictio/dash/ depictio/cli/ depictio/tests/  # All folders combined must pass CI

# Type checking with mypy (limited scope)
mypy depictio/models/ depictio/cli/

# Run pre-commit hooks
pre-commit run --all-files
```

### Local CI Testing with Act

```bash
# Test GitHub Actions workflow locally using act
# Requires Docker and act (https://github.com/nektos/act)
act --workflows .github/workflows/depictio-ci.yaml -j quality -P ubuntu-22.04=catthehacker/ubuntu:full-22.04 --container-architecture linux/amd64 --container-options "--privileged" --reuse --action-offline-mode

# Run specific job only
act --workflows .github/workflows/depictio-ci.yaml -j quality

# List available jobs
act --workflows .github/workflows/depictio-ci.yaml --list
```

### Running the Application

#### Development Mode (Docker compose)

```bash
# Start all services in development mode
docker compose -f docker-compose.dev.yaml -f docker-compose/docker-compose.minio.yaml --env-file docker-compose/.env up
```

## Architecture Overview

### Core Components

**FastAPI Backend (`depictio/api/`)**

- REST API with OpenAPI documentation
- Async MongoDB integration using Beanie ODM
- JWT-based authentication with user/group management
- Background task processing for data collections
- S3/MinIO integration for file storage

**Dash Frontend (`depictio/dash/`)**

- Interactive web dashboard built with Plotly Dash
- Modular component system (card, figure, table components)
- Draggable interface with save/restore functionality
- Authentication integration with backend API

**CLI Tool (`depictio/cli/`)**

- Typer-based command-line interface
- Commands for data management, configuration, and workflow execution
- Rich console output with progress indicators
- Integration with backend API for remote operations

**Data Models (`depictio/models/`)**

- Pydantic models with MongoDB document mapping
- Shared between API, CLI, and Dash components
- Type-safe data validation and serialization
- Support for various data collection types (tables, genomic data)

### Data Architecture

#### Database Layer

- MongoDB for metadata and configuration storage
- Collections: users, groups, projects, workflows, data_collections
- GridFS for large file storage
- Delta tables (Polars/PyArrow) for analytical data storage in S3/MinIO

#### Authentication & Authorization

- JWT tokens with public/private key encryption
- Role-based access control (users, groups, projects)
- SAML/OAuth integration capabilities (see dev/ examples)

#### File Storage

- S3-compatible storage (MinIO for local dev, AWS S3 for production)
- Delta Lake format for structured data
- Parquet files for efficient analytics
- Screenshot storage for dashboard previews

### Component Integration

#### Data Flow

1. CLI ingests data → Validates and stores in Delta format → Registers in MongoDB
2. API serves metadata and data access → Dash renders interactive visualizations
3. User interactions in Dash → API updates → Real-time dashboard updates

#### Inter-Service Communication

- FastAPI backend exposes REST endpoints at `/depictio/api/v1/`
- Dash frontend calls API endpoints for data and authentication
- CLI can operate standalone or communicate with remote API instances

### Development Patterns

#### Configuration Management

- Pydantic Settings for environment-based configuration
- Different contexts: API, Dash, CLI (set via DEPICTIO_CONTEXT)
- Environment files (.env) for secrets and deployment settings

#### Error Handling

- Structured exceptions with proper HTTP status codes
- Comprehensive logging with configurable levels
- Input sanitization and validation at model level

#### Testing Strategy

- Unit tests for models and utilities
- Integration tests for API endpoints
- E2E tests with Cypress for full user workflows
- Docker-based integration testing with real databases

### Type Checking with ty

The codebase uses Astral's `ty` type checker for static type analysis and maintains perfect type safety:

- Run `ty check depictio/models/ depictio/api/ depictio/dash/` - All folders MUST pass with zero errors
- Type checking is enforced in CI/CD pipeline for all pull requests and commits
- The codebase achieves complete type safety without using `# type: ignore` comments
- Type-safe patterns used:
  - Explicit field validation for Pydantic model instantiation
  - Proper ObjectId/PyObjectId type conversions
  - Defensive programming with None checks and validation
  - Type guards for Union types and optional fields

## Key Dependencies

- **FastAPI**: Web framework for the backend API
- **Dash/Plotly**: Interactive web dashboard framework
- **Beanie**: Async MongoDB ODM built on Pydantic
- **Polars**: Fast DataFrame library for data processing
- **Delta Lake**: Transactional storage layer for analytics
- **Typer**: CLI framework with rich output support
- **Pydantic**: Data validation and settings management

## Entry Points

- API: `depictio/api/main.py` - FastAPI application
- Dash: `depictio/dash/app.py` - Dash application factory
- CLI: `depictio/cli/depictio_cli.py` - Typer CLI application

## Configuration Files

- `pyproject.toml`: Python packaging, dependencies, and tool configuration
- `docker-compose.yaml`: Local development environment
- `helm-charts/depictio/`: Kubernetes deployment manifests
- `.env`: Environment variables (create from examples in dev/)
