# Service Logs Viewer

View logs from depictio services.

## Instructions

Check logs for the specified service:

1. **Available services**:
   - `api` or `backend` - FastAPI backend logs
   - `dash` or `frontend` - Dash frontend logs
   - `mongo` or `mongodb` - MongoDB logs
   - `redis` - Redis cache logs
   - `minio` or `s3` - MinIO storage logs
   - `celery` or `worker` - Celery worker logs
   - `all` - All services

2. **Commands**:
   ```bash
   # View recent logs
   docker compose -f docker-compose.dev.yaml logs --tail=100 <service>

   # Follow logs in real-time
   docker compose -f docker-compose.dev.yaml logs -f <service>
   ```

3. **Analyze logs**:
   - Look for ERROR or WARNING messages
   - Check for stack traces
   - Identify connection issues
   - Note timing and performance issues

## Service Mapping

| Alias | Docker Service |
|-------|---------------|
| api, backend | backend |
| dash, frontend | dash |
| mongo, mongodb | mongodb |
| redis | redis |
| minio, s3 | minio |
| celery, worker | celery_worker |

## Usage

`/logs <service>` - View last 100 lines of service logs
`/logs <service> <lines>` - View specified number of lines
`/logs <service> errors` - Filter for errors only

$ARGUMENTS
