# Standard Feature Development Workflow for Depictio

A complete guide to developing features using Claude Code's full toolkit.

---

## Overview: The Complete Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FEATURE DEVELOPMENT LIFECYCLE                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐       │
│  │ PHASE 1 │──▶│ PHASE 2 │──▶│ PHASE 3 │──▶│ PHASE 4 │──▶│ PHASE 5 │       │
│  │ PLAN    │   │ SETUP   │   │ BUILD   │   │ REFINE  │   │ SHIP    │       │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘       │
│       │             │             │             │             │              │
│       ▼             ▼             ▼             ▼             ▼              │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐       │
│  │ /arch   │   │ branch  │   │ Agents  │   │/quality │   │/code-   │       │
│  │ /db     │   │ /feature│   │ /test   │   │ simplify│   │ review  │       │
│  │ explore │   │ -dev    │   │ iterate │   │ /review │   │/commit  │       │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘   │ PR      │       │
│                                                          └─────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Planning & Discovery

### 1.1 Understand the Codebase Context

```bash
# Start Claude Code
claude

# Explore architecture relevant to your feature
/arch

# If working on specific areas:
/arch api           # Backend architecture
/arch dash          # Frontend architecture
/arch flow auth     # Trace specific flows
```

**Example conversation:**
```
YOU: "I need to add a feature for dashboard templates - users should be
     able to save and share dashboard configurations. Help me understand
     the current dashboard architecture."

CLAUDE: [Uses Explore agent to analyze dashboard models, storage,
         and sharing mechanisms]
```

### 1.2 Check Current State

```bash
# Database state
/db collections
/db query dashboards

# Service health
/logs api
/logs dash
```

### 1.3 Create a Plan

```
YOU: "Based on what we learned, let's plan this feature.
     What components need to change?"

CLAUDE: [Creates structured plan with tasks]

        ## Dashboard Templates Feature Plan

        ### Backend Changes
        1. Create DashboardTemplate model
        2. Add template CRUD endpoints
        3. Add sharing/permissions logic

        ### Frontend Changes
        4. Add "Save as Template" button
        5. Create template browser component
        6. Add "Apply Template" functionality

        ### Tests
        7. API endpoint tests
        8. Model validation tests
```

---

## Phase 2: Branch Setup & Feature Dev Kickoff

### 2.1 Create Feature Branch

```bash
# Create and switch to feature branch
git checkout -b feat/dashboard-templates
```

### 2.2 Start Feature Development Workflow

```bash
# Use the official feature-dev plugin for structured development
/feature-dev
```

This launches a **7-phase guided workflow**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    /feature-dev PHASES                          │
├─────────────────────────────────────────────────────────────────┤
│ Phase 1: Requirements Analysis                                   │
│   └─▶ Clarify scope, acceptance criteria, edge cases            │
│                                                                  │
│ Phase 2: Architecture Design                                     │
│   └─▶ Component design, data flow, API contracts                │
│                                                                  │
│ Phase 3: Implementation Planning                                 │
│   └─▶ Break into tasks, identify dependencies                   │
│                                                                  │
│ Phase 4: Code Implementation                                     │
│   └─▶ Write code with appropriate agents                        │
│                                                                  │
│ Phase 5: Testing                                                 │
│   └─▶ Unit tests, integration tests, manual testing             │
│                                                                  │
│ Phase 6: Code Review                                             │
│   └─▶ Self-review, quality checks                               │
│                                                                  │
│ Phase 7: Documentation                                           │
│   └─▶ Update docs, add comments where needed                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 3: Implementation (Building the Feature)

### 3.1 Backend Development (API Agent)

```
YOU: "Let's start with the backend. Create the DashboardTemplate model."
```

Claude automatically engages the **API Agent**:

```bash
# Claude creates the model
# depictio/models/models/dashboard_templates.py

# You can also use the skill explicitly:
/model DashboardTemplate
```

