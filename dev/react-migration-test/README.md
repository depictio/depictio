# React-migration test deploy

Throwaway kubernetes manifests to validate the new per-service images
(`depictio-api`, `depictio-worker`, `depictio-viewer`) end-to-end on a real
cluster, **without merging** the dash-removal PR.

This directory is intentionally not under `kubernetes/` or `helm-charts/` —
it bypasses the production chart entirely and ships only what's needed to
prove the three new images boot and talk to each other. Delete after the
proper Helm refactor lands.

## Prerequisites

1. **Push the test images.** From the GitHub Actions UI: Actions tab →
   *Build migration images (api / worker / viewer)* → **Run workflow** →
   branch `claude/remove-dash-1AKSZ` → version `<your-tag>` (e.g.
   `react-test-1`). This publishes:

   - `ghcr.io/depictio/depictio-api:<tag>` (and `:next`)
   - `ghcr.io/depictio/depictio-worker:<tag>` (and `:next`)
   - `ghcr.io/depictio/depictio-viewer:<tag>` (and `:next`)

2. **kubectl context** pointed at the target cluster (minikube / k3s /
   wherever).

3. **GHCR pull secret** in the target namespace if the images are private:
   ```bash
   kubectl create namespace depictio-react-test
   kubectl -n depictio-react-test create secret docker-registry ghcr-pull \
     --docker-server=ghcr.io \
     --docker-username=<gh-username> \
     --docker-password=<gh-pat-with-read:packages> \
     --docker-email=<email>
   ```

   If `ghcr.io/depictio` is public, skip — and remove the `imagePullSecrets`
   block from `manifests.yaml`.

## Apply

```bash
# Pick your image tag (must match what you pushed in step 1 above)
export IMAGE_TAG=react-test-1

# Substitute the tag and apply
sed "s|__IMAGE_TAG__|${IMAGE_TAG}|g" dev/react-migration-test/manifests.yaml \
  | kubectl apply -f -
```

## Access

```bash
# Viewer (nginx + React SPA)
kubectl -n depictio-react-test port-forward svc/depictio-viewer 5080:80
# → http://localhost:5080/dashboard-beta/

# Backend (FastAPI) — optional, the viewer proxies /depictio/api/ already
kubectl -n depictio-react-test port-forward svc/depictio-api 8058:8058
# → http://localhost:8058/docs

# MinIO console (optional)
kubectl -n depictio-react-test port-forward svc/minio 9001:9001
```

Default admin credentials are seeded by the API on first boot via
`db_init.py`: `admin@example.com` / `changeme`. Change them before any
non-throwaway use.

## What this DOES validate

- The three new images compile + boot in a cluster (not just locally)
- API ↔ Mongo, API ↔ Redis, Worker ↔ Redis, API/Worker ↔ MinIO networking
- nginx → API proxy for `/depictio/api/*` and `/static/*`
- WebSocket upgrade for `/depictio/api/v1/events/ws` (set
  `DEPICTIO_EVENTS_ENABLED=true` in the ConfigMap to exercise)
- React SPA renders `/dashboard-beta/`
- Screenshots: trigger one via the API, confirm file lands at
  `/app/depictio/api/static/screenshots/` inside the API pod

## What this DOES NOT validate

- Persistent storage (Mongo / Redis / MinIO all use `emptyDir` — data
  evaporates on pod restart)
- Real ingress / TLS (use `kubectl port-forward`)
- Production-grade resource limits, HPA, anti-affinity, etc.
- Helm chart correctness — that's a separate PR

## Tear down

```bash
kubectl delete namespace depictio-react-test
```
