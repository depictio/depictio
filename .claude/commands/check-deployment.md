# Deployment Render Check

Verify that every dashboard on a live Depictio deployment is up and that each component on
every dashboard and tab actually renders. Run this after a deployment.

## Instructions

1. **Parse arguments** to pick the target:
   - `demo` -> `demo.depictio.embl.org`
   - `dev` -> `dev.demo.depictio.embl.org`
   - no args -> run both, `demo` first
   - anything else -> treat it as an explicit host (works for a local stack too)

2. **Run the checker** with the project Python. It uses `rich` for its tables, so the system
   `python3` will not have the dependency:

   ```bash
   ./depictio-venv-dash-v3/bin/python scripts/check_deployment.py --host <host>
   # or
   uv run python scripts/check_deployment.py --host <host>
   ```

   Useful flags:
   - `--only <dashboard_id> ...` to narrow to specific dashboards (child tab ids work on their own)
   - `--json report.json` / `--markdown report.md` for machine-readable or paste-able output
   - `--strict` to exit 1 when any component fails (default exit is 0 unless the host is unreachable)
   - `--token-file <path>` to also cover private dashboards, see Auth below
   - `--dry-run` to list the dashboard families without probing
   - `--concurrency N` (default 4), keep it modest against a shared deployment

3. **Report back**, in this order:
   - Deployed version and the initialization health line, including any pending data collections
   - Total dashboards, components and failures
   - The failure buckets from the summary, since one missing data collection usually explains many
     component failures at once. Lead with the root cause, not the count.
   - Per-dashboard breakdown **only for dashboards that have failures**. Do not re-list the
     healthy ones beyond a count.

4. **If there are failures**, diagnose by verdict rather than restating the output:

   | Verdict | Meaning | Where to look |
   | --- | --- | --- |
   | `DC_NOT_REGISTERED` | The dashboard binds to a data collection id that the deployed project does not declare. Seed and dashboard drift. | Compare `depictio/api/v1/db_init_reference_datasets.py` `STATIC_IDS` against the deployed project. `depictio/tests/api/v1/test_reference_seed_dashboards.py` is the offline guard for this. |
   | `DC_NOT_INGESTED` | Declared but never materialised as a Delta table. | Ingestion did not run or did not complete. Cross-check the `[init]` pending list. |
   | `DC_NO_AGGREGATION` | Delta table exists but has no column specs. | Ingestion partially completed. |
   | `CARD_NO_VALUE` | Card returned HTTP 200 with a null value. Renders as a dash in the UI, no error shown. | Usually the same missing data collection as its neighbours. |
   | `COLUMN_MISSING` | Specs loaded but the column the control binds to is gone. | The control renders inert with no error. Schema drift. |
   | `EMPTY_RESULT` | Request succeeded but returned no rows or no figure data. | Warning, not necessarily a fault. Check whether empty is legitimate. |
   | `NOT_PROBED` | The component only reaches the API through an async compute job, which is not dispatched. Currently `coverage_track` only. | Warning. Nothing was verified, so do not read it as a pass. |
   | `PREPARING` | MultiQC still building after the retries. | Celery worker slow or down. Check `/monitoring/health`. |
   | `SERVICE_UNAVAILABLE` | 503, typically the JBrowse sidecar. | Check that service. |
   | `DASHBOARD_UNREADABLE` | The dashboard document itself would not load. | Worse than a component failure, lead with it. |

5. **If the host fails preflight**, say which of the two cases it is. The script distinguishes them:
   - a TLS error usually means the host is serving a default ingress certificate and is not routed
     to Depictio at all
   - an HTTP 200 that is not a Depictio status payload means something else is answering on that host

## Auth

The default run sends no `Authorization` header. Both EMBL deployments run in public mode, where
that is equivalent to the temporary-user session the browser creates, so the run reproduces what an
ordinary visitor sees. This is the right default: it is the experience being validated.

Pass `--token-file` only to also cover **private** dashboards, which switches enumeration to
`/dashboards/list_all`. Mint a token with `/depictio-embl-admin-login`, or directly:

```bash
NS=datasci-depictio-project-demo-dev
POD=$(kubectl -n $NS get pods -o name | grep -m1 depictio-backend | sed 's|pod/||')
kubectl -n $NS exec $POD -c depictio-backend -- python3 -c \
  "import yaml;print(yaml.safe_load(open('/app/depictio/.depictio/thomas.weber_config.yaml'))['user']['token']['access_token'])" \
  > /tmp/demo_admin_token
```

Note the on-pod file is `{username}_config.yaml`, not `admin_config.yaml`.

## What it checks, and what it does not

For each component it replays the same request the React viewer issues, dispatching on
`component_type` exactly as `packages/depictio-react-core/src/components/ComponentRenderer.tsx`
does, then judges the **payload**, not only the status code. That last part matters: broken cards
come back as HTTP 200 with null values, and a failing filter renders as a silently empty dropdown
with no error text on the page. Both are caught here and neither is visible by eyeballing the
dashboard.

Not covered:
- Async advanced-viz compute jobs (embedding, upset, complex heatmap, coverage track, sankey). For
  most kinds their `/advanced_viz/data` leg is still probed, which is the leg carrying the data
  dependency. `coverage_track` has no such leg and is reported `NOT_PROBED`.
- `phylogenetic` deliberately skips the data leg for its own `dc_id`: the tree comes from
  `/advanced_viz/phylogeny/{tree_dc_id}/newick` and that data collection has no Delta table by
  design, so probing it would report a failure the viewer never sees.
- Anything that only breaks in the browser, such as a bundle error or a JS crash. This is an API
  level check. If a dashboard passes here but still looks wrong, open it and inspect the console.

## Usage Examples

`/check-deployment` - check both demo and dev.demo

`/check-deployment demo` - check demo only

`/check-deployment dev` - check dev.demo only

`/check-deployment localhost:5080` - check a local stack (add `--scheme http`)

## Notes

- The script needs no browser. Its only dependency is `rich` (already pinned in `pyproject.toml`),
  so run it with the project interpreter, not the system `python3`.
- Every data collection is reported as tag plus id, because the tag is what you act on and the id
  is what you grep for. For a data collection the project no longer declares, the tag comes from the
  component's own `stored_metadata`, which is the only place it still exists.
- Exit codes: 0 = reachable, 1 = unreachable or preflight failed. Add `--strict` for 1 on any
  component failure, which is what a CI gate would use.
- Related: `/validate-dashboard` validates dashboard YAML offline, before deployment. This command
  is the online counterpart, after deployment.

$ARGUMENTS
