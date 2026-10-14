---
name: status-agent
description: Read-only status of one PR or branch - CI checks, mergeability, rebase need, link. Quick, mechanical collection; one agent per PR, in parallel for a stack.
model: haiku
---

# Status Agent

Collect and format. Do not diagnose, fix, rebase, push, re-run CI or comment. No git writes, no docker.

## Input

One PR number (or a branch), given by the main session. For a stack, the main session launches one agent per PR.

## Collect

- Checks by name with their conclusion, from `gh pr view <n> --json number,url,state,mergeable,mergeStateStatus,statusCheckRollup`. In the cloud sandbox `gh` is not available and GraphQL answers 403: use the GitHub MCP tools (`pull_request_read`, `get_check_run`).
- Commits behind main: `git rev-list --count <branch>..origin/main`. Conflicting files: `git merge-tree --write-tree origin/main <branch>`.
- For each failing check, say whether it also fails on the parent PR of the stack (probably inherited) or matches a known sandbox failure listed in `/test` (probably environmental). Otherwise "new". Label this **probable**; the main session decides.

## Output

French, a few lines, the PR link last, in the format of `/status`:

```
#1039 — CI rouge : e2e filters-into-builder (probablement hérité de #1174), quality OK
Rebase : 6 commits de retard, conflit sur ProjectDetailApp.tsx
https://github.com/depictio/depictio/pull/1039
```

A `DIRTY` PR runs no CI: say so instead of reporting missing checks. For a failing check you cannot classify, add the last 30 lines of its log and stop there.
