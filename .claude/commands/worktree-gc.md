# Worktree GC

Free the disk that finished worktrees keep: virtualenvs, `node_modules` and the per-instance `data/` (several GB each once the showcases are seeded).

`/worktree-gc` — dry run, lists what is reclaimable and why. `/worktree-gc apply` — delete the heavy directories. `/worktree-gc remove` — also remove the merged worktrees.

$ARGUMENTS

## Steps

1. Run `scripts/worktree_gc.sh` (dry run). It fetches with `--prune` first; add `--no-fetch` offline.
2. Show the table to the user. A worktree is listed when its branch is merged into `origin/main`, its upstream is gone, or its last commit is older than 14 days (`--days N`).
3. Skipped on purpose, never override: the main checkout, the current worktree, tracked changes, unpushed commits, a process running from inside the worktree.
4. Only after the user's go: `scripts/worktree_gc.sh --apply`, adding `--remove` for merged or deleted branches (an idle one is never removed). Only `.venv`, `venv`, `depictio/cli/.venv`, `node_modules`, `depictio/viewer/node_modules` and `data/` are deleted.
5. Report the space reclaimed.

Instance data of a worktree stack lives in `data/<compose project>/`; a stack started with `/new-worktree` seeds the iris example only, so it stays small.
