#!/usr/bin/env bash
# Preflight check: confirms every file exists AND is at its final version
# (not a stale earlier paste). Run from anywhere:  bash scripts/preflight.sh
cd "$(dirname "$0")/.." || exit 1
fail=0

exists() { if [ -f "$1" ]; then echo "  OK    $1"; else echo "  FAIL  missing file: $1"; fail=1; fi; }
has()    { if grep -qF -- "$2" "$3" 2>/dev/null; then echo "  OK    $1"; else echo "  FAIL  $1   (expected '$2' in $3)"; fail=1; fi; }
hasnt()  { if grep -rqF -- "$2" $3 2>/dev/null; then echo "  FAIL  $1   (stale '$2' still in $3)"; fail=1; else echo "  OK    $1"; fi; }

SERVICES="inventory-service auth-service payment-service recommendation-service notification-service gateway"
HELM=infra/helm/incident-commander

echo "== Dockerfiles =="
for d in $(for s in $SERVICES; do echo services/$s; done) \
         backend/incident-engine backend/dependency-graph backend/rootcause-engine \
         backend/telemetry-consumer ml/anomaly-detection; do
  exists "$d/Dockerfile"
done

echo "== Synthetic services =="
for s in $SERVICES; do
  exists "services/$s/requirements.txt"
  has "$s: instrumentator compatible with FastAPI 0.115" "prometheus-fastapi-instrumentator==7.1.0" "services/$s/requirements.txt"
  has "$s: OTLP auth token"     "OTEL_AUTH_TOKEN" "services/$s/main.py"
  has "$s: deployment.id tag"   "deployment.id"   "services/$s/main.py"
  has "$s: /metrics exposed"    "Instrumentator"  "services/$s/main.py"
done
has "payment-service: Redis password" "REDIS_PASSWORD" services/payment-service/main.py
has "payment-service: DB password required" 'require_env("POSTGRES_PASSWORD")' services/payment-service/main.py

echo "== Reasoning engine =="
has   "incident-engine: API key required"   'require_env("API_KEY")' backend/incident-engine/main.py
has   "incident-engine: /accuracy"          "/accuracy"              backend/incident-engine/main.py
has   "incident-engine: /deployment-info"   "/deployment-info"       backend/incident-engine/main.py
has   "models: confirmed cause column"      "confirmed_root_cause"   backend/incident-engine/models.py
has   "models: predictions table"           "RootCausePrediction"    backend/incident-engine/models.py
has   "models: DB password required"        'require_env("POSTGRES_PASSWORD")' backend/incident-engine/models.py
has   "graph: discovers DB/cache edges"     "call_type"              backend/dependency-graph/builder.py
has   "dependency-graph: API key required"  'require_env("API_KEY")' backend/dependency-graph/main.py
has   "rootcause rules: live z-scores"      "latency_zscores"        backend/rootcause-engine/rules.py
hasnt "rootcause rules: hardcoded deps gone"       "INFRA_DEPENDENCIES"            backend/rootcause-engine/rules.py
hasnt "rootcause rules: hardcoded thresholds gone" "LATENCY_SUSPICION_THRESHOLDS"  backend/rootcause-engine/rules.py
has   "rootcause: configurable service URLs" 'os.getenv("INCIDENT_ENGINE_URL"' backend/rootcause-engine/main.py
has   "rootcause: Prometheus auth"          "PROMETHEUS_AUTH"        backend/rootcause-engine/main.py
has   "rootcause: persists predictions"     "/predictions"           backend/rootcause-engine/main.py
has   "telemetry-consumer: DB password required" 'require_env("POSTGRES_PASSWORD")' backend/telemetry-consumer/main.py
has   "detector: Prometheus auth"           "PROMETHEUS_AUTH"        ml/anomaly-detection/zscore_detector.py
has   "detector: sends API key"             "OUTGOING_HEADERS"       ml/anomaly-detection/zscore_detector.py
exists backend/notifier/main.py
exists backend/notifier/.env.example
hasnt "no hardcoded DB password in Python"  '"incident_pass"'        "backend services chaos"

