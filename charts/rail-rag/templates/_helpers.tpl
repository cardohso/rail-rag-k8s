{{- define "rail-rag.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "rail-rag.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Labels every object carries. Usage: include "rail-rag.labels" (dict "root" . "component" "api") */}}
{{- define "rail-rag.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "rail-rag.selectorLabels" . }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end -}}

{{/* The immutable subset used by selectors and NetworkPolicies. */}}
{{- define "rail-rag.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rail-rag.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "rail-rag.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}

{{/* Non-root, no privilege escalation, no capabilities, read-only root filesystem. */}}
{{- define "rail-rag.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 1000
runAsGroup: 1000
fsGroup: 1000
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "rail-rag.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}

{{/* Shared by the HPA and the KEDA ScaledObject: fast up, slow down. */}}
{{- define "rail-rag.hpaBehavior" -}}
scaleUp:
  stabilizationWindowSeconds: 0
  policies:
    - {type: Pods, value: 2, periodSeconds: 15}
scaleDown:
  stabilizationWindowSeconds: {{ .Values.api.autoscaling.scaleDownStabilizationSeconds }}
  policies:
    - {type: Pods, value: 1, periodSeconds: 60}
{{- end }}
