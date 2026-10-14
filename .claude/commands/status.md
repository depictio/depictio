# Status

Report where a branch or PR stands, in one short block. The user asks this at the end of nearly every session.

`/status` — current branch's PR. `/status 1038 1039` — those PRs.

$ARGUMENTS

## What to collect, per PR

- **CI**: each check by name with its conclusion. For a failure, say whether it is new, inherited from the parent PR of a stack, or environmental (see the known failures in `/test`).
- **Mergeability**: `mergeable` and `mergeStateStatus`. A `DIRTY` PR runs no CI at all, so a missing CI means rebase first.
- **Rebase needed**: how many commits behind main, and which files conflict (`git merge-tree`).
- **Link**: the PR URL.

`gh pr view <n> --json number,url,state,mergeable,mergeStateStatus,statusCheckRollup` locally. In the cloud sandbox `gh` is not available and GraphQL answers 403: use the GitHub MCP tools (`pull_request_read`, `get_check_run`).

For two or more PRs, launch one `status-agent` (Haiku, read-only) per PR in parallel and assemble their blocks. A single PR is quicker to collect directly.

## Output

French, a few lines per PR, the link last. Open with one of three words so nobody has to guess what happened: **implémenté** (code changed and pushed), **vérifié** (ran it, say how and where) or **lu seulement** (nothing changed).

```
#1039 — CI rouge : e2e filters-into-builder (hérité de #1174), quality OK
Rebase : 6 commits de retard, conflit sur ProjectDetailApp.tsx
https://github.com/depictio/depictio/pull/1039
```

$ARGUMENTS
