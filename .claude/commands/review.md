# Code Review Helper

Review a change. For a full multi-pass review prefer the `/code-review` plugin skill; this is the quick local version.

## Scope

No argument: `git diff` and `git diff --cached`. A file path: that file. `pr <number>`: `gh pr diff <number>`.

## Check, in priority order

1. **Security**: auth dependency and permission check on every route, NoSQL injection, path traversal, secrets in logs (see `security-agent`).
2. **Invariants** from `/CLAUDE.md` that the diff touches: dashboard versioning (baseline before and capture after a content write, `TabSnapshot` coverage), storage families, component ids from tags, YAML changes with their `.db_seeds/*.json` regenerated, editor not writing before a user action, Mantine theming without hardcoded colors.
3. **Types**: `depictio/models/` must stay `ty`-clean; no new debt in `api/` or `cli/`.
4. **Correctness and performance**: None handling, missing `await`, N+1 queries, reading whole Delta tables where a projection would do.
5. **Tests**: a test for the new behaviour, including the error path.

Report by severity (Critical, Warning, Info) with `file:line` and a concrete fix.

$ARGUMENTS
