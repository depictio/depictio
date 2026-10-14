# PR stack

Bring a stack of PRs (each branch on top of the previous one) up to date with main and keep every member mergeable.

`/pr-stack` — the stack the current branch belongs to. `/pr-stack 1174 1180` — those PRs, bottom first.

$ARGUMENTS

## Rules

- Rewrite history only on branches this user's agents created. Never on someone else's branch, never on main.
- Each push needs an explicit go from the user; one "go" covers the push it was asked about.
- Never hand-merge `uv.lock` or `pnpm-lock.yaml`: take main's, then regenerate (`uv lock`, `pnpm install --lockfile-only`).
- No empty commit or close/reopen to kick CI.

## Steps

1. `git fetch origin`, then list the stack bottom to top.
2. **Dry-run each branch against main**: `git merge-tree --write-tree origin/main <branch>`. Note which files conflict. The recurring ones: `EditorApp.tsx`, `App.tsx`, `ProjectDetailApp.tsx`, `local_stack.py` (`INHERITED_SETTINGS`), `pyproject.toml` (`testpaths`, extras), generated catalog snapshots, and the tests that guard them.
3. **Pick the method**: `git rebase --update-refs origin/main` from the top branch when few commits replay. When more than about 20 commits replay with the same conflict over and over, merge main into the branch instead.
4. Resolve, regenerate lockfiles and snapshots, then `/preflight` on **each** branch of the stack.
5. Push with `--force-with-lease` after the go. If the stack is linked (`gh stack`), unstack before changing a base and link again afterwards.
6. Check every PR is mergeable (a `DIRTY` one silently runs no CI) and report with `/status`.
