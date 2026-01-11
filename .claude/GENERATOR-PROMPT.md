# Claude Code Configuration Generator Prompt

Use this prompt in any repository to generate a comprehensive Claude Code development toolkit.

---

## The Prompt

Copy and paste the following prompt when starting Claude Code in a new repository:

---

```
Analyze my codebase and create a comprehensive Claude Code development toolkit. Generate the complete `.claude/` directory structure with all necessary configurations.

## What I Need

Create the following components tailored to MY specific codebase:

### 1. Settings Configuration (`.claude/settings.json`)
- Permissions: Allow safe development commands, deny dangerous operations
- Environment variables specific to my project
- Hook configurations

### 2. Hooks (`.claude/hooks/`)
- `post-file-change.sh`: Run linters/formatters after file edits
- `pre-bash-check.sh`: Block dangerous commands, allow safe ones
- `on-stop-summary.sh`: Session end summary with git status

### 3. Custom Skills/Commands (`.claude/commands/`)
Based on my tech stack, create skills for:
- Code quality checks (linting, formatting, type checking)
- Running tests
- Code review
- Creating new components/modules (following MY patterns)
- Database operations
- Viewing logs
- Architecture exploration

### 4. MCP Servers (`.claude/mcp.json`)
Configure relevant MCP servers:
- GitHub (for PRs, issues)
- Database access (MongoDB, PostgreSQL, etc.)
- File system access
- HTTP fetch for API testing
- Any other relevant integrations

### 5. Specialized Agents (`.claude/agents/`)
Create domain-specific agents based on my tech stack:
- Backend agent (for my backend framework)
- Frontend agent (for my frontend framework)
- Testing agent
- Data processing agent (if applicable)
- DevOps agent
- Security agent

### 6. Workflows (`.claude/workflows/`)
- Standard feature development workflow
- Bug fix workflow
- Full-stack feature workflow (if applicable)
- Any framework-specific workflows

### 7. Documentation
- `README.md`: Overview of all configurations
- `GETTING-STARTED.md`: Comprehensive guide explaining all concepts

## Analysis Steps

1. **Explore my codebase** to understand:
   - Programming languages and frameworks used
   - Project structure and architecture
   - Testing patterns and tools
   - Build/deployment tools
   - Database and storage systems
   - Existing code quality tools (linters, formatters, type checkers)
   - CI/CD configuration

2. **Identify patterns** I use for:
   - Creating new components/modules
   - API endpoint structure
   - Data models
   - Testing conventions
   - Naming conventions

3. **Generate configurations** that:
   - Follow MY existing patterns and conventions
   - Use MY actual tools (not generic ones)
   - Reference MY actual file paths and structures
   - Include MY specific commands and scripts

## Output Requirements

- All hook scripts must be executable (chmod +x)
- All configurations must be valid JSON
- All markdown must be well-formatted
- Include practical examples using MY actual codebase
- Skills should use $ARGUMENTS placeholder for user input
- Agents should reference MY actual code patterns

## After Generation

1. Commit all generated files
2. Push to my current branch
3. Provide a summary of what was created

Start by exploring my codebase to understand its structure and technology stack.
```

---

## Quick Version (Shorter Prompt)

For a faster setup, use this condensed version:

```
Analyze my codebase and generate a complete Claude Code toolkit in `.claude/`:

1. **Explore**: Understand my tech stack, patterns, and tools
2. **Generate**:
   - `settings.json` - Permissions and hooks config
   - `hooks/` - post-file-change, pre-bash-check, on-stop-summary
   - `commands/` - Skills for quality, test, review, create components
   - `mcp.json` - Database, GitHub, fetch servers
   - `agents/` - Backend, frontend, testing, security specialists
   - `workflows/` - Feature dev, bug fix, full-stack workflows
   - `README.md` + `GETTING-STARTED.md`

3. **Customize** everything to MY specific:
   - Frameworks and languages
   - File structure and patterns
   - Tools (linters, test runners, etc.)
   - Naming conventions

4. **Commit** and push when done.

Start by exploring the codebase.
```

---

## Framework-Specific Additions

Add these to the prompt based on your stack:

