# Service Logs Viewer

Read logs of the dev stack (`docker-compose.dev.yaml`). Only `docker logs` is allowed (CLAUDE.md); do not run other docker commands.

## Containers

| Alias | Container |
| --- | --- |
| api, backend | `depictio-backend` |
| viewer, frontend | `depictio-viewer-dev` (Vite; `depictio-viewer` under the `ci` profile) |
| mongo | `mongo` |
| redis | `redis` |
| s3, minio | `s3` |
| celery, worker | `depictio-celery-worker` |
| ingestion | `depictio-ingestion-worker` |
| flower | `depictio-flower` (`monitoring` profile) |

In a worktree, container names may carry the `COMPOSE_PROJECT_NAME` prefix; check `.env.instance` and the user's `docker ps` output.

## Commands

```bash
docker logs --tail 100 depictio-backend
docker logs --tail 500 depictio-backend 2>&1 | grep -iE "error|traceback|warning"
```

Summarise: errors and stack traces first, then connection problems and slow requests. Do not use `-f` (it never returns).

Usage: `/logs <service> [lines|errors]`

$ARGUMENTS
