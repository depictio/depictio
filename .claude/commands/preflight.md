# Preflight

Run the checks that CI has failed on after earlier pushes, before pushing.

`/preflight` — everything. `/preflight fast` — skip `pre-commit run --all-files`.

$ARGUMENTS

## Steps

1. `ruff format depictio && ruff check depictio`, `uv run --extra dev ty check depictio/models/`.
2. The registry tests, which fail when a change misses a place it must be declared:
   ```bash
   uv run --extra dev pytest -q \
     depictio/tests/models/test_template_conventions.py \
     depictio/tests/models/test_shipped_dashboard_yamls.py \
     depictio/tests/models/test_template_dc_order.py \
     depictio/tests/cli/utils/test_recipes.py \
     depictio/tests/api/v1/endpoints/backup_endpoints/test_backup_routes.py \
     depictio/tests/api/v1/tasks/test_backup_tasks.py \
     depictio/tests/unit/models/validation
   ```
3. `pre-commit run --all-files` (skipped by `fast`). Known unrelated failures in the cloud sandbox: `helm lint` (no `helm`), `shellcheck` on `nfcore_megatests_showcase/scripts/upload.sh` and `scripts/security_audit_compose.sh`. Do not fix those inside an unrelated PR.

## Checklist for what a test cannot see

- **New Mongo collection**: add it to the patched collection lists in the backup tests and the fixtures that enumerate collections.
- **New write route**: where a scope gate exists on the branch (`git grep scope_gate`), give the route a scope decision.
- **New component type**: register it everywhere the type map and the validation list it (`depictio/models/components/validation.py`, `depictio/models/models/dashboards.py`), and in the catalog snapshots.
- **New dashboard field**: `TabSnapshot` or a `SNAPSHOT_*_FIELDS` set (see CLAUDE.md, Dashboard Versioning).
- **UI change**: add a `data-testid` and select on that, never on `.mantine-*` classes or heading tags; check Playwright specs that touch the screen. A spec on a feature disabled in public/demo mode must skip on the auth mode, not only on `UNAUTHENTICATED_MODE`.
- **Template dashboards and recipes**: recipes carry `# INPUT SCHEMA:` and `# OUTPUT SCHEMA:` comments; dashboard text names no value from one run.

Report what ran, what failed, and which failures are environmental.
