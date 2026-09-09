# Depictio DevContainer

Universal development environment that works locally and in GitHub Codespaces.

## 🚀 Quick Start

### Local Development

```bash
# Option 1: Main repo (standard development)
cd depictio
code .
# Reopen in Container

# Option 2: Worktree (parallel development)
git worktree add ../depictio-worktrees/feat-my-feature
cd ../depictio-worktrees/feat-my-feature
code .
# Reopen in Container
```

### GitHub Codespaces

Click the "Code" button → "Create codespace on [branch]"

Everything works automatically!

## 🔌 Services & Ports

The devcontainer automatically starts all services:

| Service | Internal Port | Local Access | Description |
|---------|--------------|--------------|-------------|
| MongoDB | 27018 | `localhost:27018` (local) / Auto-forwarded (Codespaces) | Database |
| Redis | 6379 | `localhost:6379` | Cache |
| FastAPI | 8058 | `localhost:8058` | Backend API |
| Dash | 5080 | `localhost:5080` | Frontend UI |
| S3 (SeaweedFS) | 9000 | `localhost:9000` | S3 Storage |
| S3 admin UI | 9001 | `localhost:9001` | Storage UI (SeaweedFS) |

**Local worktrees**: Each branch gets unique ports (offset by 10-150) to avoid conflicts.
**Codespaces**: Uses standard ports, accessed via GitHub's proxy URLs.

## 🌳 Worktree Features (Local Only)

When using git worktrees locally, you get automatic:
- ✅ Branch-based port allocation (no conflicts)
- ✅ Instance-specific data directories
- ✅ Isolated databases per branch
- ✅ Git integration in devcontainer

**Note**: Worktree features gracefully degrade in Codespaces (single-branch mode).

## 🛠️ Environment Configuration

### Auto-Generated (Codespaces & First Run)

If `docker-compose/.env` doesn't exist, a default is created automatically with:
- Development mode enabled
- S3 credentials: `minio` / `minio123`
- Debug logging
- OAuth disabled

### Custom Configuration (Local Dev)

For local development with OAuth, custom keys, etc., create `docker-compose/.env`:

```bash
# See docker-compose/.env in main repo for full example
DEPICTIO_AUTH_GOOGLE_OAUTH_ENABLED=true
DEPICTIO_AUTH_GOOGLE_OAUTH_CLIENT_ID="your-client-id"
DEPICTIO_AUTH_GOOGLE_OAUTH_CLIENT_SECRET="your-secret"
```

## 📦 What Gets Installed

- All project dependencies (via `uv sync --extra dev`)
- Test dependencies: pytest, mongomock-motor, pytest-asyncio
- Dev tools: ruff, ty, pre-commit
- depictio-cli (from GitHub)

## 🔍 Troubleshooting

### Tests not discovering

If pytest can't find `mongomock_motor`:
1. Reload VS Code window: `Cmd+Shift+P` → "Developer: Reload Window"
2. If still broken: Rebuild container

### Git not working (Local worktree)

If git panel is empty:
1. Check logs in devcontainer build output for git configuration messages
2. Rebuild container

### Services not starting

Check service health:
```bash
docker ps  # See which containers are running
docker logs <container-name>  # Check specific service logs
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│ DevContainer (app)                                      │
│ - Python environment (.venv)                            │
│ - VS Code extensions                                    │
│ - Development tools                                     │
│ - Source code at /workspace                             │
└─────────────────────────────────────────────────────────┘
              │
              │ Docker Network
              ▼
┌─────────────────────────────────────────────────────────┐
│ Services (docker-compose)                               │
│ ┌─────────┐ ┌─────────┐ ┌────────┐ ┌─────────────────┐│
│ │ MongoDB │ │  Redis  │ │  S3    │ │ FastAPI + Dash  ││
│ └─────────┘ └─────────┘ └────────┘ └─────────────────┘│
└─────────────────────────────────────────────────────────┘
```

All services communicate via container names (e.g., `mongo:27018`, `minio:9000`).

## 📝 Files

- `devcontainer.json` - Main configuration
- `Dockerfile` - Container image
- `docker-compose.devcontainer.yaml` - DevContainer service definition
- `pre_create_setup.sh` - Port allocation & directory setup
- `post_create_setup.sh` - Dependency installation
- `fix_git_worktree.sh` - Git initialization for worktrees
- `scripts/allocate-ports.sh` - Branch-based port allocation logic
