{{/*
Expand the name of the chart.
*/}}
{{- define "depictio.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "depictio.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "depictio.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "depictio.labels" -}}
helm.sh/chart: {{ include "depictio.chart" . }}
{{ include "depictio.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "depictio.selectorLabels" -}}
app.kubernetes.io/name: {{ include "depictio.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
=============================================================================
URL Construction Helpers
=============================================================================
These helpers construct URLs based on the configured pattern type.

Supported pattern types:
- "prefix": {release}-{service}.{domain} (default, backward compatible)
  Example: demo-api.depictio.embl.org
- "subdomain": {subdomain}{service}.{release}.{domain}
  Example: dev.api.demo.depictio.embl.org
- "custom": Use custom template strings from values

Usage in templates:
  {{ include "depictio.apiUrl" . }}
  {{ include "depictio.frontendUrl" . }}
  {{ include "depictio.s3Url" . }}
*/}}

{{/*
Get the URL pattern type, defaulting to "prefix" for backward compatibility
*/}}
{{- define "depictio.urlPatternType" -}}
{{- .Values.global.urlPattern.type | default "prefix" }}
{{- end }}

{{/*
Get the subdomain prefix with proper formatting
Returns empty string if not set, or the subdomain with a trailing dot
*/}}
{{- define "depictio.subdomain" -}}
{{- if .Values.global.urlPattern.subdomain }}
{{- if hasSuffix "." .Values.global.urlPattern.subdomain }}
{{- .Values.global.urlPattern.subdomain }}
{{- else }}
{{- printf "%s." .Values.global.urlPattern.subdomain }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Construct the API URL based on the pattern type
*/}}
{{- define "depictio.apiUrl" -}}
{{- $patternType := include "depictio.urlPatternType" . }}
{{- $subdomain := include "depictio.subdomain" . }}
{{- if eq $patternType "prefix" }}
{{- printf "%s-api.%s" .Release.Name .Values.global.domain }}
{{- else if eq $patternType "subdomain" }}
{{- printf "%sapi.%s.%s" $subdomain .Release.Name .Values.global.domain }}
{{- else if eq $patternType "custom" }}
{{- if .Values.global.urlPattern.templates.api }}
{{- tpl .Values.global.urlPattern.templates.api . }}
{{- else }}
{{- printf "%s-api.%s" .Release.Name .Values.global.domain }}
{{- end }}
{{- else }}
{{- printf "%s-api.%s" .Release.Name .Values.global.domain }}
{{- end }}
{{- end }}

{{/*
Construct the frontend URL based on the pattern type
*/}}
{{- define "depictio.frontendUrl" -}}
{{- $patternType := include "depictio.urlPatternType" . }}
{{- $subdomain := include "depictio.subdomain" . }}
{{- if eq $patternType "prefix" }}
{{- printf "%s.%s" .Release.Name .Values.global.domain }}
{{- else if eq $patternType "subdomain" }}
{{- printf "%s%s.%s" $subdomain .Release.Name .Values.global.domain }}
{{- else if eq $patternType "custom" }}
{{- if .Values.global.urlPattern.templates.frontend }}
{{- tpl .Values.global.urlPattern.templates.frontend . }}
{{- else }}
{{- printf "%s.%s" .Release.Name .Values.global.domain }}
{{- end }}
{{- else }}
{{- printf "%s.%s" .Release.Name .Values.global.domain }}
{{- end }}
{{- end }}

{{/*
Construct the bundled S3 store URL based on the pattern type.
The generated host keeps the historical "-minio" / "minio." label: renaming it
would change the public S3 endpoint of live deployments (and invalidate
presigned URLs, DNS records and TLS certificates issued for it).
*/}}
{{- define "depictio.s3Url" -}}
{{- $patternType := include "depictio.urlPatternType" . }}
{{- $subdomain := include "depictio.subdomain" . }}
{{- $customTemplate := include "depictio.s3UrlTemplate" . }}
{{- if eq $patternType "prefix" }}
{{- printf "%s-minio.%s" .Release.Name .Values.global.domain }}
{{- else if eq $patternType "subdomain" }}
{{- printf "%sminio.%s.%s" $subdomain .Release.Name .Values.global.domain }}
{{- else if eq $patternType "custom" }}
{{- if $customTemplate }}
{{- tpl $customTemplate . }}
{{- else }}
{{- printf "%s-minio.%s" .Release.Name .Values.global.domain }}
{{- end }}
{{- else }}
{{- printf "%s-minio.%s" .Release.Name .Values.global.domain }}
{{- end }}
{{- end }}

{{/*
Construct the full HTTPS API URL
*/}}
{{- define "depictio.apiUrlWithProtocol" -}}
{{- printf "https://%s" (include "depictio.apiUrl" .) }}
{{- end }}

{{/*
Construct the full HTTPS frontend URL
*/}}
{{- define "depictio.frontendUrlWithProtocol" -}}
{{- printf "https://%s" (include "depictio.frontendUrl" .) }}
{{- end }}

{{/*
Construct the full HTTPS bundled S3 store URL
*/}}
{{- define "depictio.s3UrlWithProtocol" -}}
{{- printf "https://%s" (include "depictio.s3Url" .) }}
{{- end }}

{{/*
=============================================================================
S3 storage values (with legacy `minio` key compatibility)
=============================================================================
The storage block used to live under `minio:` (plus `persistence.minio`,
`secrets.minioRootUser/Password`, `global.urlPattern.templates.minio` and
`minio.env.DEPICTIO_MINIO_*`). The chart defaults now live under the new keys
only; the legacy keys are still read and, when set, override the defaults so
existing values files render the same manifests.

Precedence: legacy key > new key > chart default. The chart cannot tell an
explicit `s3.*` value from its own default, so when a legacy key is present it
wins. Do not set both; migrate to the new keys instead.

Usage (templates only receive strings from `include`, hence the fromYaml):
  {{- $s3 := include "depictio.s3" . | fromYaml }}
  {{ $s3.enabled }} / {{ $s3.service.httpPort }} / {{ index $s3.env "DEPICTIO_S3_BUCKET" }}
*/}}

{{/*
Recursively merge .src into .dst in place (maps are merged key by key, any
other value replaces the destination). Unlike sprig's mergeOverwrite this
also lets a `false` / empty value override a default, e.g. a legacy
`minio.enabled: false` over the default `s3.enabled: true`.
*/}}
{{- define "depictio.mergeInto" -}}
{{- $dst := .dst -}}
{{- range $key, $value := .src -}}
{{- if and (kindIs "map" $value) (kindIs "map" (index $dst $key)) -}}
{{- include "depictio.mergeInto" (dict "dst" (index $dst $key) "src" $value) -}}
{{- else -}}
{{- $_ := set $dst $key $value -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Effective S3 store values: `.Values.s3` with the legacy `.Values.minio` block
merged on top. Legacy `DEPICTIO_MINIO_*` env keys (in either block) are
renamed to `DEPICTIO_S3_*`, overriding the new-name value.
*/}}
{{- define "depictio.s3" -}}
{{- $s3 := deepCopy (.Values.s3 | default dict) -}}
{{- $legacy := .Values.minio | default dict -}}
{{- include "depictio.mergeInto" (dict "dst" $s3 "src" (deepCopy $legacy)) -}}
{{- $env := $s3.env | default dict -}}
{{- range $key, $value := deepCopy $env -}}
{{- if hasPrefix "DEPICTIO_MINIO_" $key -}}
{{- $_ := set $env (printf "DEPICTIO_S3_%s" (trimPrefix "DEPICTIO_MINIO_" $key)) $value -}}
{{- $_ := unset $env $key -}}
{{- end -}}
{{- end -}}
{{- $_ := set $s3 "env" $env -}}
{{- toYaml $s3 -}}
{{- end }}

{{/*
Effective S3 store PVC values: `persistence.s3` with the legacy
`persistence.minio` merged on top.
*/}}
{{- define "depictio.s3Persistence" -}}
{{- $persistence := deepCopy (.Values.persistence.s3 | default dict) -}}
{{- include "depictio.mergeInto" (dict "dst" $persistence "src" (deepCopy (.Values.persistence.minio | default dict))) -}}
{{- toYaml $persistence -}}
{{- end }}

{{/*
S3 root access key / secret key overrides: legacy secrets.minioRoot* win over
secrets.s3Root* when set. Both default to "" (generated / derived values).
*/}}
{{- define "depictio.s3RootUser" -}}
{{- default .Values.secrets.s3RootUser .Values.secrets.minioRootUser -}}
{{- end }}

{{- define "depictio.s3RootPassword" -}}
{{- default .Values.secrets.s3RootPassword .Values.secrets.minioRootPassword -}}
{{- end }}

{{/*
Custom URL template for the S3 host: legacy global.urlPattern.templates.minio
wins over global.urlPattern.templates.s3 when set.
*/}}
{{- define "depictio.s3UrlTemplate" -}}
{{- $templates := .Values.global.urlPattern.templates | default dict -}}
{{- default (index $templates "s3") (index $templates "minio") -}}
{{- end }}

{{/*
Non-empty when the release still uses a legacy `minio`-named values key.
Drives the deprecation warning in NOTES.txt.
*/}}
{{- define "depictio.s3LegacyKeys" -}}
{{- $found := list -}}
{{- if .Values.minio }}{{- $found = append $found "minio" -}}{{- end -}}
{{- if .Values.persistence.minio }}{{- $found = append $found "persistence.minio" -}}{{- end -}}
{{- if .Values.secrets.minioRootUser }}{{- $found = append $found "secrets.minioRootUser" -}}{{- end -}}
{{- if .Values.secrets.minioRootPassword }}{{- $found = append $found "secrets.minioRootPassword" -}}{{- end -}}
{{- $templates := .Values.global.urlPattern.templates | default dict -}}
{{- if index $templates "minio" }}{{- $found = append $found "global.urlPattern.templates.minio" -}}{{- end -}}
{{- $s3 := .Values.s3 | default dict -}}
{{- range $key, $_ := ($s3.env | default dict) -}}
{{- if hasPrefix "DEPICTIO_MINIO_" $key }}{{- $found = append $found (printf "s3.env.%s" $key) -}}{{- end -}}
{{- end -}}
{{- join ", " $found -}}
{{- end }}
