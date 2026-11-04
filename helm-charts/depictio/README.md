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
| `enableServiceLinks` | Inject the legacy Docker-link service environment variables into every pod. Keep `false`: on clusters with many Services the injected block overflows the process argument limit and the viewer's nginx entrypoint crashloops with `envsubst: Argument list too long` | `false` |

### Namespace parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace.create` | Create the Kubernetes namespace | `true` |
| `namespace.name` | Name of the Kubernetes namespace | `"datasci-depictio-project"` |

### Storage parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `storageClass` | Storage class to use for PVCs | `"standard"` |
| `persistence.mongo.size` | MongoDB PVC size | `1Gi` |
| `persistence.mongo.accessMode` | MongoDB PVC access mode | `ReadWriteOnce` |
| `persistence.s3.size` | Bundled S3 store PVC size (legacy key: `persistence.minio`) | `1Gi` |
| `persistence.s3.accessMode` | Bundled S3 store PVC access mode | `ReadWriteMany` |
| `persistence.screenshots.size` | Screenshots PVC size | `100Mi` |
| `persistence.screenshots.accessMode` | Screenshots PVC access mode | `ReadWriteMany` |
| `persistence.keys.size` | JWT keys PVC size | `1Mi` |
| `persistence.keys.accessMode` | JWT keys PVC access mode | `ReadWriteMany` |
| `persistence.config.size` | Config PVC size | `10Mi` |
| `persistence.config.accessMode` | Config PVC access mode | `ReadWriteMany` |
| `persistence.uploads.size` | Uploads PVC size | `5Gi` |
| `persistence.uploads.accessMode` | Uploads PVC access mode | `ReadWriteMany` |

### Secrets parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `secrets.s3RootUser` | S3 root access key (legacy key: `secrets.minioRootUser`) | `""` (release name) |
| `secrets.s3RootPassword` | S3 root secret key (legacy key: `secrets.minioRootPassword`) | `""` (random, kept across upgrades) |

These credentials are stored in the Kubernetes Secret named `<release-name>-depictio-secrets`
under the data keys `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` (legacy names kept on purpose:
the chart reads the generated password back through them on upgrade). Override them only if
custom values are required.

### Single sign-on (OpenID Connect)

Any OpenID Connect provider (Keycloak, Authentik, Microsoft Entra ID, Google, ...) can be added
under `oidc.providers`. The list is rendered as JSON into `DEPICTIO_AUTH_OIDC_PROVIDERS`.

```yaml
oidc:
  providers:
    - id: keycloak                 # [a-z0-9][a-z0-9_-]{0,31}, used in URLs
      label: "Sign in with SSO"    # button text
      enabled: true
      issuer: "https://idp.example.org/realms/example"
      scopes: ["openid", "email", "profile"]
      claims: {email: email, groups: groups, display_name: name, login: preferred_username}
```

Client credentials never go in `oidc.providers`. Put them in a values file kept out of the
repository (or an external secret manager); the chart stores them in the Secret and exposes
them as `DEPICTIO_AUTH_OIDC_<ID>_CLIENT_ID` / `_CLIENT_SECRET` (`<ID>` is the provider id,
upper-cased, `-` replaced by `_`):

```yaml
secrets:
  oidcClients:
    keycloak:
      clientId: "<client-id>"
      clientSecret: "<client-secret>"
```

Register this redirect URI at the identity provider:

```
https://<api-host>/depictio/api/v1/auth/oidc/<id>/callback
```

Related switches in `backend.env`: `DEPICTIO_AUTH_REGISTRATION_DISABLED` (SSO becomes login-only
for pre-provisioned accounts) and `DEPICTIO_AUTH_PASSWORD_LOGIN_DISABLED` (SSO-only mode, effective
only while at least one provider is enabled and configured). Optional provider keys (`discovery_url`,
`redirect_uri`, `assume_email_verified`, `token_endpoint_auth_method`, `authorize_params`,
`fetch_userinfo`, `sso_provider`) are described in `depictio/api/v1/configs/settings_models.py`.

**SAML is no longer supported.** The `DEPICTIO_AUTH_SAML_*` variables are ignored and the backend
logs an error naming each one with its OIDC replacement (for example `ATTRIBUTE_GROUPS` becomes
`claims.groups`). OIDC claim names can differ from SAML attribute names: check them against the
identity provider's mappers.

**Legacy Google keys (deprecated, removed in a later release).** `backend.env.DEPICTIO_AUTH_GOOGLE_OAUTH_ENABLED`
and `auth.DEPICTIO_AUTH_GOOGLE_OAUTH_CLIENT_ID` / `_CLIENT_SECRET` / `_REDIRECT_URI` still work and map onto
a provider with id `google`. The client secret is now carried by the Secret rather than the ConfigMap.
To migrate, declare a `google` entry in `oidc.providers` with its credentials in `secrets.oidcClients.google`;
an explicit `google` entry takes precedence over the legacy keys.

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

### Bundled S3 store parameters (`s3.*`)