**What happens:**
- Creates Pydantic model with proper types
- Adds Beanie document class
- Follows depictio conventions
- Hook runs → checks formatting

```
YOU: "Now create the CRUD endpoints for templates."
```

```bash
# Or use the skill:
/api-endpoint dashboard templates CRUD
```

**What happens:**
- Creates route handlers in `depictio/api/v1/endpoints/templates_endpoints/`
- Adds authentication with `get_current_user`
- Implements proper error handling
- Registers router

### 3.2 Run Tests Incrementally

```bash
# After each component, run relevant tests
/test api

# Or test specific file
/test depictio/tests/api/v1/endpoints/templates_endpoints/
```

### 3.3 Frontend Development (Dash Agent)

```
YOU: "Now let's create the template browser component for the frontend."
```

Claude engages the **Dash Agent**:

```bash
# Or use skill:
/dash-component template-browser
```

**What happens:**
- Creates component with DMC 2.0+ (mandatory)
- Ensures theme compatibility (light/dark)
- Uses CSS variables, not hardcoded colors
- Sets up callbacks

```
YOU: "Add the 'Save as Template' button to the dashboard editor."
```

**Theme Check (Automatic via Dash Agent):**
```python
# ✅ CORRECT - Theme-aware
dmc.Button(
    "Save as Template",
    leftSection=DashIconify(icon="mdi:content-save"),
    style={"backgroundColor": "var(--app-primary-color)"}
)

# ❌ WRONG - Hardcoded colors
dmc.Button(
    "Save as Template",
    style={"backgroundColor": "#228be6"}  # NO!
)
```

### 3.4 Iterative Development Loop

```
┌──────────────────────────────────────────────────────────────────┐
│                    DEVELOPMENT ITERATION                          │
│                                                                   │
│    ┌─────────┐      ┌─────────┐      ┌─────────┐                 │
│    │  CODE   │─────▶│  TEST   │─────▶│  FIX    │──┐              │
│    └─────────┘      └─────────┘      └─────────┘  │              │
│         ▲                                          │              │
│         └──────────────────────────────────────────┘              │
│                                                                   │
│    Hooks run automatically:                                       │
│    • post-file-change.sh → Lint check after each edit            │
│    • pre-bash-check.sh → Safety check before commands            │
└──────────────────────────────────────────────────────────────────┘
```

After each edit, you'll see:
```
[Hook] Format issues detected in depictio/dash/modules/template_browser/frontend.py
       Run 'ruff format' to fix
```

---

## Phase 4: Refinement (Quality & Simplification)

### 4.1 Code Quality Check

```bash
# Run full quality suite
/quality

# Output:
# ✓ ruff format: OK
# ✓ ruff check: OK
# ✓ ty check: OK
# ✓ pre-commit: OK
```

If issues found:
```bash
# Auto-fix what's possible
/quality fix
```

### 4.2 Code Simplification

Ask Claude to simplify complex code:

```
YOU: "This callback is getting complex. Can you simplify it?"
```

```
YOU: "Review this function and suggest how to make it more readable."
```

**Claude will:**
- Extract helper functions
- Simplify nested conditions
- Improve variable names
- Add type hints where missing
- Remove duplication

**Example simplification:**
```python
# BEFORE (complex)
def process_template(template_data, user, options):
    if template_data:
        if user:
            if options.get('validate'):
                if validate_template(template_data):
                    return save_template(template_data, user)
                else:
                    raise ValueError("Invalid")
            else:
                return save_template(template_data, user)
    return None

# AFTER (simplified)
def process_template(
    template_data: dict | None,
    user: UserBeanie | None,
    options: dict
) -> TemplateBeanie | None:
    """Process and save a dashboard template."""
    if not template_data or not user:
        return None

    if options.get('validate') and not validate_template(template_data):
        raise ValueError("Invalid template data")

    return save_template(template_data, user)
```

### 4.3 Self Code Review

