{{/*
Expand the name of the chart.
*/}}
{{- define "depictio.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
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
Create the name of the namespace to use
*/}}
{{- define "depictio.namespaceName" -}}
{{- default .Values.namespace.name }}
{{- end }}

{{/*
Create mongo selector labels
*/}}
{{- define "depictio.mongo.selectorLabels" -}}
app: mongo
{{- end }}

{{/*
Create minio selector labels
*/}}
{{- define "depictio.minio.selectorLabels" -}}
app: minio
{{- end }}

{{/*
Create backend selector labels
*/}}
{{- define "depictio.backend.selectorLabels" -}}
app: depictio-backend
{{- end }}

{{/*
Create frontend selector labels
*/}}
{{- define "depictio.frontend.selectorLabels" -}}
app: depictio-frontend
{{- end }}