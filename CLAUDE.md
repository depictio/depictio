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
pytest depictio/tests/ -xvs -n auto

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
ty check depictio/

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

## Documentation Workflow

When finishing a PR that adds new features or makes significant changes:

### 1. Update depictio-docs (VS Code workspace)

- **Required**: Update relevant documentation files in the depictio-docs repository
- Document new features, API changes, configuration options, and user-facing functionality
- Include code examples, usage patterns, and integration guides
- Update README files, installation guides, and user documentation as needed

### 2. Update Obsidian Notes (Core Developer Documentation)

- **Required**: Extend corresponding Obsidian notes with detailed technical information
- **Location**: Obsidian vault accessible via MCP integration (`mcp-obsidian`)
- **Access**: Use MCP tools to read/write notes directly from Claude Code
- **Focus areas**:
  - Technical implementation details not suitable for public docs
  - Architecture decisions and trade-offs
  - Internal APIs and developer-specific patterns
  - Performance considerations and optimization notes
  - Debugging strategies and troubleshooting for developers
  - Database schema changes and migration notes
  - Security considerations and implementation details
  - Testing strategies and coverage gaps
  - Future refactoring opportunities and technical debt

### Documentation Guidelines

**depictio-docs (Public Documentation)**:

- User-focused content
- Clear examples and tutorials
- Installation and deployment guides
- API reference documentation
- Best practices for end users

**Obsidian Notes (Internal Documentation)**:

- Developer-focused technical details
- Implementation specifics and edge cases
- Performance benchmarks and profiling results
- Code review insights and lessons learned
- Integration challenges and solutions
- Monitoring and observability setup
- Development environment quirks and fixes

## Code Quality Enforcement

**CRITICAL REQUIREMENT**: After every code operation (creating, editing, or deleting files), you MUST:

1. **Run pre-commit hooks**: `pre-commit run --all-files`
2. **Fix any failures** before considering the task complete
3. **Re-run pre-commit** until all checks pass

This ensures all code changes comply with project standards including:
- Code formatting (ruff format)
- Linting rules (ruff check)
- Type checking (ty check)
- Import sorting and other quality checks

**No exceptions** - pre-commit compliance is mandatory for all code changes.

## Frontend Development Guidelines

### Component Framework Standards

**CRITICAL REQUIREMENT**: All new frontend components and features MUST use **DMC 2.0+** (Dash Mantine Components) for UI consistency and maintainability.

#### Component Library Priority

1. **Primary**: DMC 2.0+ components (dash-mantine-components >= 2.0.0)
   - All new UI components must use DMC 2.0+ unless technically impossible
   - Provides consistent styling and theme integration
   - Better accessibility and modern UI patterns

2. **Secondary**: Custom HTML/CSS components (only when DMC is insufficient)
   - Must follow the established theme system patterns
   - Require justification for not using DMC

3. **Deprecated**: Bootstrap components (dash-bootstrap-components)
   - Only maintain existing usage, do not extend
   - Gradually migrate to DMC when refactoring

#### Theme Compatibility Requirements

**MANDATORY**: All new components and modifications MUST be compatible with the dark/light theme switch system.

##### Theme-Aware Development Checklist

- [ ] **Use CSS Variables**: All styling must use theme-aware CSS variables:
  - `var(--app-bg-color)` for background colors
  - `var(--app-text-color)` for text colors
  - `var(--app-surface-color)` for component surfaces
  - `var(--app-border-color)` for borders

- [ ] **Test Both Themes**: Manually test components in both light and dark themes
  - Verify text readability and contrast
  - Check background color inheritance
  - Ensure icons and graphics are theme-appropriate

- [ ] **Follow Theme Patterns**:
  - Use DMC's built-in theme support when available
  - Extend `theme_utils.py` for custom theme-aware styling
  - Never hardcode colors (e.g., `#ffffff`, `#000000`)

- [ ] **DataTable Styling**: For Dash DataTables, use the established pattern:
  ```python
  style_cell={
      "backgroundColor": "var(--app-surface-color, #ffffff)",
      "color": "var(--app-text-color, #000000)",
      # ... other styling
  }
  ```

##### Theme Integration Examples

```python
# ✅ GOOD: Theme-aware component
dmc.Paper(
    children=[...],
    style={
        "backgroundColor": "var(--app-surface-color, #ffffff)",
        "color": "var(--app-text-color, #000000)",
        "border": "1px solid var(--app-border-color, #ddd)",
    }
)

# ❌ BAD: Hardcoded colors
dmc.Paper(
    children=[...],
    style={
        "backgroundColor": "#ffffff",
        "color": "#000000",
        "border": "1px solid #ddd",
    }
)
```

#### Component Testing Requirements

