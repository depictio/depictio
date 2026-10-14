# New Feature Workflow

Checklist for a change that spans backend, viewer and data. Commands, conventions and the versioning rules are in `/CLAUDE.md`; this only orders the steps. Skip the sections the change does not touch.

1. **Scope.** Read the code you will touch (`/arch <topic>`). Note which of models, API, CLI, viewer, dashboard YAML and docs are affected.
2. **Models** (`depictio/models/models/`). Add the Pydantic/Beanie model or field (`/pydantic-model`). A new dashboard field must be covered by `TabSnapshot` or a `SNAPSHOT_*_FIELDS` set in `versioning.py`. Gate: `uv run --extra dev ty check depictio/models/`.
3. **API** (`depictio/api/v1/endpoints/<domain>_endpoints/`). Add the route (`/api-endpoint`) with an auth dependency and a permission check. A route that mutates dashboard content must seed a baseline before the write and capture after it.
4. **CLI** (`depictio/cli/`) if ingestion or import changes. Smoke it with `/import-project` or `/import-template`.
5. **Viewer** (`depictio/viewer/`, `packages/`). Mantine 7, theme tokens only. Build with `cd depictio/viewer && pnpm run build`, run the relevant `pnpm run check:*`. Spawn `viewer-agent` for larger UI work.
6. **Dashboard YAML and seeds.** If you changed a `depictio/projects/**/dashboards/*.yaml`, regenerate the matching `.db_seeds/*.json` (`depictio/dev_scripts/generate_dashboard_seeds.py`, or the project's `generate_seeds.sh`), then `/validate-dashboard` and `/reseed` a running instance.
7. **Tests.** pytest next to the code (`depictio/tests/{api,models,cli,unit}`), plus a Playwright spec in `depictio/tests/e2e-playwright` for user-visible flows. `/test`.
8. **Verify in a real browser.** `/dev-stack` starts the server and publishes it; check the changed screen in light and dark with realistic data, then give the user the URL and say what you did and did not check. In a cloud sandbox this replaces pulling the branch to look at it. Fix what the user reports in the same session.
9. **Quality gates.** `/preflight` (ruff, `ty` on models, the registry tests, `pre-commit run --all-files`; mandatory after any code change).
10. **Docs.** After a significant PR, update depictio-docs and the Obsidian notes (CLAUDE.md, Documentation). Update `/CLAUDE.md` only if a convention changed.
11. **Commit** with `/commit` (or `/commit-push-pr`).
