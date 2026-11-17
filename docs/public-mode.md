# Public mode: what visitors can and cannot do

`DEPICTIO_AUTH_PUBLIC_MODE=true` opens an instance to readers who do not sign
in. Every visitor is minted a **temporary user** (`is_temporary`), which passes
the API's authentication like any account. The routes that write shared content
therefore check *who* is calling, not only whether the call is authenticated.

## Closed to visitors

| Route | Visitor (temporary / anonymous) | Signed-in user | Admin |
| --- | --- | --- | --- |
| `POST /dashboards/import/yaml` | 403 | editor of the target project | yes |
| `POST /dashboards/import/json` | 403 | editor of the target project | yes |
| Project creation, project from a folder | 403 | 403 | yes |
| `POST /auth/me/tokens` (CLI token) | 403 | 403 | yes |
| User registration, account management | 403 | 403 | 403 |

The two import routes refuse visitors with
`"Dashboard import is disabled in public/demo mode"`. Anyone else goes through
the same rule as on a private instance: an admin imports into any project, a user
with editor (or owner) rights imports into that project, and a user who can only
read it (a public project grants viewers only) gets a 403. A published project
(`published_lock`) still refuses imports with a 409.

In the web UI the Import tab of the "New dashboard" dialog is disabled for
visitors and enabled for a signed-in user.

## Admins keep CLI access

An admin of a public instance does not have to switch public mode off to refresh
dashboards. Create a long-lived CLI token (Profile > CLI agents, admin only in
public mode), then run the usual commands against the instance:

```bash
depictio dashboard import dashboard.yaml --server admin_config.yaml --project <project_id>
```

```bash
depictio ingest DATA_DIR --server admin_config.yaml --template nf-core/ampliseq/latest
```

The instance stays reachable for anonymous readers during and after the import.
