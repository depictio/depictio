# New Feature Workflow

A structured workflow for implementing new features in depictio.

## Phase 1: Planning & Analysis

1. **Understand requirements**
   - Clarify feature scope and acceptance criteria
   - Identify affected components (API, Dash, CLI, Models)
   - Note integration points with existing code

2. **Architecture review**
   - Review related existing code
   - Identify models that need updates
   - Plan API endpoint structure
   - Design UI components (if applicable)

3. **Create task breakdown**
   - Use TodoWrite to create detailed tasks
   - Estimate complexity for each task
   - Identify dependencies between tasks

## Phase 2: Implementation

### Backend (if needed)

1. **Models** (`depictio/models/`)
   - Create/update Pydantic models
   - Add validators and defaults
   - Run: `ty check depictio/models/`

2. **API Endpoints** (`depictio/api/v1/endpoints/`)
   - Create route handlers
   - Add authentication/authorization
   - Write utility functions
   - Run: `ty check depictio/api/`

3. **Tests** (`depictio/tests/api/`)
   - Write unit tests for new endpoints
   - Test success and error cases
   - Run: `pytest depictio/tests/api/ -xvs`

### Frontend (if needed)

1. **Components** (`depictio/dash/modules/`)
   - Create/update component modules
   - Use DMC 2.0+ components
   - Ensure theme compatibility
   - Run: `ty check depictio/dash/`

2. **Callbacks** (`depictio/dash/`)
   - Add Dash callbacks
   - Handle state management
   - Test interactivity

3. **Tests** (`depictio/tests/dash/`)
   - Write component tests
   - Run: `pytest depictio/tests/dash/ -xvs`

## Phase 3: Quality Assurance

1. **Code quality**
   ```bash
   ruff format depictio/
   ruff check depictio/ --fix
   ty check depictio/models/ depictio/api/ depictio/dash/ depictio/cli/
   pre-commit run --all-files
   ```

2. **Full test suite**
   ```bash
   pytest depictio/tests/ -xvs -n auto
   ```

3. **Manual testing**
   - Test in development environment
   - Verify theme compatibility (light/dark)
   - Check responsive behavior

## Phase 4: Documentation & Commit

1. **Update documentation**
   - Update relevant docstrings
   - Add usage examples if needed
   - Update CLAUDE.md if patterns changed

2. **Commit changes**
   - Stage related files
   - Write descriptive commit message
   - Reference issue/PR if applicable

## Checklist

- [ ] Models created/updated with proper types
- [ ] API endpoints with auth and error handling
- [ ] Frontend components using DMC 2.0+
- [ ] Theme compatibility verified
- [ ] Unit tests written and passing
- [ ] Type checking passes (ty check)
- [ ] Linting passes (ruff)
- [ ] Pre-commit hooks pass
- [ ] Documentation updated
- [ ] Committed with descriptive message
