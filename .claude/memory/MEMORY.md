# Project Memory

## Multi-Version Clone Setup Pattern

See [multi-version-setup.md](multi-version-setup.md) for full details.

**Quick reference** — to clone & configure a new version/branch:
1. `GIT_LFS_SKIP_SMUDGE=1 git clone <repo> <dir>`
2. Checkout tag via local branch (or fetch remote branch)
3. Copy real SVGs from `depitio-0.7.4/docs/images/` (LFS server returns 404)
4. `source .devcontainer/scripts/allocate-ports.sh`
5. Regenerate `docker-compose.override.yaml` cleanly (allocate-ports.sh output is missing SINGLE_USER_MODE and may have issues)
6. Append `DEPICTIO_AUTH_SINGLE_USER_MODE=true` to `.env.instance` if missing
7. `rm -f .env && ln -sf .env.instance .env`
8. Launch: `source .env.instance && docker-compose -p ${COMPOSE_PROJECT_NAME} --env-file .env.instance -f docker-compose.dev.yaml -f docker-compose.override.yaml up -d --force-recreate`

**Key gotchas:**
- macOS `sed` doesn't support `\n` in replacement strings — use heredoc/cat to regenerate files instead
- `allocate-ports.sh` needs `git branch --show-current` to work — use local branches, not detached HEAD
- Port offset 110-149 range is for unknown branch types (hash-based, collisions possible)
- `docker-compose` (hyphenated) works, not `docker compose` (space) on this machine
- All 3 services need SINGLE_USER_MODE in override: frontend, backend, celery-worker

## Existing Workspace Versions

Located in `/Users/tweber/Gits/workspaces/depictio-workspace/`:

| Directory | Version/Branch | Dash | API | Offset |
|-----------|---------------|------|-----|--------|
| depitio-0.7.4 | v0.7.4 | 5111 | 8111 | 111 |
| depitio-0.7.5-b1 | v0.7.5-b1 | 5143 | 8143 | 143 |
| depitio-0.7.5-b2 | v0.7.5-b2 | 5126 | 8126 | 126 |
| depitio-0.7.5 | v0.7.5 | 5117 | 8117 | 117 |
| depitio-0.7.6-b1 | v0.7.6-b1 | 5125 | 8125 | 125 |
| depitio-0.7.6 | v0.7.6 | 5130 | 8130 | 130 |
| depitio-0.8.0-b1 | v0.8.0-b1 | 5114 | 8114 | 114 |
| depitio-claude-python-bioinformatics-setup | claude/python-bioinformatics-setup-SVaj0 | 5138 | 8138 | 138 |
