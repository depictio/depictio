# Getting Started with Claude Code for Depictio

A practical guide to understanding and using Claude Code's features for depictio development.

---

## Table of Contents

1. [Core Concepts](#core-concepts)
2. [Quick Start](#quick-start)
3. [Skills (Slash Commands)](#skills-slash-commands)
4. [Hooks (Automation)](#hooks-automation)
5. [MCP Servers (External Tools)](#mcp-servers-external-tools)
6. [Official Plugins](#official-plugins)
7. [Agents (Specialists)](#agents-specialists)
8. [Workflows (Guided Processes)](#workflows-guided-processes)
9. [Common Development Scenarios](#common-development-scenarios)
10. [Tips & Best Practices](#tips--best-practices)

---

## Core Concepts

### What is Claude Code?

Claude Code is an AI-powered CLI tool that helps with software development. Think of it as having an expert developer assistant in your terminal that can:

- Read and understand your codebase
- Write and edit code
- Run commands and tests
- Review code for issues
- Guide you through complex tasks

### The Building Blocks

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLAUDE CODE                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │  SKILLS  │  │  HOOKS   │  │   MCP    │  │     PLUGINS      │ │
│  │          │  │          │  │ SERVERS  │  │                  │ │
│  │ /command │  │ Pre/Post │  │          │  │ Official tools   │ │
│  │ shortcuts│  │ triggers │  │ External │  │ from Anthropic   │ │
│  │          │  │          │  │ tools    │  │                  │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
│                                                                  │
│  ┌──────────────────────────┐  ┌─────────────────────────────┐  │
│  │         AGENTS           │  │        WORKFLOWS            │  │
│  │                          │  │                             │  │
│  │  Specialized AI experts  │  │  Step-by-step guides for    │  │
│  │  for specific domains    │  │  complex tasks              │  │
│  └──────────────────────────┘  └─────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

| Concept | What It Does | Analogy |
|---------|--------------|---------|
| **Skills** | Quick commands for common tasks | Keyboard shortcuts |
| **Hooks** | Automatic actions on events | Git hooks / CI triggers |
| **MCP Servers** | Connect to external tools | API integrations |
| **Plugins** | Pre-built feature packages | VS Code extensions |
| **Agents** | Domain expert prompts | Specialized consultants |
| **Workflows** | Multi-step guides | Runbooks / SOPs |

---

## Quick Start

### 1. Start Claude Code

```bash
cd /path/to/depictio
claude
```

### 2. Try Your First Skill

```bash
# Check code quality
/quality

# Run tests
/test

# Explore architecture
/arch
```

### 3. Ask Questions Naturally

```
"What does the authentication flow look like?"
"Help me add a new API endpoint for user settings"
"Why is this test failing?"
```

### 4. Use Official Plugins

```bash
# AI-assisted commit
/commit

# Full code review
/code-review
```

---

## Skills (Slash Commands)

### What Are Skills?

Skills are shortcuts that trigger specific behaviors. Type `/` followed by the skill name.

### Your Custom Skills for Depictio

```bash
# CODE QUALITY
/quality              # Run ruff, ty, pre-commit
/quality fix          # Auto-fix issues
/quality depictio/api # Check specific path

# TESTING
/test                 # Run all tests
/test api             # Run API tests only
/test models          # Run model tests only

# CODE REVIEW
/review               # Review staged changes
/review file.py       # Review specific file

# DEVELOPMENT
/api-endpoint         # Create new FastAPI endpoint
/model                # Create Pydantic model

# OPERATIONS
/logs api             # View backend logs
/logs dash            # View frontend logs
/db collections       # List MongoDB collections
/db query users       # Query a collection

# EXPLORATION
/arch                 # Architecture overview
/arch api             # Deep dive into API
/arch flow auth       # Trace auth data flow
```

### How Skills Work

Skills are markdown files in `.claude/commands/`. Example structure:

```markdown
# Quality Check

Run code quality checks on the depictio codebase.

## Instructions

1. Run ruff format check
2. Run ruff lint
3. Run ty type checker
4. Report issues and suggest fixes

$ARGUMENTS   <!-- User's input goes here -->
```

### Creating Your Own Skill

```bash
# Create a new skill file
touch .claude/commands/my-skill.md
```

```markdown
# My Custom Skill

Description of what this skill does.

## Instructions

Step-by-step instructions for Claude to follow.

Use $ARGUMENTS for user input.
```

---

## Hooks (Automation)

### What Are Hooks?

Hooks are scripts that run automatically when certain events happen. They're like Git hooks but for Claude Code.

### Hook Types

| Type | When It Runs | Use Case |
|------|--------------|----------|
| **PreToolUse** | Before a tool executes | Validate commands, block dangerous ops |
| **PostToolUse** | After a tool completes | Run linters, notify, log |
| **Stop** | When session ends | Show summary, remind about commits |
| **Notification** | On notifications | Custom alerts |

### Your Configured Hooks

```
┌─────────────────┐     ┌──────────────────────┐
│   Write/Edit    │────▶│  post-file-change.sh │
│   Python file   │     │  - Check formatting  │
└─────────────────┘     │  - Report lint issues│
                        └──────────────────────┘

┌─────────────────┐     ┌──────────────────────┐
│   Bash command  │────▶│  pre-bash-check.sh   │
│   about to run  │     │  - Block dangerous   │
└─────────────────┘     │  - Allow safe ops    │
                        └──────────────────────┘

┌─────────────────┐     ┌──────────────────────┐
│  Session ends   │────▶│  on-stop-summary.sh  │
│                 │     │  - Git status        │
└─────────────────┘     │  - Pending issues    │
                        └──────────────────────┘
```

### Example: What pre-bash-check.sh Does

When you (or Claude) try to run a bash command:

```bash
# ✅ ALLOWED - Safe commands pass through
git status
pytest depictio/tests/
docker logs backend

# ❌ BLOCKED - Dangerous commands are stopped
docker rm -f container    # Returns: "Blocked dangerous command"
rm -rf /depictio          # Returns: "Could cause data loss"
```

### Creating a Custom Hook

```bash
# 1. Create the hook script
cat > .claude/hooks/my-hook.sh << 'EOF'
#!/bin/bash
# Access context via environment variables:
# - TOOL_INPUT: JSON with tool parameters
# - TOOL_OUTPUT: JSON with tool result (PostToolUse only)

# Example: Log all Write operations
echo "File written: $(echo $TOOL_INPUT | jq -r '.file_path')" >> /tmp/claude-writes.log
EOF

chmod +x .claude/hooks/my-hook.sh

# 2. Register in settings.json
# Add to "hooks" section
```

---

## MCP Servers (External Tools)

### What Are MCP Servers?

MCP (Model Context Protocol) servers connect Claude Code to external tools and data sources. They extend Claude's capabilities beyond the filesystem.

### Your Configured MCP Servers

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLAUDE CODE                               │
│                                                                  │
│    ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────────┐   │
│    │ github  │  │ mongodb │  │  fetch  │  │ sequential-     │   │
│    │         │  │         │  │         │  │ thinking        │   │
│    └────┬────┘  └────┬────┘  └────┬────┘  └────────┬────────┘   │
└─────────┼───────────┼───────────┼─────────────────┼─────────────┘
          │           │           │                 │
          ▼           ▼           ▼                 ▼
    ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────────┐
    │ GitHub  │  │ MongoDB │  │  HTTP   │  │    Enhanced     │
    │   API   │  │localhost│  │ Requests│  │    Reasoning    │
    │         │  │ :27018  │  │         │  │                 │
    └─────────┘  └─────────┘  └─────────┘  └─────────────────┘
```

### What Each Server Does

| Server | Capabilities | Example Use |
|--------|--------------|-------------|
| **github** | Read PRs, issues, commits | "Show me open PRs", "What's in issue #123?" |
| **mongodb** | Query/inspect database | "How many users are there?", "Show recent projects" |
| **filesystem** | Enhanced file operations | "Search all Python files" |
| **fetch** | Make HTTP requests | "Test this API endpoint" |
| **memory** | Persistent knowledge | Remember context across sessions |
| **sequential-thinking** | Complex reasoning | Multi-step problem solving |

### Enabling MCP Servers

```bash
# GitHub integration (required for /code-review on PRs)
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"

# Then start Claude Code
claude
```

### Using MCP Servers

Once configured, you can ask:

```
"Show me the open pull requests"           # Uses github MCP
"How many documents in the users collection?"  # Uses mongodb MCP
"Fetch the response from localhost:8058/health"  # Uses fetch MCP
```

---

## Official Plugins

### What Are Plugins?

Plugins are pre-built packages of skills, hooks, and agents created by Anthropic. They provide powerful, tested workflows.

### Your Enabled Plugins

| Plugin | What It Does |
|--------|--------------|
| **code-review** | 5 parallel agents review your code for bugs, compliance, etc. |
| **commit-commands** | AI-generated commit messages, streamlined git workflow |
| **frontend-design** | UI/UX design guidance for your Dash components |
| **feature-dev** | 7-phase feature development workflow |
| **security-guidance** | Monitors for security anti-patterns |
| **hookify** | Create custom hooks interactively |

### Using Plugins

```bash
# CODE REVIEW - Analyzes staged changes with 5 specialized agents
/code-review

# Output:
# ┌─ Compliance Agent ─────────────────────┐
# │ ✓ No license violations detected       │
# └────────────────────────────────────────┘
# ┌─ Bug Detection Agent ──────────────────┐
# │ ⚠ Potential null reference on line 45  │
# └────────────────────────────────────────┘
# ... (3 more agents)


# COMMIT - Creates commit with AI-generated message
/commit

# Output:
# Analyzing changes...
# Suggested commit message:
#   feat(api): add user preferences endpoint
#
#   - Add GET/PUT /users/preferences endpoints
#   - Create UserPreferences Pydantic model
#   - Add tests for preference operations
#
# Proceed? [Y/n]


# COMMIT + PUSH + PR in one command
/commit-push-pr


# FEATURE DEVELOPMENT - Guided 7-phase workflow
/feature-dev

# Phases:
# 1. Requirements Analysis
# 2. Architecture Design
# 3. Implementation Planning
# 4. Code Implementation
# 5. Testing
# 6. Code Review
# 7. Documentation
```

### Installing More Plugins

```bash
# Browse available plugins
/plugin

# Install a specific plugin
/plugin install pr-review-toolkit@anthropics/claude-plugins-official

# List installed plugins
/plugin list

# Get help on a plugin
/plugin help code-review
```

---

## Agents (Specialists)

### What Are Agents?

Agents are specialized AI personas with deep expertise in specific areas. They're defined in `.claude/agents/` and provide focused knowledge.

### Your Depictio Agents

```
┌─────────────────────────────────────────────────────────────────┐
│                      SPECIALIZED AGENTS                          │
├─────────────┬─────────────┬─────────────┬───────────────────────┤
│             │             │             │                       │
│  API Agent  │ DevOps Agt  │ Test Agent  │     Data Agent        │
│             │             │             │                       │
│  FastAPI    │  Docker     │   pytest    │      Polars           │
│  Beanie     │  Helm       │   async     │    Delta Lake         │
│  REST       │  CI         │  fixtures   │      S3               │
│             │             │             │                       │
├─────────────┼─────────────┴─────────────┴───────────────────────┤
│             │                                                    │
│DevOps Agent │              Security Agent                        │
│             │                                                    │
│  Docker     │              JWT Auth, OWASP                       │
│  Helm       │              Input Validation                      │
│  CI/CD      │              Access Control                        │
│             │                                                    │
└─────────────┴────────────────────────────────────────────────────┘
```

### How Agents Are Selected

Agents are automatically engaged based on your task:

```
YOU: "Create a new endpoint for user dashboards"
     └──▶ API Agent activated
          - Knows FastAPI patterns
          - Suggests Beanie models
          - Follows depictio conventions

YOU: "Add a new chart component"
     └──▶ Dash Agent activated
          - Uses DMC 2.0+ components
          - Ensures theme compatibility
          - Follows callback patterns

YOU: "Is this code secure?"
     └──▶ Security Agent activated
          - Checks for injection vulnerabilities
          - Reviews auth implementation
          - Validates input sanitization
```

### Explicitly Requesting an Agent

You can ask for specific expertise:

```
"Using your API expertise, design a new endpoint for..."
"As a security expert, review this authentication code"
"From a DevOps perspective, how should I structure this Dockerfile?"
```

---

## Workflows (Guided Processes)

### What Are Workflows?

Workflows are step-by-step guides for complex tasks. They're documented in `.claude/workflows/` and provide structured approaches.

### Your Available Workflows

#### 1. Feature Workflow (`workflows/standard-feature-workflow.md`)

```
Phase 1: PLANNING
├── Understand requirements
├── Identify affected components
└── Create task breakdown

Phase 2: IMPLEMENTATION
├── Backend (if needed)
│   ├── Create/update models
│   ├── Add API endpoints
│   └── Write tests
└── Frontend (if needed)
    ├── Create components (DMC 2.0+)
    ├── Add callbacks
    └── Ensure theme compatibility

Phase 3: QUALITY
├── ruff format
├── ruff check
├── ty type check
└── pre-commit

Phase 4: COMMIT
├── Stage changes
├── Write commit message
└── Create PR (optional)
```

#### 2. Bug Fix Workflow (`workflows/bug-fix.md`)

```
1. REPRODUCE → Understand the bug, get steps to reproduce
2. LOCATE    → Find the source code causing the issue
3. ANALYZE   → Root cause analysis
4. FIX       → Implement minimal fix
5. TEST      → Add regression test
6. VALIDATE  → Run full test suite
7. COMMIT    → Create descriptive commit
```

#### 3. API Development (`workflows/api-development.md`)

```
1. DESIGN    → Define endpoint, methods, schemas
2. MODEL     → Create Pydantic models
3. IMPLEMENT → Write route handlers
4. AUTH      → Add authentication/authorization
5. TEST      → Write endpoint tests
6. DOCUMENT  → Update API docs
```

### Using Workflows

Reference workflows when starting a task:

```
"I need to add a feature for exporting dashboards.
 Let's follow the standard-feature workflow."

"There's a bug in the authentication.
 Walk me through the bug-fix workflow."
```

---

## Common Development Scenarios

### Scenario 1: Starting Your Day

```bash
# Start Claude Code
claude

# Check what's happening
/logs api           # Any errors overnight?
/db collections     # Database healthy?
git status          # Any uncommitted work?

# Review your branch
/review             # Review your staged changes
```

### Scenario 2: Adding a New API Endpoint

```bash
# 1. Describe what you need
"I need to add an endpoint for user preferences at /users/{id}/preferences"

# 2. Claude uses the API Agent and workflow
#    - Creates Pydantic model
#    - Implements endpoint
#    - Adds tests

# 3. Validate
/quality            # Check code quality
/test api           # Run API tests

# 4. Commit
/commit             # AI-generated commit message
```

### Scenario 3: Creating a New Dash Component

```bash
# 1. Describe the component
"Create a new stats card component that shows workflow metrics"

# 2. Claude uses Dash Agent
#    - Creates component with DMC 2.0+
#    - Ensures theme compatibility
#    - Adds callbacks

# 3. Verify theme compatibility
"Test this in both light and dark mode"

# 4. Quality check
/quality
```

### Scenario 4: Fixing a Bug

```bash
# 1. Describe the bug
"Users are getting 403 errors when accessing their own dashboards"

# 2. Check logs
/logs api           # Look for error patterns

# 3. Claude investigates
#    - Searches for auth code
#    - Identifies the issue
#    - Proposes fix

# 4. Validate fix
/test               # Run tests
/review             # Review the fix

# 5. Commit
/commit
```

### Scenario 5: Code Review Before PR

```bash
# 1. Run full quality check
/quality

# 2. Run all tests
/test

# 3. Official code review
/code-review        # 5 specialized agents review

# 4. Security check
"Review this code for security vulnerabilities"

# 5. Create PR
/commit-push-pr
```

### Scenario 6: Understanding the Codebase

```bash
# High-level overview
/arch

# Deep dive into specific areas
/arch api           # Backend architecture
/arch dash          # Frontend architecture
/arch flow auth     # Authentication flow

# Ask questions
"How does the data flow from CLI to dashboard?"
"Where is the S3 upload handled?"
```

---

## Tips & Best Practices

### Do's ✅

```bash
# Use skills for common tasks
/quality            # Instead of manually running ruff, ty, etc.
/test api           # Instead of remembering pytest flags

# Let Claude explore
"Find all places where we handle file uploads"
"What's the pattern for adding new components?"

# Use workflows for complex tasks
"Let's follow the standard-feature workflow"
"Walk me through the bug-fix process"

# Leverage code review
/code-review        # Before every PR
/review             # For quick checks
```

### Don'ts ❌

```bash
# Don't skip quality checks
# Always run /quality before committing

# Don't hardcode colors in Dash components
# Use: var(--app-surface-color)
# Not: #ffffff

# Don't bypass hooks
# They're there to protect you

# Don't forget to test both themes
# Light AND dark mode for all UI changes
```

### Productivity Tips

1. **Start sessions with context**
   ```
   "I'm working on the dashboard export feature today.
    The relevant files are in depictio/viewer/src/dashboards/"
   ```

2. **Use natural language**
   ```
   "This test is flaky, help me understand why"
   "Make this code more readable"
   "Is there a better way to do this?"
   ```

3. **Chain operations**
   ```
   "Fix the lint errors, then run the tests, then commit if they pass"
   ```

4. **Ask for explanations**
   ```
   "Explain what this callback does"
   "Why did you choose this approach?"
   ```

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────┐
│                    CLAUDE CODE QUICK REFERENCE                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  QUALITY        /quality, /quality fix, /test                   │
│  GIT            /commit, /commit-push-pr, /code-review          │
│  EXPLORE        /arch, /logs, /db                               │
│  CREATE         /api-endpoint, /model          │
│  PLUGINS        /plugin, /plugin list, /plugin install          │
│  HOOKS          /hookify, /hookify:list                         │
│  FEATURE        /feature-dev                                    │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ENVIRONMENT VARIABLES                                           │
│  GITHUB_TOKEN        Enable GitHub MCP integration              │
│  SLACK_BOT_TOKEN     Enable Slack notifications                 │
│  SENTRY_AUTH_TOKEN   Enable error tracking                      │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  FILES                                                           │
│  .claude/settings.json     Permissions, hooks, plugins          │
│  .claude/mcp.json          MCP server configuration             │
│  .claude/commands/         Custom skills                        │
│  .claude/hooks/            Hook scripts                         │
│  .claude/workflows/        Workflow guides                      │
│  .claude/agents/           Agent definitions                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Next Steps

1. **Try the basics**: Start with `/quality`, `/test`, `/arch`
2. **Use code review**: Run `/code-review` on your next PR
3. **Explore workflows**: Follow the `standard-feature-workflow` for your next task
4. **Customize**: Add your own skills in `.claude/commands/`
5. **Enable GitHub**: Set `GITHUB_TOKEN` for full PR integration

Happy coding! 🚀