The bundled object store is [SeaweedFS](https://github.com/seaweedfs/seaweedfs)
(`weed mini`). Set `s3.enabled: false` plus `s3.env.DEPICTIO_S3_PUBLIC_URL` (and
`s3.env.DEPICTIO_S3_ROOT_USER` / `DEPICTIO_S3_ROOT_PASSWORD`) to use any external S3
endpoint instead.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `s3.enabled` | Deploy the bundled S3 store | `true` |
| `s3.image.repository` | Object store image repository | `chrislusf/seaweedfs` |
| `s3.image.tag` | Object store image tag | `4.46` |
| `s3.image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `s3.resources` | Resource requests and limits | Check `values.yaml` |
| `s3.service.type` | Service type | `ClusterIP` |
| `s3.service.httpPort` | S3 API port | `9000` |
| `s3.service.adminPort` | SeaweedFS admin UI port (only when `adminUI.enabled`) | `23646` |
| `s3.adminUI.enabled` | Expose the admin UI (guarded by the root credentials) | `false` |
| `s3.s3ExternalUrl` | Public S3 URL for signature verification behind a proxy without `X-Forwarded-*` headers | `""` |
| `s3.extraArgs` | Extra `weed mini` flags | `[]` |
| `s3.env.DEPICTIO_S3_BUCKET` | Bucket name | `depictio-bucket` |
| `s3.env.DEPICTIO_S3_SERVICE_PORT` | In-cluster S3 port advertised to the app | `"9000"` |
| `s3.env.DEPICTIO_S3_PUBLIC_URL` | Public S3 URL (required when `s3.enabled: false`) | unset |
| `s3.ingress.separateRoute` | Split the S3 store out of the shared ingress so `/` auth settings do not affect it | `false` |
| `s3.ingress.annotations` | S3-specific ingress annotations; falls back to `ingress.annotations` | `{}` |
| `s3.ingress.labels` | S3-specific ingress labels; falls back to `ingress.labels` | `{}` |
| `s3.ingress.hosts` | Optional explicit host rules for the dedicated S3 ingress | `[]` |
| `s3.ingress.tls` | Optional TLS entries for the dedicated S3 ingress; falls back to `ingress.tls` | `[]` |
| `s3.httpRoute.annotations` / `s3.httpRoute.filters` | Gateway API HTTPRoute annotations and filters for the S3 route | `{}` / `[]` |
| `global.urlPattern.templates.s3` | Custom S3 host template when `global.urlPattern.type: custom` (legacy key: `templates.minio`) | `""` |

The ConfigMaps export both `DEPICTIO_S3_*` and the legacy `DEPICTIO_MINIO_*` variables, so an
older image pinned through `backend.image.tag` keeps working. The legacy copies will be dropped
in a later release.

#### Legacy `minio` keys

Values files written for earlier chart versions still work unchanged. The legacy keys are
read and merged over the new ones (legacy wins when both are set), and `helm install/upgrade`
prints a deprecation warning listing them:

| Legacy key | New key |
|------------|---------|
| `minio.*` | `s3.*` |
| `minio.env.DEPICTIO_MINIO_*` | `s3.env.DEPICTIO_S3_*` |
| `persistence.minio.*` | `persistence.s3.*` |
| `secrets.minioRootUser` / `secrets.minioRootPassword` | `secrets.s3RootUser` / `secrets.s3RootPassword` |
| `global.urlPattern.templates.minio` | `global.urlPattern.templates.s3` |

Kubernetes object names are intentionally unchanged, because renaming them would break
upgrades of live releases: the `<release>-minio` Deployment and Service (with the immutable
`app: minio` selector), the `<release>-minio-pvc` PVC (renaming would start the store on an
empty volume), the `<release>-minio-ingress` / `<release>-minio-httproute` routes, the public
host `<release>-minio.<domain>` (DNS, TLS and presigned URLs), and the Secret keys
`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`.

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
| `backend.ingress.separateRoute` | Split the API out of the shared ingress so `/` auth settings do not affect it | `false` |
| `backend.ingress.annotations` | Backend-specific ingress annotations; falls back to `ingress.annotations` | `{}` |
| `backend.ingress.labels` | Backend-specific ingress labels; falls back to `ingress.labels` | `{}` |
| `backend.ingress.hosts` | Optional explicit host rules for the dedicated backend ingress | `[]` |
| `backend.ingress.tls` | Optional TLS entries for the dedicated backend ingress; falls back to `ingress.tls` | `[]` |

### Frontend parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `viewer.replicas` | React viewer replica count | `1` |
| `viewer.image.repository` | Viewer image repository | `ghcr.io/depictio/depictio-viewer` |
| `viewer.image.tag` | Viewer image tag | Check `values.yaml` |
| `viewer.image.pullPolicy` | Viewer image pull policy | `Always` |
| `viewer.resources` | Viewer resource requests and limits | Check `values.yaml` |
| `viewer.service.type` | Viewer service type | `ClusterIP` |
| `viewer.service.httpPort` | Viewer HTTP service port | `80` |
| `viewer.service.httpsPort` | Viewer HTTPS service port | `443` |
| `viewer.service.targetPort` | Viewer container port (nginx) | `80` |

## Usage

After deploying the chart, you can access the Depictio application:

- If using ClusterIP (default), use port-forwarding to access the viewer service:

```bash
kubectl port-forward -n datasci-depictio-project service/depictio-viewer 8080:80
```

  Then visit <http://localhost:8080>

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