```bash
# Review your changes
/review

# Output:
# Reviewing staged changes...
#
# ┌─ depictio/models/models/dashboard_templates.py ─────────────┐
# │ ✓ Good: Proper type annotations                            │
# │ ✓ Good: Follows DepictioBaseModel pattern                  │
# │ ⚠ Consider: Add docstring to DashboardTemplate class       │
# └─────────────────────────────────────────────────────────────┘
```

### 4.4 Run Full Test Suite

```bash
# Run all tests
/test

# Specific areas
/test api
/test models
/test dash
```

### 4.5 Security Review (Security Agent)

```
YOU: "Review this code for security vulnerabilities, especially
     the template sharing logic."
```

**Security Agent checks:**
- Authorization on all endpoints
- Input validation
- NoSQL injection risks
- XSS in template content
- Proper permission checks

---

## Phase 5: Ship It (Commit, PR, Review)

### 5.1 Final Quality Gate

```bash
# One final check
/quality

# Run complete test suite
/test
```

### 5.2 Commit with AI Assistance

```bash
# Option 1: AI-generated commit message
/commit

# Claude analyzes changes and suggests:
# ┌─────────────────────────────────────────────────────────────┐
# │ feat(templates): add dashboard template system              │
# │                                                             │
# │ - Add DashboardTemplate model with sharing capabilities     │
# │ - Create CRUD API endpoints for templates                   │
# │ - Add template browser component (DMC 2.0+)                 │
# │ - Add "Save as Template" functionality to dashboard editor  │
# │ - Include comprehensive test coverage                       │
# │                                                             │
# │ Closes #XXX                                                 │
# └─────────────────────────────────────────────────────────────┘
# Proceed? [Y/n]
```

```bash
# Option 2: Commit + Push + Create PR in one command
/commit-push-pr
```

### 5.3 Automated Code Review

```bash
# Run official code review plugin (5 parallel agents)
/code-review
```

**What happens:**
```
┌─────────────────────────────────────────────────────────────────┐
│                    /code-review OUTPUT                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│ ┌─ Compliance Agent ─────────────────────────────────────────┐  │
│ │ ✓ License headers present                                  │  │
│ │ ✓ No dependency issues                                     │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ ┌─ Bug Detection Agent ──────────────────────────────────────┐  │
│ │ ✓ No obvious bugs detected                                 │  │
│ │ ⚠ Consider edge case: empty template name                  │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ ┌─ Security Agent ───────────────────────────────────────────┐  │
│ │ ✓ Auth checks present on all endpoints                     │  │
│ │ ✓ Input validation implemented                             │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ ┌─ Performance Agent ────────────────────────────────────────┐  │
│ │ ✓ No N+1 queries detected                                  │  │
│ │ ⚠ Consider: Add index on template.owner_id                 │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ ┌─ Context Agent ────────────────────────────────────────────┐  │
│ │ ✓ Follows existing patterns                                │  │
│ │ ✓ Consistent with codebase conventions                     │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ Overall: APPROVED with minor suggestions                         │
└─────────────────────────────────────────────────────────────────┘
```

### 5.4 Create Pull Request

```bash
# If not already done with /commit-push-pr:
git push -u origin feat/dashboard-templates

# Then create PR via GitHub
gh pr create --title "feat: add dashboard template system" \
  --body "## Summary
  - Add ability to save dashboards as reusable templates
  - Add template browser and sharing

  ## Test Plan
  - [ ] Unit tests pass
  - [ ] Manual testing of template save/load
  - [ ] Theme compatibility verified"
```

### 5.5 PR Review with GitHub MCP

If you have GitHub MCP configured:

```
YOU: "Show me the comments on PR #123"

YOU: "What changes are requested in the review?"

YOU: "Help me address the review feedback"
```

---

## Complete Session Example

Here's what a complete development session looks like:

