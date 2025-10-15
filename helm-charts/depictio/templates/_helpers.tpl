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
  {{ include "depictio.minioUrl" . }}
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
Construct the MinIO URL based on the pattern type
*/}}
{{- define "depictio.minioUrl" -}}
{{- $patternType := include "depictio.urlPatternType" . }}
{{- $subdomain := include "depictio.subdomain" . }}
{{- if eq $patternType "prefix" }}
{{- printf "%s-minio.%s" .Release.Name .Values.global.domain }}
{{- else if eq $patternType "subdomain" }}
{{- printf "%sminio.%s.%s" $subdomain .Release.Name .Values.global.domain }}
{{- else if eq $patternType "custom" }}
{{- if .Values.global.urlPattern.templates.minio }}
{{- tpl .Values.global.urlPattern.templates.minio . }}
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
Construct the full HTTPS MinIO URL
*/}}
{{- define "depictio.minioUrlWithProtocol" -}}
{{- printf "https://%s" (include "depictio.minioUrl" .) }}
{{- end }}
