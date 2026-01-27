# Git Worktree + Multi-Instance DevContainer Workflow

This document explains how to use git worktrees with Depictio's multi-instance devcontainer system to work on multiple branches simultaneously without conflicts.

## Overview

Each git worktree (branch) gets its own:
- **Unique container names**: `depictio-{branch-name}-mongo`, etc.
- **Unique ports**: Automatically assigned based on branch type
- **Isolated data**: Separate databases, MinIO storage, Redis data
- **Independent VS Code window**: Full development environment per branch

## Quick Start

### 1. Create Worktrees

```bash
# From your main repository
cd ~/projects/depictio

# Create worktrees for different branches
git worktree add ../depictio-wt-main main
git worktree add ../depictio-wt-feat-figure feat/figure-component
git worktree add ../depictio-wt-auth feat/auth-refactor
```

### 2. Open in VS Code

```bash
# Open each worktree in a separate VS Code window
code ~/projects/depictio-wt-main
code ~/projects/depictio-wt-feat-figure
code ~/projects/depictio-wt-auth
```

### 3. Let DevContainer Build

Each VS Code window will:
1. Detect the git branch automatically
2. Allocate unique ports based on branch name
3. Create instance-specific data directories
4. Build and start all services with no conflicts

### 4. Access Services

Each instance gets unique external ports:

**Main Branch** (offset: 0):
- FastAPI: `http://localhost:8000`
- Dash: `http://localhost:5000`
- MinIO Console: `http://localhost:9001`

**Feature Branch** (offset: varies, e.g., 42):
- FastAPI: `http://localhost:8042`
- Dash: `http://localhost:5042`
- MinIO Console: `http://localhost:9043`

Check the post-create output in each devcontainer terminal for exact ports.

## Port Allocation Strategy

Ports are assigned deterministically based on branch type:

### Main Branch
```
Offset: 0
MongoDB:    27000
Redis:      6000
FastAPI:    8000
Dash:       5000
MinIO:      9000
Console:    9001
```

### Feature Branches (`feat/*`)
```
Offset: 10-89 (hash-based)
Example: feat/figure-component → offset 42
MongoDB:    27042
Redis:      6042
FastAPI:    8042
Dash:       5042
MinIO:      9042
Console:    9043
```

### Hotfix Branches (`hotfix/*`)
```
Offset: 90-99 (hash-based)
Example: hotfix/crash-fix → offset 93
MongoDB:    27093
FastAPI:    8093
```

### Release Branches (`release/*`)
```
Offset: 100-109 (hash-based)
```

### Other Branches
```
Offset: 110-149 (hash-based)
```

## Data Isolation

Each branch gets its own data directory:

```
depictio/
├── data/
│   ├── depictio-main/
│   │   ├── depictioDB/          # MongoDB data for main
│   │   ├── minio_data/          # MinIO storage for main
│   │   ├── redis/               # Redis data for main
│   │   └── cache/               # App cache for main
│   │
│   ├── depictio-feat-figure-component/
│   │   ├── depictioDB/          # Separate MongoDB data
│   │   ├── minio_data/          # Separate MinIO storage
│   │   └── ...
│   │
│   └── depictio-feat-auth-refactor/
│       └── ...
```

## Typical Workflows

### Scenario 1: Parallel Feature Development

```bash
# Terminal 1 - UI work
cd ~/projects/depictio-wt-feat-figure
code .
# VS Code opens, devcontainer starts on ports 8042, 5042, etc.
# Work on figure component UI

# Terminal 2 - Backend work
cd ~/projects/depictio-wt-auth
code .
# VS Code opens, devcontainer starts on ports 8067, 5067, etc.
# Work on authentication backend

# Both running simultaneously, no conflicts!
```

### Scenario 2: Testing Migration on Feature Branch

```bash
# Terminal 1 - Production-like main branch
cd ~/projects/depictio-wt-main
code .
# Database has production-like data

# Terminal 2 - Feature branch with migration
cd ~/projects/depictio-wt-feat-schema-change
code .
# Test migration on isolated database
# If it breaks, main branch is unaffected
```

### Scenario 3: Quick Hotfix While Working on Feature

```bash
# Already working on feature branch
cd ~/projects/depictio-wt-feat-big-feature
# Services running on ports 8042, 5042

# Urgent hotfix needed!
cd ~/projects
git worktree add depictio-wt-hotfix-urgent hotfix/urgent-fix
code depictio-wt-hotfix-urgent
# New devcontainer starts on ports 8093, 5093
# Fix bug, test, commit, PR

# Return to feature work - still running on 8042, 5042
```

## Instance Configuration Files

### `.env.instance` (Auto-generated, Git-ignored)

Created by `.devcontainer/scripts/allocate-ports.sh`:

```bash
# Auto-generated instance configuration
# Branch: feat/figure-component
# Generated: 2026-01-08 21:30:00 UTC

COMPOSE_PROJECT_NAME=depictio-feat-figure-component
INSTANCE_ID=feat-figure-component-42
BRANCH_NAME=feat/figure-component
PORT_OFFSET=42

# Port assignments
MONGO_PORT=27042
REDIS_PORT=6042
FASTAPI_PORT=8042
DASH_PORT=5042
MINIO_PORT=9042
MINIO_CONSOLE_PORT=9043

# Data directory
DATA_DIR=data/depictio-feat-figure-component
```