### Snakemake Workflow Projects
```
Additional Snakemake-specific requirements:
- Skills for:
  - snakemake --lint (workflow linting)
  - snakemake -n --dry-run (dry run validation)
  - snakemake --dag | dot (DAG visualization)
  - snakemake --report (generate reports)
  - snakemake --list-rules (list available rules)
  - snakemake --summary (show output file status)
- Agent expertise:
  - Snakemake rule syntax and best practices
  - Conda/mamba environment management
  - Cluster/cloud execution (SLURM, LSF, AWS, GCP)
  - Workflow modularization (rules/, scripts/, envs/)
  - Config file management (config.yaml, profiles/)
  - Wildcards, expand(), input functions
  - Checkpoint rules for dynamic DAGs
  - Resource management (threads, mem_mb, runtime)
- Workflows:
  - New rule development workflow
  - Pipeline debugging workflow
  - Performance optimization workflow
- Hooks:
  - Snakemake lint after .smk file edits
  - Config validation after config.yaml changes
- MCP servers:
  - File system for large data directories
  - Cluster job monitoring (if applicable)
```

### Python Projects
```
Additional Python-specific requirements:
- Skills for: pytest, ruff/black, mypy/pyright, pre-commit
- Agent expertise: FastAPI/Django/Flask, SQLAlchemy/Beanie, Pydantic
- Hook: Type checking after Python file edits
```

### Node.js/TypeScript Projects
```
Additional Node.js-specific requirements:
- Skills for: npm/yarn/pnpm, jest/vitest, eslint, tsc
- Agent expertise: Express/Nest/Next.js, Prisma/TypeORM
- Hook: ESLint check after TypeScript file edits
```

### React/Vue/Angular Projects
```
Additional frontend-specific requirements:
- Skills for: Component generation, Storybook, testing-library
- Agent expertise: State management, routing, styling patterns
- Workflow: Component development with design system compliance
```

### Go Projects
```
Additional Go-specific requirements:
- Skills for: go test, golangci-lint, go mod
- Agent expertise: Standard library patterns, concurrency
- Hook: go fmt after Go file edits
```

### Rust Projects
```
Additional Rust-specific requirements:
- Skills for: cargo test, clippy, rustfmt
- Agent expertise: Ownership patterns, async/await, error handling
- Hook: cargo check after Rust file edits
```

### DevOps/Infrastructure
```
Additional DevOps-specific requirements:
- Skills for: Docker, Kubernetes, Terraform, Ansible
- Agent expertise: CI/CD pipelines, infrastructure as code
- Workflow: Infrastructure change with plan/apply pattern
```

---

## Complete Snakemake Project Prompt

For Snakemake/bioinformatics workflow projects, use this complete prompt:

