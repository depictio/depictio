# Bug Fix Workflow

1. **Reproduce.** Get the failing behaviour and the exact request or input. Backend logs: `/logs backend`. Data state: `/db`.
2. **Find the root cause**, not the symptom. `git log -p` on the touched file often shows the change that introduced it.
3. **Write a failing test first** (pytest under `depictio/tests/`, Playwright for viewer-only behaviour). Confirm it fails for the reason you diagnosed.
4. **Make the smallest fix** that makes the test pass. Check CLAUDE.md for invariants of the area (dashboard versioning, storage families, YAML to seed) before changing behaviour.
5. **Gates.** `/test`, `/quality`, `pre-commit run --all-files`.
6. **Commit** as `fix(<scope>): <subject>` with `/commit`.