- **Visual Testing**: All components must be visually tested in both themes
- **Accessibility**: Ensure proper contrast ratios in both light and dark modes
- **Responsive Design**: Components must work across different screen sizes
- **State Management**: Theme changes should not break component state

#### Migration Strategy

When working with existing components:

1. **Assess Current State**: Identify non-DMC components that need migration
2. **Gradual Migration**: Replace components incrementally during feature work
3. **Theme Compatibility**: Ensure all changes maintain theme switching functionality
4. **Documentation**: Update component documentation with theme requirements

## Screenshot System - Dash 3+ Component Targeting

### Background

With the migration to Dash 3+ and Mantine AppShell architecture, the traditional screenshot approach targeting `.mantine-AppShell-main` captured the full viewport (1920x1080) including navbar, header, and other UI elements. This was problematic for dashboard previews where only the dashboard content should be captured.

### Problem Analysis

**Root Cause**: In minimalistic dashboards, parent containers (`#page-content`, `#draggable`, `.react-grid-layout`) collapse to 0px height because they only contain absolutely positioned components (`.react-grid-item`). The actual dashboard content exists as individual positioned components.

**Key Findings**:
- `.mantine-AppShell-main` captures full viewport including unwanted UI elements
- Parent containers have 0px dimensions with minimal dashboard content
- `.react-grid-item` components contain the actual rendered dashboard elements

### Solution: Component-Based Composite Screenshots

#### Implementation Strategy

**Primary Method**: Component-based composite targeting
1. **Target Individual Components**: Use `.react-grid-item` selector to find all dashboard components
2. **Create Composite Boundary**: Calculate bounding box encompassing all components
3. **Generate Composite Screenshot**: Capture only the dashboard content area

**Fallback Chain**:
1. Component composite screenshot (preferred)
2. AppShell main element (legacy compatibility)
3. Full page screenshot (final fallback)

#### Technical Implementation

**Location**: `depictio/api/v1/endpoints/utils_endpoints/routes.py:screenshot_dash_fixed()`

```python
# Wait for dashboard components to render
await page.wait_for_function("""
    () => {
        const components = document.querySelectorAll('.react-grid-item');
        if (components.length === 0) return false;

        // Check if at least one component has meaningful dimensions
        for (let component of components) {
            const rect = component.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                return true;
            }
        }
        return false;
    }
""", timeout=10000)

# Create composite view of all components
components = await page.query_selector_all('.react-grid-item')
composite_element = await page.evaluate("""
    () => {
        const components = document.querySelectorAll('.react-grid-item');
        // Calculate bounding box of all components
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

        components.forEach(component => {
            const rect = component.getBoundingClientRect();
            minX = Math.min(minX, rect.left);
            minY = Math.min(minY, rect.top);
            maxX = Math.max(maxX, rect.right);
            maxY = Math.max(maxY, rect.bottom);
        });

        // Create invisible container encompassing all components
        const container = document.createElement('div');
        container.id = 'temp-screenshot-container';
        container.style.position = 'absolute';
        container.style.left = minX + 'px';
        container.style.top = minY + 'px';
        container.style.width = (maxX - minX) + 'px';
        container.style.height = (maxY - minY) + 'px';
        // ... container styling

        document.body.appendChild(container);
        return { width: maxX - minX, height: maxY - minY, componentCount: components.length };
    }
""")

# Screenshot the composite area
temp_container = await page.query_selector('#temp-screenshot-container')
await temp_container.screenshot(path=output_file)
```

#### Validation and Testing

**Development Environment**: `dev/playwright_debug/mantine_appshell_debug.py`
- **Authentication**: Uses real credentials from `depictio/.depictio/admin_config.yaml`
- **Component Detection**: Validates individual `.react-grid-item` targeting
- **Composite Generation**: Creates both individual and composite screenshots

**Test Results**:
- Successfully captured 9 dashboard components individually
- Generated composite view: 1648x890 (perfect dashboard content only)
- Excluded navbar, header, and UI chrome elements

#### Advantages

1. **Precise Targeting**: Captures only dashboard content, excluding UI chrome
2. **Responsive to Content**: Automatically adjusts to actual component dimensions
3. **Future-Proof**: Works with any number/arrangement of dashboard components
4. **Fallback Compatible**: Maintains backward compatibility with existing approaches

#### Development Notes

- **Browser Compatibility**: Uses Playwright's element selection and screenshot APIs
- **Performance**: Minimal overhead - single DOM query + bounding box calculation
- **Reliability**: Includes proper wait conditions for component rendering
- **Debugging**: Comprehensive logging for troubleshooting screenshot failures

#### Usage Considerations

- **Component Requirements**: Requires `.react-grid-item` components to be present
- **Timing**: Uses smart waiting for component rendering with proper dimensions
- **Error Handling**: Graceful fallback to traditional methods if component targeting fails
- **Cleanup**: Properly removes temporary DOM elements after screenshot