```bash
# === MORNING: START SESSION ===
claude

# Check status
/logs api
git status

# === PLANNING ===
/arch
"I need to add dashboard templates. What's the current structure?"
/db query dashboards

# === SETUP ===
git checkout -b feat/dashboard-templates
/feature-dev

# === BACKEND IMPLEMENTATION ===
/model DashboardTemplate
"Add CRUD endpoints for templates with proper auth"
/test api

# === FRONTEND IMPLEMENTATION ===
/dash-component template-browser
"Add save-as-template button to dashboard editor"
"Make sure it works in dark mode"
/test dash

# === REFINEMENT ===
/quality
"Simplify this callback, it's too complex"
/review
"Check for security issues in the sharing logic"

# === SHIP ===
/test
/code-review
/commit-push-pr

# === CLEANUP ===
# Session ends, on-stop hook shows summary
```

---

## Workflow Cheat Sheet

```
┌─────────────────────────────────────────────────────────────────┐
│              DEPICTIO FEATURE WORKFLOW CHEAT SHEET              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PHASE 1: PLAN                                                   │
│  ─────────────────                                               │
│  /arch              Explore architecture                         │
│  /db collections    Check database state                         │
│  /logs <service>    Check service health                         │
│                                                                  │
│  PHASE 2: SETUP                                                  │
│  ─────────────────                                               │
│  git checkout -b feat/xxx                                        │
│  /feature-dev       Start guided workflow                        │
│                                                                  │
│  PHASE 3: BUILD                                                  │
│  ─────────────────                                               │
│  /model             Create Pydantic model                        │
│  /api-endpoint      Create API endpoints                         │
│  /dash-component    Create Dash component                        │
│  /test              Run tests frequently                         │
│                                                                  │
│  PHASE 4: REFINE                                                 │
│  ─────────────────                                               │
│  /quality           Check code quality                           │
│  /quality fix       Auto-fix issues                              │
│  /review            Self code review                             │
│  "simplify this"    Ask for simplification                       │
│  "security review"  Security check                               │
│                                                                  │
│  PHASE 5: SHIP                                                   │
│  ─────────────────                                               │
│  /code-review       5-agent automated review                     │
│  /commit            AI-generated commit                          │
│  /commit-push-pr    Commit + push + PR                           │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  AGENTS (automatic based on context):                            │
│  • API Agent      → Backend/FastAPI tasks                        │
│  • Dash Agent     → Frontend/component tasks                     │
│  • Testing Agent  → Test writing                                 │
│  • Security Agent → Security reviews                             │
│  • Data Agent     → Data processing                              │
│  • DevOps Agent   → Docker/CI/CD                                 │
│                                                                  │
│  HOOKS (automatic):                                              │
│  • post-file-change → Lint check after edits                     │
│  • pre-bash-check   → Block dangerous commands                   │
│  • on-stop          → Session summary                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tips for Efficient Development

### 1. Use Natural Language
```
"Add a button to export templates as JSON"
"This function is slow, help me optimize it"
"Why is this test failing?"
```

### 2. Let Agents Do Their Thing
Claude automatically selects the right agent:
- Mention "endpoint" → API Agent
- Mention "component" → Dash Agent
- Mention "security" → Security Agent

### 3. Iterate Quickly
```
code → /test → fix → /test → /quality → /commit
```

### 4. Use /code-review Before Every PR
It catches issues you might miss.

### 5. Trust the Hooks
They run automatically to keep you safe.

---

## Troubleshooting Common Issues

| Issue | Solution |
|-------|----------|
| Tests failing | `/test` → Read errors → Fix → Repeat |
| Type errors | `/quality` → Check ty output |
| Lint errors | `/quality fix` |
| Theme issues | Check CSS variables, not hardcoded |
| Auth issues | Verify `get_current_user` dependency |
| Hook blocked command | Review why, adjust if needed |

---

**You're now ready to develop features efficiently using the full Claude Code toolkit!**
