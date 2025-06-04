# Depictio Helm Chart

This Helm chart deploys the Depictio application on a Kubernetes cluster.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- PV provisioner support in the underlying infrastructure (if persistence is enabled)

## Installing the Chart

To install the chart with the release name `depictio`:

```bash
helm install depictio ./depictio
```

The command deploys Depictio on the Kubernetes cluster with the default configuration. The [Parameters](#parameters) section lists the parameters that can be configured during installation.

## Uninstalling the Chart

To uninstall/delete the `depictio` deployment:

```bash
helm uninstall depictio
```

## Parameters

### Global parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `nameOverride` | String to partially override the chart name | `""` |
| `fullnameOverride` | String to fully override the chart name | `""` |

### Namespace parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace.create` | Create the Kubernetes namespace | `true` |
| `namespace.name` | Name of the Kubernetes namespace | `"datasci-depictio-project"` |

### Storage parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `storageClass` | Storage class to use for PVCs | `"standard"` |
| `persistence.src.enabled` | Enable source code persistence | `true` |
| `persistence.src.size` | Source code PVC size | `1Gi` |
| `persistence.src.accessMode` | Source code PVC access mode | `ReadWriteOnce` |
| `persistence.data.enabled` | Enable data persistence | `true` |
| `persistence.data.size` | Data PVC size | `5Gi` |
| `persistence.data.accessMode` | Data PVC access mode | `ReadWriteOnce` |
| `persistence.minioData.enabled` | Enable MinIO data persistence | `true` |
| `persistence.minioData.size` | MinIO data PVC size | `5Gi` |
| `persistence.minioData.accessMode` | MinIO data PVC access mode | `ReadWriteOnce` |
| `persistence.configs.enabled` | Enable configs persistence | `true` |
| `persistence.configs.size` | Configs PVC size | `1Gi` |
| `persistence.configs.accessMode` | Configs PVC access mode | `ReadWriteOnce` |
| `persistence.kubernetes.enabled` | Enable Kubernetes persistence | `true` |
| `persistence.kubernetes.size` | Kubernetes PVC size | `1Gi` |
| `persistence.kubernetes.accessMode` | Kubernetes PVC access mode | `ReadWriteOnce` |
| `persistence.mongo.enabled` | Enable MongoDB persistence | `true` |
| `persistence.mongo.size` | MongoDB PVC size | `5Gi` |
| `persistence.mongo.accessMode` | MongoDB PVC access mode | `ReadWriteOnce` |
| `persistence.minio.enabled` | Enable MinIO persistence | `true` |
| `persistence.minio.size` | MinIO PVC size | `10Gi` |
| `persistence.minio.accessMode` | MinIO PVC access mode | `ReadWriteOnce` |
| `persistence.exampleData.enabled` | Enable example data persistence | `true` |
| `persistence.exampleData.size` | Example data PVC size | `5Gi` |
| `persistence.exampleData.accessMode` | Example data PVC access mode | `ReadWriteOnce` |
| `persistence.screenshots.enabled` | Enable screenshots persistence | `true` |
| `persistence.screenshots.size` | Screenshots PVC size | `5Gi` |
| `persistence.screenshots.accessMode` | Screenshots PVC access mode | `ReadWriteOnce` |

### Secrets parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `secrets.minioRootUser` | MinIO root username | `"minio"` |
| `secrets.minioRootPassword` | MinIO root password | `"minio123"` |

These credentials are also stored in the Kubernetes Secret named `<release-name>-depictio-secrets`. Override them only if custom values are required.

### MongoDB parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mongo.enabled` | Enable MongoDB deployment | `true` |
| `mongo.image.repository` | MongoDB image repository | `mongo` |
| `mongo.image.tag` | MongoDB image tag | `latest` |
| `mongo.image.pullPolicy` | MongoDB image pull policy | `IfNotPresent` |
| `mongo.resources` | MongoDB resource requests and limits | Check `values.yaml` |
| `mongo.service.type` | MongoDB service type | `ClusterIP` |
| `mongo.service.port` | MongoDB service port | `27018` |
| `mongo.args` | MongoDB container arguments | `["mongod", "--dbpath", "/data/depictioDB", "--port", "27018"]` |

### MinIO parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `minio.enabled` | Enable MinIO deployment | `true` |
| `minio.image.repository` | MinIO image repository | `minio/minio` |
| `minio.image.tag` | MinIO image tag | `latest` |
| `minio.image.pullPolicy` | MinIO image pull policy | `IfNotPresent` |
| `minio.resources` | MinIO resource requests and limits | Check `values.yaml` |
| `minio.service.type` | MinIO service type | `ClusterIP` |
| `minio.service.httpPort` | MinIO HTTP service port | `9000` |
| `minio.service.consolePort` | MinIO console service port | `9001` |
| `minio.args` | MinIO container arguments | `["server", "/data", "--console-address", ":9001"]` |

### Backend parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `backend.enabled` | Enable backend deployment | `true` |
| `backend.image.repository` | Backend image repository | `registry.git.embl.de/tweber/depictio/depictio` |
| `backend.image.tag` | Backend image tag | `v0.0.3` |
| `backend.image.pullPolicy` | Backend image pull policy | `Always` |
| `backend.resources` | Backend resource requests and limits | Check `values.yaml` |
| `backend.service.type` | Backend service type | `ClusterIP` |
| `backend.service.httpPort` | Backend HTTP service port | `80` |
| `backend.service.httpsPort` | Backend HTTPS service port | `443` |
| `backend.service.targetPort` | Backend container port | `8058` |
| `backend.env` | Backend environment variables | Check `values.yaml` |
| `backend.command` | Backend container command | `["python", "/app/depictio/api/run.py"]` |
| `backend.securityContext.fsGroup` | Backend pod fsGroup | `2000` |

### Frontend parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `frontend.enabled` | Enable frontend deployment | `true` |
| `frontend.image.repository` | Frontend image repository | `registry.git.embl.de/tweber/depictio/depictio` |
| `frontend.image.tag` | Frontend image tag | `v0.0.3` |
| `frontend.image.pullPolicy` | Frontend image pull policy | `Always` |
| `frontend.resources` | Frontend resource requests and limits | Check `values.yaml` |
| `frontend.service.type` | Frontend service type | `ClusterIP` |
| `frontend.service.httpPort` | Frontend HTTP service port | `80` |
| `frontend.service.httpsPort` | Frontend HTTPS service port | `443` |
| `frontend.service.targetPort` | Frontend container port | `5080` |
| `frontend.env` | Frontend environment variables | Check `values.yaml` |
| `frontend.command` | Frontend container command | `["python", "/app/depictio/dash/app.py"]` |

## Usage

After deploying the chart, you can access the Depictio application:

- If using ClusterIP (default), use port-forwarding to access the frontend service:

```bash
kubectl port-forward -n datasci-depictio-project service/depictio-frontend 5080:80
```

  Then visit <http://localhost:5080>

- If using LoadBalancer, wait for the external IP to be provisioned and then access the service at that IP.

## Configuration

The default configuration works well for most deployments, but you can customize the chart by overriding its values in a separate YAML file:

```bash
helm install depictio ./depictio -f my-values.yaml
```

For a complete list of configurable parameters, refer to the `values.yaml` file or run:

```bash
helm show values ./depictio
```