echo "== Chaos tools =="
for f in traffic_generator kill_pod inject_latency stress_cpu log_deployment; do exists chaos/$f.py; done
has "chaos: log_deployment password required" 'require_env("POSTGRES_PASSWORD")' chaos/log_deployment.py
has "chaos: Python 3.13-safe asyncpg"         "asyncpg==0.30.0" chaos/requirements.txt

echo "== docker-compose + observability =="
exists infra/docker-compose.yml
has   "kafka: Kubernetes listener"        "PLAINTEXT_K8S"   infra/docker-compose.yml
has   "prometheus: basic auth enabled"    "web.config.file" infra/docker-compose.yml
has   "collector: receives auth token"    "OTEL_AUTH_TOKEN" infra/docker-compose.yml
hasnt "orphaned compose postgres removed" "container_name: postgres" infra/docker-compose.yml
hasnt "orphaned compose redis removed"    "container_name: redis"    infra/docker-compose.yml
exists infra/.env.example
exists infra/kind-config.yaml
has   "prometheus.yml: scrapes via NodePorts"    "host.docker.internal:30080" observability/prometheus.yml
has   "collector: bearer token auth"             "bearertokenauth"            observability/otel-collector-config.yaml
has   "collector: Kafka exporter"                "otel-traces"                observability/otel-collector-config.yaml
has   "grafana: Prometheus basic auth"           "basicAuth"                  observability/grafana/provisioning/datasources/prometheus.yml
exists observability/grafana/provisioning/datasources/tempo-loki.yml
exists observability/grafana/provisioning/dashboards/dashboard-provider.yml
exists observability/grafana/dashboards/services-overview.json
exists observability/tempo-config.yaml
exists observability/loki-config.yaml
exists observability/promtail-config.yaml
exists observability/prometheus-web-config.yml.example

echo "== Helm chart =="
exists $HELM/Chart.yaml
for t in microservice worker postgres-statefulset redis-deployment payment-service-hpa secrets; do
  exists $HELM/templates/$t.yaml
done
exists $HELM/values-customer.yaml.example
has "values: reasoning services deployed" "name: incident-engine" $HELM/values.yaml
has "values: workers defined"             "workers:"              $HELM/values.yaml
has "values: mesh policy flag"            "meshPolicy"            $HELM/values.yaml
has "values: customer identity"           "customer:"             $HELM/values.yaml
has "secrets example: redis"              "redisSecrets"          $HELM/values-secrets.yaml.example
has "secrets example: otel"               "otelSecrets"           $HELM/values-secrets.yaml.example
has "secrets example: prometheus"         "prometheusSecrets"     $HELM/values-secrets.yaml.example
has "secret template: prometheus"         "prometheus-password"   $HELM/templates/secrets.yaml
has "redis requires password"             "requirepass"           $HELM/templates/redis-deployment.yaml
has "services: OTLP token injected"       "otel-auth-token"       $HELM/templates/microservice.yaml
has "services: own ServiceAccount"        "serviceAccountName"    $HELM/templates/microservice.yaml

echo "== Dashboard =="
has "dashboard: sends API key"   "VITE_API_KEY"   apps/incident-dashboard/src/App.jsx
has "dashboard: accuracy panel"  "AccuracyPanel"  apps/incident-dashboard/src/App.jsx
has "service map: sends API key" "AUTH_HEADERS"   apps/incident-dashboard/src/ServiceMap.jsx
exists apps/incident-dashboard/package.json
exists apps/incident-dashboard/.env.local.example

echo "== Repo hygiene =="
has ".gitignore protects secrets" "values-secrets.yaml" .gitignore

echo
if [ "$fail" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "Some checks FAILED -- fix the FAIL lines above (usually a missing or stale file)."; fi
exit $fail