```
Analyze my Snakemake workflow project and create a comprehensive Claude Code
development toolkit in `.claude/`.

## My Project Type
This is a Snakemake bioinformatics/data science workflow project.

## Generate These Components

### 1. Settings (`.claude/settings.json`)
Permissions for:
- snakemake commands (lint, dry-run, run, report, dag)
- conda/mamba commands
- cluster submission tools (if applicable: sbatch, bsub, qsub)
- Python scripts execution
- pytest for testing
- ruff/black for Python formatting
- git operations

### 2. Hooks (`.claude/hooks/`)
- `post-file-change.sh`:
  - Run snakemake --lint after .smk file edits
  - Run ruff check after .py script edits
  - Validate config.yaml syntax after config changes
- `pre-bash-check.sh`: Block dangerous rm commands on data directories
- `on-stop-summary.sh`: Show workflow status and pending jobs

### 3. Skills (`.claude/commands/`)
Create skills for:
- `/lint` - Run snakemake --lint on workflow
- `/dry-run` or `/validate` - Run snakemake -n to validate DAG
- `/dag` - Generate and display workflow DAG
- `/run` - Execute workflow with common options
- `/status` - Show job status and output file summary
- `/report` - Generate snakemake HTML report
- `/rules` - List and explain available rules
- `/test` - Run pytest on workflow tests
- `/quality` - Run all quality checks (lint, ruff, tests)
- `/new-rule` - Create a new rule following my patterns
- `/debug` - Debug a failing rule
- `/profile` - Analyze workflow performance

### 4. MCP Servers (`.claude/mcp.json`)
- GitHub for repository operations
- Filesystem for data directory access
- Fetch for downloading reference data

### 5. Agents (`.claude/agents/`)
- **Snakemake Agent**: Rule syntax, wildcards, expand(), input functions,
  checkpoints, resource management, cluster config
- **Bioinformatics Agent**: Tool expertise (samtools, bwa, STAR, etc.),
  file formats (BAM, VCF, FASTQ), best practices
- **Conda Agent**: Environment management, dependency resolution,
  reproducibility
- **Cluster Agent**: SLURM/LSF/PBS configuration, job optimization,
  resource allocation
- **Testing Agent**: Workflow testing strategies, test data management
- **Performance Agent**: Benchmarking, bottleneck identification,
  parallelization optimization

### 6. Workflows (`.claude/workflows/`)
- **new-rule.md**: Adding a new rule to the workflow
- **debug-rule.md**: Debugging a failing rule
- **optimize-workflow.md**: Performance optimization
- **add-tool.md**: Integrating a new bioinformatics tool
- **cluster-setup.md**: Configuring cluster execution

### 7. Documentation
- README.md with all configurations
- GETTING-STARTED.md with Snakemake-specific examples

## Analysis Steps

1. **Explore my workflow structure**:
   - Main Snakefile location
   - Rules organization (rules/*.smk)
   - Config files (config/*.yaml)
   - Conda environments (envs/*.yaml)
   - Scripts directory (scripts/*.py, scripts/*.R)
   - Cluster profiles (profiles/*)

2. **Identify my patterns**:
   - Rule naming conventions
   - Wildcard patterns
   - Resource specifications
   - Log file organization
   - Benchmark tracking

3. **Generate configurations** that match MY:
   - Directory structure
   - Naming conventions
   - Cluster/execution environment
   - Tool versions and environments

## After Generation
Commit all files and push to my branch.

Start by exploring my Snakemake workflow structure.
```

---

## Example Usage

```bash
# 1. Navigate to your project
cd /path/to/my-project

# 2. Start Claude Code
claude

# 3. Paste the prompt above

# 4. Claude will:
#    - Explore your codebase
#    - Generate all configurations
#    - Commit and push

# 5. Start using your new toolkit
/quality          # Run code quality checks
/test             # Run tests
/arch             # Explore architecture
/commit           # AI-assisted commit
```

---

## Customization Tips

### Add Project-Specific Context

Include any special requirements in your prompt:

```
Additional context for my project:
- We use [specific tool] for [purpose]
- Our code style guide requires [specific rules]
- We have a monorepo with [packages/services]
- Our CI runs on [platform] with [specific checks]
- Database is [type] at [connection info]
```

### Specify Forbidden Operations

```
Safety requirements:
- Never run [specific dangerous commands]
- Block operations on [protected paths/resources]
- Require confirmation for [specific actions]
```

### Define Team Conventions

```
Team conventions to follow:
- Commit messages must follow [format]
- PRs require [specific checks]
- Code must pass [quality gates] before commit
- [Specific naming conventions]
```

---

## What Gets Generated

After running the prompt, you'll have:

```
.claude/
├── settings.json           # Permissions, env vars, hooks
├── mcp.json               # External tool integrations
├── README.md              # Configuration overview
├── GETTING-STARTED.md     # Comprehensive usage guide
├── hooks/
│   ├── post-file-change.sh
│   ├── pre-bash-check.sh
│   └── on-stop-summary.sh
├── commands/
│   ├── quality.md         # /quality
│   ├── test.md            # /test
│   ├── review.md          # /review
│   └── [framework-specific].md
├── agents/
│   ├── backend-agent.md
│   ├── frontend-agent.md
│   ├── testing-agent.md
│   └── [domain-specific].md
└── workflows/
    ├── new-feature.md
    ├── bug-fix.md
    └── [framework-specific].md
```

---

## Maintenance

After initial setup, you can:

```bash
# Add new skill
"Create a new skill for [purpose]"

# Add new agent
"Create an agent specialized in [domain]"

# Update hooks
"Add a hook that [does something]"

# Add workflow
"Create a workflow for [process]"
```

The toolkit grows with your project!