### `.env` (Auto-generated, Git-ignored)

Combined configuration for Docker Compose:
- Includes all variables from `.env.instance`
- Includes variables from `docker-compose/.env`
- Read automatically by `docker compose`

## Container Naming

Each instance gets unique container names:

```bash
# Main branch
mongo-depictio-main
redis-depictio-main
depictio-backend-depictio-main
depictio-frontend-depictio-main
minio-depictio-main

# Feature branch
mongo-depictio-feat-figure-component
redis-depictio-feat-figure-component
depictio-backend-depictio-feat-figure-component
depictio-frontend-depictio-feat-figure-component
minio-depictio-feat-figure-component
```

## Managing Worktrees

### List All Worktrees

```bash
git worktree list
```

### Remove a Worktree

```bash
# Remove worktree directory and registration
git worktree remove ~/projects/depictio-wt-old-feature

# Or manually delete directory, then prune
rm -rf ~/projects/depictio-wt-old-feature
git worktree prune
```

### Clean Up Orphaned Data

```bash
# Remove data for deleted worktree
rm -rf data/depictio-feat-old-feature
```

## Troubleshooting

### Port Already in Use

If you get "port already in use" errors:

```bash
# Check which instance is using the port
docker ps | grep 8042

# If it's a stale container, stop it
docker compose -f docker-compose.dev.yaml \
    -f docker-compose/docker-compose.minio.yaml \
    -f .devcontainer/docker-compose.devcontainer.yaml \
    down

# Or stop specific containers
docker stop depictio-backend-depictio-feat-figure-component
```

### Instance Configuration Not Found

If `.env.instance` is missing:

```bash
# Recreate it
.devcontainer/scripts/allocate-ports.sh

# Or rebuild devcontainer
# VS Code Command Palette: Dev Containers: Rebuild Container
```

### Wrong Ports After Branch Switch

If you switch branches in an existing worktree:

```bash
# Regenerate instance configuration
rm .env.instance .env
.devcontainer/scripts/allocate-ports.sh

# Rebuild containers
docker compose down
# VS Code: Dev Containers: Rebuild Container
```

### Data Directory Permissions

If you get permission errors:

```bash
# Fix permissions for current instance
source .env.instance
sudo chown -R $(id -u):$(id -g) "data/${COMPOSE_PROJECT_NAME}"
chmod -R 775 "data/${COMPOSE_PROJECT_NAME}"
```

## Advanced Usage

### Sharing Data Between Instances

If you need to copy data from one instance to another:

```bash
# Copy MongoDB data from main to feature branch
source .env.instance  # In feature branch worktree
FEATURE_DATA="data/${COMPOSE_PROJECT_NAME}"

# Stop feature branch containers
docker compose down

# Copy main data
cp -r data/depictio-main/depictioDB/* "${FEATURE_DATA}/depictioDB/"

# Restart
docker compose up -d
```

### Custom Port Offsets

To force a specific port offset:

```bash
# Edit .devcontainer/scripts/allocate-ports.sh
# Add custom branch handling:
case "$BRANCH_NAME" in
  "my-special-branch")
    PORT_OFFSET=200
    ;;
  # ... rest of cases
esac
```

### Running Without DevContainer

To use worktrees without VS Code DevContainer:

```bash
cd ~/projects/depictio-wt-feat-figure

# Generate instance config
.devcontainer/scripts/allocate-ports.sh

# Source it
source .env

# Start services
docker compose -f docker-compose.dev.yaml \
    -f docker-compose/docker-compose.minio.yaml \
    up -d
```

## Benefits Summary

✅ **No Port Conflicts**: Each branch gets unique ports
✅ **Data Isolation**: Separate databases per branch
✅ **Parallel Development**: Work on multiple features simultaneously
✅ **Safe Testing**: Break things in feature branches without affecting main
✅ **Easy Comparison**: Run multiple versions side-by-side
✅ **Fast Context Switching**: Just switch VS Code windows
✅ **Clean Separation**: Each branch has its own complete environment

## Files Reference

- `.devcontainer/scripts/allocate-ports.sh` - Port allocation logic
- `.devcontainer/pre_create_setup.sh` - Instance initialization
- `.devcontainer/post_create_setup.sh` - Service readiness checks
- `docker-compose.dev.yaml` - Service definitions with dynamic ports
- `docker-compose/docker-compose.minio.yaml` - MinIO with dynamic ports
- `.devcontainer/docker-compose.devcontainer.yaml` - DevContainer service
- `.env.instance` - Generated instance configuration
- `.env` - Combined environment for Docker Compose

## See Also

- [Official Git Worktree Documentation](https://git-scm.com/docs/git-worktree)
- [VS Code DevContainers Documentation](https://code.visualstudio.com/docs/devcontainers/containers)
- [Docker Compose Environment Variables](https://docs.docker.com/compose/environment-variables/)
