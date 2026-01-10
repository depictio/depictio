# Claude Code Configuration for Depictio

This directory contains Claude Code configuration for developing depictio. It includes settings, hooks, custom skills, MCP servers, and workflow templates.

## Quick Start

1. **Install Claude Code**: Follow instructions at [code.claude.com](https://code.claude.com)
2. **Open in Claude Code**: `claude` from the depictio directory
3. **Use skills**: Type `/quality`, `/test`, `/review`, etc.

## Directory Structure

```
.claude/
├── settings.json          # Claude Code settings and permissions
├── mcp.json              # MCP server configurations
├── hooks/                # Automation hooks
│   ├── post-file-change.sh    # Runs after Write/Edit
│   ├── pre-bash-check.sh      # Validates bash commands
│   └── on-stop-summary.sh     # Session end summary
├── commands/             # Custom skills (slash commands)
│   ├── quality.md        # /quality - Code quality checks
│   ├── test.md           # /test - Run tests
│   ├── api-endpoint.md   # /api-endpoint - Create API endpoints
│   ├── dash-component.md # /dash-component - Create Dash components
│   ├── model.md          # /model - Create Pydantic models
│   ├── logs.md           # /logs - View service logs
│   ├── review.md         # /review - Code review helper
│   ├── db.md             # /db - Database operations
│   └── arch.md           # /arch - Architecture explorer
├── workflows/            # Development workflow guides
│   ├── new-feature.md    # Feature implementation workflow
│   ├── bug-fix.md        # Bug fix workflow
│   ├── api-development.md        # API development guide
│   └── dash-component-development.md  # Component development guide
├── agents/               # Specialized agent definitions
│   ├── api-agent.md      # FastAPI backend specialist
│   ├── dash-agent.md     # Dash frontend specialist
│   ├── testing-agent.md  # Testing specialist
│   ├── data-agent.md     # Data processing specialist
│   ├── devops-agent.md   # DevOps specialist
│   └── security-agent.md # Security specialist
└── README.md             # This file
```

## Custom Skills

### Code Quality & Testing
| Skill | Description | Example |
|-------|-------------|---------|
| `/quality` | Run code quality checks | `/quality fix` |
| `/test` | Run tests | `/test api`, `/test models` |
| `/review` | Code review helper | `/review`, `/review <file>` |

### Development
| Skill | Description | Example |
|-------|-------------|---------|
| `/api-endpoint` | Create API endpoint | `/api-endpoint user preferences` |
| `/dash-component` | Create Dash component | `/dash-component figure heatmap` |
| `/model` | Create Pydantic model | `/model UserPreferences` |

### Operations
| Skill | Description | Example |
|-------|-------------|---------|
| `/logs` | View service logs | `/logs api`, `/logs dash` |
| `/db` | Database operations | `/db collections`, `/db query users` |
| `/arch` | Architecture explorer | `/arch api`, `/arch flow auth` |

## Hooks

### PostToolUse: post-file-change.sh
Runs after Write/Edit on Python files:
- Checks formatting with ruff
- Reports lint issues
- Suggests fixes

### PreToolUse: pre-bash-check.sh
Validates bash commands before execution:
- Blocks dangerous commands (rm -rf, docker rm, etc.)
- Prevents accidental data loss
- Allows safe development commands

### Stop: on-stop-summary.sh
Runs when session ends:
- Shows git status summary
- Reports pending lint issues
- Reminds about uncommitted changes

## MCP Servers

| Server | Purpose |
|--------|---------|
| mongodb | Direct MongoDB access for depictioDB |
| filesystem | File system access for codebase |
| fetch | HTTP fetch for API testing |
| memory | Persistent memory for session context |

## Specialized Agents

Agents are domain-specific AI assistants with deep expertise in particular areas of depictio development. They can be invoked for complex, multi-step tasks.

### Available Agents

| Agent | Expertise | Use Case |
|-------|-----------|----------|
| **API Agent** | FastAPI, Beanie ODM, REST APIs | Backend endpoint development |
| **Dash Agent** | Plotly Dash, DMC 2.0+, Callbacks | Frontend component development |
| **Testing Agent** | pytest, async testing, fixtures | Writing and running tests |
| **Data Agent** | Polars, Delta Lake, S3/MinIO | Data processing pipelines |
| **DevOps Agent** | Docker, Helm, GitHub Actions | Infrastructure and CI/CD |
| **Security Agent** | Auth, validation, OWASP | Security review and implementation |

### How Agents Work

Agents are automatically selected based on task context, or can be explicitly requested:

```
"Help me create a new API endpoint for user preferences"
→ API Agent is engaged for FastAPI expertise

"Review this code for security vulnerabilities"
→ Security Agent is engaged for security review

"Set up data ingestion for a new CSV format"
→ Data Agent is engaged for data processing
```

### Agent Capabilities

Each agent has:
- **Domain expertise** - Deep knowledge of specific technologies
- **Code patterns** - Best practices and templates for that domain
- **Safety rules** - Understanding of what operations are safe
- **Context awareness** - Knowledge of depictio's architecture

## Workflows

### New Feature Workflow
`workflows/new-feature.md` - Complete guide for implementing features:
1. Planning & Analysis
2. Backend implementation (Models, API, Tests)
3. Frontend implementation (Components, Callbacks, Tests)
4. Quality assurance
5. Documentation & Commit

### Bug Fix Workflow
`workflows/bug-fix.md` - Structured approach to fixing bugs:
1. Reproduce and diagnose
2. Root cause analysis
3. Implement minimal fix
4. Add regression tests
5. Validate and commit

### API Development Workflow
`workflows/api-development.md` - FastAPI endpoint development:
- Directory structure
- Model design
- Endpoint implementation
- Testing patterns
- Best practices

### Dash Component Workflow
`workflows/dash-component-development.md` - Dash component development:
- Component structure
- DMC 2.0+ requirements
- Theme compatibility
- Callback patterns
- State management

## Permissions

The settings.json configures allowed and denied operations:

### Allowed
- Testing: pytest, ruff, ty, pre-commit
- Package management: uv, pip, npm
- Git operations: all standard commands
- Docker: logs, ps, compose logs
- Database: mongosh queries
- File operations: read, write, edit, glob, grep

### Denied (Safety)
- Destructive docker commands (rm, rmi, volume rm, system prune)
- Docker compose lifecycle (up, down, restart, exec)
- sudo commands
- rm -rf on critical paths

## Environment Variables

Set automatically in Claude Code sessions:
- `DEPICTIO_CONTEXT=server`
- `DEPICTIO_LOGGING_VERBOSITY_LEVEL=DEBUG`
- `PYTHONPATH=${workspaceFolder}`

## Best Practices

### Using Skills
1. Start with `/arch` to understand the codebase
2. Use `/quality` before committing
3. Run `/test` after changes
4. Use `/review` for code review

### Development Flow
1. Check current state: `/logs`, `/db`
2. Plan with workflow templates
3. Implement with skill guidance
4. Validate with `/quality` and `/test`
5. Review with `/review`

### Extending Configuration

**Add a new skill:**
1. Create `.claude/commands/my-skill.md`
2. Define instructions and examples
3. Use `$ARGUMENTS` placeholder for inputs

**Add a new hook:**
1. Create `.claude/hooks/my-hook.sh`
2. Make executable: `chmod +x`
3. Add to settings.json hooks section

**Add MCP server:**
1. Update `.claude/mcp.json`
2. Add server configuration
3. Restart Claude Code session

## Troubleshooting

### Hooks not running
- Check hooks are executable: `chmod +x .claude/hooks/*.sh`
- Verify jq is installed for JSON parsing
- Check hook matcher patterns in settings.json

### MCP servers not connecting
- Ensure npx is available
- Check network connectivity
- Review MCP server logs

### Skills not appearing
- Verify markdown format in commands/
- Check for syntax errors in skill files
- Restart Claude Code session
