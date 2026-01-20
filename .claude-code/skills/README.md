# Depictio Custom Skills for Claude Code

This directory contains custom skills for Claude Code to assist with Depictio development workflows.

## Available Skills

### Testing & Quality Assurance

#### `/run-tests` - Smart Test Runner
Run tests with intelligent scope detection (all tests, specific modules, patterns, failed tests only).

**Quick usage**: "run tests", "test the API module", "re-run failed tests"

#### `/check-quality` - Code Quality Checks
Run complete quality workflow: ruff format, ruff check, ty type checking, and pre-commit hooks.

**Quick usage**: "check quality", "run pre-commit"

**CRITICAL**: Must pass with zero errors before committing.

#### `/test-e2e` - End-to-End Testing
Run Cypress E2E tests in headless or interactive mode with screenshot/video capture.

**Quick usage**: "run e2e tests", "open cypress"

### Development Workflow

#### `/bump-version` - Version Bumping
Automates version bumping using bump2helm script (updates all files, creates git tag, pushes to remote).

**Quick usage**: "bump version to beta 4", "bump patch version"

#### `/create-pr` - Pull Request Creation
Streamlined PR workflow with quality checks, test validation, and proper GitHub PR creation.

**Quick usage**: "create pr", "ready for pull request"

#### `/cleanup-branches` - Branch Cleanup
Clean up merged, gone, and stale branches to maintain repository hygiene.

**Quick usage**: "cleanup branches", "delete old branches"

### Database & Data Management

#### `/db-operations` - Database Operations
MongoDB backup, restore, validation, and coverage checking using Depictio CLI.

**Quick usage**: "create backup", "restore from backup", "list backups"

#### `/data-import` - Data Import Workflow
Import and process data collections using Depictio CLI (scan files, convert to Delta, register in MongoDB).

**Quick usage**: "import data from /path", "scan data files"

### Documentation

#### `/update-docs` - Documentation Updates
Update both public documentation (depictio-docs) and internal technical notes (Obsidian via MCP).

**Quick usage**: "update docs", "document this feature"

#### `/release-workflow` - Complete Release Process
Comprehensive release workflow from beta to stable release with all necessary steps.

**Quick usage**: "prepare release", "create beta release"

## How to Use Custom Skills

### Method 1: Direct Invocation (Recommended for Claude Code CLI)
Type `/skill-name` in your message to Claude Code:
```
/run-tests
/check-quality
/create-pr
```

### Method 2: Natural Language (Works Everywhere)
Simply describe what you want in natural language:
```
"run all tests"
"check code quality"
"create a pull request"
"bump version to beta 4"
"cleanup old branches"
```

Claude will recognize your intent and use the appropriate skill automatically.

### Method 3: Interactive
Claude will ask clarifying questions when needed:
```
You: "run tests"
Claude: "Which tests would you like to run? (all, specific module, pattern, failed only)"
```

## Common Workflows

### Before Committing
1. `/check-quality` - Ensure code quality
2. `/run-tests` - Verify tests pass
3. Commit changes

### Creating a Pull Request
1. `/check-quality` - Quality checks
2. `/run-tests` - Run tests
3. `/create-pr` - Create PR with proper formatting

### Preparing a Release
1. `/run-tests` - Verify all tests
2. `/check-quality` - Quality checks
3. `/update-docs` - Update documentation
4. `/bump-version` - Bump version and create tag
5. `/create-pr` - Create release PR (if needed)

### Weekly Maintenance
1. `/cleanup-branches` - Remove stale branches
2. `/db-operations` - Create backup
3. Review and merge open PRs

## Adding New Skills

To add a new custom skill:

1. Create a new `.md` file in this directory
2. Use the skill name as the filename (e.g., `my-skill.md`)
3. Follow the structure:
   - Title (# Skill Name)
   - Description
   - Usage instructions
   - Process/steps
   - Examples
   - Error handling

Claude Code will automatically discover and use skills in this directory.

## Skill Best Practices

- **Be specific**: Provide clear step-by-step instructions
- **Handle errors**: Include error handling guidance
- **Add examples**: Show concrete usage examples
- **Context-aware**: Reference project-specific tools and scripts
- **Interactive**: Guide Claude to ask clarifying questions when needed
