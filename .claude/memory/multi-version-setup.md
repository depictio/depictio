# Multi-Version Setup Pattern for Bug Bisection

## Purpose
Clone and configure multiple Depictio versions to run simultaneously for manual bug bisection.

## Full Setup Steps for a New Version/Branch

### 1. Clone with LFS skip
```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/depictio/depictio depitio-<name>
```

### 2. Checkout
For tags: `git checkout -b local/<version> <tag>` (avoids detached HEAD)
For branches: `git fetch origin <branch> && git checkout -b <branch> origin/<branch>`

### 3. Fix broken LFS files
```bash
cp /path/to/depitio-0.7.4/docs/images/{favicon,logo_hd,logo_hd_white}.svg docs/images/
```
LFS server returns 404 for these objects.

### 4. Generate port config
```bash
source .devcontainer/scripts/allocate-ports.sh
```
This creates `.env.instance` and `docker-compose.override.yaml`.

### 5. Fix single-user mode
Append to `.env.instance` if missing:
```
DEPICTIO_AUTH_SINGLE_USER_MODE=true
```

### 6. Regenerate docker-compose.override.yaml
The allocate-ports.sh output is missing SINGLE_USER_MODE (versions before v0.8.0-b1).
Regenerate cleanly using heredoc reading COMPOSE_PROJECT_NAME, FASTAPI_PORT, DASH_PORT from .env.instance.

Template:
```yaml
services:
  mongo:
    container_name: ${COMPOSE_PROJECT}-mongo
  redis:
    container_name: ${COMPOSE_PROJECT}-redis
  minio:
    container_name: ${COMPOSE_PROJECT}-minio
  depictio-frontend:
    container_name: ${COMPOSE_PROJECT}-depictio-frontend
    environment:
      - DEPICTIO_FASTAPI_EXTERNAL_PORT=${FASTAPI_PORT}
      - DEPICTIO_DASH_EXTERNAL_PORT=${DASH_PORT}
      - DEPICTIO_DEV_MODE=true
      - DEPICTIO_MONGODB_WIPE=false
      - DEPICTIO_AUTH_SINGLE_USER_MODE=true
  depictio-backend:
    container_name: ${COMPOSE_PROJECT}-depictio-backend
    environment:
      - DEPICTIO_DEV_MODE=true
      - DEPICTIO_MONGODB_WIPE=false
      - DEPICTIO_AUTH_SINGLE_USER_MODE=true
  depictio-celery-worker:
    container_name: ${COMPOSE_PROJECT}-depictio-celery-worker
    environment:
      - DEPICTIO_DEV_MODE=true
      - DEPICTIO_MONGODB_WIPE=false
      - DEPICTIO_AUTH_SINGLE_USER_MODE=true
```

### 7. Symlink .env
```bash
rm -f .env && ln -sf .env.instance .env
```

### 8. Launch
```bash
source .env.instance && docker-compose -p ${COMPOSE_PROJECT_NAME} --env-file .env.instance -f docker-compose.dev.yaml -f docker-compose.override.yaml up -d --force-recreate
```

## Gotchas
- macOS sed doesn't support `\n` in replacement — always use cat heredoc
- `docker-compose` (hyphenated) works on this machine, NOT `docker compose` (space)
- allocate-ports.sh hash can collide (e.g., v0.7.6-b1 and v0.7.6 both got 125) — manually fix offset if needed
- v0.7.4 was originally set up with empty branch name causing double-dash container names — fixed by setting COMPOSE_PROJECT_NAME to depictio-v0-7-4
