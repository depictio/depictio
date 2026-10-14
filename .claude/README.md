# Claude Code configuration

Project instructions are in `/CLAUDE.md` (source of truth). This directory holds the tooling around them.

## Contents

| Path | Purpose |
| --- | --- |
| `settings.json` | Shared permissions, env, enabled plugins, hooks. `settings.local.json` is a personal overlay |
| `mcp.json` | MCP servers (GitHub, MongoDB at `localhost:27018`, filesystem, fetch, memory, sequential-thinking; Slack and Sentry disabled) |
| `hooks/post-file-change.sh` | After Write/Edit on Python under `depictio/`: `ruff format --check` and `ruff check` hints |
| `hooks/pre-bash-check.sh` | Blocks destructive patterns (docker rm/prune, mongo drop, force-push to main, ...) |
| `hooks/on-stop-summary.sh` | Git status and lint summary at the end of a session |
| `agents/` | `api-agent` (backend), `viewer-agent` (React SPA), `testing-agent`, `security-agent` |
| `workflows/` | `new-feature.md` (backend + viewer + seeds + gates), `bug-fix.md` |
| `commands/` | Slash commands, below |
| `memory/MEMORY.md` | Pointer only; lessons live in CLAUDE.md |

## Slash commands

- Quality: `/quality`, `/test`, `/review`, `/preflight`
- Verify and report: `/dev-stack` (server + public tunnel, `scripts/dev_tunnel.sh`), `/status` (CI, mergeability, link), `/pr-stack` (rebase a stack of PRs)
- Scaffolding: `/api-endpoint`, `/pydantic-model`, `/validate-dashboard`
- Data and projects: `/import-project`, `/import-template`, `/reseed`
- Inspection: `/arch`, `/logs`, `/db`, `/check-deployment`
- Git and release: `/commit`, `/commit-push`, `/commit-push-pr`, `/bump-version`, `/bump-docs-version`, `/new-worktree`, `/worktree-gc`, `/cli-venv`
- EMBL deployment: `/depictio-embl-admin-login`

A command is a markdown file in `commands/`; `$ARGUMENTS` receives what follows the command name.

## Notes

- Hooks need `jq`. They must be executable (`chmod +x .claude/hooks/*.sh`).
- Docker: Claude may only run `docker logs` (CLAUDE.md); `settings.json` denies `docker compose up/down/restart`, `docker exec` and removals.
- Keep these files short and point to CLAUDE.md instead of copying from it, otherwise they go stale (the Dash-era files did).
